from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
import stat
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .audit import AuditFilter, AuditStore, AuditUnavailable, InvalidAuditEvent
from .config import Settings
from .governance import PolicyActor, PolicyAdminService
from .lifecycle import (
    REAUTH_MAX_AGE_SECONDS,
    AdminContext,
    LifecycleError,
    LifecycleUnavailable,
    TokenLifecycleStore,
)
from .policy import InvalidPolicy, PolicyStore, PolicyUnavailable


MAX_BODY_BYTES = 65_536
SAFE_REF = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
MCP_PROTOCOL_VERSION = "2025-06-18"
NO_STORE = {"Cache-Control": "private, no-store, max-age=0", "Pragma": "no-cache"}


@dataclass(frozen=True)
class AdminSettings:
    internal_token_file: Path
    registry_path: Path
    lifecycle_audit_path: Path
    forgejo_token_root: Path
    forgejo_token_allowlist: tuple[str, ...]
    policy_path: Path
    audit_path: Path
    mcp_url: str
    listen_port: int = 8001
    audit_retention_seconds: int = 7_776_000

    @classmethod
    def from_env(cls) -> "AdminSettings":
        runtime = Settings.from_env()
        return cls(
            internal_token_file=Path(os.environ["NYANKOFACE_MCP_ADMIN_INTERNAL_TOKEN_FILE"]),
            registry_path=Path(os.getenv("NYANKOFACE_MCP_TOKEN_FILE", str(runtime.token_file))),
            lifecycle_audit_path=Path(os.getenv(
                "NYANKOFACE_MCP_LIFECYCLE_AUDIT_PATH", "/run/nyankoface-mcp/lifecycle-audit.jsonl"
            )),
            forgejo_token_root=Path(os.getenv(
                "NYANKOFACE_MCP_FORGEJO_TOKEN_ROOT", "/run/secrets/nyankoface-mcp-users"
            )),
            forgejo_token_allowlist=tuple(filter(None, (
                item.strip() for item in os.getenv(
                    "NYANKOFACE_MCP_FORGEJO_TOKEN_ALLOWLIST",
                    "nyankoface-mcp-forgejo-user-token",
                ).split(",")
            ))),
            policy_path=runtime.policy_state_path,
            audit_path=runtime.audit_state_path,
            mcp_url=os.getenv("NYANKOFACE_MCP_ADMIN_TEST_URL", "http://nyankoface-mcp:8000/mcp"),
            listen_port=int(os.getenv("NYANKOFACE_MCP_ADMIN_LISTEN_PORT", "8001")),
            audit_retention_seconds=runtime.audit_retention_seconds,
        )


def _response(payload: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers=NO_STORE)


def _error(status: int, code: str) -> JSONResponse:
    return _response({"error": code}, status)


async def _body(request: Request) -> dict[str, Any]:
    length = request.headers.get("content-length")
    if length and (not length.isdigit() or int(length) > MAX_BODY_BYTES):
        raise ValueError("request_too_large")
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise ValueError("request_too_large")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_json") from exc
    if not isinstance(value, dict):
        raise ValueError("invalid_json")
    return value


def _strings(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"invalid_{name}")
    return value


def _required_string(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"invalid_{name}")
    return value


def _required_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"invalid_{name}")
    return value


def _actor(request: Request) -> tuple[AdminContext, PolicyActor]:
    subject = request.headers.get("x-nyankoface-admin-subject", "")
    if not subject or len(subject) > 255 or not subject.isprintable():
        raise ValueError("invalid_actor")
    raw_reauthenticated_at = request.headers.get(
        "x-nyankoface-admin-reauthenticated-at", ""
    )
    try:
        reauthenticated_at = int(raw_reauthenticated_at)
    except ValueError as exc:
        raise ValueError("fresh_reauthentication_required") from exc
    now = int(time.time())
    if reauthenticated_at > now or now - reauthenticated_at > REAUTH_MAX_AGE_SECONDS:
        raise ValueError("fresh_reauthentication_required")
    return (
        AdminContext(subject, True, reauthenticated_at),
        PolicyActor(subject, "human", "nyankoface-admin-ui"),
    )


def _safe_audit(record: Any) -> dict[str, Any]:
    return {
        key: getattr(record, key)
        for key in (
            "sequence", "event_id", "occurred_at", "event_type", "outcome",
            "request_id", "subject_id", "subject_type", "client_id", "tool",
            "target", "reason_code", "repository", "operation_id", "policy_version",
            "metadata",
        )
    }


class AdminApi:
    def __init__(
        self,
        settings: AdminSettings,
        http_client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
    ):
        self.settings = settings
        self.lifecycle = TokenLifecycleStore(settings.registry_path, settings.lifecycle_audit_path)
        self.policy = PolicyStore(settings.policy_path)
        self.audit = AuditStore(
            settings.audit_path, retention_seconds=settings.audit_retention_seconds
        )
        self.policy_admin = PolicyAdminService(self.policy, self.audit)
        self.http_client_factory = http_client_factory
        token = settings.internal_token_file.read_text(encoding="utf-8").strip()
        if len(token) < 32:
            raise RuntimeError("admin internal credential is unavailable")
        self._internal_token = token

    def authorized(self, request: Request) -> bool:
        scheme, _, supplied = request.headers.get("authorization", "").partition(" ")
        return scheme.lower() == "bearer" and hmac.compare_digest(
            supplied.encode("utf-8"), self._internal_token.encode("utf-8")
        )

    async def state(self, request: Request) -> JSONResponse:
        context, _ = _actor(request)
        query = request.query_params
        filters = AuditFilter(
            outcome=query.get("outcome"), tool=query.get("tool"),
            subject_id=query.get("subject"), client_id=query.get("client"),
            repository=query.get("repository"),
            occurred_after=int(query["after"]) if query.get("after") else None,
            occurred_before=int(query["before"]) if query.get("before") else None,
        )
        if (filters.occurred_after is not None and filters.occurred_before is not None
                and filters.occurred_after >= filters.occurred_before):
            raise ValueError("invalid_audit_period")
        limit = min(int(query.get("limit", "25")), 100)
        cursor = int(query["cursor"]) if query.get("cursor") else None
        page = self.audit.search(filters, limit=limit, cursor=cursor)
        return _response({
            "service_accounts": self.lifecycle.list_service_accounts(context),
            "tokens": self.lifecycle.list_tokens(context),
            "policy": {
                "version": self.policy.current_version(),
                "tools": [asdict(item) for item in self.policy.list_tool_policies()],
                "read_only": [asdict(item) for item in self.policy.list_read_only_policies()],
            },
            "audit": {
                "items": [_safe_audit(item) for item in page.items],
                "next_cursor": page.next_cursor,
                "summary": self.audit.summarize(filters),
            },
        })

    def _forgejo_token_file(self, reference: Any) -> str:
        if not isinstance(reference, str) or not SAFE_REF.fullmatch(reference):
            raise ValueError("invalid_forgejo_token_ref")
        if reference not in self.settings.forgejo_token_allowlist:
            raise ValueError("unavailable_forgejo_token_ref")
        root = self.settings.forgejo_token_root.resolve()
        path = root / reference
        try:
            metadata = path.lstat()
            if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
                raise ValueError("unavailable_forgejo_token_ref")
            if path.parent.resolve() != root or not os.access(path, os.R_OK):
                raise ValueError("unavailable_forgejo_token_ref")
        except OSError as exc:
            raise ValueError("unavailable_forgejo_token_ref") from exc
        return str(path)

    async def create_service_account(self, request: Request) -> JSONResponse:
        context, _ = _actor(request)
        data = await _body(request)
        permissions = data.get("repository_permissions", {})
        if not isinstance(permissions, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in permissions.items()
        ):
            raise ValueError("invalid_repository_permissions")
        result = self.lifecycle.create_service_account(
            context, subject_id=_required_string(data.get("subject_id"), "subject_id"),
            forgejo_user_id=_required_int(data.get("forgejo_user_id"), "forgejo_user_id"),
            forgejo_token_file=self._forgejo_token_file(data.get("forgejo_token_ref")),
            allowed_scopes=_strings(data.get("allowed_scopes"), "allowed_scopes"),
            repository_permissions=permissions,
        )
        return _response(result, 201)

    async def service_account_action(self, request: Request) -> JSONResponse:
        context, _ = _actor(request)
        subject = request.path_params["subject_id"]
        action = request.path_params["action"]
        if action == "disable":
            return _response(self.lifecycle.disable_service_account(context, subject))
        if action != "remap":
            raise ValueError("invalid_service_account_action")
        data = await _body(request)
        permissions = data.get("repository_permissions", {})
        if not isinstance(permissions, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in permissions.items()
        ):
            raise ValueError("invalid_repository_permissions")
        return _response(self.lifecycle.remap_service_account(
            context, subject_id=subject,
            forgejo_user_id=_required_int(data.get("forgejo_user_id"), "forgejo_user_id"),
            forgejo_token_file=self._forgejo_token_file(data.get("forgejo_token_ref")),
            allowed_scopes=_strings(data.get("allowed_scopes"), "allowed_scopes"),
            repository_permissions=permissions,
        ))

    async def issue_token(self, request: Request) -> JSONResponse:
        context, _ = _actor(request)
        data = await _body(request)
        issued = self.lifecycle.issue(
            context, subject_id=_required_string(data.get("subject_id"), "subject_id"),
            client_id=_required_string(data.get("client_id"), "client_id"),
            scopes=_strings(data.get("scopes"), "scopes"),
            repositories=_strings(data.get("repositories", []), "repositories"),
            ttl_seconds=_required_int(data.get("ttl_seconds", 2_592_000), "ttl_seconds"),
        )
        return _response({**issued.metadata, "token": issued.token}, 201)

    async def rotate_token(self, request: Request) -> JSONResponse:
        context, _ = _actor(request)
        data = await _body(request)
        issued = self.lifecycle.rotate(
            context, request.path_params["token_id"],
            ttl_seconds=_required_int(data.get("ttl_seconds", 2_592_000), "ttl_seconds"),
        )
        return _response({**issued.metadata, "token": issued.token})

    async def revoke_token(self, request: Request) -> JSONResponse:
        context, _ = _actor(request)
        return _response(self.lifecycle.revoke(context, request.path_params["token_id"]))

    async def change_policy(self, request: Request) -> JSONResponse:
        _, actor = _actor(request)
        data = await _body(request)
        action = _required_string(data.get("action", ""), "action")
        scope = _required_string(data.get("scope", ""), "scope")
        scope_id = _required_string(data.get("scope_id"), "scope_id")
        expected = _required_int(data.get("expected_version", -1), "expected_version")
        if expected < 0:
            raise ValueError("invalid_expected_version")
        metadata: dict[str, Any] = {"scope": scope, "scope_id": scope_id}
        if action in {"allow", "deny", "delete"}:
            tool = _required_string(data.get("tool", ""), "tool")
            metadata["tool"] = tool
            mutate = (
                lambda: self.policy.delete_tool_policy(
                    scope, scope_id, tool, expected_version=expected
                ) if action == "delete" else self.policy.set_tool_policy(
                    scope, scope_id, tool, action, expected_version=expected
                )
            )
            target = f"{scope}:{scope_id}/{tool}"
        elif action in {"read-only", "read-write"}:
            metadata["enabled"] = action == "read-only"
            mutate = lambda: self.policy.set_read_only(
                scope, scope_id, action == "read-only", expected_version=expected
            )
            target = f"{scope}:{scope_id}/read-only"
        else:
            raise ValueError("invalid_policy_action")
        version = self.policy_admin.change(
            actor=actor, request_id=f"admin:{uuid.uuid4()}", target=target,
            action=action, mutate=mutate, metadata=metadata,
        )
        return _response({"policy_version": version})

    async def connection_test(self, request: Request) -> JSONResponse:
        _actor(request)
        data = await _body(request)
        token = data.get("token")
        if not isinstance(token, str) or not token:
            raise ValueError("invalid_token")
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        try:
            async with asyncio.timeout(30), self.http_client_factory(timeout=10) as client:
                results: dict[str, Any] = {}
                counts: dict[str, int | None] = {"tools": None, "resources": None}
                initialize = await client.post(self.settings.mcp_url, headers=headers, json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                        "protocolVersion": MCP_PROTOCOL_VERSION, "capabilities": {},
                        "clientInfo": {"name": "nyankoface-admin-ui", "version": "1"},
                    },
                })
                check, payload = _rpc_check(initialize, "initialize", 1)
                results["initialize"] = check
                if not check["ok"]:
                    return _response({
                        "reachable": True, "ok": False,
                        "reason_code": check["reason_code"],
                        "tools": counts["tools"], "resources": counts["resources"],
                        "checks": results,
                    })

                session_id = initialize.headers.get("mcp-session-id")
                protocol_version = payload["result"]["protocolVersion"]
                request_headers = dict(headers)
                request_headers["MCP-Protocol-Version"] = protocol_version
                if session_id:
                    request_headers["Mcp-Session-Id"] = session_id
                notification = await client.post(
                    self.settings.mcp_url,
                    headers=request_headers,
                    json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                )
                notification_check = _rpc_notification_check(notification)
                results["notifications/initialized"] = notification_check
                if not notification_check["ok"]:
                    return _response({
                        "reachable": True, "ok": False,
                        "reason_code": notification_check["reason_code"],
                        "tools": counts["tools"], "resources": counts["resources"],
                        "checks": results,
                    })

                for request_id, method in enumerate(("tools/list", "resources/list"), 2):
                    response = await client.post(
                        self.settings.mcp_url,
                        headers=request_headers,
                        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": {}},
                    )
                    check, payload = _rpc_check(response, method, request_id)
                    results[method] = check
                    if not check["ok"]:
                        return _response({
                            "reachable": True, "ok": False,
                            "reason_code": check["reason_code"],
                            "tools": counts["tools"], "resources": counts["resources"],
                            "checks": results,
                        })
                    key = "tools" if method == "tools/list" else "resources"
                    counts[key] = len(payload["result"][key])
                return _response({
                    "reachable": True, "ok": True, "reason_code": "ok",
                    "tools": counts["tools"], "resources": counts["resources"],
                    "checks": results,
                })
        except (httpx.HTTPError, TimeoutError):
            return _response({
                "reachable": False, "ok": False, "reason_code": "transport_unreachable",
                "tools": None, "resources": None, "checks": {},
            })


def _rpc_payload(response: httpx.Response) -> dict[str, Any]:
    if "text/event-stream" not in response.headers.get("content-type", ""):
        value = response.json()
        return value if isinstance(value, dict) else {}
    events = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
    return json.loads(events[-1]) if events else {}


def _rpc_notification_check(response: httpx.Response) -> dict[str, Any]:
    check: dict[str, Any] = {"status": response.status_code, "ok": False}
    if response.status_code != 202:
        check["reason_code"] = (
            "http_error" if response.status_code < 200 or response.status_code >= 300
            else "invalid_response"
        )
        return check
    if response.content:
        check["reason_code"] = "invalid_response"
        return check
    check.update({"ok": True, "reason_code": "ok"})
    return check


def _rpc_check(
    response: httpx.Response, method: str, expected_id: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    check: dict[str, Any] = {"status": response.status_code, "ok": False}
    if response.status_code in {401, 403}:
        check["reason_code"] = "authentication_failed"
        return check, {}
    if response.status_code < 200 or response.status_code >= 300:
        check["reason_code"] = "http_error"
        return check, {}
    try:
        payload = _rpc_payload(response)
    except (ValueError, TypeError, json.JSONDecodeError):
        check["reason_code"] = "invalid_response"
        return check, {}
    if not isinstance(payload, dict):
        check["reason_code"] = "invalid_response"
        return check, {}
    if payload.get("jsonrpc") != "2.0" or payload.get("id") != expected_id:
        check["reason_code"] = "invalid_response"
        return check, {}
    error = payload.get("error")
    if isinstance(error, dict):
        message = str(error.get("message", "")).casefold()
        check["reason_code"] = (
            "authentication_failed"
            if "auth" in message or "unauthorized" in message or "forbidden" in message
            else "rpc_error"
        )
        return check, {}
    result = payload.get("result")
    if not isinstance(result, dict):
        check["reason_code"] = "invalid_response"
        return check, {}
    if method == "initialize":
        protocol_version = result.get("protocolVersion")
        if protocol_version != MCP_PROTOCOL_VERSION:
            check["reason_code"] = "invalid_response"
            return check, {}
    if method != "initialize":
        key = "tools" if method == "tools/list" else "resources"
        if not isinstance(result.get(key), list):
            check["reason_code"] = "invalid_response"
            return check, {}
        check["count"] = len(result[key])
    check.update({"ok": True, "reason_code": "ok"})
    return check, payload


def create_admin_app(
    settings: AdminSettings | None = None,
    *,
    http_client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
) -> Starlette:
    api = AdminApi(settings or AdminSettings.from_env(), http_client_factory)

    async def guarded(request: Request, handler: Callable[[Request], Awaitable[JSONResponse]]):
        if not api.authorized(request):
            return _error(401, "unauthorized")
        try:
            return await handler(request)
        except InvalidPolicy as exc:
            return _error(409 if str(exc) == "policy version conflict" else 400, str(exc).replace(" ", "_"))
        except (LifecycleUnavailable, PolicyUnavailable, AuditUnavailable):
            return _error(503, "admin_backend_unavailable")
        except (LifecycleError, InvalidAuditEvent, ValueError) as exc:
            return _error(400, str(exc).replace(" ", "_"))
        except (httpx.HTTPError, OSError):
            return _error(503, "connection_test_unavailable")

    def route(path: str, handler: Callable[[Request], Awaitable[JSONResponse]], methods: list[str]):
        async def endpoint(request: Request):
            return await guarded(request, handler)
        return Route(path, endpoint, methods=methods)

    async def health(_: Request) -> JSONResponse:
        return _response({"status": "ok"})

    return Starlette(routes=[
        Route("/health", health, methods=["GET"]),
        route("/v1/state", api.state, ["GET"]),
        route("/v1/service-accounts", api.create_service_account, ["POST"]),
        route("/v1/service-accounts/{subject_id:str}/{action:str}",
              api.service_account_action, ["POST"]),
        route("/v1/tokens", api.issue_token, ["POST"]),
        route("/v1/tokens/{token_id:str}/rotate", api.rotate_token, ["POST"]),
        route("/v1/tokens/{token_id:str}/revoke", api.revoke_token, ["POST"]),
        route("/v1/policies", api.change_policy, ["PUT"]),
        route("/v1/connection-tests", api.connection_test, ["POST"]),
    ])
