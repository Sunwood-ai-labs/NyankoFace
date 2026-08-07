import asyncio
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError

import config
import main
import space_api_auth
import space_environment


@pytest.fixture(autouse=True)
def bypass_environment_lock(monkeypatch):
    monkeypatch.setattr(space_environment, "acquire_mutation_lock", lambda *_: object())
    monkeypatch.setattr(space_environment, "release_mutation_lock", lambda *_: None)


class FakeAsyncClient:
    def __init__(self, responses: list[httpx.Response]):
        self.responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url: str, **_kwargs):
        response = self.responses.pop(0)
        response.request = httpx.Request("GET", url)
        return response


class FailingAsyncClient:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *_args):
        return None
    async def get(self, url: str, **_kwargs):
        raise httpx.ReadTimeout("timed out", request=httpx.Request("GET", url))


def response(status: int, payload: dict, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=payload, headers=headers)


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("path", [
    "/api/v1/spaces/acme/demo/environment/TOKEN",
    "/api/spaces/acme/demo/environment",
])
@pytest.mark.parametrize("error_type", [
    "json_invalid",
    "string_too_long",
    "string_type",
])
def test_environment_validation_error_never_echoes_input(
    path: str,
    error_type: str,
) -> None:
    marker = "secret=must-not-echo"
    request = main.Request({
        "type": "http", "http_version": "1.1", "method": "PUT",
        "scheme": "http", "path": path,
        "raw_path": path.encode(),
        "query_string": b"", "headers": [], "server": ("test", 80),
        "client": ("test", 1), "root_path": "",
    })
    error = RequestValidationError([{
        "type": error_type, "loc": ("body", "value"),
        "msg": "Invalid confidential input", "input": marker,
    }])

    response = run(main.sanitize_environment_validation_error(request, error))

    assert response.status_code == 422
    assert marker.encode() not in response.body
    assert b"invalid_environment_request" in response.body


def test_bearer_token_is_required() -> None:
    with pytest.raises(HTTPException) as exc:
        space_api_auth.bearer_token(None)
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "invalid_token"
def test_structured_control_errors_can_declare_safe_retry() -> None:
    error = space_api_auth.api_error(503, "forgejo_unavailable", "Try again.", retry_safe=True)
    assert error.detail == {"code": "forgejo_unavailable", "message": "Try again.", "retry_safe": True}
@pytest.mark.parametrize("client", [FailingAsyncClient(), FakeAsyncClient([
    httpx.Response(200, content=b"{invalid",
                   headers={"x-oauth-scopes": "write:repository"}),
]), FakeAsyncClient([response(200, {"login": "alice"}, {"x-oauth-scopes": "write:repository"}),
                     response(200, {"topics": ["space"], "permissions": []})])])
def test_pre_dispatch_authorization_failures_are_retry_safe(monkeypatch, client) -> None:
    monkeypatch.setattr(space_api_auth.httpx, "AsyncClient", lambda **_kwargs: client)
    space_api_auth.reset_rate_limits_for_tests()
    with pytest.raises(HTTPException) as exc:
        run(space_api_auth.authorize_space_pat("Bearer " + "a" * 32, "acme", "demo", write=True))
    assert (exc.value.status_code, exc.value.detail["code"], exc.value.detail["retry_safe"]) == (
        503, "forgejo_unavailable", True)
def test_pipeline_errors_distinguish_pre_and_post_dispatch_outcomes() -> None:
    unknown = main.pipeline_http_error(main.pipeline_control.PipelineError("Runner unavailable."))
    rejected = main.pipeline_http_error(main.pipeline_control.PipelineError("Invalid run.", 409, "invalid_run"))
    assert unknown.detail["retry_safe"] is False
    assert rejected.detail["retry_safe"] is True


def test_read_pat_is_scoped_to_accessible_space(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeAsyncClient(
        [
            response(
                200,
                {"login": "alice"},
                {"x-oauth-scopes": "read:repository"},
            ),
            response(
                200,
                {
                    "topics": ["space"],
                    "permissions": {"pull": True, "push": False},
                },
            ),
        ]
    )
    monkeypatch.setattr(space_api_auth.httpx, "AsyncClient", lambda **_kwargs: client)
    space_api_auth.reset_rate_limits_for_tests()

    principal = run(
        space_api_auth.authorize_space_pat(
            "Bearer " + "a" * 32,
            "acme",
            "demo",
            write=False,
        )
    )

    assert principal.login == "alice"
    assert principal.scopes == ("read:repository",)


def test_read_scope_cannot_mutate_even_with_repo_push(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeAsyncClient(
        [
            response(
                200,
                {"login": "alice"},
                {"x-oauth-scopes": "read:repository"},
            ),
        ]
    )
    monkeypatch.setattr(space_api_auth.httpx, "AsyncClient", lambda **_kwargs: client)
    space_api_auth.reset_rate_limits_for_tests()

    with pytest.raises(HTTPException) as exc:
        run(
            space_api_auth.authorize_space_pat(
                "Bearer " + "b" * 32,
                "acme",
                "demo",
                write=True,
            )
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "insufficient_scope"


@pytest.mark.parametrize("push_permission", [False, "false", 1, None])
def test_repo_push_permission_must_be_literal_true(
    monkeypatch: pytest.MonkeyPatch, push_permission,
) -> None:
    client = FakeAsyncClient(
        [
            response(
                200,
                {"login": "alice"},
                {"x-oauth-scopes": "write:repository"},
            ),
            response(
                200,
                {
                    "topics": ["space"],
                    "permissions": {"pull": True, "push": push_permission},
                },
            ),
        ]
    )
    monkeypatch.setattr(space_api_auth.httpx, "AsyncClient", lambda **_kwargs: client)
    space_api_auth.reset_rate_limits_for_tests()

    with pytest.raises(HTTPException) as exc:
        run(
            space_api_auth.authorize_space_pat(
                "Bearer " + "c" * 32,
                "acme",
                "demo",
                write=True,
            )
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "repository_forbidden"


def test_rate_limit_is_per_token_and_returns_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "SPACE_API_RATE_LIMIT_PER_MINUTE", 2)
    space_api_auth.reset_rate_limits_for_tests()
    token = "d" * 32

    space_api_auth.check_rate_limit(token)
    space_api_auth.check_rate_limit(token)
    with pytest.raises(HTTPException) as exc:
        space_api_auth.check_rate_limit(token)

    assert exc.value.status_code == 429
    assert exc.value.headers == {"Retry-After": "60"}


def test_v1_legacy_environment_shape_stays_secret_safe_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def authorize(*_args, **_kwargs):
        return space_api_auth.SpaceApiPrincipal(
            login="alice",
            token="e" * 32,
            scopes=("write:repository",),
        )

    monkeypatch.setattr(space_api_auth, "authorize_space_pat", authorize)
    monkeypatch.setattr(
        space_environment,
        "get_setting",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        space_environment,
        "get_setting_metadata",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        space_environment,
        "upsert",
        lambda *_args: {
            "name": "SERVICE_TOKEN",
            "kind": "secret",
            "scope": "runtime",
            "enabled": True,
            "configured": True,
            "value": "must-not-leak",
        },
    )
    monkeypatch.setattr(space_environment, "delete", lambda *_args: False)

    created = run(
        main.api_v1_upsert_space_environment(
            "acme",
            "demo",
            "SERVICE_TOKEN",
            main.SpaceEnvironmentApiUpsertRequest(
                kind="secret", value="must-not-leak",
            ),
            "Bearer " + "e" * 32,
        )
    )
    deleted = run(
        main.api_v1_delete_space_environment(
            "acme",
            "demo",
            "SERVICE_TOKEN",
            restart=False,
            authorization="Bearer " + "e" * 32,
        )
    )

    assert "value" not in created["item"]
    assert created["restart_required"] is True
    assert deleted["deleted"] is False
    assert deleted["name"] == "SERVICE_TOKEN"


def test_environment_metadata_api_uses_metadata_only_database_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def authorize(*_args, **_kwargs):
        return space_api_auth.SpaceApiPrincipal(
            login="alice",
            token="e" * 32,
            scopes=("read:repository",),
        )

    monkeypatch.setattr(space_api_auth, "authorize_space_pat", authorize)
    monkeypatch.setattr(
        space_environment,
        "list_settings",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("metadata API must not decrypt settings")
        ),
    )
    monkeypatch.setattr(
        space_environment,
        "list_setting_metadata",
        lambda *_args: [{
            "name": "DATABASE_URL",
            "kind": "variable",
            "configured": True,
            "updated_at": "2026-08-02T00:00:00Z",
        }],
    )

    result = run(main.api_v1_list_space_environment(
        "acme",
        "demo",
        "Bearer " + "e" * 32,
    ))

    assert result["items"] == [{
        "name": "DATABASE_URL",
        "kind": "variable",
        "configured": True,
        "updated_at": "2026-08-02T00:00:00Z",
    }]


def test_openapi_publishes_cookie_free_environment_contract() -> None:
    schema = main.app.openapi()
    paths = schema["paths"]

    assert "/api/v1/spaces/{owner}/{repo}/environment" in paths
    assert "/api/v1/spaces/{owner}/{repo}/environment/{name}" in paths
    assert "/api/v1/spaces/{owner}/{repo}/environment/audit" in paths
    assert "/api/v1/spaces/{owner}/{repo}/environment/apply" in paths
    assert "/api/v1/pipelines/{owner}/{repo}/runs" in paths
    assert "/api/v1/pipelines/{owner}/{repo}/runs/{run_number}/metadata" in paths
    assert {f"/api/v1/spaces/{{owner}}/{{repo}}/{action}" for action in
            ("start", "stop", "restart")} | {"/api/v1/pages/{owner}/{repo}/deploy"} <= set(paths)
def test_space_control_api_uses_current_pat_for_each_action(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    async def authorize(*_args, **_kwargs):
        calls.append(("authorize", _kwargs))
        return space_api_auth.SpaceApiPrincipal(login="alice", token="p" * 32,
                                                scopes=("write:repository",))
    async def start(owner, repo, token, **kwargs):
        calls.append(("start", owner, repo, token, kwargs))
        return {"status": "building"}
    async def stop(owner, repo):
        calls.append(("stop", owner, repo))
        return {"status": "stopped"}
    monkeypatch.setattr(main.space_api_auth, "authorize_space_pat", authorize)
    monkeypatch.setattr(main, "start_space_control", start)
    monkeypatch.setattr(main, "stop_space_control", stop)
    run(main.api_v1_start_space("acme", "demo", "Bearer " + "p" * 32))
    run(main.api_v1_stop_space("acme", "demo", "Bearer " + "p" * 32))
    run(main.api_v1_restart_space("acme", "demo", "Bearer " + "p" * 32))
    names = [entry[0] for entry in calls]
    assert (names.count("authorize"), names.count("start"), names.count("stop")) == (3, 2, 2)
    assert all(entry[3] == "p" * 32 for entry in calls if entry[0] == "start")
    assert calls[-1][-1] == {"preflight_retry_safe": False}


def test_restart_waits_for_remote_gpu_cancellation_before_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = []

    async def authorize(*_args, **_kwargs):
        return space_api_auth.SpaceApiPrincipal(
            login="alice", token="p" * 32, scopes=("write:repository",),
        )

    async def stop(owner, repo):
        events.append(("stop", owner, repo))
        return {
            "status": "cancel_requested",
            "execution": "remote-gpu",
            "job_id": "job-1",
        }

    statuses = iter([
        {"status": "cancel_requested"},
        {"status": "stopping"},
        {"status": "cancelled"},
    ])

    async def get_job(job_id):
        events.append(("poll", job_id))
        return next(statuses)

    async def start(owner, repo, token, **kwargs):
        events.append(("start", owner, repo, token, kwargs))
        return {"status": "queued", "job_id": "job-2"}

    monkeypatch.setattr(main.space_api_auth, "authorize_space_pat", authorize)
    monkeypatch.setattr(main, "stop_space_control", stop)
    monkeypatch.setattr(main.gpu_control, "get_job_async", get_job)
    monkeypatch.setattr(main.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(main, "start_space_control", start)

    result = run(main.api_v1_restart_space(
        "acme", "demo", "Bearer " + "p" * 32,
    ))

    assert result == {"status": "queued", "job_id": "job-2"}
    assert [event[0] for event in events] == [
        "stop", "poll", "poll", "poll", "start",
    ]
    assert events[-1][-1] == {"preflight_retry_safe": False}


def test_restart_queued_gpu_job_starts_replacement_without_polling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = space_api_auth.SpaceApiPrincipal(
        login="alice", token="p" * 32, scopes=("write:repository",),
    )
    stop = AsyncMock(return_value={
        "status": "cancelled", "execution": "remote-gpu", "job_id": "job-1",
    })
    start = AsyncMock(return_value={"status": "queued", "job_id": "job-2"})
    get_job = AsyncMock()
    monkeypatch.setattr(
        main.space_api_auth, "authorize_space_pat", AsyncMock(return_value=principal),
    )
    monkeypatch.setattr(main, "stop_space_control", stop)
    monkeypatch.setattr(main, "start_space_control", start)
    monkeypatch.setattr(main.gpu_control, "get_job_async", get_job)

    result = run(main.api_v1_restart_space(
        "acme", "demo", "Bearer " + "p" * 32,
    ))

    assert result == {"status": "queued", "job_id": "job-2"}
    get_job.assert_not_awaited()
    start.assert_awaited_once_with(
        "acme", "demo", "p" * 32, preflight_retry_safe=False,
    )


def test_gpu_start_waits_for_prior_cancellation_then_enqueues_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "GPU_WORKERS_ENABLED", True)
    monkeypatch.setattr(main.forgejo, "verify_space_repo", AsyncMock())
    monkeypatch.setattr(
        main.forgejo, "get_repo_topics", AsyncMock(return_value=["space", "gpu"]),
    )
    monkeypatch.setattr(main.space_environment, "list_settings", lambda *_args: [])
    monkeypatch.setattr(
        main.forgejo, "get_default_revision", AsyncMock(return_value="abc123"),
    )
    jobs = iter([
        {"id": "job-1", "status": "cancel_requested"},
        {"id": "job-2", "status": "queued"},
    ])
    enqueue = Mock(side_effect=lambda *_args: next(jobs))
    wait = AsyncMock()
    monkeypatch.setattr(main.gpu_control, "enqueue_job", enqueue)
    monkeypatch.setattr(main, "wait_for_gpu_cancellation", wait)

    result = run(main.start_space_control("acme", "demo", "token"))

    assert result == {
        "status": "queued",
        "execution": "remote-gpu",
        "job_id": "job-2",
        "revision": "abc123",
    }
    assert enqueue.call_count == 2
    wait.assert_awaited_once_with("job-1", retry_safe=True)


def test_gpu_start_does_not_report_a_second_cancelling_job_as_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "GPU_WORKERS_ENABLED", True)
    monkeypatch.setattr(main.forgejo, "verify_space_repo", AsyncMock())
    monkeypatch.setattr(
        main.forgejo, "get_repo_topics", AsyncMock(return_value=["space", "gpu"]),
    )
    monkeypatch.setattr(main.space_environment, "list_settings", lambda *_args: [])
    monkeypatch.setattr(
        main.forgejo, "get_default_revision", AsyncMock(return_value="abc123"),
    )
    jobs = iter([
        {"id": "job-1", "status": "cancel_requested"},
        {"id": "job-2", "status": "stopping"},
    ])
    monkeypatch.setattr(
        main.gpu_control, "enqueue_job", Mock(side_effect=lambda *_args: next(jobs)),
    )
    monkeypatch.setattr(main, "wait_for_gpu_cancellation", AsyncMock())

    with pytest.raises(HTTPException) as exc:
        run(main.start_space_control("acme", "demo", "token"))

    assert exc.value.status_code == 409
    assert exc.value.detail == {
        "code": "gpu_start_interrupted",
        "message": "The remote GPU Space was stopped while starting.",
        "retry_safe": True,
    }


def test_space_listing_deduplicates_cpu_and_gpu_case_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "GPU_WORKERS_ENABLED", True)
    monkeypatch.setattr(main.spaces, "list_spaces", lambda: [{
        "owner": "NyankoFace", "repo": "Demo", "status": "running",
    }])
    monkeypatch.setattr(main.gpu_control, "list_repo_jobs", lambda: [{
        "owner": "nyankoface",
        "repo": "demo",
        "status": "queued",
        "worker_id": None,
        "error": None,
    }])

    result = run(main.api_list_spaces())

    assert result == [{
        "owner": "nyankoface",
        "repo": "demo",
        "status": "queued",
        "execution": "remote-gpu",
        "worker_id": None,
        "error": None,
    }]


def test_restart_cancellation_timeout_is_not_retry_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = iter([0.0, 0.0, 31.0])
    loop = Mock()
    loop.time.side_effect = lambda: next(clock)
    monkeypatch.setattr(main.asyncio, "get_running_loop", lambda: loop)
    monkeypatch.setattr(main.gpu_control, "get_job_async", AsyncMock(
        return_value={"status": "cancel_requested"},
    ))
    monkeypatch.setattr(main.asyncio, "sleep", AsyncMock())

    with pytest.raises(HTTPException) as exc:
        run(main.wait_for_gpu_cancellation("job-1", timeout_seconds=30.0))

    assert exc.value.status_code == 504
    assert exc.value.detail == {
        "code": "gpu_cancel_timeout",
        "message": "The remote GPU job did not stop before the cancellation timeout.",
        "retry_safe": False,
    }


def test_standalone_start_cancellation_timeout_is_retry_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = iter([0.0, 0.0, 31.0])
    loop = Mock()
    loop.time.side_effect = lambda: next(clock)
    monkeypatch.setattr(main.asyncio, "get_running_loop", lambda: loop)
    monkeypatch.setattr(main.gpu_control, "get_job_async", AsyncMock(
        return_value={"status": "cancel_requested"},
    ))
    monkeypatch.setattr(main.asyncio, "sleep", AsyncMock())

    with pytest.raises(HTTPException) as exc:
        run(main.wait_for_gpu_cancellation(
            "job-1", timeout_seconds=30.0, retry_safe=True,
        ))

    assert exc.value.status_code == 504
    assert exc.value.detail["code"] == "gpu_cancel_timeout"
    assert exc.value.detail["retry_safe"] is True


def test_restart_bounds_each_gpu_cancellation_status_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def stalled_get_job(_job_id):
        await asyncio.sleep(0.02)
        return {"status": "cancel_requested"}

    monkeypatch.setattr(main.gpu_control, "get_job_async", stalled_get_job)

    with pytest.raises(HTTPException) as exc:
        run(main.wait_for_gpu_cancellation("job-1", timeout_seconds=0.001))

    assert exc.value.status_code == 504
    assert exc.value.detail["code"] == "gpu_cancel_timeout"
    assert exc.value.detail["retry_safe"] is False


@pytest.mark.parametrize("job_result", [None, {}, {"status": 1}])
def test_restart_rejects_invalid_gpu_cancellation_status(
    monkeypatch: pytest.MonkeyPatch, job_result,
) -> None:
    monkeypatch.setattr(
        main.gpu_control, "get_job_async", AsyncMock(return_value=job_result),
    )

    with pytest.raises(HTTPException) as exc:
        run(main.wait_for_gpu_cancellation("job-1"))

    assert exc.value.status_code == 502
    assert exc.value.detail["code"] == "invalid_gpu_job_response"
    assert exc.value.detail["retry_safe"] is False


def test_restart_gpu_cancellation_lookup_failure_is_not_retry_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main.gpu_control, "get_job_async", AsyncMock(
        side_effect=RuntimeError("database unavailable"),
    ))

    with pytest.raises(HTTPException) as exc:
        run(main.wait_for_gpu_cancellation("job-1"))

    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "gpu_job_unavailable"
    assert exc.value.detail["retry_safe"] is False


def test_space_stop_failure_is_explicitly_retry_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "GPU_WORKERS_ENABLED", False)
    monkeypatch.setattr(
        main.spaces, "stop_space", lambda *_args: {"status": "error", "error": "busy"},
    )
    with pytest.raises(HTTPException) as exc:
        run(main.stop_space_control("acme", "demo"))
    assert (exc.value.status_code, exc.value.detail["code"], exc.value.detail["retry_safe"]) == (
        502, "space_stop_failed", True)
@pytest.mark.parametrize("failure", [
    main.forgejo.ForgejoError("503"), ValueError("invalid"),
    AttributeError("invalid"), TypeError("invalid"),
])
def test_gpu_revision_failure_before_enqueue_is_retry_safe(monkeypatch, failure) -> None:
    monkeypatch.setattr(config, "GPU_WORKERS_ENABLED", True)
    monkeypatch.setattr(main.forgejo, "verify_space_repo", AsyncMock())
    monkeypatch.setattr(main.forgejo, "get_repo_topics", AsyncMock(return_value=["gpu"]))
    monkeypatch.setattr(main.space_environment, "list_settings", lambda *_: [])
    monkeypatch.setattr(main.forgejo, "get_default_revision",
                        AsyncMock(side_effect=failure))
    with pytest.raises(HTTPException) as exc:
        run(main.start_space_control("acme", "demo", "token"))
    assert exc.value.detail["retry_safe"] is True


@pytest.mark.parametrize("preflight_retry_safe", [True, False])
def test_gpu_environment_lookup_failure_preserves_phase_classification(
    monkeypatch, preflight_retry_safe,
) -> None:
    enqueue = AsyncMock()
    monkeypatch.setattr(config, "GPU_WORKERS_ENABLED", True)
    monkeypatch.setattr(main.forgejo, "verify_space_repo", AsyncMock())
    monkeypatch.setattr(main.forgejo, "get_repo_topics", AsyncMock(return_value=["gpu"]))
    monkeypatch.setattr(
        main.space_environment,
        "list_settings",
        lambda *_: (_ for _ in ()).throw(RuntimeError("decrypt failed")),
    )
    monkeypatch.setattr(main.gpu_control, "enqueue_job", enqueue)

    with pytest.raises(HTTPException) as exc:
        run(main.start_space_control(
            "acme", "demo", "token", preflight_retry_safe=preflight_retry_safe,
        ))

    assert exc.value.detail == {
        "code": "space_environment_unavailable",
        "message": "Could not inspect the Space environment.",
        "retry_safe": preflight_retry_safe,
    }
    enqueue.assert_not_awaited()


@pytest.mark.parametrize("payload", [[], {"commit": []}, {"commit": 1}])
def test_default_revision_rejects_malformed_branch_payload(monkeypatch, payload) -> None:
    client = FakeAsyncClient([
        response(200, {"default_branch": "main"}), response(200, payload),
    ])
    monkeypatch.setattr(main.forgejo.httpx, "AsyncClient", lambda **_kwargs: client)
    with pytest.raises(main.forgejo.ForgejoError, match="invalid branch response"):
        run(main.forgejo.get_default_revision("acme", "demo", "token"))


@pytest.mark.parametrize("failure", [httpx.ReadTimeout("timeout"), ValueError("invalid")])
def test_initial_space_transport_failure_is_retry_safe(monkeypatch, failure) -> None:
    monkeypatch.setattr(main.forgejo, "verify_space_repo", AsyncMock(
        side_effect=failure))
    with pytest.raises(HTTPException) as exc:
        run(main.start_space_control("acme", "demo", "token"))
    assert exc.value.detail["retry_safe"] is True


@pytest.mark.parametrize("topics", [["space", "gpu", 1], "space,gpu"])
def test_start_rejects_malformed_topics_before_enqueue(monkeypatch, topics) -> None:
    enqueue = AsyncMock()
    monkeypatch.setattr(config, "GPU_WORKERS_ENABLED", True)
    monkeypatch.setattr(main.forgejo, "verify_space_repo", AsyncMock())
    monkeypatch.setattr(main.forgejo, "get_repo_topics", AsyncMock(return_value=topics))
    monkeypatch.setattr(main.gpu_control, "enqueue_job", enqueue)

    with pytest.raises(HTTPException) as exc:
        run(main.start_space_control("acme", "demo", "token"))

    assert exc.value.detail == {
        "code": "forgejo_unavailable",
        "message": "Could not verify the Space.",
        "retry_safe": True,
    }
    enqueue.assert_not_awaited()


def test_pages_control_api_uses_pat_actor_and_requires_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    principal = space_api_auth.SpaceApiPrincipal(login="alice", token="p" * 32,
                                                  scopes=("write:repository",))
    deploy = AsyncMock(return_value={"status": "published"})
    monkeypatch.setattr(main.space_api_auth, "authorize_space_pat", AsyncMock(return_value=principal))
    monkeypatch.setattr(main.pages_deploy, "deploy", deploy)
    result = run(main.api_v1_deploy_pages(
        "acme", "site", main.PagesDeployRequest(method="docs", confirmed=True),
        "Bearer " + "p" * 32))
    assert result == {"status": "published"}
    assert deploy.await_args.args == ("acme", "site", "docs", "p" * 32, "alice")
    with pytest.raises(HTTPException) as exc:
        run(main.api_v1_deploy_pages("acme", "site",
            main.PagesDeployRequest(method="docs", confirmed=False), "Bearer " + "p" * 32))
    assert exc.value.detail["code"] == "confirmation_required"
@pytest.mark.parametrize(("failure", "code", "retry_safe"), [
    (main.pages_deploy.PagesOutcomeUnknown("failed"), "pages_deploy_outcome_unknown", False),
    (ValueError("invalid"), "pages_deploy_rejected", True)])
def test_pages_post_write_failure_is_not_retry_safe(monkeypatch, failure, code, retry_safe) -> None:
    principal = space_api_auth.SpaceApiPrincipal(login="alice", token="p" * 32,
                                                  scopes=("write:repository",))
    monkeypatch.setattr(main.space_api_auth, "authorize_space_pat", AsyncMock(return_value=principal))
    monkeypatch.setattr(main.pages_deploy, "deploy", AsyncMock(side_effect=failure))
    with pytest.raises(HTTPException) as exc:
        run(main.api_v1_deploy_pages(
            "acme", "site", main.PagesDeployRequest(method="docs", confirmed=True),
            "Bearer " + "p" * 32,
        ))
    assert exc.value.detail["code"] == code
    assert exc.value.detail["retry_safe"] is retry_safe


@pytest.mark.parametrize("topics", [1, [{"name": "space"}], ["space", 2]])
def test_control_auth_rejects_malformed_topics_as_retry_safe(monkeypatch, topics) -> None:
    responses = [
        response(200, {"login": "alice"}, {"x-oauth-scopes": "write:repository"}),
        response(200, {"topics": topics, "permissions": {"push": True}}),
    ]
    client = FakeAsyncClient(responses)
    monkeypatch.setattr(space_api_auth.httpx, "AsyncClient", lambda **_kwargs: client)
    with pytest.raises(HTTPException) as exc:
        run(space_api_auth.authorize_space_pat(
            "Bearer " + "p" * 32, "acme", "demo", write=True, require_space=True,
        ))
    assert (exc.value.status_code, exc.value.detail["code"], exc.value.detail["retry_safe"]) == (
        503, "forgejo_unavailable", True,
    )


def test_pipeline_runs_api_forwards_bounded_upstream_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def authorize(*_args, **_kwargs):
        return space_api_auth.SpaceApiPrincipal(
            login="alice",
            token="e" * 32,
            scopes=("read:repository",),
        )

    captured = {}

    async def list_runs(*args, **kwargs):
        captured.update({"args": args, "kwargs": kwargs})
        return {
            "runs": [],
            "pagination": {"page": 2, "limit": 50, "total_count": 0, "total_pages": 1},
        }

    monkeypatch.setattr(space_api_auth, "authorize_space_pat", authorize)
    monkeypatch.setattr(main.pipeline_control, "list_runs", list_runs)

    result = run(main.api_v1_pipeline_runs(
        "acme", "site", page=2, limit=500,
        authorization="Bearer " + "e" * 32,
    ))

    assert result["pagination"]["limit"] == 50
    assert captured["args"] == ("acme", "site", "e" * 32)
    assert captured["kwargs"] == {
        "page": 2, "limit": 50, "include_pagination": True,
        "reconcile_deployments": False,
    }


def test_pipeline_run_metadata_api_uses_lightweight_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def authorize(*_args, **_kwargs):
        return space_api_auth.SpaceApiPrincipal(
            login="alice",
            token="e" * 32,
            scopes=("read:repository",),
        )

    captured = {}

    async def run_metadata(*args):
        captured["args"] = args
        return {"state": {"run": {"status": "queued"}}, "jobs": []}

    monkeypatch.setattr(space_api_auth, "authorize_space_pat", authorize)
    monkeypatch.setattr(main.pipeline_control, "run_metadata", run_metadata)

    result = run(main.api_v1_pipeline_run_metadata(
        "acme", "site", 12, authorization="Bearer " + "e" * 32,
    ))

    assert result["state"]["run"]["status"] == "queued"
    assert captured["args"] == ("acme", "site", 12, "e" * 32)


def test_swagger_ui_uses_proxy_safe_relative_openapi_url() -> None:
    response = run(main.api_docs())
    body = response.body.decode("utf-8")

    assert "url: './openapi.json'" in body
    assert "url: '/api/openapi.json'" not in body
