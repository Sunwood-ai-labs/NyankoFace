import hashlib
import json
from pathlib import Path

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from nyankoface_mcp.config import Settings
from nyankoface_mcp.audit import AuditFilter, AuditStore, AuditUnavailable
from nyankoface_mcp.governance import ToolPolicyGate
from nyankoface_mcp.policy import PolicyStore
from nyankoface_mcp.server import (
    TransportContractMiddleware,
    create_server,
    decode_resource_ref,
    encode_resource_ref,
)
from nyankoface_mcp.server import TOOL_ACCESS
from nyankoface_mcp.write_safety import WriteIdentity, WriteSafetyStore, fingerprint


ROOT = Path(__file__).resolve().parents[2]


class FakeAdapter:
    def __init__(self):
        self.authorizations = 0
        self.mutations = []
        self.repository_reads = []
        self.repository_access = True

    async def get_current_user_id(self, token):
        if token == "caller-pat":
            return 42
        raise ToolError("invalid Forgejo token")

    async def search_catalog(self, kind, query="", page=1, limit=20):
        return {"kind": kind, "items": [{"full_name": "nyankoface/demo", "private": False}]}

    async def get_repository(self, owner, repo, token):
        self.repository_reads.append((owner, repo, token))
        if not self.repository_access:
            raise ToolError("Resource was not found or is not authorized")
        return {"full_name": f"{owner}/{repo}", "private": False}

    async def list_repositories(self, query, page, limit, token):
        return {"items": [], "page": page, "limit": limit}

    async def get_file(self, owner, repo, path, ref, token):
        return {"path": path, "ref": ref, "text": "hello"}

    async def get_tree(self, owner, repo, ref, token):
        return {"owner": owner, "repo": repo, "ref": ref, "entries": []}

    async def get_knowledge(self, owner, slug, token):
        return {"owner": owner, "slug": slug, "title": "Example"}

    async def list_issues(self, owner, repo, state, page, limit, token):
        return {"items": []}

    async def get_issue(self, owner, repo, number, token):
        return {"number": number, "title": "example"}

    async def get_status(self, surface, owner, repo, token):
        return {"surface": surface, "status": "running"}

    async def authorize_issue_write(self, owner, repo, token):
        self.authorizations += 1

    async def authorize_control_write(self, owner, repo, token):
        self.authorizations += 1

    async def create_issue(self, owner, repo, title, body, token):
        self.mutations.append(("create", owner, repo, title, body, token))
        return {"number": 1, "title": title}

    async def update_issue(self, owner, repo, number, changes, token):
        self.mutations.append(("update", owner, repo, number, changes, token))
        return {"number": number, **changes}

    async def comment_issue(self, owner, repo, number, body, token):
        self.mutations.append(("comment", owner, repo, number, body, token))
        return {"id": 4, "body": body}

    async def control_space(self, action, owner, repo, token):
        self.mutations.append((action, owner, repo, token))
        return {"status": "accepted", "action": action}

    async def set_space_environment(self, owner, repo, name, kind, value, scope, token):
        self.mutations.append(("set_environment", owner, repo, name, kind, value, scope, token))
        return {"item": {"name": name, "kind": kind, "scope": scope, "configured": True}}

    async def delete_space_environment(self, owner, repo, name, kind, token):
        self.mutations.append(("delete_environment", owner, repo, name, kind, token))
        return {"deleted": True, "name": name}

    async def apply_space_environment(self, owner, repo, revision, token):
        self.mutations.append(("apply_environment", owner, repo, revision, token))
        return {"status": "applied", "restart_required": False}

    async def deploy_pages(self, owner, repo, method, token):
        self.mutations.append(("deploy", owner, repo, method, token))
        return {"status": "queued", "method": method}

    async def dispatch_pipeline(
        self, owner, repo, workflow, ref, environment, inputs, token,
    ):
        self.mutations.append((
            "dispatch", owner, repo, workflow, ref, environment, inputs, token,
        ))
        return {"status": "queued", "workflow": workflow}

    async def pipeline_action(self, action, owner, repo, run_number, token):
        self.mutations.append((action, owner, repo, run_number, token))
        return {"status": "accepted", "action": action, "run_number": run_number}

    async def get_space_environment_metadata(self, owner, repo, token):
        return {"data": {"items": []}, "_meta": {"mime_type": "application/json"}}

    async def list_pipeline_runs(self, owner, repo, page, limit, token):
        return {
            "data": {"items": []},
            "_meta": {"mime_type": "application/json", "pagination": {"page": page}},
        }

    async def get_pipeline_run(self, owner, repo, run_number, token):
        return {"data": {"run_number": run_number}, "_meta": {"mime_type": "application/json"}}

    async def get_metrics(self, owner, repo, token):
        return {"data": {"views": 0}, "_meta": {"mime_type": "application/json"}}

    async def get_openapi(self):
        return {"data": {"openapi": "3.1.0"}, "_meta": {"mime_type": "application/json"}}


def make_settings(tmp_path, *, json_response, scopes=None, configure_policy=True):
    token_file = tmp_path / ("tokens-json.json" if json_response else "tokens-sse.json")
    (tmp_path / "forgejo-token").write_text("caller-pat", encoding="utf-8")
    effective_scopes = scopes or [
        "catalog:read", "repos:read", "issues:read", "spaces:read",
        "pages:read", "pipelines:read", "issues:write", "metrics:read",
        "spaces:run", "pages:deploy", "pipelines:write",
        "variables:write", "secrets:write",
    ]
    token_file.write_text(json.dumps({"version": 2, "subjects": [{
        "subject_id": "service:test",
        "subject_type": "service_account",
        "enabled": True,
        "forgejo_user_id": 42,
        "forgejo_token_file": str(tmp_path / "forgejo-token"),
        "allowed_scopes": effective_scopes,
        "repository_permissions": {"NyankoFace/Demo": "write"},
        "mapping_version": 1,
    }], "tokens": [{
        "token_id": "00000000-0000-4000-8000-000000000001",
        "token_sha256": hashlib.sha256(b"test-token").hexdigest(),
        "client_id": "test",
        "subject_id": "service:test",
        "subject_type": "service_account",
        "audience": "nyankoface-api-v1",
        "scopes": effective_scopes,
        "repositories": ["NyankoFace/Demo"],
        "mapping_version": 1,
        "expires_at": 4102444800,
        "revoked_at": None,
    }]}), encoding="utf-8")
    settings = Settings(
        public_base_url="http://testserver",
        token_file=token_file,
        json_response=json_response,
        allowed_hosts=("testserver",),
        write_state_path=tmp_path / "write-safety.sqlite3",
        policy_state_path=tmp_path / "policy.sqlite3",
        audit_state_path=tmp_path / "audit.sqlite3",
    )
    policy = PolicyStore(settings.policy_state_path)
    if configure_policy:
        for tool in TOOL_ACCESS:
            policy.set_tool_policy("global", "*", tool, "allow")
    return settings


def initialize_payload(request_id=1):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "contract-test", "version": "1.0"},
        },
    }


async def post(app, payload, *, token="test-token"):
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(
                "/mcp",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                json=payload,
            )


async def post_many(app, payloads):
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            responses = []
            for payload in payloads:
                responses.append(await client.post(
                    "/mcp",
                    headers={
                        "Authorization": "Bearer test-token",
                        "Accept": "application/json, text/event-stream",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                ))
            return responses


@pytest.mark.asyncio
async def test_json_initialize_is_stateless_and_safe_to_retry(tmp_path):
    app_one = create_server(make_settings(tmp_path, json_response=True), FakeAdapter()).streamable_http_app()
    first = await post(app_one, initialize_payload(1))
    app_two = create_server(make_settings(tmp_path, json_response=True), FakeAdapter()).streamable_http_app()
    retry = await post(app_two, initialize_payload(1))

    assert first.status_code == retry.status_code == 200
    assert first.headers["content-type"].startswith("application/json")
    assert "mcp-session-id" not in first.headers
    assert first.json()["result"]["serverInfo"]["name"] == "NyankoFace"
    assert retry.json()["result"]["serverInfo"]["name"] == "NyankoFace"


@pytest.mark.asyncio
async def test_sse_initialize_and_retry_are_stateless(tmp_path):
    app_one = create_server(make_settings(tmp_path, json_response=False), FakeAdapter()).streamable_http_app()
    first = await post(app_one, initialize_payload(2))
    app_two = create_server(make_settings(tmp_path, json_response=False), FakeAdapter()).streamable_http_app()
    retry = await post(app_two, initialize_payload(2))

    assert first.status_code == retry.status_code == 200
    assert first.headers["content-type"].startswith("text/event-stream")
    assert "mcp-session-id" not in first.headers
    assert "event: message" in first.text
    assert '"name":"NyankoFace"' in first.text
    assert retry.text == first.text


@pytest.mark.asyncio
async def test_transport_exposes_instance_and_rejects_last_event_id(tmp_path):
    inner = create_server(
        make_settings(tmp_path, json_response=False), FakeAdapter(),
    ).streamable_http_app()
    app = TransportContractMiddleware(inner, "mcp-a")
    transport = httpx.ASGITransport(app=app)
    async with inner.router.lifespan_context(inner):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            healthy = await client.post(
                "/mcp",
                headers={
                    "Authorization": "Bearer test-token",
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                json=initialize_payload(20),
            )
            rejected = await client.post(
                "/mcp",
                headers={"Last-Event-ID": "event-1"},
                json=initialize_payload(21),
            )

    assert healthy.headers["x-nyankoface-mcp-instance"] == "mcp-a"
    assert rejected.status_code == 400
    assert rejected.headers["x-nyankoface-mcp-instance"] == "mcp-a"
    assert rejected.json()["error"] == "last_event_id_not_supported"
    assert "idempotency_key" in rejected.json()["retry"]


def test_production_compose_and_gateway_keep_the_ha_safety_boundary():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    gateway = (ROOT / "gateway/nginx.conf").read_text(encoding="utf-8")

    mcp_service = compose.split("  nyankoface-mcp:", 1)[1].split("\n  forgejo:", 1)[0]
    assert "replicas: 2" in mcp_service
    assert "nyankoface-mcp-state:/data" in mcp_service
    assert "container_name:" not in mcp_service
    assert "client_max_body_size 1m;" in gateway
    assert "limit_req zone=mcp_per_ip burst=20 nodelay;" in gateway
    assert "proxy_request_buffering on;" in gateway
    assert "proxy_next_upstream off;" in gateway
    assert "proxy_read_timeout 30s;" in gateway
    assert "upstream nyankoface_mcp_backend" in gateway
    assert "zone nyankoface_mcp_backend 64k;" in gateway
    assert "resolver 127.0.0.11 valid=1s ipv6=off;" in gateway
    assert "server nyankoface-mcp:8000 resolve max_fails=1 fail_timeout=1s;" in gateway
    assert "proxy_pass http://nyankoface_mcp_backend;" in gateway
    assert "$mcp_upstream" not in gateway


def test_ha_e2e_allocates_an_isolated_project_and_loopback_port():
    compose = (ROOT / "compose.mcp-ha.test.yml").read_text(encoding="utf-8")
    runner = (ROOT / "nyankoface-mcp/scripts/run_ha_e2e.py").read_text(encoding="utf-8")

    assert not compose.startswith("name:")
    assert '"127.0.0.1::443"' in compose
    assert "uuid.uuid4().hex" in runner
    assert '"-p", PROJECT' in runner
    assert 'compose("port", "gateway", "443"' in runner


def test_production_ha_e2e_uses_the_shipped_compose_and_gateway():
    override = (ROOT / "compose.mcp-production-ha.test.yml").read_text(encoding="utf-8")
    runner = (ROOT / "nyankoface-mcp/scripts/run_production_ha_e2e.py").read_text(
        encoding="utf-8"
    )

    assert '"-f", "docker-compose.yml"' in runner
    assert '"-f", "compose.mcp-production-ha.test.yml"' in runner
    assert '"nyankoface-mcp", "gateway"' in runner
    assert 'subprocess.run(["docker", "stop", active]' in runner
    assert 'subprocess.run(["docker", "stop", standby]' in runner
    assert "assert_stable(lambda: request(URL), standby_instance)" in runner
    assert "assert_stable(internal_request, standby_instance)" in runner
    assert "assert_stable(lambda: request(URL), first)" in runner
    assert "assert_stable(internal_request, first)" in runner
    assert '"127.0.0.1::443"' in override
    assert 'compose("down", "--remove-orphans")' in runner
    assert 'compose("down", "--volumes"' not in runner
    assert 'f"{PROJECT}_production-mcp-state"' in runner


def test_production_ha_e2e_regresses_public_tls_initialize_route():
    runner = (ROOT / "nyankoface-mcp/scripts/run_production_ha_e2e.py").read_text(
        encoding="utf-8"
    )
    assert '"method": "initialize"' in runner
    assert '"Accept": "application/json, text/event-stream"' in runner
    assert '"Content-Type": "application/json"' in runner
    assert 'URL = f"https://localhost:' in runner
    assert "wait_for_unauthorized(lambda: request(URL))" in runner
    assert "assert_stable(lambda: request(URL), standby_instance)" in runner


@pytest.mark.asyncio
async def test_invalid_token_is_rejected(tmp_path):
    app = create_server(make_settings(tmp_path, json_response=True), FakeAdapter()).streamable_http_app()
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/mcp",
                headers={
                    "Authorization": "Bearer wrong",
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                json=initialize_payload(),
            )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_tool_contract_exposes_bounded_reads_and_safe_writes(tmp_path):
    app = create_server(make_settings(tmp_path, json_response=True), FakeAdapter()).streamable_http_app()
    response = await post(app, {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}})
    names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert names == set(TOOL_ACCESS) == {
        "search_catalog", "list_repositories", "get_repository", "get_file", "get_tree",
        "get_knowledge", "list_issues", "get_issue",
        "get_space_status", "get_pages_status", "list_pipeline_runs",
        "create_issue", "update_issue", "comment_issue",
        "get_space_environment_metadata", "get_pipeline_run", "get_metrics",
        "start_space", "stop_space", "restart_space", "deploy_pages",
        "dispatch_pipeline", "cancel_pipeline", "rollback_pipeline",
        "set_space_variable", "delete_space_variable",
        "set_space_secret", "delete_space_secret", "apply_space_environment",
        "get_operation", "reconcile_operation",
    }

    template_app = create_server(make_settings(tmp_path, json_response=True), FakeAdapter()).streamable_http_app()
    templates = await post(template_app, {
        "jsonrpc": "2.0", "id": 31, "method": "resources/templates/list", "params": {},
    })
    uris = {item["uriTemplate"] for item in templates.json()["result"]["resourceTemplates"]}
    assert uris == {
        "nyankoface://catalog/{kind}",
        "nyankoface://repos/{owner}/{repo}",
        "nyankoface://repos/{owner}/{repo}/tree/{ref_b64}",
        "nyankoface://knowledge/{owner}/{slug}",
        "nyankoface://issues/{owner}/{repo}/{number}",
        "nyankoface://spaces/{owner}/{repo}/status",
        "nyankoface://pages/{owner}/{repo}/status",
        "nyankoface://pipelines/{owner}/{repo}/runs",
        "nyankoface://operations/{operation_id}",
    }
    assert {
        item["uriTemplate"]: item.get("mimeType")
        for item in templates.json()["result"]["resourceTemplates"]
    }["nyankoface://repos/{owner}/{repo}/tree/{ref_b64}"] == "application/json"

    resource_app = create_server(
        make_settings(tmp_path, json_response=True), FakeAdapter(),
    ).streamable_http_app()
    resources = await post(resource_app, {
        "jsonrpc": "2.0", "id": 311, "method": "resources/list", "params": {},
    })
    assert {item["uri"] for item in resources.json()["result"]["resources"]} == {
        "nyankoface://api/openapi",
    }

    prompt_app = create_server(make_settings(tmp_path, json_response=True), FakeAdapter()).streamable_http_app()
    prompts = await post(prompt_app, {
        "jsonrpc": "2.0", "id": 32, "method": "prompts/list", "params": {},
    })
    assert {item["name"] for item in prompts.json()["result"]["prompts"]} == {
        "diagnose_space", "publish_pages", "analyze_pipeline_failure",
        "validate_topics", "publish_content",
    }


@pytest.mark.asyncio
async def test_tool_scope_is_checked_per_call(tmp_path):
    settings = make_settings(tmp_path, json_response=True, scopes=["catalog:read"])
    app = create_server(settings, FakeAdapter()).streamable_http_app()
    response = await post(app, {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {"name": "get_repository", "arguments": {"owner": "nyankoface", "repo": "demo"}},
    })
    result = response.json()["result"]
    assert result["isError"] is True
    assert "repos:read" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_direct_forgejo_bearer_can_call_read_tool_without_policy_provisioning(tmp_path):
    settings = make_settings(tmp_path, json_response=True, configure_policy=False)
    response = await post(
        create_server(settings, FakeAdapter()).streamable_http_app(),
        tool_payload("search_catalog", {
            "kind": "doc", "query": "", "page": 1, "limit": 1,
        }, 5),
        token="caller-pat",
    )

    result = structured(response)
    assert result["kind"] == "doc"
    assert result["items"]


@pytest.mark.asyncio
async def test_direct_forgejo_bearer_reaches_upstream_write_permission_check(tmp_path):
    adapter = FakeAdapter()
    settings = make_settings(tmp_path, json_response=True, configure_policy=False)
    arguments = {
        "owner": "nyankoface", "repo": "demo", "title": "direct Forgejo write",
    }
    preview = structured(await post(
        create_server(settings, adapter).streamable_http_app(),
        tool_payload("create_issue", arguments, 6),
        token="caller-pat",
    ))
    assert preview["status"] == "preview"
    assert adapter.authorizations == 1

    execution = structured(await post(
        create_server(settings, adapter).streamable_http_app(),
        tool_payload("create_issue", {
            **arguments,
            "preview": False,
            "confirmation": preview["confirmation"],
            "idempotency_key": "direct-forgejo-write",
        }, 7),
        token="caller-pat",
    ))
    assert execution["status"] == "completed"
    assert adapter.authorizations == 2
    assert len(adapter.mutations) == 1


def tool_payload(name, arguments, request_id):
    return {
        "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


def structured(response):
    result = response.json()["result"]
    assert result.get("isError") is not True, result
    return result["structuredContent"]


@pytest.mark.asyncio
async def test_read_only_policy_allows_reads_and_denies_writes_before_side_effects(tmp_path):
    adapter = FakeAdapter()
    settings = make_settings(tmp_path, json_response=True)
    PolicyStore(settings.policy_state_path).set_read_only("global", "*", True)
    app = create_server(settings, adapter).streamable_http_app()

    read, write = await post_many(app, [
        tool_payload("get_repository", {"owner": "nyankoface", "repo": "demo"}, 7),
        tool_payload("create_issue", {
            "owner": "nyankoface", "repo": "demo", "title": "must not run",
        }, 8),
    ])

    assert structured(read)["full_name"] == "nyankoface/demo"
    error = write.json()["result"]
    assert error["isError"] is True
    assert "read_only" in error["content"][0]["text"]
    assert adapter.authorizations == 0
    assert adapter.mutations == []
    audit = AuditStore(settings.audit_state_path).search(AuditFilter(outcome="denied"))
    assert [(item.tool, item.reason_code) for item in audit.items] == [
        ("create_issue", "read_only"),
    ]


@pytest.mark.asyncio
async def test_result_audit_outage_is_visible_on_allowed_read(tmp_path):
    class ResultAuditFails(AuditStore):
        calls = 0
        def append(self, event):
            self.calls += 1
            if self.calls > 1:
                raise AuditUnavailable("audit backend is unavailable")
            return super().append(event)
    settings = make_settings(tmp_path, json_response=True)
    gate = ToolPolicyGate(PolicyStore(settings.policy_state_path), ResultAuditFails(tmp_path / "fail.db"))
    result = structured(await post(create_server(
        settings, FakeAdapter(), policy_gate=gate,
    ).streamable_http_app(), tool_payload(
        "get_repository", {"owner": "nyankoface", "repo": "demo"}, 9,
    )))
    assert result["audit_degraded"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "arguments"), [
    ("create_issue", {"title": "Create me", "body": "body"}),
    ("update_issue", {"number": 7, "state": "closed"}),
    ("comment_issue", {"number": 7, "body": "A comment"}),
])
async def test_each_issue_tool_requires_preview_confirmation_and_idempotency(
    tmp_path, name, arguments,
):
    adapter = FakeAdapter()
    settings = make_settings(tmp_path, json_response=True)
    app = create_server(settings, adapter).streamable_http_app()
    arguments = {"owner": "nyankoface", "repo": "demo", **arguments}
    # Preview first in its own stateless request. Recreate the app for subsequent
    # requests while retaining the shared SQLite safety store.
    preview_app = app
    preview = structured(await post(preview_app, tool_payload(name, arguments, 10)))
    assert preview["status"] == "preview"
    assert len(preview["confirmation"]) >= 32
    assert adapter.mutations == []

    app = create_server(settings, adapter).streamable_http_app()
    execution_response, replay_response = await post_many(app, [tool_payload(name, {
        **arguments,
        "preview": False,
        "confirmation": preview["confirmation"],
        "idempotency_key": f"test-{name}",
    }, 11), tool_payload(name, {
        **arguments,
        "preview": False,
        "confirmation": "already-consumed-is-okay-for-exact-replay",
        "idempotency_key": f"test-{name}",
    }, 12)])
    execution = structured(execution_response)
    assert execution["status"] == "completed"
    assert len(adapter.mutations) == 1

    replay = structured(replay_response)
    assert replay["replayed"] is True
    assert len(adapter.mutations) == 1
    assert adapter.authorizations == 3
    results = AuditStore(settings.audit_state_path).search(AuditFilter(
        event_type="tool_result", tool=name,
    )).items
    assert [item.outcome for item in results] == ["replayed", "allowed", "allowed"]
    assert all(item.operation_id for item in results)
    assert sum(item.operation_id == execution["operation_id"] for item in results) == 2


@pytest.mark.asyncio
async def test_returned_indeterminate_write_is_audited_as_failed(tmp_path):
    class UncertainAdapter(FakeAdapter):
        async def create_issue(self, owner, repo, title, body, token):
            raise TimeoutError("unknown upstream outcome")

    adapter = UncertainAdapter()
    settings = make_settings(tmp_path, json_response=True)
    arguments = {"owner": "nyankoface", "repo": "demo", "title": "uncertain"}
    preview = structured(await post(
        create_server(settings, adapter).streamable_http_app(),
        tool_payload("create_issue", arguments, 20),
    ))
    result = structured(await post(
        create_server(settings, adapter).streamable_http_app(),
        tool_payload("create_issue", {
            **arguments, "preview": False,
            "confirmation": preview["confirmation"],
            "idempotency_key": "indeterminate-write",
        }, 21),
    ))

    assert result["status"] == "indeterminate"
    failed = AuditStore(settings.audit_state_path).search(AuditFilter(
        event_type="tool_result", outcome="failed", tool="create_issue",
    )).items
    assert len(failed) == 1
    assert failed[0].reason_code == "tool_indeterminate"


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "arguments"), [
    ("start_space", {}),
    ("stop_space", {}),
    ("restart_space", {}),
    ("deploy_pages", {"method": "docs"}),
    ("dispatch_pipeline", {"workflow": "publish.yml"}),
    ("cancel_pipeline", {"run_number": 7}),
    ("rollback_pipeline", {"run_number": 7}),
])
async def test_each_control_tool_uses_common_write_safety(
    tmp_path, name, arguments,
):
    adapter = FakeAdapter()
    settings = make_settings(tmp_path, json_response=True)
    base = {"owner": "nyankoface", "repo": "demo", **arguments}
    preview = structured(await post(
        create_server(settings, adapter).streamable_http_app(),
        tool_payload(name, base, 40),
    ))
    assert preview["status"] == "preview"
    assert adapter.mutations == []

    execution = structured(await post(
        create_server(settings, adapter).streamable_http_app(),
        tool_payload(name, {
            **base,
            "preview": False,
            "confirmation": preview["confirmation"],
            "idempotency_key": f"control-{name}",
        }, 41),
    ))
    assert execution["status"] == "completed"
    assert execution["operation_uri"].startswith("nyankoface://operations/")
    assert len(adapter.mutations) == 1

    operation = structured(await post(
        create_server(settings, adapter).streamable_http_app(),
        tool_payload("get_operation", {
            "operation_id": execution["operation_id"],
        }, 42),
    ))
    assert operation["state"] == "completed"
    assert adapter.repository_reads == [("nyankoface", "demo", "caller-pat")]


@pytest.mark.asyncio
async def test_operation_tool_and_resource_recheck_scope_and_repository_access(tmp_path):
    adapter = FakeAdapter()
    settings = make_settings(tmp_path, json_response=True)
    preview = structured(await post(
        create_server(settings, adapter).streamable_http_app(),
        tool_payload("start_space", {"owner": "nyankoface", "repo": "demo"}, 43),
    ))
    execution_response = await post(
        create_server(settings, adapter).streamable_http_app(),
        tool_payload("start_space", {
            "owner": "nyankoface", "repo": "demo", "preview": False,
            "confirmation": preview["confirmation"], "idempotency_key": "operation-read",
        }, 44),
    )
    execution = structured(execution_response)
    operation_id = execution["operation_id"]

    restricted = create_server(
        make_settings(tmp_path, json_response=True, scopes=["spaces:run"]),
        adapter,
    ).streamable_http_app()
    missing_scope = await post(
        restricted, tool_payload("get_operation", {"operation_id": operation_id}, 45),
    )
    assert "repos:read" in missing_scope.json()["result"]["content"][0]["text"]

    adapter.repository_access = False
    denied_tool = await post(
        create_server(make_settings(tmp_path, json_response=True), adapter).streamable_http_app(),
        tool_payload("get_operation", {"operation_id": operation_id}, 46),
    )
    denied_resource = await post(create_server(
        make_settings(tmp_path, json_response=True), adapter,
    ).streamable_http_app(), {
        "jsonrpc": "2.0", "id": 47, "method": "resources/read",
        "params": {"uri": f"nyankoface://operations/{operation_id}"},
    })
    assert "not found or is not authorized" in denied_tool.text
    assert "not found or is not authorized" in denied_resource.text


@pytest.mark.asyncio
async def test_control_disconnect_is_indeterminate_and_never_redispatched(tmp_path):
    adapter = FakeAdapter()
    settings = make_settings(tmp_path, json_response=True)

    async def disconnected(action, owner, repo, token):
        adapter.mutations.append((action, owner, repo, token))
        raise ToolError("connection closed after dispatch")

    adapter.control_space = disconnected
    arguments = {"owner": "nyankoface", "repo": "demo"}
    preview = structured(await post(
        create_server(settings, adapter).streamable_http_app(),
        tool_payload("start_space", arguments, 50),
    ))
    execution = structured(await post(
        create_server(settings, adapter).streamable_http_app(),
        tool_payload("start_space", {
            **arguments, "preview": False,
            "confirmation": preview["confirmation"],
            "idempotency_key": "disconnect-start",
        }, 51),
    ))
    replay = structured(await post(
        create_server(settings, adapter).streamable_http_app(),
        tool_payload("start_space", {
            **arguments, "preview": False,
            "confirmation": "unused-for-replay",
            "idempotency_key": "disconnect-start",
        }, 52),
    ))
    assert execution["status"] == "indeterminate"
    assert execution["error"]["retry_safe"] is False
    assert replay["replayed"] is True
    assert len(adapter.mutations) == 1

    reconcile_preview = structured(await post(
        create_server(settings, adapter).streamable_http_app(),
        tool_payload("reconcile_operation", {
            "operation_id": execution["operation_id"],
            "resolution": "not_applied",
        }, 53),
    ))
    reconciliation = structured(await post(
        create_server(settings, adapter).streamable_http_app(),
        tool_payload("reconcile_operation", {
            "operation_id": execution["operation_id"],
            "resolution": "not_applied", "preview": False,
            "confirmation": reconcile_preview["confirmation"],
            "idempotency_key": "reconcile-disconnect",
        }, 54),
    ))
    assert reconciliation["status"] == "completed"
    assert reconciliation["result"]["state"] == "reconciled"
    replay = structured(await post(
        create_server(settings, adapter).streamable_http_app(),
        tool_payload("reconcile_operation", {
            "operation_id": execution["operation_id"], "resolution": "not_applied",
            "dry_run": False, "confirmation": reconcile_preview["confirmation"],
            "idempotency_key": "reconcile-disconnect",
        }, 55),
    ))
    assert replay["replayed"] is True

    operation = structured(await post(
        create_server(settings, adapter).streamable_http_app(),
        tool_payload("get_operation", {"operation_id": execution["operation_id"]}, 56),
    ))
    assert operation["state"] == "reconciled"
    assert operation["result"]["reconciliation"]["resolution"] == "not_applied"


@pytest.mark.asyncio
async def test_issue_write_scope_is_checked_before_adapter_or_mutation(tmp_path):
    adapter = FakeAdapter()
    settings = make_settings(tmp_path, json_response=True, scopes=["issues:read"])
    app = create_server(settings, adapter).streamable_http_app()
    response = await post(app, tool_payload(
        "create_issue", {"owner": "nyankoface", "repo": "demo", "title": "No"}, 20,
    ))
    result = response.json()["result"]
    assert result["isError"] is True
    assert "issues:write" in result["content"][0]["text"]
    assert adapter.authorizations == 0
    assert adapter.mutations == []


@pytest.mark.asyncio
async def test_issue_write_requires_repository_read_scope_too(tmp_path):
    adapter = FakeAdapter()
    settings = make_settings(tmp_path, json_response=True, scopes=["issues:write"])
    app = create_server(settings, adapter).streamable_http_app()
    response = await post(app, tool_payload(
        "create_issue", {"owner": "nyankoface", "repo": "demo", "title": "No"}, 22,
    ))
    result = response.json()["result"]
    assert result["isError"] is True
    assert "repos:read" in result["content"][0]["text"]
    assert adapter.authorizations == 0
    assert adapter.mutations == []


@pytest.mark.asyncio
async def test_issue_write_cannot_escape_token_repository_constraints(tmp_path):
    adapter = FakeAdapter()
    app = create_server(make_settings(tmp_path, json_response=True), adapter).streamable_http_app()
    result = (await post(app, tool_payload(
        "create_issue", {"owner": "nyankoface", "repo": "other", "title": "No"}, 23,
    ))).json()["result"]
    assert result["isError"] is True
    assert "not found or is not authorized" in result["content"][0]["text"]
    assert adapter.authorizations == 0
    assert adapter.mutations == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "kind", "required_scope"),
    [
        ("set_space_variable", "variable", "variables:write"),
        ("set_space_secret", "secret", "secrets:write"),
    ],
)
async def test_environment_set_uses_safe_preview_confirmation_and_replay(
    tmp_path, caplog, tool, kind, required_scope,
):
    assert required_scope in {"variables:write", "secrets:write"}
    adapter = FakeAdapter()
    settings = make_settings(tmp_path, json_response=True)
    marker = "ghp_not-a-real-token=structured:{secret:true}"
    arguments = {
        "owner": "nyankoface", "repo": "demo", "name": "SERVICE_TOKEN",
        "value": marker, "scope": "both",
    }
    preview = structured(await post(
        create_server(settings, adapter).streamable_http_app(),
        tool_payload(tool, arguments, 120),
    ))
    assert preview["status"] == "preview"
    assert preview["change"] == {
        "action": "set", "name": "SERVICE_TOKEN", "kind": kind, "scope": "both",
    }
    assert marker not in json.dumps(preview)

    execution = structured(await post(
        create_server(settings, adapter).streamable_http_app(),
        tool_payload(tool, {
            **arguments, "preview": False, "confirmation": preview["confirmation"],
            "idempotency_key": f"set-{kind}-once",
        }, 121),
    ))
    assert execution["status"] == "completed"
    assert execution["result"]["item"]["kind"] == kind
    assert marker not in json.dumps(execution)

    replay = structured(await post(
        create_server(settings, adapter).streamable_http_app(),
        tool_payload(tool, {
            **arguments, "preview": False, "confirmation": "not-reused",
            "idempotency_key": f"set-{kind}-once",
        }, 122),
    ))
    assert replay["replayed"] is True
    assert len(adapter.mutations) == 1
    operation = await post(
        create_server(settings, adapter).streamable_http_app(),
        {"jsonrpc": "2.0", "id": 123, "method": "resources/read", "params": {
            "uri": execution["operation_uri"],
        }},
    )
    surfaces = [
        json.dumps(preview), json.dumps(execution), json.dumps(replay),
        operation.text, caplog.text,
        settings.write_state_path.read_bytes().decode("latin1"),
        settings.audit_state_path.read_bytes().decode("latin1"),
    ]
    assert all(marker not in surface for surface in surfaces)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "scope"),
    [
        ("set_space_variable", "variables:write"),
        ("delete_space_variable", "variables:write"),
        ("set_space_secret", "secrets:write"),
        ("delete_space_secret", "secrets:write"),
        ("apply_space_environment", "spaces:run"),
    ],
)
async def test_environment_tools_require_dedicated_scope_before_authorization(
    tmp_path, tool, scope,
):
    adapter = FakeAdapter()
    settings = make_settings(tmp_path, json_response=True, scopes=["repos:read"])
    arguments = {"owner": "nyankoface", "repo": "demo", "name": "TOKEN"}
    if tool.startswith("set_"):
        arguments["value"] = "do-not-leak"
    if tool == "apply_space_environment":
        arguments.pop("name")
    response = await post(
        create_server(settings, adapter).streamable_http_app(),
        tool_payload(tool, arguments, 123),
    )
    result = response.json()["result"]
    assert result["isError"] is True
    assert scope in result["content"][0]["text"]
    assert adapter.authorizations == 0
    assert adapter.mutations == []


@pytest.mark.asyncio
async def test_environment_write_cannot_escape_repository_constraints(tmp_path):
    adapter = FakeAdapter()
    settings = make_settings(tmp_path, json_response=True)
    response = await post(
        create_server(settings, adapter).streamable_http_app(),
        tool_payload("set_space_secret", {
            "owner": "nyankoface", "repo": "other", "name": "TOKEN",
            "value": "private-secret",
        }, 124),
    )
    result = response.json()["result"]
    assert result["isError"] is True
    assert "not found or is not authorized" in result["content"][0]["text"]
    assert "private-secret" not in response.text
    assert adapter.authorizations == 0


@pytest.mark.asyncio
async def test_environment_upstream_and_validation_errors_never_echo_plaintext(tmp_path):
    class RejectingAdapter(FakeAdapter):
        async def set_space_environment(self, *_args):
            raise ToolError("upstream reflected value=never-print-this")

    settings = make_settings(tmp_path, json_response=True)
    for value in ("never-print-this", "A=B", '{"token":"never-print-this"}'):
        response = await post(
            create_server(settings, RejectingAdapter()).streamable_http_app(),
            tool_payload("set_space_secret", {
                "owner": "nyankoface", "repo": "demo", "name": "TOKEN",
                "value": value, "preview": False, "confirmation": "invalid",
                "idempotency_key": f"reject-{hashlib.sha256(value.encode()).hexdigest()}",
            }, 125),
        )
        assert response.json()["result"]["isError"] is True
        assert value not in response.text
        assert "never-print-this" not in response.text


@pytest.mark.asyncio
async def test_invalid_repository_input_never_enters_audit_metadata(tmp_path):
    adapter = FakeAdapter()
    settings = make_settings(tmp_path, json_response=True)
    app = create_server(settings, adapter).streamable_http_app()
    marker = "Bearer abcdefghijklmnopqrstuv"
    response = await post(app, tool_payload(
        "create_issue", {"owner": marker, "repo": "demo", "title": "No"}, 21,
    ))
    result = response.json()["result"]
    assert result["isError"] is True
    assert "Invalid repository identity" in result["content"][0]["text"]
    assert marker.encode() not in settings.write_state_path.read_bytes()
@pytest.mark.asyncio
async def test_repository_listing_cannot_escape_token_constraints(tmp_path):
    class ConstrainedAdapter(FakeAdapter):
        async def list_repositories(self, query, page, limit, token):
            raise AssertionError("constrained token used the global repository search")

    settings = make_settings(tmp_path, json_response=True)
    registry = json.loads(settings.token_file.read_text(encoding="utf-8"))
    registry["subjects"][0]["subject_type"] = "human"
    registry["tokens"][0]["subject_type"] = "human"
    registry["tokens"][0]["repositories"] = []
    settings.token_file.write_text(json.dumps(registry), encoding="utf-8")
    app = create_server(settings, ConstrainedAdapter()).streamable_http_app()
    response = await post(app, {
        "jsonrpc": "2.0", "id": 41, "method": "tools/call",
        "params": {"name": "list_repositories", "arguments": {}},
    })
    result = response.json()["result"]
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["totalCount"] == 1
    assert [item["full_name"] for item in payload["items"]] == ["NyankoFace/Demo"]


@pytest.mark.asyncio
async def test_constrained_repository_listing_bounds_fetches_and_skips_missing(tmp_path):
    settings = make_settings(tmp_path, json_response=True)
    registry = json.loads(settings.token_file.read_text(encoding="utf-8"))
    registry["subjects"][0]["repository_permissions"] = {
        "nyankoface/alpha": "read",
        "nyankoface/missing": "read",
        "nyankoface/zulu": "read",
    }
    registry["tokens"][0]["repositories"] = [
        "nyankoface/alpha", "nyankoface/missing", "nyankoface/zulu",
    ]
    settings.token_file.write_text(json.dumps(registry), encoding="utf-8")

    class BoundedAdapter(FakeAdapter):
        def __init__(self):
            self.fetched = []

        async def get_repository(self, owner, repo, token):
            self.fetched.append(f"{owner}/{repo}")
            if repo == "missing":
                raise ToolError(json.dumps({
                    "error": {
                        "code": "not_found_or_unauthorized",
                        "message": "Resource was not found or is not authorized",
                        "retryable": False,
                        "action": "Verify the repository and caller access",
                    }
                }))
            return {"full_name": f"{owner}/{repo}", "private": False}

    adapter = BoundedAdapter()
    app = create_server(settings, adapter).streamable_http_app()
    response = await post(app, {
        "jsonrpc": "2.0", "id": 42, "method": "tools/call",
        "params": {"name": "list_repositories", "arguments": {"page": 2, "limit": 1}},
    })
    result = response.json()["result"]
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["totalCount"] == 3
    assert payload["totalPages"] == 3
    assert payload["items"] == []
    assert adapter.fetched == ["nyankoface/missing"]

    next_page_app = create_server(settings, adapter).streamable_http_app()
    response = await post(next_page_app, {
        "jsonrpc": "2.0", "id": 43, "method": "tools/call",
        "params": {"name": "list_repositories", "arguments": {"page": 3, "limit": 1}},
    })
    payload = json.loads(response.json()["result"]["content"][0]["text"])
    assert [item["full_name"] for item in payload["items"]] == ["nyankoface/zulu"]
    assert adapter.fetched == ["nyankoface/missing", "nyankoface/zulu"]


@pytest.mark.asyncio
async def test_constrained_repository_listing_does_not_hide_other_operational_errors(tmp_path):
    class UnavailableAdapter(FakeAdapter):
        async def get_repository(self, owner, repo, token):
            raise ToolError(json.dumps({
                "error": {
                    "code": "upstream_unavailable",
                    "message": "Forgejo is temporarily unavailable",
                    "retryable": True,
                    "action": "Retry after checking Forgejo health",
                }
            }))

    app = create_server(
        make_settings(tmp_path, json_response=True),
        UnavailableAdapter(),
    ).streamable_http_app()
    response = await post(app, {
        "jsonrpc": "2.0", "id": 44, "method": "tools/call",
        "params": {"name": "list_repositories", "arguments": {}},
    })

    result = response.json()["result"]
    assert result["isError"] is True
    assert "upstream_unavailable" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_tree_resource_and_tool_share_repository_scope(tmp_path):
    settings = make_settings(tmp_path, json_response=True, scopes=["catalog:read"])

    tool_app = create_server(settings, FakeAdapter()).streamable_http_app()
    tool_response = await post(tool_app, {
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {
            "name": "get_tree",
            "arguments": {"owner": "nyankoface", "repo": "demo", "ref": "main"},
        },
    })
    assert tool_response.json()["result"]["isError"] is True
    assert "repos:read" in tool_response.json()["result"]["content"][0]["text"]

    resource_app = create_server(settings, FakeAdapter()).streamable_http_app()
    resource_response = await post(resource_app, {
        "jsonrpc": "2.0", "id": 6, "method": "resources/read",
        "params": {"uri": f"nyankoface://repos/nyankoface/demo/tree/{encode_resource_ref('main')}"},
    })
    assert "repos:read" in resource_response.text


@pytest.mark.asyncio
async def test_tree_resource_decodes_slash_containing_ref(tmp_path):
    app = create_server(make_settings(tmp_path, json_response=True), FakeAdapter()).streamable_http_app()
    ref = "refs/heads/release"
    response = await post(app, {
        "jsonrpc": "2.0", "id": 7, "method": "resources/read",
        "params": {"uri": f"nyankoface://repos/nyankoface/demo/tree/{encode_resource_ref(ref)}"},
    })
    contents = response.json()["result"]["contents"]
    assert json.loads(contents[0]["text"])["ref"] == ref


@pytest.mark.asyncio
async def test_reconcile_operation_applies_repository_read_only_policy(tmp_path):
    settings = make_settings(tmp_path, json_response=True)
    safety = WriteSafetyStore(settings.write_state_path)
    item = WriteIdentity(
        "service:test", "deploy_pages", "POST", "/pages/nyankoface/demo",
    )
    payload_hash = fingerprint({"method": "docs"})
    confirmation, _ = safety.issue_confirmation(item, payload_hash)
    claim = safety.claim(item, payload_hash, confirmation, "unknown-pages")
    safety.complete(claim.namespace, {
        "status": "indeterminate",
        "error": {"code": "upstream_outcome_unknown", "retry_safe": False},
    })
    PolicyStore(settings.policy_state_path).set_read_only(
        "repository", "nyankoface/demo", True,
    )

    response = await post(create_server(
        settings, FakeAdapter(),
    ).streamable_http_app(), {
        "jsonrpc": "2.0", "id": 45, "method": "tools/call",
        "params": {"name": "reconcile_operation", "arguments": {
            "operation_id": claim.operation_id, "resolution": "not_applied",
        }},
    })
    result = response.json()["result"]
    assert result["isError"] is True
    assert "read_only" in result["content"][0]["text"]


@pytest.mark.parametrize("ref", ["main", "feature/demo", "refs/heads/release", "日本語/検証"])
def test_resource_ref_token_round_trips_as_one_safe_segment(ref):
    token = encode_resource_ref(ref)
    assert "/" not in token and "%" not in token and "=" not in token
    assert decode_resource_ref(token) == ref


@pytest.mark.parametrize("token", ["", "refs%2Fheads%2Fmain", "not/slash-safe", "a=", "_"])
def test_resource_ref_token_rejects_noncanonical_or_invalid_values(token):
    with pytest.raises(ValueError, match="Invalid resource ref token"):
        decode_resource_ref(token)
