"""NyankoFace spaces-runner.

FastAPI service that builds & runs Gradio "Space" repos as Docker containers
and reverse-proxies traffic to them. Mounted by the gateway as:

    /runner-api/  -> this app's /api/
    /run/         -> this app's /  (HTTP + WebSocket)

Mutating management calls are accepted only from the NyankoFace frontend, which
checks the caller's Forgejo repository permission before forwarding them.
"""
from __future__ import annotations

import asyncio
import logging
import mimetypes
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import PurePosixPath
from typing import Literal

import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Request, WebSocket
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    Response,
    StreamingResponse,
)
from pydantic import BaseModel, Field

import config
import agent_metrics
import forgejo
import gpu_control
import pages_metadata
import pages_deploy
import pipeline_control
import preview_artifacts
import proxy
import space_api_auth
import spaces
import space_environment

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("spaces-runner")


@asynccontextmanager
async def lifespan(app: FastAPI):
    agent_metrics.initialize()
    gpu_control.initialize()
    pipeline_control.initialize()
    space_environment.initialize()
    try:
        spaces.adopt_running_containers()
    except Exception as exc:  # noqa: BLE001 - docker may not be reachable yet
        logger.warning("could not adopt running containers at startup: %s", exc)
    reaper_task = asyncio.create_task(spaces.reap_idle_loop())
    gpu_reaper_task = asyncio.create_task(gpu_reap_loop())
    pipeline_reconcile_task = asyncio.create_task(pipeline_control.reconcile_loop())
    try:
        yield
    finally:
        reaper_task.cancel()
        gpu_reaper_task.cancel()
        pipeline_reconcile_task.cancel()


app = FastAPI(
    title="NyankoFace spaces-runner",
    version="1.0.0",
    docs_url=None,
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def sanitize_environment_validation_error(
    request: Request,
    exc: RequestValidationError,
):
    path = request.url.path
    if (
        request.method in {"PUT", "PATCH", "DELETE", "POST"}
        and (
            path.startswith("/api/v1/spaces/")
            or path.startswith("/api/spaces/")
        )
        and "/environment" in path
    ):
        # Pydantic errors include an `input` field that may contain plaintext.
        # Do not log or serialize `exc` for this write-only surface.
        return JSONResponse(
            status_code=422,
            content={"detail": {
                "code": "invalid_environment_request",
                "message": "The environment request is invalid.",
                "retry_safe": True,
            }},
        )
    from fastapi.exception_handlers import request_validation_exception_handler
    return await request_validation_exception_handler(request, exc)


@app.get("/api/docs", include_in_schema=False, response_class=HTMLResponse)
async def api_docs() -> HTMLResponse:
    """Render Swagger UI correctly both directly and below /runner-api/."""
    return get_swagger_ui_html(
        openapi_url="./openapi.json",
        title=f"{app.title} - Swagger UI",
    )


class RepoMetricsTarget(BaseModel):
    owner: str = Field(min_length=1, max_length=100)
    repo: str = Field(min_length=1, max_length=100)


class RepoMetricsBatchRequest(BaseModel):
    repos: list[RepoMetricsTarget] = Field(max_length=48)


class DownloadMetricRequest(BaseModel):
    source: Literal["raw", "lfs", "automation"]
    artifact_path: str | None = Field(default=None, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=200)
    outcome: Literal["success", "failed", "cancelled", "denied", "bot", "health_check"] = "success"


class KnowledgeMetricsTarget(BaseModel):
    owner: str = Field(min_length=1, max_length=100)
    repo: str = Field(min_length=1, max_length=100)
    slug: str = Field(min_length=1, max_length=180)


class KnowledgeMetricsBatchRequest(BaseModel):
    items: list[KnowledgeMetricsTarget] = Field(max_length=200)


class EnrollmentTokenRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    ttl_minutes: int = Field(default=15, ge=1, le=1440)


class WorkerEnrollRequest(BaseModel):
    token: str = Field(min_length=20, max_length=300)


class WorkerRegistrationRequest(BaseModel):
    capabilities: dict = Field(default_factory=dict)
    max_jobs: int = Field(default=1, ge=1, le=16)


class WorkerHeartbeatRequest(BaseModel):
    capabilities: dict = Field(default_factory=dict)
    running_jobs: int = Field(default=0, ge=0, le=16)


class WorkerEventRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    details: dict = Field(default_factory=dict)


class GpuJobRequest(BaseModel):
    owner: str = Field(min_length=1, max_length=100)
    repo: str = Field(min_length=1, max_length=100)
    revision: str = Field(min_length=7, max_length=64)
    requirements: dict = Field(default_factory=lambda: {"gpu": True, "gpu_count": 1})


class SpaceEnvironmentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=127)
    kind: Literal["variable", "secret"]
    value: str = Field(min_length=1, max_length=16384)
    scope: Literal["runtime", "build", "both"] = "runtime"


class SpaceEnvironmentApiUpsertRequest(BaseModel):
    kind: Literal["variable", "secret"]
    # Optional to keep the published v1 payload backwards compatible. New
    # callers should send it as a compare-and-set kind guard.
    expected_kind: Literal["variable", "secret"] | None = None
    value: str = Field(min_length=1, max_length=16384)
    scope: Literal["runtime", "build", "both"] = "runtime"
    enabled: bool = True
    restart: bool = False


class SpaceEnvironmentApiStateRequest(BaseModel):
    enabled: bool
    restart: bool = False


class SpaceEnvironmentApiApplyRequest(BaseModel):
    restart: bool = True
    revision: str | None = Field(
        default=None,
        min_length=7,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{7,64}$",
    )


class PagesDeployRequest(BaseModel):
    method: Literal["gh-pages", "docs", "vitepress"]
    confirmed: bool


class PipelineDispatchRequest(BaseModel):
    workflow: str = Field(min_length=1, max_length=255)
    ref: str = Field(default="main", min_length=1, max_length=255)
    environment: Literal["preview", "staging", "production"] = "staging"
    inputs: dict[str, str] = Field(default_factory=dict, max_length=20)


def pipeline_http_error(exc: pipeline_control.PipelineError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "code": exc.code,
            "message": str(exc),
            "retry_safe": exc.retry_safe,
        },
    )


def authenticated_agent(authorization: str | None):
    prefix = "Bearer "
    api_key = authorization[len(prefix):].strip() if authorization and authorization.startswith(prefix) else None
    agent = agent_metrics.authenticate(api_key)
    if not agent:
        raise HTTPException(status_code=401, detail="A valid agent Bearer token is required")
    return agent


def require_frontend_control(control_token: str | None) -> None:
    """Reject browser-direct runner mutations.

    The Forgejo admin token is shared read-only with the frontend and runner;
    it is never sent to a browser. The frontend uses it only after verifying
    the signed-in Forgejo user's push permission for the target repository.
    """
    expected = config.CONTROL_TOKEN or config.read_forgejo_token()
    if not expected or not control_token or not secrets.compare_digest(control_token, expected):
        raise HTTPException(status_code=403, detail="Space control must be authorized by NyankoFace")


def authenticated_worker(authorization: str | None):
    prefix = "Bearer "
    credential = (
        authorization[len(prefix):].strip()
        if authorization and authorization.startswith(prefix)
        else None
    )
    worker = gpu_control.authenticate(credential or "")
    if not worker:
        raise HTTPException(status_code=401, detail="A valid worker Bearer credential is required")
    return worker


async def gpu_reap_loop() -> None:
    while True:
        await asyncio.sleep(30)
        await asyncio.to_thread(gpu_control.reap_expired)


async def verify_repo(owner: str, repo: str) -> None:
    try:
        await forgejo.get_repo_info(owner, repo, config.read_forgejo_token())
    except forgejo.ForgejoError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


async def verify_public_repo(owner: str, repo: str) -> None:
    try:
        info = await forgejo.get_repo_info(owner, repo, config.read_forgejo_token())
    except forgejo.ForgejoError as exc:
        raise HTTPException(status_code=404, detail="The public repository was not found") from exc
    if info.get("private") is True:
        raise HTTPException(status_code=404, detail="The public repository was not found")


def metric_actor_kind(request: Request) -> str:
    hinted = request.headers.get("X-NyankoFace-Actor")
    if hinted in {"anonymous", "authenticated", "agent", "system"}:
        return hinted
    return "authenticated" if request.cookies.get("nyankoface_session") else "anonymous"


async def start_space_control(
    owner: str, repo: str, token: str, *, preflight_retry_safe: bool = True,
) -> dict:
    try:
        await forgejo.verify_space_repo(owner, repo, token)
        topics = await forgejo.get_repo_topics(owner, repo, token)
        if not isinstance(topics, list) or any(
            not isinstance(topic, str) for topic in topics
        ):
            raise ValueError("Forgejo returned invalid repository topics")
    except forgejo.ForgejoError as exc:
        raise space_api_auth.api_error(
            404, "space_not_found", "The Space was not found or is not accessible.",
            retry_safe=preflight_retry_safe,
        ) from exc
    except (httpx.HTTPError, ValueError, AttributeError, TypeError) as exc:
        raise space_api_auth.api_error(
            503, "forgejo_unavailable", "Could not verify the Space.",
            retry_safe=preflight_retry_safe,
        ) from exc

    if config.GPU_WORKERS_ENABLED and "gpu" in topics:
        try:
            gpu_settings = await asyncio.to_thread(
                space_environment.list_settings, owner, repo,
            )
        except Exception as exc:
            raise space_api_auth.api_error(
                503,
                "space_environment_unavailable",
                "Could not inspect the Space environment.",
                retry_safe=preflight_retry_safe,
            ) from exc
        if gpu_settings:
            raise space_api_auth.api_error(
                409,
                "gpu_secret_delivery_unavailable",
                "Secure GPU environment delivery is not configured for this worker.",
            )
        try:
            revision = await forgejo.get_default_revision(owner, repo, token)
        except (
            forgejo.ForgejoError, httpx.HTTPError, ValueError, AttributeError, TypeError,
        ) as exc:
            raise space_api_auth.api_error(
                503, "forgejo_unavailable", "Could not resolve the Space revision.",
                retry_safe=preflight_retry_safe,
            ) from exc
        minimum_vram = 0
        for topic in topics:
            if topic.startswith("vram-") and topic.endswith("gb"):
                try:
                    minimum_vram = int(topic[5:-2]) * 1024
                except ValueError:
                    pass
        requirements = {
            "gpu": True,
            "min_vram_mb": minimum_vram,
            "features": ["nvidia"] if "nvidia" in topics or "cuda" in topics else [],
        }

        async def enqueue() -> dict:
            result = await asyncio.to_thread(
                gpu_control.enqueue_job,
                owner,
                repo,
                revision,
                requirements,
            )
            if (
                not isinstance(result, dict)
                or not isinstance(result.get("status"), str)
                or result.get("id") is None
                or not str(result["id"])
            ):
                raise space_api_auth.api_error(
                    502,
                    "invalid_gpu_job_response",
                    "The remote GPU queue returned an invalid job.",
                    retry_safe=False,
                )
            return result

        job = await enqueue()
        if job["status"] in {"cancel_requested", "stopping"}:
            await wait_for_gpu_cancellation(
                str(job["id"]), retry_safe=preflight_retry_safe,
            )
            job = await enqueue()
            if job["status"] in {"cancel_requested", "stopping"}:
                raise space_api_auth.api_error(
                    409,
                    "gpu_start_interrupted",
                    "The remote GPU Space was stopped while starting.",
                    retry_safe=True,
                )
        return {
            "status": job["status"],
            "execution": "remote-gpu",
            "job_id": str(job["id"]),
            "revision": revision,
        }

    result = await asyncio.to_thread(spaces.start_space, owner, repo, token)
    result["execution"] = "local-cpu"
    return result


async def stop_space_control(owner: str, repo: str) -> dict:
    if config.GPU_WORKERS_ENABLED:
        job = await asyncio.to_thread(gpu_control.cancel_repo_job, owner, repo)
        if job:
            return {
                "status": job["status"],
                "execution": "remote-gpu",
                "job_id": str(job["id"]),
            }
    result = await asyncio.to_thread(spaces.stop_space, owner, repo)
    if result.get("status") == "error":
        raise space_api_auth.api_error(
            502,
            "space_stop_failed",
            str(result.get("error") or "The Space could not be stopped."),
            retry_safe=True,
        )
    return result


async def wait_for_gpu_cancellation(
    job_id: str,
    timeout_seconds: float = 30.0,
    *,
    retry_safe: bool = False,
) -> None:
    """Wait until a remote GPU cancellation reaches a terminal state."""
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise space_api_auth.api_error(
                504,
                "gpu_cancel_timeout",
                "The remote GPU job did not stop before the cancellation timeout.",
                retry_safe=retry_safe,
            )
        try:
            job = await asyncio.wait_for(
                gpu_control.get_job_async(job_id),
                timeout=remaining,
            )
        except TimeoutError as exc:
            raise space_api_auth.api_error(
                504,
                "gpu_cancel_timeout",
                "The remote GPU job did not stop before the cancellation timeout.",
                retry_safe=retry_safe,
            ) from exc
        except Exception as exc:
            raise space_api_auth.api_error(
                503,
                "gpu_job_unavailable",
                "Could not confirm that the remote GPU job stopped.",
                retry_safe=retry_safe,
            ) from exc
        if not isinstance(job, dict) or not isinstance(job.get("status"), str):
            raise space_api_auth.api_error(
                502,
                "invalid_gpu_job_response",
                "The remote GPU job returned an invalid status.",
                retry_safe=retry_safe,
            )
        if job["status"] in {"completed", "failed", "cancelled"}:
            return
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise space_api_auth.api_error(
                504,
                "gpu_cancel_timeout",
                "The remote GPU job did not stop before the cancellation timeout.",
                retry_safe=retry_safe,
            )
        await asyncio.sleep(min(0.25, remaining))


# ---------------------------------------------------------------------------
# Management API (mounted at /runner-api/ -> here at /api/)
# ---------------------------------------------------------------------------

@app.post("/api/spaces/{owner}/{repo}/start")
async def api_start_space(
    owner: str,
    repo: str,
    x_nyankoface_control_token: str | None = Header(default=None),
):
    require_frontend_control(x_nyankoface_control_token)
    return await start_space_control(owner, repo, config.read_forgejo_token())


@app.get("/api/spaces/{owner}/{repo}/environment")
async def api_list_space_environment(
    owner: str,
    repo: str,
    x_nyankoface_control_token: str | None = Header(default=None),
):
    require_frontend_control(x_nyankoface_control_token)
    return {"items": await asyncio.to_thread(space_environment.list_settings, owner, repo)}


@app.put("/api/spaces/{owner}/{repo}/environment")
async def api_put_space_environment(
    owner: str,
    repo: str,
    payload: SpaceEnvironmentRequest,
    x_nyankoface_control_token: str | None = Header(default=None),
    x_nyankoface_actor: str | None = Header(default=None),
):
    require_frontend_control(x_nyankoface_control_token)
    try:
        item = await upsert_space_environment_setting(
            owner,
            repo,
            payload.name,
            payload.kind,
            payload.value,
            x_nyankoface_actor or "authorized-forgejo-user",
            True,
            payload.scope,
            config.read_forgejo_token() or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except pipeline_control.PipelineError as exc:
        raise pipeline_http_error(exc) from exc
    return public_environment_item(item)


@app.delete("/api/spaces/{owner}/{repo}/environment/{name}")
async def api_delete_space_environment(
    owner: str,
    repo: str,
    name: str,
    x_nyankoface_control_token: str | None = Header(default=None),
    x_nyankoface_actor: str | None = Header(default=None),
):
    require_frontend_control(x_nyankoface_control_token)
    try:
        deleted = await delete_space_environment_setting(
            owner,
            repo,
            name,
            x_nyankoface_actor or "authorized-forgejo-user",
            config.read_forgejo_token() or "",
        )
    except (ValueError, pipeline_control.PipelineError) as exc:
        if isinstance(exc, pipeline_control.PipelineError):
            raise pipeline_http_error(exc) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Environment entry was not found")
    return {"deleted": True, "name": name.upper()}


@app.patch("/api/spaces/{owner}/{repo}/environment/{name}")
async def api_set_space_environment_state(
    owner: str,
    repo: str,
    name: str,
    payload: SpaceEnvironmentApiStateRequest,
    x_nyankoface_control_token: str | None = Header(default=None),
    x_nyankoface_actor: str | None = Header(default=None),
):
    require_frontend_control(x_nyankoface_control_token)
    try:
        item = await set_space_environment_enabled(
            owner,
            repo,
            name,
            payload.enabled,
            x_nyankoface_actor or "authorized-forgejo-user",
            config.read_forgejo_token() or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except pipeline_control.PipelineError as exc:
        raise pipeline_http_error(exc) from exc
    if not item:
        raise HTTPException(status_code=404, detail="Environment entry was not found")
    return public_environment_item(item)


async def _probe_space_http_readiness(
    owner: str,
    repo: str,
) -> tuple[bool, str]:
    """Confirm that the same HTTP endpoint used by the proxy is responsive."""
    url = f"http://{spaces.container_name(owner, repo)}:{config.CONTAINER_PORT}/"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(2.0),
            follow_redirects=False,
        ) as client:
            async with client.stream("GET", url) as response:
                status_code = response.status_code
        if status_code < 500:
            return True, f"HTTP {status_code}"
        return False, f"HTTP {status_code}"
    except (httpx.HTTPError, OSError) as exc:
        return False, exc.__class__.__name__


async def restart_space_environment(
    owner: str,
    repo: str,
    token: str,
    revision: str | None = None,
    *,
    wait_until_ready: bool = False,
) -> dict:
    topics = await forgejo.get_repo_topics(owner, repo, token)
    if config.GPU_WORKERS_ENABLED and "gpu" in topics:
        raise space_api_auth.api_error(
            409,
            "gpu_secret_delivery_unavailable",
            "Remote GPU environment delivery is not configured; no plaintext fallback is allowed.",
        )
    try:
        await asyncio.get_running_loop().run_in_executor(None, space_environment.runtime_values, owner, repo)
    except RuntimeError as exc:
        raise space_api_auth.api_error(422, "environment_limit",
                                       "Space environment delivery limit exceeded.") from exc
    stopped = await asyncio.to_thread(spaces.stop_space, owner, repo)
    if stopped.get("status") == "error":
        raise space_api_auth.api_error(
            502,
            "space_stop_failed",
            str(stopped.get("error") or "The previous Space could not be stopped."),
            retry_safe=True,
        )
    result = await asyncio.to_thread(
        spaces.start_space,
        owner,
        repo,
        token,
        revision,
    )
    generation = result.get("generation")
    result = {
        key: value
        for key, value in result.items()
        if key != "generation"
    }
    if wait_until_ready:
        if not isinstance(generation, int):
            raise space_api_auth.api_error(
                502,
                "space_generation_missing",
                "The Space runner did not return a deployment generation.",
            )
        deadline = (
            asyncio.get_running_loop().time()
            + config.SPACE_DEPLOY_TIMEOUT_SECONDS
        )
        readiness_reason = "the application has not answered yet"
        try:
            while True:
                status = await asyncio.to_thread(
                    spaces.get_status,
                    owner,
                    repo,
                )
                observed_generation = status.get("generation")
                if observed_generation != generation:
                    raise space_api_auth.api_error(
                        409,
                        "space_deployment_superseded",
                        "A newer Space deployment superseded this request.",
                    )
                if status.get("status") == "running":
                    if revision and status.get("revision") != revision:
                        await asyncio.to_thread(
                            spaces.cancel_space_generation,
                            owner,
                            repo,
                            generation,
                        )
                        raise space_api_auth.api_error(
                            502,
                            "space_revision_mismatch",
                            "The Space started with a different revision.",
                        )
                    ready, readiness_reason = (
                        await _probe_space_http_readiness(owner, repo)
                    )
                    if ready:
                        # Re-check the Docker identity after the network probe
                        # so a replacement cannot satisfy an older request.
                        confirmed = await asyncio.to_thread(
                            spaces.get_status,
                            owner,
                            repo,
                        )
                        if confirmed.get("generation") != generation:
                            raise space_api_auth.api_error(
                                409,
                                "space_deployment_superseded",
                                "A newer Space deployment superseded this request.",
                            )
                        if (
                            confirmed.get("status") == "running"
                            and (
                                not revision
                                or confirmed.get("revision") == revision
                            )
                        ):
                            result = confirmed
                            break
                if status.get("status") == "error":
                    raise space_api_auth.api_error(
                        502,
                        "space_deployment_failed",
                        str(status.get("error") or "The Space build failed."),
                    )
                if status.get("status") == "stopped":
                    raise space_api_auth.api_error(
                        502,
                        "space_deployment_stopped",
                        "The Space container stopped before it became ready.",
                    )
                if asyncio.get_running_loop().time() >= deadline:
                    cancelled = await asyncio.to_thread(
                        spaces.cancel_space_generation,
                        owner,
                        repo,
                        generation,
                    )
                    if not cancelled:
                        raise space_api_auth.api_error(
                            409,
                            "space_deployment_superseded",
                            "A newer Space deployment superseded this request.",
                        )
                    raise space_api_auth.api_error(
                        504,
                        "space_readiness_timeout",
                        "The Space did not become HTTP-ready before the deployment "
                        f"timeout ({readiness_reason}).",
                    )
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            cleanup = asyncio.create_task(asyncio.to_thread(
                spaces.cancel_space_generation, owner, repo, generation,
            ))
            await drain_cancellation(cleanup)
            raise
    return {
        **{
            key: value
            for key, value in result.items()
            if key != "generation"
        },
        "execution": "local-cpu",
    }


def public_environment_item(item: dict) -> dict:
    return {key: value for key, value in item.items() if key not in {"value", "generation"}}


async def drain_cancellation(task: asyncio.Task, *, prefer_cancellation: bool = False):
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except BaseException:
            break
    if cancelled and prefer_cancellation:
        raise asyncio.CancelledError
    return task.result(), cancelled


async def release_environment_lock(session) -> None:
    release = asyncio.create_task(asyncio.to_thread(space_environment.release_mutation_lock, session))
    _, cancelled = await drain_cancellation(release)
    if cancelled:
        raise asyncio.CancelledError


async def run_serialized_environment_operation(owner, repo, name, operation, *, cancel_operation=False):
    owner, repo = owner.strip().casefold(), repo.strip().casefold()
    acquire = asyncio.create_task(asyncio.to_thread(
        space_environment.acquire_mutation_lock, owner, repo, name,
    ))
    try:
        session, cancelled = await drain_cancellation(acquire)
    except TimeoutError as exc:
        raise ValueError(str(exc)) from exc
    if cancelled:
        await release_environment_lock(session)
        raise asyncio.CancelledError
    mutation = asyncio.create_task(operation())
    try:
        if cancel_operation:
            try:
                return await mutation
            except asyncio.CancelledError:
                await drain_cancellation(mutation)
                raise
        result, _ = await drain_cancellation(mutation, prefer_cancellation=True)
        return result
    finally:
        await release_environment_lock(session)


def serialized_environment_mutation(function):
    @wraps(function)
    async def wrapped(owner, repo, name, *args, **kwargs):
        owner, repo = owner.strip().casefold(), repo.strip().casefold()
        return await run_serialized_environment_operation(
            owner, repo, name,
            lambda: function(owner, repo, name, *args, **kwargs),
        )
    return wrapped


async def restore_space_environment_snapshot(
    owner: str,
    repo: str,
    name: str,
    previous: dict | None,
    expected_generation: int,
) -> bool:
    return await asyncio.to_thread(
        space_environment.restore_if_current,
        owner,
        repo,
        name,
        expected_generation,
        previous,
    )


@serialized_environment_mutation
async def upsert_space_environment_setting(
    owner: str,
    repo: str,
    name: str,
    kind: str,
    value: str,
    actor: str,
    enabled: bool,
    scope: str,
    token: str,
    expected_kind: str | None = None,
) -> dict:
    previous = await asyncio.to_thread(
        space_environment.get_setting,
        owner,
        repo,
        name,
    )
    item = await asyncio.to_thread(
        space_environment.upsert,
        owner,
        repo,
        name,
        kind,
        value,
        actor,
        enabled,
        scope,
        expected_kind,
    )
    # The public item intentionally redacts secret plaintext. Keep the
    # submitted value in a separate trusted object for native Forgejo sync.
    internal_item = {**item, "value": value}
    try:
        await reconcile_build_setting(
            owner,
            repo,
            token,
            previous,
            internal_item,
        )
    except pipeline_control.PipelineError as exc:
        if exc.retry_safe:
            await restore_space_environment_snapshot(
                owner, repo, name, previous, int(item["generation"]),
            )
        raise
    except Exception:
        await restore_space_environment_snapshot(
            owner, repo, name, previous, int(item["generation"]),
        )
        raise
    current = await asyncio.to_thread(space_environment.get_setting, owner, repo, name)
    if (current or {}).get("generation") != item.get("generation"):
        await reconcile_build_setting(owner, repo, token, internal_item, current)
    return item


@serialized_environment_mutation
async def set_space_environment_enabled(
    owner: str,
    repo: str,
    name: str,
    enabled: bool,
    actor: str,
    token: str,
) -> dict | None:
    previous = await asyncio.to_thread(
        space_environment.get_setting,
        owner,
        repo,
        name,
    )
    item = await asyncio.to_thread(
        space_environment.set_enabled,
        owner,
        repo,
        name,
        enabled,
        actor,
    )
    if not item:
        return None
    try:
        synced = await asyncio.to_thread(
            space_environment.get_setting,
            owner,
            repo,
            name,
        )
        await reconcile_build_setting(owner, repo, token, previous, synced)
    except pipeline_control.PipelineError as exc:
        if exc.retry_safe:
            await restore_space_environment_snapshot(
                owner, repo, name, previous, int(item["generation"]),
            )
        raise
    except Exception:
        await restore_space_environment_snapshot(
            owner, repo, name, previous, int(item["generation"]),
        )
        raise
    current = await asyncio.to_thread(space_environment.get_setting, owner, repo, name)
    if (current or {}).get("generation") != (synced or {}).get("generation"):
        await reconcile_build_setting(owner, repo, token, synced, current)
    return item


async def reconcile_build_setting(
    owner: str,
    repo: str,
    token: str,
    previous: dict | None,
    current: dict | None,
) -> None:
    previous_build = bool(
        previous and previous.get("scope") in ("build", "both")
    )
    current_build = bool(
        current
        and current.get("enabled", True)
        and current.get("scope") in ("build", "both")
    )
    kind_changed = bool(
        previous
        and current
        and previous.get("kind") != current.get("kind")
    )
    if previous_build and current_build and kind_changed:
        # Stage the new native kind first. If that sync fails, the old native
        # value is still intact and the caller can safely restore its local
        # snapshot. Only remove the old kind after the replacement exists.
        await pipeline_control.sync_build_setting(owner, repo, current, token)
        try:
            await pipeline_control.remove_build_setting(
                owner,
                repo,
                str(previous["name"]),
                str(previous["kind"]),
                token,
            )
        except pipeline_control.PipelineError as exc:
            # The old native value is still authoritative. Remove the staged
            # replacement only after a definite rejection. An unknown removal
            # may have deleted the old value, so preserving the replacement and
            # local generation is the only replay-safe state.
            if exc.retry_safe:
                await pipeline_control.remove_build_setting(
                    owner,
                    repo,
                    str(current["name"]),
                    str(current["kind"]),
                    token,
                )
            raise
        return
    if previous_build and (not current_build or kind_changed):
        await pipeline_control.remove_build_setting(
            owner,
            repo,
            str(previous["name"]),
            str(previous["kind"]),
            token,
        )
    if current_build:
        await pipeline_control.sync_build_setting(owner, repo, current, token)


@serialized_environment_mutation
async def delete_space_environment_setting(
    owner: str,
    repo: str,
    name: str,
    actor: str,
    token: str,
    expected_kind: str | None = None,
) -> bool:
    """Remove a setting without losing secret-redaction metadata on failure.

    Build settings are removed from Forgejo before the encrypted local row.
    If Forgejo is unavailable, the local value remains available for log
    redaction and the delete can be retried safely.
    """
    previous = await asyncio.to_thread(
        space_environment.get_setting_metadata,
        owner,
        repo,
        name,
    )
    if previous is None:
        return False
    if expected_kind is not None and previous.get("kind") != expected_kind:
        raise ValueError(f"Environment entry is not a {expected_kind}")
    await reconcile_build_setting(
        owner,
        repo,
        token,
        previous,
        None,
    )
    deleted = await asyncio.to_thread(
        space_environment.delete,
        owner,
        repo,
        name,
        actor,
        expected_kind,
        previous.get("generation"),
    )
    if deleted:
        return True
    # Another request changed the row after metadata was read. Restore the
    # current native build projection and fail instead of reporting a delete.
    current = await asyncio.to_thread(
        space_environment.get_setting,
        owner,
        repo,
        name,
    )
    await reconcile_build_setting(owner, repo, token, None, current)
    raise ValueError("Environment entry changed during deletion; retry safely")


# ---------------------------------------------------------------------------
# Public automation API. Unlike the browser routes above, these endpoints use
# a Forgejo PAT on every request and never depend on a browser cookie.
# Gateway URL: /runner-api/v1/spaces/{owner}/{repo}/environment
# ---------------------------------------------------------------------------

@app.get("/api/v1/spaces/{owner}/{repo}/environment")
async def api_v1_list_space_environment(
    owner: str,
    repo: str,
    authorization: str | None = Header(default=None),
):
    await space_api_auth.authorize_space_pat(
        authorization,
        owner,
        repo,
        write=False,
    )
    items = await asyncio.to_thread(
        space_environment.list_setting_metadata,
        owner,
        repo,
    )
    return {
        "items": [public_environment_item(item) for item in items],
        "runtime_application": "restart_required_after_change",
    }


@app.get("/api/v1/spaces/{owner}/{repo}/environment/audit")
async def api_v1_list_space_environment_audit(
    owner: str,
    repo: str,
    limit: int = 100,
    authorization: str | None = Header(default=None),
):
    await space_api_auth.authorize_space_pat(
        authorization,
        owner,
        repo,
        write=False,
    )
    return {
        "items": await asyncio.to_thread(
            space_environment.list_audit,
            owner,
            repo,
            limit,
        )
    }


@app.put("/api/v1/spaces/{owner}/{repo}/environment/{name}")
async def api_v1_upsert_space_environment(
    owner: str,
    repo: str,
    name: str,
    payload: SpaceEnvironmentApiUpsertRequest,
    authorization: str | None = Header(default=None),
):
    principal = await space_api_auth.authorize_space_pat(
        authorization,
        owner,
        repo,
        write=True,
    )
    try:
        item = await upsert_space_environment_setting(
            owner,
            repo,
            name,
            payload.kind,
            payload.value,
            principal.login,
            payload.enabled,
            payload.scope,
            principal.token,
            payload.expected_kind,
        )
    except ValueError as exc:
        raise space_api_auth.api_error(422, "invalid_environment_entry", str(exc)) from exc
    except pipeline_control.PipelineError as exc:
        raise pipeline_http_error(exc) from exc
    restart = (
        await restart_space_environment(owner, repo, principal.token)
        if payload.restart
        else None
    )
    return {
        "item": public_environment_item(item),
        "restart_required": not payload.restart,
        "runtime": restart,
    }


@app.patch("/api/v1/spaces/{owner}/{repo}/environment/{name}")
async def api_v1_set_space_environment_state(
    owner: str,
    repo: str,
    name: str,
    payload: SpaceEnvironmentApiStateRequest,
    authorization: str | None = Header(default=None),
):
    principal = await space_api_auth.authorize_space_pat(
        authorization,
        owner,
        repo,
        write=True,
    )
    try:
        item = await set_space_environment_enabled(
            owner,
            repo,
            name,
            payload.enabled,
            principal.login,
            principal.token,
        )
    except ValueError as exc:
        raise space_api_auth.api_error(422, "invalid_environment_entry", str(exc)) from exc
    except pipeline_control.PipelineError as exc:
        raise pipeline_http_error(exc) from exc
    if not item:
        raise space_api_auth.api_error(
            404,
            "environment_entry_not_found",
            "The environment entry was not found.",
        )
    restart = (
        await restart_space_environment(owner, repo, principal.token)
        if payload.restart
        else None
    )
    return {
        "item": public_environment_item(item),
        "restart_required": not payload.restart,
        "runtime": restart,
    }


@app.delete("/api/v1/spaces/{owner}/{repo}/environment/{name}")
async def api_v1_delete_space_environment(
    owner: str,
    repo: str,
    name: str,
    restart: bool = False,
    expected_kind: Literal["variable", "secret"] | None = None,
    authorization: str | None = Header(default=None),
):
    principal = await space_api_auth.authorize_space_pat(
        authorization,
        owner,
        repo,
        write=True,
    )
    try:
        deleted = await delete_space_environment_setting(
            owner,
            repo,
            name,
            principal.login,
            principal.token,
            expected_kind,
        )
    except (ValueError, pipeline_control.PipelineError) as exc:
        if isinstance(exc, pipeline_control.PipelineError):
            raise pipeline_http_error(exc) from exc
        raise space_api_auth.api_error(422, "invalid_environment_entry", str(exc)) from exc
    runtime = (
        await restart_space_environment(owner, repo, principal.token)
        if restart
        else None
    )
    # Deleting an already absent entry is intentionally a successful no-op.
    return {
        "deleted": deleted,
        "name": name.upper(),
        "restart_required": not restart,
        "runtime": runtime,
    }


@app.post("/api/v1/spaces/{owner}/{repo}/environment/apply")
async def api_v1_apply_space_environment(
    owner: str,
    repo: str,
    payload: SpaceEnvironmentApiApplyRequest,
    authorization: str | None = Header(default=None),
):
    principal = await space_api_auth.authorize_space_pat(
        authorization,
        owner,
        repo,
        write=True,
    )
    owner, repo = owner.strip().casefold(), repo.strip().casefold()
    if not payload.restart:
        return {
            "status": "unchanged",
            "restart_required": True,
        }
    runtime = await run_serialized_environment_operation(
        owner, repo, None,
        lambda: restart_space_environment(
            owner, repo, principal.token, payload.revision, wait_until_ready=True,
        ),
        cancel_operation=True,
    )
    return {
        "status": "applied",
        "restart_required": False,
        "runtime": runtime,
    }


# ---------------------------------------------------------------------------
# Forgejo Actions-backed repository CI/CD control plane.
# ---------------------------------------------------------------------------

@app.get("/api/pipelines/{owner}/{repo}")
async def api_pipeline_summary(
    owner: str,
    repo: str,
    x_nyankoface_control_token: str | None = Header(default=None),
):
    require_frontend_control(x_nyankoface_control_token)
    try:
        return await pipeline_control.summary(
            owner,
            repo,
            config.read_forgejo_token() or "",
        )
    except (pipeline_control.PipelineError, forgejo.ForgejoError) as exc:
        if isinstance(exc, pipeline_control.PipelineError):
            raise pipeline_http_error(exc) from exc
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/pipelines/{owner}/{repo}/runs/{run_number}")
async def api_pipeline_run_detail(
    owner: str,
    repo: str,
    run_number: int,
    x_nyankoface_control_token: str | None = Header(default=None),
):
    require_frontend_control(x_nyankoface_control_token)
    try:
        return await pipeline_control.run_detail(
            owner,
            repo,
            run_number,
            config.read_forgejo_token() or "",
        )
    except pipeline_control.PipelineError as exc:
        raise pipeline_http_error(exc) from exc


@app.post("/api/pipelines/{owner}/{repo}/install")
async def api_pipeline_install(
    owner: str,
    repo: str,
    x_nyankoface_control_token: str | None = Header(default=None),
    x_nyankoface_actor: str | None = Header(default=None),
):
    require_frontend_control(x_nyankoface_control_token)
    try:
        return await pipeline_control.install_starter(
            owner,
            repo,
            config.read_forgejo_token() or "",
            x_nyankoface_actor or "authorized-forgejo-user",
        )
    except (pipeline_control.PipelineError, forgejo.ForgejoError) as exc:
        if isinstance(exc, pipeline_control.PipelineError):
            raise pipeline_http_error(exc) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/pipelines/{owner}/{repo}/dispatch")
async def api_pipeline_dispatch(
    owner: str,
    repo: str,
    payload: PipelineDispatchRequest,
    x_nyankoface_control_token: str | None = Header(default=None),
    x_nyankoface_actor: str | None = Header(default=None),
):
    require_frontend_control(x_nyankoface_control_token)
    try:
        return await pipeline_control.dispatch(
            owner,
            repo,
            payload.workflow,
            payload.ref,
            payload.environment,
            payload.inputs,
            config.read_forgejo_token() or "",
            x_nyankoface_actor or "authorized-forgejo-user",
        )
    except pipeline_control.PipelineError as exc:
        raise pipeline_http_error(exc) from exc


@app.post("/api/pipelines/{owner}/{repo}/runs/{run_number}/{action}")
async def api_pipeline_run_action(
    owner: str,
    repo: str,
    run_number: int,
    action: Literal["cancel", "rerun", "approve", "rollback"],
    x_nyankoface_control_token: str | None = Header(default=None),
    x_nyankoface_actor: str | None = Header(default=None),
):
    require_frontend_control(x_nyankoface_control_token)
    try:
        return await pipeline_control.run_action(
            owner,
            repo,
            run_number,
            action,
            config.read_forgejo_token() or "",
            x_nyankoface_actor or "authorized-forgejo-user",
        )
    except pipeline_control.PipelineError as exc:
        raise pipeline_http_error(exc) from exc


@app.post(
    "/api/pipelines/{owner}/{repo}/runs/{run_number}/jobs/{job_id}/rerun"
)
async def api_pipeline_rerun_job(
    owner: str,
    repo: str,
    run_number: int,
    job_id: int,
    x_nyankoface_control_token: str | None = Header(default=None),
    x_nyankoface_actor: str | None = Header(default=None),
):
    require_frontend_control(x_nyankoface_control_token)
    try:
        return await pipeline_control.rerun_job(
            owner,
            repo,
            run_number,
            job_id,
            config.read_forgejo_token() or "",
            x_nyankoface_actor or "authorized-forgejo-user",
        )
    except pipeline_control.PipelineError as exc:
        raise pipeline_http_error(exc) from exc


@app.get("/api/v1/pipelines/{owner}/{repo}")
async def api_v1_pipeline_summary(
    owner: str,
    repo: str,
    authorization: str | None = Header(default=None),
):
    principal = await space_api_auth.authorize_space_pat(
        authorization,
        owner,
        repo,
        write=False,
        require_space=False,
        rate_limit_per_minute=config.PIPELINE_API_RATE_LIMIT_PER_MINUTE,
        rate_limit_namespace="pipelines",
        rate_limit_label="Pipeline API",
    )
    try:
        return await pipeline_control.summary(owner, repo, principal.token)
    except pipeline_control.PipelineError as exc:
        raise pipeline_http_error(exc) from exc


@app.get("/api/v1/pipelines/{owner}/{repo}/runs/{run_number}")
async def api_v1_pipeline_run_detail(
    owner: str,
    repo: str,
    run_number: int,
    authorization: str | None = Header(default=None),
):
    principal = await space_api_auth.authorize_space_pat(
        authorization,
        owner,
        repo,
        write=False,
        require_space=False,
        rate_limit_per_minute=config.PIPELINE_API_RATE_LIMIT_PER_MINUTE,
        rate_limit_namespace="pipelines",
        rate_limit_label="Pipeline API",
    )
    try:
        return await pipeline_control.run_detail(
            owner,
            repo,
            run_number,
            principal.token,
        )
    except pipeline_control.PipelineError as exc:
        raise pipeline_http_error(exc) from exc


@app.get("/api/v1/pipelines/{owner}/{repo}/runs")
async def api_v1_pipeline_runs(
    owner: str,
    repo: str,
    page: int = 1,
    limit: int = 20,
    authorization: str | None = Header(default=None),
):
    principal = await space_api_auth.authorize_space_pat(
        authorization,
        owner,
        repo,
        write=False,
        require_space=False,
        rate_limit_per_minute=config.PIPELINE_API_RATE_LIMIT_PER_MINUTE,
        rate_limit_namespace="pipelines",
        rate_limit_label="Pipeline API",
    )
    try:
        return await pipeline_control.list_runs(
            owner,
            repo,
            principal.token,
            page=max(1, page),
            limit=max(1, min(limit, 50)),
            include_pagination=True,
            reconcile_deployments=False,
        )
    except pipeline_control.PipelineError as exc:
        raise pipeline_http_error(exc) from exc


@app.get("/api/v1/pipelines/{owner}/{repo}/runs/{run_number}/metadata")
async def api_v1_pipeline_run_metadata(
    owner: str,
    repo: str,
    run_number: int,
    authorization: str | None = Header(default=None),
):
    principal = await space_api_auth.authorize_space_pat(
        authorization,
        owner,
        repo,
        write=False,
        require_space=False,
        rate_limit_per_minute=config.PIPELINE_API_RATE_LIMIT_PER_MINUTE,
        rate_limit_namespace="pipelines",
        rate_limit_label="Pipeline API",
    )
    try:
        return await pipeline_control.run_metadata(
            owner,
            repo,
            run_number,
            principal.token,
        )
    except pipeline_control.PipelineError as exc:
        raise pipeline_http_error(exc) from exc


@app.post("/api/v1/pipelines/{owner}/{repo}/install")
async def api_v1_pipeline_install(
    owner: str,
    repo: str,
    authorization: str | None = Header(default=None),
):
    principal = await space_api_auth.authorize_space_pat(
        authorization,
        owner,
        repo,
        write=True,
        require_space=False,
        rate_limit_per_minute=config.PIPELINE_API_RATE_LIMIT_PER_MINUTE,
        rate_limit_namespace="pipelines",
        rate_limit_label="Pipeline API",
    )
    try:
        return await pipeline_control.install_starter(
            owner,
            repo,
            principal.token,
            principal.login,
        )
    except (pipeline_control.PipelineError, forgejo.ForgejoError) as exc:
        if isinstance(exc, pipeline_control.PipelineError):
            raise pipeline_http_error(exc) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc


async def authorize_control_pat(
    authorization: str | None,
    owner: str,
    repo: str,
    *,
    require_space: bool,
    label: str,
) -> space_api_auth.SpaceApiPrincipal:
    return await space_api_auth.authorize_space_pat(
        authorization,
        owner,
        repo,
        write=True,
        require_space=require_space,
        rate_limit_namespace="runtime-control",
        rate_limit_label=label,
    )


@app.post("/api/v1/spaces/{owner}/{repo}/start")
async def api_v1_start_space(
    owner: str,
    repo: str,
    authorization: str | None = Header(default=None),
):
    principal = await authorize_control_pat(
        authorization, owner, repo, require_space=True, label="Space control API",
    )
    return await start_space_control(owner, repo, principal.token)


@app.post("/api/v1/spaces/{owner}/{repo}/stop")
async def api_v1_stop_space(
    owner: str,
    repo: str,
    authorization: str | None = Header(default=None),
):
    await authorize_control_pat(
        authorization, owner, repo, require_space=True, label="Space control API",
    )
    return await stop_space_control(owner, repo)


@app.post("/api/v1/spaces/{owner}/{repo}/restart")
async def api_v1_restart_space(
    owner: str,
    repo: str,
    authorization: str | None = Header(default=None),
):
    principal = await authorize_control_pat(
        authorization, owner, repo, require_space=True, label="Space control API",
    )
    stopped = await stop_space_control(owner, repo)
    if stopped.get("execution") == "remote-gpu" and stopped.get("status") == "cancel_requested":
        job_id = stopped.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            raise space_api_auth.api_error(
                502,
                "invalid_gpu_job_response",
                "The remote GPU cancellation returned an invalid job identifier.",
                retry_safe=False,
            )
        await wait_for_gpu_cancellation(job_id)
    return await start_space_control(
        owner, repo, principal.token, preflight_retry_safe=False,
    )


@app.post("/api/v1/pages/{owner}/{repo}/deploy")
async def api_v1_deploy_pages(
    owner: str,
    repo: str,
    payload: PagesDeployRequest,
    authorization: str | None = Header(default=None),
):
    principal = await authorize_control_pat(
        authorization, owner, repo, require_space=False, label="Pages control API",
    )
    if not payload.confirmed:
        raise space_api_auth.api_error(
            422,
            "confirmation_required",
            "Confirm the repository changes before deploying Pages.",
        )
    try:
        return await pages_deploy.deploy(
            owner, repo, payload.method, principal.token, principal.login,
        )
    except pages_deploy.PagesOutcomeUnknown as exc:
        raise space_api_auth.api_error(
            502,
            "pages_deploy_outcome_unknown",
            "Pages deployment outcome is unknown; inspect the repository before retrying.",
            retry_safe=False,
        ) from exc
    except (forgejo.ForgejoError, httpx.HTTPError, ValueError, AttributeError, TypeError) as exc:
        raise space_api_auth.api_error(
            409, "pages_deploy_rejected", "Pages deployment was rejected.",
            retry_safe=True,
        ) from exc


@app.post("/api/v1/pipelines/{owner}/{repo}/dispatch")
async def api_v1_pipeline_dispatch(
    owner: str,
    repo: str,
    payload: PipelineDispatchRequest,
    authorization: str | None = Header(default=None),
):
    principal = await space_api_auth.authorize_space_pat(
        authorization,
        owner,
        repo,
        write=True,
        require_space=False,
        rate_limit_per_minute=config.PIPELINE_API_RATE_LIMIT_PER_MINUTE,
        rate_limit_namespace="pipelines",
        rate_limit_label="Pipeline API",
    )
    try:
        return await pipeline_control.dispatch(
            owner,
            repo,
            payload.workflow,
            payload.ref,
            payload.environment,
            payload.inputs,
            principal.token,
            principal.login,
        )
    except pipeline_control.PipelineError as exc:
        raise pipeline_http_error(exc) from exc


@app.post("/api/v1/pipelines/{owner}/{repo}/runs/{run_number}/{action}")
async def api_v1_pipeline_run_action(
    owner: str,
    repo: str,
    run_number: int,
    action: Literal["cancel", "rerun", "approve", "rollback"],
    authorization: str | None = Header(default=None),
):
    principal = await space_api_auth.authorize_space_pat(
        authorization,
        owner,
        repo,
        write=True,
        require_space=False,
        rate_limit_per_minute=config.PIPELINE_API_RATE_LIMIT_PER_MINUTE,
        rate_limit_namespace="pipelines",
        rate_limit_label="Pipeline API",
    )
    try:
        return await pipeline_control.run_action(
            owner,
            repo,
            run_number,
            action,
            principal.token,
            principal.login,
        )
    except pipeline_control.PipelineError as exc:
        raise pipeline_http_error(exc) from exc


@app.post(
    "/api/v1/pipelines/{owner}/{repo}/runs/{run_number}/jobs/{job_id}/rerun"
)
async def api_v1_pipeline_rerun_job(
    owner: str,
    repo: str,
    run_number: int,
    job_id: int,
    authorization: str | None = Header(default=None),
):
    principal = await space_api_auth.authorize_space_pat(
        authorization,
        owner,
        repo,
        write=True,
        require_space=False,
        rate_limit_per_minute=config.PIPELINE_API_RATE_LIMIT_PER_MINUTE,
        rate_limit_namespace="pipelines",
        rate_limit_label="Pipeline API",
    )
    try:
        return await pipeline_control.rerun_job(
            owner,
            repo,
            run_number,
            job_id,
            principal.token,
            principal.login,
        )
    except pipeline_control.PipelineError as exc:
        raise pipeline_http_error(exc) from exc


@app.get("/api/spaces/{owner}/{repo}/status")
async def api_space_status(owner: str, repo: str):
    if config.GPU_WORKERS_ENABLED:
        job = await asyncio.to_thread(gpu_control.get_repo_job, owner, repo)
        if job and job["status"] not in ("completed", "cancelled"):
            result = {
                "status": job["status"],
                "execution": "remote-gpu",
                "job_id": str(job["id"]),
                "worker_id": str(job["worker_id"]) if job["worker_id"] else None,
                "error": job["error"],
            }
            if job["status"] == "running":
                result["url"] = f"/run/{owner}/{repo}/"
            return result
    return await asyncio.to_thread(spaces.get_status, owner, repo)


@app.post("/api/spaces/{owner}/{repo}/stop")
async def api_stop_space(
    owner: str,
    repo: str,
    x_nyankoface_control_token: str | None = Header(default=None),
):
    require_frontend_control(x_nyankoface_control_token)
    return await stop_space_control(owner, repo)


@app.get("/api/spaces")
async def api_list_spaces():
    local_spaces = await asyncio.to_thread(spaces.list_spaces)
    if not config.GPU_WORKERS_ENABLED:
        return local_spaces
    remote_jobs = await asyncio.to_thread(gpu_control.list_repo_jobs)
    remote_keys = {
        (str(job["owner"]).lower(), str(job["repo"]).lower())
        for job in remote_jobs
    }
    result = [
        {**item, "execution": "local-cpu"}
        for item in local_spaces
        if (str(item["owner"]).lower(), str(item["repo"]).lower()) not in remote_keys
    ]
    result.extend(
        {
            "owner": job["owner"],
            "repo": job["repo"],
            "status": job["status"],
            "execution": "remote-gpu",
            "worker_id": str(job["worker_id"]) if job["worker_id"] else None,
            "error": job["error"],
        }
        for job in remote_jobs
    )
    return result


# ---------------------------------------------------------------------------
# Remote GPU worker control plane
# ---------------------------------------------------------------------------

@app.post("/api/v1/workers/enrollment-tokens")
async def api_issue_worker_enrollment(
    payload: EnrollmentTokenRequest,
    x_nyankoface_control_token: str | None = Header(default=None),
):
    require_frontend_control(x_nyankoface_control_token)
    return await asyncio.to_thread(
        gpu_control.issue_enrollment_token, payload.name, payload.ttl_minutes
    )


@app.post("/api/v1/workers/enroll")
async def api_enroll_worker(payload: WorkerEnrollRequest):
    result = await asyncio.to_thread(gpu_control.enroll, payload.token)
    if not result:
        raise HTTPException(status_code=401, detail="Enrollment token is invalid, expired, or used")
    return result


@app.post("/api/v1/workers/register")
async def api_register_worker(
    payload: WorkerRegistrationRequest,
    authorization: str | None = Header(default=None),
):
    worker = authenticated_worker(authorization)
    result = await asyncio.to_thread(
        gpu_control.register, str(worker["id"]), payload.capabilities, payload.max_jobs
    )
    return {"worker_id": str(result["id"]), "status": result["status"]}


@app.post("/api/v1/workers/{worker_id}/heartbeat")
async def api_worker_heartbeat(
    worker_id: str,
    payload: WorkerHeartbeatRequest,
    authorization: str | None = Header(default=None),
):
    worker = authenticated_worker(authorization)
    if str(worker["id"]) != worker_id:
        raise HTTPException(status_code=403, detail="Worker identity does not match credential")
    return await asyncio.to_thread(
        gpu_control.heartbeat, worker_id, payload.capabilities, payload.running_jobs
    )


@app.post("/api/v1/workers/{worker_id}/jobs/claim")
async def api_claim_worker_job(
    worker_id: str,
    authorization: str | None = Header(default=None),
):
    worker = authenticated_worker(authorization)
    if str(worker["id"]) != worker_id:
        raise HTTPException(status_code=403, detail="Worker identity does not match credential")
    job = await asyncio.to_thread(gpu_control.claim_job, worker)
    if not job:
        return Response(status_code=204)
    return {
        "id": str(job["id"]),
        "owner": job["owner"],
        "repo": job["repo"],
        "revision": job["revision"],
        "requirements": job["requirements"],
        "clone_url": f"{config.PUBLIC_BASE_URL.rstrip('/')}/git/{job['owner']}/{job['repo']}.git",
        "lease_expires_at": job["lease_expires_at"],
    }


@app.post("/api/v1/workers/{worker_id}/jobs/{job_id}/events")
async def api_worker_job_event(
    worker_id: str,
    job_id: str,
    payload: WorkerEventRequest,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    worker = authenticated_worker(authorization)
    if str(worker["id"]) != worker_id:
        raise HTTPException(status_code=403, detail="Worker identity does not match credential")
    result = await asyncio.to_thread(
        gpu_control.record_event,
        worker_id,
        job_id,
        payload.kind,
        payload.details,
        idempotency_key,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Job is not assigned to this worker")
    return {"job_id": job_id, "status": result["status"]}


@app.post("/api/v1/workers/{worker_id}/jobs/{job_id}/lease")
async def api_worker_job_lease(
    worker_id: str,
    job_id: str,
    authorization: str | None = Header(default=None),
):
    worker = authenticated_worker(authorization)
    if str(worker["id"]) != worker_id:
        raise HTTPException(status_code=403, detail="Worker identity does not match credential")
    result = await asyncio.to_thread(gpu_control.renew_lease, worker_id, job_id)
    if not result:
        raise HTTPException(status_code=409, detail="Job lease is no longer renewable")
    return result


@app.get("/api/v1/workers")
async def api_list_gpu_workers(
    x_nyankoface_control_token: str | None = Header(default=None),
):
    require_frontend_control(x_nyankoface_control_token)
    return await asyncio.to_thread(gpu_control.list_workers)


@app.delete("/api/v1/workers/{worker_id}")
async def api_revoke_gpu_worker(
    worker_id: str,
    x_nyankoface_control_token: str | None = Header(default=None),
):
    require_frontend_control(x_nyankoface_control_token)
    worker = await asyncio.to_thread(gpu_control.revoke_worker, worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found or already revoked")
    return worker


@app.post("/api/v1/gpu/jobs")
async def api_enqueue_gpu_job(
    payload: GpuJobRequest,
    x_nyankoface_control_token: str | None = Header(default=None),
):
    """Administrative enqueue endpoint used by schedulers and diagnostics."""
    require_frontend_control(x_nyankoface_control_token)
    job = await asyncio.to_thread(
        gpu_control.enqueue_job,
        payload.owner,
        payload.repo,
        payload.revision,
        payload.requirements,
    )
    return {
        "id": str(job["id"]),
        "status": job["status"],
        "owner": job["owner"],
        "repo": job["repo"],
        "revision": job["revision"],
    }


# ---------------------------------------------------------------------------
# NyankoFace Pages — static sites sourced from public Forgejo repositories
# ---------------------------------------------------------------------------

async def serve_pages_asset(owner: str, repo: str, asset_path: str, head_only: bool = False):
    safe_path = asset_path or "index.html"
    path = PurePosixPath(safe_path)
    if path.is_absolute() or ".." in path.parts:
        raise HTTPException(status_code=404, detail="Pages asset not found")
    token = config.read_forgejo_token()
    try:
        repo_info = await forgejo.get_repo_info(owner, repo, token)
        source = await forgejo.get_pages_source(owner, repo, token)
    except forgejo.ForgejoError as exc:
        raise HTTPException(status_code=404, detail="Pages site not found") from exc
    if not source:
        raise HTTPException(status_code=404, detail="Pages site not found")
    status, content, upstream_type = await forgejo.fetch_pages_asset(
        owner, repo, source[0], source[1], str(path), token
    )
    if status != 200:
        raise HTTPException(status_code=404, detail="Pages asset not found")
    guessed_type = mimetypes.guess_type(str(path))[0]
    # Forgejo's raw endpoint commonly labels static text as text/plain. Pages
    # must prefer the extension-derived MIME type so browsers execute CSS and
    # JavaScript and render HTML rather than displaying its source.
    generic_upstream_type = not upstream_type or upstream_type.startswith("text/plain") or upstream_type.startswith("application/octet-stream")
    media_type = guessed_type if generic_upstream_type else upstream_type
    media_type = media_type or "application/octet-stream"
    if media_type.startswith("text/html"):
        public_path = f"/pages/{owner}/{repo}/{str(path) if str(path) != 'index.html' else ''}"
        content = pages_metadata.complete_pages_metadata(
            content,
            repo_name=repo_info.get("name") or repo,
            description=repo_info.get("description"),
            page_url=f"{config.PUBLIC_BASE_URL.rstrip('/')}{public_path}",
        )
    return Response(
        content=b"" if head_only else content,
        media_type=media_type,
        headers={
            "Cache-Control": "public, max-age=60",
            "X-NyankoFace-Pages": "1",
            "Content-Length": str(len(content)),
        },
    )


@app.get("/api/pages/{owner}/{repo}/status")
async def api_pages_status(owner: str, repo: str):
    token = config.read_forgejo_token()
    try:
        inspection = await forgejo.inspect_pages_source(owner, repo, token)
    except forgejo.ForgejoError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    inspection["public_url"] = (
        f"{config.PUBLIC_BASE_URL.rstrip('/')}/pages/{owner}/{repo}/"
        if inspection["status"] == "published"
        else None
    )
    return inspection


@app.post("/api/pages/{owner}/{repo}/deploy")
async def api_deploy_pages(
    owner: str,
    repo: str,
    payload: PagesDeployRequest,
    x_nyankoface_control_token: str | None = Header(default=None),
    x_nyankoface_actor: str | None = Header(default=None),
):
    require_frontend_control(x_nyankoface_control_token)
    if not payload.confirmed:
        raise HTTPException(
            status_code=422,
            detail="Confirm the repository changes before deploying Pages.",
        )
    token = config.read_forgejo_token()
    try:
        return await pages_deploy.deploy(
            owner,
            repo,
            payload.method,
            token,
            x_nyankoface_actor or "authorized-forgejo-user",
        )
    except forgejo.ForgejoError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/pages/{owner}/{repo}")
async def api_pages_index(owner: str, repo: str):
    return await serve_pages_asset(owner, repo, "index.html")


@app.head("/api/pages/{owner}/{repo}")
async def api_pages_index_head(owner: str, repo: str):
    return await serve_pages_asset(owner, repo, "index.html", head_only=True)


@app.get("/api/pages/{owner}/{repo}/{asset_path:path}")
async def api_pages_asset(owner: str, repo: str, asset_path: str):
    return await serve_pages_asset(owner, repo, asset_path)


@app.head("/api/pages/{owner}/{repo}/{asset_path:path}")
async def api_pages_asset_head(owner: str, repo: str, asset_path: str):
    return await serve_pages_asset(owner, repo, asset_path, head_only=True)


async def serve_pipeline_deployment_asset(
    owner: str,
    repo: str,
    environment: Literal["preview", "staging"],
    key: str,
    asset_path: str,
    *,
    head_only: bool = False,
):
    if environment == "preview":
        if not (
            key.startswith("pr-") or key.startswith("run-")
        ) or not key.split("-", 1)[1].isdigit():
            raise HTTPException(status_code=404, detail="Preview not found")
    elif key != "current":
        raise HTTPException(status_code=404, detail="Staging site not found")
    token = config.read_forgejo_token()
    try:
        repo_info = await forgejo.get_repo_info(owner, repo, token)
    except forgejo.ForgejoError as exc:
        raise HTTPException(status_code=404, detail="Deployment not found") from exc
    if repo_info.get("private"):
        raise HTTPException(status_code=404, detail="Deployment not found")
    try:
        opened = await asyncio.to_thread(
            preview_artifacts.open_asset,
            owner,
            repo,
            environment,
            key,
            asset_path or "index.html",
        )
    except preview_artifacts.PreviewArtifactError as exc:
        raise HTTPException(status_code=404, detail="Deployment asset not found") from exc
    if opened is None:
        raise HTTPException(status_code=404, detail="Deployment asset not found")
    stream, path, stat_result = opened
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers = {
        "Cache-Control": "no-store",
        "Content-Length": str(stat_result.st_size),
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-NyankoFace-Deployment": environment,
    }
    normalized_media_type = media_type.partition(";")[0].strip().lower()
    browser_active_document = (
        normalized_media_type in {
            "text/html",
            "application/xhtml+xml",
            "image/svg+xml",
            "application/xml",
            "text/xml",
        }
        or normalized_media_type.endswith("+xml")
    )
    if browser_active_document:
        # Deployment output is untrusted repository content. A sandboxed
        # opaque origin prevents HTML, XHTML, SVG, and other XML documents
        # from reading portal cookies or calling NyankoFace APIs even though
        # the fallback URL shares the gateway host.
        headers.update(
            {
                "Content-Security-Policy": (
                    "sandbox allow-scripts; default-src 'self' data: blob:; "
                    "connect-src 'none'; form-action 'none'; object-src 'none'; "
                    "base-uri 'none'; frame-ancestors 'none'"
                ),
                "Cross-Origin-Opener-Policy": "same-origin",
            }
        )
    if head_only:
        await asyncio.to_thread(stream.close)
        return Response(content=b"", media_type=media_type, headers=headers)

    async def body():
        try:
            while chunk := await asyncio.to_thread(
                stream.read,
                64 * 1024,
            ):
                yield chunk
        finally:
            await asyncio.to_thread(stream.close)

    return StreamingResponse(
        body(),
        media_type=media_type,
        headers=headers,
    )


@app.get("/api/previews/{owner}/{repo}/{key}")
async def api_preview_index(owner: str, repo: str, key: str):
    return await serve_pipeline_deployment_asset(
        owner, repo, "preview", key, "index.html"
    )


@app.head("/api/previews/{owner}/{repo}/{key}")
async def api_preview_index_head(owner: str, repo: str, key: str):
    return await serve_pipeline_deployment_asset(
        owner, repo, "preview", key, "index.html", head_only=True
    )


@app.get("/api/previews/{owner}/{repo}/{key}/{asset_path:path}")
async def api_preview_asset(owner: str, repo: str, key: str, asset_path: str):
    return await serve_pipeline_deployment_asset(
        owner, repo, "preview", key, asset_path
    )


@app.head("/api/previews/{owner}/{repo}/{key}/{asset_path:path}")
async def api_preview_asset_head(
    owner: str, repo: str, key: str, asset_path: str
):
    return await serve_pipeline_deployment_asset(
        owner, repo, "preview", key, asset_path, head_only=True
    )


@app.get("/api/staging/{owner}/{repo}")
async def api_staging_index(owner: str, repo: str):
    return await serve_pipeline_deployment_asset(
        owner, repo, "staging", "current", "index.html"
    )


@app.head("/api/staging/{owner}/{repo}")
async def api_staging_index_head(owner: str, repo: str):
    return await serve_pipeline_deployment_asset(
        owner, repo, "staging", "current", "index.html", head_only=True
    )


@app.get("/api/staging/{owner}/{repo}/{asset_path:path}")
async def api_staging_asset(owner: str, repo: str, asset_path: str):
    return await serve_pipeline_deployment_asset(
        owner, repo, "staging", "current", asset_path
    )


@app.head("/api/staging/{owner}/{repo}/{asset_path:path}")
async def api_staging_asset_head(owner: str, repo: str, asset_path: str):
    return await serve_pipeline_deployment_asset(
        owner, repo, "staging", "current", asset_path, head_only=True
    )


# ---------------------------------------------------------------------------
# Agent interaction API
# ---------------------------------------------------------------------------

@app.get("/api/agents")
async def api_list_agents():
    """Public agent profiles. API keys are never returned."""
    return await asyncio.to_thread(agent_metrics.list_agents)


@app.post("/api/metrics/repos/batch")
async def api_repo_metrics_batch(payload: RepoMetricsBatchRequest):
    async def public_target(target: RepoMetricsTarget) -> tuple[str, str] | None:
        try:
            await verify_public_repo(target.owner, target.repo)
        except HTTPException as exc:
            if exc.status_code == 404:
                return None
            raise
        return target.owner, target.repo

    verified_targets = await asyncio.gather(*(public_target(target) for target in payload.repos))
    targets = [target for target in verified_targets if target is not None]
    return await asyncio.to_thread(agent_metrics.metrics_batch, targets)


@app.get("/api/metrics/repos/{owner}/{repo}")
async def api_repo_metrics(owner: str, repo: str):
    await verify_public_repo(owner, repo)
    return await asyncio.to_thread(agent_metrics.metrics, owner, repo)


@app.get("/api/metrics/repos/{owner}/{repo}/timeseries")
async def api_repo_metrics_timeseries(
    owner: str,
    repo: str,
    from_value: str | None = Query(default=None, alias="from", max_length=80),
    to_value: str | None = Query(default=None, alias="to", max_length=80),
    bucket: Literal["day", "week", "month"] = "day",
    timezone_name: str = Query(default="UTC", alias="timezone", min_length=1, max_length=64),
):
    await verify_public_repo(owner, repo)
    now = datetime.now(timezone.utc)

    def parse_bound(raw: str | None, fallback: datetime) -> datetime:
        if raw is None:
            return fallback
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="from and to must be ISO-8601 timestamps") from exc
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    from_at = parse_bound(from_value, now - timedelta(days=30))
    to_at = parse_bound(to_value, now)
    try:
        return await asyncio.to_thread(
            agent_metrics.timeseries,
            owner,
            repo,
            from_at,
            to_at,
            bucket,
            timezone_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/metrics/repos/{owner}/{repo}/views")
async def api_browser_view(
    request: Request,
    owner: str,
    repo: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Record a real browser visit. One detail-page load supplies one stable key."""
    await verify_public_repo(owner, repo)
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key is required")
    if len(idempotency_key) > 200:
        raise HTTPException(status_code=400, detail="Idempotency-Key must be 200 characters or fewer")
    created, result = await asyncio.to_thread(
        agent_metrics.record_browser_view,
        owner,
        repo,
        idempotency_key,
        metric_actor_kind(request),
    )
    return {"ok": True, "created": created, "source": "browser", "metrics": result}


@app.post("/api/metrics/repos/{owner}/{repo}/downloads")
async def api_download_metric(
    request: Request,
    owner: str,
    repo: str,
    payload: DownloadMetricRequest,
    x_nyankoface_control_token: str | None = Header(default=None, alias="X-NyankoFace-Control-Token"),
):
    require_frontend_control(x_nyankoface_control_token)
    await verify_public_repo(owner, repo)
    if payload.artifact_path and (
        payload.artifact_path.startswith(("/", "\\"))
        or "\\" in payload.artifact_path
        or ".." in PurePosixPath(payload.artifact_path).parts
    ):
        raise HTTPException(status_code=400, detail="artifact_path must be a repository-relative path")
    created, result = await asyncio.to_thread(
        agent_metrics.record_download,
        owner,
        repo,
        payload.source,
        payload.artifact_path,
        payload.idempotency_key,
        payload.outcome,
        metric_actor_kind(request),
    )
    return {
        "ok": True,
        "created": created,
        "source": payload.source,
        "outcome": payload.outcome,
        "metrics": result,
    }


@app.post("/api/metrics/knowledge/batch")
async def api_knowledge_metrics_batch(payload: KnowledgeMetricsBatchRequest):
    targets = [(item.owner, item.repo, item.slug) for item in payload.items]
    return await asyncio.to_thread(agent_metrics.knowledge_metrics_batch, targets)


@app.get("/api/metrics/knowledge/{owner}/{repo}/{slug}")
async def api_knowledge_metrics(owner: str, repo: str, slug: str):
    return await asyncio.to_thread(agent_metrics.knowledge_metrics, owner, repo, slug)


@app.post("/api/metrics/knowledge/{owner}/{repo}/{slug}/views")
async def api_knowledge_browser_view(
    owner: str,
    repo: str,
    slug: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    await verify_repo(owner, repo)
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key is required")
    if len(idempotency_key) > 200:
        raise HTTPException(status_code=400, detail="Idempotency-Key must be 200 characters or fewer")
    created, result = await asyncio.to_thread(
        agent_metrics.record_knowledge_view, owner, repo, slug, idempotency_key
    )
    return {"ok": True, "created": created, "source": "browser", "metrics": result}


@app.post("/api/agent/v1/repos/{owner}/{repo}/views")
async def api_agent_view(
    owner: str,
    repo: str,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    agent = authenticated_agent(authorization)
    await verify_repo(owner, repo)
    if idempotency_key and len(idempotency_key) > 200:
        raise HTTPException(status_code=400, detail="Idempotency-Key must be 200 characters or fewer")
    created, result = await asyncio.to_thread(
        agent_metrics.record_view, agent["id"], owner, repo, idempotency_key
    )
    return {"ok": True, "created": created, "agent": agent["slug"], "metrics": result}


@app.put("/api/agent/v1/repos/{owner}/{repo}/like")
async def api_agent_like(
    owner: str,
    repo: str,
    authorization: str | None = Header(default=None),
):
    agent = authenticated_agent(authorization)
    await verify_repo(owner, repo)
    changed, result = await asyncio.to_thread(agent_metrics.set_like, agent["id"], owner, repo, True)
    return {"ok": True, "changed": changed, "liked": True, "agent": agent["slug"], "metrics": result}


@app.delete("/api/agent/v1/repos/{owner}/{repo}/like")
async def api_agent_unlike(
    owner: str,
    repo: str,
    authorization: str | None = Header(default=None),
):
    agent = authenticated_agent(authorization)
    await verify_repo(owner, repo)
    changed, result = await asyncio.to_thread(agent_metrics.set_like, agent["id"], owner, repo, False)
    return {"ok": True, "changed": changed, "liked": False, "agent": agent["slug"], "metrics": result}


# ---------------------------------------------------------------------------
# Reverse proxy (mounted at /run/ -> here at /)
# ---------------------------------------------------------------------------

@app.websocket("/{owner}/{repo}/{path:path}")
async def ws_proxy(websocket: WebSocket, owner: str, repo: str, path: str):
    await proxy.proxy_websocket(websocket, owner, repo, path)


@app.websocket("/{owner}/{repo}")
async def ws_proxy_root(websocket: WebSocket, owner: str, repo: str):
    await proxy.proxy_websocket(websocket, owner, repo, "")


@app.api_route(
    "/{owner}/{repo}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
async def http_proxy(request: Request, owner: str, repo: str, path: str = ""):
    return await proxy.proxy_http(request, owner, repo, path)


@app.api_route(
    "/{owner}/{repo}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
async def http_proxy_root(request: Request, owner: str, repo: str):
    return await proxy.proxy_http(request, owner, repo, "")


@app.get("/healthz")
async def healthz():
    try:
        metrics_ok, pipeline_ok = await asyncio.gather(
            asyncio.to_thread(agent_metrics.database_ready),
            asyncio.to_thread(pipeline_control.database_ready),
        )
        database_ok = metrics_ok and pipeline_ok
    except Exception:
        metrics_ok = False
        pipeline_ok = False
        database_ok = False
    return JSONResponse(
        {
            "status": "ok" if database_ok else "degraded",
            "database": database_ok,
            "metrics_database": metrics_ok,
            "pipeline_database": pipeline_ok,
        },
        status_code=200 if database_ok else 503,
    )
