"""Encrypted, repository-scoped runtime settings for Space containers."""
from __future__ import annotations

import logging
import os
import re
import secrets
import stat
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import psycopg
from cryptography.fernet import Fernet, InvalidToken
from psycopg.rows import dict_row

import config

logger = logging.getLogger("spaces-runner.environment")
ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,126}$")
RESERVED_NAMES = {
    "DOCKER_HOST",
    "FORGEJO_TOKEN",
    "HOME",
    "HOSTNAME",
    "NYANKOFACE_CONTROL_TOKEN",
    "PATH",
}
SettingKind = Literal["variable", "secret"]
SettingScope = Literal["runtime", "build", "both"]
MAX_REPOSITORY_SETTINGS = 128
MAX_DELIVERED_VALUE_BYTES = 131072


def _repository(owner: str, repo: str) -> tuple[str, str]:
    return owner.strip().casefold(), repo.strip().casefold()


def _connect(**kwargs) -> psycopg.Connection:
    return psycopg.connect(config.DATABASE_URL, row_factory=dict_row, **kwargs)


def acquire_mutation_lock(owner: str, repo: str, name: str | None, timeout: float = 5.0):
    owner, repo = _repository(owner, repo)
    normalized = _validate_name(name) if name is not None else None
    deadline = time.monotonic() + timeout
    try:
        db = _connect(connect_timeout=max(1, int(timeout + 0.999)),
                      options=f"-c statement_timeout={max(1, int(timeout * 1000))}")
    except psycopg.OperationalError as exc:
        raise TimeoutError("Environment setting is busy; retry the request") from exc
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        db.close()
        raise TimeoutError("Environment setting is busy; retry the request")
    cancel = threading.Timer(remaining, db.cancel_safe)
    cancel.daemon = True
    cancel.start()
    try:
        db.autocommit = True
        repository = f"space-environment:{owner}/{repo}"
        operation = "pg_try_advisory_lock_shared" if normalized else "pg_try_advisory_lock"
        locks = [(operation, repository)]
        if normalized:
            locks.append(("pg_try_advisory_lock", f"{repository}/{normalized}"))
        for operation, target in locks:
            while time.monotonic() < deadline:
                row = db.execute(
                    f"SELECT {operation}(hashtextextended(%s, 0)) AS locked",
                    (target,),
                ).fetchone()
                if row["locked"]:
                    break
                time.sleep(0.05)
            else:
                raise TimeoutError("Environment setting is busy; retry the request")
        cancel.cancel()
        return db
    except (psycopg.errors.QueryCanceled, psycopg.OperationalError) as exc:
        cancel.cancel()
        db.close()
        raise TimeoutError("Environment setting is busy; retry the request") from exc
    except BaseException:
        cancel.cancel()
        db.close()
        raise
    cancel.cancel()
    db.close()
    raise TimeoutError("Environment setting is busy; retry the request")


def release_mutation_lock(db) -> None:
    try:
        db.execute("SELECT pg_advisory_unlock_all()")
    finally:
        db.close()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _key() -> bytes:
    path = Path(config.SPACE_SECRETS_KEY_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() and not path.is_symlink():
        temporary = path.with_name(
            f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
        )
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        try:
            value = Fernet.generate_key()
            offset = 0
            while offset < len(value):
                written = os.write(descriptor, value[offset:])
                if written <= 0:
                    raise RuntimeError("Space secret key write failed")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
            if os.name != "nt":
                directory = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError("Space secret key must be a regular file") from exc
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode):
            raise RuntimeError("Space secret key must be a regular file")
        if os.name != "nt" and (details.st_uid != os.getuid() or details.st_mode & 0o077):
            raise RuntimeError("Space secret key ownership or mode is unsafe")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 128)
            if not chunk:
                break
            chunks.append(chunk)
            if sum(map(len, chunks)) > 128:
                break
        key = b"".join(chunks).strip()
    finally:
        os.close(descriptor)
    Fernet(key)
    return key


def _cipher() -> Fernet:
    return Fernet(_key())


def initialize() -> None:
    _key()
    with _connect() as db:
        db.execute("CREATE SEQUENCE IF NOT EXISTS space_environment_generation_seq")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS space_environment (
                id BIGSERIAL PRIMARY KEY,
                owner TEXT NOT NULL,
                repo TEXT NOT NULL,
                name TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('variable', 'secret')),
                scope TEXT NOT NULL DEFAULT 'runtime' CHECK (scope = 'runtime'),
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                ciphertext BYTEA NOT NULL,
                generation BIGINT NOT NULL DEFAULT nextval('space_environment_generation_seq'),
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                UNIQUE(owner, repo, name)
            )
            """
        )
        db.execute("LOCK TABLE space_environment IN ACCESS EXCLUSIVE MODE")
        collision = db.execute("""SELECT 1 FROM space_environment
            GROUP BY LOWER(BTRIM(owner)), LOWER(BTRIM(repo)), name HAVING COUNT(*) > 1 LIMIT 1""").fetchone()
        if collision:
            raise RuntimeError("Canonical environment identity collision")
        db.execute("""UPDATE space_environment SET owner = LOWER(BTRIM(owner)), repo = LOWER(BTRIM(repo))
                    WHERE owner <> LOWER(BTRIM(owner)) OR repo <> LOWER(BTRIM(repo))""")
        db.execute(
            """
            ALTER TABLE space_environment
            ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE
            """
        )
        db.execute("ALTER TABLE space_environment ADD COLUMN IF NOT EXISTS generation BIGINT")
        db.execute("UPDATE space_environment SET generation = nextval('space_environment_generation_seq') WHERE generation IS NULL")
        db.execute("""
            SELECT setval('space_environment_generation_seq', MAX(generation), true)
            FROM space_environment
            HAVING MAX(generation) >= (SELECT last_value FROM space_environment_generation_seq)
        """)
        db.execute("ALTER TABLE space_environment ALTER COLUMN generation SET DEFAULT nextval('space_environment_generation_seq')")
        db.execute("ALTER TABLE space_environment ALTER COLUMN generation SET NOT NULL")
        db.execute(
            """
            ALTER TABLE space_environment
            DROP CONSTRAINT IF EXISTS space_environment_scope_check
            """
        )
        db.execute(
            """
            ALTER TABLE space_environment
            ADD CONSTRAINT space_environment_scope_check
            CHECK (scope IN ('runtime', 'build', 'both'))
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS space_environment_audit (
                id BIGSERIAL PRIMARY KEY,
                owner TEXT NOT NULL,
                repo TEXT NOT NULL,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        db.execute("LOCK TABLE space_environment_audit IN ACCESS EXCLUSIVE MODE")
        db.execute("""UPDATE space_environment_audit SET owner = LOWER(BTRIM(owner)), repo = LOWER(BTRIM(repo))
                    WHERE owner <> LOWER(BTRIM(owner)) OR repo <> LOWER(BTRIM(repo))""")


def _validate_name(name: str) -> str:
    normalized = name.strip().upper()
    if not ENV_NAME.fullmatch(normalized):
        raise ValueError("Environment name must match [A-Z_][A-Z0-9_]{0,126}")
    if normalized in RESERVED_NAMES:
        raise ValueError(f"{normalized} is reserved by the NyankoFace runtime")
    return normalized


def _validate_scope(scope: str) -> SettingScope:
    if scope not in ("runtime", "build", "both"):
        raise ValueError("scope must be runtime, build, or both")
    return scope


def list_settings(owner: str, repo: str) -> list[dict]:
    owner, repo = _repository(owner, repo)
    with _connect() as db:
        rows = db.execute(
            """
            SELECT name, kind, scope, enabled, ciphertext, created_at, updated_at
            FROM space_environment
            WHERE owner = %s AND repo = %s
            ORDER BY kind, name
            """,
            (owner, repo),
        ).fetchall()
    cipher = _cipher()
    result = []
    for row in rows:
        item = {
            "name": row["name"],
            "kind": row["kind"],
            "scope": row["scope"],
            "enabled": row["enabled"],
            "configured": True,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        if row["kind"] == "variable":
            try:
                item["value"] = cipher.decrypt(bytes(row["ciphertext"])).decode("utf-8")
            except InvalidToken as exc:
                raise RuntimeError(f"Cannot decrypt variable {row['name']}") from exc
        result.append(item)
    return result


def list_setting_metadata(owner: str, repo: str) -> list[dict]:
    """Return setting metadata without loading or decrypting ciphertext."""
    owner, repo = _repository(owner, repo)
    with _connect() as db:
        rows = db.execute(
            """
            SELECT name, kind, scope, enabled, created_at, updated_at
            FROM space_environment
            WHERE owner = %s AND repo = %s
            ORDER BY kind, name
            """,
            (owner, repo),
        ).fetchall()
    return [{**dict(row), "configured": True} for row in rows]


def get_setting_metadata(owner: str, repo: str, name: str) -> dict | None:
    owner, repo = _repository(owner, repo)
    normalized = _validate_name(name)
    with _connect() as db:
        row = db.execute(
            """
            SELECT name, kind, scope, enabled, generation, created_at, updated_at
            FROM space_environment
            WHERE owner = %s AND repo = %s AND name = %s
            """,
            (owner, repo, normalized),
        ).fetchone()
    return {**dict(row), "configured": True} if row else None


def get_setting(owner: str, repo: str, name: str) -> dict | None:
    """Return one decrypted setting for trusted internal rollback handling."""
    owner, repo = _repository(owner, repo)
    normalized = _validate_name(name)
    with _connect() as db:
        row = db.execute(
            """
            SELECT name, kind, scope, enabled, ciphertext, generation, created_at, updated_at
            FROM space_environment
            WHERE owner = %s AND repo = %s AND name = %s
            """,
            (owner, repo, normalized),
        ).fetchone()
    if not row:
        return None
    try:
        value = _cipher().decrypt(bytes(row["ciphertext"])).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError(f"Cannot decrypt configured value for {normalized}") from exc
    return {
        "name": row["name"],
        "kind": row["kind"],
        "scope": row["scope"],
        "enabled": row["enabled"],
        "value": value,
        "configured": True,
        "generation": row["generation"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def upsert(
    owner: str,
    repo: str,
    name: str,
    kind: SettingKind,
    value: str,
    actor: str = "authorized-forgejo-user",
    enabled: bool = True,
    scope: SettingScope = "runtime",
    expected_kind: SettingKind | None = None,
) -> dict:
    owner, repo = _repository(owner, repo)
    normalized = _validate_name(name)
    normalized_scope = _validate_scope(scope)
    if kind not in ("variable", "secret"):
        raise ValueError("kind must be variable or secret")
    if expected_kind not in (None, "variable", "secret"):
        raise ValueError("expected_kind must be variable or secret")
    if expected_kind is not None and expected_kind != kind:
        raise ValueError("kind must match expected_kind")
    if not value or len(value) > 16384:
        raise ValueError("Value must contain between 1 and 16384 characters")
    ciphertext = _cipher().encrypt(value.encode("utf-8"))
    now = _now()
    with _connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 1))",
                   (f"space-environment-count:{owner}/{repo}",))
        count = db.execute(
            "SELECT COUNT(*) AS count FROM space_environment WHERE owner = %s AND repo = %s",
            (owner, repo),
        ).fetchone()["count"]
        existing = db.execute(
            """
            SELECT kind, generation FROM space_environment
            WHERE owner = %s AND repo = %s AND name = %s
            FOR UPDATE
            """,
            (owner, repo, normalized),
        ).fetchone()
        if not existing and count >= MAX_REPOSITORY_SETTINGS:
            raise ValueError("Repository environment setting limit reached")
        if enabled and normalized_scope in ("runtime", "both"):
            rows = db.execute("""SELECT name, ciphertext FROM space_environment WHERE owner = %s AND repo = %s
                AND enabled = TRUE AND scope IN ('runtime', 'both') AND name <> %s""",
                (owner, repo, normalized)).fetchall()
            cipher = _cipher()
            total = sum(len(row["name"].encode()) + len(cipher.decrypt(
                bytes(row["ciphertext"]))) for row in rows)
            if total + len(normalized.encode()) + len(value.encode()) > MAX_DELIVERED_VALUE_BYTES:
                raise ValueError("Repository environment delivery limit exceeded")
        if existing and expected_kind is not None and existing["kind"] != expected_kind:
            raise ValueError(f"Environment entry is not a {expected_kind}")
        written = db.execute(
            """
            INSERT INTO space_environment(
                owner, repo, name, kind, scope, enabled, ciphertext, generation, created_at, updated_at
            ) VALUES(%s,%s,%s,%s,%s,%s,%s,nextval('space_environment_generation_seq'),%s,%s)
            ON CONFLICT(owner, repo, name) DO UPDATE SET
                kind = EXCLUDED.kind,
                scope = EXCLUDED.scope,
                enabled = EXCLUDED.enabled,
                ciphertext = EXCLUDED.ciphertext,
                generation = EXCLUDED.generation,
                updated_at = EXCLUDED.updated_at
            WHERE %s IS NULL OR space_environment.kind = %s
            RETURNING generation
            """,
            (
                owner,
                repo,
                normalized,
                kind,
                normalized_scope,
                enabled,
                ciphertext,
                now,
                now,
                expected_kind,
                expected_kind,
            ),
        ).fetchone()
        if not written:
            raise ValueError(f"Environment entry is not a {expected_kind}")
        action = (
            "create"
            if not existing
            else "rotate"
            if kind == "secret"
            else "update"
        )
        db.execute(
            """
            INSERT INTO space_environment_audit(
                owner, repo, name, kind, action, actor, created_at
            ) VALUES(%s,%s,%s,%s,%s,%s,%s)
            """,
            (owner, repo, normalized, kind, action, actor, now),
        )
    logger.info(
        "space environment %s owner=%s repo=%s name=%s kind=%s",
        action,
        owner,
        repo,
        normalized,
        kind,
    )
    return {
        "name": normalized,
        "kind": kind,
        "scope": normalized_scope,
        "enabled": enabled,
        "configured": True,
        "generation": written["generation"],
        "updated_at": now,
    }


def set_enabled(
    owner: str,
    repo: str,
    name: str,
    enabled: bool,
    actor: str = "authorized-forgejo-user",
) -> dict | None:
    owner, repo = _repository(owner, repo)
    normalized = _validate_name(name)
    now = _now()
    with _connect() as db:
        if enabled:
            db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 1))",
                       (f"space-environment-count:{owner}/{repo}",))
            rows = db.execute("""SELECT name, ciphertext FROM space_environment WHERE owner = %s AND repo = %s
                AND scope IN ('runtime', 'both') AND (enabled = TRUE OR name = %s)""",
                (owner, repo, normalized)).fetchall()
            cipher = _cipher()
            if sum(len(row["name"].encode()) + len(cipher.decrypt(bytes(row["ciphertext"]))) for row in rows) > MAX_DELIVERED_VALUE_BYTES:
                raise ValueError("Repository environment delivery limit exceeded")
        row = db.execute(
            """
            UPDATE space_environment
            SET enabled = %s, generation = nextval('space_environment_generation_seq'), updated_at = %s
            WHERE owner = %s AND repo = %s AND name = %s
            RETURNING name, kind, scope, enabled, generation, created_at, updated_at
            """,
            (enabled, now, owner, repo, normalized),
        ).fetchone()
        if row:
            db.execute(
                """
                INSERT INTO space_environment_audit(
                    owner, repo, name, kind, action, actor, created_at
                ) VALUES(%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    owner,
                    repo,
                    normalized,
                    row["kind"],
                    "enable" if enabled else "disable",
                    actor,
                    now,
                ),
            )
    if not row:
        return None
    return {
        **dict(row),
        "configured": True,
    }


def restore_if_current(
    owner: str,
    repo: str,
    name: str,
    expected_generation: int,
    previous: dict | None,
) -> bool:
    """Rollback only the generation written by the failed request."""
    owner, repo = _repository(owner, repo)
    normalized = _validate_name(name)
    now = _now()
    with _connect() as db:
        if previous is None:
            row = db.execute(
                """
                DELETE FROM space_environment
                WHERE owner = %s AND repo = %s AND name = %s AND generation = %s
                RETURNING kind
                """,
                (owner, repo, normalized, expected_generation),
            ).fetchone()
        else:
            ciphertext = _cipher().encrypt(str(previous["value"]).encode("utf-8"))
            row = db.execute(
                """
                UPDATE space_environment
                SET kind = %s, scope = %s, enabled = %s, ciphertext = %s,
                    generation = nextval('space_environment_generation_seq'), updated_at = %s
                WHERE owner = %s AND repo = %s AND name = %s AND generation = %s
                RETURNING kind
                """,
                (
                    previous["kind"], previous.get("scope") or "runtime",
                    bool(previous.get("enabled", True)), ciphertext, now,
                    owner, repo, normalized, expected_generation,
                ),
            ).fetchone()
        if row:
            db.execute(
                """
                INSERT INTO space_environment_audit(
                    owner, repo, name, kind, action, actor, created_at
                ) VALUES(%s,%s,%s,%s,'restore','native-sync-rollback',%s)
                """,
                (owner, repo, normalized, row["kind"], now),
            )
    return bool(row)


def delete(
    owner: str,
    repo: str,
    name: str,
    actor: str = "authorized-forgejo-user",
    expected_kind: SettingKind | None = None,
    expected_generation: int | None = None,
) -> bool:
    owner, repo = _repository(owner, repo)
    normalized = _validate_name(name)
    if expected_kind not in (None, "variable", "secret"):
        raise ValueError("expected_kind must be variable or secret")
    now = _now()
    with _connect() as db:
        row = db.execute(
            """
            DELETE FROM space_environment
            WHERE owner = %s AND repo = %s AND name = %s
              AND (%s IS NULL OR kind = %s)
              AND (%s IS NULL OR generation = %s)
            RETURNING kind
            """,
            (
                owner, repo, normalized, expected_kind, expected_kind,
                expected_generation, expected_generation,
            ),
        ).fetchone()
        if row:
            db.execute(
                """
                INSERT INTO space_environment_audit(
                    owner, repo, name, kind, action, actor, created_at
                ) VALUES(%s,%s,%s,%s,'delete',%s,%s)
                """,
                (owner, repo, normalized, row["kind"], actor, now),
            )
    logger.info("space environment delete owner=%s repo=%s name=%s existed=%s", owner, repo, normalized, bool(row))
    return bool(row)


def list_audit(owner: str, repo: str, limit: int = 100) -> list[dict]:
    owner, repo = _repository(owner, repo)
    with _connect() as db:
        rows = db.execute(
            """
            SELECT id, name, kind, action, actor, created_at
            FROM space_environment_audit
            WHERE owner = %s AND repo = %s
            ORDER BY id DESC
            LIMIT %s
            """,
            (owner, repo, max(1, min(limit, 500))),
        ).fetchall()
    return [dict(row) for row in rows]


def _values_for_scopes(
    owner: str,
    repo: str,
    scopes: tuple[SettingScope, ...],
) -> dict[str, dict[str, str]]:
    owner, repo = _repository(owner, repo)
    with _connect() as db:
        rows = db.execute(
            """
            SELECT name, kind, scope, ciphertext FROM space_environment
            WHERE owner = %s AND repo = %s AND scope = ANY(%s) AND enabled = TRUE
            """,
            (owner, repo, list(scopes)),
        ).fetchall()
    cipher = _cipher()
    values: dict[str, dict[str, str]] = {}
    delivered_bytes = 0
    for row in rows:
        try:
            value = cipher.decrypt(bytes(row["ciphertext"])).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError(f"Cannot decrypt configured value for {row['name']}") from exc
        delivered_bytes += len(row["name"].encode()) + len(value.encode())
        if delivered_bytes > MAX_DELIVERED_VALUE_BYTES:
            raise RuntimeError("Repository environment delivery limit exceeded")
        values[row["name"]] = {
            "kind": row["kind"],
            "scope": row["scope"],
            "value": value,
        }
    return values


def runtime_values(owner: str, repo: str) -> dict[str, str]:
    return {
        name: item["value"]
        for name, item in _values_for_scopes(
            owner,
            repo,
            ("runtime", "both"),
        ).items()
    }


def build_settings(owner: str, repo: str) -> dict[str, dict[str, str]]:
    """Return enabled build settings for trusted internal synchronization only."""
    return _values_for_scopes(owner, repo, ("build", "both"))

