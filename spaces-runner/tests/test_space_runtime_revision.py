import asyncio
import threading

import pytest
from fastapi import HTTPException

import main
import space_api_auth
import spaces


@pytest.fixture(autouse=True)
def valid_environment(monkeypatch): monkeypatch.setattr(main.space_environment, "runtime_values", lambda *_: {})


def run(coro):
    return asyncio.run(coro)


def test_clone_repo_fetches_and_checks_out_requested_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], str | None, int]] = []

    monkeypatch.setattr(
        spaces.forgejo,
        "clone_url",
        lambda owner, repo, token: f"https://example.test/{owner}/{repo}?{token}",
    )
    monkeypatch.setattr(
        spaces,
        "_run",
        lambda command, cwd=None, timeout=300: calls.append(
            (command, cwd, timeout)
        ),
    )

    spaces._clone_repo(
        "acme",
        "demo",
        "token",
        "C:/tmp/demo",
        "0123456789abcdef",
    )

    assert calls == [
        (
            [
                "git",
                "clone",
                "--depth",
                "1",
                "https://example.test/acme/demo?token",
                "C:/tmp/demo",
            ],
            None,
            300,
        ),
        (
            [
                "git",
                "fetch",
                "--depth",
                "1",
                "origin",
                "0123456789abcdef",
            ],
            "C:/tmp/demo",
            300,
        ),
        (
            ["git", "checkout", "--detach", "FETCH_HEAD"],
            "C:/tmp/demo",
            300,
        ),
    ]


def test_start_space_rebuilds_running_container_for_different_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[tuple] = []

    class ImmediateThread:
        def __init__(self, target, args, daemon):
            started.append((target, args, daemon))

        def start(self):
            return None

    state = spaces.registry.get("acme", "demo")
    state.status = "running"
    state.revision = "1111111"
    monkeypatch.setattr(spaces, "probe_container_status", lambda *_args: "running")
    monkeypatch.setattr(spaces.threading, "Thread", ImmediateThread)

    result = spaces.start_space("acme", "demo", "token", "2222222")

    assert result == {
        "status": "building",
        "revision": "2222222",
        "generation": state.generation,
    }
    assert started[0][0] is spaces._build_and_run
    assert started[0][1][:4] == ("acme", "demo", "token", "2222222")
    assert started[0][1][4] == state.generation


def test_superseded_build_cannot_replace_newer_revision(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_build_started = threading.Event()
    release_old_build = threading.Event()
    launched: list[str] = []
    launched_labels: list[dict[str, str]] = []
    build_counter = iter(range(2))

    class Image:
        def __init__(self, image_id: str):
            self.id = image_id

    class Images:
        removed: list[str] = []

        def build(self, *, tag, **_kwargs):
            if tag.endswith("generation-1"):
                old_build_started.set()
                assert release_old_build.wait(timeout=5)
                return Image("old-image"), []
            return Image("new-image"), []

        def remove(self, image, **_kwargs):
            self.removed.append(image)

    class Containers:
        current_image: Image | None = Image("previous-image")

        def get(self, _name):
            if self.current_image is None:
                raise spaces.NotFound("missing")

            owner = self

            class Existing:
                image = owner.current_image

                def remove(self, **_kwargs):
                    owner.current_image = None

            return Existing()

        def run(self, image_id, **_kwargs):
            launched.append(image_id)
            launched_labels.append(dict(_kwargs["labels"]))
            self.current_image = Image(image_id)

    class Client:
        images = Images()
        containers = Containers()

    monkeypatch.setattr(
        spaces.tempfile,
        "mkdtemp",
        lambda **_kwargs: str(tmp_path / f"build-{next(build_counter)}"),
    )
    monkeypatch.setattr(spaces, "_clone_repo", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(spaces, "_ensure_dockerfile", lambda *_args: None)
    monkeypatch.setattr(spaces, "get_docker_client", lambda: Client())
    monkeypatch.setattr(spaces, "_evict_lru_if_needed", lambda *_args: [])
    monkeypatch.setattr(
        spaces.space_environment,
        "runtime_values",
        lambda *_args: {},
    )

    state = spaces.registry.get("concurrency", "demo")
    with state.lock:
        state.generation = 1
        state.status = "building"
        state.revision = None

    old = threading.Thread(
        target=spaces._build_and_run,
        args=("concurrency", "demo", "token", "old-sha", 1),
    )
    old.start()
    assert old_build_started.wait(timeout=5)

    with state.lock:
        state.generation = 2
        state.status = "building"
    newer = threading.Thread(
        target=spaces._build_and_run,
        args=("concurrency", "demo", "token", "new-sha", 2),
    )
    newer.start()
    newer.join(timeout=5)
    assert not newer.is_alive()

    release_old_build.set()
    old.join(timeout=5)
    assert not old.is_alive()

    assert launched == ["new-image"]
    assert launched_labels == [
        {
            spaces.config.SPACE_LABEL_KEY: spaces.config.SPACE_LABEL_VALUE,
            spaces.config.OWNER_LABEL_KEY: "concurrency",
            spaces.config.REPO_LABEL_KEY: "demo",
            spaces.config.GENERATION_LABEL_KEY: "2",
            spaces.config.REVISION_LABEL_KEY: "new-sha",
        }
    ]
    assert state.status == "running"
    assert state.revision == "new-sha"
    assert state.generation == 2
    assert Client.images.removed == ["previous-image", "old-image"]


def test_restart_space_environment_forwards_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple] = []

    async def topics(*_args):
        return ["space"]

    async def to_thread(function, *args):
        calls.append((function, args))
        if function is spaces.start_space:
            return {"status": "building", "revision": args[-1]}
        return {"status": "stopped"}

    monkeypatch.setattr(main.forgejo, "get_repo_topics", topics)
    monkeypatch.setattr(main.asyncio, "to_thread", to_thread)

    result = run(
        main.restart_space_environment(
            "acme",
            "demo",
            "token",
            "0123456789abcdef",
        )
    )

    assert calls == [
        (spaces.stop_space, ("acme", "demo")),
        (
            spaces.start_space,
            ("acme", "demo", "token", "0123456789abcdef"),
        ),
    ]
    assert result == {
        "status": "building",
        "revision": "0123456789abcdef",
        "execution": "local-cpu",
    }


def test_oversized_environment_does_not_stop_running_space(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.forgejo, "get_repo_topics", lambda *_: asyncio.sleep(0, result=[])); monkeypatch.setattr(main.space_environment, "runtime_values", lambda *_: (_ for _ in ()).throw(RuntimeError("limit"))); monkeypatch.setattr(main.spaces, "stop_space", lambda *_: pytest.fail("stopped before preflight"))
    with pytest.raises(HTTPException) as captured: run(main.restart_space_environment("acme", "demo", "token"))
    assert captured.value.status_code == 422 and captured.value.detail["code"] == "environment_limit"


def test_stop_space_removes_the_deleted_container_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class Image:
        id = "previous-generation-image"

    class Container:
        image = Image()

        def stop(self, *, timeout):
            assert timeout == 10
            events.append("stop")

        def remove(self, *, force):
            assert force is True
            events.append("remove-container")

    class Containers:
        def get(self, _name):
            return Container()

    class Client:
        containers = Containers()

    state = spaces.registry.get("stop-cleanup", "demo")
    state.generation = 4
    state.revision = "old-revision"
    monkeypatch.setattr(spaces, "get_docker_client", lambda: Client())
    monkeypatch.setattr(
        spaces,
        "_remove_image",
        lambda _client, image_id: events.append(f"remove-image:{image_id}"),
    )

    result = spaces.stop_space("stop-cleanup", "demo")

    assert result == {"status": "stopped"}
    assert events == [
        "stop",
        "remove-container",
        "remove-image:previous-generation-image",
    ]
    assert state.generation == 5
    assert state.revision is None


def test_cancel_space_generation_is_a_compare_and_swap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    docker_calls: list[str] = []

    class Containers:
        def get(self, _name):
            docker_calls.append("get")
            raise spaces.NotFound("missing")

    class Client:
        containers = Containers()

    state = spaces.registry.get("conditional-cancel", "demo")
    state.generation = 8
    state.status = "building"
    state.revision = "newer-revision"
    monkeypatch.setattr(spaces, "get_docker_client", lambda: Client())

    assert spaces.cancel_space_generation(
        "conditional-cancel",
        "demo",
        7,
    ) is False
    assert docker_calls == []
    assert state.generation == 8
    assert state.status == "building"
    assert state.revision == "newer-revision"

    assert spaces.cancel_space_generation(
        "conditional-cancel",
        "demo",
        8,
    ) is True
    assert docker_calls == ["get"]
    assert state.generation == 9
    assert state.status == "stopped"
    assert state.revision is None


def test_cancelled_generation_cannot_launch_after_build_finishes(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_started = threading.Event()
    release_build = threading.Event()
    launched: list[str] = []
    removed_images: list[str] = []

    class Image:
        id = "cancelled-image"

    class Images:
        def build(self, **_kwargs):
            build_started.set()
            assert release_build.wait(timeout=5)
            return Image(), []

        def remove(self, image, **_kwargs):
            removed_images.append(image)

    class Containers:
        def get(self, _name):
            raise spaces.NotFound("missing")

        def run(self, image_id, **_kwargs):
            launched.append(image_id)

    class Client:
        images = Images()
        containers = Containers()

    monkeypatch.setattr(
        spaces.tempfile,
        "mkdtemp",
        lambda **_kwargs: str(tmp_path / "cancelled-build"),
    )
    monkeypatch.setattr(spaces, "_clone_repo", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(spaces, "_ensure_dockerfile", lambda *_args: None)
    monkeypatch.setattr(spaces, "get_docker_client", lambda: Client())

    state = spaces.registry.get("cancel-build", "demo")
    state.generation = 1
    state.status = "building"
    thread = threading.Thread(
        target=spaces._build_and_run,
        args=("cancel-build", "demo", "token", "old-sha", 1),
    )
    thread.start()
    assert build_started.wait(timeout=5)

    assert spaces.cancel_space_generation("cancel-build", "demo", 1) is True
    release_build.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert launched == []
    assert removed_images == ["cancelled-image"]
    assert state.generation == 2
    assert state.status == "stopped"


def test_environment_apply_api_accepts_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def authorize(*_args, **_kwargs):
        return space_api_auth.SpaceApiPrincipal(
            login="alice",
            token="token",
            scopes=("write:repository",),
        )

    restarted: list[tuple] = []

    async def restart(*args, **kwargs):
        restarted.append((*args, kwargs))
        return {"status": "building", "revision": args[-1]}

    monkeypatch.setattr(space_api_auth, "authorize_space_pat", authorize)
    monkeypatch.setattr(main, "restart_space_environment", restart)
    monkeypatch.setattr(main.space_environment, "acquire_mutation_lock", lambda *_: object())
    monkeypatch.setattr(main.space_environment, "release_mutation_lock", lambda *_: None)

    result = run(
        main.api_v1_apply_space_environment(
            "acme",
            "demo",
            main.SpaceEnvironmentApiApplyRequest(
                restart=True,
                revision="0123456789abcdef",
            ),
            "Bearer token",
        )
    )

    assert restarted == [
        (
            "acme",
            "demo",
            "token",
            "0123456789abcdef",
            {"wait_until_ready": True},
        )
    ]
    assert result["runtime"]["revision"] == "0123456789abcdef"


def test_restart_space_waits_for_requested_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statuses = iter(
        [
            {
                "status": "building",
                "generation": 7,
                "revision": "0123456789abcdef",
            },
            {
                "status": "running",
                "url": "/run/acme/demo/",
                "revision": "0123456789abcdef",
                "generation": 7,
            },
            {
                "status": "running",
                "url": "/run/acme/demo/",
                "revision": "0123456789abcdef",
                "generation": 7,
            },
        ]
    )

    async def topics(*_args):
        return ["space"]

    async def to_thread(function, *args):
        if function is spaces.stop_space:
            return {"status": "stopped"}
        if function is spaces.start_space:
            return {
                "status": "building",
                "revision": args[-1],
                "generation": 7,
            }
        if function is spaces.get_status:
            return next(statuses)
        raise AssertionError(function)

    async def no_sleep(_seconds):
        return None

    async def ready(*_args):
        return True, "HTTP 200"

    monkeypatch.setattr(main.forgejo, "get_repo_topics", topics)
    monkeypatch.setattr(main.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(main.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(main, "_probe_space_http_readiness", ready)

    result = run(
        main.restart_space_environment(
            "acme",
            "demo",
            "token",
            "0123456789abcdef",
            wait_until_ready=True,
        )
    )

    assert result == {
        "status": "running",
        "url": "/run/acme/demo/",
        "revision": "0123456789abcdef",
        "execution": "local-cpu",
    }


def test_restart_space_surfaces_background_build_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def topics(*_args):
        return ["space"]

    async def to_thread(function, *args):
        if function is spaces.stop_space:
            return {"status": "stopped"}
        if function is spaces.start_space:
            return {
                "status": "building",
                "revision": args[-1],
                "generation": 3,
            }
        if function is spaces.get_status:
            return {
                "status": "error",
                "error": "docker build failed",
                "generation": 3,
            }
        raise AssertionError(function)

    monkeypatch.setattr(main.forgejo, "get_repo_topics", topics)
    monkeypatch.setattr(main.asyncio, "to_thread", to_thread)

    with pytest.raises(HTTPException) as error:
        run(
            main.restart_space_environment(
                "acme",
                "demo",
                "token",
                "0123456789abcdef",
                wait_until_ready=True,
            )
        )

    assert getattr(error.value, "status_code", None) == 502
    assert "docker build failed" in str(getattr(error.value, "detail", ""))


def test_restart_space_timeout_cancels_only_its_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple] = []

    async def topics(*_args):
        return ["space"]

    async def to_thread(function, *args):
        calls.append((function, args))
        if function is spaces.stop_space:
            return {"status": "stopped"}
        if function is spaces.start_space:
            return {
                "status": "building",
                "revision": args[-1],
                "generation": 7,
            }
        if function is spaces.get_status:
            return {"status": "building", "generation": 7}
        if function is spaces.cancel_space_generation:
            return True
        raise AssertionError(function)

    monkeypatch.setattr(main.forgejo, "get_repo_topics", topics)
    monkeypatch.setattr(main.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(main.config, "SPACE_DEPLOY_TIMEOUT_SECONDS", 0)

    with pytest.raises(HTTPException) as error:
        run(
            main.restart_space_environment(
                "acme",
                "demo",
                "token",
                "0123456789abcdef",
                wait_until_ready=True,
            )
        )

    assert getattr(error.value, "status_code", None) == 504
    assert calls[-1] == (
        spaces.cancel_space_generation,
        ("acme", "demo", 7),
    )


def test_restart_space_revision_mismatch_cancels_its_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple] = []

    async def topics(*_args):
        return ["space"]

    async def to_thread(function, *args):
        calls.append((function, args))
        if function is spaces.stop_space:
            return {"status": "stopped"}
        if function is spaces.start_space:
            return {
                "status": "building",
                "revision": args[-1],
                "generation": 12,
            }
        if function is spaces.get_status:
            return {
                "status": "running",
                "revision": "different-revision",
                "generation": 12,
            }
        if function is spaces.cancel_space_generation:
            return True
        raise AssertionError(function)

    monkeypatch.setattr(main.forgejo, "get_repo_topics", topics)
    monkeypatch.setattr(main.asyncio, "to_thread", to_thread)

    with pytest.raises(HTTPException) as error:
        run(
            main.restart_space_environment(
                "acme",
                "demo",
                "token",
                "0123456789abcdef",
                wait_until_ready=True,
            )
        )

    assert getattr(error.value, "status_code", None) == 502
    assert calls[-1] == (
        spaces.cancel_space_generation,
        ("acme", "demo", 12),
    )


def test_restart_space_task_cancellation_invalidates_its_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple] = []

    async def topics(*_args):
        return ["space"]

    async def to_thread(function, *args):
        calls.append((function, args))
        if function is spaces.stop_space:
            return {"status": "stopped"}
        if function is spaces.start_space:
            return {
                "status": "building",
                "revision": args[-1],
                "generation": 15,
            }
        if function is spaces.get_status:
            raise asyncio.CancelledError
        if function is spaces.cancel_space_generation:
            return True
        raise AssertionError(function)

    monkeypatch.setattr(main.forgejo, "get_repo_topics", topics)
    monkeypatch.setattr(main.asyncio, "to_thread", to_thread)

    with pytest.raises(asyncio.CancelledError):
        run(
            main.restart_space_environment(
                "acme",
                "demo",
                "token",
                "0123456789abcdef",
                wait_until_ready=True,
            )
        )

    assert calls[-1] == (
        spaces.cancel_space_generation,
        ("acme", "demo", 15),
    )


def test_restart_space_retries_http_readiness_until_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probes = iter([(False, "HTTP 503"), (True, "HTTP 204")])
    probe_calls = 0

    async def topics(*_args):
        return ["space"]

    async def to_thread(function, *args):
        if function is spaces.stop_space:
            return {"status": "stopped"}
        if function is spaces.start_space:
            return {
                "status": "running",
                "revision": args[-1],
                "generation": 21,
            }
        if function is spaces.get_status:
            return {
                "status": "running",
                "url": "/run/acme/demo/",
                "revision": "0123456789abcdef",
                "generation": 21,
            }
        raise AssertionError(function)

    async def probe(*_args):
        nonlocal probe_calls
        probe_calls += 1
        return next(probes)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(main.forgejo, "get_repo_topics", topics)
    monkeypatch.setattr(main.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(main.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(main, "_probe_space_http_readiness", probe)

    result = run(
        main.restart_space_environment(
            "acme",
            "demo",
            "token",
            "0123456789abcdef",
            wait_until_ready=True,
        )
    )

    assert probe_calls == 2
    assert result["status"] == "running"
    assert result["revision"] == "0123456789abcdef"


def test_restart_space_http_failure_times_out_and_cancels_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple] = []

    async def topics(*_args):
        return ["space"]

    async def to_thread(function, *args):
        calls.append((function, args))
        if function is spaces.stop_space:
            return {"status": "stopped"}
        if function is spaces.start_space:
            return {
                "status": "running",
                "revision": args[-1],
                "generation": 22,
            }
        if function is spaces.get_status:
            return {
                "status": "running",
                "revision": "0123456789abcdef",
                "generation": 22,
            }
        if function is spaces.cancel_space_generation:
            return True
        raise AssertionError(function)

    async def not_ready(*_args):
        return False, "HTTP 503"

    monkeypatch.setattr(main.forgejo, "get_repo_topics", topics)
    monkeypatch.setattr(main.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(main, "_probe_space_http_readiness", not_ready)
    monkeypatch.setattr(main.config, "SPACE_DEPLOY_TIMEOUT_SECONDS", 0)

    with pytest.raises(HTTPException) as error:
        run(
            main.restart_space_environment(
                "acme",
                "demo",
                "token",
                "0123456789abcdef",
                wait_until_ready=True,
            )
        )

    assert getattr(error.value, "status_code", None) == 504
    assert getattr(error.value, "detail", {}).get("code") == "space_readiness_timeout"
    assert calls[-1] == (
        spaces.cancel_space_generation,
        ("acme", "demo", 22),
    )


def test_restart_space_rejects_superseded_generation_without_cancelling_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple] = []

    async def topics(*_args):
        return ["space"]

    async def to_thread(function, *args):
        calls.append((function, args))
        if function is spaces.stop_space:
            return {"status": "stopped"}
        if function is spaces.start_space:
            return {
                "status": "building",
                "revision": args[-1],
                "generation": 30,
            }
        if function is spaces.get_status:
            return {
                "status": "running",
                "revision": "0123456789abcdef",
                "generation": 31,
            }
        raise AssertionError(function)

    monkeypatch.setattr(main.forgejo, "get_repo_topics", topics)
    monkeypatch.setattr(main.asyncio, "to_thread", to_thread)

    with pytest.raises(HTTPException) as error:
        run(
            main.restart_space_environment(
                "acme",
                "demo",
                "token",
                "0123456789abcdef",
                wait_until_ready=True,
            )
        )

    assert getattr(error.value, "status_code", None) == 409
    assert all(
        function is not spaces.cancel_space_generation
        for function, _args in calls
    )


def test_environment_apply_rejects_non_hex_revision() -> None:
    with pytest.raises(ValueError):
        main.SpaceEnvironmentApiApplyRequest(
            restart=True,
            revision="not-a-git-revision",
        )
