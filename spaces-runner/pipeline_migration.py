"""Explicit one-time migration from the legacy pipeline SQLite audit file.

Normal spaces-runner startup never imports this module and never searches for
the legacy file.  Operators must pass the source file explicitly, which keeps
an old file from being mistaken for an authoritative database after a restore.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

import config
import pipeline_control


class PipelineMigrationError(RuntimeError):
    """The legacy source failed validation or could not be migrated safely."""


@dataclass(frozen=True)
class LegacyAudit:
    id: int
    owner: str
    repo: str
    action: str
    actor: str
    run_number: int | None
    workflow: str | None
    environment: str | None
    revision: str | None
    created_at: datetime


@dataclass(frozen=True)
class LegacyInventory:
    digest: str
    row_count: int
    rows: tuple[LegacyAudit, ...]


_REQUIRED_COLUMNS = {
    "id",
    "owner",
    "repo",
    "action",
    "actor",
    "run_number",
    "workflow",
    "environment",
    "revision",
    "created_at",
}


def _source_digest(source: Path) -> str:
    digest = hashlib.sha256()
    try:
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise PipelineMigrationError("Could not read the legacy SQLite file.") from exc
    return digest.hexdigest()


def _timestamp(value: object) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise PipelineMigrationError("A legacy audit row has no timestamp.")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PipelineMigrationError("A legacy audit row has an invalid timestamp.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _integer(value: object, field: str, *, allow_none: bool = False) -> int | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool):
        raise PipelineMigrationError(f"A legacy audit {field} is invalid.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise PipelineMigrationError(f"A legacy audit {field} is invalid.") from exc


def _read_inventory(source_value: str | Path) -> LegacyInventory:
    source = Path(source_value).expanduser()
    if not source.is_file():
        raise PipelineMigrationError("The explicitly supplied SQLite source is not a file.")
    source = source.resolve()
    digest = _source_digest(source)
    uri = f"file:{source.as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as legacy:
            integrity = legacy.execute("PRAGMA integrity_check").fetchone()
            if not integrity or str(integrity[0]).lower() != "ok":
                raise PipelineMigrationError("The legacy SQLite integrity check failed.")
            table = legacy.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'pipeline_audit'"
            ).fetchone()
            if not table:
                raise PipelineMigrationError("The legacy SQLite pipeline_audit table is missing.")
            columns = {
                str(row[1])
                for row in legacy.execute("PRAGMA table_info(pipeline_audit)").fetchall()
            }
            if not _REQUIRED_COLUMNS.issubset(columns):
                raise PipelineMigrationError("The legacy pipeline_audit schema is not recognized.")
            rows: list[LegacyAudit] = []
            for raw in legacy.execute(
                """
                SELECT id, owner, repo, action, actor, run_number, workflow,
                       environment, revision, created_at
                FROM pipeline_audit
                ORDER BY id ASC
                """
            ):
                audit_id = _integer(raw[0], "id")
                if audit_id is None or audit_id < 1:
                    raise PipelineMigrationError("A legacy audit id is invalid.")
                owner, repo, action, actor = (str(raw[index] or "") for index in range(1, 5))
                if not owner or not repo or not action or not actor:
                    raise PipelineMigrationError("A legacy audit identity is invalid.")
                rows.append(
                    LegacyAudit(
                        id=audit_id,
                        owner=owner,
                        repo=repo,
                        action=action,
                        actor=actor,
                        run_number=_integer(raw[5], "run_number", allow_none=True),
                        workflow=None if raw[6] is None else str(raw[6]),
                        environment=None if raw[7] is None else str(raw[7]),
                        revision=None if raw[8] is None else str(raw[8]),
                        created_at=_timestamp(raw[9]),
                    )
                )
    except sqlite3.Error as exc:
        raise PipelineMigrationError("The legacy SQLite source could not be read.") from exc
    return LegacyInventory(digest=digest, row_count=len(rows), rows=tuple(rows))

def verify_sqlite(source: str | Path) -> dict[str, int | str]:
    """Validate a legacy source without connecting to or changing PostgreSQL."""
    inventory = _read_inventory(source)
    _reconciliation_rows(inventory)
    return {"digest": inventory.digest, "row_count": inventory.row_count}

def _audit_equal(target: dict[str, Any], source: LegacyAudit) -> bool:
    target_created = target.get("created_at")
    if isinstance(target_created, datetime):
        if target_created.tzinfo is None:
            target_created = target_created.replace(tzinfo=timezone.utc)
        target_created = target_created.astimezone(timezone.utc)
    return all(
        (
            target.get("id") == source.id,
            target.get("owner") == source.owner,
            target.get("repo") == source.repo,
            target.get("action") == source.action,
            target.get("actor") == source.actor,
            target.get("run_number") == source.run_number,
            target.get("workflow") == source.workflow,
            target.get("environment") == source.environment,
            target.get("revision") == source.revision,
            target_created == source.created_at,
        )
    )


def _state_payload(row: LegacyAudit) -> dict[str, Any] | None:
    if row.action != "_reconcile_production_state":
        return None
    if row.run_number is None or not row.workflow:
        raise PipelineMigrationError("A legacy reconciliation state is incomplete.")
    try:
        payload = json.loads(row.workflow)
    except json.JSONDecodeError as exc:
        raise PipelineMigrationError("A legacy reconciliation state is invalid.") from exc
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise PipelineMigrationError("A legacy reconciliation state version is unsupported.")
    state = str(payload.get("state") or "")
    if state not in {"pending", "watch", "terminal"}:
        raise PipelineMigrationError("A legacy reconciliation state value is invalid.")
    fingerprint = payload.get("fingerprint")
    updated = payload.get("updated")
    expires_at = payload.get("expires_at")
    if not isinstance(fingerprint, str) or not isinstance(updated, str) or not isinstance(expires_at, str):
        raise PipelineMigrationError("A legacy reconciliation state payload is invalid.")
    attempt = _integer(payload.get("attempt"), "attempt")
    artifact_id = _integer(payload.get("artifact_id"), "artifact_id")
    run_id = _integer(payload.get("run_id"), "run_id")
    if attempt is None or attempt < 0 or artifact_id is None or artifact_id < 0 or run_id is None:
        raise PipelineMigrationError("A legacy reconciliation state counter is invalid.")
    return {
        "owner": row.owner,
        "repo": row.repo,
        "run_number": row.run_number,
        "state": state,
        "run_id": run_id,
        "fingerprint": fingerprint,
        "updated": updated,
        "attempt": attempt,
        "artifact_id": artifact_id,
        "expires_at": expires_at,
        "revision": row.revision,
        "workflow": row.workflow,
        "checked_at": row.created_at,
        "last_audit_id": row.id,
    }

def _reconciliation_rows(
    inventory: LegacyInventory,
) -> tuple[dict[tuple[str, str, int], dict[str, Any]], dict[tuple[str, str], LegacyAudit]]:
    state_rows, cursor_rows = {}, {}
    for row in inventory.rows:
        payload = _state_payload(row)
        if payload is not None:
            state_rows[(row.owner, row.repo, int(row.run_number))] = payload
        if row.action == "_reconcile_production_cursor":
            if row.run_number is None: raise PipelineMigrationError("A legacy reconciliation cursor is incomplete.")
            cursor_rows[(row.owner, row.repo)] = row
    return state_rows, cursor_rows

def _utc_timestamp(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


_STATE_FIELDS = (
    "owner",
    "repo",
    "run_number",
    "state",
    "run_id",
    "fingerprint",
    "updated",
    "attempt",
    "artifact_id",
    "expires_at",
    "revision",
    "workflow",
)


def _target_state_fields_equal(target: dict[str, Any], payload: dict[str, Any]) -> bool:
    return all(target.get(key) == payload[key] for key in _STATE_FIELDS)


def _target_state_equal(target: dict[str, Any], payload: dict[str, Any]) -> bool:
    for key in (
        *_STATE_FIELDS,
        "last_audit_id",
    ):
        if target.get(key) != payload[key]:
            return False
    return _utc_timestamp(target.get("checked_at")) == payload["checked_at"]

def _audit_row(db, audit_id: object):
    audit = db.execute(
        sql.SQL(
            """
            SELECT id, owner, repo, action, actor, run_number, workflow,
                   environment, revision, created_at
            FROM {} WHERE id = %s
            """
        ).format(pipeline_control._qualified("pipeline_audit")),
        (audit_id,),
    ).fetchone()
    return audit

def _state_audit_matches_target(db, target: dict[str, Any]) -> bool:
    audit = _audit_row(db, target.get("last_audit_id"))
    if not audit:
        return False
    return all(
        (
            audit["id"] == target.get("last_audit_id"),
            audit["owner"] == target.get("owner"),
            audit["repo"] == target.get("repo"),
            audit["action"] == "_reconcile_production_state",
            audit["actor"] == "nyankoface-deployer",
            audit["run_number"] == target.get("run_number"),
            audit["workflow"] == target.get("workflow"),
            audit["environment"] == target.get("state"),
            audit["revision"] == target.get("revision"),
            _utc_timestamp(audit["created_at"]) == _utc_timestamp(target.get("checked_at")),
        )
    )


def _target_state_status(db, target: dict[str, Any], payload: dict[str, Any]) -> str | None:
    current_id = _integer(target.get("last_audit_id"), "target reconciliation audit id")
    if current_id is None:
        return None
    source_id = int(payload["last_audit_id"])
    if current_id == source_id:
        if _target_state_equal(target, payload):
            return "exact"
        target_checked = _utc_timestamp(target.get("checked_at"))
        if (
            _target_state_fields_equal(target, payload)
            and target_checked is not None
            and target_checked >= payload["checked_at"]
        ):
            return "refreshed"
        return None
    if current_id < source_id:
        return None
    target_checked = _utc_timestamp(target.get("checked_at"))
    if target_checked is None or target_checked < payload["checked_at"]:
        return None
    return "advanced" if _state_audit_matches_target(db, target) else None


def _target_cursor_equal(target: dict[str, Any], source: LegacyAudit) -> bool:
    target_updated = _utc_timestamp(target.get("updated_at"))
    return (
        int(target.get("run_number") or 0) == int(source.run_number or 0)
        and int(target.get("last_audit_id") or 0) == source.id
        and target_updated == source.created_at
    )


def _cursor_audit_matches_target(
    db,
    owner: str,
    repo: str,
    target: dict[str, Any],
) -> bool:
    audit = _audit_row(db, target.get("last_audit_id"))
    if not audit:
        return False
    return all(
        (
            audit["id"] == target.get("last_audit_id"),
            audit["owner"] == owner,
            audit["repo"] == repo,
            audit["action"] == "_reconcile_production_cursor",
            audit["actor"] == "nyankoface-deployer",
            audit["run_number"] == target.get("run_number"),
            audit["workflow"] == "v1",
            audit["environment"] == "production",
            audit["revision"] is None,
            _utc_timestamp(audit["created_at"]) == _utc_timestamp(target.get("updated_at")),
        )
    )


def _target_cursor_status(
    db,
    owner: str,
    repo: str,
    target: dict[str, Any],
    source: LegacyAudit,
) -> str | None:
    current_id = _integer(target.get("last_audit_id"), "target cursor audit id")
    current_run = _integer(target.get("run_number"), "target cursor run number")
    if current_id is None or current_run is None or source.run_number is None:
        return None
    if current_id == source.id:
        return "exact" if _target_cursor_equal(target, source) else None
    if current_id < source.id or current_run <= int(source.run_number):
        return None
    target_updated = _utc_timestamp(target.get("updated_at"))
    if target_updated is None or target_updated < source.created_at:
        return None
    return "advanced" if _cursor_audit_matches_target(db, owner, repo, target) else None

def _reset_audit_sequence(db) -> None:
    sequence = db.execute(
        "SELECT pg_get_serial_sequence(%s, %s) AS sequence_name",
        (f"{config.PIPELINE_DB_SCHEMA}.pipeline_audit", "id"),
    ).fetchone()
    if not sequence or not sequence["sequence_name"]:
        return
    maximum = db.execute(
        sql.SQL("SELECT MAX(id) AS maximum FROM {}")
        .format(pipeline_control._qualified("pipeline_audit"))
    ).fetchone()["maximum"]
    if maximum is None:
        db.execute("SELECT setval(%s, 1, false)", (sequence["sequence_name"],))
    else:
        db.execute(
            "SELECT setval(%s, %s, true)",
            (sequence["sequence_name"], int(maximum)),
        )

def migrate_sqlite(source: str | Path) -> dict[str, int | str | bool]:
    """Import one validated SQLite audit file exactly once.

    The source is retained.  A digest marker in PostgreSQL makes repeating the
    command a safe verification/idempotency operation instead of duplicating
    events or reconciliation transitions.  Reconciliation rows may advance
    after the marker is written, but only when their newer audit row verifies
    the current target state or cursor.
    """
    inventory = _read_inventory(source)
    state_rows, cursor_rows = _reconciliation_rows(inventory)
    pipeline_control.initialize()
    with pipeline_control._connect() as db:
        db.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 1))",
            (f"pipeline-sqlite-migration:{inventory.digest}",),
        )
        marker = db.execute(
            sql.SQL("SELECT row_count FROM {} WHERE source_digest = %s")
            .format(pipeline_control._qualified("sqlite_migrations")),
            (inventory.digest,),
        ).fetchone()
        if marker:
            if int(marker["row_count"]) != inventory.row_count:
                raise PipelineMigrationError("The recorded SQLite migration count does not match the source.")
            for source_row in inventory.rows:
                target = db.execute(
                    sql.SQL(
                        """
                        SELECT id, owner, repo, action, actor, run_number, workflow,
                               environment, revision, created_at
                        FROM {} WHERE id = %s
                        """
                    ).format(pipeline_control._qualified("pipeline_audit")),
                    (source_row.id,),
                ).fetchone()
                if not target or not _audit_equal(target, source_row):
                    raise PipelineMigrationError("The recorded SQLite migration failed verification.")
            for payload in state_rows.values():
                target = db.execute(
                    sql.SQL(
                        "SELECT * FROM {} WHERE owner = %s AND repo = %s AND run_number = %s"
                    ).format(pipeline_control._qualified("pipeline_reconcile_state")),
                    (payload["owner"], payload["repo"], payload["run_number"]),
                ).fetchone()
                if not target or _target_state_status(db, target, payload) is None:
                    raise PipelineMigrationError("The recorded SQLite reconciliation state failed verification.")
            for (owner, repo), source_row in cursor_rows.items():
                target = db.execute(
                    sql.SQL(
                        "SELECT run_number, updated_at, last_audit_id FROM {}"
                        " WHERE owner = %s AND repo = %s"
                    ).format(pipeline_control._qualified("pipeline_reconcile_cursor")),
                    (owner, repo),
                ).fetchone()
                if not target or _target_cursor_status(db, owner, repo, target, source_row) is None:
                    raise PipelineMigrationError("The recorded SQLite reconciliation cursor failed verification.")
            return {
                "digest": inventory.digest,
                "row_count": inventory.row_count,
                "already_migrated": True,
            }
        for source_row in inventory.rows:
            target = db.execute(
                sql.SQL(
                    """
                    SELECT id, owner, repo, action, actor, run_number, workflow,
                           environment, revision, created_at
                    FROM {} WHERE id = %s
                    """
                ).format(pipeline_control._qualified("pipeline_audit")),
                (source_row.id,),
            ).fetchone()
            if target and not _audit_equal(target, source_row):
                raise PipelineMigrationError("A legacy audit id conflicts with existing PostgreSQL data.")
        for source_row in inventory.rows:
            db.execute(
                sql.SQL(
                    """
                    INSERT INTO {} AS target(
                        id, owner, repo, action, actor, run_number, workflow,
                        environment, revision, created_at
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(id) DO NOTHING
                    """
                ).format(pipeline_control._qualified("pipeline_audit")),
                (
                    source_row.id,
                    source_row.owner,
                    source_row.repo,
                    source_row.action,
                    source_row.actor,
                    source_row.run_number,
                    source_row.workflow,
                    source_row.environment,
                    source_row.revision,
                    source_row.created_at,
                ),
            )
        for payload in state_rows.values():
            current = db.execute(
                sql.SQL(
                    "SELECT * FROM {} WHERE owner = %s AND repo = %s AND run_number = %s"
                ).format(pipeline_control._qualified("pipeline_reconcile_state")),
                (payload["owner"], payload["repo"], payload["run_number"]),
            ).fetchone()
            if current:
                current_id = _integer(current.get("last_audit_id"), "target reconciliation audit id")
                if current_id is None:
                    raise PipelineMigrationError("A legacy reconciliation state conflicts with existing PostgreSQL data.")
                if current_id >= payload["last_audit_id"]:
                    if _target_state_status(db, current, payload) is None:
                        raise PipelineMigrationError("A legacy reconciliation state conflicts with existing PostgreSQL data.")
                    continue
            db.execute(
                sql.SQL(
                    """
                    INSERT INTO {} AS target(
                        owner, repo, run_number, state, run_id, fingerprint,
                        updated, attempt, artifact_id, expires_at, revision,
                        workflow, checked_at, last_audit_id
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(owner, repo, run_number) DO UPDATE SET
                        state = EXCLUDED.state, run_id = EXCLUDED.run_id,
                        fingerprint = EXCLUDED.fingerprint, updated = EXCLUDED.updated,
                        attempt = EXCLUDED.attempt, artifact_id = EXCLUDED.artifact_id,
                        expires_at = EXCLUDED.expires_at, revision = EXCLUDED.revision,
                        workflow = EXCLUDED.workflow, checked_at = EXCLUDED.checked_at,
                        last_audit_id = EXCLUDED.last_audit_id
                    WHERE target.last_audit_id < EXCLUDED.last_audit_id
                    """
                ).format(pipeline_control._qualified("pipeline_reconcile_state")),
                tuple(payload[key] for key in (
                    "owner", "repo", "run_number", "state", "run_id", "fingerprint",
                    "updated", "attempt", "artifact_id", "expires_at", "revision",
                    "workflow", "checked_at", "last_audit_id",
                )),
            )
        for (owner, repo), row in cursor_rows.items():
            current = db.execute(
                sql.SQL(
                    "SELECT run_number, updated_at, last_audit_id FROM {}"
                    " WHERE owner = %s AND repo = %s"
                ).format(pipeline_control._qualified("pipeline_reconcile_cursor")),
                (owner, repo),
            ).fetchone()
            if current:
                current_id = _integer(current.get("last_audit_id"), "target cursor audit id")
                if current_id is None:
                    raise PipelineMigrationError("A legacy reconciliation cursor conflicts with existing PostgreSQL data.")
                if current_id >= row.id:
                    if _target_cursor_status(db, owner, repo, current, row) is None:
                        raise PipelineMigrationError("A legacy reconciliation cursor conflicts with existing PostgreSQL data.")
                    continue
            db.execute(
                sql.SQL(
                    """
                    INSERT INTO {} AS target(owner, repo, run_number, updated_at, last_audit_id)
                    VALUES(%s,%s,%s,%s,%s)
                    ON CONFLICT(owner, repo) DO UPDATE SET
                        run_number = EXCLUDED.run_number,
                        updated_at = EXCLUDED.updated_at,
                        last_audit_id = EXCLUDED.last_audit_id
                    WHERE target.last_audit_id < EXCLUDED.last_audit_id
                    """
                ).format(pipeline_control._qualified("pipeline_reconcile_cursor")),
                (owner, repo, row.run_number, row.created_at, row.id),
            )
        _reset_audit_sequence(db)
        db.execute(
            sql.SQL(
                "INSERT INTO {}(source_digest, row_count) VALUES(%s,%s)"
            ).format(pipeline_control._qualified("sqlite_migrations")),
            (inventory.digest, inventory.row_count),
        )
    return {
        "digest": inventory.digest,
        "row_count": inventory.row_count,
        "already_migrated": False,
    }

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate or explicitly migrate a legacy pipeline SQLite audit file."
    )
    parser.add_argument("--source", required=True, help="Path to the legacy pipeline-audit.db")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Validate the source without changing PostgreSQL",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = (
            verify_sqlite(args.source)
            if args.verify_only
            else migrate_sqlite(args.source)
        )
    except (PipelineMigrationError, OSError, ValueError, RuntimeError, psycopg.Error) as exc:
        detail = " ".join(str(exc).split())
        if len(detail) > 500:
            detail = f"{detail[:497]}..."
        print(
            f"Pipeline migration failed: {type(exc).__name__}: {detail}",
            file=sys.stderr,
        )
        return 1
    if args.verify_only:
        print(f"Validated legacy pipeline SQLite source ({result['row_count']} audit rows).")
    elif result["already_migrated"]:
        print(f"Legacy pipeline SQLite migration already verified ({result['row_count']} audit rows).")
    else:
        print(f"Migrated legacy pipeline SQLite audit ({result['row_count']} rows).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
