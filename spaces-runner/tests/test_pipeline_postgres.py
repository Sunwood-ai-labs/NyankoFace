from __future__ import annotations

import json
import os
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest

import config
import pipeline_control
import pipeline_migration

def test_pipeline_control_normal_path_has_no_sqlite_audit_file_dependency() -> None:
    source = (Path(__file__).resolve().parents[1] / "pipeline_control.py").read_text(
        encoding="utf-8"
    )
    assert "sqlite3" not in source
    assert "pipeline-audit.db" not in source
    assert "PIPELINE_DATA_DIR" not in source

def test_migration_cli_reports_failure_detail(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    def fail(_source: str | Path):
        raise pipeline_migration.PipelineMigrationError(
            "The legacy pipeline_audit schema is not recognized."
        )
    monkeypatch.setattr(pipeline_migration, "migrate_sqlite", fail)
    assert pipeline_migration.main(["--source", "pipeline-audit.db"]) == 1
    assert capsys.readouterr().err == (
        "Pipeline migration failed: PipelineMigrationError: "
        "The legacy pipeline_audit schema is not recognized.\n"
    )

@pytest.mark.parametrize(("audit_id", "column", "value", "message"), [(3, "workflow", "{malformed", "reconciliation state is invalid"), (4, "run_number", None, "reconciliation cursor is incomplete")])
def test_verify_sqlite_validates_reconciliation_rows(tmp_path: Path, audit_id: int, column: str, value: object, message: str) -> None:
    source = tmp_path / "pipeline-audit.db"
    _legacy_pipeline_db(source)
    with sqlite3.connect(source) as db:
        db.execute(f"UPDATE pipeline_audit SET {column} = ? WHERE id = ?", (value, audit_id))
    with pytest.raises(pipeline_migration.PipelineMigrationError, match=message):
        pipeline_migration.verify_sqlite(source)

@pytest.fixture
def postgres_pipeline(monkeypatch: pytest.MonkeyPatch):
    database_url = os.environ.get("NYANKOFACE_PIPELINE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("NYANKOFACE_PIPELINE_TEST_DATABASE_URL is not configured")
    schema = f"pipeline_test_{uuid.uuid4().hex[:16]}"
    monkeypatch.setattr(config, "DATABASE_URL", database_url)
    monkeypatch.setattr(config, "PIPELINE_DB_SCHEMA", schema)
    pipeline_control.initialize()
    try:
        yield database_url, schema
    finally:
        with psycopg.connect(database_url) as db:
            db.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
def _query(database_url: str, statement: str, params: tuple = ()) -> list[dict]:
    with psycopg.connect(database_url, row_factory=dict_row) as db:
        return [dict(row) for row in db.execute(statement, params).fetchall()]

def test_schema_is_idempotent_and_has_explicit_contract(postgres_pipeline) -> None:
    database_url, schema = postgres_pipeline
    pipeline_control.initialize()
    assert pipeline_control.database_ready()
    tables = {
        row["table_name"]
        for row in _query(
            database_url,
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = %s
            """,
            (schema,),
        )
    }
    assert tables == {
        "schema_migrations",
        "pipeline_audit",
        "pipeline_reconcile_state",
        "pipeline_reconcile_cursor",
        "sqlite_migrations",
    }
    indexes = {
        row["indexname"]
        for row in _query(
            database_url,
            "SELECT indexname FROM pg_indexes WHERE schemaname = %s",
            (schema,),
        )
    }
    assert {
        "pipeline_audit_repository_history",
        "pipeline_audit_reconcile_lookup",
        "pipeline_audit_production_revision",
        "pipeline_reconcile_due",
    }.issubset(indexes)
    assert _query(
        database_url,
        f'SELECT version FROM "{schema}".schema_migrations',
    ) == [{"version": 1}]

def test_unknown_schema_version_fails_closed(postgres_pipeline) -> None:
    database_url, schema = postgres_pipeline
    with psycopg.connect(database_url) as db:
        db.execute(
            sql.SQL("INSERT INTO {}.schema_migrations(version) VALUES(99)").format(
                sql.Identifier(schema)
            )
        )
    assert not pipeline_control.database_ready()
    with pytest.raises(RuntimeError, match="newer"):
        pipeline_control.initialize()

def test_concurrent_identical_reconcile_transition_is_recorded_once(postgres_pipeline) -> None:
    _database_url, _schema = postgres_pipeline
    def write_state() -> None:
        pipeline_control.record_production_reconcile_state(
            "acme",
            "site",
            run_number=11,
            state="watch",
            run_id=73,
            fingerprint="f" * 64,
            updated="2026-08-05T00:00:00Z",
            attempt=1,
            artifact_id=503,
            expires_at="2026-10-29T00:00:00Z",
            revision="a" * 40,
            force=True,
        )
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _item: write_state(), range(8)))
    state = pipeline_control.latest_production_reconcile_state("acme", "site", 11)
    assert state is not None and state["state"] == "watch"
    rows = _query(
        config.DATABASE_URL,
        f'''SELECT COUNT(*) AS count FROM "{config.PIPELINE_DB_SCHEMA}".pipeline_reconcile_state
            WHERE owner = 'acme' AND repo = 'site' AND run_number = 11''',
    )
    assert rows[0]["count"] == 1
    audit_rows = _query(
        config.DATABASE_URL,
        f'''SELECT COUNT(*) AS count FROM "{config.PIPELINE_DB_SCHEMA}".pipeline_audit
            WHERE owner = 'acme' AND repo = 'site'
              AND action = '_reconcile_production_state' AND run_number = 11''',
    )
    assert audit_rows[0]["count"] == 1

def test_concurrent_cursor_advancement_keeps_highest_watermark(postgres_pipeline) -> None:
    _database_url, _schema = postgres_pipeline
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda number: pipeline_control.record_production_reconcile_cursor(
                    "acme", "site", number
                ),
                range(1, 25),
            )
        )
    assert pipeline_control.production_reconcile_cursor("acme", "site") == 24

def _legacy_pipeline_db(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.execute(
            """
            CREATE TABLE pipeline_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner TEXT NOT NULL,
                repo TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT NOT NULL,
                run_number INTEGER,
                workflow TEXT,
                environment TEXT,
                revision TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        state = {
            "v": 1,
            "state": "watch",
            "run_id": 73,
            "fingerprint": "f" * 64,
            "updated": "2026-08-05T00:00:00Z",
            "attempt": 1,
            "artifact_id": 503,
            "expires_at": "2026-10-29T00:00:00Z",
        }
        db.executemany(
            """
            INSERT INTO pipeline_audit(
                id, owner, repo, action, actor, run_number, workflow,
                environment, revision, created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (1, "acme", "site", "install", "alice", None, "workflow.yml", None, None, "2026-08-05T00:00:00+00:00"),
                (2, "acme", "site", "deploy_production", "alice", 11, None, "production", "a" * 40, "2026-08-05T00:00:01+00:00"),
                (3, "acme", "site", "_reconcile_production_state", "nyankoface-deployer", 11, json.dumps(state, sort_keys=True, separators=(",", ":")), "watch", "a" * 40, "2026-08-05T00:00:02+00:00"),
                (4, "acme", "site", "_reconcile_production_cursor", "nyankoface-deployer", 24, "v1", "production", None, "2026-08-05T00:00:03+00:00"),
            ],
        )


def test_explicit_sqlite_migration_is_validated_idempotent_and_stateful(
    postgres_pipeline,
    tmp_path: Path,
) -> None:
    database_url, _schema = postgres_pipeline
    source = tmp_path / "pipeline-audit.db"
    _legacy_pipeline_db(source)
    before = source.read_bytes()
    verified = pipeline_migration.verify_sqlite(source)
    assert verified["row_count"] == 4
    migrated = pipeline_migration.migrate_sqlite(source)
    assert migrated["row_count"] == 4
    assert migrated["already_migrated"] is False
    repeated = pipeline_migration.migrate_sqlite(source)
    assert repeated["already_migrated"] is True
    assert source.read_bytes() == before
    assert pipeline_control.recorded_production_revision("acme", "site", 11) == "a" * 40
    assert pipeline_control.production_reconcile_cursor("acme", "site") == 24
    assert pipeline_control.latest_production_reconcile_state("acme", "site", 11)["state"] == "watch"
    assert [item["action"] for item in pipeline_control.list_audit("acme", "site")] == [
        "deploy_production",
        "install",
    ]
    assert _query(
        database_url,
        f'''SELECT COUNT(*) AS count FROM "{config.PIPELINE_DB_SCHEMA}".pipeline_audit''',
    )[0]["count"] == 4


def test_sqlite_migration_accepts_reconcile_state_and_cursor_advancement(
    postgres_pipeline,
    tmp_path: Path,
) -> None:
    database_url, schema = postgres_pipeline
    source = tmp_path / "pipeline-audit.db"
    _legacy_pipeline_db(source)
    pipeline_migration.migrate_sqlite(source)
    with psycopg.connect(database_url) as db:
        db.execute(
            sql.SQL(
                "UPDATE {} SET checked_at = checked_at + INTERVAL '1 minute'"
                " WHERE owner = 'acme' AND repo = 'site' AND run_number = 11"
            ).format(sql.Identifier(schema, "pipeline_reconcile_state"))
        )
    refreshed = pipeline_migration.migrate_sqlite(source)
    assert refreshed["already_migrated"] is True
    pipeline_control.record_production_reconcile_state(
        "acme",
        "site",
        run_number=11,
        state="terminal",
        run_id=73,
        fingerprint="f" * 64,
        updated="2026-08-05T01:00:00Z",
        attempt=2,
        artifact_id=504,
        expires_at="2026-10-29T01:00:00Z",
        revision="a" * 40,
    )
    pipeline_control.record_production_reconcile_cursor("acme", "site", 25)
    # The fixture's historical source timestamps are fixed.  Move the newly
    # created reconciliation events after that source point so the test models
    # a real post-migration advancement even when the container clock is older.
    with psycopg.connect(database_url) as db:
        db.execute(
            sql.SQL(
                "UPDATE {} SET checked_at = %s"
                " WHERE owner = 'acme' AND repo = 'site' AND run_number = 11"
            ).format(sql.Identifier(schema, "pipeline_reconcile_state")),
            ("2026-08-05T00:00:04+00:00",),
        )
        db.execute(
            sql.SQL(
                "UPDATE {} SET created_at = %s"
                " WHERE id = (SELECT last_audit_id FROM {}"
                " WHERE owner = 'acme' AND repo = 'site' AND run_number = 11)"
            ).format(
                sql.Identifier(schema, "pipeline_audit"),
                sql.Identifier(schema, "pipeline_reconcile_state"),
            ),
            ("2026-08-05T00:00:04+00:00",),
        )
        db.execute(
            sql.SQL(
                "UPDATE {} SET updated_at = %s"
                " WHERE owner = 'acme' AND repo = 'site'"
            ).format(sql.Identifier(schema, "pipeline_reconcile_cursor")),
            ("2026-08-05T00:00:05+00:00",),
        )
        db.execute(
            sql.SQL(
                "UPDATE {} SET created_at = %s"
                " WHERE id = (SELECT last_audit_id FROM {}"
                " WHERE owner = 'acme' AND repo = 'site')"
            ).format(
                sql.Identifier(schema, "pipeline_audit"),
                sql.Identifier(schema, "pipeline_reconcile_cursor"),
            ),
            ("2026-08-05T00:00:05+00:00",),
        )
    advanced = pipeline_migration.migrate_sqlite(source)
    assert advanced["already_migrated"] is True


def test_sqlite_migration_rejects_tampered_advanced_reconcile_audit(
    postgres_pipeline,
    tmp_path: Path,
) -> None:
    database_url, schema = postgres_pipeline
    source = tmp_path / "pipeline-audit.db"
    _legacy_pipeline_db(source)
    pipeline_migration.migrate_sqlite(source)
    pipeline_control.record_production_reconcile_state(
        "acme",
        "site",
        run_number=11,
        state="terminal",
        run_id=73,
        fingerprint="f" * 64,
        updated="2026-08-05T01:00:00Z",
        attempt=2,
        artifact_id=504,
        expires_at="2026-10-29T01:00:00Z",
        revision="a" * 40,
    )
    with psycopg.connect(database_url) as db:
        db.execute(
            sql.SQL(
                "UPDATE {} SET environment = 'watch'"
                " WHERE id = (SELECT last_audit_id FROM {}"
                " WHERE owner = 'acme' AND repo = 'site' AND run_number = 11)"
            ).format(
                sql.Identifier(schema, "pipeline_audit"),
                sql.Identifier(schema, "pipeline_reconcile_state"),
            )
        )
    with pytest.raises(
        pipeline_migration.PipelineMigrationError,
        match="reconciliation state failed verification",
    ):
        pipeline_migration.migrate_sqlite(source)


def test_sqlite_migration_rejects_tampered_advanced_cursor_audit(
    postgres_pipeline,
    tmp_path: Path,
) -> None:
    database_url, schema = postgres_pipeline
    source = tmp_path / "pipeline-audit.db"
    _legacy_pipeline_db(source)
    pipeline_migration.migrate_sqlite(source)
    pipeline_control.record_production_reconcile_cursor("acme", "site", 25)
    with psycopg.connect(database_url) as db:
        db.execute(
            sql.SQL("UPDATE {} SET updated_at = %s WHERE owner = 'acme' AND repo = 'site'").format(
                sql.Identifier(schema, "pipeline_reconcile_cursor")
            ),
            ("2026-08-05T00:00:05+00:00",),
        )
        db.execute(
            sql.SQL(
                "UPDATE {} SET created_at = %s"
                " WHERE id = (SELECT last_audit_id FROM {}"
                " WHERE owner = 'acme' AND repo = 'site')"
            ).format(
                sql.Identifier(schema, "pipeline_audit"),
                sql.Identifier(schema, "pipeline_reconcile_cursor"),
            ),
            ("2026-08-05T00:00:05+00:00",),
        )
        db.execute(
            sql.SQL(
                "UPDATE {} SET workflow = 'tampered'"
                " WHERE id = (SELECT last_audit_id FROM {}"
                " WHERE owner = 'acme' AND repo = 'site')"
            ).format(
                sql.Identifier(schema, "pipeline_audit"),
                sql.Identifier(schema, "pipeline_reconcile_cursor"),
            )
        )
    with pytest.raises(
        pipeline_migration.PipelineMigrationError,
        match="reconciliation cursor failed verification",
    ):
        pipeline_migration.migrate_sqlite(source)


def test_sqlite_migration_rejects_tampered_migrated_audit_row(
    postgres_pipeline,
    tmp_path: Path,
) -> None:
    database_url, schema = postgres_pipeline
    source = tmp_path / "pipeline-audit.db"
    _legacy_pipeline_db(source)
    pipeline_migration.migrate_sqlite(source)
    with psycopg.connect(database_url) as db:
        db.execute(
            sql.SQL("UPDATE {} SET actor = 'tampered' WHERE id = 1").format(
                sql.Identifier(schema, "pipeline_audit")
            )
        )
    with pytest.raises(
        pipeline_migration.PipelineMigrationError,
        match="recorded SQLite migration failed verification",
    ):
        pipeline_migration.migrate_sqlite(source)
