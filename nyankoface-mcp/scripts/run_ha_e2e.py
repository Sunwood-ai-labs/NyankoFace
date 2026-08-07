"""Run the hermetic two-container MCP failover contract."""
from __future__ import annotations

import json
import http.client
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROJECT = f"nyankoface-mcp-ha-{uuid.uuid4().hex[:12]}"
COMPOSE = [
    "docker", "compose", "--progress", "quiet", "-p", PROJECT,
    "-f", "compose.mcp-ha.test.yml",
]
URL = ""
PORT = 0
TOKEN = "test-token"
CONTEXT = ssl._create_unverified_context()


def compose(*args: str, capture: bool = False) -> str:
    completed = subprocess.run(
        [*COMPOSE, *args], cwd=ROOT, text=True,
        capture_output=capture, check=True,
    )
    return completed.stdout.strip() if capture else ""


def rpc(payload: dict, extra_headers: dict[str, str] | None = None) -> tuple[int, dict, str]:
    data = json.dumps(payload, separators=(",", ":")).encode()
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Origin": "https://ha.test",
        **(extra_headers or {}),
    }
    request = urllib.request.Request(URL, data=data, headers=headers, method="POST")
    try:
        response = urllib.request.urlopen(request, context=CONTEXT, timeout=8)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        return exc.code, json.loads(body) if body.startswith("{") else {"body": body}, exc.headers.get("X-NyankoFace-MCP-Instance", "")
    body = response.read().decode()
    if response.headers.get_content_type() == "text/event-stream":
        body = next(line[6:] for line in body.splitlines() if line.startswith("data: "))
    return response.status, json.loads(body), response.headers.get("X-NyankoFace-MCP-Instance", "")


def initialize(request_id: int) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "ha-e2e", "version": "1"},
    }}


def tool(name: str, arguments: dict, request_id: int) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {
        "name": name, "arguments": arguments,
    }}


def structured(response: dict) -> dict:
    result = response["result"]
    if result.get("isError"):
        raise AssertionError(result)
    return result["structuredContent"]


def wait_ready() -> None:
    for request_id in range(30):
        try:
            status, body, _instance = rpc(initialize(request_id))
            if status == 200 and "result" in body:
                return
        except (OSError, ValueError):
            pass
        time.sleep(1)
    raise AssertionError("TLS gateway did not become ready")


def verify() -> None:
    wait_ready()
    instances = {rpc(initialize(100 + index))[2] for index in range(6)}
    assert instances == {"mcp-a", "mcp-b"}, instances

    status, read, _ = rpc(tool("search_catalog", {"kind": "model"}, 200))
    assert status == 200 and structured(read)["items"][0]["full_name"] == "nyankoface/demo"

    status, rejected, _ = rpc(initialize(201), {"Last-Event-ID": "event-7"})
    assert status == 400 and rejected["error"] == "last_event_id_not_supported"
    status, _body, _ = rpc(initialize(202), {"Origin": "https://evil.invalid"})
    assert status == 403

    preview_status, preview_body, preview_instance = rpc(tool("create_issue", {
        "owner": "nyankoface", "repo": "demo", "title": "HA write",
    }, 300))
    preview = structured(preview_body)
    assert preview_status == 200 and preview["status"] == "preview"
    execute_args = {
        "owner": "nyankoface", "repo": "demo", "title": "HA write",
        "preview": False, "confirmation": preview["confirmation"],
        "idempotency_key": "ha-e2e-write",
    }
    _, executed_body, execute_instance = rpc(tool("create_issue", execute_args, 301))
    executed = structured(executed_body)
    assert execute_instance != preview_instance
    _, replay_body, replay_instance = rpc(tool("create_issue", {
        **execute_args, "confirmation": "replay-does-not-consume-a-token",
    }, 302))
    replay = structured(replay_body)
    assert replay_instance != execute_instance and replay["replayed"] is True
    assert replay["result"] == executed["result"]
    assert compose("exec", "-T", "fixture", "cat", "/state/mutations.json", capture=True) == "1"

    compose("stop", "mcp-a")
    # Docker DNS convergence is bounded by the proxy's one-second resolver TTL.
    for attempt in range(10):
        status, body, instance = rpc(initialize(390 + attempt))
        if status == 200 and "result" in body and instance == "mcp-b":
            break
        time.sleep(1)
    else:
        raise AssertionError("mcp-b did not take over after mcp-a stopped")
    for request_id in range(400, 404):
        status, body, instance = rpc(initialize(request_id))
        assert status == 200 and "result" in body and instance == "mcp-b"
    compose("start", "mcp-a")
    returned: set[str] = set()
    for index in range(30):
        status, body, instance = rpc(initialize(500 + index))
        if status == 200 and "result" in body:
            returned.add(instance)
        if returned == {"mcp-a", "mcp-b"}:
            break
        time.sleep(1)
    assert returned == {"mcp-a", "mcp-b"}, returned

    # The proxy, not an unbounded worker wait, terminates a slow upstream.
    started = time.monotonic()
    try:
        rpc(tool("search_catalog", {"kind": "model", "query": "slow"}, 600))
    except http.client.IncompleteRead:
        # SSE headers are already committed, so nginx bounds the stream by
        # closing it rather than replacing the response with a 504 body.
        pass
    else:
        raise AssertionError("slow SSE upstream was not terminated")
    assert time.monotonic() - started < 8
    time.sleep(2)
    assert rpc(initialize(601))[0] == 200

    # A client that disconnects during upload never dispatches a partial POST.
    raw = socket.create_connection(("127.0.0.1", PORT), timeout=3)
    tls = CONTEXT.wrap_socket(raw, server_hostname="localhost")
    tls.sendall(
        b"POST /mcp HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\n"
        b"Content-Length: 100000\r\n\r\n{\"jsonrpc\":\"2.0\""
    )
    tls.close()
    assert rpc(initialize(602))[0] == 200

    oversized = urllib.request.Request(
        URL, data=b"x" * 1_048_577,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        urllib.request.urlopen(oversized, context=CONTEXT, timeout=5)
    except urllib.error.HTTPError as exc:
        assert exc.code == 413
    else:
        raise AssertionError("oversized MCP body was accepted")

    # Rate limiting is last so the test does not make later assertions flaky.
    with ThreadPoolExecutor(max_workers=40) as pool:
        rate_statuses = list(pool.map(
            lambda index: rpc(initialize(700 + index))[0], range(40),
        ))
    assert 503 in rate_statuses, rate_statuses


def main() -> int:
    global PORT, URL
    compose("down", "--volumes", "--remove-orphans")
    try:
        compose("up", "-d", "--build", "--wait")
        published = compose("port", "gateway", "443", capture=True)
        PORT = int(published.rsplit(":", 1)[1])
        URL = f"https://localhost:{PORT}/mcp"
        verify()
        print("MCP HA E2E passed: TLS LB, two instances, failover, and exactly-once write")
        return 0
    finally:
        compose("down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    sys.exit(main())
