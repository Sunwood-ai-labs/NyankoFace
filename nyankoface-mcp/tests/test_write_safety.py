import asyncio
import json
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from nyankoface_mcp.client import WriteResponseError
from nyankoface_mcp.write_safety import (
    WriteCoordinator,
    WriteIdentity,
    WriteSafetyStore,
    fingerprint,
)


def identity(subject="agent:one", tool="create_issue", target="/repos/a/r/issues"):
    return WriteIdentity(subject, tool, "POST", target)


def store(tmp_path, confirmation_ttl=300, idempotency_ttl=86_400):
    return WriteSafetyStore(
        tmp_path / "write.sqlite3", confirmation_ttl, idempotency_ttl,
    )


@pytest.mark.parametrize("changed", ["subject", "tool", "target", "payload"])
def test_confirmation_cannot_be_rebound(tmp_path, changed):
    safety = store(tmp_path)
    original = identity()
    original_payload = fingerprint({"title": "original"})
    token, _ = safety.issue_confirmation(original, original_payload)
    candidate = {
        "subject": identity(subject="agent:two"),
        "tool": identity(tool="update_issue"),
        "target": identity(target="/repos/a/other/issues"),
        "payload": original,
    }[changed]
    payload_hash = fingerprint({"title": "modified"}) if changed == "payload" else original_payload
    with pytest.raises(ToolError, match="valid, unexpired"):
        safety.claim(candidate, payload_hash, token, "key-1")


def test_expired_confirmation_is_rejected(tmp_path, monkeypatch):
    safety = store(tmp_path, confirmation_ttl=1)
    current = int(time.time())
    monkeypatch.setattr(time, "time", lambda: current)
    token, _ = safety.issue_confirmation(identity(), fingerprint({"x": 1}))
    monkeypatch.setattr(time, "time", lambda: current + 2)
    with pytest.raises(ToolError, match="valid, unexpired"):
        safety.claim(identity(), fingerprint({"x": 1}), token, "key")


def test_new_preview_reaps_abandoned_expired_confirmations(tmp_path, monkeypatch):
    safety = store(tmp_path, confirmation_ttl=1)
    current = int(time.time())
    monkeypatch.setattr(time, "time", lambda: current)
    safety.issue_confirmation(identity(), fingerprint({"x": 1}))
    with sqlite3.connect(safety.path) as db:
        assert db.execute("SELECT COUNT(*) FROM confirmations").fetchone()[0] == 1

    monkeypatch.setattr(time, "time", lambda: current + 2)
    safety.issue_confirmation(identity(), fingerprint({"x": 2}))
    with sqlite3.connect(safety.path) as db:
        assert db.execute("SELECT COUNT(*) FROM confirmations").fetchone()[0] == 1


def test_idempotency_namespace_isolated_by_subject_method_and_target(tmp_path):
    safety = store(tmp_path)
    payload_hash = fingerprint({"title": "same"})
    identities = [
        identity(),
        identity(subject="agent:two"),
        WriteIdentity("agent:one", "create_issue", "PATCH", "/repos/a/r/issues"),
        identity(target="/repos/a/other/issues"),
    ]
    namespaces = set()
    for item in identities:
        token, _ = safety.issue_confirmation(item, payload_hash)
        claim = safety.claim(item, payload_hash, token, "same-key")
        namespaces.add(claim.namespace)
        safety.complete(claim.namespace, {"status": "completed"})
    assert len(namespaces) == len(identities)


def test_confirmation_is_single_use_even_with_a_new_idempotency_key(tmp_path):
    safety = store(tmp_path)
    payload_hash = fingerprint({"title": "same"})
    token, _ = safety.issue_confirmation(identity(), payload_hash)
    first = safety.claim(identity(), payload_hash, token, "first")
    safety.complete(first.namespace, {"status": "completed"})
    with pytest.raises(ToolError, match="valid, unexpired"):
        safety.claim(identity(), payload_hash, token, "second")


def test_expired_pending_claim_remains_non_dispatchable(tmp_path, monkeypatch):
    safety = WriteSafetyStore(tmp_path / "write.sqlite3", 300, 1)
    current = int(time.time())
    monkeypatch.setattr(time, "time", lambda: current)
    payload_hash = fingerprint({"title": "may have reached upstream"})
    token, _ = safety.issue_confirmation(identity(), payload_hash)
    first = safety.claim(identity(), payload_hash, token, "process-crash")

    monkeypatch.setattr(time, "time", lambda: current + 2)
    replacement, _ = safety.issue_confirmation(identity(), payload_hash)
    retry = safety.claim(identity(), payload_hash, replacement, "process-crash")
    assert retry.operation_id == first.operation_id
    assert retry.replay["status"] == "running"

    with sqlite3.connect(safety.path) as db:
        row = db.execute(
            "SELECT namespace, status FROM idempotency WHERE namespace = ?",
            (first.namespace,),
        ).fetchone()
    assert row == (first.namespace, "pending")


def test_expired_completed_key_can_be_reused_without_deleting_history(
    tmp_path, monkeypatch,
):
    safety = WriteSafetyStore(tmp_path / "write.sqlite3", 300, 1)
    current = int(time.time())
    monkeypatch.setattr(time, "time", lambda: current)
    payload_hash = fingerprint({"title": "safe retry"})
    token, _ = safety.issue_confirmation(identity(), payload_hash)
    first = safety.claim(identity(), payload_hash, token, "reusable")
    safety.complete(first.namespace, {"status": "completed"})

    monkeypatch.setattr(time, "time", lambda: current + 2)
    replacement, _ = safety.issue_confirmation(identity(), payload_hash)
    second = safety.claim(identity(), payload_hash, replacement, "reusable")

    assert second.operation_id != first.operation_id
    assert second.replay is None
    assert safety.get_operation("agent:one", first.operation_id)["state"] == "completed"
    assert safety.get_operation("agent:one", second.operation_id)["state"] == "running"


def test_legacy_unresolved_claim_blocks_new_keys_after_schema_upgrade(tmp_path):
    path = tmp_path / "write.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("""
            CREATE TABLE idempotency (
                namespace TEXT PRIMARY KEY,
                payload_fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                result_json TEXT,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            )
        """)
        db.execute(
            "INSERT INTO idempotency VALUES ('legacy', 'hash', 'pending', NULL, 1, 2)"
        )

    safety = WriteSafetyStore(path)
    payload_hash = fingerprint({"title": "must not dispatch"})
    token, _ = safety.issue_confirmation(identity(), payload_hash)
    with pytest.raises(ToolError, match="legacy unresolved"):
        safety.claim(identity(), payload_hash, token, "different-key")
    safety.resolve_legacy_claim("legacy")
    safety.claim(identity(), payload_hash, token, "different-key")


def test_authorized_reconciliation_preserves_history_and_releases_target(tmp_path):
    safety = store(tmp_path)
    item = identity(tool="dispatch_pipeline", target="/pipelines/a/r")
    payload_hash = fingerprint({"ref": "main"})
    token, _ = safety.issue_confirmation(item, payload_hash)
    first = safety.claim(item, payload_hash, token, "unknown")
    safety.complete(first.namespace, {
        "status": "indeterminate",
        "error": {"code": "upstream_outcome_unknown", "retry_safe": False},
    })

    reconciled = safety.reconcile_operation("agent:one", first.operation_id, "applied")
    replacement, _ = safety.issue_confirmation(item, payload_hash)
    second = safety.claim(item, payload_hash, replacement, "later-operation")
    original = safety.get_operation("agent:one", first.operation_id)

    assert reconciled["state"] == "reconciled"
    assert original["result"]["error"]["code"] == "upstream_outcome_unknown"
    assert original["result"]["reconciliation"]["resolution"] == "applied"
    assert second.operation_id != first.operation_id


def test_abandoned_running_operation_can_be_reconciled_after_lease(tmp_path):
    safety = store(tmp_path)
    item = identity(tool="deploy_pages", target="/pages/a/r")
    payload_hash = fingerprint({"method": "docs"})
    token, _ = safety.issue_confirmation(item, payload_hash)
    claim = safety.claim(item, payload_hash, token, "abandoned")
    with sqlite3.connect(safety.path) as db:
        db.execute(
            "UPDATE operations SET updated_at = 1 WHERE operation_id = ?",
            (claim.operation_id,),
        )

    result = safety.reconcile_operation(
        "agent:one", claim.operation_id, "not_applied",
    )
    assert result["state"] == "reconciled"
    assert safety.claim(item, payload_hash, "unused", "abandoned").replay["reconciliation"]


@pytest.mark.asyncio
async def test_running_mutation_renews_lease_before_reconciliation(tmp_path):
    safety = store(tmp_path)
    coordinator = WriteCoordinator(safety, heartbeat_seconds=0.01)
    started = asyncio.Event()
    release = asyncio.Event()

    async def allowed():
        return None

    async def mutate():
        started.set()
        await release.wait()
        return {"status": "published"}

    item = identity(tool="deploy_pages", target="/pages/a/r")
    payload = {"method": "docs"}
    preview = await coordinator.run(
        identity=item, payload=payload, preview=True, dry_run=None,
        confirmation="", idempotency_key="", authorize=allowed, mutate=mutate,
    )
    running = asyncio.create_task(coordinator.run(
        identity=item, payload=payload, preview=False, dry_run=None,
        confirmation=preview["confirmation"], idempotency_key="live",
        authorize=allowed, mutate=mutate,
    ))
    await started.wait()
    with sqlite3.connect(safety.path) as db:
        db.execute("UPDATE operations SET updated_at = 1 WHERE state = 'running'")
    await asyncio.sleep(0.03)
    operation_id = safety.claim(item, fingerprint(payload), "unused", "live").operation_id
    with pytest.raises(ToolError, match="Only an unresolved operation"):
        safety.reconcile_operation("agent:one", operation_id, "not_applied")
    release.set()
    await running


@pytest.mark.asyncio
async def test_reconciled_operation_cannot_be_overwritten_by_resumed_mutation(tmp_path):
    safety = store(tmp_path)
    coordinator = WriteCoordinator(safety, heartbeat_seconds=60)
    started = asyncio.Event()
    release = asyncio.Event()

    async def allowed():
        return None

    async def mutate():
        started.set()
        await release.wait()
        return {"status": "published"}

    item = identity(tool="deploy_pages", target="/pages/a/r")
    payload = {"method": "docs"}
    preview = await coordinator.run(
        identity=item, payload=payload, preview=True, dry_run=None,
        confirmation="", idempotency_key="", authorize=allowed, mutate=mutate,
    )
    running = asyncio.create_task(coordinator.run(
        identity=item, payload=payload, preview=False, dry_run=None,
        confirmation=preview["confirmation"], idempotency_key="paused",
        authorize=allowed, mutate=mutate,
    ))
    await started.wait()
    claim = safety.claim(item, fingerprint(payload), "unused", "paused")
    with sqlite3.connect(safety.path) as db:
        db.execute("UPDATE operations SET updated_at = 1 WHERE state = 'running'")
    safety.reconcile_operation("agent:one", claim.operation_id, "not_applied")
    release.set()
    with pytest.raises(ToolError, match="lease was lost"):
        await running
    assert safety.get_operation("agent:one", claim.operation_id)["state"] == "reconciled"


@pytest.mark.asyncio
async def test_same_key_same_payload_replays_without_second_mutation(tmp_path):
    coordinator = WriteCoordinator(store(tmp_path))
    mutations = 0

    async def authorize():
        return None

    async def mutate():
        nonlocal mutations
        mutations += 1
        return {"number": 9}

    preview = await coordinator.run(
        identity=identity(), payload={"title": "safe"}, preview=True, dry_run=None,
        confirmation="", idempotency_key="", authorize=authorize, mutate=mutate,
    )
    first = await coordinator.run(
        identity=identity(), payload={"title": "safe"}, preview=False, dry_run=None,
        confirmation=preview["confirmation"], idempotency_key="one",
        authorize=authorize, mutate=mutate,
    )
    replay = await coordinator.run(
        identity=identity(), payload={"title": "safe"}, preview=False, dry_run=None,
        confirmation="not-needed-for-replay", idempotency_key="one",
        authorize=authorize, mutate=mutate,
    )
    assert first["status"] == "completed"
    assert replay["replayed"] is True
    assert replay["result"] == first["result"]
    assert mutations == 1


@pytest.mark.asyncio
async def test_operation_is_durable_and_subject_bound_across_instances(tmp_path):
    path = tmp_path / "write.sqlite3"
    coordinator = WriteCoordinator(WriteSafetyStore(path))

    async def allowed():
        return None

    async def mutate():
        return {"status": "queued"}

    item = identity(tool="start_space", target="/spaces/a/r")
    preview = await coordinator.run(
        identity=item, payload={"action": "start"}, preview=True, dry_run=None,
        confirmation="", idempotency_key="", authorize=allowed, mutate=mutate,
    )
    result = await coordinator.run(
        identity=item, payload={"action": "start"}, preview=False, dry_run=None,
        confirmation=preview["confirmation"], idempotency_key="start-1",
        authorize=allowed, mutate=mutate,
    )

    restarted = WriteSafetyStore(path)
    operation = restarted.get_operation("agent:one", result["operation_id"])
    assert operation["state"] == "completed"
    assert operation["result"]["result"] == {"status": "queued"}
    with pytest.raises(ToolError, match="not found or is not authorized"):
        restarted.get_operation("agent:two", result["operation_id"])


@pytest.mark.asyncio
async def test_different_actions_on_same_target_cannot_run_concurrently(tmp_path):
    coordinator = WriteCoordinator(store(tmp_path))
    started = asyncio.Event()
    release = asyncio.Event()

    async def allowed():
        return None

    async def wait_mutation():
        started.set()
        await release.wait()
        return {"status": "running"}

    async def stop_mutation():
        return {"status": "stopped"}

    start_identity = identity(tool="start_space", target="/spaces/a/r")
    stop_identity = identity(tool="stop_space", target="/spaces/a/r")
    start_preview = await coordinator.run(
        identity=start_identity, payload={"action": "start"}, preview=True,
        dry_run=None, confirmation="", idempotency_key="",
        authorize=allowed, mutate=wait_mutation,
    )
    stop_preview = await coordinator.run(
        identity=stop_identity, payload={"action": "stop"}, preview=True,
        dry_run=None, confirmation="", idempotency_key="",
        authorize=allowed, mutate=stop_mutation,
    )
    running = asyncio.create_task(coordinator.run(
        identity=start_identity, payload={"action": "start"}, preview=False,
        dry_run=None, confirmation=start_preview["confirmation"],
        idempotency_key="start", authorize=allowed, mutate=wait_mutation,
    ))
    await started.wait()
    with pytest.raises(ToolError, match="Another operation"):
        await coordinator.run(
            identity=stop_identity, payload={"action": "stop"}, preview=False,
            dry_run=None, confirmation=stop_preview["confirmation"],
            idempotency_key="stop", authorize=allowed, mutate=stop_mutation,
        )
    release.set()
    await running


@pytest.mark.asyncio
async def test_same_key_different_payload_is_rejected(tmp_path):
    coordinator = WriteCoordinator(store(tmp_path))

    async def allowed():
        return None

    async def mutate():
        return {"number": 1}

    preview = await coordinator.run(
        identity=identity(), payload={"title": "one"}, preview=True, dry_run=None,
        confirmation="", idempotency_key="", authorize=allowed, mutate=mutate,
    )
    await coordinator.run(
        identity=identity(), payload={"title": "one"}, preview=False, dry_run=None,
        confirmation=preview["confirmation"], idempotency_key="shared",
        authorize=allowed, mutate=mutate,
    )
    with pytest.raises(ToolError, match="different payload"):
        await coordinator.run(
            identity=identity(), payload={"title": "two"}, preview=False, dry_run=None,
            confirmation="unused", idempotency_key="shared",
            authorize=allowed, mutate=mutate,
        )


@pytest.mark.asyncio
async def test_concurrent_duplicate_is_rejected_before_duplicate_side_effect(tmp_path):
    coordinator = WriteCoordinator(store(tmp_path))
    started = asyncio.Event()
    release = asyncio.Event()
    mutations = 0

    async def allowed():
        return None

    async def mutate():
        nonlocal mutations
        mutations += 1
        started.set()
        await release.wait()
        return {"number": 1}

    payload = {"title": "race"}
    preview = await coordinator.run(
        identity=identity(), payload=payload, preview=True, dry_run=None,
        confirmation="", idempotency_key="", authorize=allowed, mutate=mutate,
    )
    first = asyncio.create_task(coordinator.run(
        identity=identity(), payload=payload, preview=False, dry_run=None,
        confirmation=preview["confirmation"], idempotency_key="race-key",
        authorize=allowed, mutate=mutate,
    ))
    await started.wait()
    retry = await coordinator.run(
        identity=identity(), payload=payload, preview=False, dry_run=None,
        confirmation=preview["confirmation"], idempotency_key="race-key",
        authorize=allowed, mutate=mutate,
    )
    assert retry["status"] == "running"
    assert retry["replayed"] is True
    assert retry["operation_uri"].startswith("nyankoface://operations/")
    release.set()
    await first
    assert mutations == 1


@pytest.mark.asyncio
async def test_timeout_has_terminal_non_replayable_unknown_outcome(tmp_path):
    coordinator = WriteCoordinator(store(tmp_path))
    mutations = 0

    async def allowed():
        return None

    async def timeout():
        nonlocal mutations
        mutations += 1
        raise ToolError("Bearer abcdefghijklmnopqrstuvwxyz upstream exploded")

    payload = {"body": "hello"}
    preview = await coordinator.run(
        identity=identity(tool="comment_issue"), payload=payload,
        preview=None, dry_run=True, confirmation="", idempotency_key="",
        authorize=allowed, mutate=timeout,
    )
    result = await coordinator.run(
        identity=identity(tool="comment_issue"), payload=payload,
        preview=None, dry_run=False, confirmation=preview["confirmation"],
        idempotency_key="timeout", authorize=allowed, mutate=timeout,
    )
    replay = await coordinator.run(
        identity=identity(tool="comment_issue"), payload=payload,
        preview=False, dry_run=None, confirmation="ignored",
        idempotency_key="timeout", authorize=allowed, mutate=timeout,
    )
    assert result["status"] == "indeterminate"
    assert result["error"] == {"code": "upstream_outcome_unknown", "retry_safe": False}
    assert "Bearer" not in str(result)
    assert replay["replayed"] is True
    assert mutations == 1


@pytest.mark.asyncio
async def test_indeterminate_operation_blocks_a_new_key_for_the_same_target(tmp_path):
    coordinator = WriteCoordinator(store(tmp_path))

    async def allowed():
        return None

    async def disconnected():
        raise ToolError("connection lost after dispatch")

    item = identity(tool="dispatch_pipeline", target="/pipelines/a/r")
    payload = {"ref": "main"}
    preview = await coordinator.run(
        identity=item, payload=payload, preview=True, dry_run=None,
        confirmation="", idempotency_key="", authorize=allowed, mutate=disconnected,
    )
    first = await coordinator.run(
        identity=item, payload=payload, preview=False, dry_run=None,
        confirmation=preview["confirmation"], idempotency_key="dispatch-1",
        authorize=allowed, mutate=disconnected,
    )
    assert first["status"] == "indeterminate"

    second_preview = await coordinator.run(
        identity=item, payload=payload, preview=True, dry_run=None,
        confirmation="", idempotency_key="", authorize=allowed, mutate=disconnected,
    )
    with pytest.raises(ToolError, match="active or unresolved") as error:
        await coordinator.run(
            identity=item, payload=payload, preview=False, dry_run=None,
            confirmation=second_preview["confirmation"], idempotency_key="dispatch-2",
            authorize=allowed, mutate=disconnected,
        )
    assert first["operation_uri"] in str(error.value)


def test_terminal_idempotency_and_operation_updates_are_atomic(tmp_path):
    safety = store(tmp_path)
    payload_hash = fingerprint({"ref": "main"})
    item = identity(tool="dispatch_pipeline", target="/pipelines/a/r")
    token, _ = safety.issue_confirmation(item, payload_hash)
    claim = safety.claim(item, payload_hash, token, "atomic")

    with sqlite3.connect(safety.path) as db:
        db.execute("""
            CREATE TRIGGER reject_operation_completion
            BEFORE UPDATE ON operations
            BEGIN
                SELECT RAISE(ABORT, 'simulated operation update failure');
            END;
        """)

    with pytest.raises(sqlite3.IntegrityError, match="simulated operation update failure"):
        safety.complete(claim.namespace, {"status": "completed"})

    with sqlite3.connect(safety.path) as db:
        idempotency = db.execute(
            "SELECT status, result_json FROM idempotency WHERE namespace = ?",
            (claim.namespace,),
        ).fetchone()
        operation = db.execute(
            "SELECT state, result_json FROM operations WHERE namespace = ?",
            (claim.namespace,),
        ).fetchone()
    assert idempotency == ("pending", None)
    assert operation == ("running", None)


@pytest.mark.asyncio
async def test_non_retryable_unknown_outcome_survives_idempotency_expiry(
    tmp_path, monkeypatch,
):
    coordinator = WriteCoordinator(store(tmp_path, idempotency_ttl=1))
    current = int(time.time())
    monkeypatch.setattr(time, "time", lambda: current)
    mutations = 0

    async def allowed():
        return None

    async def disconnected():
        nonlocal mutations
        mutations += 1
        raise ToolError("connection lost after dispatch")

    payload = {"body": "unknown outcome"}
    preview = await coordinator.run(
        identity=identity(tool="comment_issue"), payload=payload,
        preview=True, dry_run=None, confirmation="", idempotency_key="",
        authorize=allowed, mutate=disconnected,
    )
    first = await coordinator.run(
        identity=identity(tool="comment_issue"), payload=payload,
        preview=False, dry_run=None, confirmation=preview["confirmation"],
        idempotency_key="unknown", authorize=allowed, mutate=disconnected,
    )

    # Simulate the durable row format written by the preceding build, then
    # restart the store to exercise its upgrade migration.
    with sqlite3.connect(coordinator.store.path) as db:
        db.execute("UPDATE idempotency SET status = 'complete'")
    coordinator = WriteCoordinator(WriteSafetyStore(
        coordinator.store.path, 300, 1,
    ))
    with sqlite3.connect(coordinator.store.path) as db:
        assert db.execute(
            "SELECT status FROM idempotency",
        ).fetchone()[0] == "non_retryable"

    monkeypatch.setattr(time, "time", lambda: current + 2)
    replacement, _ = coordinator.store.issue_confirmation(
        identity(tool="comment_issue"), fingerprint(payload),
    )
    replay = await coordinator.run(
        identity=identity(tool="comment_issue"), payload=payload,
        preview=False, dry_run=None, confirmation=replacement,
        idempotency_key="unknown", authorize=allowed, mutate=disconnected,
    )

    assert first["status"] == replay["status"] == "indeterminate"
    assert replay["replayed"] is True
    assert mutations == 1
    with sqlite3.connect(coordinator.store.path) as db:
        assert db.execute(
            "SELECT status FROM idempotency",
        ).fetchone()[0] == "non_retryable"


@pytest.mark.asyncio
async def test_definite_upstream_rejection_is_preserved_and_replayed(tmp_path):
    coordinator = WriteCoordinator(store(tmp_path))
    mutations = 0

    async def allowed():
        return None

    async def rejected():
        nonlocal mutations
        mutations += 1
        raise WriteResponseError(
            "Resource was not found or is not authorized", "upstream_rejected", True,
        )

    payload = {"body": "hello"}
    preview = await coordinator.run(
        identity=identity(tool="comment_issue"), payload=payload,
        preview=True, dry_run=None, confirmation="", idempotency_key="",
        authorize=allowed, mutate=rejected,
    )
    result = await coordinator.run(
        identity=identity(tool="comment_issue"), payload=payload,
        preview=False, dry_run=None, confirmation=preview["confirmation"],
        idempotency_key="rejected", authorize=allowed, mutate=rejected,
    )
    replay = await coordinator.run(
        identity=identity(tool="comment_issue"), payload=payload,
        preview=False, dry_run=None, confirmation="unused",
        idempotency_key="rejected", authorize=allowed, mutate=rejected,
    )
    assert result["status"] == "rejected"
    assert result["error"] == {
        "code": "upstream_rejected",
        "message": "Resource was not found or is not authorized",
        "retry_safe": True,
    }
    assert replay["replayed"] is True
    assert mutations == 1

    next_preview = await coordinator.run(
        identity=identity(tool="comment_issue"), payload=payload,
        preview=True, dry_run=None, confirmation="", idempotency_key="",
        authorize=allowed, mutate=rejected,
    )
    next_result = await coordinator.run(
        identity=identity(tool="comment_issue"), payload=payload,
        preview=False, dry_run=None, confirmation=next_preview["confirmation"],
        idempotency_key="rejected-again", authorize=allowed, mutate=rejected,
    )
    assert next_result["status"] == "rejected"
    assert mutations == 2


@pytest.mark.asyncio
async def test_invalid_accepted_response_remains_locked_for_reconciliation(tmp_path):
    coordinator = WriteCoordinator(store(tmp_path))

    async def allowed():
        return None

    async def malformed_success():
        raise WriteResponseError(
            "NyankoFace control API returned an invalid response",
            "invalid_upstream_response",
            False,
        )

    item = identity(tool="start_space", target="/spaces/acme/demo")
    payload = {"action": "start"}
    preview = await coordinator.run(
        identity=item, payload=payload, preview=True, dry_run=None,
        confirmation="", idempotency_key="", authorize=allowed,
        mutate=malformed_success,
    )
    failed = await coordinator.run(
        identity=item, payload=payload, preview=False, dry_run=None,
        confirmation=preview["confirmation"], idempotency_key="malformed-1",
        authorize=allowed, mutate=malformed_success,
    )

    assert failed["status"] == "failed"
    assert failed["error"]["retry_safe"] is False
    next_preview = await coordinator.run(
        identity=item, payload=payload, preview=True, dry_run=None,
        confirmation="", idempotency_key="", authorize=allowed,
        mutate=malformed_success,
    )
    with pytest.raises(ToolError, match="active or unresolved"):
        await coordinator.run(
            identity=item, payload=payload, preview=False, dry_run=None,
            confirmation=next_preview["confirmation"], idempotency_key="malformed-2",
            authorize=allowed, mutate=malformed_success,
        )


@pytest.mark.asyncio
async def test_unexpected_mutation_exception_is_also_sanitized(tmp_path):
    coordinator = WriteCoordinator(store(tmp_path))

    async def allowed():
        return None

    async def explode():
        raise RuntimeError("github_pat-abcdefghijklmnopqrstuvwxyz must never leak")

    payload = {"body": "hello"}
    preview = await coordinator.run(
        identity=identity(), payload=payload, preview=True, dry_run=None,
        confirmation="", idempotency_key="", authorize=allowed, mutate=explode,
    )
    result = await coordinator.run(
        identity=identity(), payload=payload, preview=False, dry_run=None,
        confirmation=preview["confirmation"], idempotency_key="unexpected",
        authorize=allowed, mutate=explode,
    )
    assert result["status"] == "indeterminate"
    assert "github_pat" not in str(result)


@pytest.mark.asyncio
async def test_cancelled_mutation_is_terminal_and_cannot_be_dispatched_again(tmp_path):
    coordinator = WriteCoordinator(store(tmp_path))
    started = asyncio.Event()
    mutations = 0

    async def allowed():
        return None

    async def mutate():
        nonlocal mutations
        mutations += 1
        started.set()
        await asyncio.Event().wait()

    payload = {"body": "cancelled after dispatch"}
    preview = await coordinator.run(
        identity=identity(tool="comment_issue"), payload=payload,
        preview=True, dry_run=None, confirmation="", idempotency_key="",
        authorize=allowed, mutate=mutate,
    )
    task = asyncio.create_task(coordinator.run(
        identity=identity(tool="comment_issue"), payload=payload,
        preview=False, dry_run=None, confirmation=preview["confirmation"],
        idempotency_key="cancelled", authorize=allowed, mutate=mutate,
    ))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    replay = await coordinator.run(
        identity=identity(tool="comment_issue"), payload=payload,
        preview=False, dry_run=None, confirmation="unused",
        idempotency_key="cancelled", authorize=allowed, mutate=mutate,
    )
    assert replay["status"] == "indeterminate"
    assert replay["error"] == {"code": "upstream_outcome_unknown", "retry_safe": False}
    assert replay["replayed"] is True
    assert mutations == 1


@pytest.mark.asyncio
async def test_repository_authorization_is_checked_for_preview_execution_and_replay(tmp_path):
    coordinator = WriteCoordinator(store(tmp_path))
    checks = 0

    async def authorize():
        nonlocal checks
        checks += 1

    async def mutate():
        return {"number": 1}

    payload = {"title": "one"}
    preview = await coordinator.run(
        identity=identity(), payload=payload, preview=True, dry_run=None,
        confirmation="", idempotency_key="", authorize=authorize, mutate=mutate,
    )
    await coordinator.run(
        identity=identity(), payload=payload, preview=False, dry_run=None,
        confirmation=preview["confirmation"], idempotency_key="key",
        authorize=authorize, mutate=mutate,
    )
    await coordinator.run(
        identity=identity(), payload=payload, preview=False, dry_run=None,
        confirmation="ignored", idempotency_key="key", authorize=authorize, mutate=mutate,
    )
    assert checks == 3


@pytest.mark.asyncio
async def test_denial_and_audit_never_contain_input_or_credentials(tmp_path):
    safety = store(tmp_path)
    coordinator = WriteCoordinator(safety)
    secret = "Bearer abcdefghijklmnopqrstuvwxyz"

    async def denied():
        raise ToolError("Resource was not found or is not authorized")

    async def mutate():
        raise AssertionError("must not mutate")

    with pytest.raises(ToolError, match="not found or is not authorized"):
        await coordinator.run(
            identity=identity(), payload={"body": secret}, preview=True, dry_run=None,
            confirmation="", idempotency_key="", authorize=denied, mutate=mutate,
        )
    raw = safety.path.read_bytes()
    assert secret.encode() not in raw
    assert b"authorization" not in raw.lower()
    with sqlite3.connect(safety.path) as db:
        row = db.execute(
            "SELECT subject, tool, target, operation, result, payload_fingerprint FROM audit_events"
        ).fetchone()
    assert row[:5] == (
        "agent:one", "create_issue", "/repos/a/r/issues", "preview", "denied",
    )
    assert len(row[5]) == 64


def test_preview_and_dry_run_cannot_disagree(tmp_path):
    coordinator = WriteCoordinator(store(tmp_path))

    async def noop():
        return None

    async def mutate():
        return {}

    with pytest.raises(ToolError, match="must agree"):
        asyncio.run(coordinator.run(
            identity=identity(), payload={}, preview=True, dry_run=False,
            confirmation="", idempotency_key="", authorize=noop, mutate=mutate,
        ))


def test_sensitive_fingerprint_is_keyed_stable_and_not_raw_sha256(tmp_path):
    safety = store(tmp_path)
    payload = {"value": "ghp_secret-token", "nested": {"assignment": "A=B"}}

    first = safety.sensitive_fingerprint(payload)
    second = WriteSafetyStore(safety.path).sensitive_fingerprint(payload)

    assert first == second
    assert first != fingerprint(payload)
    assert len(first) == 64
    assert b"ghp_secret-token" not in safety.path.read_bytes()
    assert safety.fingerprint_key_path.stat().st_size == 32
    assert not list(tmp_path.glob(".*.hmac-key.*.tmp"))


def test_sensitive_fingerprint_rejects_invalid_key_length(tmp_path):
    safety = store(tmp_path)
    safety.fingerprint_key_path.write_bytes(b"short")
    if os.name != "nt":
        safety.fingerprint_key_path.chmod(0o600)

    with pytest.raises(RuntimeError, match="key is invalid"):
        safety.sensitive_fingerprint({"value": "never-digest-with-a-weak-key"})


def test_sensitive_fingerprint_concurrent_initialization_uses_one_key(tmp_path):
    path = tmp_path / "write.sqlite3"
    stores = [WriteSafetyStore(path) for _ in range(8)]
    payload = {"value": "shared-confidential-value"}

    with ThreadPoolExecutor(max_workers=len(stores)) as pool:
        digests = list(pool.map(
            lambda item: item.sensitive_fingerprint(payload),
            stores,
        ))

    key_path = stores[0].fingerprint_key_path
    lock_path = key_path.with_suffix(f"{key_path.suffix}.lock")
    assert len(set(digests)) == 1
    assert key_path.stat().st_size == 32
    assert not lock_path.exists()
    assert not list(tmp_path.glob(".*.hmac-key.*.tmp"))


def test_sensitive_fingerprint_rejects_symlink_key(tmp_path):
    safety = store(tmp_path)
    target = tmp_path / "other-key"
    target.write_bytes(b"x" * 32)
    try:
        safety.fingerprint_key_path.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")

    with pytest.raises(RuntimeError, match="regular file"):
        safety.sensitive_fingerprint({"value": "confidential"})


@pytest.mark.skipif(os.name == "nt", reason="POSIX ownership/mode checks")
def test_sensitive_fingerprint_rejects_group_readable_key(tmp_path):
    safety = store(tmp_path)
    safety.fingerprint_key_path.write_bytes(b"x" * 32)
    safety.fingerprint_key_path.chmod(0o640)

    with pytest.raises(RuntimeError, match="ownership or mode is unsafe"):
        safety.sensitive_fingerprint({"value": "confidential"})


@pytest.mark.asyncio
async def test_sensitive_preview_contains_only_explicit_safe_change_metadata(tmp_path):
    safety = store(tmp_path)
    coordinator = WriteCoordinator(safety)
    secret = "token=super-secret-value"

    async def authorize():
        return None

    async def mutate():
        raise AssertionError("preview must not mutate")

    result = await coordinator.run(
        identity=identity(tool="set_space_secret"),
        payload={"name": "TOKEN", "value": secret},
        preview=True,
        dry_run=None,
        confirmation="",
        idempotency_key="",
        authorize=authorize,
        mutate=mutate,
        sensitive_payload=True,
        preview_details={"action": "set", "name": "TOKEN", "kind": "secret"},
    )

    assert result["change"] == {"action": "set", "name": "TOKEN", "kind": "secret"}
    assert secret not in json.dumps(result)
    assert secret.encode() not in safety.path.read_bytes()
