from __future__ import annotations

import errno
import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .client import SLUG


TOKEN_AUDIENCE = "nyankoface-api-v1"
DEFAULT_TTL_SECONDS = 30 * 24 * 60 * 60
MAX_TTL_SECONDS = 90 * 24 * 60 * 60
MAX_TOKEN_EXPIRY = 253_402_300_799  # 9999-12-31T23:59:59Z
REAUTH_MAX_AGE_SECONDS = 300
DECLARED_SCOPES = frozenset({
    "catalog:read", "repos:read", "issues:read", "issues:write",
    "spaces:read", "spaces:write", "spaces:run",
    "pages:read", "pages:write", "pages:deploy",
    "pipelines:read", "pipelines:write", "metrics:read",
    "variables:write", "secrets:write",
})
MUTATING_SCOPES = frozenset({
    scope for scope in DECLARED_SCOPES
    if scope.endswith(":write") or scope in {"spaces:run", "pages:deploy"}
})
SERVICE_ACCOUNT_ID_PATTERN = re.compile(r"[A-Za-z0-9:_.-]{1,128}\Z")


class LifecycleError(ValueError):
    """A stable, secret-free lifecycle failure."""


class LifecycleUnavailable(LifecycleError):
    """The lifecycle registry or its lock cannot currently be used."""


@dataclass(frozen=True)
class AdminContext:
    subject_id: str
    is_admin: bool
    reauthenticated_at: int


@dataclass(frozen=True)
class IssuedToken:
    token: str
    metadata: dict[str, Any]


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def parse_token_expiry(value: Any) -> int:
    """Accept only bounded JSON integers as credential expiry timestamps."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise LifecycleError("invalid token expiry")
    if value < 1 or value > MAX_TOKEN_EXPIRY:
        raise LifecycleError("invalid token expiry")
    return value


def validate_governance_identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not value or not value.isprintable():
        raise LifecycleError(f"invalid {name}")


def validate_service_account_identifier(name: str, value: str) -> None:
    if (
        not isinstance(value, str)
        or value in {".", ".."}
        or SERVICE_ACCOUNT_ID_PATTERN.fullmatch(value) is None
    ):
        raise LifecycleError(f"invalid {name}")


def public_token_metadata(record: dict[str, Any]) -> dict[str, Any]:
    """Return metadata safe for normal APIs, logs, traces and audit."""
    return {
        key: value
        for key, value in record.items()
        if key not in {"token_sha256", "forgejo_token_file"}
    }


class TokenLifecycleStore:
    """Atomic file-backed token and subject lifecycle backend.

    Plaintext credentials exist only in the return value of ``issue`` and
    ``rotate``. The registry contains only SHA-256 digests and non-secret
    metadata. A lock file serializes writers across processes; an atomic
    replace prevents partial registries.
    """

    def __init__(
        self,
        registry_path: Path,
        audit_path: Path | None = None,
        registry_reader_gid: int | None = None,
    ):
        self.registry_path = registry_path
        self.audit_path = audit_path or registry_path.with_suffix(".audit.jsonl")
        self.lock_path = registry_path.with_suffix(registry_path.suffix + ".lock")
        if registry_reader_gid is None:
            configured_gid = os.getenv("NYANKOFACE_MCP_REGISTRY_READER_GID", "").strip()
            try:
                registry_reader_gid = int(configured_gid) if configured_gid else None
            except ValueError as exc:
                raise LifecycleError("invalid registry reader group") from exc
        if registry_reader_gid is not None and registry_reader_gid <= 0:
            raise LifecycleError("invalid registry reader group")
        self.registry_reader_gid = registry_reader_gid
        self._thread_lock = threading.Lock()

    @contextmanager
    def _locked(self, timeout: float = 5.0) -> Iterator[None]:
        deadline = time.monotonic() + timeout
        try:
            self._mkdir_durable(self.registry_path.parent)
            self._prepare_registry_directory()
        except OSError as exc:
            raise LifecycleUnavailable("token store is unavailable") from exc
        with self._thread_lock:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
                try:
                    while True:
                        try:
                            self._try_advisory_lock(fd)
                            break
                        except OSError as exc:
                            if time.monotonic() >= deadline:
                                raise LifecycleUnavailable("token store is busy") from exc
                            time.sleep(0.01)
                    os.ftruncate(fd, 0)
                    os.write(fd, f"{os.getpid()}\n".encode())
                    os.fsync(fd)
                    yield
                finally:
                    try:
                        self._release_advisory_lock(fd)
                    finally:
                        os.close(fd)
            except LifecycleUnavailable:
                raise
            except OSError as exc:
                raise LifecycleUnavailable("token store is unavailable") from exc

    def _prepare_registry_directory(self) -> None:
        if self.registry_reader_gid is None:
            return
        if os.name == "nt" or not hasattr(os, "chown"):
            return
        try:
            directory = self.registry_path.parent
            stat_result = directory.stat()
            effective_uid = os.geteuid() if hasattr(os, "geteuid") else stat_result.st_uid
            if stat_result.st_uid != effective_uid or stat_result.st_gid != self.registry_reader_gid:
                # Compose may bind-mount a directory created by the operator.
                # The isolated writer takes ownership with its narrowly scoped
                # CHOWN capability, then exposes only group read/traverse.
                os.chown(directory, effective_uid, self.registry_reader_gid)
            os.chmod(directory, (stat_result.st_mode & 0o700) | 0o750)
        except OSError as exc:
            raise LifecycleUnavailable("registry directory cannot grant MCP read access") from exc

    @staticmethod
    def _try_advisory_lock(fd: int) -> None:
        """Acquire a process-owned lock that the OS releases after termination."""
        os.lseek(fd, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt

            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
                os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _release_advisory_lock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)

    def _read(self, *, strict_schema: bool = True) -> dict[str, Any]:
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"version": 2, "subjects": [], "tokens": []}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LifecycleUnavailable("token store is unavailable") from exc
        if not isinstance(data, dict):
            raise LifecycleUnavailable("token store is unavailable")
        data.setdefault("version", 2)
        data.setdefault("subjects", [])
        data.setdefault("tokens", [])
        data.setdefault("audit_outbox", [])
        for collection in ("subjects", "tokens", "audit_outbox"):
            if not isinstance(data[collection], list) or not all(
                isinstance(item, dict) for item in data[collection]
            ):
                raise LifecycleUnavailable("token store is unavailable")
        if strict_schema:
            self._validate_registry_record_shapes(data)
        return data

    @staticmethod
    def _validate_registry_record_shapes(data: dict[str, Any]) -> None:
        """Reject malformed persisted fields before lifecycle code consumes them."""

        def invalid() -> None:
            raise LifecycleUnavailable("token store is unavailable")

        def validate_record(
            record: dict[str, Any],
            *,
            required_fields: tuple[str, ...] = (),
            string_fields: tuple[str, ...] = (),
            integer_fields: tuple[str, ...] = (),
            nullable_integer_fields: tuple[str, ...] = (),
            boolean_fields: tuple[str, ...] = (),
            string_list_fields: tuple[str, ...] = (),
            string_map_fields: tuple[str, ...] = (),
        ) -> None:
            if any(field not in record for field in required_fields):
                invalid()
            for field in string_fields:
                if field in record and not isinstance(record[field], str):
                    invalid()
            for field in integer_fields:
                value = record.get(field)
                if field in record and (isinstance(value, bool) or not isinstance(value, int)):
                    invalid()
            for field in nullable_integer_fields:
                value = record.get(field)
                if field in record and value is not None and (
                    isinstance(value, bool) or not isinstance(value, int)
                ):
                    invalid()
            for field in boolean_fields:
                if field in record and not isinstance(record[field], bool):
                    invalid()
            for field in string_list_fields:
                value = record.get(field)
                if field in record and (
                    not isinstance(value, list)
                    or any(not isinstance(item, str) for item in value)
                ):
                    invalid()
            for field in string_map_fields:
                value = record.get(field)
                if field in record and (
                    not isinstance(value, dict)
                    or any(
                        not isinstance(key, str) or not isinstance(item, str)
                        for key, item in value.items()
                    )
                ):
                    invalid()

        for subject in data["subjects"]:
            validate_record(
                subject,
                required_fields=(
                    "subject_id", "subject_type", "enabled", "forgejo_user_id",
                    "forgejo_token_file", "allowed_scopes", "repository_permissions",
                    "mapping_version",
                ),
                string_fields=(
                    "subject_id", "subject_type", "forgejo_token_file", "created_by",
                ),
                integer_fields=("forgejo_user_id", "mapping_version", "created_at"),
                boolean_fields=("enabled",),
                string_list_fields=("allowed_scopes",),
                string_map_fields=("repository_permissions",),
            )
        for token in data["tokens"]:
            validate_record(
                token,
                required_fields=(
                    "token_id", "token_sha256", "client_id", "subject_id", "subject_type",
                    "audience", "scopes", "repositories", "mapping_version", "created_at",
                    "expires_at", "revoked_at",
                ),
                string_fields=(
                    "token_id", "token_sha256", "client_id", "subject_id",
                    "subject_type", "audience", "revocation_reason", "rotated_from",
                ),
                integer_fields=("mapping_version", "created_at", "expires_at"),
                nullable_integer_fields=("revoked_at",),
                string_list_fields=("scopes", "repositories"),
            )

    def _write(self, data: dict[str, Any]) -> None:
        name: str | None = None
        try:
            self._mkdir_durable(self.registry_path.parent)
            handle, name = tempfile.mkstemp(
                prefix=f".{self.registry_path.name}.", dir=self.registry_path.parent, text=True
            )
            try:
                with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                    json.dump(data, stream, ensure_ascii=False, indent=2, sort_keys=True)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                if self.registry_reader_gid is None:
                    os.chmod(name, 0o600)
                else:
                    process_group_matches = (
                        hasattr(os, "getegid") and os.getegid() == self.registry_reader_gid
                    )
                    if os.name != "nt" and hasattr(os, "chown") and not process_group_matches:
                        try:
                            os.chown(name, -1, self.registry_reader_gid)
                        except OSError as exc:
                            raise LifecycleUnavailable("registry cannot grant MCP read access") from exc
                    os.chmod(name, 0o640)
                try:
                    self._sync_registry_directory()
                except OSError as exc:
                    if not self._directory_sync_unsupported(exc):
                        raise
                os.replace(name, self.registry_path)
                try:
                    self._sync_registry_directory()
                except OSError:
                    # The replacement is already the process-visible authority.
                    # A preflight sync already rejected persistent storage errors;
                    # after this commit point the active credential must be
                    # returned so an operator cannot be locked out.
                    pass
            finally:
                if name and os.path.exists(name):
                    os.unlink(name)
        except LifecycleUnavailable:
            raise
        except OSError as exc:
            raise LifecycleUnavailable("token store is unavailable") from exc

    def _sync_registry_directory(self) -> None:
        self._sync_directory(self.registry_path.parent)

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        if os.name == "nt" or not hasattr(os, "O_DIRECTORY"):
            return
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    @staticmethod
    def _directory_sync_unsupported(exc: OSError) -> bool:
        return exc.errno in {errno.EINVAL, errno.ENOSYS, getattr(errno, "ENOTSUP", -1),
                            getattr(errno, "EOPNOTSUPP", -1)}

    def _mkdir_durable(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        # Repeat every parent-edge sync on every call. If a previous attempt
        # created the hierarchy but failed while syncing one ancestor, merely
        # checking which directories are now present would skip that durability
        # barrier forever on retry.
        cursor = directory
        while cursor.parent != cursor:
            try:
                self._sync_directory(cursor.parent)
            except OSError as exc:
                if not self._directory_sync_unsupported(exc):
                    raise
            cursor = cursor.parent

    @staticmethod
    def _audit_payload(
        event: str, actor: str, target: str, result: str, **fields: Any
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "audit_event_id": str(uuid.uuid4()),
            "event": event,
            "actor_subject_id": actor,
            "target_id": target,
            "result": result,
            "time": int(time.time()),
            **fields,
        }
        forbidden = {"token", "token_sha256", "forgejo_token_file"}
        if forbidden.intersection(payload):
            raise LifecycleError("unsafe audit payload")
        return payload

    def _append_audit(self, payload: dict[str, Any]) -> None:
        self._mkdir_durable(self.audit_path.parent)
        with self.audit_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            self._sync_directory(self.audit_path.parent)
        except OSError as exc:
            if not self._directory_sync_unsupported(exc):
                raise

    def _repair_audit_tail(self) -> None:
        """Discard an unterminated JSONL fragment before retrying outbox delivery."""
        try:
            with self.audit_path.open("r+b") as stream:
                stream.seek(0, os.SEEK_END)
                size = stream.tell()
                if size == 0:
                    return
                stream.seek(-1, os.SEEK_END)
                if stream.read(1) == b"\n":
                    return
                stream.seek(0)
                contents = stream.read()
                last_complete = contents.rfind(b"\n")
                stream.truncate(last_complete + 1 if last_complete >= 0 else 0)
                stream.flush()
                os.fsync(stream.fileno())
        except FileNotFoundError:
            return

    def _audit_event_ids(self) -> set[str]:
        self._repair_audit_tail()
        try:
            lines = self.audit_path.read_bytes().splitlines()
        except FileNotFoundError:
            return set()
        event_ids: set[str] = set()
        for encoded_line in lines:
            try:
                line = encoded_line.decode("utf-8")
                event_id = json.loads(line).get("audit_event_id")
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                continue
            if event_id:
                event_ids.add(str(event_id))
        return event_ids

    def _commit_with_audit(self, data: dict[str, Any], payload: dict[str, Any]) -> None:
        """Atomically persist state plus a durable, secret-free audit outbox entry.

        Delivery to the JSONL audit sink is at-least-once and best effort. A sink
        failure never turns a successfully persisted mutation into a reported
        failure; the outbox is retried by the next mutation.
        """
        data.setdefault("audit_outbox", []).append(payload)
        self._write(data)
        try:
            delivered = self._audit_event_ids()
            for pending in data["audit_outbox"]:
                event_id = str(pending.get("audit_event_id", ""))
                if event_id not in delivered:
                    self._append_audit(pending)
                    delivered.add(event_id)
            data["audit_outbox"] = []
            self._write(data)
        except (OSError, LifecycleError):
            # The first atomic write is authoritative. Keep the outbox entry in
            # the registry so a later successful mutation can deliver it.
            return

    @staticmethod
    def _require_admin(context: AdminContext, now: int) -> None:
        if not context.is_admin:
            raise LifecycleError("administrator authorization is required")
        age = now - int(context.reauthenticated_at)
        if age < 0 or age > REAUTH_MAX_AGE_SECONDS:
            raise LifecycleError("fresh reauthentication is required")

    @staticmethod
    def _validate_scopes(scopes: list[str] | tuple[str, ...]) -> list[str]:
        if (
            not isinstance(scopes, (list, tuple))
            or not scopes
            or any(not isinstance(scope, str) for scope in scopes)
        ):
            raise LifecycleError("invalid token scopes")
        normalized = sorted(set(scopes))
        if not normalized or not set(normalized).issubset(DECLARED_SCOPES):
            raise LifecycleError("invalid token scopes")
        return normalized

    @staticmethod
    def _validate_repositories(repositories: list[str] | tuple[str, ...]) -> list[str]:
        normalized = sorted(set(repositories))
        for target in normalized:
            parts = target.split("/")
            if (
                len(parts) != 2
                or not all(SLUG.fullmatch(part) for part in parts)
                or any(part in {".", ".."} for part in parts)
            ):
                raise LifecycleError("invalid repository constraint")
        return normalized

    @staticmethod
    def _subject(data: dict[str, Any], subject_id: str) -> dict[str, Any] | None:
        return next((item for item in data["subjects"] if item.get("subject_id") == subject_id), None)

    def create_service_account(
        self,
        context: AdminContext,
        *,
        subject_id: str,
        forgejo_user_id: int,
        forgejo_token_file: str,
        allowed_scopes: list[str],
        repository_permissions: dict[str, str],
        now: int | None = None,
    ) -> dict[str, Any]:
        now = int(time.time()) if now is None else now
        self._require_admin(context, now)
        normalized_scopes = self._validate_scopes(allowed_scopes)
        validate_service_account_identifier("subject identifier", subject_id)
        repositories = self._validate_repositories(list(repository_permissions))
        if set(repository_permissions.values()) - {"read", "write", "admin"}:
            raise LifecycleError("invalid repository permission")
        if not subject_id or forgejo_user_id <= 0 or not forgejo_token_file:
            raise LifecycleError("invalid subject mapping")
        with self._locked():
            data = self._read()
            if self._subject(data, subject_id):
                raise LifecycleError("subject already exists")
            record = {
                "subject_id": subject_id,
                "subject_type": "service_account",
                "enabled": True,
                "forgejo_user_id": forgejo_user_id,
                "forgejo_token_file": forgejo_token_file,
                "allowed_scopes": normalized_scopes,
                "repository_permissions": {key: repository_permissions[key] for key in repositories},
                "mapping_version": 1,
                "created_at": now,
            }
            data["subjects"].append(record)
            self._commit_with_audit(data, self._audit_payload(
                "service_account.created", context.subject_id, subject_id, "success"
            ))
        return {key: value for key, value in record.items() if key != "forgejo_token_file"}

    def disable_service_account(
        self, context: AdminContext, subject_id: str, *, now: int | None = None
    ) -> dict[str, Any]:
        now = int(time.time()) if now is None else now
        self._require_admin(context, now)
        with self._locked():
            data = self._read()
            subject = self._subject(data, subject_id)
            if not subject or subject.get("subject_type") != "service_account":
                raise LifecycleError("service account not found")
            subject["enabled"] = False
            subject["mapping_version"] = int(subject.get("mapping_version", 0)) + 1
            for token in data["tokens"]:
                if token.get("subject_id") == subject_id and token.get("revoked_at") is None:
                    token["revoked_at"] = now
                    token["revocation_reason"] = "subject_disabled"
            self._commit_with_audit(data, self._audit_payload(
                "service_account.disabled", context.subject_id, subject_id, "success"
            ))
        return {key: value for key, value in subject.items() if key != "forgejo_token_file"}

    def remap_service_account(
        self,
        context: AdminContext,
        subject_id: str,
        *,
        forgejo_user_id: int,
        forgejo_token_file: str,
        allowed_scopes: list[str],
        repository_permissions: dict[str, str],
        now: int | None = None,
    ) -> dict[str, Any]:
        """Replace a mapping and revoke every credential bound to the old mapping."""
        now = int(time.time()) if now is None else now
        self._require_admin(context, now)
        normalized_scopes = self._validate_scopes(allowed_scopes)
        repositories = self._validate_repositories(list(repository_permissions))
        if set(repository_permissions.values()) - {"read", "write", "admin"}:
            raise LifecycleError("invalid repository permission")
        if forgejo_user_id <= 0 or not forgejo_token_file:
            raise LifecycleError("invalid subject mapping")
        with self._locked():
            data = self._read()
            subject = self._subject(data, subject_id)
            if not subject or subject.get("subject_type") != "service_account":
                raise LifecycleError("service account not found")
            subject.update({
                "forgejo_user_id": forgejo_user_id,
                "forgejo_token_file": forgejo_token_file,
                "allowed_scopes": normalized_scopes,
                "repository_permissions": {key: repository_permissions[key] for key in repositories},
                "mapping_version": int(subject.get("mapping_version", 0)) + 1,
                "enabled": True,
            })
            for token in data["tokens"]:
                if token.get("subject_id") == subject_id and token.get("revoked_at") is None:
                    token["revoked_at"] = now
                    token["revocation_reason"] = "subject_remapped"
            self._commit_with_audit(data, self._audit_payload(
                "service_account.remapped", context.subject_id, subject_id, "success"
            ))
        return {key: value for key, value in subject.items() if key != "forgejo_token_file"}

    def issue(
        self,
        context: AdminContext,
        *,
        subject_id: str,
        client_id: str,
        scopes: list[str],
        repositories: list[str],
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        now: int | None = None,
    ) -> IssuedToken:
        now = int(time.time()) if now is None else now
        self._require_admin(context, now)
        normalized_scopes = self._validate_scopes(scopes)
        validate_governance_identifier("subject identifier", subject_id)
        validate_governance_identifier("client identifier", client_id)
        normalized_repositories = self._validate_repositories(repositories)
        if ttl_seconds <= 0 or ttl_seconds > MAX_TTL_SECONDS:
            raise LifecycleError("invalid token lifetime")
        plaintext = secrets.token_urlsafe(32)
        with self._locked():
            data = self._read()
            subject = self._subject(data, subject_id)
            if not subject or not subject.get("enabled") or not subject.get("forgejo_user_id"):
                raise LifecycleError("active subject mapping is required")
            if subject.get("subject_type") == "service_account" and not normalized_repositories:
                raise LifecycleError("service account tokens require repository constraints")
            allowed_scopes = subject.get("allowed_scopes")
            repository_permissions = subject.get("repository_permissions")
            if (
                not isinstance(allowed_scopes, list)
                or not allowed_scopes
                or any(not isinstance(scope, str) for scope in allowed_scopes)
                or not set(allowed_scopes).issubset(DECLARED_SCOPES)
                or not isinstance(repository_permissions, dict)
                or any(
                    not isinstance(target, str)
                    or not isinstance(permission, str)
                    or permission not in {"read", "write", "admin"}
                    for target, permission in repository_permissions.items()
                )
            ):
                raise LifecycleError("active subject mapping is required")
            available = set(repository_permissions)
            if not set(normalized_repositories).issubset(available):
                raise LifecycleError("repository constraint exceeds subject mapping")
            if not set(normalized_scopes).issubset(set(allowed_scopes)):
                raise LifecycleError("token scope exceeds subject grant")
            needs_write = any(scope in MUTATING_SCOPES for scope in normalized_scopes)
            if needs_write:
                order = {"read": 1, "write": 2, "admin": 3}
                if any(
                    order.get(repository_permissions.get(target), 0) < order["write"]
                    for target in normalized_repositories
                ):
                    raise LifecycleError("token scope exceeds repository permission")
            token_id = str(uuid.uuid4())
            record = {
                "token_id": token_id,
                "token_sha256": token_digest(plaintext),
                "client_id": client_id,
                "subject_id": subject_id,
                "subject_type": subject.get("subject_type", "human"),
                "audience": TOKEN_AUDIENCE,
                "scopes": normalized_scopes,
                "repositories": normalized_repositories,
                "mapping_version": subject.get("mapping_version", 1),
                "created_at": now,
                "expires_at": now + ttl_seconds,
                "revoked_at": None,
            }
            data["tokens"].append(record)
            self._commit_with_audit(data, self._audit_payload(
                "token.issued", context.subject_id, token_id, "success", subject_id=subject_id
            ))
        return IssuedToken(token=plaintext, metadata=public_token_metadata(record))

    def rotate(
        self,
        context: AdminContext,
        token_id: str,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        now: int | None = None,
    ) -> IssuedToken:
        now = int(time.time()) if now is None else now
        self._require_admin(context, now)
        if ttl_seconds <= 0 or ttl_seconds > MAX_TTL_SECONDS:
            raise LifecycleError("invalid token lifetime")
        plaintext = secrets.token_urlsafe(32)
        with self._locked():
            data = self._read()
            previous = next((item for item in data["tokens"] if item.get("token_id") == token_id), None)
            if not previous or previous.get("revoked_at") is not None or previous.get("expires_at", 0) <= now:
                raise LifecycleError("active token not found")
            subject = self._subject(data, str(previous.get("subject_id", "")))
            if (
                not subject or not subject.get("enabled")
                or subject.get("mapping_version") != previous.get("mapping_version")
            ):
                raise LifecycleError("active subject mapping is required")
            previous["revoked_at"] = now
            previous["revocation_reason"] = "rotated"
            new_id = str(uuid.uuid4())
            record = {
                **{key: previous[key] for key in (
                    "client_id", "subject_id", "subject_type", "audience", "scopes",
                    "repositories", "mapping_version"
                )},
                "token_id": new_id,
                "token_sha256": token_digest(plaintext),
                "created_at": now,
                "expires_at": now + ttl_seconds,
                "revoked_at": None,
                "rotated_from": token_id,
            }
            data["tokens"].append(record)
            self._commit_with_audit(data, self._audit_payload(
                "token.rotated", context.subject_id, new_id, "success", previous_token_id=token_id
            ))
        return IssuedToken(token=plaintext, metadata=public_token_metadata(record))

    def revoke(
        self, context: AdminContext, token_id: str, *, now: int | None = None
    ) -> dict[str, Any]:
        now = int(time.time()) if now is None else now
        self._require_admin(context, now)
        with self._locked():
            data = self._read()
            record = next((item for item in data["tokens"] if item.get("token_id") == token_id), None)
            if not record:
                raise LifecycleError("token not found")
            if record.get("revoked_at") is None:
                record["revoked_at"] = now
                record["revocation_reason"] = "administrator_revoked"
            self._commit_with_audit(data, self._audit_payload(
                "token.revoked", context.subject_id, token_id, "success"
            ))
        return public_token_metadata(record)

    def list_tokens(self, context: AdminContext, *, now: int | None = None) -> list[dict[str, Any]]:
        now = int(time.time()) if now is None else now
        self._require_admin(context, now)
        with self._locked():
            return [public_token_metadata(item) for item in self._read()["tokens"]]

    def list_service_accounts(
        self, context: AdminContext, *, now: int | None = None
    ) -> list[dict[str, Any]]:
        """Return operator-safe mappings without credential file locations."""
        now = int(time.time()) if now is None else now
        self._require_admin(context, now)
        with self._locked():
            return [
                {key: value for key, value in item.items() if key != "forgejo_token_file"}
                for item in self._read()["subjects"]
                if item.get("subject_type") == "service_account"
            ]

    def find_digest(self, digest: str, *, now: int | None = None) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """Constant-work lookup followed by lifecycle and mapping validation."""
        now = int(time.time()) if now is None else now
        # Readers do not create a lock beside the registry: the deployed Docker
        # secret is deliberately read-only. Writers use atomic replace, so a
        # reader observes either the old complete document or the new one.
        data = self._read(strict_schema=False)
        matched: dict[str, Any] | None = None
        for candidate in data["tokens"]:
            candidate_digest = str(candidate.get("token_sha256", "")).lower()
            if len(candidate_digest) == 64 and hmac.compare_digest(candidate_digest, digest):
                matched = candidate
        if not matched or matched.get("audience") != TOKEN_AUDIENCE:
            return None
        try:
            expires_at = parse_token_expiry(matched.get("expires_at"))
        except LifecycleError:
            return None
        if matched.get("revoked_at") is not None or expires_at <= now:
            return None
        subject = self._subject(data, str(matched.get("subject_id", "")))
        try:
            forgejo_user_id = int(subject.get("forgejo_user_id", 0)) if subject else 0
        except (TypeError, ValueError):
            forgejo_user_id = 0
        if (
            not subject or not subject.get("enabled") or forgejo_user_id <= 0
            or subject.get("mapping_version") != matched.get("mapping_version")
        ):
            return None
        token_scopes = matched.get("scopes")
        allowed_scopes = subject.get("allowed_scopes")
        if (
            not isinstance(token_scopes, list)
            or not isinstance(allowed_scopes, list)
            or not token_scopes
            or not allowed_scopes
            or any(not isinstance(scope, str) for scope in token_scopes)
            or any(not isinstance(scope, str) for scope in allowed_scopes)
            or not set(token_scopes).issubset(DECLARED_SCOPES)
            or not set(allowed_scopes).issubset(DECLARED_SCOPES)
            or not set(token_scopes).issubset(set(allowed_scopes))
        ):
            return None
        token_repositories = matched.get("repositories")
        repository_permissions = subject.get("repository_permissions")
        if (
            not isinstance(token_repositories, list)
            or not isinstance(repository_permissions, dict)
            or any(not isinstance(target, str) for target in token_repositories)
            or any(
                not isinstance(target, str)
                or not isinstance(permission, str)
                or permission not in {"read", "write", "admin"}
                for target, permission in repository_permissions.items()
            )
            or not set(token_repositories).issubset(set(repository_permissions))
            or (
                subject.get("subject_type") == "service_account"
                and not token_repositories
            )
        ):
            return None
        return dict(matched), dict(subject)
