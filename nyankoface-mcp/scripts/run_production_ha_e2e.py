"""Exercise MCP failover through the production Compose and nginx files."""
from __future__ import annotations

import json
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROJECT = f"nyankoface-mcp-production-ha-{uuid.uuid4().hex[:12]}"
NETWORK = f"{PROJECT}-network"
COMPOSE = [
    "docker", "compose", "--progress", "quiet", "-p", PROJECT,
    "-f", "docker-compose.yml", "-f", "compose.mcp-production-ha.test.yml",
    "--profile", "mcp",
]
ENV = {**os.environ, "NYANKOFACE_LIVE_HA_NETWORK": NETWORK}
CONTEXT = ssl._create_unverified_context()
URL = ""


def compose(*args: str, capture: bool = False) -> str:
    completed = subprocess.run(
        [*COMPOSE, *args], cwd=ROOT, env=ENV, text=True,
        capture_output=capture, check=True,
    )
    return completed.stdout.strip() if capture else ""


def request(url: str) -> tuple[int, str]:
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "production-ha", "version": "1"},
        },
    }).encode()
    call = urllib.request.Request(
        url, data=payload, method="POST",
        headers={
            "Authorization": "Bearer deliberately-invalid",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
    )
    try:
        response = urllib.request.urlopen(call, context=CONTEXT, timeout=5)
        status = response.status
        instance = response.headers.get("X-NyankoFace-MCP-Instance", "")
        response.read()
        return status, instance
    except urllib.error.HTTPError as exc:
        exc.read()
        return exc.code, exc.headers.get("X-NyankoFace-MCP-Instance", "")


def internal_request() -> tuple[int, str]:
    program = r'''
import json, ssl, urllib.error, urllib.request
payload=json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"internal","version":"1"}}}).encode()
req=urllib.request.Request("https://gateway/mcp",data=payload,method="POST",headers={"Authorization":"Bearer deliberately-invalid","Accept":"application/json, text/event-stream","Content-Type":"application/json"})
try:
    res=urllib.request.urlopen(req,context=ssl._create_unverified_context(),timeout=5)
except urllib.error.HTTPError as exc:
    res=exc
print(json.dumps({"status":res.status,"instance":res.headers.get("X-NyankoFace-MCP-Instance","")}))
res.read()
'''
    raw = compose("exec", "-T", "probe", "python", "-c", program, capture=True)
    result = json.loads(raw)
    return int(result["status"]), str(result["instance"])


def wait_for_unauthorized(call, expected_instance: str | None = None) -> str:
    last: tuple[int, str] = (0, "")
    for _ in range(20):
        try:
            last = call()
            if last[0] == 401 and last[1] and (
                expected_instance is None or last[1] == expected_instance
            ):
                return last[1]
        except (OSError, subprocess.CalledProcessError, ValueError):
            pass
        time.sleep(0.25)
    raise AssertionError(f"gateway did not converge to HTTP 401: {last}")


def container_for_instance(instance: str) -> str:
    containers = compose("ps", "-q", "nyankoface-mcp", capture=True).splitlines()
    for container in containers:
        hostname = subprocess.run(
            ["docker", "inspect", "--format", "{{.Config.Hostname}}", container],
            text=True, capture_output=True, check=True,
        ).stdout.strip()
        if hostname == instance:
            return container
    raise AssertionError(f"no container owns instance {instance!r}: {containers}")


def assert_stable(call, expected_instance: str, count: int = 10) -> None:
    results = [call() for _ in range(count)]
    assert results == [(401, expected_instance)] * count, results


def verify() -> None:
    first = wait_for_unauthorized(lambda: request(URL))
    containers = compose("ps", "-q", "nyankoface-mcp", capture=True).splitlines()
    assert len(containers) == 2, containers
    active = container_for_instance(first)
    standby = next(container for container in containers if container != active)
    standby_instance = subprocess.run(
        ["docker", "inspect", "--format", "{{.Config.Hostname}}", standby],
        text=True, capture_output=True, check=True,
    ).stdout.strip()

    subprocess.run(["docker", "stop", active], check=True, capture_output=True)
    # POSTs are never replayed by nginx. The failed attempt marks the dead peer;
    # the next client attempt converges through Docker DNS to the live peer.
    wait_for_unauthorized(lambda: request(URL), standby_instance)
    assert_stable(lambda: request(URL), standby_instance)
    assert_stable(internal_request, standby_instance)

    subprocess.run(["docker", "start", active], check=True, capture_output=True)
    observed: set[str] = set()
    for _ in range(30):
        status, instance = request(URL)
        if status == 401:
            observed.add(instance)
        if observed == {first, standby_instance}:
            break
        time.sleep(0.25)
    assert observed == {first, standby_instance}, observed

    # Exercise the opposite rolling-restart order as well.
    subprocess.run(["docker", "stop", standby], check=True, capture_output=True)
    wait_for_unauthorized(lambda: request(URL), first)
    assert_stable(lambda: request(URL), first)
    assert_stable(internal_request, first)
    subprocess.run(["docker", "start", standby], check=True, capture_output=True)
    wait_for_unauthorized(lambda: request(URL))


def main() -> int:
    global URL
    try:
        compose(
            "up", "-d", "--build", "--wait", "--no-deps",
            "dependency-stub", "probe", "nyankoface-mcp", "gateway",
        )
        published = compose("port", "gateway", "443", capture=True)
        URL = f"https://localhost:{int(published.rsplit(':', 1)[1])}/mcp"
        verify()
        print("Production MCP HA E2E passed: public/internal failover and rolling return")
        return 0
    finally:
        # The base production file declares externally named data volumes.
        # Never ask Compose to remove every declared volume from a test run.
        compose("down", "--remove-orphans")
        subprocess.run(
            ["docker", "volume", "rm", f"{PROJECT}_production-mcp-state"],
            text=True, capture_output=True, check=False,
        )


if __name__ == "__main__":
    sys.exit(main())
