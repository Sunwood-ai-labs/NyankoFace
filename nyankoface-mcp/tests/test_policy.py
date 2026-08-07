from __future__ import annotations

import sqlite3

import pytest

from nyankoface_mcp.policy import (
    InvalidPolicy,
    PolicyRequest,
    PolicyRule,
    PolicyStore,
    PolicyUnavailable,
)


def request(
    *,
    tool: str = "get_repository",
    access: str = "read",
    subject_id: str = "user:alice",
    subject_type: str = "human",
    repository: str | None = "NyankoFace/Example",
) -> PolicyRequest:
    return PolicyRequest(
        subject_id=subject_id,
        subject_type=subject_type,
        client_id="codex",
        tool=tool,
        access=access,
        repository=repository,
    )


def test_unconfigured_tool_is_default_deny(tmp_path):
    decision = PolicyStore(tmp_path / "policy.db").evaluate(request())

    assert decision.allowed is False
    assert decision.reason == "default_deny"
    assert decision.policy_version == 0
    assert decision.matched_scope is None


def test_previously_issued_identifiers_with_spaces_remain_authorizable(tmp_path):
    store = PolicyStore(tmp_path / "policy.db")
    subject_id = "Human User " + "x" * 300
    store.set_tool_policy("subject", subject_id, "get_repository", "allow")
    assert store.evaluate(PolicyRequest(
        subject_id=subject_id, subject_type="human", client_id="VS Code " + "y" * 300,
        tool="get_repository", access="read", repository="nyankoface/example",
    )).allowed is True
    store.set_tool_policy("subject", "\n", "get_repository", "allow")
    assert store.evaluate(PolicyRequest(
        subject_id="\n", subject_type="human", client_id="", tool="get_repository",
        access="read", repository="nyankoface/example",
    )).allowed is True


def test_policy_specificity_is_global_repository_service_account_subject(tmp_path):
    store = PolicyStore(tmp_path / "policy.db")
    service_request = request(
        subject_id="service:publisher",
        subject_type="service_account",
    )
    store.set_tool_policy("global", "*", "get_repository", "deny")
    store.set_tool_policy("repository", "nyankoface/example", "get_repository", "allow")
    store.set_tool_policy("service_account", "*", "get_repository", "deny")
    store.set_tool_policy(
        "service_account", "service:publisher", "get_repository", "allow"
    )

    service_decision = store.evaluate(service_request)
    assert service_decision.allowed is True
    assert service_decision.matched_scope == "service_account:service:publisher"

    store.set_tool_policy("subject", "service:publisher", "get_repository", "deny")
    subject_decision = store.evaluate(service_request)
    assert subject_decision.allowed is False
    assert subject_decision.reason == "explicit_deny"
    assert subject_decision.matched_scope == "subject:service:publisher"

    human_decision = store.evaluate(request())
    assert human_decision.allowed is True
    assert human_decision.matched_scope == "repository:nyankoface/example"


def test_repository_identity_is_case_normalized(tmp_path):
    store = PolicyStore(tmp_path / "policy.db")
    store.set_tool_policy("repository", "NYANKOFACE/EXAMPLE", "get_repository", "allow")

    decision = store.evaluate(request(repository="nyankoface/example"))

    assert decision.allowed is True
    assert decision.matched_scope == "repository:nyankoface/example"


def test_read_only_rejects_write_before_any_tool_policy_allow(tmp_path):
    store = PolicyStore(tmp_path / "policy.db")
    store.set_tool_policy("subject", "user:alice", "create_issue", "allow")
    store.set_read_only("global", "*", True)

    decision = store.evaluate(request(tool="create_issue", access="write"))

    assert decision.allowed is False
    assert decision.reason == "read_only"
    assert decision.read_only is True


def test_read_only_does_not_bypass_explicit_read_policy(tmp_path):
    store = PolicyStore(tmp_path / "policy.db")
    store.set_tool_policy("global", "*", "get_repository", "allow")
    store.set_read_only("repository", "nyankoface/example", True)

    allowed_read = store.evaluate(request())
    denied_unconfigured_read = store.evaluate(request(tool="get_issue"))

    assert allowed_read.allowed is True
    assert denied_unconfigured_read.reason == "default_deny"


def test_disabling_read_only_is_visible_to_existing_store_instances(tmp_path):
    path = tmp_path / "policy.db"
    first = PolicyStore(path)
    second = PolicyStore(path)
    first.set_tool_policy("global", "*", "create_issue", "allow")
    first.set_read_only("global", "*", True)
    assert second.evaluate(request(tool="create_issue", access="write")).reason == "read_only"

    version = first.set_read_only("global", "*", False)
    decision = second.evaluate(request(tool="create_issue", access="write"))

    assert decision.allowed is True
    assert decision.policy_version == version


def test_policy_changes_are_visible_on_the_next_request_without_cache(tmp_path):
    path = tmp_path / "policy.db"
    writer = PolicyStore(path)
    reader = PolicyStore(path)
    writer.set_tool_policy("global", "*", "get_repository", "allow")
    assert reader.evaluate(request()).allowed is True

    version = writer.set_tool_policy("global", "*", "get_repository", "deny")
    decision = reader.evaluate(request())

    assert decision.allowed is False
    assert decision.policy_version == version


def test_backend_error_fails_closed_instead_of_returning_a_decision(tmp_path, monkeypatch):
    store = PolicyStore(tmp_path / "policy.db")

    def unavailable():
        raise sqlite3.OperationalError("disk offline")

    monkeypatch.setattr(store, "_connect", unavailable)

    with pytest.raises(PolicyUnavailable, match="policy backend is unavailable"):
        store.evaluate(request())


def test_backend_path_failure_does_not_expose_internal_path(tmp_path):
    blocked = tmp_path / "private-policy-location"
    blocked.write_text("not a directory", encoding="utf-8")

    with pytest.raises(PolicyUnavailable) as captured:
        PolicyStore(blocked / "policy.db")
    assert str(captured.value) == "policy backend is unavailable"
    assert str(blocked) not in str(captured.value)


@pytest.mark.parametrize(
    ("scope", "scope_id"),
    [
        ("global", "not-star"),
        ("repository", "missing-slash"),
        ("service_account", None),
        ("unknown", "value"),
    ],
)
def test_invalid_operator_policy_is_rejected(tmp_path, scope, scope_id):
    store = PolicyStore(tmp_path / "policy.db")

    with pytest.raises(InvalidPolicy):
        store.set_tool_policy(scope, scope_id, "get_repository", "allow")


def test_policy_listing_contains_only_non_secret_contract_fields(tmp_path):
    store = PolicyStore(tmp_path / "policy.db")
    version = store.set_tool_policy(
        "subject", "service:publisher", "deploy_pages", "allow", now=123
    )

    assert store.list_tool_policies() == [PolicyRule(
        scope="subject",
        scope_id="service:publisher",
        tool="deploy_pages",
        effect="allow",
        version=version,
        updated_at=123,
    )]
