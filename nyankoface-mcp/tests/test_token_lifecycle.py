import hashlib
import errno
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from nyankoface_mcp.admin import main as admin_main
from nyankoface_mcp.lifecycle import (
    AdminContext,
    LifecycleError,
    LifecycleUnavailable,
    REAUTH_MAX_AGE_SECONDS,
    TokenLifecycleStore,
)


def context(now: int = 1_000, *, admin: bool = True, age: int = 0) -> AdminContext:
    return AdminContext("user:admin", admin, now - age)


def service(store: TokenLifecycleStore, now: int = 1_000) -> None:
    store.create_service_account(
        context(now),
        subject_id="service:reader",
        forgejo_user_id=44,
        forgejo_token_file="/run/secrets/reader-pat",
        allowed_scopes=["catalog:read", "repos:read"],
        repository_permissions={"nyankoface/demo": "read"},
        now=now,
    )


@pytest.mark.parametrize(
    "invalid",
    [
        "",
        "invalid\nidentifier",
        "invalid\u0085identifier",
        "invalid\u200bidentifier",
        "invalid\ud800identifier",
    ],
)
def test_rejects_new_non_printable_governance_identifiers(tmp_path, invalid):
    store = TokenLifecycleStore(tmp_path / "registry.json")
    with pytest.raises(LifecycleError, match="subject identifier"):
        store.create_service_account(
            context(), subject_id=invalid, forgejo_user_id=44,
            forgejo_token_file="/run/secrets/reader-pat", allowed_scopes=["repos:read"],
            repository_permissions={"nyankoface/demo": "read"}, now=1_000,
        )
    service(store)
    with pytest.raises(LifecycleError, match="client identifier"):
        store.issue(context(), subject_id="service:reader", client_id=invalid,
                    scopes=["repos:read"], repositories=["nyankoface/demo"], now=1_000)


@pytest.mark.parametrize("invalid", [
    "service account",
    "service/account",
    "サービス:agent",
    "service:" + "x" * 128,
    ".",
    "..",
])
def test_rejects_service_account_ids_not_supported_by_action_routes(tmp_path, invalid):
    store = TokenLifecycleStore(tmp_path / "registry.json")
    with pytest.raises(LifecycleError, match="subject identifier"):
        store.create_service_account(
            context(), subject_id=invalid, forgejo_user_id=44,
            forgejo_token_file="/run/secrets/reader-pat", allowed_scopes=["repos:read"],
            repository_permissions={"nyankoface/demo": "read"}, now=1_000,
        )


def test_issue_returns_plaintext_once_and_never_persists_or_enumerates_it(tmp_path):
    store = TokenLifecycleStore(tmp_path / "registry.json")
    service(store)
    issued = store.issue(
        context(), subject_id="service:reader", client_id="codex",
        scopes=["repos:read"], repositories=["nyankoface/demo"], ttl_seconds=60, now=1_000,
    )

    registry = (tmp_path / "registry.json").read_text(encoding="utf-8")
    audit = (tmp_path / "registry.audit.jsonl").read_text(encoding="utf-8")
    listed = store.list_tokens(context(), now=1_000)
    assert issued.token not in registry
    assert issued.token not in audit
    assert issued.token not in json.dumps(listed)
    assert hashlib.sha256(issued.token.encode()).hexdigest() in registry
    assert all("token_sha256" not in item and "forgejo_token_file" not in item for item in listed)


def test_revocation_expiry_rotation_and_concurrent_rotation_are_immediate(tmp_path):
    store = TokenLifecycleStore(tmp_path / "registry.json")
    service(store)
    issued = store.issue(
        context(), subject_id="service:reader", client_id="codex",
        scopes=["repos:read"], repositories=["nyankoface/demo"], ttl_seconds=60, now=1_000,
    )
    digest = hashlib.sha256(issued.token.encode()).hexdigest()
    assert store.find_digest(digest, now=1_000)

    def rotate():
        try:
            contender = TokenLifecycleStore(tmp_path / "registry.json")
            return contender.rotate(
                context(1_001), issued.metadata["token_id"], ttl_seconds=60, now=1_001
            )
        except LifecycleError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: rotate(), range(2)))
    rotated = [result for result in results if result]
    assert len(rotated) == 1
    assert store.find_digest(digest, now=1_001) is None
    new_digest = hashlib.sha256(rotated[0].token.encode()).hexdigest()
    assert store.find_digest(new_digest, now=1_001)
    assert store.find_digest(new_digest, now=1_062) is None


def test_rotation_returns_active_credential_when_directory_fsync_is_unsupported(
    tmp_path, monkeypatch,
):
    store = TokenLifecycleStore(tmp_path / "registry.json")
    service(store)
    issued = store.issue(
        context(), subject_id="service:reader", client_id="codex",
        scopes=["repos:read"], repositories=["nyankoface/demo"], ttl_seconds=60, now=1_000,
    )
    old_digest = hashlib.sha256(issued.token.encode()).hexdigest()
    monkeypatch.setattr(
        store,
        "_sync_registry_directory",
        lambda: (_ for _ in ()).throw(OSError(errno.EINVAL, "directory fsync unsupported")),
    )

    rotated = store.rotate(
        context(1_001), issued.metadata["token_id"], ttl_seconds=60, now=1_001
    )

    new_digest = hashlib.sha256(rotated.token.encode()).hexdigest()
    assert store.find_digest(old_digest, now=1_001) is None
    assert store.find_digest(new_digest, now=1_001)


def test_rotation_translates_directory_fsync_io_failure(tmp_path, monkeypatch):
    store = TokenLifecycleStore(tmp_path / "registry.json")
    monkeypatch.setattr(
        store, "_sync_registry_directory",
        lambda: (_ for _ in ()).throw(OSError(errno.EIO, "directory fsync failed")),
    )
    with pytest.raises(LifecycleUnavailable, match="token store is unavailable"):
        store._write({"version": 2, "subjects": [], "tokens": []})
    assert not store.registry_path.exists()


def test_new_registry_tree_allows_unsupported_directory_fsync(tmp_path, monkeypatch):
    store = TokenLifecycleStore(tmp_path / "new" / "nested" / "registry.json")
    monkeypatch.setattr(store, "_sync_directory", lambda _path: (_ for _ in ()).throw(
        OSError(errno.ENOTSUP, "directory fsync unsupported")))
    service(store)
    assert store.registry_path.exists()
    assert json.loads(store.registry_path.read_text(encoding="utf-8"))["audit_outbox"] == []
    assert store.audit_path.read_text(encoding="utf-8").count('"event": "service_account.created"') == 1


def test_new_registry_tree_retries_failed_ancestor_directory_sync(tmp_path, monkeypatch):
    store = TokenLifecycleStore(tmp_path / "new" / "nested" / "registry.json")
    failed_parent = tmp_path / "new"
    attempts: list[object] = []
    failed_once = False

    def sync(directory):
        nonlocal failed_once
        attempts.append(directory)
        if directory == failed_parent and not failed_once:
            failed_once = True
            raise OSError(errno.EIO, "ancestor directory fsync failed")

    monkeypatch.setattr(store, "_sync_directory", sync)
    with pytest.raises(OSError, match="ancestor directory fsync failed"):
        store._mkdir_durable(store.registry_path.parent)

    attempts.clear()
    store._mkdir_durable(store.registry_path.parent)
    assert failed_parent in attempts


@pytest.mark.parametrize("mutation", ["scope_escalation", "empty_repositories"])
def test_runtime_rejects_manually_broadened_service_token(tmp_path, mutation):
    store = TokenLifecycleStore(tmp_path / "registry.json")
    service(store)
    issued = store.issue(
        context(), subject_id="service:reader", client_id="codex",
        scopes=["repos:read"], repositories=["nyankoface/demo"], ttl_seconds=60, now=1_000,
    )
    digest = hashlib.sha256(issued.token.encode()).hexdigest()
    registry = json.loads(store.registry_path.read_text(encoding="utf-8"))
    token = registry["tokens"][0]
    if mutation == "scope_escalation":
        token["scopes"].append("issues:write")
    else:
        token["repositories"] = []
    store.registry_path.write_text(json.dumps(registry), encoding="utf-8")

    assert store.find_digest(digest, now=1_000) is None


@pytest.mark.parametrize("invalid_expiry", [None, "4102444800", 1e999, True, -1])
def test_runtime_rejects_non_integer_or_out_of_range_expiry(tmp_path, invalid_expiry):
    store = TokenLifecycleStore(tmp_path / "registry.json")
    service(store)
    issued = store.issue(context(), subject_id="service:reader", client_id="codex",
                         scopes=["repos:read"], repositories=["nyankoface/demo"], now=1_000)
    registry = json.loads(store.registry_path.read_text(encoding="utf-8"))
    registry["tokens"][0]["expires_at"] = invalid_expiry
    store.registry_path.write_text(json.dumps(registry), encoding="utf-8")
    assert store.find_digest(hashlib.sha256(issued.token.encode()).hexdigest(), now=1_000) is None


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("scopes", ["repos:read", {"unexpected": "object"}]),
        ("allowed_scopes", ["repos:read", {"unexpected": "object"}]),
        ("repositories", ["nyankoface/demo", {"unexpected": "object"}]),
        ("repository_permissions", {"nyankoface/demo": ["read"]}),
    ],
)
def test_runtime_rejects_malformed_authorization_entries(tmp_path, field, invalid_value):
    store = TokenLifecycleStore(tmp_path / "registry.json")
    service(store)
    issued = store.issue(context(), subject_id="service:reader", client_id="codex",
                         scopes=["repos:read"], repositories=["nyankoface/demo"], now=1_000)
    registry = json.loads(store.registry_path.read_text(encoding="utf-8"))
    target = registry["tokens"][0] if field in {"scopes", "repositories"} else registry["subjects"][0]
    target[field] = invalid_value
    store.registry_path.write_text(json.dumps(registry), encoding="utf-8")
    assert store.find_digest(hashlib.sha256(issued.token.encode()).hexdigest(), now=1_000) is None


def test_missing_disabled_or_changed_mapping_fails_closed(tmp_path):
    store = TokenLifecycleStore(tmp_path / "registry.json")
    service(store)
    issued = store.issue(
        context(), subject_id="service:reader", client_id="codex",
        scopes=["repos:read"], repositories=["nyankoface/demo"], ttl_seconds=60, now=1_000,
    )
    digest = hashlib.sha256(issued.token.encode()).hexdigest()
    store.disable_service_account(context(1_001), "service:reader", now=1_001)
    assert store.find_digest(digest, now=1_001) is None


def test_scope_repository_escalation_and_stale_reauthentication_are_denied(tmp_path):
    store = TokenLifecycleStore(tmp_path / "registry.json")
    service(store)
    with pytest.raises(LifecycleError, match="administrator"):
        store.issue(
            context(admin=False), subject_id="service:reader", client_id="bad",
            scopes=["repos:read"], repositories=["nyankoface/demo"], now=1_000,
        )
    with pytest.raises(LifecycleError, match="reauthentication"):
        store.issue(
            context(age=REAUTH_MAX_AGE_SECONDS + 1), subject_id="service:reader", client_id="old",
            scopes=["repos:read"], repositories=["nyankoface/demo"], now=1_000,
        )
    with pytest.raises(LifecycleError, match="repository constraint"):
        store.issue(
            context(), subject_id="service:reader", client_id="wide",
            scopes=["repos:read"], repositories=["nyankoface/other"], now=1_000,
        )
    with pytest.raises(LifecycleError, match="invalid token scopes"):
        store.issue(
            context(), subject_id="service:reader", client_id="admin",
            scopes=["admin:*"], repositories=["nyankoface/demo"], now=1_000,
        )
    with pytest.raises(LifecycleError, match="subject grant"):
        store.issue(
            context(), subject_id="service:reader", client_id="write",
            scopes=["issues:write"], repositories=["nyankoface/demo"], now=1_000,
        )
    for invalid in ("nyankoface/demo name", f"nyankoface/{'x' * 101}"):
        with pytest.raises(LifecycleError, match="repository constraint"):
            store.issue(
                context(), subject_id="service:reader", client_id="invalid",
                scopes=["repos:read"], repositories=[invalid], now=1_000,
            )


def test_metrics_read_scope_can_be_granted_and_issued(tmp_path):
    store = TokenLifecycleStore(tmp_path / "registry.json")
    store.create_service_account(
        context(),
        subject_id="service:metrics",
        forgejo_user_id=45,
        forgejo_token_file="/run/secrets/metrics-pat",
        allowed_scopes=["metrics:read"],
        repository_permissions={"nyankoface/demo": "read"},
        now=1_000,
    )

    issued = store.issue(
        context(),
        subject_id="service:metrics",
        client_id="dashboard",
        scopes=["metrics:read"],
        repositories=["nyankoface/demo"],
        ttl_seconds=60,
        now=1_000,
    )

    assert issued.metadata["scopes"] == ["metrics:read"]


def test_lookup_performs_constant_number_of_digest_comparisons(tmp_path, monkeypatch):
    store = TokenLifecycleStore(tmp_path / "registry.json")
    service(store)
    tokens = [
        store.issue(
            context(), subject_id="service:reader", client_id=f"client-{index}",
            scopes=["repos:read"], repositories=["nyankoface/demo"], now=1_000,
        )
        for index in range(3)
    ]
    calls = 0
    original = __import__("hmac").compare_digest

    def counted(left, right):
        nonlocal calls
        calls += 1
        return original(left, right)

    monkeypatch.setattr("nyankoface_mcp.lifecycle.hmac.compare_digest", counted)
    store.find_digest(hashlib.sha256(tokens[1].token.encode()).hexdigest(), now=1_000)
    known_calls = calls
    calls = 0
    store.find_digest("f" * 64, now=1_000)
    assert calls == known_calls == 3


def test_runtime_lookup_does_not_write_beside_read_only_registry(tmp_path, monkeypatch):
    store = TokenLifecycleStore(tmp_path / "registry.json")
    service(store)
    issued = store.issue(
        context(), subject_id="service:reader", client_id="readonly",
        scopes=["repos:read"], repositories=["nyankoface/demo"], now=1_000,
    )

    def forbidden_lock(*args, **kwargs):
        raise AssertionError("runtime authentication attempted a registry write")

    monkeypatch.setattr(store, "_locked", forbidden_lock)
    digest = hashlib.sha256(issued.token.encode()).hexdigest()
    assert store.find_digest(digest, now=1_000)


def test_remap_requires_fresh_admin_and_revokes_old_credentials(tmp_path):
    store = TokenLifecycleStore(tmp_path / "registry.json")
    service(store)
    issued = store.issue(
        context(), subject_id="service:reader", client_id="codex",
        scopes=["repos:read"], repositories=["nyankoface/demo"], now=1_000,
    )
    store.remap_service_account(
        context(1_001), "service:reader", forgejo_user_id=45,
        forgejo_token_file="/run/secrets/new-reader-pat",
        allowed_scopes=["catalog:read", "repos:read"],
        repository_permissions={"nyankoface/demo": "write"}, now=1_001,
    )
    assert store.find_digest(hashlib.sha256(issued.token.encode()).hexdigest(), now=1_001) is None
    audit = (tmp_path / "registry.audit.jsonl").read_text(encoding="utf-8")
    assert "new-reader-pat" not in audit
    assert "token_sha256" not in audit


def test_invalid_remap_is_rejected_before_revoking_credentials(tmp_path):
    store = TokenLifecycleStore(tmp_path / "registry.json")
    service(store)
    issued = store.issue(
        context(), subject_id="service:reader", client_id="codex",
        scopes=["repos:read"], repositories=["nyankoface/demo"], now=1_000,
    )
    digest = hashlib.sha256(issued.token.encode()).hexdigest()

    with pytest.raises(LifecycleError, match="invalid subject mapping"):
        store.remap_service_account(
            context(1_001), "service:reader", forgejo_user_id=0,
            forgejo_token_file="", allowed_scopes=["repos:read"],
            repository_permissions={"nyankoface/demo": "read"}, now=1_001,
        )

    assert store.find_digest(digest, now=1_001)


def test_rotation_returns_credential_and_retries_audit_delivery(tmp_path, monkeypatch):
    store = TokenLifecycleStore(tmp_path / "registry.json")
    service(store)
    issued = store.issue(
        context(), subject_id="service:reader", client_id="codex",
        scopes=["repos:read"], repositories=["nyankoface/demo"], now=1_000,
    )
    original_append = store._append_audit

    def unavailable(_payload):
        raise OSError("audit volume is full")

    monkeypatch.setattr(store, "_append_audit", unavailable)
    rotated = store.rotate(
        context(1_001), issued.metadata["token_id"], ttl_seconds=60, now=1_001,
    )
    rotated_digest = hashlib.sha256(rotated.token.encode()).hexdigest()
    assert store.find_digest(rotated_digest, now=1_001)
    registry = json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))
    assert [event["event"] for event in registry["audit_outbox"]] == ["token.rotated"]
    assert rotated.token not in json.dumps(registry)

    monkeypatch.setattr(store, "_append_audit", original_append)
    store.revoke(context(1_002), rotated.metadata["token_id"], now=1_002)
    audit = (tmp_path / "registry.audit.jsonl").read_text(encoding="utf-8")
    assert audit.count('"event": "token.rotated"') == 1
    assert '"event": "token.revoked"' in audit
    registry = json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))
    assert registry["audit_outbox"] == []


def test_audit_delivery_syncs_a_separate_parent_before_clearing_outbox(tmp_path, monkeypatch):
    registry_parent = tmp_path / "registry-root" / "nested-registry"
    audit_parent = tmp_path / "outside" / "nested-audit"
    store = TokenLifecycleStore(registry_parent / "registry.json", audit_parent / "events.jsonl")
    synced = []
    original_sync = store._sync_directory
    monkeypatch.setattr(store, "_sync_directory", lambda path: (synced.append(path), original_sync(path))[1])
    service(store)
    assert {registry_parent, registry_parent.parent, audit_parent, audit_parent.parent, tmp_path} <= set(synced)
    assert json.loads(store.registry_path.read_text(encoding="utf-8"))["audit_outbox"] == []


def test_audit_retry_repairs_an_incomplete_trailing_record(tmp_path, monkeypatch):
    registry_path = tmp_path / "registry.json"
    store = TokenLifecycleStore(registry_path)
    service(store)
    original_append = store._append_audit

    def partial_write(_payload):
        with store.audit_path.open("ab") as stream:
            stream.write(b'{"audit_event_id":"partial')
            stream.flush()
            os.fsync(stream.fileno())
        raise OSError("audit volume became unavailable")

    monkeypatch.setattr(store, "_append_audit", partial_write)
    issued = store.issue(
        context(), subject_id="service:reader", client_id="repair",
        scopes=["repos:read"], repositories=["nyankoface/demo"], now=1_000,
    )
    assert issued.token
    assert json.loads(registry_path.read_text(encoding="utf-8"))["audit_outbox"]

    monkeypatch.setattr(store, "_append_audit", original_append)
    store.revoke(context(), token_id=issued.metadata["token_id"], now=1_001)

    parsed = [
        json.loads(line)
        for line in store.audit_path.read_text(encoding="utf-8").splitlines()
    ]
    assert all(item.get("audit_event_id") != "partial" for item in parsed)
    assert [item["event"] for item in parsed].count("token.issued") == 1
    assert [item["event"] for item in parsed].count("token.revoked") == 1
    assert json.loads(registry_path.read_text(encoding="utf-8"))["audit_outbox"] == []


def test_audit_delivery_skips_newline_terminated_invalid_utf8(tmp_path):
    registry_path = tmp_path / "registry.json"
    store = TokenLifecycleStore(registry_path)
    service(store)
    with store.audit_path.open("ab") as stream:
        stream.write(b"\xff\n")

    issued = store.issue(
        context(), subject_id="service:reader", client_id="corrupt-audit",
        scopes=["repos:read"], repositories=["nyankoface/demo"], now=1_000,
    )

    assert issued.token
    valid_events = []
    for line in store.audit_path.read_bytes().splitlines():
        try:
            valid_events.append(json.loads(line.decode("utf-8"))["event"])
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    assert valid_events.count("token.issued") == 1
    assert json.loads(registry_path.read_text(encoding="utf-8"))["audit_outbox"] == []


def test_stale_lock_file_does_not_block_new_operator(tmp_path):
    registry = tmp_path / "registry.json"
    lock_path = registry.with_suffix(".json.lock")
    lock_path.write_text("999999\n", encoding="utf-8")
    store = TokenLifecycleStore(registry)

    service(store)

    assert json.loads(registry.read_text(encoding="utf-8"))["subjects"][0]["subject_id"] == "service:reader"


def test_registry_replacement_syncs_parent_directory(tmp_path, monkeypatch):
    store = TokenLifecycleStore(tmp_path / "registry.json")
    syncs = []
    monkeypatch.setattr(store, "_sync_registry_directory", lambda: syncs.append(True))

    service(store)

    assert syncs == [True, True, True, True]


@pytest.mark.skipif(os.name == "nt", reason="POSIX group ownership contract")
def test_registry_replacements_remain_readable_by_runtime_group(tmp_path, monkeypatch):
    registry = tmp_path / "state" / "registry.json"
    store = TokenLifecycleStore(registry, registry_reader_gid=os.getegid())
    monkeypatch.setattr(
        "nyankoface_mcp.lifecycle.os.chown",
        lambda *_args: (_ for _ in ()).throw(AssertionError("capability-free path must not chown")),
    )

    service(store)

    assert registry.stat().st_gid == os.getegid()
    assert stat.S_IMODE(registry.stat().st_mode) == 0o640
    assert stat.S_IMODE(registry.parent.stat().st_mode) & 0o050 == 0o050


@pytest.mark.skipif(
    os.name == "nt" or not hasattr(os, "geteuid") or os.geteuid() != 0,
    reason="requires a root writer to drop to the production runtime identity",
)
def test_root_writer_registry_is_readable_by_nonroot_runtime_identity():
    root = Path(tempfile.mkdtemp(prefix="nyankoface-mcp-root-reader-", dir="/tmp"))
    try:
        os.chmod(root, 0o755)
        os.chown(root, 12_345, 12_345)
        registry = root / "registry.json"
        store = TokenLifecycleStore(registry, registry_reader_gid=10_001)
        service(store)

        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; print(Path(r'" + str(registry) + "').read_text())",
            ],
            user=10_001,
            group=10_001,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )

        assert '"service:reader"' in completed.stdout
        assert registry.stat().st_gid == 10_001
        assert stat.S_IMODE(registry.stat().st_mode) == 0o640
    finally:
        shutil.rmtree(root)


def test_offline_admin_cli_issues_once_and_lists_only_metadata(tmp_path, capsys):
    registry = tmp_path / "nested" / "registry.json"
    common = ["--registry", str(registry), "--actor", "user:admin"]
    assert admin_main(common + [
        "create-service-account", "service:cli", "--forgejo-user-id", "50",
        "--forgejo-token-file", "/run/secrets/cli-pat",
        "--allowed-scope", "repos:read",
        "--repository-permission", "nyankoface/demo=read",
    ]) == 0
    capsys.readouterr()
    assert admin_main(common + [
        "issue-token", "service:cli", "--client-id", "cli",
        "--scope", "repos:read", "--repository", "nyankoface/demo",
    ]) == 0
    issued = json.loads(capsys.readouterr().out)
    assert len(issued.pop("token")) >= 43
    assert admin_main(common + ["list-tokens"]) == 0
    listed = capsys.readouterr().out
    assert "token_sha256" not in listed
    assert "forgejo_token_file" not in listed
