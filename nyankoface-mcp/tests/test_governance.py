from __future__ import annotations

import sqlite3

import pytest

from nyankoface_mcp.audit import AuditFilter, AuditStore
from nyankoface_mcp.governance import (
    PolicyActor,
    PolicyAdminService,
    PolicyDenied,
    ToolPolicyGate,
)
from nyankoface_mcp.policy import PolicyRequest, PolicyStore
from nyankoface_mcp.config import Settings
from nyankoface_mcp.policy_admin import main as policy_admin_main


def request(access: str = "read", tool: str = "get_repository") -> PolicyRequest:
    return PolicyRequest(
        subject_id="service:codex", subject_type="service_account",
        client_id="codex", tool=tool, access=access,
        repository="nyankoface/example",
    )


def gate(tmp_path, *, access: str = "read", tool: str = "get_repository"):
    policy = PolicyStore(tmp_path / "policy.db")
    audit = AuditStore(tmp_path / "audit.db")
    policy.set_tool_policy("subject", "service:codex", tool, "allow")
    return ToolPolicyGate(policy, audit), audit, request(access, tool)


def authorize(gate: ToolPolicyGate, policy_request: PolicyRequest):
    return gate.authorize(
        policy_request, request_id="request-1", target="nyankoface/example",
        operation_id="operation-1", idempotency_key="do-not-store-verbatim",
    )


def test_allowed_request_is_audited_before_tool_execution(tmp_path):
    policy_gate, audit, policy_request = gate(tmp_path)

    result = authorize(policy_gate, policy_request)

    assert result.decision.allowed is True
    records = audit.search(AuditFilter(request_id="request-1")).items
    assert len(records) == 1
    assert records[0].outcome == "allowed"
    assert records[0].idempotency_fingerprint != "do-not-store-verbatim"


def test_default_denial_is_audited_and_raised(tmp_path):
    policy = PolicyStore(tmp_path / "policy.db")
    audit = AuditStore(tmp_path / "audit.db")
    policy_gate = ToolPolicyGate(policy, audit)

    with pytest.raises(PolicyDenied) as captured:
        authorize(policy_gate, request())

    assert captured.value.reason == "default_deny"
    assert audit.search(AuditFilter(outcome="denied")).items[0].reason_code == "default_deny"


def test_policy_backend_failure_denies_even_when_audit_is_healthy(tmp_path, monkeypatch):
    policy_gate, audit, policy_request = gate(tmp_path)

    def unavailable():
        raise sqlite3.OperationalError("policy offline")

    monkeypatch.setattr(policy_gate.policy, "_connect", unavailable)

    with pytest.raises(PolicyDenied, match="policy_unavailable"):
        authorize(policy_gate, policy_request)
    assert audit.search(AuditFilter(reason_code="policy_unavailable")).items


def test_audit_failure_denies_write_before_caller_can_mutate(tmp_path, monkeypatch):
    policy_gate, _, policy_request = gate(tmp_path, access="write", tool="create_issue")

    def unavailable():
        raise sqlite3.OperationalError("audit offline")

    monkeypatch.setattr(policy_gate.audit, "_connect", unavailable)
    side_effect = False

    with pytest.raises(PolicyDenied, match="audit_unavailable"):
        authorize(policy_gate, policy_request)
        side_effect = True

    assert side_effect is False


def test_audit_failure_allows_explicit_read_with_degraded_marker(tmp_path, monkeypatch):
    policy_gate, _, policy_request = gate(tmp_path)

    def unavailable():
        raise sqlite3.OperationalError("audit offline")

    monkeypatch.setattr(policy_gate.audit, "_connect", unavailable)

    result = authorize(policy_gate, policy_request)

    assert result.decision.allowed is True
    assert result.audit_degraded is True


def test_records_failed_and_replayed_results_with_same_identifiers(tmp_path):
    policy_gate, audit, policy_request = gate(tmp_path, access="write", tool="create_issue")
    result = authorize(policy_gate, policy_request)
    assert policy_gate.record_result(
        policy_request, request_id="request-1", target="nyankoface/example",
        outcome="failed", reason="upstream_rejected",
        policy_version=result.decision.policy_version, operation_id="operation-1",
    ) is True
    assert policy_gate.record_result(
        policy_request, request_id="request-2", target="nyankoface/example",
        outcome="replayed", reason="idempotent_replay",
        policy_version=result.decision.policy_version, operation_id="operation-1",
    ) is True

    outcomes = {item.outcome for item in audit.search(AuditFilter(tool="create_issue")).items}
    assert outcomes == {"allowed", "failed", "replayed"}


def test_policy_admin_audits_request_and_applied_version(tmp_path):
    policy = PolicyStore(tmp_path / "policy.db")
    audit = AuditStore(tmp_path / "audit.db")
    service = PolicyAdminService(policy, audit)
    actor = PolicyActor("user:admin", "human", "admin-cli")

    version = service.change(
        actor=actor, request_id="request-policy", target="global:*/get_repository",
        action="set_tool_policy",
        mutate=lambda: policy.set_tool_policy("global", "*", "get_repository", "allow"),
        metadata={"scope": "global", "scope_id": "*", "tool": "get_repository",
                  "effect": "allow"},
    )

    records = audit.search(AuditFilter(event_type="policy_change")).items
    assert [item.outcome for item in records] == ["changed", "allowed"]
    assert records[0].policy_version == version
    assert policy.evaluate(request()).allowed is True


def test_policy_admin_does_not_mutate_when_audit_preflight_fails(tmp_path, monkeypatch):
    policy = PolicyStore(tmp_path / "policy.db")
    audit = AuditStore(tmp_path / "audit.db")
    service = PolicyAdminService(policy, audit)

    def unavailable():
        raise sqlite3.OperationalError("audit offline")

    monkeypatch.setattr(audit, "_connect", unavailable)
    with pytest.raises(Exception, match="audit backend is unavailable"):
        service.change(
            actor=PolicyActor("user:admin", "human", "admin-cli"),
            request_id="request-policy", target="global:*/get_repository",
            action="set_tool_policy",
            mutate=lambda: policy.set_tool_policy("global", "*", "get_repository", "allow"),
            metadata={},
        )

    assert policy.evaluate(request()).reason == "default_deny"


def test_policy_admin_cli_provisions_fresh_default_deny_store(tmp_path, capsys):
    settings = Settings(
        policy_state_path=tmp_path / "policy.db",
        audit_state_path=tmp_path / "audit.db",
    )
    assert policy_admin_main([
        "--actor-subject", "user:admin", "allow", "global", "*",
        "get_repository",
    ], settings=settings) == 0

    assert PolicyStore(settings.policy_state_path).evaluate(request()).allowed is True
    assert '"policy_version": 1' in capsys.readouterr().out
    assert AuditStore(settings.audit_state_path).search(
        AuditFilter(event_type="policy_change")
    ).items

    assert policy_admin_main(["--actor-subject", "user:admin", "allow", "subject",
                              "x" * 2000, "get_repository"], settings=settings) == 0
