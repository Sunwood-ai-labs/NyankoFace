from __future__ import annotations

import sqlite3

import pytest

from nyankoface_mcp.audit import (
    AuditEvent,
    AuditFilter,
    AuditStore,
    AuditUnavailable,
    InvalidAuditEvent,
)


def event(
    *,
    outcome: str = "allowed",
    tool: str = "get_repository",
    request_id: str = "request-1",
    subject_id: str = "user:alice",
    metadata: dict | None = None,
    idempotency_key: str | None = None,
) -> AuditEvent:
    return AuditEvent(
        event_type="request",
        outcome=outcome,
        request_id=request_id,
        operation_id="operation-1",
        idempotency_key=idempotency_key,
        subject_id=subject_id,
        subject_type="human",
        client_id="codex",
        tool=tool,
        target="nyankoface/example",
        repository="NyankoFace/Example",
        reason_code="explicit_allow",
        policy_version=3,
        metadata=metadata,
    )


def test_appends_required_non_secret_identifiers_and_hash_chain(tmp_path):
    store = AuditStore(tmp_path / "audit.db", clock=lambda: 123)

    first = store.append(event(idempotency_key="raw-key"))
    second = store.append(event(outcome="replayed", request_id="request-2"))

    assert first.occurred_at == 123
    assert first.idempotency_fingerprint is not None
    assert first.idempotency_fingerprint != "raw-key"
    assert second.previous_hash == first.event_hash
    assert store.verify_integrity().valid is True
    assert store.verify_integrity().checked_events == 2


def test_redacts_secret_values_from_metadata_and_target(tmp_path):
    store = AuditStore(tmp_path / "audit.db")
    record = store.append(AuditEvent(
        **{
            **event(metadata={"authorization": "Bearer abcdefghijklmnopqrstuvwxyz"}).__dict__,
            "target": "nyankoface/example?token=abcdefghijklmnopqrstuvwxyz",
        }
    ))

    serialized = repr(record)
    assert "abcdefghijklmnopqrstuvwxyz" not in serialized
    assert "Bearer" not in serialized
    assert "[REDACTED]" in serialized


def test_redacts_secret_shaped_repository_search_field(tmp_path):
    store = AuditStore(tmp_path / "audit.db")
    record = store.append(AuditEvent(**{
        **event().__dict__,
        "repository": "sk-abcdefghijklmnop/example",
        "target": "sk-abcdefghijklmnop/example",
    }))

    assert record.repository == "redacted/redacted"
    assert "sk-abcdefghijklmnop" not in repr(record)


def test_redacts_secret_shaped_searchable_identifiers(tmp_path):
    store = AuditStore(tmp_path / "audit.db")
    secret = "sk-abcdefghijklmnop"
    record = store.append(AuditEvent(**{
        **event().__dict__,
        "request_id": secret,
        "subject_id": secret,
        "client_id": secret,
        "operation_id": secret,
    }))

    assert record.request_id == "redacted"
    assert record.subject_id == "redacted"
    assert record.client_id == "redacted"
    assert record.operation_id == "redacted"
    assert secret not in repr(record)

    compatible = store.append(AuditEvent(**{
        **event(request_id="request-compat").__dict__,
        "subject_id": "Human User " + "x" * 300, "client_id": "VS Code " + "y" * 300,
    }))
    assert compatible.subject_id.startswith("Human User ")
    assert compatible.client_id.startswith("VS Code ")


@pytest.mark.parametrize(
    "legacy", ["legacy\u0085id", "legacy\u200bid", "legacy\ud800id"]
)
def test_legacy_non_printable_identifiers_are_opaque_and_searchable(tmp_path, legacy):
    store = AuditStore(tmp_path / "audit.db")
    record = store.append(AuditEvent(**{
        **event().__dict__,
        "request_id": legacy,
        "subject_id": legacy,
        "client_id": legacy,
        "operation_id": legacy,
    }))

    assert record.request_id.startswith("opaque:sha256:")
    assert record.subject_id == record.request_id
    assert record.client_id == record.request_id
    assert record.operation_id == record.request_id
    assert store.search(AuditFilter(subject_id=legacy)).items == (record,)
    assert store.search(AuditFilter(client_id=legacy)).items == (record,)
    assert store.search(AuditFilter(request_id=legacy)).items == (record,)
    assert store.search(AuditFilter(operation_id=legacy)).items == (record,)


def test_redacts_secret_shaped_nested_metadata_keys(tmp_path):
    store = AuditStore(tmp_path / "audit.db")
    secret = "sk-abcdefghijklmnop"
    record = store.append(event(metadata={"nested": {secret: "value"}}))

    assert secret not in repr(record)
    assert next(iter(record.metadata["nested"])).startswith("redacted_key_")


def test_redacts_secret_shaped_keys_and_values_inside_tuple_metadata(tmp_path):
    store = AuditStore(tmp_path / "audit.db")
    secret = "sk-abcdefghijklmnop"

    record = store.append(event(metadata={"items": ({secret: secret},)}))

    assert secret not in repr(record)
    assert isinstance(record.metadata["items"], list)
    nested = record.metadata["items"][0]
    assert next(iter(nested)).startswith("redacted_key_")
    assert nested[next(iter(nested))] == "[REDACTED]"


def test_filters_and_cursor_pagination_cover_operational_search(tmp_path):
    ticks = iter((100, 101, 102, 103))
    store = AuditStore(tmp_path / "audit.db", clock=lambda: next(ticks))
    store.append(event(outcome="allowed", request_id="request-1"))
    store.append(event(outcome="denied", request_id="request-2"))
    store.append(event(outcome="failed", request_id="request-3", subject_id="user:bob"))
    store.append(event(outcome="replayed", request_id="request-4"))

    first_page = store.search(limit=2)
    second_page = store.search(cursor=first_page.next_cursor, limit=2)
    denied = store.search(AuditFilter(outcome="denied"))
    alice = store.search(AuditFilter(subject_id="user:alice", occurred_after=102))

    assert [item.request_id for item in first_page.items] == ["request-4", "request-3"]
    assert [item.request_id for item in second_page.items] == ["request-2", "request-1"]
    assert first_page.next_cursor == first_page.items[-1].sequence
    assert second_page.next_cursor is None
    assert [item.request_id for item in denied.items] == ["request-2"]
    assert [item.request_id for item in alice.items] == ["request-4"]
    assert store.summarize(AuditFilter(occurred_after=101, occurred_before=104)) == {
        "total": 3,
        "by_outcome": {"denied": 1, "failed": 1, "replayed": 1},
        "by_tool": {"get_repository": 3},
    }


def test_policy_changes_are_searchable_as_first_class_events(tmp_path):
    store = AuditStore(tmp_path / "audit.db")
    store.append(AuditEvent(
        event_type="policy_change", outcome="changed", request_id="request-policy",
        subject_id="user:admin", subject_type="human", client_id="admin-cli",
        tool="policy", target="global:*/get_repository",
        reason_code="tool_policy_updated", policy_version=4,
        metadata={"effect": "allow"},
    ))
    store.append(event())

    page = store.search(AuditFilter(event_type="policy_change"))

    assert len(page.items) == 1
    assert page.items[0].request_id == "request-policy"
    assert page.items[0].policy_version == 4


def test_retention_keeps_anchor_for_remaining_hash_chain(tmp_path):
    ticks = iter((100, 200, 300))
    store = AuditStore(tmp_path / "audit.db", clock=lambda: next(ticks))
    store.append(event(request_id="request-1"))
    store.append(event(request_id="request-2"))
    last = store.append(event(request_id="request-3"))

    assert store.purge_before(250) == 2

    page = store.search()
    assert [item.event_hash for item in page.items] == [last.event_hash]
    report = store.verify_integrity()
    assert report.valid is True
    assert report.checked_events == 1


def test_configured_retention_is_applied_after_append(tmp_path):
    ticks = iter((100, 200))
    store = AuditStore(
        tmp_path / "audit.db", clock=lambda: next(ticks), retention_seconds=50
    )
    store.append(event(request_id="request-old"))
    store.append(event(request_id="request-current"))

    assert [item.request_id for item in store.search().items] == ["request-current"]
    assert store.verify_integrity().valid is True


def test_hash_verification_detects_modified_record(tmp_path):
    path = tmp_path / "audit.db"
    store = AuditStore(path)
    record = store.append(event())
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE audit_events SET outcome = 'denied' WHERE sequence = ?",
            (record.sequence,),
        )

    report = store.verify_integrity()

    assert report.valid is False
    assert report.first_invalid_sequence == record.sequence


def test_backend_errors_are_stable_and_do_not_leak_database_details(tmp_path, monkeypatch):
    store = AuditStore(tmp_path / "audit.db")

    def unavailable():
        raise sqlite3.OperationalError("C:/secret/audit.db disk failure")

    monkeypatch.setattr(store, "_connect", unavailable)

    with pytest.raises(AuditUnavailable) as captured:
        store.append(event())
    assert str(captured.value) == "audit backend is unavailable"
    assert "C:/secret" not in str(captured.value)


def test_backend_path_failure_does_not_expose_internal_path(tmp_path):
    blocked = tmp_path / "private-audit-location"
    blocked.write_text("not a directory", encoding="utf-8")

    with pytest.raises(AuditUnavailable) as captured:
        AuditStore(blocked / "audit.db")
    assert str(captured.value) == "audit backend is unavailable"
    assert str(blocked) not in str(captured.value)


@pytest.mark.parametrize(
    "invalid",
    [
        {"event_type": "unknown"},
        {"outcome": "success"},
        {"tool": "Invalid Tool"},
        {"repository": "missing-slash"},
        {"policy_version": -1},
    ],
)
def test_invalid_events_are_rejected_before_persistence(tmp_path, invalid):
    store = AuditStore(tmp_path / "audit.db")
    values = {**event().__dict__, **invalid}

    with pytest.raises(InvalidAuditEvent):
        store.append(AuditEvent(**values))


def test_invalid_pagination_is_rejected(tmp_path):
    store = AuditStore(tmp_path / "audit.db")

    with pytest.raises(InvalidAuditEvent, match="pagination"):
        store.search(limit=101)


def test_non_json_metadata_is_rejected_before_database_write(tmp_path):
    store = AuditStore(tmp_path / "audit.db")
    with pytest.raises(InvalidAuditEvent, match="JSON values"):
        store.append(event(metadata={"unsafe": object()}))
    assert store.search().items == ()
