from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .audit import AuditEvent, AuditStore, AuditUnavailable
from .policy import PolicyDecision, PolicyRequest, PolicyStore, PolicyUnavailable


class PolicyDenied(RuntimeError):
    """Stable policy denial raised before a Tool can perform side effects."""

    def __init__(self, reason: str, decision: PolicyDecision | None = None):
        super().__init__(reason)
        self.reason = reason
        self.decision = decision


@dataclass(frozen=True)
class GateResult:
    decision: PolicyDecision
    audit_degraded: bool = False


@dataclass(frozen=True)
class PolicyActor:
    subject_id: str
    subject_type: str
    client_id: str


class PolicyAdminService:
    """Audit-before-mutate operator boundary for policy changes."""

    def __init__(self, policy: PolicyStore, audit: AuditStore):
        self.policy = policy
        self.audit = audit

    def change(
        self,
        *,
        actor: PolicyActor,
        request_id: str,
        target: str,
        action: str,
        mutate: Callable[[], int],
        metadata: dict[str, Any],
    ) -> int:
        common = {
            "event_type": "policy_change", "request_id": request_id,
            "subject_id": actor.subject_id, "subject_type": actor.subject_type,
            "client_id": actor.client_id, "tool": "policy", "target": target,
        }
        # This durable request event is the precondition for mutation. An audit
        # outage therefore leaves policy state untouched.
        self.audit.append(AuditEvent(
            **common, outcome="allowed", reason_code="policy_change_requested",
            metadata={"action": action, **metadata},
        ))
        try:
            version = mutate()
        except Exception:
            self.audit.append(AuditEvent(
                **common, outcome="failed", reason_code="policy_change_failed",
                metadata={"action": action},
            ))
            raise
        self.audit.append(AuditEvent(
            **common, outcome="changed", reason_code="policy_change_applied",
            policy_version=version, metadata={"action": action, **metadata},
        ))
        return version


class ToolPolicyGate:
    """Request-time policy and pre-execution audit boundary for MCP Tools."""

    def __init__(self, policy: PolicyStore, audit: AuditStore):
        self.policy = policy
        self.audit = audit

    @staticmethod
    def _event(
        request: PolicyRequest,
        *,
        request_id: str,
        target: str,
        outcome: str,
        reason: str,
        policy_version: int | None,
        operation_id: str | None,
        idempotency_key: str | None,
        event_type: str = "request",
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        return AuditEvent(
            event_type=event_type,
            outcome=outcome,
            request_id=request_id,
            subject_id=request.subject_id,
            subject_type=request.subject_type,
            client_id=request.client_id,
            tool=request.tool,
            target=target,
            reason_code=reason,
            repository=request.repository,
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            policy_version=policy_version,
            metadata=metadata,
        )

    def authorize(
        self,
        request: PolicyRequest,
        *,
        request_id: str,
        target: str,
        operation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> GateResult:
        try:
            decision = self.policy.evaluate(request)
        except PolicyUnavailable:
            try:
                self.audit.append(self._event(
                    request, request_id=request_id, target=target,
                    outcome="denied", reason="policy_unavailable", policy_version=None,
                    operation_id=operation_id, idempotency_key=idempotency_key,
                ))
            except AuditUnavailable:
                pass
            raise PolicyDenied("policy_unavailable") from None

        outcome = "allowed" if decision.allowed else "denied"
        try:
            self.audit.append(self._event(
                request, request_id=request_id, target=target,
                outcome=outcome, reason=decision.reason,
                policy_version=decision.policy_version,
                operation_id=operation_id, idempotency_key=idempotency_key,
                metadata={"matched_scope": decision.matched_scope,
                          "read_only": decision.read_only},
            ))
        except AuditUnavailable:
            if not decision.allowed:
                raise PolicyDenied(decision.reason, decision) from None
            if request.access == "write":
                raise PolicyDenied("audit_unavailable", decision) from None
            return GateResult(decision, audit_degraded=True)

        if not decision.allowed:
            raise PolicyDenied(decision.reason, decision)
        return GateResult(decision)

    def record_result(
        self,
        request: PolicyRequest,
        *,
        request_id: str,
        target: str,
        outcome: str,
        reason: str,
        policy_version: int,
        operation_id: str | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        try:
            self.audit.append(self._event(
                request, request_id=request_id, target=target,
                outcome=outcome, reason=reason, policy_version=policy_version,
                operation_id=operation_id, idempotency_key=idempotency_key,
                event_type="tool_result", metadata=metadata,
            ))
        except AuditUnavailable:
            # A successful preflight event already proves the write was allowed.
            # A backend failure after dispatch cannot safely be reported as if
            # the upstream mutation failed, so callers expose degraded audit.
            return False
        return True
