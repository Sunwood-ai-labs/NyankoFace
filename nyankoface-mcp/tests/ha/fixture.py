"""Tiny deterministic upstream for the container-level HA contract."""
import asyncio
import json
import os
from pathlib import Path

import uvicorn

from nyankoface_mcp.config import Settings
from nyankoface_mcp.policy import PolicyStore
from nyankoface_mcp.server import TOOL_ACCESS


STATE = Path("/state/mutations.json")


def json_response(send, status, payload):
    body = json.dumps(payload, separators=(",", ":")).encode()
    return send({"type": "http.response.start", "status": status, "headers": [
        (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
    ]}), send({"type": "http.response.body", "body": body})


async def app(scope, receive, send):
    path, method = scope["path"], scope["method"]
    if path == "/healthz":
        first, second = json_response(send, 200, {"ok": True})
        await first; await second; return
    if path == "/api/v1/user":
        first, second = json_response(send, 200, {"id": 42})
        await first; await second; return
    if path == "/api/v1/repos/nyankoface/demo":
        first, second = json_response(send, 200, {
            "full_name": "nyankoface/demo", "private": False,
            "default_branch": "main", "permissions": {"push": True},
        })
        await first; await second; return
    if path == "/api/catalog/repositories":
        if b"q=slow" in scope.get("query_string", b""):
            await asyncio.sleep(6)
        first, second = json_response(send, 200, {"items": [
            {"full_name": "nyankoface/demo", "private": False},
        ], "page": 1, "limit": 20, "totalCount": 1, "totalPages": 1})
        await first; await second; return
    if path == "/api/v1/repos/nyankoface/demo/issues" and method == "POST":
        count = int(STATE.read_text() if STATE.exists() else "0") + 1
        STATE.write_text(str(count))
        first, second = json_response(send, 201, {"number": count, "title": "HA write"})
        await first; await second; return
    if path == "/stats":
        first, second = json_response(send, 200, {
            "mutations": int(STATE.read_text() if STATE.exists() else "0"),
        })
        await first; await second; return
    first, second = json_response(send, 404, {"error": "not_found"})
    await first; await second


if __name__ == "__main__":
    settings = Settings.from_env()
    policy = PolicyStore(settings.policy_state_path)
    for tool in TOOL_ACCESS:
        policy.set_tool_policy("global", "*", tool, "allow")
    os.chmod("/state", 0o777)
    for path in (settings.policy_state_path, settings.audit_state_path):
        if path.exists():
            os.chmod(path, 0o666)
    uvicorn.run(app, host="0.0.0.0", port=8001)
