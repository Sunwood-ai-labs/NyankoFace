from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import stat
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from mcp.server.fastmcp.exceptions import ToolError

from .client import WriteResponseError, redact


SAFE_DENIAL = "Resource was not found or is not authorized"
ABANDONED_OPERATION_SECONDS = 300
OPERATION_HEARTBEAT_SECONDS = 30


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def effective_preview(preview: bool | None, dry_run: bool | None) -> bool:
    if preview is not None and dry_run is not None and preview != dry_run:
        raise ToolError("preview and dry_run must agree when both are provided")
    if dry_run is not None:
        return dry_run
    return True if preview is None else preview


@dataclass(frozen=True)
class WriteIdentity:
    subject: str
    tool: str
    method: str
    target: str


@dataclass(frozen=True)
class Claim:
    namespace: str
    operation_id: str | None = None
    replay: dict[str, Any] | None = None


class WriteSafetyStore:
    """Durable confirmation, idempotency, and non-secret audit state."""

    def __init__(self, path: Path, confirmation_ttl: int = 300, idempotency_ttl: int = 86_400):
        self.path = path
        self.fingerprint_key_path = path.with_name(f"{path.name}.hmac-key")
        self.confirmation_ttl = confirmation_ttl
        self.idempotency_ttl = idempotency_ttl
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def sensitive_fingerprint(self, value: Any) -> str:
        """Fingerprint confidential input without a reversible or raw digest."""
        key = self._fingerprint_key()
        return hmac.new(
            key,
            canonical_json(value).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _fingerprint_key(self) -> bytes:
        if self.fingerprint_key_path.exists() or self.fingerprint_key_path.is_symlink():
            return self._read_fingerprint_key()
        temporary = self.fingerprint_key_path.with_name(
            f".{self.fingerprint_key_path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
        )
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        try:
            value = secrets.token_bytes(32)
            offset = 0
            while offset < len(value):
                written = os.write(descriptor, value[offset:])
                if written <= 0:
                    raise RuntimeError("sensitive fingerprint key write failed")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            # Publishing a fully-written inode by hard link is atomic and never
            # replaces a key won by another replica.
            try:
                os.link(temporary, self.fingerprint_key_path)
            except FileExistsError:
                pass
            if os.name != "nt":
                directory = os.open(self.fingerprint_key_path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)
        return self._read_fingerprint_key()

    def _read_fingerprint_key(self) -> bytes:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.fingerprint_key_path, flags)
        except OSError as exc:
            raise RuntimeError("sensitive fingerprint key must be a regular file") from exc
        try:
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode):
                raise RuntimeError("sensitive fingerprint key must be a regular file")
            if os.name != "nt":
                if details.st_uid != os.getuid() or details.st_mode & 0o077:
                    raise RuntimeError("sensitive fingerprint key ownership or mode is unsafe")
            chunks: list[bytes] = []
            remaining = 33
            while remaining:
                chunk = os.read(descriptor, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            key = b"".join(chunks)
        finally:
            os.close(descriptor)
        if len(key) != 32:
            raise RuntimeError("sensitive fingerprint key is invalid")
        return key

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS confirmations (
                    token_digest TEXT PRIMARY KEY,
                    subject TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    target TEXT NOT NULL,
                    payload_fingerprint TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    consumed_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS idempotency (
                    namespace TEXT PRIMARY KEY,
                    payload_fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at INTEGER NOT NULL,
                    request_id TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    target TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    result TEXT NOT NULL,
                    payload_fingerprint TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY,
                    namespace TEXT NOT NULL UNIQUE,
                    subject TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    target TEXT NOT NULL,
                    state TEXT NOT NULL,
                    result_json TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS legacy_unresolved_claims (
                    namespace TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    detected_at INTEGER NOT NULL,
                    resolved_at INTEGER
                );
                CREATE UNIQUE INDEX IF NOT EXISTS operations_running_target
                    ON operations(target) WHERE state = 'running';
                CREATE TRIGGER IF NOT EXISTS operations_unresolved_target_insert
                BEFORE INSERT ON operations
                WHEN NEW.state IN ('running', 'indeterminate', 'failed')
                BEGIN
                    SELECT RAISE(ABORT, 'target has an active or unresolved operation')
                    WHERE EXISTS (
                        SELECT 1 FROM operations
                        WHERE target = NEW.target
                          AND state IN ('running', 'indeterminate', 'failed')
                    );
                END;
            """)
            # Earlier builds stored every terminal result as ``complete``.
            # Reclassify their sanitized JSON before expiry cleanup can remove
            # an outcome that explicitly forbids retrying the mutation.
            legacy_rows = db.execute(
                """SELECT namespace, result_json FROM idempotency
                   WHERE status = 'complete' AND result_json IS NOT NULL""",
            ).fetchall()
            for row in legacy_rows:
                try:
                    result = json.loads(row["result_json"])
                except (TypeError, json.JSONDecodeError):
                    continue
                error = result.get("error") if isinstance(result, dict) else None
                if (
                    isinstance(result, dict)
                    and (
                        result.get("status") == "indeterminate"
                        or (isinstance(error, dict) and error.get("retry_safe") is False)
                    )
                ):
                    db.execute(
                        "UPDATE idempotency SET status = 'non_retryable' WHERE namespace = ?",
                        (row["namespace"],),
                    )
            # Pre-operation-schema claims cannot be mapped back from their
            # hashed namespace to a repository target. Preserve them as a
            # global fail-closed migration lock rather than permitting a
            # different key to duplicate an unknown upstream mutation.
            db.execute(
                """INSERT OR IGNORE INTO legacy_unresolved_claims
                   (namespace, status, detected_at, resolved_at)
                   SELECT i.namespace, i.status, ?, NULL
                   FROM idempotency AS i
                   LEFT JOIN operations AS o ON o.namespace = i.namespace
                   WHERE i.status IN ('pending', 'non_retryable')
                     AND o.operation_id IS NULL""",
                (int(time.time()),),
            )

    def issue_confirmation(self, identity: WriteIdentity, payload_hash: str) -> tuple[str, int]:
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = int(time.time())
        expires_at = now + self.confirmation_ttl
        with self._connect() as db:
            # Reap abandoned previews during normal preview traffic so the
            # durable table cannot grow without a later execution.
            db.execute("DELETE FROM confirmations WHERE expires_at < ?", (now,))
            db.execute(
                "INSERT INTO confirmations VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (digest, identity.subject, identity.tool, identity.target, payload_hash, expires_at),
            )
        return token, expires_at

    def claim(
        self,
        identity: WriteIdentity,
        payload_hash: str,
        confirmation: str,
        idempotency_key: str,
    ) -> Claim:
        if not confirmation or len(confirmation) > 512:
            raise ToolError("A valid, unexpired preview confirmation is required")
        if not idempotency_key or len(idempotency_key) > 255:
            raise ToolError("idempotency_key is required and must be at most 255 characters")
        now = int(time.time())
        token_digest = hashlib.sha256(confirmation.encode("utf-8")).hexdigest()
        namespace = fingerprint({
            "subject": identity.subject,
            "method": identity.method,
            "target": identity.target,
            "key": idempotency_key,
        })
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            legacy_lock = db.execute(
                """SELECT 1 FROM legacy_unresolved_claims
                   WHERE resolved_at IS NULL LIMIT 1""",
            ).fetchone()
            if legacy_lock:
                db.execute("ROLLBACK")
                raise ToolError(
                    "A legacy unresolved write claim requires operator reconciliation"
                )
            db.execute("DELETE FROM confirmations WHERE expires_at < ?", (now,))
            # Completed outcomes expire normally, but a stale pending claim may
            # mean the process died after Forgejo accepted the mutation. Keep
            # that namespace non-dispatchable instead of deleting the only
            # evidence that the upstream outcome is unknown.
            db.execute(
                """DELETE FROM idempotency
                   WHERE expires_at < ?
                     AND status NOT IN ('pending', 'non_retryable')""",
                (now,),
            )
            existing = db.execute(
                "SELECT payload_fingerprint, status, result_json FROM idempotency WHERE namespace = ?",
                (namespace,),
            ).fetchone()
            if existing:
                if existing["payload_fingerprint"] != payload_hash:
                    db.execute("COMMIT")
                    raise ToolError("Idempotency key was already used with a different payload")
                if existing["status"] == "pending":
                    operation = db.execute(
                        "SELECT operation_id, tool, target FROM operations WHERE namespace = ?",
                        (namespace,),
                    ).fetchone()
                    db.execute("COMMIT")
                    if operation is None:
                        raise ToolError("An identical write is already in progress")
                    operation_id = operation["operation_id"]
                    return Claim(namespace, operation_id=operation_id, replay={
                        "status": "running",
                        "tool": operation["tool"],
                        "target": operation["target"],
                        "operation_id": operation_id,
                        "operation_uri": f"nyankoface://operations/{operation_id}",
                    })
                db.execute("COMMIT")
                return Claim(namespace, replay=json.loads(existing["result_json"]))

            confirmation_row = db.execute(
                "SELECT * FROM confirmations WHERE token_digest = ?",
                (token_digest,),
            ).fetchone()
            bound = confirmation_row and all((
                confirmation_row["subject"] == identity.subject,
                confirmation_row["tool"] == identity.tool,
                confirmation_row["target"] == identity.target,
                confirmation_row["payload_fingerprint"] == payload_hash,
                confirmation_row["expires_at"] >= now,
                confirmation_row["consumed_at"] is None,
            ))
            if not bound:
                db.execute("ROLLBACK")
                raise ToolError("A valid, unexpired preview confirmation is required")
            db.execute(
                "UPDATE confirmations SET consumed_at = ? WHERE token_digest = ?",
                (now, token_digest),
            )
            # A terminal idempotency reservation may have expired while its
            # operation remains useful audit history. Archive only that
            # operation's internal namespace so the configured key can be
            # reused without deleting the old operation resource.
            db.execute(
                """UPDATE operations
                   SET namespace = namespace || ':expired:' || operation_id
                   WHERE namespace = ?
                     AND state NOT IN ('running', 'indeterminate', 'failed')""",
                (namespace,),
            )
            operation_id = str(uuid.uuid4())
            try:
                db.execute(
                    "INSERT INTO operations VALUES (?, ?, ?, ?, ?, 'running', NULL, ?, ?)",
                    (operation_id, namespace, identity.subject, identity.tool,
                     identity.target, now, now),
                )
            except sqlite3.IntegrityError:
                db.execute("ROLLBACK")
                with self._connect() as lookup:
                    running = lookup.execute(
                        """SELECT operation_id FROM operations
                           WHERE target = ?
                             AND state IN ('running', 'indeterminate', 'failed')""",
                        (identity.target,),
                    ).fetchone()
                suffix = (
                    f" at nyankoface://operations/{running['operation_id']}"
                    if running else ""
                )
                raise ToolError(
                    "Another operation for this target is active or unresolved; inspect its operation resource"
                    f"{suffix} before retrying"
                ) from None
            db.execute(
                "INSERT INTO idempotency VALUES (?, ?, 'pending', NULL, ?, ?)",
                (namespace, payload_hash, now, now + self.idempotency_ttl),
            )
            db.execute("COMMIT")
        return Claim(namespace, operation_id=operation_id)

    def complete(self, namespace: str, result: dict[str, Any]) -> bool:
        safe_result = redact(result)
        error = safe_result.get("error")
        non_retryable = (
            safe_result.get("status") == "indeterminate"
            or (isinstance(error, dict) and error.get("retry_safe") is False)
        )
        storage_status = "non_retryable" if non_retryable else "complete"
        with self._connect() as db:
            now = int(time.time())
            serialized = canonical_json(safe_result)
            db.execute("BEGIN IMMEDIATE")
            try:
                changed = db.execute(
                    """UPDATE operations
                       SET state = ?, result_json = ?, updated_at = ?
                       WHERE namespace = ? AND state = 'running'""",
                    (str(safe_result.get("status", "failed")), serialized, now, namespace),
                ).rowcount
                if changed != 1:
                    db.execute("ROLLBACK")
                    return False
                db.execute(
                    "UPDATE idempotency SET status = ?, result_json = ? WHERE namespace = ?",
                    (storage_status, serialized, namespace),
                )
                db.execute("COMMIT")
                return True
            except Exception:
                db.execute("ROLLBACK")
                raise

    def heartbeat(self, namespace: str) -> None:
        """Renew a running operation's durable lease from any MCP instance."""
        with self._connect() as db:
            changed = db.execute(
                "UPDATE operations SET updated_at = ? WHERE namespace = ? AND state = 'running'",
                (int(time.time()), namespace),
            ).rowcount
        if changed != 1:
            raise RuntimeError("operation lease was lost")

    def get_operation(self, subject: str, operation_id: str) -> dict[str, Any]:
        try:
            uuid.UUID(operation_id)
        except ValueError:
            raise ToolError(SAFE_DENIAL) from None
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM operations WHERE operation_id = ? AND subject = ?",
                (operation_id, subject),
            ).fetchone()
        if row is None:
            raise ToolError(SAFE_DENIAL)
        result = json.loads(row["result_json"]) if row["result_json"] else None
        return {
            "operation_id": row["operation_id"],
            "operation_uri": f"nyankoface://operations/{row['operation_id']}",
            "tool": row["tool"],
            "target": row["target"],
            "state": row["state"],
            "result": result,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def reconcile_operation(
        self, subject: str, operation_id: str, resolution: str,
    ) -> dict[str, Any]:
        if resolution not in {"applied", "not_applied"}:
            raise ToolError("resolution must be applied or not_applied")
        try:
            uuid.UUID(operation_id)
        except ValueError:
            raise ToolError(SAFE_DENIAL) from None
        now = int(time.time())
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT namespace, result_json FROM operations
                   WHERE operation_id = ? AND subject = ?
                     AND (state IN ('indeterminate', 'failed')
                          OR (state = 'running' AND updated_at <= ?))""",
                (operation_id, subject, now - ABANDONED_OPERATION_SECONDS),
            ).fetchone()
            if row is None:
                db.execute("ROLLBACK")
                raise ToolError("Only an unresolved operation can be reconciled")
            result = json.loads(row["result_json"]) if row["result_json"] else {}
            result["reconciliation"] = {
                "resolution": resolution,
                "reconciled_at": now,
            }
            serialized = canonical_json(result)
            db.execute(
                """UPDATE operations
                   SET state = 'reconciled', result_json = ?, updated_at = ?
                   WHERE operation_id = ?""",
                (serialized, now, operation_id),
            )
            db.execute("UPDATE idempotency SET status = 'complete', result_json = ? WHERE namespace = ?",
                       (serialized, row["namespace"]))
            db.execute("COMMIT")
        return {
            "operation_id": operation_id,
            "state": "reconciled",
            "resolution": resolution,
        }

    def resolve_legacy_claim(self, namespace: str) -> None:
        with self._connect() as db:
            changed = db.execute(
                "UPDATE legacy_unresolved_claims SET resolved_at = ? "
                "WHERE namespace = ? AND resolved_at IS NULL",
                (int(time.time()), namespace),
            ).rowcount
        if changed != 1:
            raise ToolError("Legacy claim was not found or was already resolved")

    def audit(
        self,
        identity: WriteIdentity,
        operation: str,
        result: str,
        payload_hash: str,
        request_id: str,
    ) -> None:
        with self._connect() as db:
            db.execute(
                """INSERT INTO audit_events
                   (occurred_at, request_id, subject, tool, target, operation, result, payload_fingerprint)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (int(time.time()), request_id, identity.subject, identity.tool,
                 identity.target, operation, result, payload_hash),
            )


class WriteCoordinator:
    def __init__(
        self,
        store: WriteSafetyStore,
        heartbeat_seconds: float = OPERATION_HEARTBEAT_SECONDS,
    ):
        self.store = store
        self.heartbeat_seconds = heartbeat_seconds

    async def _mutate_with_heartbeat(
        self, namespace: str, mutate: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        async def renew() -> None:
            while True:
                await asyncio.sleep(self.heartbeat_seconds)
                self.store.heartbeat(namespace)

        mutation = asyncio.create_task(mutate())
        heartbeat = asyncio.create_task(renew())
        try:
            done, _ = await asyncio.wait(
                {mutation, heartbeat}, return_when=asyncio.FIRST_COMPLETED,
            )
            if heartbeat in done:
                await heartbeat
                raise RuntimeError("operation heartbeat stopped unexpectedly")
            return await mutation
        finally:
            mutation.cancel()
            heartbeat.cancel()
            await asyncio.gather(mutation, heartbeat, return_exceptions=True)

    async def run(
        self,
        *,
        identity: WriteIdentity,
        payload: dict[str, Any],
        preview: bool | None,
        dry_run: bool | None,
        confirmation: str,
        idempotency_key: str,
        authorize: Callable[[], Awaitable[None]],
        mutate: Callable[[], Awaitable[dict[str, Any]]],
        sensitive_payload: bool = False,
        preview_details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload_hash = (
            self.store.sensitive_fingerprint(payload)
            if sensitive_payload else fingerprint(payload)
        )
        request_id = str(uuid.uuid4())
        operation = "preview" if effective_preview(preview, dry_run) else "execute"
        try:
            # Positive repository authorization is deliberately never cached.
            await authorize()
            if operation == "preview":
                token, expires_at = self.store.issue_confirmation(identity, payload_hash)
                result = {
                    "status": "preview",
                    "tool": identity.tool,
                    "target": identity.target,
                    "payload_fingerprint": payload_hash,
                    "confirmation": token,
                    "confirmation_expires_at": expires_at,
                    "request_id": request_id,
                }
                if preview_details is not None:
                    result["change"] = redact(preview_details)
                self.store.audit(identity, operation, "allowed", payload_hash, request_id)
                return result

            claim = self.store.claim(
                identity, payload_hash, confirmation, idempotency_key,
            )
            if claim.replay is not None:
                replay = {**claim.replay, "replayed": True}
                self.store.audit(identity, operation, "replayed", payload_hash, request_id)
                return replay

            try:
                mutation = redact(await self._mutate_with_heartbeat(claim.namespace, mutate))
                result = {
                    "status": "completed",
                    "tool": identity.tool,
                    "target": identity.target,
                    "operation_id": claim.operation_id,
                    "operation_uri": f"nyankoface://operations/{claim.operation_id}",
                    "result": mutation,
                    "request_id": request_id,
                    "replayed": False,
                }
            except asyncio.CancelledError:
                # Cancellation can arrive after the upstream accepted the write.
                # Persist the unknown outcome synchronously before propagating it,
                # so the same idempotency namespace can never dispatch it again.
                result = self._indeterminate(identity, request_id, claim.operation_id)
                self.store.complete(claim.namespace, result)
                self.store.audit(identity, operation, result["status"], payload_hash, request_id)
                raise
            except WriteResponseError as exc:
                # The upstream returned a definite sanitized response. Preserve
                # that distinction instead of misreporting a transport-unknown
                # outcome, while still completing the idempotency record.
                result = {
                    "status": "rejected" if exc.retry_safe else "failed",
                    "tool": identity.tool,
                    "target": identity.target,
                    "operation_id": claim.operation_id,
                    "operation_uri": f"nyankoface://operations/{claim.operation_id}",
                    "error": {
                        "code": exc.code,
                        "message": str(exc),
                        "retry_safe": exc.retry_safe,
                    },
                    "request_id": request_id,
                    "replayed": False,
                }
            except Exception:
                # A timeout or disconnect has an unknown commit outcome. Persist the
                # terminal safe result so a retry can never duplicate the mutation.
                result = self._indeterminate(identity, request_id, claim.operation_id)
            if not self.store.complete(claim.namespace, result):
                raise ToolError(
                    "Operation lease was lost; inspect the operation resource before retrying"
                )
            self.store.audit(identity, operation, result["status"], payload_hash, request_id)
            return result
        except ToolError:
            try:
                self.store.audit(identity, operation, "denied", payload_hash, request_id)
            except Exception:
                pass
            raise
        except Exception:
            try:
                self.store.audit(identity, operation, "failed", payload_hash, request_id)
            except Exception:
                pass
            raise ToolError("NyankoFace write safety service is temporarily unavailable") from None

    @staticmethod
    def _indeterminate(
        identity: WriteIdentity, request_id: str, operation_id: str | None,
    ) -> dict[str, Any]:
        return {
            "status": "indeterminate",
            "tool": identity.tool,
            "target": identity.target,
            "operation_id": operation_id,
            "operation_uri": f"nyankoface://operations/{operation_id}",
            "error": {"code": "upstream_outcome_unknown", "retry_safe": False},
            "request_id": request_id,
            "replayed": False,
        }


if __name__ == "__main__":
    if len(sys.argv) != 5 or sys.argv[1] != "resolve-legacy" or sys.argv[4] != "VERIFIED":
        raise SystemExit("usage: write_safety.py resolve-legacy DATABASE NAMESPACE VERIFIED")
    WriteSafetyStore(Path(sys.argv[2])).resolve_legacy_claim(sys.argv[3])
