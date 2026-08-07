from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from .client import redact, redact_text


AuditOutcome = Literal["allowed", "denied", "failed", "replayed", "changed"]
AuditEventType = Literal["request", "tool_result", "policy_change"]

_EVENT_TYPES = frozenset({"request", "tool_result", "policy_change"})
_OUTCOMES = frozenset({"allowed", "denied", "failed", "replayed", "changed"})
_TOOL_NAME = re.compile(r"^(?:[a-z][a-z0-9_]{0,127}|policy)$")


class AuditUnavailable(RuntimeError):
    """The durable audit backend cannot accept or search events."""


class InvalidAuditEvent(ValueError):
    """An unsafe or malformed audit event was rejected before persistence."""


@dataclass(frozen=True)
class AuditEvent:
    event_type: AuditEventType
    outcome: AuditOutcome
    request_id: str
    subject_id: str
    subject_type: str
    client_id: str
    tool: str
    target: str
    reason_code: str
    repository: str | None = None
    operation_id: str | None = None
    idempotency_key: str | None = None
    policy_version: int | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class AuditRecord:
    sequence: int
    event_id: str
    occurred_at: int
    event_type: str
    outcome: str
    request_id: str
    subject_id: str
    subject_type: str
    client_id: str
    tool: str
    target: str
    reason_code: str
    repository: str | None
    operation_id: str | None
    idempotency_fingerprint: str | None
    policy_version: int | None
    metadata: dict[str, Any]
    previous_hash: str
    event_hash: str


@dataclass(frozen=True)
class AuditFilter:
    event_type: str | None = None
    outcome: str | None = None
    tool: str | None = None
    subject_id: str | None = None
    client_id: str | None = None
    repository: str | None = None
    request_id: str | None = None
    operation_id: str | None = None
    reason_code: str | None = None
    occurred_after: int | None = None
    occurred_before: int | None = None


@dataclass(frozen=True)
class AuditPage:
    items: tuple[AuditRecord, ...]
    next_cursor: int | None


@dataclass(frozen=True)
class IntegrityReport:
    valid: bool
    checked_events: int
    first_invalid_sequence: int | None = None


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: str) -> str:
    # ``surrogatepass`` keeps normalization deterministic for malformed legacy
    # identifiers that can exist in an already-provisioned registry.
    return hashlib.sha256(value.encode("utf-8", errors="surrogatepass")).hexdigest()


def _safe_metadata_keys(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise InvalidAuditEvent("metadata keys must be strings")
            safe_key = (
                key if redact_text(key) == key
                else f"redacted_key_{_fingerprint(key)[:12]}"
            )
            result[safe_key] = _safe_metadata_keys(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_metadata_keys(item) for item in value]
    return value


def _safe_identifier(name: str, value: str) -> str:
    if not isinstance(value, str):
        raise InvalidAuditEvent(f"invalid {name}")
    if not value or not value.isprintable():
        return f"opaque:sha256:{_fingerprint(value)}"
    if redact_text(value) != value:
        return "redacted"
    return value


def _safe_repository(value: str | None) -> str | None:
    if value is None:
        return None
    _safe_identifier("repository", value)
    if value.count("/") != 1:
        raise InvalidAuditEvent("repository must be owner/name")
    owner, repo = value.split("/", 1)
    if owner in {".", ".."} or repo in {".", ".."}:
        raise InvalidAuditEvent("repository must be owner/name")
    normalized = f"{owner.casefold()}/{repo.casefold()}"
    if redact_text(normalized) != normalized:
        return "redacted/redacted"
    return normalized


class AuditStore:
    """Append-only, redacted SQLite audit log with cursor search and hash chain."""

    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], float] = time.time,
        retention_seconds: int = 7_776_000,
    ):
        if retention_seconds < 1:
            raise InvalidAuditEvent("audit retention must be positive")
        self.path = path
        self.clock = clock
        self.retention_seconds = retention_seconds
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise AuditUnavailable("audit backend is unavailable") from exc
        self._initialize()
        self._grant_shared_writer_access()

    def _grant_shared_writer_access(self) -> None:
        if os.name == "nt":
            return
        try:
            parent = self.path.parent.stat()
            parent_mode = parent.st_mode & 0o777
            if parent_mode & 0o070 != 0o070:
                if parent.st_uid != os.geteuid():
                    raise OSError("shared audit directory is not group writable")
                os.chmod(self.path.parent, parent_mode | 0o070)
            record = self.path.stat()
            mode = record.st_mode & 0o777
            if mode & 0o060 != 0o060:
                if record.st_uid != os.geteuid():
                    raise OSError("shared audit database is not group writable")
                os.chmod(self.path, mode | 0o060)
        except OSError as exc:
            raise AuditUnavailable("audit backend is unavailable") from exc

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        try:
            with self._connect() as db:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS audit_state (
                        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                        anchor_sequence INTEGER NOT NULL,
                        anchor_hash TEXT NOT NULL
                    );
                    INSERT OR IGNORE INTO audit_state
                        (singleton, anchor_sequence, anchor_hash) VALUES (1, 0, '');

                    CREATE TABLE IF NOT EXISTS audit_events (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT NOT NULL UNIQUE,
                        occurred_at INTEGER NOT NULL,
                        event_type TEXT NOT NULL,
                        outcome TEXT NOT NULL,
                        request_id TEXT NOT NULL,
                        subject_id TEXT NOT NULL,
                        subject_type TEXT NOT NULL,
                        client_id TEXT NOT NULL,
                        tool TEXT NOT NULL,
                        target TEXT NOT NULL,
                        reason_code TEXT NOT NULL,
                        repository TEXT,
                        operation_id TEXT,
                        idempotency_fingerprint TEXT,
                        policy_version INTEGER,
                        metadata_json TEXT NOT NULL,
                        previous_hash TEXT NOT NULL,
                        event_hash TEXT NOT NULL UNIQUE
                    );
                    CREATE INDEX IF NOT EXISTS audit_events_search
                        ON audit_events (occurred_at, outcome, tool, subject_id, repository);
                    CREATE INDEX IF NOT EXISTS audit_events_request
                        ON audit_events (request_id, operation_id);
                """)
        except (OSError, sqlite3.Error) as exc:
            raise AuditUnavailable("audit backend is unavailable") from exc

    @staticmethod
    def _sanitize(event: AuditEvent) -> dict[str, Any]:
        if event.event_type not in _EVENT_TYPES:
            raise InvalidAuditEvent("invalid event type")
        if event.outcome not in _OUTCOMES:
            raise InvalidAuditEvent("invalid outcome")
        identifiers = {
            name: _safe_identifier(name, value) for name, value in (
            ("request_id", event.request_id),
            ("subject_id", event.subject_id),
            ("subject_type", event.subject_type),
            ("client_id", event.client_id),
            ("reason_code", event.reason_code),
            )
        }
        if not _TOOL_NAME.fullmatch(event.tool):
            raise InvalidAuditEvent("invalid tool")
        operation_id = (
            _safe_identifier("operation_id", event.operation_id)
            if event.operation_id is not None else None
        )
        if not isinstance(event.target, str) or not event.target or len(event.target) > 1024:
            raise InvalidAuditEvent("invalid target")
        if event.policy_version is not None and event.policy_version < 0:
            raise InvalidAuditEvent("invalid policy version")
        metadata = redact(_safe_metadata_keys(event.metadata or {}))
        if not isinstance(metadata, dict):
            raise InvalidAuditEvent("metadata must be an object")
        try:
            _canonical(metadata)
        except (TypeError, ValueError) as exc:
            raise InvalidAuditEvent("metadata must contain JSON values") from exc
        return {
            "event_type": event.event_type,
            "outcome": event.outcome,
            "request_id": identifiers["request_id"],
            "subject_id": identifiers["subject_id"],
            "subject_type": identifiers["subject_type"],
            "client_id": identifiers["client_id"],
            "tool": event.tool,
            "target": redact_text(event.target),
            "reason_code": identifiers["reason_code"],
            "repository": _safe_repository(event.repository),
            "operation_id": operation_id,
            "idempotency_fingerprint": (
                _fingerprint(event.idempotency_key) if event.idempotency_key else None
            ),
            "policy_version": event.policy_version,
            "metadata": metadata,
        }

    def append(self, event: AuditEvent) -> AuditRecord:
        safe = self._sanitize(event)
        occurred_at = int(self.clock())
        event_id = str(uuid.uuid4())
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                previous = db.execute(
                    "SELECT event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
                ).fetchone()
                if previous is None:
                    state = db.execute(
                        "SELECT anchor_hash FROM audit_state WHERE singleton = 1"
                    ).fetchone()
                    if state is None:
                        raise AuditUnavailable("audit backend is unavailable")
                    previous_hash = str(state["anchor_hash"])
                else:
                    previous_hash = str(previous["event_hash"])
                hashed = {
                    "event_id": event_id,
                    "occurred_at": occurred_at,
                    **safe,
                    "previous_hash": previous_hash,
                }
                event_hash = _fingerprint(_canonical(hashed))
                cursor = db.execute(
                    """INSERT INTO audit_events (
                           event_id, occurred_at, event_type, outcome, request_id,
                           subject_id, subject_type, client_id, tool, target,
                           reason_code, repository, operation_id,
                           idempotency_fingerprint, policy_version, metadata_json,
                           previous_hash, event_hash
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event_id, occurred_at, safe["event_type"], safe["outcome"],
                        safe["request_id"], safe["subject_id"], safe["subject_type"],
                        safe["client_id"], safe["tool"], safe["target"],
                        safe["reason_code"], safe["repository"], safe["operation_id"],
                        safe["idempotency_fingerprint"], safe["policy_version"],
                        _canonical(safe["metadata"]), previous_hash, event_hash,
                    ),
                )
                sequence = int(cursor.lastrowid)
                db.execute("COMMIT")
        except AuditUnavailable:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise AuditUnavailable("audit backend is unavailable") from exc
        self.purge_before(occurred_at - self.retention_seconds)
        return AuditRecord(
            sequence=sequence,
            event_id=event_id,
            occurred_at=occurred_at,
            previous_hash=previous_hash,
            event_hash=event_hash,
            **safe,
        )

    @staticmethod
    def _record(row: sqlite3.Row) -> AuditRecord:
        try:
            metadata = json.loads(row["metadata_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise AuditUnavailable("audit backend integrity check failed") from exc
        return AuditRecord(
            sequence=int(row["sequence"]), event_id=row["event_id"],
            occurred_at=int(row["occurred_at"]), event_type=row["event_type"],
            outcome=row["outcome"], request_id=row["request_id"],
            subject_id=row["subject_id"], subject_type=row["subject_type"],
            client_id=row["client_id"], tool=row["tool"], target=row["target"],
            reason_code=row["reason_code"], repository=row["repository"],
            operation_id=row["operation_id"],
            idempotency_fingerprint=row["idempotency_fingerprint"],
            policy_version=row["policy_version"], metadata=metadata,
            previous_hash=row["previous_hash"], event_hash=row["event_hash"],
        )

    @staticmethod
    def _filter_clause(filters: AuditFilter) -> tuple[list[str], list[Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        for column, value in (
            ("event_type", filters.event_type), ("outcome", filters.outcome),
            ("tool", filters.tool),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                parameters.append(value)
        for column, value in (
            ("subject_id", filters.subject_id),
            ("client_id", filters.client_id),
            ("request_id", filters.request_id),
            ("operation_id", filters.operation_id),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                parameters.append(_safe_identifier(column, value))
        if filters.reason_code is not None:
            clauses.append("reason_code = ?")
            parameters.append(filters.reason_code)
        if filters.repository is not None:
            clauses.append("repository = ?")
            parameters.append(_safe_repository(filters.repository))
        if filters.occurred_after is not None:
            clauses.append("occurred_at >= ?")
            parameters.append(filters.occurred_after)
        if filters.occurred_before is not None:
            clauses.append("occurred_at < ?")
            parameters.append(filters.occurred_before)
        return clauses, parameters

    def search(
        self,
        filters: AuditFilter = AuditFilter(),
        *,
        cursor: int | None = None,
        limit: int = 50,
    ) -> AuditPage:
        if limit < 1 or limit > 100 or cursor is not None and cursor < 1:
            raise InvalidAuditEvent("invalid pagination")
        clauses, parameters = self._filter_clause(filters)
        if cursor is not None:
            clauses.append("sequence < ?")
            parameters.append(cursor)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        try:
            with self._connect() as db:
                rows = db.execute(
                    f"SELECT * FROM audit_events {where} ORDER BY sequence DESC LIMIT ?",
                    (*parameters, limit + 1),
                ).fetchall()
        except (OSError, sqlite3.Error) as exc:
            raise AuditUnavailable("audit backend is unavailable") from exc
        has_more = len(rows) > limit
        items = tuple(self._record(row) for row in rows[:limit])
        next_cursor = items[-1].sequence if has_more and items else None
        return AuditPage(items, next_cursor)

    def summarize(self, filters: AuditFilter = AuditFilter()) -> dict[str, Any]:
        clauses, parameters = self._filter_clause(filters)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        try:
            with self._connect() as db:
                rows = db.execute(
                    f"""SELECT outcome, tool, COUNT(*) AS count
                        FROM audit_events {where}
                        GROUP BY outcome, tool ORDER BY outcome, tool""",
                    parameters,
                ).fetchall()
        except (OSError, sqlite3.Error) as exc:
            raise AuditUnavailable("audit backend is unavailable") from exc
        by_outcome: dict[str, int] = {}
        by_tool: dict[str, int] = {}
        total = 0
        for row in rows:
            count = int(row["count"])
            total += count
            by_outcome[str(row["outcome"])] = by_outcome.get(str(row["outcome"]), 0) + count
            by_tool[str(row["tool"])] = by_tool.get(str(row["tool"]), 0) + count
        return {"total": total, "by_outcome": by_outcome, "by_tool": by_tool}

    def purge_before(self, cutoff: int) -> int:
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                # Only remove a contiguous prefix. A wall-clock correction must
                # never create a hole in the retained hash chain.
                boundary = db.execute(
                    """SELECT sequence FROM audit_events
                       WHERE occurred_at >= ? ORDER BY sequence LIMIT 1""",
                    (cutoff,),
                ).fetchone()
                if boundary is None:
                    anchor = db.execute(
                        """SELECT sequence, event_hash FROM audit_events
                           ORDER BY sequence DESC LIMIT 1"""
                    ).fetchone()
                else:
                    anchor = db.execute(
                        """SELECT sequence, event_hash FROM audit_events
                           WHERE sequence < ? ORDER BY sequence DESC LIMIT 1""",
                        (boundary["sequence"],),
                    ).fetchone()
                if anchor is None:
                    db.execute("COMMIT")
                    return 0
                result = db.execute(
                    "DELETE FROM audit_events WHERE sequence <= ?",
                    (anchor["sequence"],),
                )
                db.execute(
                    """UPDATE audit_state SET anchor_sequence = ?, anchor_hash = ?
                       WHERE singleton = 1""",
                    (anchor["sequence"], anchor["event_hash"]),
                )
                db.execute("COMMIT")
                return int(result.rowcount)
        except (OSError, sqlite3.Error) as exc:
            raise AuditUnavailable("audit backend is unavailable") from exc

    def verify_integrity(self) -> IntegrityReport:
        try:
            with self._connect() as db:
                db.execute("BEGIN")
                state = db.execute(
                    "SELECT anchor_hash FROM audit_state WHERE singleton = 1"
                ).fetchone()
                rows = db.execute("SELECT * FROM audit_events ORDER BY sequence").fetchall()
        except (OSError, sqlite3.Error) as exc:
            raise AuditUnavailable("audit backend is unavailable") from exc
        if state is None:
            raise AuditUnavailable("audit backend integrity check failed")
        previous_hash = str(state["anchor_hash"])
        checked = 0
        for row in rows:
            record = self._record(row)
            hashed = {
                "event_id": record.event_id,
                "occurred_at": record.occurred_at,
                "event_type": record.event_type,
                "outcome": record.outcome,
                "request_id": record.request_id,
                "subject_id": record.subject_id,
                "subject_type": record.subject_type,
                "client_id": record.client_id,
                "tool": record.tool,
                "target": record.target,
                "reason_code": record.reason_code,
                "repository": record.repository,
                "operation_id": record.operation_id,
                "idempotency_fingerprint": record.idempotency_fingerprint,
                "policy_version": record.policy_version,
                "metadata": record.metadata,
                "previous_hash": record.previous_hash,
            }
            if record.previous_hash != previous_hash or _fingerprint(_canonical(hashed)) != record.event_hash:
                return IntegrityReport(False, checked, record.sequence)
            previous_hash = record.event_hash
            checked += 1
        return IntegrityReport(True, checked)
