from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime
import json
import re
import subprocess
import sys
import threading


SCRIPT = Path(__file__).parents[1] / "scripts" / "provision_live_client_qa.sh"
RUNNER = Path(__file__).parents[1] / "scripts" / "run_live_client_protocol.py"
VSCODE_CONFIG = Path(__file__).parents[1] / "examples" / "vscode-mcp.json"
EVIDENCE = Path(__file__).parents[2] / "docs" / "evidence" / "issues" / "130"
MATRIX = EVIDENCE / "live-client-matrix.json"
TRANSCRIPTS = EVIDENCE / "client-state-transcripts.jsonl"
RAW_MANIFEST = EVIDENCE / "raw-artifact-manifest.json"
GUIDE_EN = Path(__file__).parents[2] / "docs" / "guide" / "mcp-live-clients.md"
GUIDE_JA = Path(__file__).parents[2] / "docs" / "ja" / "guide" / "mcp-live-clients.md"
MCP_SERVER_GUIDE_EN = Path(__file__).parents[2] / "docs" / "guide" / "mcp-server.md"
MCP_SERVER_GUIDE_JA = Path(__file__).parents[2] / "docs" / "ja" / "guide" / "mcp-server.md"
VALID_CAPABILITIES = {"tools": {}, "resources": {}}
VALID_SEARCH_TOOL = {"name": "search_catalog", "inputSchema": {"type": "object"}}
VALID_REPOSITORY_TOOL = {"name": "get_repository", "inputSchema": {"type": "object"}}
VALID_OPENAPI_RESOURCE = {
    "name": "openapi_resource",
    "uri": "nyankoface://api/openapi",
}


def test_live_client_provisioner_has_all_clients_and_auth_states():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "for client in codex claude-desktop vscode" in source
    for state in ("valid", "scope", "expired", "revoked", "invalid"):
        assert state in source
    assert 'issue_token "${subject}" "${client}" scope 7200 \\' in source
    assert "--scope repos:read" in source
    assert "subject_exists" in source
    assert 'account_command="remap-service-account"' in source
    assert "registry_exists" not in source


def test_live_client_provisioner_keeps_plaintext_tokens_out_of_stdout():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "umask 077" in source
    assert 'chgrp "${NYANKOFACE_MCP_REGISTRY_READER_GID}"' in source
    assert 'chmod 0750 "${NYANKOFACE_MCP_REGISTRY_DIR}"' in source
    assert "--user 0:0" in source
    assert "os.chmod(token_path, 0o600)" in source
    assert "secrets_printed" in source
    assert "cat " not in source
    assert "set -x" not in source
    assert "nyankoface-mcp-admin" not in source
    assert "python -m nyankoface_mcp.admin" in source


def test_live_protocol_runner_never_serializes_the_token():
    source = RUNNER.read_text(encoding="utf-8")

    assert '"secret_exposed": False' in source
    assert '"token": token' not in source
    assert "token_file.read_text" in source
    assert "credential appeared in diagnostic output" in source
    for method in ("initialize", "tools/list", "resources/list", "tools/call"):
        assert method in source
    assert "urllib.error.HTTPError" in source
    assert "--expected-initialize-status" in source
    assert "--expect-read-error" in source
    assert "EXPECTED_CATALOG_SCOPE_DENIAL" in source
    assert "require_result" in source


def test_live_guides_keep_tls_terminating_proxies_on_the_gateway_https_listener():
    for guide in (MCP_SERVER_GUIDE_EN, MCP_SERVER_GUIDE_JA):
        source = guide.read_text(encoding="utf-8")
        assert "426" in source
        assert "https+insecure://127.0.0.1:8443" in source
        assert "run_live_client_protocol.py" in source
        assert "initialize" in source


def test_vscode_remote_http_example_uses_a_masked_input():
    config = json.loads(VSCODE_CONFIG.read_text(encoding="utf-8"))
    server = config["servers"]["nyankoface"]

    assert server["type"] == "http"
    assert server["url"] == "https://<NYANKOFACE_HOST>/mcp"
    assert server["headers"]["Authorization"] == "Bearer ${input:nyankoface-token}"
    assert config["inputs"] == [{
        "id": "nyankoface-token",
        "type": "promptString",
        "description": "NyankoFace MCP token",
        "password": True,
    }]


class _ProtocolFixture(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    methods = []
    response_content_type = "application/json"

    def log_message(self, _format, *_args):
        return

    def _send(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", type(self).response_content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-NyankoFace-MCP-Instance", "fixture-a")
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status):
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.send_header("X-NyankoFace-MCP-Instance", "fixture-a")
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        token = self.headers.get("Authorization", "").removeprefix("Bearer ")
        if token in {"invalid-secret", "expired-secret", "revoked-secret"}:
            self._send(401, {"jsonrpc": "2.0", "id": request["id"], "error": {
                "code": -32001, "message": "authentication rejected",
            }})
            return
        method = request["method"]
        type(self).methods.append(method)
        if method == "notifications/initialized":
            self._send_empty(202)
            return
        result = {
            "initialize": {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "NyankoFace", "version": "0.1.0"},
                "capabilities": VALID_CAPABILITIES,
            },
            "tools/list": {"tools": [VALID_SEARCH_TOOL, VALID_REPOSITORY_TOOL]},
            "resources/list": {"resources": [VALID_OPENAPI_RESOURCE]},
        }.get(method)
        if method == "tools/call":
            denied = token == "scope-secret" and request["params"]["name"] == "search_catalog"
            result = {
                "content": ([{"type": "text", "text": (
                    "Error executing tool search_catalog: "
                    "Missing required NyankoFace scope: catalog:read"
                )}] if denied else
                            [{"type": "text", "text": "fixture result"}]),
                "isError": denied,
            }
        self._send(200, {"jsonrpc": "2.0", "id": request["id"], "result": result})


class _SseFixture(_ProtocolFixture):
    response_content_type = "text/event-stream"

    def _send(self, status, payload):
        encoded = json.dumps(payload)
        split_at = encoded.find(', "result"')
        assert split_at > 0
        body = (
            "event: message\n"
            f"data:{encoded[:split_at]}\n"
            f"data: {encoded[split_at:]}\n\n"
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", type(self).response_content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-NyankoFace-MCP-Instance", "fixture-a")
        self.end_headers()
        self.wfile.write(body)


class _BooleanIdSseFixture(_SseFixture):
    def _send(self, status, payload):
        payload = dict(payload)
        payload["id"] = True
        super()._send(status, payload)


class _UnsupportedContentTypeFixture(_ProtocolFixture):
    response_content_type = "text/plain"


class _JsonRpcErrorFixture(_ProtocolFixture):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        self._send(200, {"jsonrpc": "2.0", "id": request["id"], "error": {
            "code": -32603, "message": "fixture failure",
        }})


class _MissingResultFixture(_ProtocolFixture):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        self._send(200, {"jsonrpc": "2.0", "id": request["id"]})


class _EmptyInitializeFixture(_ProtocolFixture):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        self._send(200, {"jsonrpc": "2.0", "id": request["id"], "result": {}})


class _InvalidProtocolFixture(_ProtocolFixture):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        self._send(200, {"jsonrpc": "2.0", "id": request["id"], "result": {
            "protocolVersion": "2099-01-01",
            "serverInfo": {"name": "NyankoFace", "version": "0.1.0"},
            "capabilities": {},
        }})


class _InvalidServerInfoFixture(_ProtocolFixture):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        self._send(200, {"jsonrpc": "2.0", "id": request["id"], "result": {
            "protocolVersion": "2025-06-18",
            "serverInfo": {"name": "NyankoFace", "version": ""},
            "capabilities": {},
        }})


class _MissingCapabilitiesFixture(_ProtocolFixture):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        self._send(200, {"jsonrpc": "2.0", "id": request["id"], "result": {
            "protocolVersion": "2025-06-18",
            "serverInfo": {"name": "NyankoFace", "version": "0.1.0"},
        }})


class _MissingCapabilityDeclarationFixture(_ProtocolFixture):
    missing_capability = "tools"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        capabilities = dict(VALID_CAPABILITIES)
        capabilities.pop(self.missing_capability)
        self._send(200, {"jsonrpc": "2.0", "id": request["id"], "result": {
            "protocolVersion": "2025-06-18",
            "serverInfo": {"name": "NyankoFace", "version": "0.1.0"},
            "capabilities": capabilities,
        }})


class _MalformedToolListingFixture(_ProtocolFixture):
    malformed_field = "inputSchema"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        if request["method"] == "initialize":
            self._send(200, {"jsonrpc": "2.0", "id": request["id"], "result": {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "NyankoFace", "version": "0.1.0"},
                "capabilities": VALID_CAPABILITIES,
            }})
            return
        if request["method"] == "notifications/initialized":
            self._send_empty(202)
            return
        if request["method"] == "tools/list":
            tool = dict(VALID_SEARCH_TOOL)
            if type(self).malformed_field == "name":
                tool["name"] = " "
            else:
                tool.pop("inputSchema")
            self._send(200, {"jsonrpc": "2.0", "id": request["id"], "result": {
                "tools": [tool],
            }})
            return
        self._send(503, {"jsonrpc": "2.0", "id": request["id"], "error": {
            "code": -32603, "message": "unexpected method",
        }})


class _MalformedResourceListingFixture(_ProtocolFixture):
    malformed_field = "name"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        if request["method"] == "initialize":
            self._send(200, {"jsonrpc": "2.0", "id": request["id"], "result": {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "NyankoFace", "version": "0.1.0"},
                "capabilities": VALID_CAPABILITIES,
            }})
            return
        if request["method"] == "notifications/initialized":
            self._send_empty(202)
            return
        if request["method"] == "resources/list":
            resource = dict(VALID_OPENAPI_RESOURCE)
            if type(self).malformed_field == "name":
                resource["name"] = ""
            else:
                resource.pop("uri")
            self._send(200, {"jsonrpc": "2.0", "id": request["id"], "result": {
                "resources": [resource],
            }})
            return
        if request["method"] == "tools/list":
            self._send(200, {"jsonrpc": "2.0", "id": request["id"], "result": {
                "tools": [VALID_SEARCH_TOOL],
            }})
            return
        self._send(503, {"jsonrpc": "2.0", "id": request["id"], "error": {
            "code": -32603, "message": "unexpected method",
        }})


class _WrongAuthEnvelopeFixture(_ProtocolFixture):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        self._send(401, {"jsonrpc": "2.0", "id": request["id"], "error": {
            "code": -32603, "message": "upstream failure",
        }})


class _BooleanAuthIdFixture(_ProtocolFixture):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self._send(401, {"jsonrpc": "2.0", "id": True, "error": {
            "code": -32001, "message": "authentication rejected",
        }})


class _OAuthAuthFailureFixture(_ProtocolFixture):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self._send(401, {
            "error": "invalid_token",
            "error_description": "Authentication required",
        })


class _MalformedEnvelopeFixture(_ProtocolFixture):
    mode = "jsonrpc"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        payload = {
            "id": request["id"],
            "result": {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "NyankoFace", "version": "0.1.0"},
                "capabilities": {},
            },
        }
        if self.mode == "jsonrpc":
            payload["jsonrpc"] = "1.0"
        else:
            payload["jsonrpc"] = "2.0"
            payload["id"] = request["id"] + 100
        self._send(200, payload)


class _ProtocolHeaderFixture(_ProtocolFixture):
    request_count = 0

    def do_POST(self):
        type(self).request_count += 1
        if type(self).request_count > 1 and self.headers.get("MCP-Protocol-Version") != "2025-06-18":
            self._send(400, {"jsonrpc": "2.0", "id": None, "error": {
                "code": -32600, "message": "missing protocol version",
            }})
            return
        super().do_POST()


class _EmptyListingsFixture(_ProtocolFixture):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        if request["method"] == "notifications/initialized":
            self._send_empty(202)
            return
        results = {
            "initialize": {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "NyankoFace", "version": "0.1.0"},
                "capabilities": VALID_CAPABILITIES,
            },
            "tools/list": {"tools": []},
            "resources/list": {"resources": []},
            "tools/call": {
                "content": [{"type": "text", "text": "fixture result"}],
                "isError": False,
            },
        }
        self._send(200, {"jsonrpc": "2.0", "id": request["id"], "result": results[request["method"]]})


class _RedirectFixture(_ProtocolFixture):
    redirect_url = ""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self.send_response(302)
        self.send_header("Location", self.redirect_url)
        self.send_header("Content-Length", "0")
        self.end_headers()


class _RedirectTargetFixture(BaseHTTPRequestHandler):
    received_authorization = []

    def log_message(self, _format, *_args):
        return

    def _record(self):
        self.received_authorization.append(self.headers.get("Authorization"))
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = _record
    do_POST = _record


class _ToolsListFailureFixture(_ProtocolFixture):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        if request["method"] == "notifications/initialized":
            self._send_empty(202)
            return
        if request["method"] == "initialize":
            self._send(200, {"jsonrpc": "2.0", "id": request["id"], "result": {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "NyankoFace", "version": "0.1.0"},
                "capabilities": VALID_CAPABILITIES,
            }})
            return
        self._send(503, {"jsonrpc": "2.0", "id": request["id"], "error": {
            "code": -32603, "message": "list unavailable",
        }})


class _ResourcesListFailureFixture(_ProtocolFixture):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        if request["method"] == "notifications/initialized":
            self._send_empty(202)
            return
        results = {
            "initialize": {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "NyankoFace", "version": "0.1.0"},
                "capabilities": VALID_CAPABILITIES,
            },
            "tools/list": {"tools": [VALID_SEARCH_TOOL]},
        }
        if request["method"] in results:
            self._send(200, {
                "jsonrpc": "2.0", "id": request["id"],
                "result": results[request["method"]],
            })
            return
        self._send(503, {"jsonrpc": "2.0", "id": request["id"], "error": {
            "code": -32603, "message": "resources unavailable",
        }})


class _WrongOpenApiUriFixture(_ProtocolFixture):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        if request["method"] == "notifications/initialized":
            self._send_empty(202)
            return
        results = {
            "initialize": {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "NyankoFace", "version": "0.1.0"},
                "capabilities": VALID_CAPABILITIES,
            },
            "tools/list": {"tools": [VALID_SEARCH_TOOL]},
            "resources/list": {"resources": [{
                "name": "OpenAPI", "uri": "nyankoface://wrong",
            }]},
        }
        if request["method"] == "tools/call":
            results["tools/call"] = {
                "content": [{"type": "text", "text": "fixture result"}],
                "isError": False,
            }
        result = results.get(request["method"])
        if result is None:
            self._send(503, {"jsonrpc": "2.0", "id": request["id"], "error": {
                "code": -32603, "message": "unexpected method",
            }})
            return
        self._send(200, {"jsonrpc": "2.0", "id": request["id"], "result": result})


class _GenericToolErrorFixture(_ProtocolFixture):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        if request["method"] == "notifications/initialized":
            self._send_empty(202)
            return
        if request["method"] != "tools/call":
            return super()._send(200, {"jsonrpc": "2.0", "id": request["id"], "result": {
                "initialize": {
                    "protocolVersion": "2025-06-18",
                    "serverInfo": {"name": "NyankoFace", "version": "0.1.0"},
                    "capabilities": VALID_CAPABILITIES,
                },
                "tools/list": {"tools": [VALID_SEARCH_TOOL]},
                "resources/list": {"resources": [VALID_OPENAPI_RESOURCE]},
            }[request["method"]]})
        self._send(200, {"jsonrpc": "2.0", "id": request["id"], "result": {
            "content": [{"type": "text", "text": "database unavailable"}],
            "isError": True,
        }})


class _EmptyContentFixture(_GenericToolErrorFixture):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        if request["method"] == "notifications/initialized":
            self._send_empty(202)
            return
        results = {
            "initialize": {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "NyankoFace", "version": "0.1.0"},
                "capabilities": VALID_CAPABILITIES,
            },
            "tools/list": {"tools": [VALID_SEARCH_TOOL]},
            "resources/list": {"resources": [VALID_OPENAPI_RESOURCE]},
        }
        if request["method"] in results:
            self._send(200, {
                "jsonrpc": "2.0", "id": request["id"],
                "result": results[request["method"]],
            })
            return
        self._send(200, {"jsonrpc": "2.0", "id": request["id"], "result": {
            "content": [{}],
            "isError": False,
        }})


class _MalformedCallResultFixture(_ProtocolFixture):
    mode = "error_flag"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        if request["method"] == "notifications/initialized":
            self._send_empty(202)
            return
        results = {
            "initialize": {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "NyankoFace", "version": "0.1.0"},
                "capabilities": VALID_CAPABILITIES,
            },
            "tools/list": {"tools": [VALID_SEARCH_TOOL]},
            "resources/list": {"resources": [VALID_OPENAPI_RESOURCE]},
        }
        if request["method"] == "tools/call":
            result = {
                "content": [{"type": "text", "text": "fixture result"}],
                "isError": False,
            }
            if self.mode == "error_flag":
                result["isError"] = "false"
            elif self.mode == "resource":
                result["content"] = [{
                    "type": "resource", "resource": {"uri": "nyankoface://empty"},
                }]
            elif self.mode in {"image", "audio"}:
                result["content"] = [{
                    "type": self.mode,
                    "data": "not-base64!!!",
                    "mimeType": f"{self.mode}/png",
                }]
            elif self.mode == "resource_link":
                result["content"] = [{
                    "type": "resource_link", "uri": "nyankoface://empty",
                }]
            else:
                result["content"] = [{
                    "type": "resource",
                    "resource": {"uri": "nyankoface://blob", "blob": "not-base64!!!"},
                }]
        else:
            result = results[request["method"]]
        self._send(200, {"jsonrpc": "2.0", "id": request["id"], "result": result})


def _run_fixture_process(tmp_path, token, *extra, handler=_ProtocolFixture):
    token_file = tmp_path / "credential.token"
    token_file.write_text(token, encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        completed = subprocess.run([
            sys.executable, str(RUNNER),
            "--url", f"http://127.0.0.1:{server.server_port}/mcp",
            "--token-file", str(token_file),
            "--client", "behavior-test",
            "--client-version", "1.0",
            *extra,
        ], text=True, capture_output=True, timeout=15, check=False)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert token not in completed.stdout
    assert token not in completed.stderr
    return completed


def _run_fixture_case(tmp_path, token, *extra):
    completed = _run_fixture_process(tmp_path, token, *extra)
    completed.check_returncode()
    return json.loads(completed.stdout)


def test_live_protocol_runner_executes_valid_read_without_leaking_token(tmp_path):
    summary = _run_fixture_case(tmp_path, "valid-secret")

    assert summary["initialize"] == {
        "content_type": "application/json",
        "instance": "fixture-a",
        "protocol": "2025-06-18",
        "server": {"name": "NyankoFace", "version": "0.1.0"},
        "status": 200,
    }
    assert summary["tools_list"]["count"] == 2
    assert summary["resources_list"]["count"] == 1
    assert summary["initialized_notification"] == {"body_bytes": 0, "status": 202}
    assert summary["representative_read"]["is_error"] is False


def test_live_protocol_runner_parses_complete_sse_data_events(tmp_path):
    completed = _run_fixture_process(
        tmp_path, "valid-secret", handler=_SseFixture,
    )
    completed.check_returncode()
    summary = json.loads(completed.stdout)

    assert summary["initialize"]["content_type"] == "text/event-stream"
    assert summary["tools_list"]["count"] == 2
    assert summary["resources_list"]["count"] == 1
    assert summary["initialized_notification"] == {"body_bytes": 0, "status": 202}
    assert summary["representative_read"]["is_error"] is False


def test_live_protocol_runner_rejects_unsupported_response_content_type(tmp_path):
    completed = _run_fixture_process(
        tmp_path, "valid-secret", handler=_UnsupportedContentTypeFixture,
    )

    assert completed.returncode != 0
    assert "unsupported Content-Type" in completed.stderr


def test_live_protocol_runner_executes_scope_denial_without_leaking_token(tmp_path):
    summary = _run_fixture_case(
        tmp_path, "scope-secret", "--expect-read-error",
    )

    assert summary["initialize"]["status"] == 200
    assert summary["representative_read"]["is_error"] is True
    assert "Missing required NyankoFace scope: catalog:read" in (
        summary["representative_read"]["error"]
    )


def test_live_protocol_runner_rejects_rpc_errors_missing_results_and_list_failures(tmp_path):
    for handler in (
        _JsonRpcErrorFixture,
        _MissingResultFixture,
        _ToolsListFailureFixture,
        _ResourcesListFailureFixture,
    ):
        completed = _run_fixture_process(tmp_path, "valid-secret", handler=handler)
        assert completed.returncode != 0


def test_live_protocol_runner_requires_the_openapi_resource_uri(tmp_path):
    completed = _run_fixture_process(
        tmp_path, "valid-secret", handler=_WrongOpenApiUriFixture,
    )

    assert completed.returncode != 0
    assert "did not advertise the OpenAPI resource" in completed.stderr


def test_live_protocol_runner_rejects_invalid_initialize_handshakes(tmp_path):
    cases = (
        (_EmptyInitializeFixture, "unsupported protocolVersion"),
        (_InvalidProtocolFixture, "unsupported protocolVersion"),
        (_InvalidServerInfoFixture, "invalid serverInfo.version"),
        (_MissingCapabilitiesFixture, "missing capabilities"),
    )
    for handler, expected_error in cases:
        completed = _run_fixture_process(tmp_path, "valid-secret", handler=handler)
        assert completed.returncode != 0
        assert expected_error in completed.stderr


def test_live_protocol_runner_requires_tool_and_resource_capabilities(tmp_path):
    for capability in ("tools", "resources"):
        _MissingCapabilityDeclarationFixture.missing_capability = capability
        completed = _run_fixture_process(
            tmp_path, "valid-secret", handler=_MissingCapabilityDeclarationFixture,
        )
        assert completed.returncode != 0
        assert f"missing {capability} capability" in completed.stderr


def test_live_protocol_runner_rejects_malformed_listing_fields(tmp_path):
    for handler, cases in (
        (_MalformedToolListingFixture, (
            ("name", "without a valid name"),
            ("inputSchema", "missing a valid inputSchema"),
        )),
        (_MalformedResourceListingFixture, (
            ("name", "without a valid name"),
            ("uri", "missing a valid uri"),
        )),
    ):
        for field, expected_error in cases:
            handler.malformed_field = field
            completed = _run_fixture_process(
                tmp_path, "valid-secret", handler=handler,
            )
            assert completed.returncode != 0
            assert expected_error in completed.stderr


def test_live_protocol_runner_rejects_malformed_jsonrpc_envelopes(tmp_path):
    for mode, expected_error in (
        ("jsonrpc", "invalid JSON-RPC version"),
        ("id", "unexpected JSON-RPC id"),
    ):
        _MalformedEnvelopeFixture.mode = mode
        completed = _run_fixture_process(
            tmp_path, "valid-secret", handler=_MalformedEnvelopeFixture,
        )
        assert completed.returncode != 0
        assert expected_error in completed.stderr


def test_live_protocol_runner_requires_protocol_version_after_initialize(tmp_path):
    _ProtocolHeaderFixture.request_count = 0
    _ProtocolHeaderFixture.methods = []
    completed = _run_fixture_process(
        tmp_path, "valid-secret", handler=_ProtocolHeaderFixture,
    )

    assert completed.returncode == 0
    assert _ProtocolHeaderFixture.methods == [
        "initialize", "notifications/initialized", "tools/list", "resources/list", "tools/call",
    ]


def test_live_protocol_runner_rejects_empty_capability_listings(tmp_path):
    completed = _run_fixture_process(
        tmp_path, "valid-secret", handler=_EmptyListingsFixture,
    )

    assert completed.returncode != 0
    assert "did not advertise search_catalog" in completed.stderr


def test_live_protocol_runner_rejects_cleartext_non_loopback_endpoints(tmp_path):
    token_file = tmp_path / "credential.token"
    token_file.write_text("cleartext-secret", encoding="utf-8")
    completed = subprocess.run([
        sys.executable, str(RUNNER),
        "--url", "http://example.test/mcp",
        "--token-file", str(token_file),
        "--client", "behavior-test",
        "--client-version", "1.0",
    ], text=True, capture_output=True, timeout=15, check=False)

    assert completed.returncode != 0
    assert "must use HTTPS" in completed.stderr
    assert "cleartext-secret" not in completed.stdout + completed.stderr


def test_live_protocol_runner_does_not_follow_redirects_with_bearer(tmp_path):
    target = ThreadingHTTPServer(("127.0.0.1", 0), _RedirectTargetFixture)
    target_thread = threading.Thread(target=target.serve_forever, daemon=True)
    target_thread.start()
    _RedirectTargetFixture.received_authorization = []
    _RedirectFixture.redirect_url = f"http://127.0.0.1:{target.server_port}/capture"
    try:
        completed = _run_fixture_process(
            tmp_path, "redirect-secret", handler=_RedirectFixture,
        )
    finally:
        target.shutdown()
        target.server_close()
        target_thread.join(timeout=5)

    assert completed.returncode != 0
    assert "refusing HTTP redirect status 302" in completed.stderr
    assert _RedirectTargetFixture.received_authorization == []


def test_live_protocol_runner_rejects_unrelated_tool_errors(tmp_path):
    completed = _run_fixture_process(
        tmp_path,
        "scope-secret",
        "--expect-read-error",
        handler=_GenericToolErrorFixture,
    )

    assert completed.returncode != 0
    assert "expected the specific missing catalog:read denial" in completed.stderr


def test_live_protocol_runner_rejects_unrelated_auth_envelopes(tmp_path):
    completed = _run_fixture_process(
        tmp_path,
        "invalid-secret",
        "--expected-initialize-status", "401",
        handler=_WrongAuthEnvelopeFixture,
    )

    assert completed.returncode != 0
    assert "expected error code" in completed.stderr


def test_live_protocol_runner_rejects_empty_content_blocks(tmp_path):
    completed = _run_fixture_process(
        tmp_path, "valid-secret", handler=_EmptyContentFixture,
    )

    assert completed.returncode != 0
    assert "unsupported content block" in completed.stderr


def test_live_protocol_runner_rejects_malformed_call_metadata(tmp_path):
    for mode, expected_error in (
        ("error_flag", "invalid isError flag"),
        ("resource", "empty embedded resource"),
        ("resource_blob", "invalid embedded resource blob"),
        ("image", "invalid image content"),
        ("audio", "invalid audio content"),
        ("resource_link", "invalid resource link content"),
    ):
        _MalformedCallResultFixture.mode = mode
        completed = _run_fixture_process(
            tmp_path, "valid-secret", handler=_MalformedCallResultFixture,
        )
        assert completed.returncode != 0
        assert expected_error in completed.stderr


def test_live_protocol_runner_rejects_boolean_sse_request_ids(tmp_path):
    completed = _run_fixture_process(
        tmp_path, "valid-secret", handler=_BooleanIdSseFixture,
    )

    assert completed.returncode != 0
    assert "did not contain a JSON-RPC response for request id 1" in completed.stderr


def test_live_protocol_runner_executes_lifecycle_rejections_without_leaking_token(tmp_path):
    for token in ("invalid-secret", "expired-secret", "revoked-secret"):
        summary = _run_fixture_case(
            tmp_path, token, "--expected-initialize-status", "401",
        )
        assert summary["initialize"]["status"] == 401
        assert summary["auth_rejected"] is True


def test_live_protocol_runner_accepts_oauth_authentication_rejections(tmp_path):
    completed = _run_fixture_process(
        tmp_path,
        "invalid-secret",
        "--expected-initialize-status", "401",
        handler=_OAuthAuthFailureFixture,
    )
    completed.check_returncode()
    summary = json.loads(completed.stdout)
    assert summary["initialize"]["status"] == 401
    assert summary["auth_rejected"] is True


def test_live_protocol_runner_rejects_boolean_authentication_ids(tmp_path):
    completed = _run_fixture_process(
        tmp_path,
        "invalid-secret",
        "--expected-initialize-status", "401",
        handler=_BooleanAuthIdFixture,
    )

    assert completed.returncode != 0
    assert "unexpected JSON-RPC id" in completed.stderr


def test_live_client_evidence_records_server_identity_and_protocol_matrix():
    if not EVIDENCE.exists():
        return
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    deployment = matrix["deployment"]

    assert re.fullmatch(r"[0-9a-f]{40}", deployment["repository_git_sha"])
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", deployment["image_digest"])
    assert deployment["server_info"] == {"name": "NyankoFace", "version": "1.26.0"}
    assert deployment["replicas"] == 2
    assert deployment["replicas_use_same_digest"] is True
    assert deployment["image_revision_label"] == "unknown"
    follow_up = matrix["protocol_cli_follow_up"]
    assert follow_up["execution"].startswith("CLI-only Streamable HTTP checks")
    assert follow_up["client_identities"] == ["Codex CLI", "Claude Desktop", "VS Code"]
    assert follow_up["states_per_client"] == 5
    assert follow_up["valid_handshake"] == {
        "initialize_status": 200,
        "initialized_notification_status": 202,
        "initialized_notification_body_bytes": 0,
        "tools_list_status": 200,
        "resources_list_status": 200,
        "representative_read_status": 200,
    }
    assert follow_up["secret_exposed"] is False
    assert matrix["protocol_auth_matrix"] == {
        "client_identities": 3,
        "states_per_client": 5,
        "valid": "passed",
        "insufficient_scope": "tool denied for missing catalog:read",
        "expired": 401,
        "revoked": 401,
        "invalid": 401,
        "secret_exposed": False,
    }
    assert matrix["cleanup"]["fresh_tokens_issued"] == 13
    assert matrix["cleanup"]["fresh_tokens_revoked"] == 13
    assert matrix["cleanup"]["fresh_tokens_active_after_cleanup"] == 0
    assert matrix["cleanup"]["claude_configuration_restored_byte_for_byte"] is True
    isolation = matrix["instance_switch"]
    assert re.fullmatch(r"[0-9a-f]{64}", isolation["config_fingerprint_sha256"])
    assert isolation["client_reconfiguration"] is False
    assert isolation["sticky_session"] is False
    assert isolation["session_headers"] == []
    assert {phase["phase"] for phase in isolation["phases"]} == {
        "replica_1_only", "replica_2_only",
    }
    assert all(phase["other_backend_stopped"] is True for phase in isolation["phases"])
    assert all(phase["representative_read"] == "passed" for phase in isolation["phases"])
    assert all(
        phase["initialized_notification_status"] == 202
        and phase["initialized_notification_body_bytes"] == 0
        and phase["restored_healthy"] is True
        for phase in isolation["phases"]
    )


def test_sanitized_transcripts_separate_native_and_protocol_coverage():
    if not EVIDENCE.exists():
        return
    source = TRANSCRIPTS.read_text(encoding="utf-8")
    records = [json.loads(line) for line in source.splitlines() if line]
    states = {"valid", "insufficient_scope", "expired", "revoked", "invalid"}

    for client in ("Codex CLI", "Claude Desktop", "VS Code"):
        protocol = {
            item["state"] for item in records
            if item["client"] == client and item["evidence_layer"] == "protocol"
        }
        assert protocol == states
    protocol_records = [item for item in records if item["evidence_layer"] == "protocol"]
    assert all(
        item["initialized_notification_status"] == 202
        and item["initialized_notification_body_bytes"] == 0
        for item in protocol_records
        if item["state"] in {"valid", "insufficient_scope"}
    )
    assert all(item["secret_exposed"] is False for item in records)
    assert not re.search(r"(?i)bearer\s+[a-z0-9._~-]+", source)
    assert "C:\\Users\\" not in source
    assert "/opt/nyankoface/secrets" not in source

    native = {
        (item["client"], item["state"]): item
        for item in records if item["evidence_layer"] == "native"
    }
    assert native[("Codex CLI", "valid")]["outcome"] == "passed"
    assert native[("Codex CLI", "valid")]["tools_discovered"] == 26
    assert native[("Codex CLI", "valid")]["resources_discovered"] == 1
    assert native[("Codex CLI", "valid")]["resource_templates_discovered"] == 9
    assert native[("Codex CLI", "insufficient_scope")]["outcome"] == "passed"
    assert native[("Codex CLI", "invalid")]["outcome"] == "passed"
    assert native[("Claude Desktop", "valid")]["outcome"] == "restored"
    assert native[("Claude Desktop", "valid")]["representative_read"].startswith("pending")
    assert (
        native[("VS Code", "insufficient_scope")]["outcome"]
        == "passed_for_init_and_tool_discovery"
    )
    assert native[("VS Code", "invalid")]["outcome"] == "passed"

    isolation = [item for item in records if item["evidence_layer"] == "protocol_isolation"]
    assert {item["phase"] for item in isolation} == {"replica_1_only", "replica_2_only"}
    assert len({item["config_fingerprint_sha256"] for item in isolation}) == 1
    assert all(item["other_backend_stopped"] is True for item in isolation)
    assert all(item["operation_instance"] == item["container_id"][:12] for item in isolation)
    assert all(
        item["initialized_notification_status"] == 202
        and item["initialized_notification_body_bytes"] == 0
        and item["restored_healthy"] is True
        for item in isolation
    )


def test_raw_artifact_manifest_is_path_free_and_hash_bound():
    if not EVIDENCE.exists():
        return
    source = RAW_MANIFEST.read_text(encoding="utf-8")
    manifest = json.loads(source)

    assert manifest["storage"] == "git_outside_root_restricted_snapshot"
    assert manifest["known_token_scan"] == "passed"
    assert manifest["known_token_candidates"] == 22
    assert manifest["artifacts_scanned"] == 13
    assert len(manifest["artifacts"]) == 13
    follow_up = next(
        item for item in manifest["artifacts"] if item["id"] == "cli-protocol-follow-up"
    )
    assert follow_up["bytes"] == 4841
    assert follow_up["sha256"] == "4d888e60f102631db33a96e7cca68fee3815eb3b6515e999e889d48bdfc66e17"
    replica_1 = next(item for item in manifest["artifacts"] if item["id"] == "ha-replica-1-only")
    replica_2 = next(item for item in manifest["artifacts"] if item["id"] == "ha-replica-2-only")
    assert (replica_1["bytes"], replica_1["sha256"]) == (
        868, "8c07554591a432393a40ce0debbcfbb061b3418a2af18caffe3f9ac556acf628",
    )
    assert (replica_2["bytes"], replica_2["sha256"]) == (
        868, "322bf1dd0fe3a223f1dd5e983619c9cb362098d57cb465a77bf36326d076ad10",
    )
    assert manifest["scan_result"]["exact_raw_token_hits"] == 0
    assert manifest["scan_result"]["exact_tracked_worktree_token_hits"] == 0
    assert manifest["scan_result"]["high_confidence_secret_pattern_hits"] == 0
    assert "C:\\Users\\" not in source
    assert "/opt/nyankoface/secrets" not in source
    for artifact in manifest["artifacts"]:
        assert artifact["bytes"] > 0
        assert re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])
        assert artifact["source"]
        assert artifact["client"] in {
            "Codex CLI", "Claude Desktop", "VS Code", "Protocol QA",
            "Codex CLI, Claude Desktop identity, VS Code identity",
        }


def test_evidence_summary_timestamps_follow_all_sanitized_captures():
    if not EVIDENCE.exists():
        return
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    manifest = json.loads(RAW_MANIFEST.read_text(encoding="utf-8"))
    records = [
        json.loads(line) for line in TRANSCRIPTS.read_text(encoding="utf-8").splitlines()
        if line
    ]
    latest_capture = max(datetime.fromisoformat(item["captured_at"]) for item in records)

    assert datetime.fromisoformat(matrix["executed_at"]) >= latest_capture
    assert datetime.fromisoformat(manifest["captured_at"]) >= latest_capture


def test_both_live_client_guides_include_results_and_raw_evidence_procedure():
    english = GUIDE_EN.read_text(encoding="utf-8")
    japanese = GUIDE_JA.read_text(encoding="utf-8")

    for source in (english, japanese):
        assert "protocol" in source.lower() or "protocol" in source
        assert "credential" in source.lower() or "credential" in source
        assert "private" in source.lower() or "非公開" in source
    assert "公開範囲" in japanese


def test_live_client_guides_link_to_the_published_vscode_example():
    published_example = (
        "https://github.com/Sunwood-ai-labs/NyankoFace/blob/main/"
        "nyankoface-mcp/examples/vscode-mcp.json"
    )
    for guide in (GUIDE_EN, GUIDE_JA):
        source = guide.read_text(encoding="utf-8")
        assert published_example in source
        assert "../../nyankoface-mcp/examples/vscode-mcp.json" not in source
        assert "../../../nyankoface-mcp/examples/vscode-mcp.json" not in source
