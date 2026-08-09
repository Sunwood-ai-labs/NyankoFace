from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


AccessMode = Literal["read", "write"]
PolicyEffect = Literal["allow", "deny"]
PolicyScope = Literal["global", "repository", "service_account", "subject"]

_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_SCOPE_PRIORITY: dict[str, int] = {
    "global": 0,
    "repository": 100,
    "service_account": 200,
    "subject": 300,
}


class PolicyUnavailable(RuntimeError):
    """The shared policy state cannot produce an authoritative decision."""


class InvalidPolicy(ValueError):
    """An operator supplied an invalid policy definition."""


@dataclass(frozen=True)
class PolicyRequest:
    subject_id: str
    subject_type: str
    client_id: str
    tool: str
    access: AccessMode
    repository: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_id", _validate_identifier("subject_id", self.subject_id))
        object.__setattr__(self, "subject_type", _validate_identifier("subject_type", self.subject_type))
        object.__setattr__(self, "client_id", _validate_identifier("client_id", self.client_id))
        if not _TOOL_NAME.fullmatch(self.tool):
            raise InvalidPolicy("invalid tool name")
        if self.access not in {"read", "write"}:
            raise InvalidPolicy("invalid access mode")
        if self.repository is not None:
            object.__setattr__(self, "repository", _normalize_repository(self.repository))


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    policy_version: int
    matched_scope: str | None = None
    read_only: bool = False


@dataclass(frozen=True)
class PolicyRule:
    scope: PolicyScope
    scope_id: str
    tool: str
    effect: PolicyEffect
    version: int
    updated_at: int


@dataclass(frozen=True)
class ReadOnlyRule:
    scope: PolicyScope
    scope_id: str
    version: int
    updated_at: int


def _validate_identifier(name: str, value: str) -> str:
    if not isinstance(value, str):
        raise InvalidPolicy(f"invalid {name}")
    if not value or any(ord(character) < 32 or ord(character) == 127 for character in value):
        return f"opaque:sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"
    return value


def _normalize_repository(value: str) -> str:
    _validate_identifier("repository", value)
    if value.count("/") != 1:
        raise InvalidPolicy("repository must be owner/name")
    owner, repo = value.split("/", 1)
    if owner in {".", ".."} or repo in {".", ".."}:
        raise InvalidPolicy("repository must be owner/name")
    return f"{owner.casefold()}/{repo.casefold()}"


def _normalize_scope(scope: str, scope_id: str) -> tuple[str, str]:
    if scope not in _SCOPE_PRIORITY:
        raise InvalidPolicy("invalid policy scope")
    if scope == "global":
        if scope_id != "*":
            raise InvalidPolicy("global scope_id must be *")
        return scope, scope_id
    if scope == "repository":
        return scope, _normalize_repository(scope_id)
    if scope == "service_account" and scope_id == "*":
        return scope, scope_id
    return scope, _validate_identifier("scope_id", scope_id)


class PolicyStore:
    """Shared SQLite policy backend with request-time, default-deny evaluation.

    Each call opens a new connection and reads one database snapshot. There is
    deliberately no process-local decision cache, so a committed policy change
    is visible to the next request on every instance sharing the database.
    """

    def __init__(self, path: Path):
        self.path = path
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PolicyUnavailable("policy backend is unavailable") from exc
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
                    raise OSError("shared policy directory is not group writable")
                os.chmod(self.path.parent, parent_mode | 0o070)
            record = self.path.stat()
            mode = record.st_mode & 0o777
            if mode & 0o060 != 0o060:
                if record.st_uid != os.geteuid():
                    raise OSError("shared policy database is not group writable")
                os.chmod(self.path, mode | 0o060)
        except OSError as exc:
            raise PolicyUnavailable("policy backend is unavailable") from exc

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        try:
            with self._connect() as db:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS policy_state (
                        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                        version INTEGER NOT NULL CHECK (version >= 0)
                    );
                    INSERT OR IGNORE INTO policy_state (singleton, version) VALUES (1, 0);

                    CREATE TABLE IF NOT EXISTS tool_policies (
                        scope TEXT NOT NULL,
                        scope_id TEXT NOT NULL,
                        tool TEXT NOT NULL,
                        effect TEXT NOT NULL CHECK (effect IN ('allow', 'deny')),
                        version INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL,
                        PRIMARY KEY (scope, scope_id, tool)
                    );
                    CREATE INDEX IF NOT EXISTS tool_policies_tool
                        ON tool_policies (tool, scope, scope_id);

                    CREATE TABLE IF NOT EXISTS read_only_policies (
                        scope TEXT NOT NULL,
                        scope_id TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL,
                        PRIMARY KEY (scope, scope_id)
                    );
                """)
        except (OSError, sqlite3.Error) as exc:
            raise PolicyUnavailable("policy backend is unavailable") from exc

    @staticmethod
    def _next_version(db: sqlite3.Connection, expected_version: int | None = None) -> int:
        row = db.execute("SELECT version FROM policy_state WHERE singleton = 1").fetchone()
        if row is None:
            raise PolicyUnavailable("policy backend is unavailable")
        if expected_version is not None and int(row["version"]) != expected_version:
            raise InvalidPolicy("policy version conflict")
        version = int(row["version"]) + 1
        db.execute("UPDATE policy_state SET version = ? WHERE singleton = 1", (version,))
        return version

    def set_tool_policy(
        self,
        scope: PolicyScope,
        scope_id: str,
        tool: str,
        effect: PolicyEffect,
        *,
        now: int | None = None,
        expected_version: int | None = None,
    ) -> int:
        scope, scope_id = _normalize_scope(scope, scope_id)
        if not _TOOL_NAME.fullmatch(tool):
            raise InvalidPolicy("invalid tool name")
        if effect not in {"allow", "deny"}:
            raise InvalidPolicy("invalid policy effect")
        timestamp = int(time.time()) if now is None else int(now)
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                version = self._next_version(db, expected_version)
                db.execute(
                    """INSERT INTO tool_policies
                       (scope, scope_id, tool, effect, version, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(scope, scope_id, tool) DO UPDATE SET
                           effect = excluded.effect,
                           version = excluded.version,
                           updated_at = excluded.updated_at""",
                    (scope, scope_id, tool, effect, version, timestamp),
                )
                db.execute("COMMIT")
                return version
        except (OSError, sqlite3.Error) as exc:
            raise PolicyUnavailable("policy backend is unavailable") from exc

    def delete_tool_policy(
        self, scope: PolicyScope, scope_id: str, tool: str, *, expected_version: int | None = None
    ) -> int:
        scope, scope_id = _normalize_scope(scope, scope_id)
        if not _TOOL_NAME.fullmatch(tool):
            raise InvalidPolicy("invalid tool name")
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                version = self._next_version(db, expected_version)
                db.execute(
                    "DELETE FROM tool_policies WHERE scope = ? AND scope_id = ? AND tool = ?",
                    (scope, scope_id, tool),
                )
                db.execute("COMMIT")
                return version
        except (OSError, sqlite3.Error) as exc:
            raise PolicyUnavailable("policy backend is unavailable") from exc

    def set_read_only(
        self,
        scope: PolicyScope,
        scope_id: str,
        enabled: bool,
        *,
        now: int | None = None,
        expected_version: int | None = None,
    ) -> int:
        scope, scope_id = _normalize_scope(scope, scope_id)
        timestamp = int(time.time()) if now is None else int(now)
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                version = self._next_version(db, expected_version)
                if enabled:
                    db.execute(
                        """INSERT INTO read_only_policies
                           (scope, scope_id, version, updated_at) VALUES (?, ?, ?, ?)
                           ON CONFLICT(scope, scope_id) DO UPDATE SET
                               version = excluded.version,
                               updated_at = excluded.updated_at""",
                        (scope, scope_id, version, timestamp),
                    )
                else:
                    db.execute(
                        "DELETE FROM read_only_policies WHERE scope = ? AND scope_id = ?",
                        (scope, scope_id),
                    )
                db.execute("COMMIT")
                return version
        except (OSError, sqlite3.Error) as exc:
            raise PolicyUnavailable("policy backend is unavailable") from exc

    @staticmethod
    def _applicable(request: PolicyRequest) -> dict[tuple[str, str], int]:
        scopes: dict[tuple[str, str], int] = {("global", "*"): _SCOPE_PRIORITY["global"]}
        if request.repository:
            scopes[("repository", request.repository)] = _SCOPE_PRIORITY["repository"]
        if request.subject_type == "service_account":
            scopes[("service_account", "*")] = _SCOPE_PRIORITY["service_account"]
            scopes[("service_account", request.subject_id)] = _SCOPE_PRIORITY["service_account"] + 10
        scopes[("subject", request.subject_id)] = _SCOPE_PRIORITY["subject"]
        return scopes

    def evaluate(self, request: PolicyRequest) -> PolicyDecision:
        applicable = self._applicable(request)
        try:
            with self._connect() as db:
                db.execute("BEGIN")
                state = db.execute(
                    "SELECT version FROM policy_state WHERE singleton = 1"
                ).fetchone()
                if state is None:
                    raise PolicyUnavailable("policy backend is unavailable")
                version = int(state["version"])
                read_only_rows = db.execute(
                    "SELECT scope, scope_id FROM read_only_policies"
                ).fetchall()
                rules = db.execute(
                    "SELECT scope, scope_id, effect FROM tool_policies WHERE tool = ?",
                    (request.tool,),
                ).fetchall()
                db.execute("COMMIT")
        except PolicyUnavailable:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise PolicyUnavailable("policy backend is unavailable") from exc

        read_only_scopes = [
            (str(row["scope"]), str(row["scope_id"]))
            for row in read_only_rows
            if (str(row["scope"]), str(row["scope_id"])) in applicable
        ]
        if request.access == "write" and read_only_scopes:
            matched = max(read_only_scopes, key=lambda item: applicable[item])
            return PolicyDecision(
                allowed=False,
                reason="read_only",
                policy_version=version,
                matched_scope=f"{matched[0]}:{matched[1]}",
                read_only=True,
            )

        matches = [
            row for row in rules
            if (str(row["scope"]), str(row["scope_id"])) in applicable
        ]
        if not matches:
            if request.subject_type == "forgejo_user":
                # A direct Forgejo bearer is already authenticated upstream.
                # Repository-scoped reads and writes still pass the Forgejo
                # credential through verifier.require() and the adapter's
                # upstream permission check. Explicit policy denies and
                # read-only rules above still take precedence.
                return PolicyDecision(
                    allowed=True,
                    reason=f"forgejo_token_{request.access}",
                    policy_version=version,
                    matched_scope="subject_type:forgejo_user",
                )
            return PolicyDecision(False, "default_deny", version)
        highest = max(
            applicable[(str(row["scope"]), str(row["scope_id"]))]
            for row in matches
        )
        winners = [
            row for row in matches
            if applicable[(str(row["scope"]), str(row["scope_id"]))] == highest
        ]
        winner = next((row for row in winners if row["effect"] == "deny"), winners[0])
        scope = f"{winner['scope']}:{winner['scope_id']}"
        allowed = winner["effect"] == "allow"
        return PolicyDecision(
            allowed=allowed,
            reason="explicit_allow" if allowed else "explicit_deny",
            policy_version=version,
            matched_scope=scope,
        )

    def list_tool_policies(self) -> list[PolicyRule]:
        try:
            with self._connect() as db:
                rows = db.execute(
                    """SELECT scope, scope_id, tool, effect, version, updated_at
                       FROM tool_policies ORDER BY scope, scope_id, tool"""
                ).fetchall()
        except (OSError, sqlite3.Error) as exc:
            raise PolicyUnavailable("policy backend is unavailable") from exc
        return [
            PolicyRule(
                scope=row["scope"],
                scope_id=row["scope_id"],
                tool=row["tool"],
                effect=row["effect"],
                version=int(row["version"]),
                updated_at=int(row["updated_at"]),
            )
            for row in rows
        ]

    def current_version(self) -> int:
        try:
            with self._connect() as db:
                row = db.execute(
                    "SELECT version FROM policy_state WHERE singleton = 1"
                ).fetchone()
        except (OSError, sqlite3.Error) as exc:
            raise PolicyUnavailable("policy backend is unavailable") from exc
        if row is None:
            raise PolicyUnavailable("policy backend is unavailable")
        return int(row["version"])

    def list_read_only_policies(self) -> list[ReadOnlyRule]:
        try:
            with self._connect() as db:
                rows = db.execute(
                    """SELECT scope, scope_id, version, updated_at
                       FROM read_only_policies ORDER BY scope, scope_id"""
                ).fetchall()
        except (OSError, sqlite3.Error) as exc:
            raise PolicyUnavailable("policy backend is unavailable") from exc
        return [
            ReadOnlyRule(
                scope=row["scope"], scope_id=row["scope_id"],
                version=int(row["version"]), updated_at=int(row["updated_at"]),
            )
            for row in rows
        ]
