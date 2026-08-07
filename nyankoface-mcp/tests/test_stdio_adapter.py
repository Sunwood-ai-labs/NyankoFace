from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from io import BytesIO
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from nyankoface_mcp.stdio import (
    MAX_CONCURRENT_FORWARDING,
    MAX_MESSAGE_BYTES,
    MAX_ORDINARY_FORWARDING,
    MAX_QUEUED_FORWARDING,
    MAX_REMOTE_RESPONSE_BYTES,
    ConfigurationError,
    StdioSettings,
    _ActiveDispatch,
    _wait_for_request_dispatch,
    run_stdio,
)


TOKEN = "ofmcp_test_secret_never_emit_0123456789"


@pytest.mark.asyncio
async def test_dispatch_wait_prefers_finished_when_both_events_are_ready():
    dispatch = _ActiveDispatch(
        request_dispatched=asyncio.Event(),
        finished=asyncio.Event(),
    )
    dispatch.request_dispatched.set()
    dispatch.finished.set()

    assert await _wait_for_request_dispatch(dispatch) is False


class RemoteMcpHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []
    cancellation_received = threading.Event()
    concurrency_lock = threading.Lock()
    active_requests = 0
    maximum_active_requests = 0
    sse_intermediate_received = threading.Event()
    sse_intermediate_observed = False
    server_response_received = threading.Event()

    def log_message(self, _format, *_args):
        return

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        payload = json.loads(self.rfile.read(length))
        self.__class__.requests.append({"headers": dict(self.headers), "payload": payload})
        request_id = payload.get("id")
        method = payload.get("method")
        if method is None and (
            request_id == "server-response"
            or request_id == "initialize-ping"
            or request_id == "empty-server-response"
            or request_id == "release-barrier"
            or str(request_id).startswith("slow-server-response-")
            or str(request_id).startswith("blocked-server-response-")
        ):
            if request_id == "empty-server-response":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if request_id == "release-barrier":
                self.__class__.server_response_received.set()
            if request_id in {"server-response", "initialize-ping"}:
                self.__class__.server_response_received.set()
            elif str(request_id).startswith("blocked-server-response-"):
                self.__class__.cancellation_received.wait(timeout=2)
            else:
                time.sleep(0.02)
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if method == "notifications/cancelled":
            if payload.get("params", {}).get("reason") == "block control queue":
                self.__class__.server_response_received.wait(timeout=2)
            self.__class__.cancellation_received.set()
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if method == "accepted_without_response":
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if method == "empty_json_response":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if method == "no_content_response":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if method == "null_json_response":
            body = b"null"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if method == "empty_sse_response":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if method == "invalid_content_type_response":
            body = b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if method == "http_error_response":
            self.send_response(503)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if method in {
            "mismatched_json_response",
            "notification_only_json_response",
            "ambiguous_json_response",
        }:
            if method == "mismatched_json_response":
                response_payload = {
                    "jsonrpc": "2.0",
                    "id": "another-request",
                    "result": {},
                }
            elif method == "notification_only_json_response":
                response_payload = {
                    "jsonrpc": "2.0",
                    "method": "notifications/progress",
                    "params": {"progress": 1},
                }
            else:
                response_payload = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {},
                    "error": {"code": -32000, "message": "ambiguous"},
                }
            body = json.dumps(response_payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if method == "resources/read" and payload.get("params", {}).get("uri") == "nyankoface://sse":
            events = [
                {"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progress": 0.5}},
                {"jsonrpc": "2.0", "id": request_id, "result": {
                    "contents": [{"uri": "nyankoface://sse", "text": "complete"}],
                }},
            ]
            body = "".join(f"data: {json.dumps(event)}\n\n" for event in events).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if method == "resources/read" and payload.get("params", {}).get("uri") in {
            "nyankoface://progress-only-sse",
            "nyankoface://mismatched-terminal-sse",
            "nyankoface://duplicate-terminal-sse",
        }:
            uri = payload["params"]["uri"]
            progress = {
                "jsonrpc": "2.0",
                "method": "notifications/progress",
                "params": {"progress": 0.5},
            }
            events = [progress]
            if uri == "nyankoface://mismatched-terminal-sse":
                events.append({
                    "jsonrpc": "2.0",
                    "id": "another-request",
                    "result": {"contents": []},
                })
            elif uri == "nyankoface://duplicate-terminal-sse":
                terminal = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"contents": []},
                }
                events.extend([terminal, terminal])
            body = "".join(
                f"data: {json.dumps(event)}\n\n" for event in events
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if method == "resources/read" and payload.get("params", {}).get("uri") == "nyankoface://delayed-sse":
            progress = json.dumps({
                "jsonrpc": "2.0",
                "method": "notifications/progress",
                "params": {"progress": 0.25},
            }).encode()
            final = json.dumps({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"contents": [{"uri": "nyankoface://delayed-sse", "text": "done"}]},
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"data: " + progress + b"\r\r")
            self.wfile.flush()
            self.__class__.sse_intermediate_observed = (
                self.__class__.sse_intermediate_received.wait(timeout=1)
            )
            self.wfile.write(b"data: " + final + b"\r\r")
            self.wfile.flush()
            return
        if method == "initialize" and payload.get("params", {}).get("clientInfo", {}).get("name") == "initialize-sse":
            progress = json.dumps({
                "jsonrpc": "2.0",
                "method": "notifications/progress",
                "params": {"progress": 0.25},
            }).encode()
            final = json.dumps({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "serverInfo": {"name": "NyankoFace", "version": "0.1.0"},
                },
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"data: " + progress + b"\n\n")
            self.wfile.flush()
            self.__class__.sse_intermediate_observed = (
                self.__class__.sse_intermediate_received.wait(timeout=1)
            )
            self.wfile.write(b"data: " + final + b"\n\n")
            self.wfile.flush()
            return
        if method == "initialize" and payload.get("params", {}).get("clientInfo", {}).get("name") == "initialize-server-request":
            server_request = json.dumps({
                "jsonrpc": "2.0",
                "id": "initialize-ping",
                "method": "ping",
                "params": {},
            }).encode()
            final = json.dumps({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "serverInfo": {"name": "NyankoFace", "version": "0.1.0"},
                },
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"data: " + server_request + b"\n\n")
            self.wfile.flush()
            if not self.__class__.server_response_received.wait(timeout=2):
                return
            self.wfile.write(b"data: " + final + b"\n\n")
            self.wfile.flush()
            return
        if method == "initialize" and payload.get("params", {}).get("clientInfo", {}).get("name") == "initialize-cancel":
            final = json.dumps({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "serverInfo": {"name": "NyankoFace", "version": "0.1.0"},
                },
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.__class__.cancellation_received.wait(timeout=2)
            try:
                self.wfile.write(b"data: " + final + b"\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                pass
            return
        if method == "initialize":
            client_name = payload.get("params", {}).get("clientInfo", {}).get("name")
            client_versions = {
                "initialize-invalid-version": "latest",
                "initialize-wrong-type-version": 20250618,
                "initialize-invalid-month": "2025-99-99",
                "initialize-fullwidth-version": "２０２５-０６-１８",
                "initialize-invalid-leap-day": "2025-02-29",
                "initialize-invalid-day": "2025-04-31",
                "initialize-valid-leap-day": "2024-02-29",
                "initialize-valid-year-end": "2025-12-31",
            }
            result = {
                "protocolVersion": client_versions.get(client_name, "2025-06-18"),
                "capabilities": {"tools": {"listChanged": False}, "resources": {}},
                "serverInfo": {"name": "NyankoFace", "version": "0.1.0"},
            }
            if client_name == "initialize-missing-version":
                result.pop("protocolVersion")
        elif method == "tools/list":
            result = {"tools": [{"name": "search_catalog", "inputSchema": {"type": "object"}}]}
        elif method == "tools/call":
            tool_name = payload.get("params", {}).get("name")
            if tool_name == "slow_tool":
                result = {"cancelReceived": self.__class__.cancellation_received.wait(timeout=2)}
            elif tool_name == "wait_for_server_response":
                result = {
                    "responseReceived": self.__class__.server_response_received.wait(timeout=2)
                }
            elif tool_name == "delay_tool":
                time.sleep(0.15)
                result = {"delayed": True}
            elif tool_name == "barrier_tool":
                result = {
                    "released": self.__class__.server_response_received.wait(timeout=10)
                }
            elif tool_name == "oversized_response":
                body = b"x" * (MAX_REMOTE_RESPONSE_BYTES + 1)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            elif tool_name == "encoded_response":
                body = b"not-read-as-compressed-content"
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            elif tool_name == "bounded_tool":
                with self.__class__.concurrency_lock:
                    self.__class__.active_requests += 1
                    self.__class__.maximum_active_requests = max(
                        self.__class__.maximum_active_requests,
                        self.__class__.active_requests,
                    )
                try:
                    time.sleep(0.05)
                    result = {"bounded": True}
                finally:
                    with self.__class__.concurrency_lock:
                        self.__class__.active_requests -= 1
            else:
                result = {
                    "content": [{"type": "text", "text": f'{{"items":[],"echo":"{TOKEN}"}}'}],
                    "isError": False,
                    TOKEN: "credential-shaped response key",
                }
        else:
            result = {"contents": [{"uri": "nyankoface://catalog/model", "text": '{"items":[]}'}]}
        body = json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Mcp-Session-Id", "must-not-be-forwarded")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass


@pytest.fixture
def remote_endpoint():
    RemoteMcpHandler.requests = []
    RemoteMcpHandler.cancellation_received.clear()
    RemoteMcpHandler.active_requests = 0
    RemoteMcpHandler.maximum_active_requests = 0
    RemoteMcpHandler.sse_intermediate_received.clear()
    RemoteMcpHandler.sse_intermediate_observed = False
    RemoteMcpHandler.server_response_received.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), RemoteMcpHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/mcp"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def _run_adapter(
    endpoint: str,
    messages: list[dict],
    env_overrides: dict[str, str | None] | None = None,
):
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(__import__("pathlib").Path(__file__).parents[1]),
        "NYANKOFACE_MCP_REMOTE_URL": endpoint,
        "NYANKOFACE_MCP_TOKEN": TOKEN,
    })
    for name, value in (env_overrides or {}).items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    command = [sys.executable, "-m", "nyankoface_mcp", "stdio"]
    process = subprocess.run(
        command,
        input="".join(json.dumps(message) + "\n" for message in messages),
        text=True,
        capture_output=True,
        env=env,
        timeout=15,
        check=False,
    )
    responses = [json.loads(line) for line in process.stdout.splitlines()]
    return command, process, responses


def test_stdio_ignores_environment_proxy_for_bearer_transport(remote_endpoint):
    _, process, responses = _run_adapter(
        remote_endpoint,
        [{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}],
        {
            "HTTP_PROXY": "http://127.0.0.1:1",
            "HTTPS_PROXY": "http://127.0.0.1:1",
            "ALL_PROXY": "http://127.0.0.1:1",
            "http_proxy": "http://127.0.0.1:1",
            "https_proxy": "http://127.0.0.1:1",
            "all_proxy": "http://127.0.0.1:1",
            "NO_PROXY": None,
            "no_proxy": None,
        },
    )
    assert process.returncode == 0
    assert responses[0]["id"] == 1
    assert responses[0]["result"]["tools"][0]["name"] == "search_catalog"
    assert RemoteMcpHandler.requests[-1]["headers"]["Authorization"] == f"Bearer {TOKEN}"


def test_stdio_initialize_tool_and_resource_e2e_is_stateless_and_secret_safe(remote_endpoint):
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "stdio-contract", "version": "1"},
        }},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "search_catalog", "arguments": {"kind": "model"},
        }},
        {"jsonrpc": "2.0", "id": 4, "method": "resources/read", "params": {
            "uri": "nyankoface://catalog/model",
        }},
    ]
    command, process, responses = _run_adapter(remote_endpoint, messages)
    by_id = {response.get("id"): response for response in responses}
    assert process.returncode == 0
    assert by_id[1]["result"]["capabilities"].keys() == {"tools", "resources"}
    assert by_id[2]["result"]["tools"][0]["name"] == "search_catalog"
    assert by_id[3]["result"]["isError"] is False
    assert "[REDACTED]" in by_id[3]["result"]["content"][0]["text"]
    assert by_id[3]["result"]["[REDACTED]"] == "credential-shaped response key"
    assert by_id[4]["result"]["contents"][0]["uri"] == "nyankoface://catalog/model"
    assert TOKEN not in " ".join(command)
    assert TOKEN not in process.stdout
    assert TOKEN not in process.stderr
    assert len(RemoteMcpHandler.requests) == 4
    for index, request in enumerate(RemoteMcpHandler.requests):
        assert request["headers"]["Authorization"] == f"Bearer {TOKEN}"
        assert request["headers"]["Accept-Encoding"] == "identity"
        if index == 0:
            assert "MCP-Protocol-Version" not in request["headers"]
        else:
            assert request["headers"]["MCP-Protocol-Version"] == "2025-06-18"
            assert "Mcp-Session-Id" not in request["headers"]


def test_stdio_preserves_separate_sse_events(remote_endpoint):
    _, process, responses = _run_adapter(remote_endpoint, [
        {"jsonrpc": "2.0", "id": 7, "method": "resources/read", "params": {
            "uri": "nyankoface://sse",
        }},
    ])
    assert process.returncode == 0
    assert responses == [
        {"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progress": 0.5}},
        {"jsonrpc": "2.0", "id": 7, "result": {
            "contents": [{"uri": "nyankoface://sse", "text": "complete"}],
        }},
    ]


@pytest.mark.parametrize(
    ("uri", "emits_progress"),
    [
        ("nyankoface://progress-only-sse", True),
        ("nyankoface://mismatched-terminal-sse", True),
        ("nyankoface://duplicate-terminal-sse", True),
    ],
)
def test_stdio_requires_one_matching_terminal_sse_response(
    remote_endpoint,
    uri,
    emits_progress,
):
    _, process, responses = _run_adapter(remote_endpoint, [{
        "jsonrpc": "2.0",
        "id": 75,
        "method": "resources/read",
        "params": {"uri": uri},
    }])
    assert process.returncode == 0
    errors = [response for response in responses if "error" in response]
    progress = [response for response in responses if response.get("method") == "notifications/progress"]
    assert len(errors) == 1
    assert errors[0]["id"] == 75
    assert errors[0]["error"]["code"] == -32000
    assert bool(progress) is emits_progress
    assert not any("result" in response for response in responses)


def test_stdio_rejects_encoded_remote_response_before_decoding(remote_endpoint):
    _, process, responses = _run_adapter(remote_endpoint, [
        {"jsonrpc": "2.0", "id": 71, "method": "tools/call", "params": {
            "name": "encoded_response", "arguments": {},
        }},
    ])
    assert process.returncode == 0
    assert responses == [{
        "jsonrpc": "2.0",
        "id": 71,
        "error": {
            "code": -32000,
            "message": "NyankoFace MCP endpoint is unavailable or returned an invalid response",
        },
    }]


@pytest.mark.parametrize("method", [
    "accepted_without_response",
    "empty_json_response",
    "no_content_response",
    "null_json_response",
    "empty_sse_response",
    "invalid_content_type_response",
])
def test_stdio_terminates_response_required_request_on_invalid_remote_response(
    remote_endpoint,
    method,
):
    _, process, responses = _run_adapter(remote_endpoint, [
        {
            "jsonrpc": "2.0",
            "id": 72,
            "method": method,
            "params": {},
        },
    ])
    assert process.returncode == 0
    assert len(responses) == 1
    assert responses[0]["jsonrpc"] == "2.0"
    assert responses[0]["id"] == 72
    assert responses[0]["error"]["code"] == -32000
    assert TOKEN not in responses[0]["error"]["message"]


def test_stdio_terminates_request_on_http_status_error(remote_endpoint):
    _, process, responses = _run_adapter(remote_endpoint, [{
        "jsonrpc": "2.0",
        "id": 73,
        "method": "http_error_response",
        "params": {},
    }])
    assert process.returncode == 0
    assert responses == [{
        "jsonrpc": "2.0",
        "id": 73,
        "error": {
            "code": -32001,
            "message": "NyankoFace MCP endpoint returned HTTP 503",
        },
    }]


@pytest.mark.parametrize("method", [
    "mismatched_json_response",
    "notification_only_json_response",
    "ambiguous_json_response",
])
def test_stdio_requires_matching_terminal_json_response(remote_endpoint, method):
    _, process, responses = _run_adapter(remote_endpoint, [{
        "jsonrpc": "2.0",
        "id": 76,
        "method": method,
        "params": {},
    }])
    assert process.returncode == 0
    assert len(responses) == 1
    assert responses[0]["id"] == 76
    assert responses[0]["error"]["code"] == -32000


def test_stdio_terminates_request_on_transport_error():
    _, process, responses = _run_adapter("http://127.0.0.1:1/mcp", [{
        "jsonrpc": "2.0",
        "id": 74,
        "method": "tools/list",
        "params": {},
    }])
    assert process.returncode == 0
    assert responses == [{
        "jsonrpc": "2.0",
        "id": 74,
        "error": {
            "code": -32000,
            "message": "NyankoFace MCP endpoint is unavailable or returned an invalid response",
        },
    }]


def test_stdio_allows_empty_success_for_jsonrpc_response(remote_endpoint):
    _, process, responses = _run_adapter(remote_endpoint, [{
        "jsonrpc": "2.0",
        "id": "empty-server-response",
        "result": {},
    }])
    assert process.returncode == 0
    assert responses == []


@pytest.mark.asyncio
async def test_stdio_emits_sse_event_before_remote_stream_eof(remote_endpoint):
    class SignalingOutput(BytesIO):
        def write(self, data):
            written = super().write(data)
            RemoteMcpHandler.sse_intermediate_received.set()
            return written

    request = json.dumps({
        "jsonrpc": "2.0",
        "id": 70,
        "method": "resources/read",
        "params": {"uri": "nyankoface://delayed-sse"},
    }).encode("utf-8") + b"\n"
    output = SignalingOutput()
    await run_stdio(
        StdioSettings(remote_url=remote_endpoint, token=TOKEN),
        stdin=BytesIO(request),
        stdout=output,
    )
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert RemoteMcpHandler.sse_intermediate_observed is True
    assert responses == [
        {"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progress": 0.25}},
        {"jsonrpc": "2.0", "id": 70, "result": {
            "contents": [{"uri": "nyankoface://delayed-sse", "text": "done"}],
        }},
    ]


@pytest.mark.asyncio
async def test_stdio_streams_initialize_sse_notification_before_terminal(remote_endpoint):
    class SignalingOutput(BytesIO):
        def write(self, data):
            written = super().write(data)
            if b'"method":"notifications/progress"' in data:
                RemoteMcpHandler.sse_intermediate_received.set()
            return written

    request = json.dumps({
        "jsonrpc": "2.0",
        "id": 71,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "initialize-sse", "version": "1"},
        },
    }).encode("utf-8") + b"\n"
    output = SignalingOutput()
    await run_stdio(
        StdioSettings(remote_url=remote_endpoint, token=TOKEN),
        stdin=BytesIO(request),
        stdout=output,
    )
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert RemoteMcpHandler.sse_intermediate_observed is True
    assert responses == [
        {"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progress": 0.25}},
        {"jsonrpc": "2.0", "id": 71, "result": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "serverInfo": {"name": "NyankoFace", "version": "0.1.0"},
        }},
    ]


@pytest.mark.asyncio
async def test_stdio_demuxes_server_response_while_initialize_sse_is_open(remote_endpoint):
    records = [
        {
            "jsonrpc": "2.0",
            "id": 72,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "initialize-server-request", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "id": "initialize-ping", "result": {}},
    ]
    request = b"".join(
        json.dumps(record).encode("utf-8") + b"\n" for record in records
    )
    output = BytesIO()
    await run_stdio(
        StdioSettings(remote_url=remote_endpoint, token=TOKEN),
        stdin=BytesIO(request),
        stdout=output,
    )
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert RemoteMcpHandler.server_response_received.is_set()
    assert responses == [
        {
            "jsonrpc": "2.0",
            "id": "initialize-ping",
            "method": "ping",
            "params": {},
        },
        {
            "jsonrpc": "2.0",
            "id": 72,
            "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "serverInfo": {"name": "NyankoFace", "version": "0.1.0"},
            },
        },
    ]


def test_stdio_cancels_initialize_and_suppresses_late_terminal(remote_endpoint):
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 73,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "initialize-cancel", "version": "1"},
            },
        },
        {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": 73, "reason": "client stopped initialization"},
        },
        {"jsonrpc": "2.0", "id": 74, "method": "tools/list", "params": {}},
    ]
    _, process, responses = _run_adapter(remote_endpoint, messages)
    assert process.returncode == 0
    assert RemoteMcpHandler.cancellation_received.is_set()
    assert all(response.get("id") != 73 for response in responses)
    assert responses == [{
        "jsonrpc": "2.0",
        "id": 74,
        "error": {"code": -32000, "message": "MCP initialization did not complete"},
    }]
    assert all(
        request["payload"].get("method") != "tools/list"
        for request in RemoteMcpHandler.requests
    )
    methods = [request["payload"]["method"] for request in RemoteMcpHandler.requests]
    assert methods.count("initialize") == 1
    assert methods.count("notifications/cancelled") == 1


@pytest.mark.parametrize(
    "client_name",
    [
        "initialize-missing-version",
        "initialize-wrong-type-version",
        "initialize-invalid-version",
        "initialize-invalid-month",
        "initialize-fullwidth-version",
        "initialize-invalid-leap-day",
        "initialize-invalid-day",
    ],
)
def test_stdio_rejects_invalid_initialize_result_before_ordinary_work(
    remote_endpoint,
    client_name,
):
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 75,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": client_name, "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "id": 76, "method": "tools/list", "params": {}},
    ]
    _, process, responses = _run_adapter(remote_endpoint, messages)
    assert process.returncode == 0
    assert responses == [
        {
            "jsonrpc": "2.0",
            "id": 75,
            "error": {
                "code": -32000,
                "message": "NyankoFace MCP endpoint returned an invalid initialize response",
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 76,
            "error": {"code": -32000, "message": "MCP initialization did not complete"},
        },
    ]
    assert all(
        request["payload"].get("method") != "tools/list"
        for request in RemoteMcpHandler.requests
    )


@pytest.mark.parametrize(
    ("client_name", "expected_version"),
    [
        ("initialize-valid-leap-day", "2024-02-29"),
        ("initialize-valid-year-end", "2025-12-31"),
    ],
)
def test_stdio_accepts_ascii_calendar_protocol_version_boundaries(
    remote_endpoint,
    client_name,
    expected_version,
):
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 77,
            "method": "initialize",
            "params": {
                "protocolVersion": expected_version,
                "capabilities": {},
                "clientInfo": {"name": client_name, "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "id": 78, "method": "tools/list", "params": {}},
    ]
    _, process, responses = _run_adapter(remote_endpoint, messages)
    assert process.returncode == 0
    assert [response["id"] for response in responses] == [77, 78]
    assert responses[0]["result"]["protocolVersion"] == expected_version
    assert responses[1]["result"]["tools"][0]["name"] == "search_catalog"
    assert RemoteMcpHandler.requests[-1]["headers"]["MCP-Protocol-Version"] == expected_version


def test_stdio_routes_jsonrpc_response_through_control_worker(remote_endpoint):
    messages = [
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": "wait_for_server_response", "arguments": {}},
        }
        for request_id in range(600, 600 + MAX_ORDINARY_FORWARDING)
    ]
    messages.append({"jsonrpc": "2.0", "id": "server-response", "result": {}})
    _, process, responses = _run_adapter(remote_endpoint, messages)
    assert process.returncode == 0
    assert len(responses) == MAX_ORDINARY_FORWARDING
    assert all(response["result"]["responseReceived"] is True for response in responses)
    assert RemoteMcpHandler.server_response_received.is_set()


def test_stdio_never_drops_jsonrpc_responses_when_response_queue_fills(
    remote_endpoint,
):
    messages = [
        {
            "jsonrpc": "2.0",
            "id": f"slow-server-response-{request_id}",
            "result": {"accepted": True},
        }
        for request_id in range(MAX_QUEUED_FORWARDING + 1)
    ]
    _, process, responses = _run_adapter(remote_endpoint, messages)
    assert process.returncode == 0
    assert responses == []
    forwarded_ids = {
        request["payload"].get("id") for request in RemoteMcpHandler.requests
    }
    assert forwarded_ids == {message["id"] for message in messages}


def test_stdio_fails_fast_when_response_capacity_is_exceeded(remote_endpoint):
    messages = [
        {
            "jsonrpc": "2.0",
            "id": f"blocked-server-response-{request_id}",
            "result": {"accepted": True},
        }
        for request_id in range(MAX_QUEUED_FORWARDING + 20)
    ]
    _, process, responses = _run_adapter(remote_endpoint, messages)
    assert process.returncode != 0
    assert responses == []
    assert "stdio adapter stopped unexpectedly" in process.stderr


def test_response_backpressure_does_not_block_later_cancellation(remote_endpoint):
    response_messages = [
        {
            "jsonrpc": "2.0",
            "id": f"blocked-server-response-{request_id}",
            "result": {"accepted": True},
        }
        for request_id in range(MAX_QUEUED_FORWARDING + 1)
    ]
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 710,
            "method": "tools/call",
            "params": {"name": "slow_tool", "arguments": {}},
        },
        *response_messages,
        {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": 710, "reason": "response backpressure test"},
        },
    ]
    _, process, responses = _run_adapter(remote_endpoint, messages)
    assert process.returncode == 0
    assert responses == []
    assert RemoteMcpHandler.cancellation_received.is_set()
    forwarded_ids = {
        request["payload"].get("id") for request in RemoteMcpHandler.requests
    }
    assert {message["id"] for message in response_messages} <= forwarded_ids


def test_stdio_forwards_cancellation_while_tool_call_is_pending(remote_endpoint):
    for request_id in range(8, 28):
        RemoteMcpHandler.requests = []
        RemoteMcpHandler.cancellation_received.clear()
        _, process, responses = _run_adapter(remote_endpoint, [
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": "slow_tool", "arguments": {}},
            },
            {
                "jsonrpc": "2.0",
                "method": "notifications/cancelled",
                "params": {"requestId": request_id, "reason": "contract test"},
            },
        ])
        assert process.returncode == 0
        assert responses == []
        methods = [
            request["payload"]["method"] for request in RemoteMcpHandler.requests
        ]
        assert methods.count("tools/call") == 1
        assert methods.count("notifications/cancelled") == 1


@pytest.mark.parametrize("request_method", ["initialize", "tools/call"])
@pytest.mark.asyncio
async def test_cancellation_waits_for_controlled_request_dispatch(
    monkeypatch,
    request_method,
):
    loop = asyncio.get_running_loop()
    release_dispatch = asyncio.Event()
    request_started = threading.Event()
    cancellation_waiting = threading.Event()
    cancellation_forwarded = threading.Event()
    trace: list[str] = []

    original_wait_for_dispatch = _wait_for_request_dispatch

    async def tracked_wait_for_dispatch(dispatch):
        cancellation_waiting.set()
        return await original_wait_for_dispatch(dispatch)

    async def fake_forward(
        _client,
        _settings,
        message,
        _protocol_version=None,
        _on_sse_event=None,
        on_request_dispatched=None,
    ):
        if message.get("method") == "notifications/cancelled":
            trace.append("cancellation-forwarded")
            cancellation_forwarded.set()
            return []
        trace.append("request-started")
        request_started.set()
        await release_dispatch.wait()
        trace.append("request-dispatched")
        assert on_request_dispatched is not None
        on_request_dispatched()
        await asyncio.Event().wait()

    monkeypatch.setattr(
        "nyankoface_mcp.stdio._wait_for_request_dispatch",
        tracked_wait_for_dispatch,
    )
    monkeypatch.setattr("nyankoface_mcp.stdio._forward", fake_forward)
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": request_method,
        "params": {},
    }
    cancellation = {
        "jsonrpc": "2.0",
        "method": "notifications/cancelled",
        "params": {"requestId": 1},
    }
    encoded_messages = [
        json.dumps(request).encode() + b"\n",
        json.dumps(cancellation).encode() + b"\n",
    ]

    class StagedInput(BytesIO):
        def readline(self, _size=-1):
            if self.tell() == len(encoded_messages[0]):
                assert request_started.wait(timeout=2)
            elif self.tell() == sum(map(len, encoded_messages)):
                assert cancellation_waiting.wait(timeout=2)
                assert not cancellation_forwarded.is_set()
                loop.call_soon_threadsafe(release_dispatch.set)
                assert cancellation_forwarded.wait(timeout=2)
            return super().readline(_size)

    output = BytesIO()
    await asyncio.wait_for(
        run_stdio(
            StdioSettings(remote_url="http://127.0.0.1:9/mcp", token=TOKEN),
            stdin=StagedInput(b"".join(encoded_messages)),
            stdout=output,
        ),
        timeout=2,
    )

    assert trace == [
        "request-started",
        "request-dispatched",
        "cancellation-forwarded",
    ]
    assert output.getvalue() == b""


@pytest.mark.asyncio
async def test_ordered_cancellations_share_reserved_forwarding_capacity(monkeypatch):
    active_cancellations = 0
    maximum_active_cancellations = 0
    dispatched = [threading.Event() for _ in range(4)]

    async def fake_forward(
        _client,
        _settings,
        message,
        _protocol_version=None,
        _on_sse_event=None,
        on_request_dispatched=None,
    ):
        nonlocal active_cancellations, maximum_active_cancellations
        if message.get("method") == "notifications/cancelled":
            active_cancellations += 1
            maximum_active_cancellations = max(
                maximum_active_cancellations,
                active_cancellations,
            )
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            active_cancellations -= 1
            return []
        request_id = message["id"]
        assert on_request_dispatched is not None
        on_request_dispatched()
        dispatched[request_id - 1].set()
        await asyncio.Event().wait()

    monkeypatch.setattr("nyankoface_mcp.stdio._forward", fake_forward)
    requests = [
        {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {}}
        for request_id in range(1, 5)
    ]
    cancellations = [
        {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": request_id},
        }
        for request_id in range(1, 5)
    ]
    encoded_requests = [json.dumps(message).encode() + b"\n" for message in requests]

    class StagedInput(BytesIO):
        def readline(self, _size=-1):
            if self.tell() == sum(map(len, encoded_requests)):
                assert all(event.wait(timeout=2) for event in dispatched)
            return super().readline(_size)

    output = BytesIO()
    await asyncio.wait_for(
        run_stdio(
            StdioSettings(remote_url="http://127.0.0.1:9/mcp", token=TOKEN),
            stdin=StagedInput(
                b"".join(
                    json.dumps(message).encode() + b"\n"
                    for message in [*requests, *cancellations]
                )
            ),
            stdout=output,
        ),
        timeout=2,
    )

    assert maximum_active_cancellations == 1
    assert output.getvalue() == b""


@pytest.mark.asyncio
async def test_stalled_dispatch_does_not_block_unrelated_cancellation(monkeypatch):
    stalled_request_released = asyncio.Event()
    stalled_request_started = threading.Event()
    second_request_dispatched = threading.Event()
    forwarded_cancellations: list[int] = []

    async def fake_forward(
        _client,
        _settings,
        message,
        _protocol_version=None,
        _on_sse_event=None,
        on_request_dispatched=None,
    ):
        if message.get("method") == "notifications/cancelled":
            request_id = message["params"]["requestId"]
            forwarded_cancellations.append(request_id)
            if request_id == 2:
                stalled_request_released.set()
            return []
        if message.get("id") == 1:
            stalled_request_started.set()
            await stalled_request_released.wait()
        else:
            assert on_request_dispatched is not None
            on_request_dispatched()
            second_request_dispatched.set()
            await asyncio.Event().wait()
        return [{"jsonrpc": "2.0", "id": message["id"], "result": {}}]

    monkeypatch.setattr("nyankoface_mcp.stdio._forward", fake_forward)
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {}},
        {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": 1},
        },
        {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": 2},
        },
    ]
    encoded_messages = [json.dumps(message).encode() + b"\n" for message in messages]

    class StagedInput(BytesIO):
        def readline(self, _size=-1):
            if self.tell() == len(encoded_messages[0]) + len(encoded_messages[1]):
                assert stalled_request_started.wait(timeout=2)
                assert second_request_dispatched.wait(timeout=2)
            return super().readline(_size)

    output = BytesIO()
    await asyncio.wait_for(
        run_stdio(
            StdioSettings(remote_url="http://127.0.0.1:9/mcp", token=TOKEN),
            stdin=StagedInput(b"".join(encoded_messages)),
            stdout=output,
        ),
        timeout=2,
    )

    assert forwarded_cancellations == [2]
    assert output.getvalue() == b""


@pytest.mark.asyncio
async def test_ordered_cancellation_waiters_are_bounded(monkeypatch):
    async def stalled_forward(
        _client,
        _settings,
        _message,
        _protocol_version=None,
        _on_sse_event=None,
        _on_request_dispatched=None,
    ):
        await asyncio.Event().wait()

    monkeypatch.setattr("nyankoface_mcp.stdio._forward", stalled_forward)
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        *[
            {
                "jsonrpc": "2.0",
                "method": "notifications/cancelled",
                "params": {"requestId": 1, "reason": str(index)},
            }
            for index in range(MAX_QUEUED_FORWARDING + 1)
        ],
    ]

    with pytest.raises(RuntimeError, match="stdio forwarding failed"):
        await asyncio.wait_for(
            run_stdio(
                StdioSettings(
                    remote_url="http://127.0.0.1:9/mcp",
                    token=TOKEN,
                ),
                stdin=BytesIO(
                    b"".join(
                        json.dumps(message).encode() + b"\n"
                        for message in messages
                    )
                ),
                stdout=BytesIO(),
            ),
            timeout=2,
        )


def test_stdio_fails_instead_of_dropping_cancellation_when_control_queue_is_full(
    remote_endpoint,
):
    messages = [
        {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {
                "requestId": request_id,
                "reason": "block control queue",
            },
        }
        for request_id in range(MAX_QUEUED_FORWARDING + 2)
    ]
    _, process, responses = _run_adapter(remote_endpoint, messages)
    assert process.returncode == 1
    assert responses == []
    assert "cancellation capacity exceeded" in process.stderr
    assert TOKEN not in process.stderr


def test_stdio_reserves_capacity_for_cancellation_when_saturated(remote_endpoint):
    messages = [
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": "slow_tool", "arguments": {}},
        }
        for request_id in range(20, 20 + MAX_CONCURRENT_FORWARDING)
    ]
    messages.append({
        "jsonrpc": "2.0",
        "method": "notifications/cancelled",
        "params": {"requestId": 20, "reason": "saturated contract test"},
    })
    _, process, responses = _run_adapter(remote_endpoint, messages)
    assert process.returncode == 0
    assert len(responses) == MAX_CONCURRENT_FORWARDING - 1
    assert all(response["result"]["cancelReceived"] is True for response in responses)
    assert any(
        request["payload"]["method"] == "notifications/cancelled"
        for request in RemoteMcpHandler.requests
    )


def test_stdio_bounds_queued_work_without_blocking_cancellation(remote_endpoint):
    request_count = (
        MAX_CONCURRENT_FORWARDING - 1 + MAX_QUEUED_FORWARDING + 20
    )
    messages = [
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": "slow_tool", "arguments": {}},
        }
        for request_id in range(200, 200 + request_count)
    ]
    messages.append({
        "jsonrpc": "2.0",
        "method": "notifications/cancelled",
        "params": {"requestId": 200, "reason": "bounded queue contract test"},
    })
    _, process, responses = _run_adapter(remote_endpoint, messages)
    assert process.returncode == 0
    assert len(responses) == request_count - 1
    overloads = [response for response in responses if "error" in response]
    completed = [response for response in responses if "result" in response]
    assert overloads
    assert all(response["error"]["code"] == -32002 for response in overloads)
    assert all(response["result"]["cancelReceived"] is True for response in completed)
    assert len(completed) <= MAX_CONCURRENT_FORWARDING - 1 + MAX_QUEUED_FORWARDING


def test_stdio_overload_responds_to_explicit_null_id_request(remote_endpoint):
    request_count = MAX_ORDINARY_FORWARDING + MAX_QUEUED_FORWARDING
    messages = [
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": "barrier_tool", "arguments": {}},
        }
        for request_id in range(800, 800 + request_count)
    ]
    messages.append({
        "jsonrpc": "2.0",
        "id": None,
        "method": "tools/call",
        "params": {"name": "barrier_tool", "arguments": {}},
    })
    messages.append({
        "jsonrpc": "2.0",
        "id": "release-barrier",
        "result": {},
    })
    _, process, responses = _run_adapter(remote_endpoint, messages)
    assert process.returncode == 0
    assert any(
        response.get("id", "omitted") is None
        and response.get("error", {}).get("code") == -32002
        for response in responses
    )


def test_stdio_cancels_accepted_request_before_remote_start(remote_endpoint):
    target_id = 400 + MAX_CONCURRENT_FORWARDING - 1
    messages = [
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": "delay_tool", "arguments": {}},
        }
        for request_id in range(400, target_id + 1)
    ]
    messages.append({
        "jsonrpc": "2.0",
        "method": "notifications/cancelled",
        "params": {"requestId": target_id, "reason": "queued cancellation contract test"},
    })
    _, process, responses = _run_adapter(remote_endpoint, messages)
    assert process.returncode == 0
    assert len(responses) == MAX_CONCURRENT_FORWARDING - 1
    assert all(response["result"]["delayed"] is True for response in responses)
    assert target_id not in {
        request["payload"].get("id") for request in RemoteMcpHandler.requests
    }
    assert all(
        request["payload"]["method"] != "notifications/cancelled"
        for request in RemoteMcpHandler.requests
    )


def test_stdio_rejects_oversized_remote_response(remote_endpoint):
    _, process, responses = _run_adapter(remote_endpoint, [{
        "jsonrpc": "2.0",
        "id": 500,
        "method": "tools/call",
        "params": {"name": "oversized_response", "arguments": {}},
    }])
    assert process.returncode == 0
    assert responses == [{
        "jsonrpc": "2.0",
        "id": 500,
        "error": {
            "code": -32000,
            "message": "NyankoFace MCP endpoint is unavailable or returned an invalid response",
        },
    }]


@pytest.mark.asyncio
async def test_background_output_failure_propagates_after_drain(remote_endpoint):
    class FailingOutput(BytesIO):
        def write(self, _data):
            raise OSError("simulated closed stdout")

    settings = StdioSettings(remote_url=remote_endpoint, token=TOKEN)
    request = json.dumps(
        {"jsonrpc": "2.0", "id": 10, "method": "tools/list", "params": {}}
    ).encode("utf-8") + b"\n"
    with pytest.raises(RuntimeError, match="stdio forwarding failed"):
        await run_stdio(settings, stdin=BytesIO(request), stdout=FailingOutput())


@pytest.mark.asyncio
async def test_background_output_failure_does_not_wait_for_stdin_eof(remote_endpoint):
    class PersistentInput:
        def __init__(self, first_line: bytes):
            self.first_line = first_line
            self.release = threading.Event()

        def readline(self, _size=-1):
            if self.first_line:
                line, self.first_line = self.first_line, b""
                return line
            self.release.wait(timeout=5)
            return b""

    class FailingOutput(BytesIO):
        def write(self, _data):
            raise OSError("simulated closed stdout")

    request = json.dumps(
        {"jsonrpc": "2.0", "id": 11, "method": "tools/list", "params": {}}
    ).encode("utf-8") + b"\n"
    persistent_input = PersistentInput(request)
    settings = StdioSettings(remote_url=remote_endpoint, token=TOKEN)
    try:
        with pytest.raises(RuntimeError, match="stdio forwarding failed"):
            await asyncio.wait_for(
                run_stdio(settings, stdin=persistent_input, stdout=FailingOutput()),
                timeout=2,
            )
    finally:
        persistent_input.release.set()


def test_stdio_bounds_concurrent_forwarding(remote_endpoint):
    messages = [
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": "bounded_tool", "arguments": {}},
        }
        for request_id in range(100, 100 + (MAX_CONCURRENT_FORWARDING * 2 + 5))
    ]
    _, process, responses = _run_adapter(remote_endpoint, messages)
    assert process.returncode == 0
    assert len(responses) == len(messages)
    assert RemoteMcpHandler.maximum_active_requests <= MAX_CONCURRENT_FORWARDING
    assert RemoteMcpHandler.maximum_active_requests > 1


def test_validate_config_reports_source_not_secret(remote_endpoint):
    env = os.environ.copy()
    env.update({"NYANKOFACE_MCP_REMOTE_URL": remote_endpoint, "NYANKOFACE_MCP_TOKEN": TOKEN})
    process = subprocess.run(
        [sys.executable, "-m", "nyankoface_mcp", "validate-config"],
        text=True, capture_output=True, env=env, timeout=10, check=False,
    )
    assert process.returncode == 0
    assert json.loads(process.stdout)["token_source"] == "NYANKOFACE_MCP_TOKEN"
    assert TOKEN not in process.stdout + process.stderr


def test_oversized_line_is_fully_discarded_before_next_request(remote_endpoint):
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(__import__("pathlib").Path(__file__).parents[1]),
        "NYANKOFACE_MCP_REMOTE_URL": remote_endpoint,
        "NYANKOFACE_MCP_TOKEN": TOKEN,
    })
    valid_suffix = json.dumps(
        {"jsonrpc": "2.0", "id": 99, "method": "tools/list", "params": {}}
    ).encode("utf-8")
    process = subprocess.run(
        [sys.executable, "-m", "nyankoface_mcp", "stdio"],
        input=(b"x" * (MAX_MESSAGE_BYTES + 1)) + valid_suffix + b"\n",
        capture_output=True,
        env=env,
        timeout=15,
        check=False,
    )
    responses = [json.loads(line) for line in process.stdout.splitlines()]
    assert process.returncode == 0
    assert responses == [{
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32700, "message": "JSON-RPC message exceeds the size limit"},
    }]
    assert RemoteMcpHandler.requests == []


def test_exact_message_limit_with_newline_is_accepted(remote_endpoint):
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(__import__("pathlib").Path(__file__).parents[1]),
        "NYANKOFACE_MCP_REMOTE_URL": remote_endpoint,
        "NYANKOFACE_MCP_TOKEN": TOKEN,
    })
    template = {
        "jsonrpc": "2.0",
        "id": 902,
        "method": "tools/call",
        "params": {"name": "echo", "arguments": {"padding": ""}},
    }
    compact = json.dumps(template, separators=(",", ":")).encode("utf-8")
    template["params"]["arguments"]["padding"] = "x" * (
        MAX_MESSAGE_BYTES - len(compact)
    )
    encoded = json.dumps(template, separators=(",", ":")).encode("utf-8")
    assert len(encoded) == MAX_MESSAGE_BYTES
    process = subprocess.run(
        [sys.executable, "-m", "nyankoface_mcp", "stdio"],
        input=encoded + b"\n",
        capture_output=True,
        env=env,
        timeout=15,
        check=False,
    )
    responses = [json.loads(line) for line in process.stdout.splitlines()]
    assert process.returncode == 0
    assert responses[0]["id"] == 902
    assert "result" in responses[0]


def test_unterminated_oversized_line_exits_after_reporting_error(remote_endpoint):
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(__import__("pathlib").Path(__file__).parents[1]),
        "NYANKOFACE_MCP_REMOTE_URL": remote_endpoint,
        "NYANKOFACE_MCP_TOKEN": TOKEN,
    })
    process = subprocess.run(
        [sys.executable, "-m", "nyankoface_mcp", "stdio"],
        input=b"x" * (MAX_MESSAGE_BYTES + 1),
        capture_output=True,
        env=env,
        timeout=15,
        check=False,
    )
    responses = [json.loads(line) for line in process.stdout.splitlines()]
    assert process.returncode == 0
    assert responses == [{
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32700, "message": "JSON-RPC message exceeds the size limit"},
    }]
    assert RemoteMcpHandler.requests == []


def test_non_loopback_plaintext_and_ambiguous_token_sources_fail_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("NYANKOFACE_MCP_REMOTE_URL", "http://nyankoface.example/mcp")
    monkeypatch.setenv("NYANKOFACE_MCP_TOKEN", TOKEN)
    with pytest.raises(ConfigurationError, match="must use HTTPS"):
        StdioSettings.from_env()

    token_file = tmp_path / "token"
    token_file.write_text(TOKEN, encoding="utf-8")
    monkeypatch.setenv("NYANKOFACE_MCP_REMOTE_URL", "https://nyankoface.example/mcp")
    monkeypatch.setenv("NYANKOFACE_MCP_CLIENT_TOKEN_FILE", str(token_file))
    with pytest.raises(ConfigurationError, match="exactly one"):
        StdioSettings.from_env()


def test_remote_url_rejects_non_mcp_path_and_token_control_characters(monkeypatch):
    monkeypatch.setenv("NYANKOFACE_MCP_REMOTE_URL", "https://nyankoface.example/private/mcp")
    monkeypatch.setenv("NYANKOFACE_MCP_TOKEN", TOKEN)
    with pytest.raises(ConfigurationError, match="path must be /mcp"):
        StdioSettings.from_env()

    monkeypatch.setenv("NYANKOFACE_MCP_REMOTE_URL", "https://nyankoface.example/mcp")
    monkeypatch.setenv("NYANKOFACE_MCP_TOKEN", TOKEN + "\nunsafe")
    with pytest.raises(ConfigurationError, match="invalid format"):
        StdioSettings.from_env()
