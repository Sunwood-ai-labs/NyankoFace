import base64
import json
import re
import tempfile
import tomllib
from pathlib import Path

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError

import nyankoface_mcp.client as client_module

from nyankoface_mcp.auth import NyankoFaceTokenVerifier
from nyankoface_mcp.client import (
    CATALOG_KINDS,
    SECRET_PATHS,
    NyankoFaceAdapter,
    WriteResponseError,
    redact,
    validate_content_path,
    validate_ref,
    validate_repo_identity,
)
from nyankoface_mcp.config import Settings
from nyankoface_mcp.lifecycle import AdminContext, TokenLifecycleStore


ROOT = Path(__file__).resolve().parents[2]


def test_write_tokens_share_stable_subject_during_rotation_window(tmp_path):
    token_file = tmp_path / "registry.json"
    store = TokenLifecycleStore(token_file)
    admin = AdminContext("user:admin", True, 1_000)
    store.create_service_account(
        admin,
        subject_id="service:writer",
        forgejo_user_id=42,
        forgejo_token_file="/run/secrets/writer-pat",
        allowed_scopes=["repos:read", "issues:write"],
        repository_permissions={"nyankoface/demo": "write"},
        now=1_000,
    )
    for client_id in ("old-client", "new-client"):
        store.issue(
            admin,
            subject_id="service:writer",
            client_id=client_id,
            scopes=["repos:read", "issues:write"],
            repositories=["nyankoface/demo"],
            ttl_seconds=600,
            now=1_000,
        )

    async def resolve_identity(_token):
        return 42

    records = NyankoFaceTokenVerifier(token_file, resolve_identity).records()

    assert len(records) == 2
    assert {record.subject_id for record in records} == {"service:writer"}


def test_token_without_explicit_lifecycle_subject_fails_closed(tmp_path):
    token_file = tmp_path / "registry.json"
    token_file.write_text(json.dumps({"version": 2, "subjects": [], "tokens": [{
        "token_id": "00000000-0000-4000-8000-000000000001",
        "token_sha256": "e" * 64,
        "client_id": "read-client",
        "scopes": ["catalog:read"],
        "expires_at": 4_102_444_800,
    }]}), encoding="utf-8")

    async def resolve_identity(_token):
        return 42

    assert NyankoFaceTokenVerifier(token_file, resolve_identity).records() == []


def test_redact_removes_nested_secret_values():
    payload = {
        "name": "demo Bearer abcdefghijklmnopqrstu",
        "token": "leak",
        "auth": "YWxpY2U6aHVudGVyMg==",
        "authorization": "Basic dXNlcjpwYXNz",
        "nested": [{"api_key": "leak2", "ok": True}],
    }
    assert redact(payload) == {
        "name": "demo [REDACTED]",
        "token": "[REDACTED]",
        "auth": "[REDACTED]",
        "authorization": "[REDACTED]",
        "nested": [{"api_key": "[REDACTED]", "ok": True}],
    }


@pytest.mark.parametrize("value", [
    "npm_abcdefghijklmnopqrstuvwxyz0123456789",
    "AGE-SECRET-KEY-1QQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQ",
    "AKIAIOSFODNN7EXAMPLE",
    "xo" + "xb-123456789012-123456789012-abcdefghijklmnopqrstuvwx",
    "OPENAI_API_KEY=super-sensitive-value",
    "client-secret: 'quoted-sensitive-value'",
    '{"password": "hunter2"}',
    '{"Authorization": "Basic dXNlcjpwYXNz"}',
    "'api_token' = 'toml-sensitive-value'",
    '"database.password": "nested-sensitive-value"',
    "Authorization: Basic dXNlcjpwYXNz",
    "api key: unquoted-yaml-sensitive-value",
    "-----BEGIN PRIVATE KEY-----\nc2VjcmV0\n-----END PRIVATE KEY-----",
    "-----BEGIN PGP PRIVATE KEY BLOCK-----\nc2VjcmV0\n-----END PGP PRIVATE KEY BLOCK-----",
])
def test_redact_removes_secret_values_embedded_in_text(value):
    result = redact(f"before {value} after")
    assert value not in result
    assert "[REDACTED]" in result


def test_redact_preserves_json_string_shape_for_quoted_secret_values():
    result = redact('{"password": "hunter2", "safe": true}')
    assert json.loads(result) == {"password": "[REDACTED]", "safe": True}


@pytest.mark.parametrize("value", [
    "postgresql://alice:hunter2@db/app",
    "redis://:s%40cret@redis/0",
    "https://oauth2token1234567890@example.com/repo.git",
    "https://oauth2%40token@example.com/repo.git",
])
def test_redact_connection_url_passwords_preserves_destination(value):
    result = redact(f"DATABASE_URL={value}")
    assert value.split("@", 1)[0] not in result
    assert result.endswith("[REDACTED]@" + value.split("@", 1)[1])
    assert redact("https://example.com/repo.git") == "https://example.com/repo.git"


def test_redact_sk_token_requires_prefix_and_boundaries():
    assert redact("sk-abcdefghijklmnopqrst") == "[REDACTED]"
    for value in ("sklearn_preprocessing", "skills_documentation", "skips_invalid_newer_artifacts_only_after_success"):
        assert redact(value) == value


def test_redact_replaces_complete_json_secret_structures():
    result = redact(
        '{"token":["one","two"],"credentials":{"user":"alice","password":"hunter2"},'
        '"safe":[1,2]}'
    )
    assert json.loads(result) == {
        "token": "[REDACTED]",
        "credentials": "[REDACTED]",
        "safe": [1, 2],
    }


def test_redact_private_jwk_parameters_preserves_public_material():
    result = redact({"kty": "RSA", "n": "public-n", "e": "AQAB", "d": "private",
                     "p": "prime", "oth": [{"d": "nested"}]})
    assert result == {"kty": "RSA", "n": "public-n", "e": "AQAB", "d": "[REDACTED]",
                      "p": "[REDACTED]", "oth": "[REDACTED]"}
    assert redact({"kty": "oct", "k": "symmetric"})["k"] == "[REDACTED]"


def test_redact_replaces_yaml_secret_blocks_without_consuming_siblings():
    source = (
        "safe: visible\n"
        "password: |-\n"
        "  hunter2\n"
        "  second-line\n"
        "nested:\n"
        "  credentials:\n"
        "    token: nested-value\n"
        "  keep: sibling-visible\n"
        "after: still-visible\n"
    )
    result = redact(source)
    assert "hunter2" not in result
    assert "second-line" not in result
    assert "nested-value" not in result
    assert "password: |-\n  [REDACTED]\n" in result
    assert "  credentials: [REDACTED]\n" in result
    assert "  keep: sibling-visible\n" in result
    assert "after: still-visible\n" in result


def test_redact_consumes_indentationless_yaml_secret_sequences():
    source = "password:\n- decoy\n- real-secret\nsafe: visible\n"
    result = redact(source)
    assert result == "password: [REDACTED]\nsafe: visible\n"


def test_redact_consumes_comments_inside_indentationless_secret_sequences():
    source = "password:\n- decoy\n# retained YAML sequence\n- real-secret\nsafe: visible\n"
    result = redact(source)
    assert "real-secret" not in result
    assert result == "password: [REDACTED]\nsafe: visible\n"


def test_redact_consumes_multiline_plain_yaml_secret_scalars():
    source = (
        "password: decoy\n"
        "  real-secret\n"
        "\n"
        "# a YAML comment does not terminate the continued scalar\n"
        "  final-secret-fragment\n"
        "safe: visible\n"
    )
    result = redact(source)
    assert "decoy" not in result
    assert "real-secret" not in result
    assert "final-secret-fragment" not in result
    assert result == "password: [REDACTED]\nsafe: visible\n"


def test_redact_stops_sequence_mapping_secret_at_same_level_sibling():
    source = (
        "- password:\n"
        "  - decoy\n"
        "  - real-secret\n"
        "  safe: visible\n"
        "- name: next-item\n"
    )
    result = redact(source)
    assert "decoy" not in result
    assert "real-secret" not in result
    assert result == (
        "- password: [REDACTED]\n"
        "  safe: visible\n"
        "- name: next-item\n"
    )


def test_redact_honors_doubled_quotes_in_yaml_secret_scalars():
    source = "password: 'x''real-secret'\nsafe: visible\n"
    result = redact(source)
    assert "real-secret" not in result
    assert result == "password: '[REDACTED]'\nsafe: visible\n"


def test_redact_matches_only_complete_secret_key_components():
    source = {
        "tokenizer_class": "PreTrainedTokenizerFast",
        "clean_up_tokenization_spaces": True,
        "monkey": "banana",
        "access_token": "leak",
    }
    assert redact(source) == {
        "tokenizer_class": "PreTrainedTokenizerFast",
        "clean_up_tokenization_spaces": True,
        "monkey": "banana",
        "access_token": "[REDACTED]",
    }
    text = (
        "tokenizer_class: PreTrainedTokenizerFast\n"
        "clean_up_tokenization_spaces: true\n"
        "monkey: banana\n"
        "access_token: leak\n"
    )
    assert redact(text) == (
        "tokenizer_class: PreTrainedTokenizerFast\n"
        "clean_up_tokenization_spaces: true\n"
        "monkey: banana\n"
        "access_token: [REDACTED]\n"
    )


def test_redact_recognizes_camel_case_secret_key_components():
    secret_keys = (
        "accessToken", "refreshToken", "clientSecret", "databasePassword",
        "clientApiKey", "passwd", "dbPass", "sshPassphrase",
        "oneTimePasscode", "pwd", "dbPwd", "basicAuth", "registryAuth",
        "FORGEJO__database__PASSWD",
    )
    safe_values = {
        "tokenizerClass": "PreTrainedTokenizerFast", "monkey": "banana", "compass": "north",
        "passwordless": True, "passage": "safe prose", "pwdPolicy": "minimum-length",
        "author": "alice", "oauthProvider": "oidc",
        "noAuth": True, "supportsBasicAuth": True, "basicAuthEnabled": True,
    }
    source = {**dict.fromkeys(secret_keys, "leak"), **safe_values}
    expected = {**dict.fromkeys(secret_keys, "[REDACTED]"), **safe_values}
    assert redact(source) == expected


def test_redact_password_aliases_in_json_yaml_and_toml():
    json_result = redact('{"pwd":"json-secret","pwdPolicy":"safe"}')
    assert json.loads(json_result) == {"pwd": "[REDACTED]", "pwdPolicy": "safe"}

    yaml_result = redact("dbPwd: yaml-secret\npasswordless: true\n")
    assert yaml_result == "dbPwd: [REDACTED]\npasswordless: true\n"

    toml_result = redact("passcode = 'toml-secret'\ncompass = 'north'\n")
    assert tomllib.loads(toml_result) == {
        "passcode": "[REDACTED]",
        "compass": "north",
    }


def test_redact_replaces_multiline_toml_secret_structures_atomically():
    source = (
        'token = [\n  "one",\n  { nested = "two" },\n]\n'
        'password = """first-line\nsecond-line"""\n'
        'safe = "visible"\n'
    )
    result = redact(source)
    parsed = tomllib.loads(result)
    assert parsed == {
        "token": "[REDACTED]",
        "password": "[REDACTED]",
        "safe": "visible",
    }
    assert "one" not in result
    assert "two" not in result
    assert "first-line" not in result
    assert "second-line" not in result


@pytest.mark.parametrize("size", [10 * 1024, 255 * 1024])
def test_redact_scans_unterminated_structured_secret_remainder_once(
    monkeypatch,
    size,
):
    calls = 0
    original = client_module._structured_value_end

    def counted(value, start):
        nonlocal calls
        calls += 1
        return original(value, start)

    monkeypatch.setattr(client_module, "_structured_value_end", counted)
    prefix = "password: [\n"
    repeated = "password: [real-secret\n"
    source = prefix + (repeated * ((size // len(repeated)) + 1))
    source = source[:size]
    result = redact(source)
    assert len(source) == size
    assert calls == 1
    assert result == 'password: "[REDACTED]"'


@pytest.mark.parametrize("owner,repo", [
    (".", "repo"),
    ("..", "repo"),
    ("alice", "."),
    ("alice", ".."),
])
def test_repository_identity_rejects_dot_segments(owner, repo):
    with pytest.raises(ToolError, match="Invalid repository identity"):
        validate_repo_identity(owner, repo)


@pytest.mark.asyncio
async def test_dot_segment_repository_is_denied_before_upstream_request():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("dot-segment repository must not reach upstream")

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    with pytest.raises(ToolError, match="Invalid repository identity"):
        await adapter.get_repository("..", "users", "user-pat")


@pytest.mark.asyncio
async def test_private_repository_requires_caller_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"name": "private", "private": True})

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    with pytest.raises(ToolError, match="not found or is not authorized"):
        await adapter.get_repository("alice", "private", None)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    ".env.production",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".pgpass",
    ".docker/config.json",
    ".dockercfg",
    ".aws/credentials",
    ".config/gcloud/application_default_credentials.json",
    ".kube/config",
    ".ssh/config",
    "composer/auth.json",
    "server.key",
    "client.p12",
    "certificate.pfx",
    "signing.pkcs12",
    "signing.pk8",
    "putty.ppk",
    "release.jks",
    "application.keystore",
    "vault.kdbx",
])
async def test_secret_like_file_is_denied_before_upstream_request(path):
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("secret-like path must not reach upstream")

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    with pytest.raises(ToolError, match="not available"):
        await adapter.get_file("alice", "repo", path, "main", "user-pat")


@pytest.mark.parametrize("path", [
    "server.crt",
    "certificate.cer",
    "certificate.pem",
    "chain.p7b",
    "id_ed25519.pub",
])
def test_public_certificate_extensions_are_not_blanket_denied(path):
    assert SECRET_PATHS.search(path) is None


def test_plaintext_gateway_rejects_mcp_bearer_endpoint():
    gateway = (ROOT / "gateway" / "nginx.conf").read_text(
        encoding="utf-8",
    )
    http_server, tls_server = gateway.split("server {", 2)[1:]
    assert "listen 80" in http_server
    plaintext_match = re.search(r"location ~ (?P<pattern>\S+) \{\s+return 426;", http_server)
    assert plaintext_match
    matcher = re.compile(plaintext_match.group("pattern"))
    paths = ("/mcp", "/mcp/", "/mcp/tools", "/mcps")
    assert [bool(matcher.match(path)) for path in paths] == [True, True, True, False]
    assert "proxy_pass http://$mcp_upstream" not in http_server
    assert "listen 443 ssl" in tls_server
    assert "location = /mcp" in tls_server
    assert "client_max_body_size 1m" in tls_server
    assert "proxy_pass http://nyankoface_mcp_backend" in tls_server
    assert "proxy_next_upstream off" in tls_server


def test_bearer_generation_uses_csprng():
    lifecycle = (ROOT / "nyankoface-mcp" / "nyankoface_mcp" / "lifecycle.py").read_text(encoding="utf-8")
    assert 'secrets.token_urlsafe(32)' in lifecycle
    assert "random." not in lifecycle


def test_issue_write_state_is_persisted_in_a_non_root_writable_volume():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "nyankoface-mcp" / "Dockerfile").read_text(encoding="utf-8")
    assert "nyankoface-mcp-state:/data" in compose
    assert "NYANKOFACE_MCP_WRITE_STATE_PATH: /data/write-safety.sqlite3" in compose
    assert "install -d -o nyankoface -g nyankoface /data" in dockerfile


def test_docs_distinguish_local_stdio_from_uncertified_remote_connector():
    readme = (ROOT / "nyankoface-mcp" / "README.md").read_text(encoding="utf-8")
    english = (ROOT / "docs" / "guide" / "mcp-server.md").read_text(encoding="utf-8")
    japanese = (ROOT / "docs" / "ja" / "guide" / "mcp-server.md").read_text(encoding="utf-8")
    for document in (readme, english, japanese):
        assert '"command": "nyankoface-mcp-stdio"' in document
        assert "live" in document.lower() or "実機" in document
    assert "remote static-Bearer endpoint does not claim" in english
    assert "remote static Bearer endpointはClaude Desktop connector互換を保証しません" in japanese
    assert "#116" in english and "#116" in japanese


@pytest.mark.asyncio
async def test_file_content_is_bounded_utf8_and_response_is_redacted():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/repos/alice/repo"):
            return httpx.Response(200, json={"name": "repo", "private": False, "access_token": "never"})
        return httpx.Response(200, json={
            "type": "file",
            "size": 40,
            "sha": "abc",
            "content": base64.b64encode("use Bearer abcdefghijklmnopqrstuv now".encode()).decode(),
        })

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    repository = await adapter.get_repository("alice", "repo", None)
    assert repository["access_token"] == "[REDACTED]"
    content = await adapter.get_file("alice", "repo", "README.md", "main", None)
    assert content["text"] == "use [REDACTED] now"


@pytest.mark.asyncio
async def test_file_stream_aborts_when_encoded_response_metadata_exceeds_cap():
    class Tracked(httpx.AsyncByteStream):
        closed = False
        async def __aiter__(self):
            yield b'{"padding":"'
            yield b"x" * 17_000
        async def aclose(self):
            self.closed = True
    stream = Tracked()
    def handler(request):
        if "/contents/" in request.url.path:
            return httpx.Response(200, stream=stream)
        return httpx.Response(200, json={"name": "repo", "private": False})
    adapter = NyankoFaceAdapter(Settings(max_file_bytes=8), httpx.MockTransport(handler))
    with pytest.raises(ToolError, match="bounded"):
        await adapter.get_file("alice", "repo", "README.md", "main", None)
    assert stream.closed


@pytest.mark.asyncio
async def test_file_rejects_encoded_content_larger_than_declared_size():
    def handler(request):
        if "/contents/" not in request.url.path:
            return httpx.Response(200, json={"name": "repo", "private": False})
        return httpx.Response(200, json={"type": "file", "size": 1, "sha": "x",
                                         "content": base64.b64encode(b"0123456789").decode()})
    adapter = NyankoFaceAdapter(Settings(max_file_bytes=8), httpx.MockTransport(handler))
    with pytest.raises(ToolError, match="bounded"):
        await adapter.get_file("alice", "repo", "README.md", "main", None)


@pytest.mark.asyncio
async def test_pipeline_status_uses_caller_bearer_route():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "forgejo":
            assert request.headers["authorization"] == "token caller-pat"
            return httpx.Response(200, json={"name": "repo", "private": True})
        assert request.url.path == "/api/v1/pipelines/alice/repo"
        assert request.headers["authorization"] == "Bearer caller-pat"
        return httpx.Response(200, json={"runs": [], "secret": "must-not-leak"})

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    result = await adapter.get_status("pipelines", "alice", "repo", "caller-pat")
    assert len(requests) == 2
    assert result == {"runs": [], "secret": "[REDACTED]"}


@pytest.mark.asyncio
async def test_control_writes_use_runner_bearer_and_strict_result_projection():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer caller-pat"
        return httpx.Response(200, json={
            "status": "queued", "workflow": "publish.yml",
            "synced_settings": [{"name": "SECRET_NAME"}],
            "logs": ["token=must-not-leak"],
        })

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    result = await adapter.dispatch_pipeline(
        "alice", "repo", "publish.yml", "main", "staging", {}, "caller-pat",
    )
    assert requests[0].url.path == "/api/v1/pipelines/alice/repo/dispatch"
    assert requests[0].read() == (
        b'{"workflow":"publish.yml","ref":"main","environment":"staging","inputs":{}}'
    )
    assert result == {"status": "queued", "workflow": "publish.yml"}


@pytest.mark.asyncio
async def test_invalid_pipeline_action_returns_actionable_definite_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": {
            "code": "rollback_source_invalid",
            "message": "Rollback requires a successful production pipeline run.",
        }})

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    with pytest.raises(WriteResponseError) as captured:
        await adapter.pipeline_action("rollback", "alice", "repo", 7, "caller-pat")
    assert captured.value.code == "rollback_source_invalid"
    assert captured.value.retry_safe is True
    assert "successful production" in str(captured.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        ({"code": "forgejo_unavailable", "message": "Try again", "retry_safe": True}, True),
        ({"code": "unknown_failure", "message": "Outcome unknown"}, False),
    ],
)
async def test_control_5xx_uses_explicit_runner_retry_classification(detail, expected):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": detail})

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    with pytest.raises(WriteResponseError) as captured:
        await adapter.control_space("start", "alice", "repo", "caller-pat")
    assert captured.value.retry_safe is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b""),
        httpx.Response(200, content=b"{truncated"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"status": 7}),
    ],
)
async def test_control_success_rejects_malformed_response_as_non_retryable(response):
    adapter = NyankoFaceAdapter(
        Settings(), httpx.MockTransport(lambda _request: response),
    )

    with pytest.raises(WriteResponseError) as captured:
        await adapter.control_space("start", "alice", "repo", "caller-pat")

    assert captured.value.code == "invalid_upstream_response"
    assert captured.value.retry_safe is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "foreign_status"),
    [
        ("start", "published"),
        ("stop", "building"),
        ("pages", "running"),
        ("dispatch", "accepted"),
        ("cancel", "queued"),
    ],
)
async def test_control_success_rejects_status_from_another_operation(
    operation, foreign_status,
):
    adapter = NyankoFaceAdapter(
        Settings(),
        httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"status": foreign_status}),
        ),
    )

    with pytest.raises(WriteResponseError) as captured:
        if operation in {"start", "stop"}:
            await adapter.control_space(operation, "alice", "repo", "caller-pat")
        elif operation == "pages":
            await adapter.deploy_pages("alice", "repo", "docs", "caller-pat")
        elif operation == "dispatch":
            await adapter.dispatch_pipeline(
                "alice", "repo", "publish.yml", "main", "staging", {}, "caller-pat",
            )
        else:
            await adapter.pipeline_action(
                "cancel", "alice", "repo", 7, "caller-pat",
            )

    assert captured.value.code == "invalid_upstream_response"
    assert captured.value.retry_safe is False


@pytest.mark.asyncio
async def test_environment_adapter_uses_expected_kind_and_projects_only_metadata():
    requests: list[httpx.Request] = []
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.extensions["timeout"]["read"] == 120.0
        return httpx.Response(200, json={
            "item": {
                "name": "TOKEN", "kind": "secret", "scope": "both",
                "enabled": True, "configured": True,
                "updated_at": "2026-08-02T00:00:00Z",
                "value": "must-not-leak",
            },
            "restart_required": True,
            "runtime": None,
        })
    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    result = await adapter.set_space_environment(
        "alice", "repo", "TOKEN", "secret", "must-not-leak", "both", "caller-pat",
    )
    request = requests[0]
    assert request.method == "PUT"
    assert request.headers["authorization"] == "Bearer caller-pat"
    assert json.loads(request.read()) == {
        "kind": "secret", "expected_kind": "secret", "value": "must-not-leak",
        "scope": "both", "enabled": True, "restart": False,
    }
    assert result == {
        "item": {
            "name": "TOKEN", "kind": "secret", "scope": "both",
            "enabled": True, "configured": True,
            "updated_at": "2026-08-02T00:00:00Z",
        },
        "restart_required": True,
    }
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "response"),
    [
        ("set", {}),
        ("set", {"deleted": True, "name": "TOKEN"}),
        ("set", {"item": {"name": "TOKEN", "kind": "variable", "scope": "runtime", "enabled": True, "configured": True}}),
        ("set", {"item": {"name": "TOKEN", "kind": "secret", "scope": "build", "enabled": True, "configured": True}}),
        ("set", {"item": {"name": "TOKEN", "kind": "secret", "scope": "runtime", "enabled": False, "configured": True}}),
        ("set", {"item": {"name": "TOKEN", "kind": "secret", "scope": "runtime", "enabled": True, "configured": True}, "restart_required": False, "runtime": None}),
        ("set", {"item": {"name": "TOKEN", "kind": "secret", "scope": "runtime", "enabled": True, "configured": True}, "restart_required": True, "runtime": {}}),
        ("delete", {"status": "applied", "restart_required": False}),
        ("delete", {"deleted": "yes", "name": "TOKEN"}),
        ("delete", {"deleted": True, "name": "TOKEN", "restart_required": False, "runtime": None}),
        ("apply", {"status": "unchanged", "restart_required": True}),
        ("apply", {"status": "applied", "restart_required": False, "item": {}}),
        ("apply", {"status": "applied", "restart_required": False}),
        ("apply", {"status": "applied", "restart_required": False, "runtime": {"status": "building"}}),
    ],
)
async def test_environment_adapter_rejects_missing_unknown_or_cross_operation_shapes(
    operation, response,
):
    adapter = NyankoFaceAdapter(
        Settings(), httpx.MockTransport(lambda _request: httpx.Response(200, json=response)),
    )
    with pytest.raises(WriteResponseError) as captured:
        if operation == "set":
            await adapter.set_space_environment(
                "alice", "repo", "TOKEN", "secret", "value", "runtime", "caller-pat",
            )
        elif operation == "delete":
            await adapter.delete_space_environment(
                "alice", "repo", "TOKEN", "secret", "caller-pat",
            )
        else:
            await adapter.apply_space_environment("alice", "repo", None, "caller-pat")
    assert captured.value.code == "invalid_upstream_response"
    assert captured.value.retry_safe is False
@pytest.mark.asyncio
async def test_environment_adapter_delete_requires_staged_no_restart_response():
    requests: list[httpx.Request] = []
    adapter = NyankoFaceAdapter(
        Settings(), httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(200, json={
            "deleted": True,
            "name": "TOKEN",
            "restart_required": True,
            "runtime": None,
        })),
    )
    result = await adapter.delete_space_environment(
        "alice", "repo", "TOKEN", "secret", "caller-pat",
    )
    assert requests[0].extensions["timeout"]["read"] == 120.0
    assert result == {
        "deleted": True,
        "name": "TOKEN",
        "restart_required": True,
    }


@pytest.mark.asyncio
async def test_environment_adapter_apply_binds_requested_revision_and_runtime():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.extensions["timeout"]["read"] == 720.0
        assert json.loads(request.read()) == {"restart": True, "revision": "abc123"}
        return httpx.Response(200, json={
            "status": "applied",
            "restart_required": False,
            "runtime": {
                "status": "running",
                "execution": "local-cpu",
                "revision": "abc123",
                "url": "must-not-be-projected",
            },
        })

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    result = await adapter.apply_space_environment(
        "alice", "repo", "abc123", "caller-pat",
    )
    assert result == {
        "status": "applied",
        "restart_required": False,
        "runtime": {
            "status": "running",
            "execution": "local-cpu",
        "revision": "abc123",
        },
    }
@pytest.mark.asyncio
async def test_environment_adapter_apply_rejects_revision_mismatch():
    adapter = NyankoFaceAdapter(
        Settings(), httpx.MockTransport(lambda _request: httpx.Response(200, json={
            "status": "applied",
            "restart_required": False,
            "runtime": {"status": "running", "revision": "other"},
        })),
    )
    with pytest.raises(WriteResponseError) as captured:
        await adapter.apply_space_environment(
            "alice", "repo", "abc123", "caller-pat",
        )
    assert captured.value.code == "invalid_upstream_response"
    assert captured.value.retry_safe is False


@pytest.mark.asyncio
@pytest.mark.parametrize(("declared", "expected"), [(True, True), ("true", False)])
async def test_environment_adapter_preserves_only_boolean_retry_without_error_body(
    declared, expected,
):
    marker = "secret=runner-reflected-plaintext"
    adapter = NyankoFaceAdapter(
        Settings(), httpx.MockTransport(lambda _request: httpx.Response(
            503,
            json={"detail": {"code": "bad", "message": marker, "retry_safe": declared}},
        )),
    )
    with pytest.raises(WriteResponseError) as captured:
        await adapter.set_space_environment(
            "alice", "repo", "TOKEN", "secret", marker, "runtime", "caller-pat",
        )
    assert captured.value.code == "environment_rejected"
    assert captured.value.retry_safe is expected
    assert marker not in str(captured.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["space", "pages", "pipeline"])
@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadTimeout])
async def test_control_surfaces_sanitize_down_and_timeout(surface, failure):
    def handler(_request: httpx.Request) -> httpx.Response:
        raise failure("runner is down")

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    with pytest.raises(ToolError, match="temporarily unavailable"):
        if surface == "space":
            await adapter.control_space("start", "alice", "repo", "caller-pat")
        elif surface == "pages":
            await adapter.deploy_pages("alice", "repo", "docs", "caller-pat")
        else:
            await adapter.dispatch_pipeline(
                "alice", "repo", "publish.yml", "main", "staging", {}, "caller-pat",
            )


@pytest.mark.asyncio
async def test_catalog_preserves_effective_pagination_metadata():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["page"] == "99"
        return httpx.Response(200, json={
            "data": [{"full_name": "alice/repo", "private": False}],
            "page": 3,
            "limit": 20,
            "totalCount": 41,
            "totalPages": 3,
        })

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    result = await adapter.search_catalog("model", page=99, limit=20)
    assert result["page"] == 3
    assert result["limit"] == 20
    assert result["totalCount"] == 41
    assert result["totalPages"] == 3


@pytest.mark.asyncio
async def test_file_uses_repository_default_branch_when_ref_is_omitted():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "/contents/" not in request.url.path:
            return httpx.Response(200, json={
                "name": "repo",
                "private": False,
                "default_branch": "trunk",
            })
        assert request.url.params["ref"] == "trunk"
        return httpx.Response(200, json={
            "type": "file",
            "size": 5,
            "sha": "abc",
            "content": base64.b64encode(b"hello").decode(),
        })

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    result = await adapter.get_file("alice", "repo", "README.md", None, None)
    assert len(requests) == 2
    assert result["ref"] == "trunk"
    assert result["text"] == "hello"


@pytest.mark.asyncio
async def test_file_path_preserves_directories_and_percent_encodes_segments():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "/contents/" not in request.url.path:
            return httpx.Response(200, json={"name": "repo", "private": False})
        assert request.url.raw_path.split(b"?", 1)[0].endswith(
            b"/contents/docs/My%20file%20%231%25.md"
        )
        return httpx.Response(200, json={
            "type": "file",
            "size": 5,
            "sha": "abc",
            "content": base64.b64encode(b"hello").decode(),
        })

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    result = await adapter.get_file("alice", "repo", "docs/My file #1%.md", "main", None)
    assert len(requests) == 2
    assert result["path"] == "docs/My file #1%.md"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404])
async def test_issue_write_authorization_hides_private_repository_existence(status):
    def handler(_request):
        return httpx.Response(status, json={"message": "private details"})

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    with pytest.raises(ToolError) as captured:
        await adapter.authorize_issue_write("alice", "private", "caller-pat")
    assert json.loads(str(captured.value))["error"] == {
        "code": "not_found_or_unauthorized",
        "message": "Resource was not found or is not authorized",
        "retryable": False,
        "action": "Verify the repository identity and the caller's current read permission.",
    }


@pytest.mark.asyncio
async def test_issue_write_requires_current_push_permission():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        assert request.headers["authorization"] == "token caller-pat"
        return httpx.Response(200, json={
            "full_name": "alice/repo", "private": False,
            "permissions": {"pull": True, "push": False, "admin": False},
        })

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    with pytest.raises(ToolError, match="^Resource was not found or is not authorized$"):
        await adapter.authorize_issue_write("alice", "repo", "caller-pat")
    assert calls == 1


@pytest.mark.asyncio
async def test_issue_write_routes_use_caller_identity_and_redact_results():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["authorization"] == "token caller-pat"
        if request.method == "GET":
            return httpx.Response(200, json={
                "full_name": "alice/repo", "private": True,
                "permissions": {"push": True},
            })
        return httpx.Response(200, json={
            "number": 2, "authorization": "Bearer abcdefghijklmnopqrstuvwxyz",
        })

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    await adapter.authorize_issue_write("alice", "repo", "caller-pat")
    created = await adapter.create_issue("alice", "repo", "Title", "Body", "caller-pat")
    updated = await adapter.update_issue("alice", "repo", 2, {"state": "closed"}, "caller-pat")
    commented = await adapter.comment_issue("alice", "repo", 2, "Hi", "caller-pat")
    assert created["authorization"] == updated["authorization"] == commented["authorization"] == "[REDACTED]"
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/api/v1/repos/alice/repo"),
        ("POST", "/api/v1/repos/alice/repo/issues"),
        ("PATCH", "/api/v1/repos/alice/repo/issues/2"),
        ("POST", "/api/v1/repos/alice/repo/issues/2/comments"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [
    httpx.ConnectError("down"), httpx.ReadTimeout("timeout"),
])
async def test_issue_write_connection_failures_are_safely_normalized(failure):
    def handler(request):
        raise failure

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    with pytest.raises(ToolError, match="^NyankoFace upstream is temporarily unavailable$"):
        await adapter.create_issue("alice", "repo", "Title", "Body", "caller-pat")


@pytest.mark.asyncio
@pytest.mark.parametrize(("response", "code", "retry_safe"), [
    (httpx.Response(403, json={"message": "private details"}), "upstream_rejected", True),
    (httpx.Response(422, json={"message": "invalid"}), "upstream_http_error", True),
    (httpx.Response(503, json={"message": "down"}), "upstream_http_error", False),
    (httpx.Response(200, text="not-json"), "invalid_upstream_response", False),
])
async def test_issue_write_definite_responses_remain_classified(response, code, retry_safe):
    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(lambda _request: response))

    with pytest.raises(WriteResponseError) as caught:
        await adapter.create_issue("alice", "repo", "Title", "Body", "caller-pat")

    assert caught.value.code == code
    assert caught.value.retry_safe is retry_safe
    assert "private details" not in str(caught.value)


def test_default_write_state_is_local_tooling_safe():
    settings = Settings()

    assert settings.write_state_path.name == "write-safety.sqlite3"
    assert settings.write_state_path.parent.name.startswith("nyankoface-mcp-")
    assert settings.write_state_path.parent.parent == Path(tempfile.gettempdir())


def test_catalog_contract_includes_real_agent_content_kinds():
    assert {"skill", "mcp", "prompt", "doc"}.issubset(CATALOG_KINDS)


@pytest.mark.parametrize("ref", [
    ".", "..", "main/../secret", "main//leaf", "/main", "main/", "main.lock",
    "refs/heads/%2e%2e/secret", "refs%2fheads%2fmain", "refs/heads/main@{1}",
    "refs/.hidden/main", "refs/heads/release.", "refs/heads/with space",
])
def test_tree_ref_rejects_traversal_and_encoded_delimiters(ref):
    with pytest.raises(ToolError, match="Invalid repository ref"):
        validate_ref(ref)


@pytest.mark.parametrize("ref", [
    "日本語/検証", "feature/demo+safe", "refs/heads/release", "percent%2Bplus",
])
def test_tree_ref_accepts_valid_utf8_and_git_ref_characters(ref):
    assert validate_ref(ref) == ref


@pytest.mark.parametrize("path", [
    "../secret", "docs/../secret", "docs/%2e%2e/secret", "docs%2fsecret.md",
    "docs\\secret.md", "docs//secret.md", "./README.md",
    "/etc/passwd", "README.md/",
])
def test_file_path_rejects_plain_and_encoded_traversal(path):
    with pytest.raises(ToolError, match="not available"):
        validate_content_path(path)


@pytest.mark.asyncio
async def test_tree_is_ref_fixed_authorized_redacted_and_has_cache_metadata():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "token caller-pat"
        if request.url.path.endswith("/repos/alice/repo"):
            return httpx.Response(200, json={
                "name": "repo", "private": True, "updated_at": "2026-08-01T12:00:00Z",
            })
        assert request.url.path == "/api/v1/repos/alice/repo/contents"
        assert request.url.params["ref"] == "refs/heads/release"
        return httpx.Response(200, headers={"ETag": '"tree-etag"'}, json=[{
            "name": "README.md", "path": "README.md", "type": "file",
            "sha": "abc", "access_token": "never",
        }])

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    result = await adapter.get_tree("alice", "repo", "refs/heads/release", "caller-pat")
    assert len(requests) == 2
    assert result["ref"] == "refs/heads/release"
    assert result["entries"][0]["access_token"] == "[REDACTED]"
    assert result["_meta"]["etag"] == '"tree-etag"'
    assert result["_meta"]["cache_control"] == "private, max-age=60"


@pytest.mark.asyncio
@pytest.mark.parametrize("ref", ["日本語/検証", "feature/demo+safe"])
async def test_tree_sends_valid_utf8_and_plus_refs_to_upstream(ref):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/repos/alice/repo"):
            return httpx.Response(200, json={"name": "repo", "private": False})
        assert request.url.path == "/api/v1/repos/alice/repo/contents"
        assert request.url.params["ref"] == ref
        return httpx.Response(200, json=[])

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    result = await adapter.get_tree("alice", "repo", ref, None)
    assert result["ref"] == ref


@pytest.mark.asyncio
async def test_tree_denies_other_subject_before_returning_private_content():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "token other-subject-pat"
        return httpx.Response(404, json={"message": "not found", "token": "must-not-leak"})

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    with pytest.raises(ToolError, match="not found or is not authorized") as caught:
        await adapter.get_tree("alice", "private", "main", "other-subject-pat")
    assert len(requests) == 1
    assert "must-not-leak" not in str(caught.value)


@pytest.mark.asyncio
async def test_repository_listing_uses_caller_identity_and_bounded_pagination():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/repos/search"
        assert request.headers["authorization"] == "token caller-pat"
        assert request.url.params["page"] == "1"
        assert request.url.params["limit"] == "100"
        return httpx.Response(200, headers={"ETag": '"repos"', "X-Total-Count": "201"}, json={
            "data": [{"full_name": "alice/private", "private": True, "updated_at": "2026-08-01T00:00:00Z"}],
            "total_count": 1,
        })

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    result = await adapter.list_repositories("alice", -4, 999, "caller-pat")
    assert result["page"] == 1 and result["limit"] == 100
    assert result["items"][0]["private"] is True
    assert result["totalCount"] == 201 and result["totalPages"] == 3
    assert result["_meta"]["etag"] == '"repos"'
    assert result["_meta"]["updated_at"] == "2026-08-01T00:00:00Z"


@pytest.mark.asyncio
async def test_current_user_identity_uses_caller_pat_and_requires_positive_integer_id():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/user"
        assert request.headers["authorization"] == "token caller-pat"
        return httpx.Response(200, json={"id": 42, "login": "service-reader"})

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    assert await adapter.get_current_user_id("caller-pat") == 42


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_id", [None, True, 0, -1, "42"])
async def test_current_user_identity_rejects_invalid_id(invalid_id):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": invalid_id})

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    with pytest.raises(ToolError, match="invalid Forgejo identity"):
        await adapter.get_current_user_id("caller-pat")


@pytest.mark.asyncio
async def test_anonymous_repository_listing_filters_private_entries():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"data": [
            {"full_name": "alice/public", "private": False},
            {"full_name": "alice/private", "private": True},
        ]})

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    result = await adapter.list_repositories("", 1, 20, None)
    assert [item["full_name"] for item in result["items"]] == ["alice/public"]


@pytest.mark.asyncio
async def test_knowledge_uses_public_revalidation_endpoint_and_redacts_result():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/knowledge/alice/secure-publishing"
        assert "authorization" not in request.headers
        return httpx.Response(200, headers={
            "ETag": '"knowledge"',
            "Cache-Control": "public, no-cache, must-revalidate",
        }, json={
            "owner": "alice", "slug": "secure-publishing",
            "updatedAt": "2026-08-01T00:00:00Z", "bodyMarkdown": "token: secret-value",
        })

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    result = await adapter.get_knowledge("alice", "secure-publishing", None)
    assert result["bodyMarkdown"].strip() == "token: [REDACTED]"
    assert result["_meta"]["etag"] == '"knowledge"'
    assert result["_meta"]["updated_at"] == "2026-08-01T00:00:00Z"
    assert result["_meta"]["cache_control"] == "public, no-cache, must-revalidate"


@pytest.mark.asyncio
async def test_environment_metadata_never_returns_values_or_secret_shape():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "forgejo":
            return httpx.Response(200, json={
                "name": "repo", "private": True,
                "updated_at": "2026-08-01T00:00:00Z",
            })
        assert request.url.path == "/api/v1/spaces/alice/repo/environment"
        assert request.headers["authorization"] == "Bearer caller-pat"
        return httpx.Response(200, json={"items": [{
            "name": "DATABASE_URL", "configured": True,
            "updated_at": "2026-08-02T00:00:00Z", "kind": "secret",
            "scope": "runtime", "enabled": True, "value": "must-not-leak",
        }]})

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    result = await adapter.get_space_environment_metadata("alice", "repo", "caller-pat")
    assert result["data"]["items"] == [{
        "name": "DATABASE_URL", "configured": True,
        "updated_at": "2026-08-02T00:00:00Z",
    }]
    assert "must-not-leak" not in json.dumps(result)
    assert result["_meta"]["updated_at"] == "2026-08-02T00:00:00Z"


@pytest.mark.asyncio
async def test_pipeline_reads_are_paginated_and_reauthorize_repository():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "forgejo":
            return httpx.Response(200, json={"name": "repo", "private": True})
        assert request.headers["authorization"] == "Bearer caller-pat"
        if request.url.path.endswith("/runs/7/metadata"):
            return httpx.Response(200, json={
                "updated_at": "2026-08-02T02:00:00Z",
                "state": {"run": {
                    "title": "CI", "status": "success", "canRerun": True,
                    "trace": "must-not-leak",
                }},
                "jobs": [{
                    "id": 0, "forgejo_job_id": 81, "name": "Build",
                    "status": "success", "logs": ["must-not-leak"],
                    "steps": [{"name": "must-not-leak"}],
                }],
            })
        assert dict(request.url.params) == {"page": "2", "limit": "2"}
        return httpx.Response(200, json={
            "runs": [{"run_number": number} for number in (3, 4)],
            "pagination": {"page": 2, "limit": 2, "total_count": 5, "total_pages": 3},
        })

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    listing = await adapter.list_pipeline_runs("alice", "repo", 2, 2, "caller-pat")
    detail = await adapter.get_pipeline_run("alice", "repo", 7, "caller-pat")
    assert [item["run_number"] for item in listing["data"]["items"]] == [3, 4]
    assert listing["_meta"]["pagination"]["total_count"] == 5
    assert detail["data"]["run"] == {
        "title": "CI", "status": "success", "canRerun": True,
    }
    assert "must-not-leak" not in json.dumps(detail)
    assert len([request for request in requests if request.url.host == "forgejo"]) == 2


def test_resource_document_etag_covers_pagination_metadata():
    first = client_module.resource_document(
        {"items": [{"id": 1}]},
        pagination={"page": 1, "limit": 20, "total_count": 20, "total_pages": 1},
    )
    expanded = client_module.resource_document(
        {"items": [{"id": 1}]},
        pagination={"page": 1, "limit": 20, "total_count": 21, "total_pages": 2},
    )
    assert first["_meta"]["etag"] != expanded["_meta"]["etag"]


def test_resource_document_etag_covers_external_update_timestamp():
    first = client_module.resource_document(
        {"views": 12},
        updated_at="2026-08-01T00:00:00Z",
    )
    updated = client_module.resource_document(
        {"views": 12},
        updated_at="2026-08-02T00:00:00Z",
    )

    assert first["data"] == updated["data"]
    assert first["_meta"]["etag"] != updated["_meta"]["etag"]
    assert updated["_meta"]["updated_at"] == "2026-08-02T00:00:00Z"


@pytest.mark.asyncio
async def test_metrics_reauthorizes_and_uses_repository_update_time():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "forgejo":
            return httpx.Response(200, json={
                "name": "repo", "private": False,
                "updated_at": "2026-08-02T03:00:00Z",
            })
        return httpx.Response(200, json={
            "owner": "spoofed-owner",
            "repo": "spoofed-repo",
            "views": 12,
            "agent_views": 7,
            "browser_views": 5,
            "likes": 3,
            "recent_agents": [{
                "slug": "must-not-leak",
                "display_name": "must-not-leak",
            }],
            "future_field": "must-not-leak",
        })

    result = await NyankoFaceAdapter(
        Settings(), httpx.MockTransport(handler),
    ).get_metrics("alice", "repo", None)
    assert result["data"] == {
        "owner": "alice",
        "repo": "repo",
        "views": 12,
        "agent_views": 7,
        "browser_views": 5,
        "likes": 3,
    }
    assert "must-not-leak" not in json.dumps(result)
    assert result["_meta"]["updated_at"] == "2026-08-02T03:00:00Z"


@pytest.mark.asyncio
async def test_openapi_resource_preserves_schema_and_removes_sensitive_examples():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/openapi.json"
        return httpx.Response(200, json={
            "openapi": "3.1.0", "example_token": "must-not-leak",
            "components": {"schemas": {"EnrollmentTokenRequest": {
                "required": ["token"],
                "properties": {"token": {
                    "type": "string", "default": "must-not-leak",
                    "example": "must-not-leak",
                }},
            }}},
            "paths": {"/enroll": {"post": {"requestBody": {
                "content": {"application/json": {"schema": {
                    "$ref": "#/components/schemas/EnrollmentTokenRequest",
                }}},
            }}}},
        })

    result = await NyankoFaceAdapter(
        Settings(), httpx.MockTransport(handler),
    ).get_openapi()
    enroll = result["data"]["components"]["schemas"]["EnrollmentTokenRequest"]
    assert result["data"]["example_token"] == "[REDACTED]"
    assert enroll["required"] == ["token"]
    assert enroll["properties"]["token"] == {"type": "string"}
    assert result["data"]["paths"]["/enroll"]["post"]["requestBody"][
        "content"
    ]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/EnrollmentTokenRequest"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code,code,retryable", [
    (429, "rate_limited", True),
    (503, "upstream_unavailable", True),
    (422, "upstream_rejected", False),
])
async def test_operational_http_errors_are_actionable(status_code, code, retryable):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "forgejo":
            return httpx.Response(200, json={"name": "repo", "private": False})
        return httpx.Response(status_code, text="token=must-not-leak internal-host")

    adapter = NyankoFaceAdapter(Settings(), httpx.MockTransport(handler))
    with pytest.raises(ToolError) as captured:
        await adapter.get_status("spaces", "alice", "repo", None)
    payload = json.loads(str(captured.value))
    assert payload["error"]["code"] == code
    assert payload["error"]["retryable"] is retryable
    assert "must-not-leak" not in str(captured.value)
