import json
import os
import stat
import time
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

from nyankoface_mcp.admin_http import AdminSettings, create_admin_app
from nyankoface_mcp.audit import AuditStore
from nyankoface_mcp.policy import PolicyRequest, PolicyStore


SECRET = "internal-test-credential-that-is-long-enough"
HEADERS = {
    "Authorization": f"Bearer {SECRET}",
    "X-NyankoFace-Admin-Subject": "human:admin",
    "X-NyankoFace-Admin-Reauthenticated-At": str(int(time.time())),
}


@pytest.mark.skipif(os.name == "nt", reason="POSIX shared writer contract")
def test_shared_sqlite_stores_are_group_writable(tmp_path: Path):
    policy = tmp_path / "policy.sqlite3"
    audit = tmp_path / "audit.sqlite3"
    PolicyStore(policy)
    AuditStore(audit)
    assert stat.S_IMODE(policy.stat().st_mode) & 0o060 == 0o060
    assert stat.S_IMODE(audit.stat().st_mode) & 0o060 == 0o060
    assert stat.S_IMODE(tmp_path.stat().st_mode) & 0o070 == 0o070


def settings(tmp_path: Path) -> AdminSettings:
    internal = tmp_path / "internal.token"
    internal.write_text(SECRET, encoding="utf-8")
    token_root = tmp_path / "forgejo-tokens"
    token_root.mkdir(exist_ok=True)
    (token_root / "automation").write_text("not-returned", encoding="utf-8")
    return AdminSettings(
        internal_token_file=internal,
        registry_path=tmp_path / "registry.json",
        lifecycle_audit_path=tmp_path / "lifecycle.jsonl",
        forgejo_token_root=token_root,
        forgejo_token_allowlist=("automation",),
        policy_path=tmp_path / "policy.sqlite3",
        audit_path=tmp_path / "audit.sqlite3",
        mcp_url="http://mcp.invalid/mcp",
    )


def create_account(client: TestClient):
    return client.post("/v1/service-accounts", headers=HEADERS, json={
        "subject_id": "service:codex",
        "forgejo_user_id": 42,
        "forgejo_token_ref": "automation",
        "allowed_scopes": ["catalog:read", "repos:read"],
        "repository_permissions": {"nyankoface/sample-model": "read"},
    })


def test_admin_api_fails_closed_without_internal_credential_or_actor(tmp_path):
    with TestClient(create_admin_app(settings(tmp_path))) as client:
        assert client.get("/v1/state").status_code == 401
        assert client.get("/v1/state", headers={
            "Authorization": f"Bearer {SECRET}",
        }).json() == {"error": "invalid_actor"}
        assert client.get("/v1/state", headers={
            **HEADERS, "Authorization": "Bearer wrong-but-similar-credential",
        }).status_code == 401


def test_admin_api_requires_current_server_verified_reauthentication(tmp_path):
    with TestClient(create_admin_app(settings(tmp_path))) as client:
        missing = dict(HEADERS)
        missing.pop("X-NyankoFace-Admin-Reauthenticated-At")
        assert client.get("/v1/state", headers=missing).json() == {
            "error": "fresh_reauthentication_required"
        }
        assert client.get("/v1/state", headers={
            **HEADERS,
            "X-NyankoFace-Admin-Reauthenticated-At": str(int(time.time()) - 301),
        }).json() == {"error": "fresh_reauthentication_required"}
        assert client.get("/v1/state", headers={
            **HEADERS,
            "X-NyankoFace-Admin-Reauthenticated-At": str(int(time.time()) + 1),
        }).json() == {"error": "fresh_reauthentication_required"}


def test_service_account_rejects_unavailable_or_unmounted_secret_reference(tmp_path):
    configured = settings(tmp_path)
    with TestClient(create_admin_app(configured)) as client:
        payload = {
            "subject_id": "service:codex",
            "forgejo_user_id": 42,
            "forgejo_token_ref": "not-mounted",
            "allowed_scopes": ["catalog:read"],
            "repository_permissions": {"nyankoface/sample-model": "read"},
        }
        response = client.post("/v1/service-accounts", headers=HEADERS, json=payload)
        assert response.status_code == 400
        assert response.json() == {"error": "unavailable_forgejo_token_ref"}

        missing_settings = AdminSettings(
            **{**configured.__dict__, "forgejo_token_allowlist": ("missing",)}
        )
        with TestClient(create_admin_app(missing_settings)) as missing_client:
            payload["forgejo_token_ref"] = "missing"
            response = missing_client.post(
                "/v1/service-accounts", headers=HEADERS, json=payload
            )
            assert response.status_code == 400
            assert response.json() == {"error": "unavailable_forgejo_token_ref"}


@pytest.mark.parametrize(
    ("endpoint", "payload", "expected"),
    [
        (
            "/v1/service-accounts",
            {
                "subject_id": None,
                "forgejo_user_id": 42,
                "forgejo_token_ref": "automation",
                "allowed_scopes": ["catalog:read"],
                "repository_permissions": {},
            },
            {"error": "invalid_subject_id"},
        ),
        (
            "/v1/tokens",
            {
                "subject_id": None,
                "client_id": "codex",
                "scopes": ["catalog:read"],
                "repositories": [],
            },
            {"error": "invalid_subject_id"},
        ),
        (
            "/v1/tokens",
            {
                "subject_id": "service:codex",
                "client_id": None,
                "scopes": ["catalog:read"],
                "repositories": [],
            },
            {"error": "invalid_client_id"},
        ),
    ],
)
def test_admin_api_rejects_null_governance_identifiers(tmp_path, endpoint, payload, expected):
    with TestClient(create_admin_app(settings(tmp_path))) as client:
        response = client.post(endpoint, headers=HEADERS, json=payload)
    assert response.status_code == 400
    assert response.json() == expected


@pytest.mark.parametrize("forgejo_user_id", [42.9, None, True])
def test_service_account_rejects_non_integer_forgejo_user_id(tmp_path, forgejo_user_id):
    with TestClient(create_admin_app(settings(tmp_path))) as client:
        response = client.post("/v1/service-accounts", headers=HEADERS, json={
            "subject_id": "service:codex",
            "forgejo_user_id": forgejo_user_id,
            "forgejo_token_ref": "automation",
            "allowed_scopes": ["catalog:read"],
            "repository_permissions": {},
        })
    assert response.status_code == 400
    assert response.json() == {"error": "invalid_forgejo_user_id"}


def test_service_account_rejects_symlinked_secret_reference(tmp_path):
    configured = settings(tmp_path)
    linked = configured.forgejo_token_root / "linked"
    try:
        linked.symlink_to(configured.forgejo_token_root / "automation")
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")
    symlink_settings = AdminSettings(
        **{**configured.__dict__, "forgejo_token_allowlist": ("linked",)}
    )
    with TestClient(create_admin_app(symlink_settings)) as client:
        response = client.post("/v1/service-accounts", headers=HEADERS, json={
            "subject_id": "service:codex",
            "forgejo_user_id": 42,
            "forgejo_token_ref": "linked",
            "allowed_scopes": ["catalog:read"],
            "repository_permissions": {"nyankoface/sample-model": "read"},
        })
    assert response.status_code == 400
    assert response.json() == {"error": "unavailable_forgejo_token_ref"}


def test_plaintext_token_is_returned_once_and_never_listed(tmp_path):
    configured = settings(tmp_path)
    with TestClient(create_admin_app(configured)) as client:
        assert create_account(client).status_code == 201
        issued = client.post("/v1/tokens", headers=HEADERS, json={
            "subject_id": "service:codex",
            "client_id": "codex",
            "scopes": ["catalog:read"],
            "repositories": ["nyankoface/sample-model"],
            "ttl_seconds": 600,
        })
        assert issued.status_code == 201
        assert issued.headers["cache-control"] == "private, no-store, max-age=0"
        plaintext = issued.json().pop("token")
        assert plaintext

        state = client.get("/v1/state", headers=HEADERS)
        serialized = state.text
        assert plaintext not in serialized
        assert "token_sha256" not in serialized
        assert "forgejo_token_file" not in serialized
        assert str(configured.forgejo_token_root) not in serialized

        registry = json.loads(configured.registry_path.read_text(encoding="utf-8"))
        assert plaintext not in configured.registry_path.read_text(encoding="utf-8")
        assert registry["tokens"][0]["token_sha256"]


def test_policy_change_requires_current_revision_and_applies_next_request(tmp_path):
    configured = settings(tmp_path)
    with TestClient(create_admin_app(configured)) as client:
        state = client.get("/v1/state", headers=HEADERS).json()
        assert state["policy"]["version"] == 0
        changed = client.put("/v1/policies", headers=HEADERS, json={
            "action": "allow", "scope": "global", "scope_id": "*",
            "tool": "search_catalog", "expected_version": 0,
        })
        assert changed.json() == {"policy_version": 1}
        conflict = client.put("/v1/policies", headers=HEADERS, json={
            "action": "deny", "scope": "global", "scope_id": "*",
            "tool": "search_catalog", "expected_version": 0,
        })
        assert conflict.status_code == 409

        decision = PolicyStore(configured.policy_path).evaluate(PolicyRequest(
            subject_id="service:codex", subject_type="service_account",
            client_id="codex", tool="search_catalog", access="read",
        ))
        assert decision.allowed is True
        state = client.get("/v1/state", headers=HEADERS).json()
        assert state["policy"]["version"] == 1
        reasons = {item["reason_code"] for item in state["audit"]["items"]}
        assert {"policy_change_applied", "policy_change_failed"}.issubset(reasons)
        assert "event_hash" not in json.dumps(state["audit"])
        assert state["audit"]["summary"]["total"] == len(state["audit"]["items"])
        assert state["audit"]["summary"]["by_outcome"]["changed"] == 1
        assert state["audit"]["summary"]["by_outcome"]["failed"] == 1

        period = client.get(
            "/v1/state?after=1&before=9999999999&outcome=changed", headers=HEADERS,
        ).json()["audit"]
        assert len(period["items"]) == 1
        assert period["summary"]["by_outcome"] == {"changed": 1}
        assert client.get("/v1/state?after=20&before=10", headers=HEADERS).json() == {
            "error": "invalid_audit_period"
        }


def test_policy_change_rejects_null_scope_id_before_mutation(tmp_path):
    configured = settings(tmp_path)
    with TestClient(create_admin_app(configured)) as client:
        response = client.put("/v1/policies", headers=HEADERS, json={
            "action": "allow", "scope": "subject", "scope_id": None,
            "tool": "search_catalog", "expected_version": 0,
        })
        assert response.status_code == 400
        assert response.json() == {"error": "invalid_scope_id"}
        assert client.get("/v1/state", headers=HEADERS).json()["policy"]["version"] == 0


@pytest.mark.parametrize("action", ["read-only", "read-write"])
def test_policy_read_modes_do_not_require_tool(tmp_path, action):
    with TestClient(create_admin_app(settings(tmp_path))) as client:
        response = client.put("/v1/policies", headers=HEADERS, json={
            "action": action, "scope": "global", "scope_id": "*",
            "expected_version": 0,
        })
    assert response.status_code == 200
    assert response.json() == {"policy_version": 1}


def test_lifecycle_store_unavailability_returns_503(tmp_path):
    configured = settings(tmp_path)
    app = create_admin_app(configured)
    configured.registry_path.write_text("{malformed", encoding="utf-8")
    with TestClient(app) as client:
        response = client.get("/v1/state", headers=HEADERS)
    assert response.status_code == 503
    assert response.json() == {"error": "admin_backend_unavailable"}


def test_lifecycle_store_rejects_malformed_record_schema_with_503(tmp_path):
    configured = settings(tmp_path)
    configured.registry_path.write_text(json.dumps({
        "version": 2,
        "subjects": [{"subject_id": "service:codex", "mapping_version": []}],
        "tokens": [],
    }), encoding="utf-8")
    with TestClient(create_admin_app(configured)) as client:
        response = client.post(
            "/v1/service-accounts/service:codex/disable", headers=HEADERS,
        )
    assert response.status_code == 503
    assert response.json() == {"error": "admin_backend_unavailable"}


def test_lifecycle_store_rejects_malformed_expiry_schema_with_503(tmp_path):
    configured = settings(tmp_path)
    configured.registry_path.write_text(json.dumps({
        "version": 2,
        "subjects": [],
        "tokens": [{"token_id": "token-1", "expires_at": None}],
    }), encoding="utf-8")
    with TestClient(create_admin_app(configured)) as client:
        response = client.get("/v1/state", headers=HEADERS)
    assert response.status_code == 503
    assert response.json() == {"error": "admin_backend_unavailable"}


def test_lifecycle_store_rejects_missing_required_token_field_with_503(tmp_path):
    configured = settings(tmp_path)
    configured.registry_path.write_text(json.dumps({
        "version": 2,
        "subjects": [],
        "tokens": [{
            "token_id": "token-1",
            "token_sha256": "0" * 64,
            "subject_id": "service:codex",
            "subject_type": "service_account",
            "audience": "nyankoface-api-v1",
            "scopes": [],
            "repositories": [],
            "mapping_version": 1,
            "created_at": 1,
            "expires_at": 100,
            "revoked_at": None,
        }],
    }), encoding="utf-8")
    with TestClient(create_admin_app(configured)) as client:
        response = client.get("/v1/state", headers=HEADERS)
    assert response.status_code == 503
    assert response.json() == {"error": "admin_backend_unavailable"}


def test_lifecycle_store_write_io_failure_returns_503(tmp_path, monkeypatch):
    configured = settings(tmp_path)

    def unavailable(*args, **kwargs):
        raise OSError("registry volume is unavailable")

    monkeypatch.setattr("nyankoface_mcp.lifecycle.tempfile.mkstemp", unavailable)
    with TestClient(create_admin_app(configured)) as client:
        response = create_account(client)
    assert response.status_code == 503
    assert response.json() == {"error": "admin_backend_unavailable"}


def test_operator_cannot_supply_arbitrary_pat_path(tmp_path):
    with TestClient(create_admin_app(settings(tmp_path))) as client:
        response = client.post("/v1/service-accounts", headers=HEADERS, json={
            "subject_id": "service:bad", "forgejo_user_id": 1,
            "forgejo_token_ref": "../../admin", "allowed_scopes": ["catalog:read"],
            "repository_permissions": {},
        })
        assert response.json() == {"error": "invalid_forgejo_token_ref"}


def test_service_account_can_be_remapped_and_disabled(tmp_path):
    with TestClient(create_admin_app(settings(tmp_path))) as client:
        assert create_account(client).status_code == 201

        remapped = client.post(
            "/v1/service-accounts/service:codex/remap",
            headers=HEADERS,
            json={
                "forgejo_user_id": 84,
                "forgejo_token_ref": "automation",
                "allowed_scopes": ["repos:read"],
                "repository_permissions": {"nyankoface/sample-model": "write"},
            },
        )
        assert remapped.status_code == 200
        assert remapped.json()["forgejo_user_id"] == 84

        disabled = client.post(
            "/v1/service-accounts/service:codex/disable", headers=HEADERS,
        )
        assert disabled.status_code == 200
        assert disabled.json()["enabled"] is False

        state = client.get("/v1/state", headers=HEADERS).json()
        account = state["service_accounts"][0]
        assert account["forgejo_user_id"] == 84
        assert account["repository_permissions"] == {"nyankoface/sample-model": "write"}
        assert account["enabled"] is False
        serialized = json.dumps(state)
        assert "forgejo_token_file" not in serialized
        assert "automation" not in serialized


def test_service_account_remap_rejects_non_string_permission_values(tmp_path):
    with TestClient(create_admin_app(settings(tmp_path))) as client:
        assert create_account(client).status_code == 201
        response = client.post(
            "/v1/service-accounts/service:codex/remap",
            headers=HEADERS,
            json={
                "forgejo_user_id": 84,
                "forgejo_token_ref": "automation",
                "allowed_scopes": ["repos:read"],
                "repository_permissions": {"nyankoface/sample-model": []},
            },
        )
    assert response.status_code == 400
    assert response.json() == {"error": "invalid_repository_permissions"}


def test_connection_test_initializes_session_and_counts_capabilities(tmp_path):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        payload = json.loads(request.content)
        method = payload["method"]
        if method == "initialize":
            return httpx.Response(200, headers={"mcp-session-id": "session-1"}, json={
                "jsonrpc": "2.0", "id": payload["id"],
                "result": {"protocolVersion": "2025-06-18", "capabilities": {}},
            })
        if method == "notifications/initialized":
            return httpx.Response(202)
        key = "tools" if method == "tools/list" else "resources"
        values = [{"name": "one"}, {"name": "two"}] if key == "tools" else [{"uri": "one"}]
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": payload["id"], "result": {key: values},
        })

    factory = lambda **kwargs: httpx.AsyncClient(  # noqa: E731
        transport=httpx.MockTransport(handler), **kwargs
    )
    with TestClient(create_admin_app(settings(tmp_path), http_client_factory=factory)) as client:
        report = client.post(
            "/v1/connection-tests", headers=HEADERS, json={"token": "one-time-secret"},
        ).json()

    assert report == {
        "reachable": True, "ok": True, "reason_code": "ok", "tools": 2, "resources": 1,
        "checks": {
            "initialize": {"status": 200, "ok": True, "reason_code": "ok"},
            "notifications/initialized": {"status": 202, "ok": True, "reason_code": "ok"},
            "tools/list": {"status": 200, "ok": True, "reason_code": "ok", "count": 2},
            "resources/list": {"status": 200, "ok": True, "reason_code": "ok", "count": 1},
        },
    }
    assert [json.loads(request.content)["method"] for request in seen] == [
        "initialize", "notifications/initialized", "tools/list", "resources/list",
    ]
    assert all(request.headers["authorization"] == "Bearer one-time-secret" for request in seen)
    assert all(
        request.headers["mcp-protocol-version"] == "2025-06-18"
        for request in seen[1:]
    )
    assert all(request.headers["mcp-session-id"] == "session-1" for request in seen[1:])
    assert "one-time-secret" not in json.dumps(report)


def test_connection_test_reports_auth_rpc_and_transport_errors_without_secrets(tmp_path):
    secret = "secret-that-must-never-escape"

    def run(handler):
        factory = lambda **kwargs: httpx.AsyncClient(  # noqa: E731
            transport=httpx.MockTransport(handler), **kwargs
        )
        with TestClient(create_admin_app(settings(tmp_path), http_client_factory=factory)) as client:
            return client.post(
                "/v1/connection-tests", headers=HEADERS, json={"token": secret},
            ).json()

    unauthorized = run(lambda _: httpx.Response(401, text=f"rejected {secret}"))
    assert unauthorized["reachable"] is True
    assert unauthorized["ok"] is False
    assert unauthorized["reason_code"] == "authentication_failed"
    assert secret not in json.dumps(unauthorized)

    rpc_error = run(lambda request: httpx.Response(200, json={
        "jsonrpc": "2.0", "id": 1,
        "error": {"code": -32001, "message": f"Unauthorized bearer {secret}"},
    }))
    assert rpc_error["reason_code"] == "authentication_failed"
    assert secret not in json.dumps(rpc_error)

    malformed = run(lambda _: httpx.Response(200, json=[secret]))
    assert malformed["reason_code"] == "invalid_response"
    assert secret not in json.dumps(malformed)

    def disconnected(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {secret}", request=request)

    transport = run(disconnected)
    assert transport == {
        "reachable": False, "ok": False, "reason_code": "transport_unreachable",
        "tools": None, "resources": None, "checks": {},
    }

    missing_jsonrpc = run(lambda _: httpx.Response(200, json={
        "id": 1, "result": {"protocolVersion": "2025-06-18"},
    }))
    assert missing_jsonrpc["reason_code"] == "invalid_response"

    mismatched_id = run(lambda _: httpx.Response(200, json={
        "jsonrpc": "2.0", "id": 999,
        "result": {"protocolVersion": "2025-06-18"},
    }))
    assert mismatched_id["reason_code"] == "invalid_response"

    unsupported_version = run(lambda _: httpx.Response(200, json={
        "jsonrpc": "2.0", "id": 1,
        "result": {"protocolVersion": "2099-01-01"},
    }))
    assert unsupported_version["reason_code"] == "invalid_response"
