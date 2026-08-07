"""NyankoFace pull-based GPU worker and authenticated runtime gateway."""
from __future__ import annotations

import asyncio
import json
import os
import platform
import secrets
import shutil
import subprocess
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import docker
import httpx
import websockets
from docker.types import DeviceRequest
from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from starlette.datastructures import MutableHeaders
from sandbox_profile import docker_options_for

NYANKOFACE_URL = os.environ.get("NYANKOFACE_URL", "http://gateway:8090").rstrip("/")
NYANKOFACE_API_PREFIX = "/" + os.environ.get("NYANKOFACE_API_PREFIX", "runner-api").strip("/")
WORKER_NAME = os.environ.get("WORKER_NAME", platform.node() or "gpu-worker")
WORKER_PUBLIC_URL = os.environ.get("WORKER_PUBLIC_URL", "http://localhost:8787").rstrip("/")
WORKER_DATA_DIR = Path(os.environ.get("WORKER_DATA_DIR", "/data"))
WORKER_DOCKER_NETWORK = os.environ.get("WORKER_DOCKER_NETWORK", "nyankoface-gpu-worker")
WORKER_ENROLLMENT_TOKEN = os.environ.get("WORKER_ENROLLMENT_TOKEN", "")
WORKER_ENROLLMENT_TOKEN_FILE = os.environ.get(
    "WORKER_ENROLLMENT_TOKEN_FILE", "/run/secrets/nyankoface-worker-enrollment-token"
)
MAX_GPU_JOBS = max(1, int(os.environ.get("MAX_GPU_JOBS", "1")))
POLL_SECONDS = max(1, int(os.environ.get("WORKER_POLL_SECONDS", "5")))
FAKE_EXECUTOR = os.environ.get("NYANKOFACE_WORKER_FAKE_EXECUTOR", "false").lower() == "true"
VERIFY_TLS = os.environ.get("NYANKOFACE_VERIFY_TLS", "true").lower() == "true"

_state_lock = threading.Lock()
_running: dict[str, dict[str, str]] = {}
_active_jobs: set[str] = set()
_credential: dict[str, str] = {}
_docker_client: docker.DockerClient | None = None


def docker_client() -> docker.DockerClient:
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.from_env()
    return _docker_client


def _credential_path() -> Path:
    return WORKER_DATA_DIR / "credential.json"


def _runtime_state_path() -> Path:
    return WORKER_DATA_DIR / "runtimes.json"


def _save_runtime_state() -> None:
    WORKER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = _runtime_state_path().with_suffix(".tmp")
    temporary.write_text(json.dumps(_running), encoding="utf-8")
    temporary.replace(_runtime_state_path())


def load_runtime_state() -> None:
    global _running, _active_jobs
    try:
        stored = json.loads(_runtime_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stored = {}
    valid: dict[str, dict[str, str]] = {}
    for job_id, runtime in stored.items():
        if runtime.get("container") == "fake":
            continue
        try:
            container = docker_client().containers.get(runtime["container"])
            if container.status == "running":
                valid[job_id] = runtime
        except (KeyError, docker.errors.NotFound):
            continue
    with _state_lock:
        _running = valid
        _active_jobs = set(valid)
        _save_runtime_state()


def _read_enrollment_token() -> str:
    if WORKER_ENROLLMENT_TOKEN:
        return WORKER_ENROLLMENT_TOKEN
    try:
        return Path(WORKER_ENROLLMENT_TOKEN_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


async def ensure_enrolled(client: httpx.AsyncClient) -> None:
    global _credential
    WORKER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _credential = json.loads(_credential_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        token = _read_enrollment_token()
        if not token:
            raise RuntimeError("No worker credential or enrollment token is available")
        response = await client.post(
            f"{NYANKOFACE_URL}{NYANKOFACE_API_PREFIX}/v1/workers/enroll",
            json={"token": token},
        )
        response.raise_for_status()
        _credential = response.json()
        temporary = _credential_path().with_suffix(".tmp")
        temporary.write_text(json.dumps(_credential), encoding="utf-8")
        temporary.replace(_credential_path())


def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_credential['credential']}"}


def discover_capabilities() -> dict[str, Any]:
    capabilities: dict[str, Any] = {
        "os": platform.system().lower(),
        "architecture": platform.machine().lower(),
        "docker": False,
        "gpu_count": 0,
        "gpu_devices": [],
        "free_vram_mb": 0,
        "total_vram_mb": 0,
        "features": [],
    }
    if FAKE_EXECUTOR:
        capabilities.update(
            {
                "docker": True,
                "docker_version": "fake-e2e",
                "gpu_count": 1,
                "gpu_devices": [
                    {
                        "id": "0",
                        "name": "Fake NVIDIA GPU",
                        "total_vram_mb": 24576,
                        "free_vram_mb": 24576,
                    }
                ],
                "free_vram_mb": 24576,
                "total_vram_mb": 24576,
                "features": ["nvidia", "cuda", "fake-e2e"],
            }
        )
        return capabilities
    try:
        client = docker_client()
        capabilities["docker"] = True
        capabilities["docker_version"] = client.version().get("Version")
    except Exception:
        return capabilities
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=uuid,index,name,memory.total,memory.free,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        rows = [line.split(",") for line in result.stdout.splitlines() if line.strip()]
        capabilities.update(
            {
                "gpu_count": len(rows),
                "gpu_models": [row[2].strip() for row in rows],
                "gpu_devices": [
                    {
                        # UUIDs remain stable across CUDA's device-ordering modes.
                        # Passing ordinal indexes here can select a different card
                        # on Docker Desktop when CUDA uses FASTEST_FIRST ordering.
                        "id": row[0].strip(),
                        "index": row[1].strip(),
                        "name": row[2].strip(),
                        "total_vram_mb": int(row[3].strip()),
                        "free_vram_mb": int(row[4].strip()),
                    }
                    for row in rows
                ],
                "total_vram_mb": sum(int(row[3].strip()) for row in rows),
                "free_vram_mb": sum(int(row[4].strip()) for row in rows),
                "driver_version": rows[0][5].strip() if rows else None,
                "features": ["nvidia", "cuda"] if rows else [],
            }
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return capabilities


async def event(
    client: httpx.AsyncClient, job_id: str, kind: str, details: dict[str, Any] | None = None
) -> None:
    worker_id = _credential["worker_id"]
    response = await client.post(
        f"{NYANKOFACE_URL}{NYANKOFACE_API_PREFIX}/v1/workers/{worker_id}/jobs/{job_id}/events",
        headers={
            **auth_headers(),
            "Idempotency-Key": f"{job_id}:{kind}",
        },
        json={"kind": kind, "details": details or {}},
    )
    response.raise_for_status()


def _container_name(job_id: str) -> str:
    return f"nyankoface-gpu-job-{job_id[:12]}"


def _image_name(job_id: str) -> str:
    return f"nyankoface-gpu-job-{job_id}:latest"


def select_gpu_devices(requirements: dict[str, Any]) -> list[dict[str, Any]]:
    required_count = max(1, int(requirements.get("gpu_count", 1)))
    minimum_vram = int(requirements.get("min_vram_mb", 0))
    eligible = [
        device
        for device in discover_capabilities().get("gpu_devices", [])
        if int(device.get("free_vram_mb", 0)) >= minimum_vram
    ]
    # Best-fit keeps larger devices available for later jobs.
    eligible.sort(key=lambda device: int(device.get("free_vram_mb", 0)))
    selected = eligible[:required_count]
    if len(selected) != required_count:
        raise RuntimeError(
            f"No {required_count} GPU device(s) satisfy min_vram_mb={minimum_vram}"
        )
    return selected


def execute_job(job: dict[str, Any], runtime_token: str) -> tuple[str, list[dict[str, Any]]]:
    job_id = job["id"]
    if FAKE_EXECUTOR:
        with _state_lock:
            _running[job_id] = {
                "runtime_token": runtime_token,
                "container": "fake",
                "owner": job["owner"],
                "repo": job["repo"],
            }
            _save_runtime_state()
        return f"{WORKER_PUBLIC_URL}/runtime/{job_id}", [
            {"id": "0", "name": "Fake NVIDIA GPU"}
        ]

    selected_devices = select_gpu_devices(job.get("requirements") or {})
    checkout = WORKER_DATA_DIR / "jobs" / job_id
    shutil.rmtree(checkout, ignore_errors=True)
    checkout.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--no-checkout", job["clone_url"], str(checkout)],
        check=True,
        timeout=300,
    )
    subprocess.run(
        ["git", "checkout", "--detach", job["revision"]],
        cwd=checkout,
        check=True,
        timeout=60,
    )
    dockerfile = checkout / "Dockerfile"
    if not dockerfile.exists():
        raise RuntimeError("GPU Spaces must include a Dockerfile")
    client = docker_client()
    image = _image_name(job_id)
    client.images.build(path=str(checkout), tag=image, rm=True, forcerm=True)
    name = _container_name(job_id)
    try:
        client.containers.get(name).remove(force=True)
    except docker.errors.NotFound:
        pass
    runtime_options = docker_options_for(job.get("owner"), job.get("repo"))
    container = client.containers.run(
        image,
        name=name,
        detach=True,
        network=WORKER_DOCKER_NETWORK,
        environment={
            variable: ",".join(str(device["id"]) for device in selected_devices)
            for variable in ("NVIDIA_VISIBLE_DEVICES", "CUDA_VISIBLE_DEVICES")
        },
        labels={
            "nyankoface.gpu-job": job_id,
            "nyankoface.owner": job["owner"],
            "nyankoface.repo": job["repo"],
            "nyankoface.revision": job["revision"],
        },
        device_requests=[
            DeviceRequest(
                device_ids=[str(device["id"]) for device in selected_devices],
                capabilities=[["gpu"]],
            )
        ],
        restart_policy={"Name": "unless-stopped"},
        **runtime_options,
    )
    with _state_lock:
        _running[job_id] = {
            "runtime_token": runtime_token,
            "container": container.name,
            "owner": job["owner"],
            "repo": job["repo"],
        }
        _save_runtime_state()
    return f"{WORKER_PUBLIC_URL}/runtime/{job_id}", selected_devices


def stop_job(job_id: str) -> None:
    with _state_lock:
        runtime = _running.pop(job_id, None)
        _active_jobs.discard(job_id)
        _save_runtime_state()
    if runtime and runtime["container"] != "fake":
        try:
            docker_client().containers.get(runtime["container"]).remove(force=True)
        except docker.errors.NotFound:
            pass


async def run_claimed_job(client: httpx.AsyncClient, job: dict[str, Any]) -> None:
    job_id = job["id"]
    runtime_token = secrets.token_urlsafe(32)
    try:
        await event(client, job_id, "building", {"revision": job["revision"]})
        runtime_url, assigned_devices = await asyncio.to_thread(
            execute_job, job, runtime_token
        )
        await event(
            client,
            job_id,
            "running",
            {
                "runtime_url": runtime_url,
                "runtime_token": runtime_token,
                "revision": job["revision"],
                "assigned_gpu_devices": assigned_devices,
            },
        )
    except Exception as exc:
        await event(client, job_id, "failed", {"error": str(exc)[-2000:]})
        with _state_lock:
            _active_jobs.discard(job_id)


async def poll_loop() -> None:
    while True:
        try:
            async with httpx.AsyncClient(timeout=30.0, verify=VERIFY_TLS) as client:
                await ensure_enrolled(client)
                await poll_session(client)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"control-plane connection failed; retrying: {exc}", flush=True)
            await asyncio.sleep(POLL_SECONDS)


async def poll_session(client: httpx.AsyncClient) -> None:
    capabilities = discover_capabilities()
    register = await client.post(
        f"{NYANKOFACE_URL}{NYANKOFACE_API_PREFIX}/v1/workers/register",
        headers=auth_headers(),
        json={"capabilities": capabilities, "max_jobs": MAX_GPU_JOBS},
    )
    register.raise_for_status()
    worker_id = _credential["worker_id"]
    while True:
        with _state_lock:
            active_ids = list(_active_jobs)
        heartbeat = await client.post(
            f"{NYANKOFACE_URL}{NYANKOFACE_API_PREFIX}/v1/workers/{worker_id}/heartbeat",
            headers=auth_headers(),
            json={"capabilities": discover_capabilities(), "running_jobs": len(active_ids)},
        )
        heartbeat.raise_for_status()
        for action in heartbeat.json().get("actions", []):
            if action.get("action") == "stop":
                await asyncio.to_thread(stop_job, action["job_id"])
                await event(client, action["job_id"], "completed", {"reason": "cancelled"})
        for job_id in active_ids:
            lease = await client.post(
                f"{NYANKOFACE_URL}{NYANKOFACE_API_PREFIX}/v1/workers/{worker_id}/jobs/{job_id}/lease",
                headers=auth_headers(),
            )
            if lease.status_code == 409:
                await asyncio.to_thread(stop_job, job_id)
        if len(active_ids) < MAX_GPU_JOBS:
            claim = await client.post(
                f"{NYANKOFACE_URL}{NYANKOFACE_API_PREFIX}/v1/workers/{worker_id}/jobs/claim",
                headers=auth_headers(),
            )
            if claim.status_code == 200:
                claimed = claim.json()
                with _state_lock:
                    _active_jobs.add(claimed["id"])
                asyncio.create_task(run_claimed_job(client, claimed))
            elif claim.status_code != 204:
                claim.raise_for_status()
        await asyncio.sleep(POLL_SECONDS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not FAKE_EXECUTOR:
        await asyncio.to_thread(load_runtime_state)
    task = asyncio.create_task(poll_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="NyankoFace GPU worker", lifespan=lifespan)


def authorize_runtime(job_id: str, authorization: str | None) -> dict[str, str]:
    with _state_lock:
        runtime = _running.get(job_id)
    if not runtime:
        raise HTTPException(status_code=404, detail="Runtime is not active")
    expected = f"Bearer {runtime['runtime_token']}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Runtime credential is invalid")
    return runtime


@app.api_route(
    "/runtime/{job_id}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
)
async def runtime_http(
    request: Request,
    job_id: str,
    path: str,
    authorization: str | None = Header(default=None),
):
    runtime = authorize_runtime(job_id, authorization)
    if runtime["container"] == "fake":
        return HTMLResponse(
            f"<h1>NyankoFace GPU worker E2E</h1><p>{runtime['owner']}/{runtime['repo']}</p>"
        )
    target = f"http://{runtime['container']}:7860/{path}"
    body = await request.body()
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {"host", "content-length", "authorization", "connection"}
    }
    client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=None))
    upstream = await client.send(
        client.build_request(
            request.method, target, params=request.query_params, headers=headers, content=body
        ),
        stream=True,
    )
    response_headers = MutableHeaders()
    for key, value in upstream.headers.items():
        if key.lower() not in {"content-length", "transfer-encoding", "connection"}:
            response_headers.append(key, value)

    async def stream_body():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        stream_body(),
        status_code=upstream.status_code,
        headers=dict(response_headers),
        media_type=upstream.headers.get("content-type"),
    )


@app.websocket("/runtime/{job_id}/{path:path}")
async def runtime_websocket(websocket: WebSocket, job_id: str, path: str):
    runtime = authorize_runtime(job_id, websocket.headers.get("authorization"))
    if runtime["container"] == "fake":
        await websocket.accept()
        await websocket.send_text("nyankoface-gpu-worker-e2e")
        await websocket.close()
        return
    query = f"?{websocket.url.query}" if websocket.url.query else ""
    target = f"ws://{runtime['container']}:7860/{path}{query}"
    protocols = [
        value.strip()
        for value in websocket.headers.get("sec-websocket-protocol", "").split(",")
        if value.strip()
    ]
    try:
        async with websockets.connect(
            target,
            subprotocols=protocols or None,
            open_timeout=15,
            max_size=None,
        ) as upstream:
            await websocket.accept(subprotocol=upstream.subprotocol)

            async def client_to_upstream():
                try:
                    while True:
                        message = await websocket.receive()
                        if message["type"] == "websocket.disconnect":
                            break
                        if message.get("text") is not None:
                            await upstream.send(message["text"])
                        elif message.get("bytes") is not None:
                            await upstream.send(message["bytes"])
                except (WebSocketDisconnect, RuntimeError):
                    pass

            async def upstream_to_client():
                try:
                    async for message in upstream:
                        if isinstance(message, bytes):
                            await websocket.send_bytes(message)
                        else:
                            await websocket.send_text(message)
                except websockets.ConnectionClosed:
                    pass

            _, pending = await asyncio.wait(
                [
                    asyncio.create_task(client_to_upstream()),
                    asyncio.create_task(upstream_to_client()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
    except (OSError, websockets.InvalidHandshake, asyncio.TimeoutError):
        await websocket.close(code=1013)


@app.get("/healthz")
async def healthz():
    return {
        "status": "ok",
        "worker": WORKER_NAME,
        "enrolled": bool(_credential),
        "running_jobs": len(_running),
        "fake_executor": FAKE_EXECUTOR,
    }
