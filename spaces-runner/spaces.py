"""Space lifecycle management: clone, build, run, stop, status, list.

Docker access is lazy: importing this module (and the whole app) must not
require a reachable Docker daemon. The client is only created on first use,
so `python -m py_compile` / plain imports work in sandboxes without
/var/run/docker.sock.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import docker
from docker.errors import NotFound, APIError

import config
import space_environment
import forgejo

_docker_client: "docker.DockerClient | None" = None
_docker_lock = threading.Lock()
_capacity_lock = threading.Lock()


def get_docker_client() -> docker.DockerClient:
    global _docker_client
    if _docker_client is None:
        with _docker_lock:
            if _docker_client is None:
                _docker_client = docker.from_env()
    return _docker_client


def sanitize(value: str) -> str:
    """Lowercase and strip anything that isn't alnum/-/_ for use in docker names/tags."""
    value = value.lower()
    value = re.sub(r"[^a-z0-9_.-]", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "x"


def container_name(owner: str, repo: str) -> str:
    return f"nyankoface-space-{sanitize(owner)}-{sanitize(repo)}"


def image_tag(owner: str, repo: str) -> str:
    return f"nyankoface-space-{sanitize(owner)}-{sanitize(repo)}:latest"


@dataclass
class SpaceState:
    status: str = "stopped"  # stopped | building | running | error
    error: str | None = None
    last_access: float = field(default_factory=time.time)
    revision: str | None = None
    generation: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


class SpaceRegistry:
    """In-memory state tracker for spaces this process has touched."""

    def __init__(self) -> None:
        self._states: dict[tuple[str, str], SpaceState] = {}
        self._guard = threading.Lock()

    def get(self, owner: str, repo: str) -> SpaceState:
        key = (owner, repo)
        with self._guard:
            if key not in self._states:
                self._states[key] = SpaceState()
            return self._states[key]

    def touch(self, owner: str, repo: str) -> None:
        self.get(owner, repo).last_access = time.time()

    def all_keys(self) -> list[tuple[str, str]]:
        with self._guard:
            return list(self._states.keys())


registry = SpaceRegistry()

DEFAULT_DOCKERFILE = """\
FROM python:3.10-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg git libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY . .
RUN pip install --no-cache-dir -r requirements.txt \\
    && (python -c "import gradio" 2>/dev/null || pip install --no-cache-dir gradio)
RUN {gradio_install}
ENV GRADIO_SERVER_NAME=0.0.0.0
ENV GRADIO_ROOT_PATH=/run/{owner}/{repo}
EXPOSE 7860
CMD ["python", {app_file}]
"""


def _run(cmd: list[str], cwd: str | None = None, timeout: int = 300) -> None:
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"command {' '.join(cmd)} failed (rc={proc.returncode}):\n{proc.stderr[-4000:]}"
        )


def _clone_repo(
    owner: str,
    repo: str,
    token: str | None,
    dest: str,
    revision: str | None = None,
) -> None:
    url = forgejo.clone_url(owner, repo, token)
    try:
        _run(["git", "clone", "--depth", "1", url, dest], timeout=300)
    except RuntimeError:
        if token:
            # fall back to anonymous clone for public repos where token auth
            # itself might be the problem (e.g. revoked token, LAN quirks).
            anon_url = forgejo.clone_url(owner, repo, None)
            _run(["git", "clone", "--depth", "1", anon_url, dest], timeout=300)
        else:
            raise
    if revision:
        _run(
            ["git", "fetch", "--depth", "1", "origin", revision],
            cwd=dest,
            timeout=300,
        )
        _run(["git", "checkout", "--detach", "FETCH_HEAD"], cwd=dest)


def _ensure_dockerfile(build_dir: str, owner: str, repo: str) -> None:
    dockerfile_path = Path(build_dir) / "Dockerfile"
    if dockerfile_path.exists():
        return
    requirements_path = Path(build_dir) / "requirements.txt"
    if not requirements_path.exists():
        requirements_path.write_text("gradio\n", encoding="utf-8")
    app_file = "app.py"
    sdk_version: str | None = None
    readme_path = Path(build_dir) / "README.md"
    if readme_path.exists():
        readme = readme_path.read_text(encoding="utf-8", errors="replace")[:12000]
        app_match = re.search(r"(?m)^app_file:\s*['\"]?([^'\"\r\n]+)", readme)
        version_match = re.search(
            r"(?m)^sdk_version:\s*['\"]?([0-9][0-9A-Za-z_.-]*)", readme
        )
        if app_match:
            candidate = app_match.group(1).strip()
            if re.fullmatch(r"[A-Za-z0-9_./-]+\.py", candidate) and ".." not in candidate:
                app_file = candidate
        if version_match:
            sdk_version = version_match.group(1)

    if sdk_version:
        major = int(sdk_version.split(".", 1)[0])
        if major <= 3:
            web_stack = "'pydantic<2' 'fastapi==0.95.2' 'starlette==0.27.0'"
        elif major == 4:
            web_stack = "'pydantic<2.11' 'fastapi==0.112.4' 'starlette==0.38.6'"
        else:
            web_stack = "'pydantic<2.11' 'fastapi==0.115.6' 'starlette==0.41.3'"
        gradio_install = (
            "pip install --no-cache-dir 'huggingface_hub<1.0' "
            f"{web_stack} 'gradio=={sdk_version}'"
        )
    else:
        gradio_install = "true"
    content = DEFAULT_DOCKERFILE.format(
        owner=sanitize(owner),
        repo=sanitize(repo),
        gradio_install=gradio_install,
        app_file=json.dumps(app_file),
    )
    dockerfile_path.write_text(content, encoding="utf-8")


def _remove_image(client: docker.DockerClient, image_id: str | None) -> None:
    if not image_id:
        return
    try:
        client.images.remove(image=image_id, force=True)
    except (NotFound, APIError):
        pass


def _build_and_run(
    owner: str,
    repo: str,
    token: str | None,
    revision: str | None = None,
    generation: int = 0,
) -> None:
    state = registry.get(owner, repo)
    build_dir = tempfile.mkdtemp(prefix="nyankoface-space-build-")
    client: docker.DockerClient | None = None
    built_image_id: str | None = None
    deployed = False
    obsolete_image_ids: list[str] = []
    try:
        with state.lock:
            if state.generation != generation:
                return
            state.status = "building"
            state.error = None

        clone_target = str(Path(build_dir) / "src")
        _clone_repo(owner, repo, token, clone_target, revision)
        _ensure_dockerfile(clone_target, owner, repo)

        client = get_docker_client()
        tag = f"{image_tag(owner, repo)}-generation-{generation}"
        name = container_name(owner, repo)

        image, _logs = client.images.build(
            path=clone_target,
            tag=tag,
            rm=True,
            forcerm=True,
        )
        built_image_id = image.id

        # Capacity is enforced only when the new image is ready to launch, so
        # an existing Space remains available during a potentially slow build.
        with _capacity_lock:
            with state.lock:
                if state.generation != generation:
                    return
                _evict_lru_if_needed(owner, repo)

                # Remove any stale container with the same name first.
                try:
                    old = client.containers.get(name)
                    old_image_id = str(getattr(getattr(old, "image", None), "id", ""))
                    if old_image_id and old_image_id != built_image_id:
                        obsolete_image_ids.append(old_image_id)
                    old.remove(force=True)
                except NotFound:
                    pass

                runtime_environment = space_environment.runtime_values(owner, repo)
                client.containers.run(
                    image.id,
                    name=name,
                    detach=True,
                    network=config.DOCKER_NETWORK,
                    labels={
                        config.SPACE_LABEL_KEY: config.SPACE_LABEL_VALUE,
                        config.OWNER_LABEL_KEY: owner,
                        config.REPO_LABEL_KEY: repo,
                        config.GENERATION_LABEL_KEY: str(generation),
                        config.REVISION_LABEL_KEY: revision or "",
                    },
                    mem_limit=config.MEMORY_LIMIT,
                    environment=runtime_environment,
                    restart_policy={"Name": "unless-stopped"},
                )
                deployed = True

                state.status = "running"
                state.error = None
                state.revision = revision
                state.last_access = time.time()
        for obsolete_image_id in obsolete_image_ids:
            _remove_image(client, obsolete_image_id)
    except Exception as exc:  # noqa: BLE001 - surfaced via status endpoint
        with state.lock:
            if state.generation == generation:
                state.status = "error"
                state.error = str(exc)[-2000:]
    finally:
        if client is not None and built_image_id and not deployed:
            _remove_image(client, built_image_id)
        shutil.rmtree(build_dir, ignore_errors=True)


def start_space(
    owner: str,
    repo: str,
    token: str | None,
    revision: str | None = None,
) -> dict:
    state = registry.get(owner, repo)

    # If already running (per docker, source of truth), report it.
    live_status = probe_container_status(owner, repo)
    with state.lock:
        if live_status == "running" and (
            revision is None or state.revision == revision
        ):
            state.status = "running"
            state.error = None
            return {
                "status": "running",
                "url": f"/run/{owner}/{repo}/",
                "revision": state.revision,
                "generation": state.generation,
            }

        if state.status == "building":
            return {"status": "building", "generation": state.generation}

        state.generation += 1
        generation = state.generation
        state.status = "building"
        state.error = None

    thread = threading.Thread(
        target=_build_and_run,
        args=(owner, repo, token, revision, generation),
        daemon=True,
    )
    thread.start()
    return {
        "status": "building",
        "revision": revision,
        "generation": generation,
    }


def _evict_lru_if_needed(starting_owner: str, starting_repo: str) -> list[str]:
    """Keep the running set below the configured cap by stopping the LRU Space."""
    evicted: list[str] = []
    running = [
        item for item in list_spaces()
        if item["status"] == "running"
        and (item["owner"], item["repo"]) != (starting_owner, starting_repo)
    ]
    while len(running) >= config.MAX_RUNNING_SPACES:
        oldest = min(
            running,
            key=lambda item: registry.get(item["owner"], item["repo"]).last_access,
        )
        stop_space(oldest["owner"], oldest["repo"])
        evicted.append(f"{oldest['owner']}/{oldest['repo']}")
        running.remove(oldest)
    return evicted


def probe_container_status(owner: str, repo: str) -> str:
    """Ask docker directly for the container's real state."""
    return str(probe_container_runtime(owner, repo).get("status") or "stopped")


def probe_container_runtime(owner: str, repo: str) -> dict:
    """Read liveness and immutable deployment identity from Docker labels."""
    try:
        client = get_docker_client()
        container = client.containers.get(container_name(owner, repo))
        if container.status != "running":
            return {"status": "stopped"}
        labels = dict(getattr(container, "labels", None) or {})
        generation_value = labels.get(config.GENERATION_LABEL_KEY)
        try:
            generation = int(generation_value)
        except (TypeError, ValueError):
            generation = None
        revision = str(labels.get(config.REVISION_LABEL_KEY) or "") or None
        return {
            "status": "running",
            "generation": generation,
            "revision": revision,
        }
    except NotFound:
        return {"status": "stopped"}
    except Exception:  # noqa: BLE001 - docker unreachable etc.
        return {"status": "stopped"}


def get_status(owner: str, repo: str) -> dict:
    state = registry.get(owner, repo)
    with state.lock:
        generation = state.generation
        revision = state.revision
        if state.status == "building":
            return {
                "status": "building",
                "generation": generation,
                "revision": revision,
            }
        if state.status == "error":
            return {
                "status": "error",
                "error": state.error,
                "generation": generation,
                "revision": revision,
            }

    live = probe_container_runtime(owner, repo)
    if live.get("status") == "running":
        live_generation = live.get("generation")
        live_revision = live.get("revision")
        with state.lock:
            if isinstance(live_generation, int):
                state.generation = live_generation
            if live_revision:
                state.revision = str(live_revision)
            state.status = "running"
            generation = state.generation
            revision = state.revision
        return {
            "status": "running",
            "url": f"/run/{owner}/{repo}/",
            "revision": revision,
            "generation": generation,
        }

    with state.lock:
        state.status = "stopped"
        return {
            "status": "stopped",
            "generation": state.generation,
            "revision": state.revision,
        }


def stop_space(owner: str, repo: str) -> dict:
    state = registry.get(owner, repo)
    with state.lock:
        state.generation += 1
        try:
            client = get_docker_client()
            container = client.containers.get(container_name(owner, repo))
            old_image_id = str(
                getattr(getattr(container, "image", None), "id", "")
            )
            container.stop(timeout=10)
            container.remove(force=True)
            if old_image_id:
                _remove_image(client, old_image_id)
        except NotFound:
            pass
        except APIError as exc:
            state.status = "error"
            state.error = str(exc)
            return {"status": "error", "error": state.error}
        state.status = "stopped"
        state.error = None
        state.revision = None
        return {"status": "stopped"}


def cancel_space_generation(
    owner: str,
    repo: str,
    expected_generation: int,
) -> bool:
    """Invalidate only the deployment generation owned by the caller.

    A timed-out request must not stop a newer deployment that started while
    it was polling. The generation comparison is an atomic ownership check;
    once incremented, an older build thread cannot pass its pre-launch guard.
    """
    state = registry.get(owner, repo)
    with state.lock:
        if state.generation != expected_generation:
            return False
        state.generation += 1
        try:
            client = get_docker_client()
            container = client.containers.get(container_name(owner, repo))
            old_image_id = str(
                getattr(getattr(container, "image", None), "id", "")
            )
            container.stop(timeout=10)
            container.remove(force=True)
            if old_image_id:
                _remove_image(client, old_image_id)
        except NotFound:
            pass
        except APIError as exc:
            state.status = "error"
            state.error = str(exc)
            state.revision = None
            return True
        state.status = "stopped"
        state.error = None
        state.revision = None
        return True


def list_spaces() -> list[dict]:
    try:
        client = get_docker_client()
    except Exception:  # noqa: BLE001
        return []
    containers = client.containers.list(
        all=True, filters={"label": f"{config.SPACE_LABEL_KEY}={config.SPACE_LABEL_VALUE}"}
    )
    result = []
    for c in containers:
        owner = c.labels.get(config.OWNER_LABEL_KEY, "?")
        repo = c.labels.get(config.REPO_LABEL_KEY, "?")
        try:
            generation = int(c.labels.get(config.GENERATION_LABEL_KEY))
        except (TypeError, ValueError):
            generation = None
        result.append(
            {
                "owner": owner,
                "repo": repo,
                "status": "running" if c.status == "running" else "stopped",
                "container": c.name,
                "generation": generation,
                "revision": (
                    str(c.labels.get(config.REVISION_LABEL_KEY) or "") or None
                ),
            }
        )
    return result


def adopt_running_containers() -> None:
    """On startup, sync in-memory state with already-running labeled containers."""
    for item in list_spaces():
        state = registry.get(item["owner"], item["repo"])
        with state.lock:
            state.status = item["status"]
            if isinstance(item.get("generation"), int):
                state.generation = int(item["generation"])
            state.revision = item.get("revision")
            state.last_access = time.time()


async def reap_idle_loop() -> None:
    """Background task: stop containers that have been idle too long."""
    if config.IDLE_TIMEOUT_MINUTES <= 0:
        return
    timeout_seconds = config.IDLE_TIMEOUT_MINUTES * 60
    while True:
        await asyncio.sleep(config.REAPER_INTERVAL_SECONDS)
        now = time.time()
        for owner, repo in registry.all_keys():
            state = registry.get(owner, repo)
            if state.status != "running":
                continue
            if now - state.last_access < timeout_seconds:
                continue
            await asyncio.to_thread(stop_space, owner, repo)
