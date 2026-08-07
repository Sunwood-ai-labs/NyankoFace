import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

import config
import space_environment


class FakeRows:
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def fetchall(self) -> list[dict]:
        return self.rows


class FakeDatabase:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.query = ""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, query: str, _params: tuple[str, str]) -> FakeRows:
        self.query = query
        return FakeRows(self.rows)


class FakeWriteResult:
    def __init__(self, row: dict | None = None, rows: list[dict] | None = None):
        self.row, self.rows = row, rows or []
    def fetchone(self): return self.row
    def fetchall(self): return self.rows


class FakeWriteDatabase:
    def __init__(self):
        self.params: list[tuple] = []; self.queries: list[str] = []
        self.return_generation, self.count, self.collision, self.delivery_rows = True, 0, False, []
        self.environment_identity = ("Alice", "Repo")

    def __enter__(self): return self
    def __exit__(self, *_args): return None

    def execute(self, query: str, _params: tuple = ()) -> FakeWriteResult:
        self.queries.append(query); self.params.append(_params)
        if "HAVING COUNT(*) > 1" in query: return FakeWriteResult({"collision": True} if self.collision else None)
        if "UPDATE space_environment SET owner" in query: self.environment_identity = tuple(part.casefold() for part in self.environment_identity)
        if "SELECT COUNT(*)" in query: return FakeWriteResult({"count": self.count})
        if "SELECT name, ciphertext" in query: return FakeWriteResult(rows=self.delivery_rows)
        row = {"generation": 1} if self.return_generation and "RETURNING generation" in query else None
        return FakeWriteResult(row)


class GenerationDatabase(FakeWriteDatabase):
    def __init__(self):
        super().__init__()
        self.revision, self.row_generation = 0, None

    def execute(self, query: str, params: tuple = ()) -> FakeWriteResult:
        self.queries.append(query); self.params.append(params)
        if "SELECT COUNT(*)" in query: return FakeWriteResult({"count": 0})
        if "SELECT kind, generation" in query:
            return FakeWriteResult({"kind": "variable", "generation": self.row_generation} if self.row_generation else None)
        if "INSERT INTO space_environment(" in query:
            self.revision += 1; self.row_generation = self.revision
            return FakeWriteResult({"generation": self.row_generation})
        if "UPDATE space_environment" in query and "SET enabled" in query:
            self.revision += 1; self.row_generation = self.revision
            return FakeWriteResult({"name": "APP_TOKEN", "kind": "variable", "scope": "runtime",
                                    "enabled": params[0], "generation": self.row_generation,
                                    "created_at": params[1], "updated_at": params[1]})
        if "DELETE FROM space_environment" in query:
            expected = params[-1]
            if expected == self.row_generation:
                self.row_generation = None; return FakeWriteResult({"kind": "variable"})
        return FakeWriteResult()


def test_environment_name_normalizes_and_validates() -> None:
    assert space_environment._validate_name(" nyankoface_api_key ") == "NYANKOFACE_API_KEY"
    for invalid in (
        "",
        "1TOKEN",
        "HAS-HYPHEN",
        "contains space",
        "lower.dot",
        "PATH",
        "NYANKOFACE_CONTROL_TOKEN",
    ):
        with pytest.raises(ValueError):
            space_environment._validate_name(invalid)


def test_mutation_lock_bounds_connection_and_query(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []
    def unavailable(**kwargs):
        calls.append(kwargs); raise space_environment.psycopg.OperationalError("connect timeout")
    monkeypatch.setattr(space_environment, "_connect", unavailable)
    with pytest.raises(TimeoutError, match="busy"):
        space_environment.acquire_mutation_lock("alice", "repo", "TOKEN", 0.01)
    assert calls[0]["connect_timeout"] == 1 and "statement_timeout" in calls[0]["options"]
    with pytest.raises(ValueError):
        space_environment.acquire_mutation_lock("alice", "repo", "invalid-name", 0.01)
    assert len(calls) == 1
    class Database:
        cancelled = space_environment.threading.Event()
        closed = False
        def cancel_safe(self): self.cancelled.set()
        def execute(self, *_args, **_kwargs):
            assert self.cancelled.wait(0.1); raise space_environment.psycopg.errors.QueryCanceled("query timeout")
        def close(self): self.closed = True
    database = Database(); monkeypatch.setattr(space_environment, "_connect", lambda **_: database)
    started = space_environment.time.monotonic()
    with pytest.raises(TimeoutError, match="busy"):
        space_environment.acquire_mutation_lock("alice", "repo", "TOKEN", 0.01)
    assert database.closed and space_environment.time.monotonic() - started < 0.1
    class Locked:
        def __init__(self): self.calls = []
        def cancel_safe(self): pass
        def execute(self, query, params=()):
            self.calls.append((query, params)); return type("Row", (), {"fetchone": lambda _: {"locked": True}})()
        def close(self): pass
    setting, repository = Locked(), Locked(); connections = iter((setting, repository)); monkeypatch.setattr(space_environment, "_connect", lambda **_: next(connections))
    space_environment.acquire_mutation_lock("Alice", "Repo", "TOKEN"); space_environment.acquire_mutation_lock("alice", "repo", None)
    assert "lock_shared" in setting.calls[0][0] and setting.calls[0][1] == ("space-environment:alice/repo",)
    assert "lock_shared" not in repository.calls[0][0]


def test_persistent_ciphertext_is_not_plaintext(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key_file = tmp_path / "space-secrets.key"
    monkeypatch.setattr(config, "SPACE_SECRETS_KEY_FILE", str(key_file))

    plaintext = b"fake-secret-for-encryption-test"
    ciphertext = space_environment._cipher().encrypt(plaintext)

    assert plaintext not in ciphertext
    assert space_environment._cipher().decrypt(ciphertext) == plaintext
    if os.name != "nt":
        assert key_file.stat().st_mode & 0o777 == 0o600


def test_secret_key_concurrent_initialization_and_restart_are_stable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key_file = tmp_path / "space-secrets.key"
    monkeypatch.setattr(config, "SPACE_SECRETS_KEY_FILE", str(key_file))
    with ThreadPoolExecutor(max_workers=8) as pool:
        keys = list(pool.map(lambda _index: space_environment._key(), range(8)))
    assert len(set(keys)) == 1 and space_environment._key() == keys[0]
    assert len(key_file.read_bytes()) == 44 and not list(tmp_path.glob(".space-secrets.key.*.tmp"))


def test_secret_key_rejects_symlink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key_file = tmp_path / "space-secrets.key"
    target = tmp_path / "other.key"
    target.write_bytes(Fernet.generate_key())
    try:
        key_file.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")
    monkeypatch.setattr(config, "SPACE_SECRETS_KEY_FILE", str(key_file))
    with pytest.raises(RuntimeError, match="regular file"):
        space_environment._key()


def test_list_setting_metadata_never_loads_or_decrypts_ciphertext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = FakeDatabase([{
        "name": "DATABASE_URL",
        "kind": "variable",
        "scope": "runtime",
        "enabled": True,
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-02T00:00:00Z",
    }])
    monkeypatch.setattr(space_environment, "_connect", lambda: database)
    monkeypatch.setattr(
        space_environment,
        "_cipher",
        lambda: (_ for _ in ()).throw(AssertionError("must not decrypt")),
    )

    result = space_environment.list_setting_metadata("alice", "repo")

    assert "ciphertext" not in database.query.casefold()
    assert result == [{"name": "DATABASE_URL", "kind": "variable",
                       "scope": "runtime", "enabled": True, "configured": True,
                       "created_at": "2026-08-01T00:00:00Z",
                       "updated_at": "2026-08-02T00:00:00Z"}]


@pytest.mark.parametrize("kind", ["variable", "secret"])
def test_upsert_return_never_contains_plaintext_value(kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    database = FakeWriteDatabase()
    monkeypatch.setattr(space_environment, "_connect", lambda: database); monkeypatch.setattr(space_environment, "_cipher", lambda: Fernet(Fernet.generate_key()))
    monkeypatch.setattr(space_environment, "_now", lambda: "2026-08-02T00:00:00Z")
    result = space_environment.upsert("alice", "repo", "APP_TOKEN", kind, "must-not-leak")
    assert result == {"name": "APP_TOKEN", "kind": kind, "scope": "runtime",
                      "enabled": True, "configured": True, "generation": 1,
                      "updated_at": "2026-08-02T00:00:00Z"}
    assert "must-not-leak" not in repr(result) and "must-not-leak" not in repr(database.params)
    database.return_generation = False
    with pytest.raises(ValueError, match=f"not a {kind}"):
        space_environment.upsert("alice", "repo", "APP_TOKEN", kind, "new", expected_kind=kind)
    assert "WHERE %s IS NULL OR space_environment.kind = %s" in database.queries[-1]
    assert database.params[-1][-2:] == (kind, kind)


def test_repository_setting_and_delivery_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    database, cipher = FakeWriteDatabase(), Fernet(Fernet.generate_key())
    monkeypatch.setattr(space_environment, "_connect", lambda: database); monkeypatch.setattr(space_environment, "_cipher", lambda: cipher)
    database.count = space_environment.MAX_REPOSITORY_SETTINGS
    with pytest.raises(ValueError, match="setting limit"): space_environment.upsert("Alice", "Repo", "NEW_VALUE", "variable", "x")
    database.count = 0; database.delivery_rows = [{"name": "OLD", "ciphertext": cipher.encrypt(b"x" * space_environment.MAX_DELIVERED_VALUE_BYTES)}]
    with pytest.raises(ValueError, match="delivery limit"): space_environment.upsert("Alice", "Repo", "NEW_VALUE", "variable", "x")
    with pytest.raises(ValueError, match="delivery limit"): space_environment.set_enabled("Alice", "Repo", "NEW_VALUE", True)
    assert not any("INSERT INTO space_environment(" in query for query in database.queries)
    row = {"name": "VALUE", "kind": "variable", "scope": "runtime", "ciphertext": cipher.encrypt(b"x" * (space_environment.MAX_DELIVERED_VALUE_BYTES + 1))}
    monkeypatch.setattr(space_environment, "_connect", lambda: FakeDatabase([row]))
    with pytest.raises(RuntimeError, match="delivery limit"): space_environment.runtime_values("Alice", "Repo")


def test_sequence_prevents_same_clock_aba(monkeypatch: pytest.MonkeyPatch) -> None:
    database = GenerationDatabase()
    monkeypatch.setattr(space_environment, "_connect", lambda: database); monkeypatch.setattr(space_environment, "_cipher", lambda: Fernet(Fernet.generate_key()))
    monkeypatch.setattr(space_environment, "_now", lambda: "same-timestamp")
    first = space_environment.upsert("alice", "repo", "APP_TOKEN", "variable", "one")
    second = space_environment.upsert("alice", "repo", "APP_TOKEN", "variable", "two")
    enabled = space_environment.set_enabled("alice", "repo", "APP_TOKEN", False)
    assert space_environment.delete("alice", "repo", "APP_TOKEN", expected_generation=enabled["generation"])
    recreated = space_environment.upsert("alice", "repo", "APP_TOKEN", "variable", "three")
    assert [first["generation"], second["generation"], enabled["generation"], recreated["generation"]] == [1, 2, 3, 4]
    assert not space_environment.restore_if_current("alice", "repo", "APP_TOKEN", first["generation"], None)
    assert not space_environment.delete("alice", "repo", "APP_TOKEN", expected_generation=first["generation"])


def test_initialize_backfills_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    database = FakeWriteDatabase()
    monkeypatch.setattr(space_environment, "_connect", lambda: database); monkeypatch.setattr(space_environment, "_key", lambda: b"unused")
    space_environment.initialize()
    statements = "\n".join(database.queries)
    assert "LOCK TABLE space_environment IN ACCESS EXCLUSIVE MODE" in statements and "generation BIGINT NOT NULL DEFAULT nextval" in statements
    assert "SET generation = nextval" in statements
    assert "HAVING MAX(generation) >=" in statements
    assert statements.count("SET owner = LOWER(BTRIM(owner)), repo = LOWER(BTRIM(repo))") == 2
    assert database.environment_identity == ("alice", "repo")


def test_initialize_rejects_canonical_identity_collision(monkeypatch: pytest.MonkeyPatch) -> None:
    database = FakeWriteDatabase(); database.collision = True
    monkeypatch.setattr(space_environment, "_connect", lambda: database); monkeypatch.setattr(space_environment, "_key", lambda: b"unused")
    with pytest.raises(RuntimeError, match="Canonical environment identity collision"): space_environment.initialize()
    assert "ciphertext" not in str(database.params)
