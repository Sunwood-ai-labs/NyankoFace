from __future__ import annotations

import base64
import json
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from .auth import NyankoFaceTokenVerifier
from .client import (
    NyankoFaceAdapter,
    WriteResponseError,
    resource_document,
    operational_error_code,
    response_metadata,
    validate_repo_identity,
)
from .config import Settings
from .audit import AuditStore
from .governance import PolicyDenied, ToolPolicyGate
from .policy import PolicyRequest, PolicyStore
from .write_safety import (
    ABANDONED_OPERATION_SECONDS,
    SAFE_DENIAL,
    WriteCoordinator,
    WriteIdentity,
    WriteSafetyStore,
    effective_preview,
)


_RESOURCE_REF_TOKEN = re.compile(r"^[A-Za-z0-9_-]+$")
_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ENVIRONMENT_WRITE_TOOLS = {
    "set_space_variable", "delete_space_variable",
    "set_space_secret", "delete_space_secret", "apply_space_environment",
}


class TransportContractMiddleware:
    """Expose the serving instance and reject unsupported SSE resumption.

    NyankoFace keeps request boundaries stateless and does not retain an SSE
    event log. A client may retry a read as a new POST, while writes must reuse
    their idempotency key. Silently accepting Last-Event-ID would imply a resume
    guarantee that the service cannot provide.
    """

    def __init__(self, app: Callable[..., Awaitable[None]], instance_id: str):
        self.app = app
        self.instance_id = instance_id.encode("ascii", "replace")[:128]

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and any(
            key.lower() == b"last-event-id" for key, _value in scope.get("headers", ())
        ):
            await send({
                "type": "http.response.start",
                "status": 400,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"x-nyankoface-mcp-instance", self.instance_id),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": json.dumps({
                    "error": "last_event_id_not_supported",
                    "retry": "repeat safe reads as a new POST; reuse idempotency_key for writes",
                }, separators=(",", ":")).encode(),
            })
            return

        async def send_with_instance(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append(
                    (b"x-nyankoface-mcp-instance", self.instance_id),
                )
            await send(message)

        await self.app(scope, receive, send_with_instance)

TOOL_ACCESS = {
    "search_catalog": "read", "list_repositories": "read",
    "get_repository": "read", "get_file": "read", "get_tree": "read",
    "get_knowledge": "read", "list_issues": "read", "get_issue": "read",
    "get_space_status": "read", "get_pages_status": "read",
    "get_space_environment_metadata": "read", "list_pipeline_runs": "read",
    "get_pipeline_run": "read", "get_metrics": "read",
    "create_issue": "write", "update_issue": "write", "comment_issue": "write",
    "start_space": "write", "stop_space": "write", "restart_space": "write",
    "deploy_pages": "write", "dispatch_pipeline": "write",
    "cancel_pipeline": "write", "rollback_pipeline": "write",
    "set_space_variable": "write", "delete_space_variable": "write",
    "set_space_secret": "write", "delete_space_secret": "write",
    "apply_space_environment": "write",
    "get_operation": "read", "reconcile_operation": "write",
}


class GovernedFastMCP(FastMCP):
    """Apply one policy and audit boundary to every registered MCP Tool."""

    def __init__(
        self, *args, policy_gate: ToolPolicyGate, verifier: NyankoFaceTokenVerifier,
        operation_lookup: Callable[[str, str], dict[str, Any]], **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._policy_gate = policy_gate
        self._policy_verifier = verifier
        self._operation_lookup = operation_lookup

    def _target(
        self, name: str, arguments: dict[str, Any], subject_id: str,
    ) -> tuple[str, str | None]:
        owner, repo = arguments.get("owner"), arguments.get("repo")
        if isinstance(owner, str) and isinstance(repo, str):
            try:
                validate_repo_identity(owner, repo)
            except ToolError:
                pass
            else:
                repository = f"{owner.casefold()}/{repo.casefold()}"
                return repository, repository
        if name in {"get_operation", "reconcile_operation"}:
            operation_id = arguments.get("operation_id")
            if not isinstance(operation_id, str):
                raise ToolError(SAFE_DENIAL)
            operation = self._operation_lookup(subject_id, operation_id)
            parts = str(operation.get("target") or "").strip("/").split("/")
            if len(parts) < 3 or parts[0] not in {
                "repos", "spaces", "pages", "pipelines",
            }:
                raise ToolError(SAFE_DENIAL)
            owner, repo = parts[1], parts[2]
            validate_repo_identity(owner, repo)
            repository = f"{owner.casefold()}/{repo.casefold()}"
            return repository, repository
        return f"tool:{name}", None

    @staticmethod
    def _structured_result(result: Any) -> dict[str, Any] | None:
        if isinstance(result, dict):
            return result
        if (
            isinstance(result, tuple) and len(result) == 2
            and isinstance(result[1], dict)
        ):
            return result[1]
        return None

    async def call_tool(self, name: str, arguments: dict[str, Any]):
        access = TOOL_ACCESS.get(name)
        if access is None:
            raise ToolError("MCP tool is not classified for policy enforcement")
        if name in ENVIRONMENT_WRITE_TOOLS:
            required = {"owner", "repo"}
            if name != "apply_space_environment":
                required.add("name")
            if name.startswith("set_"):
                required.add("value")
            if any(not isinstance(arguments.get(key), str) for key in required):
                raise ToolError("NyankoFace environment request failed safely")
            value = arguments.get("value")
            if isinstance(value, str) and not 1 <= len(value) <= 16_384:
                raise ToolError("NyankoFace environment request failed safely")
            scope = arguments.get("scope", "runtime")
            if name.startswith("set_") and scope not in {"runtime", "build", "both"}:
                raise ToolError("NyankoFace environment request failed safely")
            revision = arguments.get("revision")
            if revision is not None and not isinstance(revision, str):
                raise ToolError("NyankoFace environment request failed safely")
        record = self._policy_verifier.current_record()
        target, repository = self._target(name, arguments, record.subject_id)
        request_id = self.get_context().request_id
        idempotency_key = arguments.get("idempotency_key")
        if not isinstance(idempotency_key, str) or not idempotency_key:
            idempotency_key = None
        request = PolicyRequest(
            subject_id=record.subject_id,
            subject_type=record.subject_type,
            client_id=record.client_id,
            tool=name,
            access=access,
            repository=repository,
        )
        try:
            gate = self._policy_gate.authorize(
                request, request_id=request_id, target=target,
                idempotency_key=idempotency_key,
            )
        except PolicyDenied as exc:
            raise ToolError(f"MCP tool denied by policy: {exc.reason}") from None
        try:
            result = await super().call_tool(name, arguments)
        except Exception:
            self._policy_gate.record_result(
                request, request_id=request_id, target=target,
                outcome="failed", reason="tool_failed",
                policy_version=gate.decision.policy_version,
                idempotency_key=idempotency_key,
            )
            raise
        structured = self._structured_result(result)
        replayed = structured is not None and structured.get("replayed") is True
        status = structured.get("status") if structured is not None else None
        failed = status in {"failed", "rejected", "indeterminate"}
        operation_id = (
            structured.get("operation_id") or structured.get("request_id")
            if structured is not None else None
        )
        if not isinstance(operation_id, str) or not operation_id:
            operation_id = None
        audited = self._policy_gate.record_result(
            request, request_id=request_id, target=target,
            outcome="replayed" if replayed else "failed" if failed else "allowed",
            reason=(
                "idempotent_replay" if replayed else
                f"tool_{status}" if failed else "tool_completed"
            ),
            policy_version=gate.decision.policy_version,
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            metadata={"audit_degraded": gate.audit_degraded} if gate.audit_degraded else None,
        )
        if not audited and structured is not None:
            structured["audit_degraded"] = True
        return result


def encode_resource_ref(ref: str) -> str:
    """Encode a repository ref as one URI-template-safe path segment."""
    return base64.urlsafe_b64encode(ref.encode("utf-8")).decode("ascii").rstrip("=")


def decode_resource_ref(token: str) -> str:
    """Decode a canonical unpadded base64url ref token."""
    if not token or not _RESOURCE_REF_TOKEN.fullmatch(token):
        raise ValueError("Invalid resource ref token")
    try:
        decoded = base64.b64decode(
            token + "=" * (-len(token) % 4),
            altchars=b"-_",
            validate=True,
        ).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid resource ref token") from exc
    if encode_resource_ref(decoded) != token:
        raise ValueError("Invalid resource ref token")
    return decoded


def create_server(
    settings: Settings | None = None,
    adapter: NyankoFaceAdapter | None = None,
    write_coordinator: WriteCoordinator | None = None,
    policy_gate: ToolPolicyGate | None = None,
) -> FastMCP:
    settings = settings or Settings.from_env()
    adapter = adapter or NyankoFaceAdapter(settings)
    verifier = NyankoFaceTokenVerifier(settings.token_file, adapter.get_current_user_id)
    write_coordinator = write_coordinator or WriteCoordinator(WriteSafetyStore(
        settings.write_state_path,
        settings.confirmation_ttl_seconds,
        settings.idempotency_ttl_seconds,
    ))
    policy_gate = policy_gate or ToolPolicyGate(
        PolicyStore(settings.policy_state_path),
        AuditStore(
            settings.audit_state_path,
            retention_seconds=settings.audit_retention_seconds,
        ),
    )
    endpoint = f"{settings.public_base_url}/mcp"
    mcp = GovernedFastMCP(
        "NyankoFace",
        instructions=(
            "NyankoFace catalog and repository access with preview-first Issue writes. "
            "Never request, expose, or infer secret values."
        ),
        token_verifier=verifier,
        auth=AuthSettings(
            issuer_url=settings.public_base_url,
            resource_server_url=endpoint,
            required_scopes=[],
        ),
        host="0.0.0.0",
        port=settings.listen_port,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=settings.json_response,
        retry_interval=1000,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(settings.allowed_hosts),
            allowed_origins=list(settings.allowed_origins),
        ),
        policy_gate=policy_gate,
        verifier=verifier,
        operation_lookup=write_coordinator.store.get_operation,
    )

    def token_for(scope: str, owner: str, repo: str) -> str | None:
        record = verifier.require(scope, owner, repo)
        return verifier.upstream_token(record)

    async def repositories_for_token(query: str, page: int, limit: int) -> dict[str, Any]:
        record = verifier.require("repos:read")
        upstream = verifier.upstream_token(record)
        if record.upstream_token_value is not None:
            # A direct Forgejo bearer uses Forgejo's repository visibility and
            # permission model as the source of truth.
            return await adapter.list_repositories(query, page, limit, upstream)
        mapped = {target for target, _permission in record.repository_permissions}
        allowed = set(record.repositories) if record.repositories else mapped
        normalized_query = query.casefold().strip()
        page = max(1, page)
        limit = min(100, max(1, limit))
        candidates = sorted(
            target for target in allowed.intersection(mapped)
            if not normalized_query or normalized_query in target.casefold()
        )
        start = (page - 1) * limit
        repositories = []
        for target in candidates[start:start + limit]:
            owner, repo = target.split("/", 1)
            try:
                repositories.append(await adapter.get_repository(owner, repo, upstream))
            except ToolError as exc:
                if operational_error_code(exc) != "not_found_or_unauthorized":
                    raise
        result = {
            "page": page,
            "limit": limit,
            "totalCount": len(candidates),
            "totalPages": max(1, (len(candidates) + limit - 1) // limit),
            "items": repositories,
        }
        result["_meta"] = response_metadata(result)
        return result

    @mcp.tool(title="Search NyankoFace catalog")
    async def search_catalog(
        kind: str,
        query: str = "",
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Search one public NyankoFace catalog kind with bounded pagination."""
        verifier.require("catalog:read")
        return await adapter.search_catalog(kind, query, page, limit)

    @mcp.tool(title="List repositories")
    async def list_repositories(
        query: str = "",
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List caller-visible repositories with bounded pagination."""
        return await repositories_for_token(query, page, limit)

    @mcp.tool(title="Get repository")
    async def get_repository(owner: str, repo: str) -> dict[str, Any]:
        """Get public or caller-authorized repository metadata."""
        return await adapter.get_repository(owner, repo, token_for("repos:read", owner, repo))

    @mcp.tool(title="Get repository file")
    async def get_file(owner: str, repo: str, path: str, ref: str | None = None) -> dict[str, Any]:
        """Read one bounded UTF-8 file; secret-like paths are always denied."""
        return await adapter.get_file(owner, repo, path, ref, token_for("repos:read", owner, repo))

    @mcp.tool(title="Get repository tree")
    async def get_tree(
        owner: str,
        repo: str,
        ref: str,
        path: str | None = None,
    ) -> dict[str, Any]:
        """Read a repository tree or one safe directory fixed to one ref."""
        return await adapter.get_tree(
            owner,
            repo,
            ref,
            token_for("repos:read", owner, repo),
            path,
        )

    @mcp.tool(title="Get knowledge article")
    async def get_knowledge(owner: str, slug: str) -> dict[str, Any]:
        """Read one published Knowledge article through the public catalog."""
        verifier.require("catalog:read")
        return await adapter.get_knowledge(owner, slug, None)

    @mcp.tool(title="List issues")
    async def list_issues(
        owner: str,
        repo: str,
        state: str = "open",
        page: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List issues visible to the caller's repository identity."""
        return await adapter.list_issues(
            owner, repo, state, page, limit, token_for("issues:read", owner, repo)
        )

    @mcp.tool(title="Get issue")
    async def get_issue(owner: str, repo: str, number: int) -> dict[str, Any]:
        """Get one issue visible to the caller's repository identity."""
        return await adapter.get_issue(
            owner, repo, number, token_for("issues:read", owner, repo)
        )

    def issue_write_context(
        tool: str, method: str, owner: str, repo: str, suffix: str,
    ) -> tuple[WriteIdentity, str | None]:
        # Validate before constructing an audit target so hostile input can
        # never become audit metadata.
        validate_repo_identity(owner, repo)
        record = verifier.require("issues:write", owner, repo)
        if "repos:read" not in record.scopes:
            raise ToolError("Missing required NyankoFace scope: repos:read")
        token = verifier.upstream_token(record)
        target = f"/repos/{owner.lower()}/{repo.lower()}/{suffix}"
        return WriteIdentity(record.subject_id, tool, method, target), token

    async def run_issue_write(
        *,
        tool: str,
        method: str,
        owner: str,
        repo: str,
        suffix: str,
        payload: dict[str, Any],
        preview: bool | None,
        dry_run: bool | None,
        confirmation: str,
        idempotency_key: str,
        mutation,
    ) -> dict[str, Any]:
        identity, token = issue_write_context(tool, method, owner, repo, suffix)
        return await write_coordinator.run(
            identity=identity,
            payload=payload,
            preview=preview,
            dry_run=dry_run,
            confirmation=confirmation,
            idempotency_key=idempotency_key,
            authorize=lambda: adapter.authorize_issue_write(owner, repo, token),
            mutate=lambda: mutation(token),
        )

    @mcp.tool(title="Create issue safely")
    async def create_issue(
        owner: str,
        repo: str,
        title: str,
        body: str = "",
        preview: bool | None = None,
        dry_run: bool | None = None,
        confirmation: str = "",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Preview first, then create an issue with explicit confirmation and idempotency."""
        title = title.strip()
        if not title or len(title) > 255 or len(body) > 65_535:
            raise ToolError("title must be 1-255 characters and body at most 65535 characters")
        payload = {"title": title, "body": body}
        return await run_issue_write(
            tool="create_issue", method="POST", owner=owner, repo=repo,
            suffix="issues", payload=payload, preview=preview, dry_run=dry_run,
            confirmation=confirmation, idempotency_key=idempotency_key,
            mutation=lambda token: adapter.create_issue(owner, repo, title, body, token),
        )

    @mcp.tool(title="Update issue safely")
    async def update_issue(
        owner: str,
        repo: str,
        number: int,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        preview: bool | None = None,
        dry_run: bool | None = None,
        confirmation: str = "",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Preview first, then update issue fields with explicit confirmation and idempotency."""
        if number < 1:
            raise ToolError("Issue number must be positive")
        changes: dict[str, Any] = {}
        if title is not None:
            clean_title = title.strip()
            if not clean_title or len(clean_title) > 255:
                raise ToolError("title must be 1-255 characters")
            changes["title"] = clean_title
        if body is not None:
            if len(body) > 65_535:
                raise ToolError("body must be at most 65535 characters")
            changes["body"] = body
        if state is not None:
            if state not in {"open", "closed"}:
                raise ToolError("state must be open or closed")
            changes["state"] = state
        if not changes:
            raise ToolError("At least one of title, body, or state is required")
        return await run_issue_write(
            tool="update_issue", method="PATCH", owner=owner, repo=repo,
            suffix=f"issues/{number}", payload=changes, preview=preview,
            dry_run=dry_run, confirmation=confirmation,
            idempotency_key=idempotency_key,
            mutation=lambda token: adapter.update_issue(owner, repo, number, changes, token),
        )

    @mcp.tool(title="Comment on issue safely")
    async def comment_issue(
        owner: str,
        repo: str,
        number: int,
        body: str,
        preview: bool | None = None,
        dry_run: bool | None = None,
        confirmation: str = "",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Preview first, then add one comment with explicit confirmation and idempotency."""
        if number < 1 or not body.strip() or len(body) > 65_535:
            raise ToolError("number must be positive and body must be 1-65535 characters")
        payload = {"body": body}
        return await run_issue_write(
            tool="comment_issue", method="POST", owner=owner, repo=repo,
            suffix=f"issues/{number}/comments", payload=payload, preview=preview,
            dry_run=dry_run, confirmation=confirmation,
            idempotency_key=idempotency_key,
            mutation=lambda token: adapter.comment_issue(owner, repo, number, body, token),
        )

    def control_write_context(
        tool: str, scope: str, owner: str, repo: str, target: str,
    ) -> tuple[WriteIdentity, str | None]:
        validate_repo_identity(owner, repo)
        record = verifier.require(scope, owner, repo)
        if "repos:read" not in record.scopes:
            raise ToolError("Missing required NyankoFace scope: repos:read")
        token = verifier.upstream_token(record)
        return WriteIdentity(
            record.subject_id, tool, "POST", target,
        ), token

    async def run_control_write(
        *, tool: str, scope: str, owner: str, repo: str, target: str,
        payload: dict[str, Any], preview: bool | None, dry_run: bool | None,
        confirmation: str, idempotency_key: str, mutation,
        sensitive_payload: bool = False,
        preview_details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        identity, token = control_write_context(
            tool, scope, owner, repo, target,
        )
        return await write_coordinator.run(
            identity=identity,
            payload=payload,
            preview=preview,
            dry_run=dry_run,
            confirmation=confirmation,
            idempotency_key=idempotency_key,
            authorize=lambda: adapter.authorize_control_write(owner, repo, token),
            mutate=lambda: mutation(token),
            sensitive_payload=sensitive_payload,
            preview_details=preview_details,
        )

    async def space_control(
        action: str, owner: str, repo: str, preview: bool | None,
        dry_run: bool | None, confirmation: str, idempotency_key: str,
    ) -> dict[str, Any]:
        return await run_control_write(
            tool=f"{action}_space", scope="spaces:run", owner=owner, repo=repo,
            target=f"/spaces/{owner.lower()}/{repo.lower()}",
            payload={"action": action}, preview=preview, dry_run=dry_run,
            confirmation=confirmation, idempotency_key=idempotency_key,
            mutation=lambda token: adapter.control_space(action, owner, repo, token),
        )

    def validate_environment_name(name: str) -> str:
        normalized = name.strip().upper()
        if len(normalized) > 127 or not _ENVIRONMENT_NAME.fullmatch(normalized):
            raise ToolError("Environment name must be a valid 1-127 character identifier")
        return normalized

    async def set_environment(
        *, kind: str, owner: str, repo: str, name: str, value: str, scope: str,
        preview: bool | None, dry_run: bool | None, confirmation: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        name = validate_environment_name(name)
        if not value or len(value) > 16_384:
            raise ToolError("Environment value must contain 1-16384 characters")
        if scope not in {"runtime", "build", "both"}:
            raise ToolError("scope must be runtime, build, or both")
        return await run_control_write(
            tool=f"set_space_{kind}",
            scope=f"{kind}s:write",
            owner=owner,
            repo=repo,
            target=f"/spaces/{owner.lower()}/{repo.lower()}/environment",
            payload={"action": "set", "name": name, "kind": kind, "scope": scope,
                     "value": value},
            preview=preview,
            dry_run=dry_run,
            confirmation=confirmation,
            idempotency_key=idempotency_key,
            mutation=lambda token: adapter.set_space_environment(
                owner, repo, name, kind, value, scope, token,
            ),
            sensitive_payload=True,
            preview_details={"action": "set", "name": name, "kind": kind, "scope": scope},
        )

    async def delete_environment(
        *, kind: str, owner: str, repo: str, name: str,
        preview: bool | None, dry_run: bool | None, confirmation: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        name = validate_environment_name(name)
        return await run_control_write(
            tool=f"delete_space_{kind}",
            scope=f"{kind}s:write",
            owner=owner,
            repo=repo,
            target=f"/spaces/{owner.lower()}/{repo.lower()}/environment",
            payload={"action": "delete", "name": name, "kind": kind},
            preview=preview,
            dry_run=dry_run,
            confirmation=confirmation,
            idempotency_key=idempotency_key,
            mutation=lambda token: adapter.delete_space_environment(
                owner, repo, name, kind, token,
            ),
            preview_details={"action": "delete", "name": name, "kind": kind},
        )

    @mcp.tool(title="Set Space variable safely")
    async def set_space_variable(
        owner: str, repo: str, name: str, value: str, scope: str = "runtime",
        preview: bool | None = None, dry_run: bool | None = None,
        confirmation: str = "", idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Write one variable; the submitted value is never returned or audited."""
        return await set_environment(
            kind="variable", owner=owner, repo=repo, name=name, value=value,
            scope=scope, preview=preview, dry_run=dry_run,
            confirmation=confirmation, idempotency_key=idempotency_key,
        )

    @mcp.tool(title="Delete Space variable safely")
    async def delete_space_variable(
        owner: str, repo: str, name: str, preview: bool | None = None,
        dry_run: bool | None = None, confirmation: str = "",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Delete one variable without affecting a same-named secret."""
        return await delete_environment(
            kind="variable", owner=owner, repo=repo, name=name, preview=preview,
            dry_run=dry_run, confirmation=confirmation,
            idempotency_key=idempotency_key,
        )

    @mcp.tool(title="Set Space secret safely")
    async def set_space_secret(
        owner: str, repo: str, name: str, value: str, scope: str = "runtime",
        preview: bool | None = None, dry_run: bool | None = None,
        confirmation: str = "", idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Write one secret; plaintext never crosses the result boundary."""
        return await set_environment(
            kind="secret", owner=owner, repo=repo, name=name, value=value,
            scope=scope, preview=preview, dry_run=dry_run,
            confirmation=confirmation, idempotency_key=idempotency_key,
        )

    @mcp.tool(title="Delete Space secret safely")
    async def delete_space_secret(
        owner: str, repo: str, name: str, preview: bool | None = None,
        dry_run: bool | None = None, confirmation: str = "",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Delete one secret without affecting a same-named variable."""
        return await delete_environment(
            kind="secret", owner=owner, repo=repo, name=name, preview=preview,
            dry_run=dry_run, confirmation=confirmation,
            idempotency_key=idempotency_key,
        )

    @mcp.tool(title="Apply Space environment safely")
    async def apply_space_environment(
        owner: str, repo: str, revision: str | None = None,
        preview: bool | None = None, dry_run: bool | None = None,
        confirmation: str = "", idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Restart one Space to apply its currently configured environment."""
        if revision is not None and not re.fullmatch(r"[0-9a-fA-F]{7,64}", revision):
            raise ToolError("revision must be a 7-64 character hexadecimal commit")
        return await run_control_write(
            tool="apply_space_environment", scope="spaces:run", owner=owner,
            repo=repo,
            target=f"/spaces/{owner.lower()}/{repo.lower()}/environment",
            payload={"action": "apply", "revision": revision}, preview=preview,
            dry_run=dry_run, confirmation=confirmation,
            idempotency_key=idempotency_key,
            mutation=lambda token: adapter.apply_space_environment(
                owner, repo, revision, token,
            ),
            preview_details={"action": "apply"},
        )

    @mcp.tool(title="Start Space safely")
    async def start_space(
        owner: str, repo: str, preview: bool | None = None,
        dry_run: bool | None = None, confirmation: str = "",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Preview first, then start one Space as a durable operation."""
        return await space_control(
            "start", owner, repo, preview, dry_run, confirmation, idempotency_key,
        )

    @mcp.tool(title="Stop Space safely")
    async def stop_space(
        owner: str, repo: str, preview: bool | None = None,
        dry_run: bool | None = None, confirmation: str = "",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Preview first, then stop one Space as a durable operation."""
        return await space_control(
            "stop", owner, repo, preview, dry_run, confirmation, idempotency_key,
        )

    @mcp.tool(title="Restart Space safely")
    async def restart_space(
        owner: str, repo: str, preview: bool | None = None,
        dry_run: bool | None = None, confirmation: str = "",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Preview first, then restart one Space as a durable operation."""
        return await space_control(
            "restart", owner, repo, preview, dry_run, confirmation, idempotency_key,
        )

    @mcp.tool(title="Deploy Pages safely")
    async def deploy_pages(
        owner: str, repo: str, method: str,
        preview: bool | None = None, dry_run: bool | None = None,
        confirmation: str = "", idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Preview first, then deploy Pages using gh-pages, docs, or vitepress."""
        if method not in {"gh-pages", "docs", "vitepress"}:
            raise ToolError("method must be gh-pages, docs, or vitepress")
        return await run_control_write(
            tool="deploy_pages", scope="pages:deploy", owner=owner, repo=repo,
            target=f"/pages/{owner.lower()}/{repo.lower()}",
            payload={"action": "deploy", "method": method}, preview=preview,
            dry_run=dry_run, confirmation=confirmation,
            idempotency_key=idempotency_key,
            mutation=lambda token: adapter.deploy_pages(owner, repo, method, token),
        )

    @mcp.tool(title="Dispatch pipeline safely")
    async def dispatch_pipeline(
        owner: str, repo: str, workflow: str, ref: str = "main",
        environment: str = "staging", inputs: dict[str, str] | None = None,
        preview: bool | None = None, dry_run: bool | None = None,
        confirmation: str = "", idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Preview first, then dispatch one bounded pipeline workflow."""
        workflow = workflow.strip()
        if not workflow or len(workflow) > 255:
            raise ToolError("workflow must be 1-255 characters")
        if environment not in {"preview", "staging", "production"}:
            raise ToolError("environment must be preview, staging, or production")
        if not ref.strip() or len(ref) > 255:
            raise ToolError("ref must be 1-255 characters")
        bounded_inputs = inputs or {}
        if len(bounded_inputs) > 20 or any(
            not str(key) or len(str(key)) > 100 or len(str(value)) > 4096
            for key, value in bounded_inputs.items()
        ):
            raise ToolError("inputs must contain at most 20 bounded string values")
        payload = {
            "action": "dispatch", "workflow": workflow, "ref": ref,
            "environment": environment, "inputs": bounded_inputs,
        }
        return await run_control_write(
            tool="dispatch_pipeline", scope="pipelines:write", owner=owner,
            repo=repo, target=f"/pipelines/{owner.lower()}/{repo.lower()}",
            payload=payload, preview=preview, dry_run=dry_run,
            confirmation=confirmation, idempotency_key=idempotency_key,
            mutation=lambda token: adapter.dispatch_pipeline(
                owner, repo, workflow, ref, environment, bounded_inputs, token,
            ),
        )

    async def run_pipeline_action(
        action: str, owner: str, repo: str, run_number: int,
        preview: bool | None, dry_run: bool | None, confirmation: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if run_number < 1:
            raise ToolError("Pipeline run number must be positive")
        return await run_control_write(
            tool=f"{action}_pipeline", scope="pipelines:write", owner=owner,
            repo=repo,
            target=f"/pipelines/{owner.lower()}/{repo.lower()}/runs/{run_number}",
            payload={"action": action, "run_number": run_number}, preview=preview,
            dry_run=dry_run, confirmation=confirmation,
            idempotency_key=idempotency_key,
            mutation=lambda token: adapter.pipeline_action(
                action, owner, repo, run_number, token,
            ),
        )

    @mcp.tool(title="Cancel pipeline safely")
    async def cancel_pipeline(
        owner: str, repo: str, run_number: int,
        preview: bool | None = None, dry_run: bool | None = None,
        confirmation: str = "", idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Preview first, then cancel one pipeline run."""
        return await run_pipeline_action(
            "cancel", owner, repo, run_number, preview, dry_run,
            confirmation, idempotency_key,
        )

    @mcp.tool(title="Rollback pipeline safely")
    async def rollback_pipeline(
        owner: str, repo: str, run_number: int,
        preview: bool | None = None, dry_run: bool | None = None,
        confirmation: str = "", idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Preview first, then roll back from one successful production run."""
        return await run_pipeline_action(
            "rollback", owner, repo, run_number, preview, dry_run,
            confirmation, idempotency_key,
        )

    def operation_repository(operation: dict[str, Any]) -> tuple[str, str]:
        parts = str(operation.get("target") or "").strip("/").split("/")
        if len(parts) < 3 or parts[0] not in {"repos", "spaces", "pages", "pipelines"}:
            raise ToolError(SAFE_DENIAL)
        owner, repo = parts[1], parts[2]
        validate_repo_identity(owner, repo)
        return owner, repo

    async def authorized_operation(operation_id: str) -> dict[str, Any]:
        """Recheck current repository visibility before exposing durable history."""
        record = verifier.require("repos:read")
        operation = write_coordinator.store.get_operation(
            record.subject_id, operation_id,
        )
        try:
            owner, repo = operation_repository(operation)
            record = verifier.require("repos:read", owner, repo)
            await adapter.get_repository(
                owner, repo, verifier.upstream_token(record),
            )
        except (ToolError, ValueError):
            raise ToolError(SAFE_DENIAL) from None
        return operation

    @mcp.tool(title="Get control operation")
    async def get_operation(operation_id: str) -> dict[str, Any]:
        """Get a durable operation after current repository reauthorization."""
        return await authorized_operation(operation_id)

    @mcp.tool(title="Reconcile unresolved operation safely")
    async def reconcile_operation(
        operation_id: str,
        resolution: str,
        preview: bool | None = None,
        dry_run: bool | None = None,
        confirmation: str = "",
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        """Release one verified unknown-outcome lock while preserving its history."""
        if resolution not in {"applied", "not_applied"}:
            raise ToolError("resolution must be applied or not_applied")
        operation = await authorized_operation(operation_id)
        abandoned = (
            operation["state"] == "running"
            and operation["updated_at"] <= int(time.time()) - ABANDONED_OPERATION_SECONDS
        )
        if (operation["state"] not in {"indeterminate", "failed"} and not abandoned
                and not (not effective_preview(preview, dry_run) and idempotency_key)):
            raise ToolError("Only an unresolved operation can be reconciled")
        tool = operation["tool"]
        if tool in {"create_issue", "update_issue", "comment_issue"}:
            scope = "issues:write"
        elif tool in {"start_space", "stop_space", "restart_space"}:
            scope = "spaces:run"
        elif tool in {"set_space_variable", "delete_space_variable"}:
            scope = "variables:write"
        elif tool in {"set_space_secret", "delete_space_secret"}:
            scope = "secrets:write"
        elif tool == "apply_space_environment":
            scope = "spaces:run"
        elif tool == "deploy_pages":
            scope = "pages:deploy"
        elif tool in {"dispatch_pipeline", "cancel_pipeline", "rollback_pipeline"}:
            scope = "pipelines:write"
        elif tool == "reconcile_operation":
            scope = "repos:read"
        else:
            raise ToolError("This operation type cannot be reconciled")
        owner, repo = operation_repository(operation)
        record = verifier.require(scope, owner, repo)
        token = verifier.upstream_token(record)

        async def reconcile_local() -> dict[str, Any]:
            try:
                return write_coordinator.store.reconcile_operation(
                    record.subject_id, operation_id, resolution,
                )
            except ToolError as exc:
                raise WriteResponseError(
                    str(exc), "operation_not_unresolved", True,
                ) from exc

        return await write_coordinator.run(
            identity=WriteIdentity(
                record.subject_id,
                "reconcile_operation",
                "PATCH",
                f"/repos/{owner.lower()}/{repo.lower()}/operations/{operation_id}/reconcile",
            ),
            payload={"operation_id": operation_id, "resolution": resolution},
            preview=preview,
            dry_run=dry_run,
            confirmation=confirmation,
            idempotency_key=idempotency_key,
            authorize=lambda: adapter.authorize_control_write(owner, repo, token),
            mutate=reconcile_local,
        )

    async def status(surface: str, owner: str, repo: str, scope: str) -> dict[str, Any]:
        return await adapter.get_status(surface, owner, repo, token_for(scope, owner, repo))

    @mcp.tool(title="Get Space status")
    async def get_space_status(owner: str, repo: str) -> dict[str, Any]:
        """Get non-secret runtime status for a Space."""
        return await status("spaces", owner, repo, "spaces:read")

    @mcp.tool(title="Get Pages status")
    async def get_pages_status(owner: str, repo: str) -> dict[str, Any]:
        """Get publication status and public URL for NyankoFace Pages."""
        return await status("pages", owner, repo, "pages:read")

    @mcp.tool(title="Get Space environment metadata")
    async def get_space_environment_metadata(owner: str, repo: str) -> dict[str, Any]:
        """List names/configuration state/update time; never return values."""
        return await adapter.get_space_environment_metadata(
            owner, repo, token_for("spaces:read", owner, repo),
        )

    @mcp.tool(title="List pipeline runs")
    async def list_pipeline_runs(
        owner: str, repo: str, page: int = 1, limit: int = 20,
    ) -> dict[str, Any]:
        """List non-secret pipeline run metadata."""
        return await adapter.list_pipeline_runs(
            owner, repo, page, limit, token_for("pipelines:read", owner, repo),
        )

    @mcp.tool(title="Get pipeline run")
    async def get_pipeline_run(owner: str, repo: str, run_number: int) -> dict[str, Any]:
        """Get one non-secret pipeline run by repository run number."""
        return await adapter.get_pipeline_run(
            owner, repo, run_number, token_for("pipelines:read", owner, repo),
        )

    @mcp.tool(title="Get repository metrics")
    async def get_metrics(owner: str, repo: str) -> dict[str, Any]:
        """Get non-secret repository view and like counters."""
        return await adapter.get_metrics(owner, repo, token_for("metrics:read", owner, repo))

    @mcp.resource("nyankoface://catalog/{kind}", mime_type="application/json")
    async def catalog_resource(kind: str) -> str:
        verifier.require("catalog:read")
        payload = await adapter.search_catalog(kind)
        return json.dumps(resource_document(payload, pagination={
            "page": int(payload.get("page", 1)),
            "limit": int(payload.get("limit", 20)),
            "total_count": int(payload.get("totalCount", 0)),
            "total_pages": int(payload.get("totalPages", 1)),
        }), ensure_ascii=False)

    @mcp.resource("nyankoface://repos/{owner}/{repo}", mime_type="application/json")
    async def repository_resource(owner: str, repo: str) -> str:
        payload = await adapter.get_repository(
            owner, repo, token_for("repos:read", owner, repo)
        )
        return json.dumps(resource_document(payload), ensure_ascii=False)

    @mcp.resource("nyankoface://repos/{owner}/{repo}/tree/{ref_b64}", mime_type="application/json")
    async def tree_resource(owner: str, repo: str, ref_b64: str) -> str:
        return json.dumps(
            await adapter.get_tree(
                owner, repo, decode_resource_ref(ref_b64), token_for("repos:read", owner, repo)
            ),
            ensure_ascii=False,
        )

    @mcp.resource("nyankoface://knowledge/{owner}/{slug}", mime_type="application/json")
    async def knowledge_resource(owner: str, slug: str) -> str:
        verifier.require("catalog:read")
        return json.dumps(await adapter.get_knowledge(owner, slug, None), ensure_ascii=False)

    @mcp.resource("nyankoface://issues/{owner}/{repo}/{number}", mime_type="application/json")
    async def issue_resource(owner: str, repo: str, number: str) -> str:
        payload = await adapter.get_issue(
            owner, repo, int(number), token_for("issues:read", owner, repo),
        )
        return json.dumps(resource_document(payload), ensure_ascii=False)

    @mcp.resource("nyankoface://spaces/{owner}/{repo}/status", mime_type="application/json")
    async def space_resource(owner: str, repo: str) -> str:
        payload = await status("spaces", owner, repo, "spaces:read")
        return json.dumps(resource_document(payload), ensure_ascii=False)

    @mcp.resource("nyankoface://pages/{owner}/{repo}/status", mime_type="application/json")
    async def pages_resource(owner: str, repo: str) -> str:
        payload = await status("pages", owner, repo, "pages:read")
        return json.dumps(resource_document(payload), ensure_ascii=False)

    @mcp.resource("nyankoface://pipelines/{owner}/{repo}/runs", mime_type="application/json")
    async def pipeline_runs_resource(owner: str, repo: str) -> str:
        return json.dumps(
            await adapter.list_pipeline_runs(
                owner, repo, 1, 20, token_for("pipelines:read", owner, repo),
            ),
            ensure_ascii=False,
        )

    @mcp.resource("nyankoface://operations/{operation_id}", mime_type="application/json")
    async def operation_resource(operation_id: str) -> str:
        return json.dumps(
            await authorized_operation(operation_id),
            ensure_ascii=False,
        )

    @mcp.resource("nyankoface://api/openapi", mime_type="application/json")
    async def openapi_resource() -> str:
        verifier.require("catalog:read")
        return json.dumps(await adapter.get_openapi(), ensure_ascii=False)

    @mcp.prompt(name="diagnose_space", title="Diagnose an NyankoFace Space")
    def diagnose_space(owner: str, repo: str) -> str:
        return (
            f"Diagnose Space {owner}/{repo}. Read nyankoface://spaces/{owner}/{repo}/status, "
            "the repository metadata, and its ref-fixed tree. Explain evidence, likely cause, "
            "and safe next actions. Never request or reproduce secrets."
        )

    @mcp.prompt(name="publish_pages", title="Prepare an NyankoFace Pages publication")
    def publish_pages(owner: str, repo: str) -> str:
        return (
            f"Prepare Pages publication for {owner}/{repo}. Inspect repository metadata and a "
            "ref-fixed tree, then propose the smallest build and publishing plan. This server is "
            "read-only: do not claim that files, pipelines, or settings were changed."
        )

    @mcp.prompt(name="analyze_pipeline_failure", title="Analyze a pipeline failure")
    def analyze_pipeline_failure(owner: str, repo: str) -> str:
        return (
            f"Analyze the latest failed pipeline for {owner}/{repo}. Correlate pipeline metadata "
            "with the repository tree and relevant files, redact secrets, and separate observed "
            "facts from hypotheses and suggested fixes."
        )

    @mcp.prompt(name="validate_topics", title="Validate NyankoFace topics")
    def validate_topics(owner: str, repo: str) -> str:
        return (
            f"Validate the catalog topics for {owner}/{repo}. Compare repository metadata and "
            "published content against the supported NyankoFace catalog kinds. Report missing, "
            "conflicting, or overly broad topics without changing the repository."
        )

    @mcp.prompt(name="publish_content", title="Prepare NyankoFace content publication")
    def publish_content(owner: str, repo: str, content_kind: str) -> str:
        return (
            f"Prepare {content_kind} publication for {owner}/{repo}. Use catalog metadata, a "
            "ref-fixed tree, and relevant text files to produce a validation checklist and minimal "
            "change plan. Never include credentials or claim write actions were performed."
        )

    return mcp


def create_http_app(settings: Settings | None = None):
    """Build the observable stateless HTTP application used by uvicorn."""
    effective = settings or Settings.from_env()
    app = create_server(effective).streamable_http_app()
    return TransportContractMiddleware(app, effective.instance_id)


mcp = create_server()
