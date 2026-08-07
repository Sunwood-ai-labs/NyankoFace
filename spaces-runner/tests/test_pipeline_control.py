import asyncio
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

import main
import pipeline_control
import space_environment


class _MemoryPipelineStore:
    """Keep API tests independent from the optional PostgreSQL test service."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.states: dict[tuple[str, str, int], dict] = {}
        self.cursors: dict[tuple[str, str], int] = {}

    def _event(self, owner: str, repo: str, action: str, actor: str, **values) -> None:
        self.events.append({
            "id": len(self.events) + 1,
            "owner": owner,
            "repo": repo,
            "action": action,
            "actor": actor,
            "created_at": datetime.now(timezone.utc).isoformat(),
            **values,
        })

    def record_event(self, owner, repo, action, actor, **values) -> None:
        self._event(owner, repo, action, actor, **values)

    def list_audit(self, owner: str, repo: str, limit: int = 100) -> list[dict]:
        items = [
            item
            for item in self.events
            if item["owner"] == owner
            and item["repo"] == repo
            and not item["action"].startswith("_reconcile_")
        ][-max(1, min(limit, 500)):]
        return [
            {
                key: value
                for key, value in event.items()
                if key not in {"owner", "repo"}
            }
            for event in reversed(items)
        ]

    def recorded_production_revision(self, owner: str, repo: str, run_number: int) -> str:
        for event in reversed(self.events):
            if (
                event["owner"] == owner
                and event["repo"] == repo
                and event["run_number"] == run_number
                and event["action"] == "deploy_production"
            ):
                return str(event.get("revision") or "").strip()
        return ""

    def latest_production_reconcile_state(self, owner: str, repo: str, run_number: int) -> dict | None:
        state = self.states.get((owner, repo, run_number))
        return dict(state) if state else None

    def record_production_reconcile_state(self, owner, repo, *, run_number, state,
                                          run_id, fingerprint, updated="", attempt=0,
                                          artifact_id=0, expires_at="", revision=None,
                                          force=False) -> None:
        payload = {
            "v": 1,
            "state": state,
            "run_id": int(run_id),
            "fingerprint": str(fingerprint),
            "updated": str(updated),
            "attempt": max(0, int(attempt)),
            "artifact_id": max(0, int(artifact_id)),
            "expires_at": str(expires_at),
        }
        key = (owner, repo, int(run_number))
        current = self.states.get(key)
        if (
            current
            and not force
            and all(current.get(name) == value for name, value in payload.items())
            and str(current.get("revision") or "") == str(revision or "")
        ):
            return
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        self.states[key] = {
            **payload,
            "owner": owner,
            "repo": repo,
            "run_number": int(run_number),
            "revision": str(revision or ""),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        self._event(
            owner,
            repo,
            "_reconcile_production_state",
            "nyankoface-deployer",
            run_number=int(run_number),
            workflow=encoded,
            environment=state,
            revision=revision,
        )

    def production_reconcile_cursor(self, owner: str, repo: str) -> int:
        return int(self.cursors.get((owner, repo), 0))

    def record_production_reconcile_cursor(self, owner: str, repo: str, run_number: int) -> None:
        if run_number == 0:
            return
        current = self.production_reconcile_cursor(owner, repo)
        if current != 0 and run_number <= current:
            return
        self.cursors[(owner, repo)] = int(run_number)
        self._event(
            owner,
            repo,
            "_reconcile_production_cursor",
            "nyankoface-deployer",
            run_number=int(run_number),
            workflow="v1",
            environment="production",
        )

    def due_production_reconcile_states(self, owner: str, repo: str, limit: int) -> list[dict]:
        cutoff = datetime.now(timezone.utc).timestamp() - pipeline_control._PRODUCTION_WATCH_INTERVAL_SECONDS
        rows = []
        for (state_owner, state_repo, _run_number), state in self.states.items():
            if state_owner != owner or state_repo != repo:
                continue
            checked = datetime.fromisoformat(state["checked_at"]).timestamp()
            if state["state"] == "pending" or (state["state"] == "watch" and checked <= cutoff):
                rows.append(dict(state))
        return rows[:max(1, int(limit))]

    def list_tracked_repositories(self) -> list[tuple[str, str]]:
        latest: dict[tuple[str, str], int] = {}
        for event in self.events:
            if not event["action"].startswith("_reconcile_"):
                latest[(event["owner"], event["repo"])] = event["id"]
        return [key for key, _id in sorted(latest.items(), key=lambda item: item[1], reverse=True)]


@pytest.fixture(autouse=True)
def isolate_pipeline_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep artifact files and pipeline API tests local to each test."""
    store = _MemoryPipelineStore()
    monkeypatch.setattr(
        pipeline_control.config,
        "PIPELINE_DATA_DIR",
        str(tmp_path / "pipeline-data"),
    )
    monkeypatch.setattr(pipeline_control, "initialize", lambda: None)
    monkeypatch.setattr(pipeline_control, "record_event", store.record_event)
    monkeypatch.setattr(pipeline_control, "list_audit", store.list_audit)
    monkeypatch.setattr(pipeline_control, "recorded_production_revision", store.recorded_production_revision)
    monkeypatch.setattr(pipeline_control, "production_reconcile_cursor", store.production_reconcile_cursor)
    monkeypatch.setattr(pipeline_control, "latest_production_reconcile_state", store.latest_production_reconcile_state)
    monkeypatch.setattr(pipeline_control, "record_production_reconcile_state", store.record_production_reconcile_state)
    monkeypatch.setattr(pipeline_control, "record_production_reconcile_cursor", store.record_production_reconcile_cursor)
    monkeypatch.setattr(pipeline_control, "due_production_reconcile_states", store.due_production_reconcile_states)
    monkeypatch.setattr(pipeline_control, "list_tracked_repositories", store.list_tracked_repositories)
    monkeypatch.setattr(space_environment, "acquire_mutation_lock", lambda *_args: object())
    monkeypatch.setattr(space_environment, "release_mutation_lock", lambda *_args: None)


def run(coro):
    return asyncio.run(coro)


def install_key_locks(monkeypatch):
    locks: dict[str, threading.Lock] = {}; released: list[str] = []
    def acquire(_owner, _repo, name):
        lock = locks.setdefault(name, threading.Lock())
        if not lock.acquire(timeout=0.2): raise TimeoutError("busy")
        return name, lock
    def release(session):
        name, lock = session; released.append(name); lock.release()
    monkeypatch.setattr(space_environment, "acquire_mutation_lock", acquire); monkeypatch.setattr(space_environment, "release_mutation_lock", release)
    return locks, released


@pytest.mark.parametrize("phase", ["database-thread", "native-sync"])
def test_cancelled_mutation_holds_lock_until_worker_finishes(monkeypatch, phase) -> None:
    locks, released = install_key_locks(monkeypatch)
    started, finish = threading.Event(), threading.Event()
    entered = 0

    @main.serialized_environment_mutation
    async def mutate(_owner, _repo, _name):
        nonlocal entered
        if _name != "TOKEN": return
        entered += 1; started.set()
        if phase == "database-thread": await asyncio.to_thread(finish.wait)
        else:
            while not finish.is_set(): await asyncio.sleep(0.005)

    async def scenario():
        first = asyncio.create_task(mutate("o", "r", "TOKEN")); assert await asyncio.to_thread(started.wait, 0.2)
        await mutate("o", "r", "OTHER")
        first.cancel(); first.cancel()
        follower = asyncio.create_task(mutate("o", "r", "TOKEN")); await asyncio.sleep(0.03)
        assert entered == 1 and locks["TOKEN"].locked()
        finish.set()
        with pytest.raises(asyncio.CancelledError): await first
        await follower
        assert released.count("TOKEN") == 2
    run(scenario())


def test_apply_uses_repository_lock_and_drains_cancel_cleanup(monkeypatch) -> None:
    acquired: list[str | None] = []
    cleanup_started, cleanup_finish = threading.Event(), threading.Event()
    monkeypatch.setattr(space_environment, "runtime_values", lambda *_args: {})
    monkeypatch.setattr(space_environment, "acquire_mutation_lock", lambda _o, _r, name: acquired.append(name) or object()); monkeypatch.setattr(space_environment, "release_mutation_lock", lambda _session: None)
    monkeypatch.setattr(main.forgejo, "get_repo_topics", AsyncMock(return_value=[]))
    monkeypatch.setattr(main.spaces, "stop_space", lambda *_args: {"status": "stopped"})
    monkeypatch.setattr(main.spaces, "start_space", lambda *_args: {"status": "starting", "generation": 7})
    monkeypatch.setattr(main.spaces, "get_status", lambda *_args: {"status": "building", "generation": 7})
    def cancel(*_args): cleanup_started.set(); cleanup_finish.wait()
    monkeypatch.setattr(main.spaces, "cancel_space_generation", cancel)

    async def scenario():
        restart = lambda: main.restart_space_environment("o", "r", "token", wait_until_ready=True)
        operation = asyncio.create_task(main.run_serialized_environment_operation("o", "r", None, restart, cancel_operation=True))
        await asyncio.sleep(0.02)
        operation.cancel(); assert await asyncio.to_thread(cleanup_started.wait, 0.2)
        operation.cancel(); await asyncio.sleep(0.02)
        assert not operation.done()
        cleanup_finish.set()
        with pytest.raises(asyncio.CancelledError): await operation
        assert acquired == [None]
    run(scenario())
class FakeAsyncClient:
    def __init__(self, responses: list[object] | None = None):
        self.responses = list(responses or [])
        self.calls: list[tuple[str, str, dict]] = []
        self.cookies = httpx.Cookies()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def aclose(self):
        return None

    async def _request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        assert isinstance(response, httpx.Response)
        response.request = httpx.Request(method, url)
        return response

    async def get(self, url: str, **kwargs):
        return await self._request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs):
        return await self._request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs):
        return await self._request("PUT", url, **kwargs)

    async def delete(self, url: str, **kwargs):
        return await self._request("DELETE", url, **kwargs)

    def stream(self, method: str, url: str, **kwargs):
        client = self

        class StreamContext:
            response: httpx.Response | None = None

            async def __aenter__(self):
                self.response = await client._request(method, url, **kwargs)
                return self.response

            async def __aexit__(self, *_args):
                if self.response is not None:
                    await self.response.aclose()

        return StreamContext()


def response(status: int, payload: object | None = None) -> httpx.Response:
    if payload is None:
        return httpx.Response(status)
    return httpx.Response(status, json=payload)


def text_response(status: int, payload: str) -> httpx.Response:
    return httpx.Response(status, text=payload)


def test_starter_workflow_covers_triggers_safety_and_deployments() -> None:
    workflow = pipeline_control.STARTER_WORKFLOW

    for trigger in (
        "push:",
        "pull_request:",
        "release:",
        "schedule:",
        "workflow_dispatch:",
    ):
        assert trigger in workflow
    assert "concurrency:" in workflow
    concurrency = workflow.split("concurrency:", 1)[1].split(
        "\njobs:",
        1,
    )[0]
    assert "&& 'production'" in concurrency
    assert "(inputs.environment == 'staging' && 'staging')" in concurrency
    assert (
        "format('{0}-{1}', inputs.environment || github.event_name, github.ref)"
        in concurrency
    )
    assert "github.event.repository.default_branch" in concurrency
    assert "startsWith(github.ref, 'refs/tags/')" in concurrency
    assert "inputs.approve_production == 'true'" in concurrency
    assert "cancel-in-progress: ${{ !((" in concurrency
    assert "cancel-in-progress: true" not in concurrency
    assert (
        "group: nyankoface-${{ github.workflow }}-${{ github.ref }}"
        not in concurrency
    )
    assert "timeout-minutes:" in workflow
    assert (
        "actions/cache@5a3ec84eff668545956fd18022155c47e93e2684"
        in workflow
    )
    assert (
        "actions/upload-artifact@a8a3f3ad30e3422c9c7b888a15615d19a852ae32"
        in workflow
    )
    assert (
        "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683"
        in workflow
    )
    assert "@v3" not in workflow
    assert "@v4" not in workflow
    assert (
        "nyankoface-preview-site-${{ needs.validate.outputs.revision }}"
        in workflow
    )
    assert (
        "nyankoface-staging-site-${{ needs.validate.outputs.revision }}"
        in workflow
    )
    assert "nyankoface-site-manifest.json" in workflow
    assert workflow.count("npm run docs:build") == 4
    assert (
        'VITEPRESS_BASE="/previews/${GITHUB_REPOSITORY}/${PREVIEW_KEY}/"'
        in workflow
    )
    assert (
        'VITEPRESS_BASE="/staging/${GITHUB_REPOSITORY}/"'
        in workflow
    )
    assert (
        'VITEPRESS_BASE="/pages/${GITHUB_REPOSITORY}/"'
        in workflow
    )
    assert '\\"environment\\":\\"staging\\",\\"operation\\":\\"delete\\"' in workflow
    assert '\\"environment\\":\\"staging\\",\\"operation\\":\\"publish\\"' in workflow
    staging_upload = workflow.split("- name: Upload staging artifact", 1)[1]
    assert not staging_upload.lstrip().startswith("if:")
    assert "path: .nyankoface-artifacts/" in staging_upload
    assert "Record immutable production revision" in workflow
    assert (
        "nyankoface-production-revision-${{ steps.deployed.outputs.sha }}"
        in workflow
    )
    assert "No Pages output detected; disabling the previous Pages publication." in workflow
    assert "- name: Reconcile gh-pages" in workflow
    production_reconcile = workflow.split("- name: Reconcile gh-pages", 1)[1]
    assert not production_reconcile.lstrip().startswith("if:")
    assert ".nyankoface-pages-tombstone.json" in production_reconcile
    assert '\\"environment\\":\\"production\\",\\"operation\\":\\"delete\\"' in workflow
    assert 'COMMIT_MESSAGE="Disable Pages for ${DEPLOY_REVISION}"' in workflow
    assert "artifact_sha256" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "github.event_name != 'pull_request'" in workflow
    assert "environment: preview" not in workflow
    assert "environment: staging" in workflow
    assert workflow.count("environment: production") >= 2
    assert "NYANKOFACE_DEPLOY_TOKEN" in workflow
    assert 'DEPLOY_REVISION="$(git rev-parse HEAD)"' in workflow
    assert '\\"revision\\":\\"${DEPLOY_REVISION}\\"' in workflow
    assert "NYANKOFACE_PIPELINE_WEBHOOK_URL" in workflow
    assert "Check out deployed revision" in workflow
    assert (
        '\\"sha\\":\\"${DEPLOY_REVISION}\\",'
        '\\"run_id\\":\\"${GITHUB_RUN_ID}\\"'
    ) in workflow
    assert '\\"status\\":\\"${PIPELINE_STATUS}\\"' in workflow
    for result in (
        "VALIDATE_RESULT",
        "PREVIEW_RESULT",
        "STAGING_RESULT",
        "PRODUCTION_RESULT",
        "SPACE_RESULT",
    ):
        assert f"${{{{ needs.{result.removesuffix('_RESULT').lower()}.result }}}}" in workflow
        assert f"${{{result}}}" in workflow
    assert '\\"sha\\":\\"${GITHUB_SHA}\\"' not in workflow
    assert "Deploy ${GITHUB_SHA}" not in workflow
    assert "inputs.approve_production == 'true'" in workflow
    assert "inputs.runner || 'node20'" in workflow
    assert workflow.count("ref: ${{ inputs.revision || github.sha }}") == 1
    assert workflow.count("ref: ${{ needs.validate.outputs.revision }}") == 5
    assert "outputs:\n      revision: ${{ steps.revision.outputs.sha }}" in workflow
    assert "Resolve immutable revision" in workflow
    assert 'echo "sha=${RESOLVED_REVISION}" >> "${GITHUB_OUTPUT}"' in workflow
    assert "github.ref_name == github.event.repository.default_branch" in workflow
    assert "refs/heads/main" not in workflow
    assert "github.event_name" in workflow
    assert "forgejo.event_name" not in workflow
    assert "GITHUB_REPOSITORY" in workflow
    assert "FORGEJO_REPOSITORY" not in workflow
    assert workflow.index("preview:") < workflow.index("NYANKOFACE_DEPLOY_TOKEN")


def test_seeded_and_api_installed_workflows_stay_identical() -> None:
    root = Path(__file__).resolve().parents[2]
    seeded = (
        root
        / "seed"
        / "templates"
        / "nyankoface-pipeline"
        / "nyankoface-pipeline.yml"
    ).read_text(encoding="utf-8")

    assert seeded == pipeline_control.STARTER_WORKFLOW


def test_run_environment_prefers_explicit_run_name() -> None:
    assert pipeline_control._run_environment(
        {"display_title": "NyankoFace staging · main", "head_branch": "main"},
        "main",
    ) == "staging"
    assert pipeline_control._run_environment(
        {"event": "pull_request", "head_branch": "feature"},
        "main",
    ) == "preview"
    assert pipeline_control._run_environment(
        {"event": "push", "head_branch": "main"},
        "main",
    ) == "production"
    assert pipeline_control._run_environment(
        {
            "event_payload": (
                '{"inputs":{"environment":"staging"},'
                '"ref":"refs/heads/main"}'
            ),
            "head_branch": "main",
        },
        "main",
    ) == "staging"
    assert pipeline_control._run_environment(
        {"event": "release", "head_branch": "v2.0.0"},
        "main",
    ) == "production"
    assert pipeline_control._run_environment(
        {
            "event": "push",
            "ref": "refs/tags/v2.0.0",
            "head_branch": "v2.0.0",
        },
        "main",
    ) == "production"
    assert pipeline_control._run_environment(
        {
            "event": "workflow_dispatch",
            "event_payload": (
                '{"inputs":{"environment":"staging"},'
                '"ref":"refs/tags/v2.0.0"}'
            ),
            "ref": "refs/tags/v2.0.0",
            "head_branch": "v2.0.0",
        },
        "main",
    ) == "production"


def test_run_environment_uses_active_deployment_job() -> None:
    assert pipeline_control._run_environment_from_jobs(
        [
            {"name": "Preview artifact", "status": "skipped"},
            {"name": "Staging artifact", "status": "running"},
            {"name": "Publish production Pages", "status": "skipped"},
        ],
        {"event": "workflow_dispatch", "head_branch": "main"},
        "main",
    ) == "staging"
    assert pipeline_control._run_environment_from_jobs(
        [{"name": "Unit tests", "status": "success"}],
        {"event": "push", "head_branch": "main"},
        "main",
    ) == "staging"
    assert pipeline_control._run_environment_from_jobs(
        [{"name": "Unit tests", "status": "success"}],
        {
            "event": "workflow_dispatch",
            "event_payload": '{"inputs":{"environment":"production"}}',
            "head_branch": "main",
        },
        "main",
    ) == "production"
    assert pipeline_control._run_environment_from_jobs(
        [
            {"name": "Staging artifact", "status": "success"},
            {"name": "Publish production Pages", "status": "success"},
        ],
        {
            "event": "workflow_dispatch",
            "event_payload": (
                '{"inputs":{"environment":"staging"},'
                '"ref":"refs/tags/v2.0.0"}'
            ),
            "ref": "refs/tags/v2.0.0",
            "head_branch": "v2.0.0",
        },
        "main",
    ) == "production"


def test_deployed_revision_prefers_workflow_dispatch_input() -> None:
    assert pipeline_control._deployed_revision(
        {
            "deployed_revision": "recorded-release",
            "event_payload": '{"inputs":{"revision":"release-v2"}}',
            "head_sha": "default-branch-sha",
        }
    ) == "recorded-release"
    assert pipeline_control._deployed_revision(
        {
            "event_payload": '{"inputs":{"revision":"release-v2"}}',
            "head_sha": "default-branch-sha",
        }
    ) == "release-v2"
    assert pipeline_control._deployed_revision(
        {"event_payload": "not-json", "head_sha": "fallback-sha"}
    ) == "fallback-sha"


def test_pull_request_approval_url_uses_native_trust_panel() -> None:
    assert pipeline_control._pull_request_approval_url(
        "acme",
        "site",
        {
            "need_approval": True,
            "event_payload": '{"pull_request":{"number":17}}',
        },
    ) == "/git/acme/site/pulls/17#pull-request-trust-panel"
    assert (
        pipeline_control._pull_request_approval_url(
            "acme",
            "site",
            {"need_approval": False, "event_payload": '{"number":17}'},
        )
        is None
    )
    assert (
        pipeline_control._pull_request_approval_url(
            "acme",
            "site",
            {"need_approval": True, "event_payload": "not-json"},
        )
        is None
    )


def test_preview_and_staging_deployment_keys_are_stable() -> None:
    assert pipeline_control._deployment_key(
        {
            "event": "pull_request",
            "event_payload": '{"action":"synchronize","pull_request":{"number":17}}',
        },
        41,
        "preview",
    ) == ("pr-17", False)
    assert pipeline_control._deployment_key(
        {
            "event": "pull_request",
            "event_payload": '{"action":"closed","pull_request":{"number":17}}',
        },
        42,
        "preview",
    ) == ("pr-17", True)
    assert pipeline_control._deployment_key(
        {"event": "workflow_dispatch"},
        43,
        "preview",
    ) == ("run-43", False)
    assert pipeline_control._deployment_key({}, 44, "staging") == (
        "current",
        False,
    )


def test_environment_url_and_successful_publish_job_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline_control.config,
        "PUBLIC_BASE_URL",
        "https://nyankoface.example/",
    )
    assert pipeline_control._deployment_url(
        "acme", "site", "preview", "pr-17"
    ) == "https://nyankoface.example/previews/acme/site/pr-17/"
    assert pipeline_control._deployment_url(
        "acme", "site", "staging", "current"
    ) == "https://nyankoface.example/staging/acme/site/"
    assert pipeline_control._deployment_job_succeeded(
        [{"name": "Publish preview site", "status": "success"}],
        "preview",
    )
    assert not pipeline_control._deployment_job_succeeded(
        [{"name": "Publish preview site", "status": "failure"}],
        "preview",
    )


def test_successful_preview_run_downloads_and_publishes_verified_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeAsyncClient(
        [
            response(
                200,
                [
                    {
                        "id": 501,
                        "name": "nyankoface-preview-site-abc123",
                        "expired": False,
                    }
                ],
            ),
            httpx.Response(200, content=b"verified-artifact-zip"),
        ]
    )
    published: list[dict] = []
    events: list[dict] = []
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "metadata",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "deletion_source_sha",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "source_sha",
        lambda *_args, **_kwargs: "abc123",
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "publish",
        lambda **kwargs: (
            published.append(kwargs)
            or {
                "source_sha": kwargs["expected_sha"],
                "run_id": kwargs["expected_run_id"],
                "artifact_id": kwargs["artifact_id"],
            }
        ),
    )
    monkeypatch.setattr(
        pipeline_control,
        "record_event",
        lambda *args, **kwargs: events.append({"args": args, **kwargs}),
    )

    result = run(
        pipeline_control._reconcile_environment_site(
            "acme",
            "site",
            {
                "id": 71,
                "index_in_repo": 9,
                "event": "pull_request",
                "event_payload": (
                    '{"action":"synchronize","pull_request":{"number":4}}'
                ),
                "commit_sha": "abc123",
            },
            [{"name": "Publish preview site", "status": "success"}],
            environment="preview",
            run_number=9,
            token="token",
            public_repo=True,
        )
    )

    assert result is not None
    assert result["url"].endswith("/previews/acme/site/pr-4/")
    assert published[0]["artifact_zip"] == b"verified-artifact-zip"
    assert published[0]["expected_repository"] == "acme/site"
    assert published[0]["expected_sha"] == "abc123"
    assert published[0]["expected_run_id"] == 71
    assert published[0]["expected_run_number"] == 9
    assert events[0]["args"][2] == "publish_preview"
    assert [call[0] for call in client.calls] == ["GET", "GET"]


def test_oversized_preview_artifact_is_rejected_while_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ChunkStream(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.yielded = 0
            self.closed = False

        async def __aiter__(self):
            for chunk in (b"abc", b"def", b"never"):
                self.yielded += 1
                yield chunk

        async def aclose(self) -> None:
            self.closed = True

    stream = ChunkStream()
    client = FakeAsyncClient(
        [
            response(
                200,
                [
                    {
                        "id": 501,
                        "name": "nyankoface-preview-site-abc123",
                        "expired": False,
                    }
                ],
            ),
            httpx.Response(200, stream=stream),
        ]
    )
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "MAX_ARCHIVE_BYTES",
        5,
    )
    source_sha_called = False

    def source_sha(*_args, **_kwargs):
        nonlocal source_sha_called
        source_sha_called = True
        return "abc123"

    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "source_sha",
        source_sha,
    )

    result = run(
        pipeline_control._reconcile_environment_site(
            "acme",
            "site",
            {
                "id": 71,
                "event": "pull_request",
                "event_payload": (
                    '{"action":"synchronize","pull_request":{"number":4}}'
                ),
            },
            [{"name": "Publish preview site", "status": "success"}],
            environment="preview",
            run_number=9,
            token="token",
            public_repo=True,
        )
    )

    assert result is None
    assert stream.yielded == 2
    assert stream.closed is True
    assert source_sha_called is False


def test_workflow_dispatch_artifact_uses_resolved_checkout_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeAsyncClient(
        [
            response(
                200,
                [
                    {
                        "id": 502,
                        "name": "nyankoface-staging-site-resolved-release-sha",
                        "expired": False,
                    }
                ],
            ),
            httpx.Response(200, content=b"verified-artifact-zip"),
        ]
    )
    published: list[dict] = []
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "metadata",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "deletion_source_sha",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "source_sha",
        lambda *_args, **_kwargs: "resolved-release-sha",
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "publish",
        lambda **kwargs: published.append(kwargs) or kwargs,
    )
    monkeypatch.setattr(
        pipeline_control,
        "record_event",
        lambda *_args, **_kwargs: None,
    )

    result = run(
        pipeline_control._reconcile_environment_site(
            "acme",
            "site",
            {
                "id": 72,
                "event": "workflow_dispatch",
                "event_payload": '{"inputs":{"revision":"release/v2"}}',
                "commit_sha": "dispatch-ref-sha",
            },
            [{"name": "Publish staging site", "status": "success"}],
            environment="staging",
            run_number=10,
            token="token",
            public_repo=True,
        )
    )

    assert result is not None
    assert published[0]["expected_sha"] == "resolved-release-sha"
    assert [call[0] for call in client.calls] == ["GET", "GET"]


def test_staging_deletion_marker_expires_current_deployment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeAsyncClient(
        [
            response(
                200,
                [
                    {
                        "id": 504,
                        "name": "nyankoface-staging-site-deleted-sha",
                        "expired": False,
                    }
                ],
            ),
            httpx.Response(200, content=b"deletion-marker-zip"),
        ]
    )
    deleted: list[dict] = []
    events: list[dict] = []
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "metadata",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "deletion_source_sha",
        lambda *_args, **_kwargs: "d" * 40,
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "mark_staging_deleted",
        lambda *args, **kwargs: deleted.append(
            {"args": args, **kwargs}
        ),
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "source_sha",
        lambda *_args, **_kwargs: pytest.fail(
            "a deletion marker must not be published"
        ),
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "publish",
        lambda **_kwargs: pytest.fail(
            "a deletion marker must not be published"
        ),
    )
    monkeypatch.setattr(
        pipeline_control,
        "record_event",
        lambda *args, **kwargs: events.append({"args": args, **kwargs}),
    )

    result = run(
        pipeline_control._reconcile_environment_site(
            "acme",
            "site",
            {
                "id": 74,
                "event": "workflow_dispatch",
                "event_payload": '{"inputs":{"revision":"main"}}',
                "commit_sha": "deleted-sha",
            },
            [{"name": "Publish staging site", "status": "success"}],
            environment="staging",
            run_number=12,
            token="token",
            public_repo=True,
        )
    )

    assert result is None
    assert deleted == [
        {
            "args": ("acme", "site"),
            "run_number": 12,
            "source_sha": "d" * 40,
        }
    ]
    assert events[0]["args"][2] == "expire_staging"
    assert events[0]["run_number"] == 12
    assert [call[0] for call in client.calls] == ["GET", "GET"]


def test_preview_deletion_marker_expires_previous_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeAsyncClient(
        [
            response(
                200,
                [
                    {
                        "id": 506,
                        "name": "nyankoface-preview-site-deleted-sha",
                        "expired": False,
                    }
                ],
            ),
            httpx.Response(200, content=b"deletion-marker-zip"),
        ]
    )
    deleted: list[dict] = []
    events: list[dict] = []
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "deletion_source_sha",
        lambda *_args, **_kwargs: "d" * 40,
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "mark_preview_deleted",
        lambda *args, **kwargs: deleted.append(
            {"args": args, **kwargs}
        ),
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "source_sha",
        lambda *_args, **_kwargs: pytest.fail(
            "a deletion marker must not be published"
        ),
    )
    monkeypatch.setattr(
        pipeline_control,
        "record_event",
        lambda *args, **kwargs: events.append({"args": args, **kwargs}),
    )

    result = run(
        pipeline_control._reconcile_environment_site(
            "acme",
            "site",
            {
                "id": 76,
                "event": "pull_request",
                "event_payload": (
                    '{"action":"synchronize","pull_request":{"number":4}}'
                ),
                "commit_sha": "deleted-sha",
            },
            [{"name": "Publish preview site", "status": "success"}],
            environment="preview",
            run_number=14,
            token="token",
            public_repo=True,
        )
    )

    assert result is None
    assert deleted == [
        {
            "args": ("acme", "site", "pr-4"),
            "run_number": 14,
            "source_sha": "d" * 40,
        }
    ]
    assert events[0]["args"][2] == "expire_preview"


def test_missing_or_invalid_staging_artifact_never_deletes_current_deployment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeAsyncClient(
        [
            response(
                200,
                [
                    {
                        "id": 505,
                        "name": "nyankoface-staging-site-invalid-sha",
                        "expired": False,
                    }
                ],
            ),
            httpx.Response(200, content=b"invalid-artifact"),
        ]
    )
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "metadata",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "deletion_source_sha",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            pipeline_control.preview_artifacts.PreviewArtifactError(
                "invalid deletion marker"
            )
        ),
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "mark_staging_deleted",
        lambda *_args, **_kwargs: pytest.fail(
            "invalid artifacts must never delete staging"
        ),
    )

    result = run(
        pipeline_control._reconcile_environment_site(
            "acme",
            "site",
            {
                "id": 75,
                "event": "workflow_dispatch",
                "event_payload": '{"inputs":{"revision":"main"}}',
                "commit_sha": "invalid-sha",
            },
            [{"name": "Publish staging site", "status": "success"}],
            environment="staging",
            run_number=13,
            token="token",
            public_repo=True,
        )
    )

    assert result is None


def test_production_revision_artifact_persists_immutable_sha(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision = "a" * 40
    client = FakeAsyncClient(
        [
            response(
                200,
                [
                    {
                        "id": 503,
                        "name": f"nyankoface-production-revision-{revision}",
                        "expired": False,
                    }
                ],
            ),
            response(
                200,
                [
                    {
                        "id": 503,
                        "name": f"nyankoface-production-revision-{revision}",
                        "expired": False,
                    }
                ],
            ),
        ]
    )
    monkeypatch.setattr(pipeline_control.config, "PIPELINE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )

    resolved = run(
        pipeline_control._reconcile_production_revision(
            "acme",
            "site",
            {"id": 73},
            [{"name": "Publish production Pages", "status": "success"}],
            run_number=11,
            token="token",
        )
    )

    assert resolved == revision
    assert (
        pipeline_control.recorded_production_revision("acme", "site", 11)
        == revision
    )

    second = run(
        pipeline_control._reconcile_production_revision(
            "acme",
            "site",
            {"id": 73},
            [{"name": "Publish production Pages", "status": "success"}],
            run_number=11,
            token="token",
        )
    )
    assert second == revision
    assert len(client.calls) == 2


def test_production_retry_replaces_recorded_revision_with_latest_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_revision = "a" * 40
    retry_revision = "b" * 40
    monkeypatch.setattr(
        pipeline_control.config,
        "PIPELINE_DATA_DIR",
        str(tmp_path),
    )
    pipeline_control.record_event(
        "acme",
        "site",
        "deploy_production",
        "nyankoface-deployer",
        run_number=11,
        environment="production",
        revision=first_revision,
    )
    client = FakeAsyncClient(
        [
            response(
                200,
                [
                    {
                        "id": 503,
                        "name": (
                            "nyankoface-production-revision-"
                            f"{first_revision}"
                        ),
                        "expired": False,
                    },
                    {
                        "id": 504,
                        "name": (
                            "nyankoface-production-revision-"
                            f"{retry_revision}"
                        ),
                        "expired": False,
                    },
                ],
            )
        ]
    )
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )

    resolved = run(
        pipeline_control._reconcile_production_revision(
            "acme",
            "site",
            {"id": 73},
            [{"name": "Publish production Pages", "status": "success"}],
            run_number=11,
            token="token",
        )
    )

    assert resolved == retry_revision
    assert (
        pipeline_control.recorded_production_revision("acme", "site", 11)
        == retry_revision
    )


def test_production_artifact_visibility_lag_stays_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    revision = "a" * 40
    item = {
        "id": 73,
        "index_in_repo": 11,
        "commit_sha": revision,
        "status": "success",
        "updated": "2026-07-31T00:01:00Z",
    }
    client = FakeAsyncClient(
        [
            response(200, []),
            response(
                200,
                [
                    {
                        "id": 503,
                        "name": f"nyankoface-production-revision-{revision}",
                        "expired": False,
                        "expires_at": "2026-10-29T00:01:00Z",
                    }
                ],
            ),
        ]
    )
    monkeypatch.setattr(
        pipeline_control.config,
        "PIPELINE_DATA_DIR",
        str(tmp_path),
    )
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    jobs = [
        {
            "name": "Publish production Pages",
            "status": "success",
            "attempt": 1,
        }
    ]

    first = run(
        pipeline_control._reconcile_production_revision(
            "acme",
            "site",
            item,
            jobs,
            run_number=11,
            token="token",
            detailed=True,
        )
    )
    second = run(
        pipeline_control._reconcile_production_revision(
            "acme",
            "site",
            item,
            jobs,
            run_number=11,
            token="token",
            detailed=True,
        )
    )

    assert first[0] == ""
    assert first[1]["state"] == "pending"
    assert second[0] == revision
    assert second[1]["state"] == "watch"
    assert second[1]["artifact_id"] == 503


def test_reconciliation_after_cursor_uses_one_head_request_for_unchanged_watch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def repo_info(*_args):
        return {"default_branch": "main", "private": False}

    item = {
        "id": 1088,
        "index_in_repo": 1000,
        "event": "push",
        "prettyref": "main",
        "commit_sha": "a" * 40,
        "status": "success",
        "updated": "2026-07-31T00:01:00Z",
    }
    monkeypatch.setattr(
        pipeline_control.config,
        "PIPELINE_DATA_DIR",
        str(tmp_path),
    )
    monkeypatch.setattr(
        pipeline_control,
        "_PRODUCTION_WATCH_INTERVAL_SECONDS",
        0,
    )
    pipeline_control.record_production_reconcile_cursor(
        "acme",
        "site",
        1000,
    )
    pipeline_control.record_production_reconcile_state(
        "acme",
        "site",
        run_number=1000,
        state="watch",
        run_id=1088,
        fingerprint=pipeline_control._production_run_fingerprint(item),
        updated=item["updated"],
        artifact_id=500,
        expires_at="2026-10-29T00:01:00Z",
        revision=item["commit_sha"],
    )
    client = FakeAsyncClient(
        [response(200, {"workflow_runs": [item]})]
    )
    monkeypatch.setattr(pipeline_control.forgejo, "get_repo_info", repo_info)
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "prune_run_previews",
        lambda *_args, **_kwargs: [],
    )

    result = run(
        pipeline_control.reconcile_repository_deployments(
            "acme",
            "site",
            "token",
        )
    )

    assert result == []
    assert len(client.calls) == 1
    assert client.calls[0][2]["params"] == {"limit": 50, "page": 1}
    assert pipeline_control.list_audit("acme", "site") == []


def test_reconciliation_discovers_only_a_fixed_run_number_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def repo_info(*_args):
        return {"default_branch": "main", "private": False}

    def production(number: int) -> dict:
        return {
            "id": 2000 + number,
            "index_in_repo": number,
            "event": "push",
            "prettyref": "main",
            "commit_sha": f"{number:040x}",
            "status": "success",
            "updated": f"2026-07-31T00:{number % 60:02d}:00Z",
        }

    monkeypatch.setattr(
        pipeline_control.config,
        "PIPELINE_DATA_DIR",
        str(tmp_path),
    )
    monkeypatch.setattr(
        pipeline_control.config,
        "PIPELINE_DISCOVERY_BATCH_SIZE",
        3,
    )
    pipeline_control.record_production_reconcile_cursor(
        "acme",
        "site",
        1000,
    )
    client = FakeAsyncClient(
        [
            response(200, {"workflow_runs": [production(1012)]}),
            response(200, {"workflow_runs": [production(1001)]}),
            response(200, {"workflow_runs": [production(1002)]}),
            response(200, {"workflow_runs": [production(1003)]}),
        ]
    )
    monkeypatch.setattr(pipeline_control.forgejo, "get_repo_info", repo_info)
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        pipeline_control,
        "due_production_reconcile_states",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "prune_run_previews",
        lambda *_args, **_kwargs: [],
    )

    run(
        pipeline_control.reconcile_repository_deployments(
            "acme",
            "site",
            "token",
        )
    )

    assert pipeline_control.production_reconcile_cursor(
        "acme",
        "site",
    ) == 1003
    assert [
        call[2].get("params", {}).get("run_number")
        for call in client.calls[1:]
    ] == [1001, 1002, 1003]
    assert len(client.calls) == 4


def test_reconciliation_remembers_active_production_before_advancing_cursor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def repo_info(*_args):
        return {"default_branch": "main", "private": False}

    active = {
        "id": 3001,
        "index_in_repo": 1001,
        "event": "push",
        "prettyref": "main",
        "commit_sha": "a" * 40,
        "status": "running",
        "updated": "2026-07-31T00:01:00Z",
    }
    monkeypatch.setattr(
        pipeline_control.config,
        "PIPELINE_DATA_DIR",
        str(tmp_path),
    )
    pipeline_control.record_production_reconcile_cursor(
        "acme",
        "site",
        1000,
    )
    client = FakeAsyncClient(
        [response(200, {"workflow_runs": [active]})]
    )
    monkeypatch.setattr(pipeline_control.forgejo, "get_repo_info", repo_info)
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        pipeline_control,
        "due_production_reconcile_states",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "prune_run_previews",
        lambda *_args, **_kwargs: [],
    )

    run(
        pipeline_control.reconcile_repository_deployments(
            "acme",
            "site",
            "token",
        )
    )

    assert pipeline_control.production_reconcile_cursor(
        "acme",
        "site",
    ) == 1001
    state = pipeline_control.latest_production_reconcile_state(
        "acme",
        "site",
        1001,
    )
    assert state is not None
    assert state["state"] == "pending"
    assert state["run_id"] == 3001


def test_changed_watched_run_fetches_jobs_and_new_artifact_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def repo_info(*_args):
        return {"default_branch": "main", "private": False}

    old_item = {
        "id": 88,
        "index_in_repo": 12,
        "event": "push",
        "prettyref": "main",
        "commit_sha": "a" * 40,
        "status": "success",
        "updated": "2026-07-31T00:01:00Z",
    }
    changed_item = {
        **old_item,
        "commit_sha": "b" * 40,
        "updated": "2026-07-31T00:05:00Z",
    }
    monkeypatch.setattr(
        pipeline_control.config,
        "PIPELINE_DATA_DIR",
        str(tmp_path),
    )
    pipeline_control.record_production_reconcile_cursor(
        "acme",
        "site",
        12,
    )
    pipeline_control.record_production_reconcile_state(
        "acme",
        "site",
        run_number=12,
        state="watch",
        run_id=88,
        fingerprint=pipeline_control._production_run_fingerprint(old_item),
        updated=old_item["updated"],
        attempt=1,
        artifact_id=501,
        expires_at="2026-10-29T00:01:00Z",
        revision=old_item["commit_sha"],
    )
    client = FakeAsyncClient(
        [
            response(200, {"workflow_runs": [changed_item]}),
            response(
                200,
                {
                    "jobs": [
                        {
                            "name": "Publish production Pages",
                            "status": "success",
                            "attempt": 2,
                        }
                    ]
                },
            ),
            response(
                200,
                [
                    {
                        "id": 502,
                        "name": (
                            "nyankoface-production-revision-"
                            f"{changed_item['commit_sha']}"
                        ),
                        "expired": False,
                        "expires_at": "2026-10-29T00:05:00Z",
                    }
                ],
            ),
        ]
    )
    monkeypatch.setattr(pipeline_control.forgejo, "get_repo_info", repo_info)
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "prune_run_previews",
        lambda *_args, **_kwargs: [],
    )

    result = run(
        pipeline_control.reconcile_repository_deployments(
            "acme",
            "site",
            "token",
        )
    )

    assert result == [
        {
            "environment": "production",
            "run_number": 12,
            "source_sha": changed_item["commit_sha"],
        }
    ]
    assert len(client.calls) == 3
    state = pipeline_control.latest_production_reconcile_state(
        "acme",
        "site",
        12,
    )
    assert state["state"] == "watch"
    assert state["attempt"] == 2
    assert state["artifact_id"] == 502


def test_closed_pull_request_expires_preview_without_fetching_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    removed: list[tuple] = []
    events: list[dict] = []
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "mark_preview_closed",
        lambda *args, **kwargs: (
            removed.append((*args, kwargs["run_number"]))
            or {"advanced": True, "removed": True}
        ),
    )
    monkeypatch.setattr(
        pipeline_control,
        "record_event",
        lambda *args, **kwargs: events.append({"args": args, **kwargs}),
    )

    result = run(
        pipeline_control._reconcile_environment_site(
            "acme",
            "site",
            {
                "id": 72,
                "event": "pull_request",
                "event_payload": (
                    '{"action":"closed","pull_request":{"number":4}}'
                ),
                "commit_sha": "def456",
            },
            [],
            environment="preview",
            run_number=10,
            token="token",
            public_repo=True,
        )
    )

    assert result is None
    assert removed == [("acme", "site", "pr-4", 10)]
    assert events[0]["args"][2] == "expire_preview"


def test_list_runs_reconciles_only_latest_event_for_each_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def repo_info(*_args):
        return {"default_branch": "main", "private": False}

    client = FakeAsyncClient(
        [
            response(
                200,
                {
                    "workflow_runs": [
                        {
                            "id": 72,
                            "index_in_repo": 10,
                            "status": "skipped",
                            "event": "pull_request",
                            "event_payload": (
                                '{"action":"closed","pull_request":{"number":4}}'
                            ),
                            "prettyref": "feature",
                            "commit_sha": "def456",
                            "workflow_id": "nyankoface-pipeline.yml",
                        },
                        {
                            "id": 71,
                            "index_in_repo": 9,
                            "status": "success",
                            "event": "pull_request",
                            "event_payload": (
                                '{"action":"opened","pull_request":{"number":4}}'
                            ),
                            "prettyref": "feature",
                            "commit_sha": "abc123",
                            "workflow_id": "nyankoface-pipeline.yml",
                        },
                    ]
                },
            ),
            response(200, []),
            response(
                200,
                [{"name": "Publish preview site", "status": "success"}],
            ),
        ]
    )
    reconciled: list[int] = []

    async def reconcile(_owner, _repo, item, _jobs, **_kwargs):
        reconciled.append(int(item["index_in_repo"]))
        return None

    monkeypatch.setattr(pipeline_control.forgejo, "get_repo_info", repo_info)
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        pipeline_control,
        "_reconcile_environment_site",
        reconcile,
    )

    items = run(pipeline_control.list_runs("acme", "site", "token"))

    assert [item["run_number"] for item in items] == [10, 9]
    assert reconciled == [10]


def test_audit_events_register_repositories_for_background_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline_control.config, "PIPELINE_DATA_DIR", str(tmp_path))

    pipeline_control.record_event("acme", "site", "install", "admin")
    pipeline_control.record_event("acme", "site", "dispatch", "admin")
    pipeline_control.record_event("acme", "other", "install", "admin")

    assert pipeline_control.list_tracked_repositories() == [
        ("acme", "other"),
        ("acme", "site"),
    ]


def test_install_starter_idempotently_tracks_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline_control.config, "PIPELINE_DATA_DIR", str(tmp_path))

    async def repo_info(*_args):
        return {"default_branch": "main"}

    async def upsert(*_args):
        return {"sha": "a" * 40, "unchanged": True}

    monkeypatch.setattr(pipeline_control.forgejo, "get_repo_info", repo_info)
    monkeypatch.setattr(pipeline_control.forgejo, "upsert_repo_file", upsert)

    first = run(
        pipeline_control.install_starter(
            "nyankoface",
            "pages-starter",
            "token",
            "nyankoface-admin",
        )
    )
    second = run(
        pipeline_control.install_starter(
            "nyankoface",
            "pages-starter",
            "token",
            "nyankoface-admin",
        )
    )

    assert first["status"] == "installed"
    assert second["status"] == "installed"
    assert pipeline_control.list_tracked_repositories() == [
        ("nyankoface", "pages-starter")
    ]


def test_background_reconciliation_bootstrap_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def repo_info(*_args):
        return {"default_branch": "main", "private": False}

    newest_page = [
        {
            "id": run_id,
            "index_in_repo": run_id,
            "event": "push",
            "prettyref": "main",
            "commit_sha": f"sha-{run_id}",
        }
        for run_id in range(100, 50, -1)
    ]
    client = FakeAsyncClient(
        [response(200, {"workflow_runs": newest_page})]
    )
    monkeypatch.setattr(
        pipeline_control.config,
        "PIPELINE_DISCOVERY_BATCH_SIZE",
        3,
    )

    monkeypatch.setattr(pipeline_control.forgejo, "get_repo_info", repo_info)
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        pipeline_control,
        "due_production_reconcile_states",
        lambda *_args, **_kwargs: [],
    )

    result = run(
        pipeline_control.reconcile_repository_deployments(
            "acme",
            "site",
            "token",
        )
    )

    assert result == []
    assert pipeline_control.production_reconcile_cursor(
        "acme",
        "site",
    ) == -50
    assert len(client.calls) == 1
    assert client.calls[0][2]["params"] == {"limit": 50, "page": 1}

    backfill_client = FakeAsyncClient(
        [
            response(200, {"workflow_runs": newest_page}),
            response(200, {"workflow_runs": []}),
            response(200, {"workflow_runs": []}),
            response(200, {"workflow_runs": []}),
        ]
    )
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: backfill_client,
    )
    run(
        pipeline_control.reconcile_repository_deployments(
            "acme",
            "site",
            "token",
        )
    )
    assert pipeline_control.production_reconcile_cursor(
        "acme",
        "site",
    ) == -47
    assert [
        call[2]["params"]["run_number"]
        for call in backfill_client.calls[1:]
    ] == [48, 49, 50]


def test_background_backfill_does_not_roll_staging_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def repo_info(*_args):
        return {"default_branch": "main", "private": False}

    head_run = {
        "id": 1100,
        "index_in_repo": 100,
        "event": "push",
        "prettyref": "main",
        "commit_sha": "newest-production",
    }
    historical_staging = {
        "id": 1050,
        "index_in_repo": 50,
        "event": "workflow_dispatch",
        "event_payload": '{"inputs":{"environment":"staging"}}',
        "prettyref": "old-feature",
        "commit_sha": "old-staging",
    }
    pipeline_control.record_production_reconcile_cursor(
        "acme",
        "site",
        -50,
    )
    monkeypatch.setattr(
        pipeline_control.config,
        "PIPELINE_DISCOVERY_BATCH_SIZE",
        3,
    )
    client = FakeAsyncClient(
        [
            response(200, {"workflow_runs": [head_run]}),
            response(200, {"workflow_runs": []}),
            response(200, {"workflow_runs": []}),
            response(200, {"workflow_runs": [historical_staging]}),
        ]
    )
    monkeypatch.setattr(pipeline_control.forgejo, "get_repo_info", repo_info)
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        pipeline_control,
        "due_production_reconcile_states",
        lambda *_args, **_kwargs: [],
    )

    async def reject_staging(*_args, **_kwargs):
        raise AssertionError("historical staging must not be republished")

    monkeypatch.setattr(
        pipeline_control,
        "_reconcile_environment_site",
        reject_staging,
    )

    assert run(
        pipeline_control.reconcile_repository_deployments(
            "acme",
            "site",
            "token",
        )
    ) == []


def test_background_reconciliation_uses_newest_successful_staging_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def repo_info(*_args):
        return {"default_branch": "main", "private": False}

    newer_failed = {
        "id": 82,
        "index_in_repo": 12,
        "event": "workflow_dispatch",
        "event_payload": '{"inputs":{"environment":"staging"}}',
        "prettyref": "release/v2",
        "commit_sha": "failed-sha",
    }
    older_success = {
        "id": 81,
        "index_in_repo": 11,
        "event": "workflow_dispatch",
        "event_payload": '{"inputs":{"environment":"staging"}}',
        "prettyref": "release/v1",
        "commit_sha": "successful-sha",
    }
    client = FakeAsyncClient(
        [
            response(
                200,
                {"workflow_runs": [newer_failed, older_success]},
            ),
            response(
                200,
                {
                    "jobs": [
                        {
                            "name": "Publish staging site",
                            "status": "failure",
                        }
                    ]
                },
            ),
            response(
                200,
                {
                    "jobs": [
                        {
                            "name": "Publish staging site",
                            "status": "success",
                        }
                    ]
                },
            ),
        ]
    )
    selected: list[int] = []

    async def reconcile(_owner, _repo, item, jobs, **_kwargs):
        selected.append(int(item["index_in_repo"]))
        assert pipeline_control._deployment_job_succeeded(jobs, "staging")
        return {"source_sha": item["commit_sha"]}

    monkeypatch.setattr(pipeline_control.forgejo, "get_repo_info", repo_info)
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        pipeline_control,
        "_reconcile_environment_site",
        reconcile,
    )

    result = run(
        pipeline_control.reconcile_repository_deployments(
            "acme",
            "site",
            "token",
        )
    )

    assert result == [{"source_sha": "successful-sha"}]
    assert selected == [11]
    assert [
        call[1].rsplit("/", 2)[-2]
        for call in client.calls[1:]
    ] == ["82", "81"]


def test_background_reconciliation_prunes_manual_preview_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def repo_info(*_args):
        return {"default_branch": "main", "private": False}

    manual_preview = {
        "id": 91,
        "index_in_repo": 14,
        "event": "workflow_dispatch",
        "event_payload": '{"inputs":{"environment":"preview"}}',
        "prettyref": "feature",
        "commit_sha": "preview-sha",
    }
    client = FakeAsyncClient(
        [
            response(200, {"workflow_runs": [manual_preview]}),
            response(
                200,
                {
                    "jobs": [
                        {
                            "name": "Publish preview site",
                            "status": "success",
                        }
                    ]
                },
            ),
        ]
    )
    prune_calls: list[tuple] = []
    events: list[dict] = []

    async def reconcile(_owner, _repo, _item, _jobs, **_kwargs):
        return {
            "environment": "preview",
            "key": "run-14",
            "source_sha": "preview-sha",
        }

    def prune(owner, repo, **kwargs):
        prune_calls.append((owner, repo, kwargs))
        return ["run-3"]

    monkeypatch.setattr(pipeline_control.forgejo, "get_repo_info", repo_info)
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        pipeline_control,
        "_reconcile_environment_site",
        reconcile,
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "prune_run_previews",
        prune,
    )
    monkeypatch.setattr(
        pipeline_control,
        "record_event",
        lambda *args, **kwargs: events.append({"args": args, **kwargs}),
    )

    result = run(
        pipeline_control.reconcile_repository_deployments(
            "acme",
            "site",
            "token",
        )
    )

    assert result[0]["key"] == "run-14"
    assert prune_calls == [
        (
            "acme",
            "site",
            {"protected_keys": ()},
        ),
        (
            "acme",
            "site",
            {"protected_keys": ("run-14",)},
        )
    ]
    deployment_events = [
        event
        for event in events
        if event["args"][2] != pipeline_control._RECONCILE_CURSOR_ACTION
    ]
    assert deployment_events == [
        {
            "args": (
                "acme",
                "site",
                "expire_manual_preview",
                "nyankoface-deployer",
            ),
            "environment": "preview",
            "workflow": "run-3",
        }
    ]


def test_background_reconciliation_bounds_manual_preview_backlog_before_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def repo_info(*_args):
        return {"default_branch": "main", "private": False}

    run_numbers = [4, 12, 2, 11, 8, 1, 10, 6, 9, 3, 7, 5]
    manual_runs = [
        {
            "id": 1000 + number,
            "index_in_repo": number,
            "event": "workflow_dispatch",
            "event_payload": '{"inputs":{"environment":"preview"}}',
            "prettyref": "main",
            "commit_sha": f"preview-{number}",
        }
        for number in run_numbers
    ]
    successful_job = response(
        200,
        {
            "jobs": [
                {
                    "name": "Publish preview site",
                    "status": "success",
                }
            ]
        },
    )
    client = FakeAsyncClient(
        [
            response(200, {"workflow_runs": manual_runs}),
            successful_job,
            successful_job,
            successful_job,
        ]
    )
    selected: list[int] = []

    async def reconcile(_owner, _repo, _item, _jobs, **kwargs):
        run_number = int(kwargs["run_number"])
        selected.append(run_number)
        return {
            "environment": "preview",
            "key": f"run-{run_number}",
            "source_sha": f"preview-{run_number}",
        }

    monkeypatch.setattr(pipeline_control.forgejo, "get_repo_info", repo_info)
    monkeypatch.setattr(pipeline_control.config, "PREVIEW_RUN_MAX_COUNT", 3)
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        pipeline_control,
        "_reconcile_environment_site",
        reconcile,
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "prune_run_previews",
        lambda *_args, **_kwargs: [],
    )

    result = run(
        pipeline_control.reconcile_repository_deployments(
            "acme",
            "site",
            "token",
        )
    )

    assert selected == [12, 11, 10]
    assert [deployment["key"] for deployment in result] == [
        "run-12",
        "run-11",
        "run-10",
    ]
    assert len(client.calls) == 4


def test_manual_preview_budget_skips_invalid_newer_artifacts_only_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def repo_info(*_args):
        return {"default_branch": "main", "private": False}

    manual_runs = [
        {
            "id": 1000 + number,
            "index_in_repo": number,
            "event": "workflow_dispatch",
            "event_payload": '{"inputs":{"environment":"preview"}}',
            "prettyref": "main",
            "commit_sha": f"preview-{number}",
        }
        for number in [8, 7, 6, 5]
    ]
    successful_job = response(
        200,
        {
            "jobs": [
                {
                    "name": "Publish preview site",
                    "status": "success",
                }
            ]
        },
    )
    client = FakeAsyncClient(
        [
            response(200, {"workflow_runs": manual_runs}),
            successful_job,
            successful_job,
            successful_job,
        ]
    )
    attempted: list[int] = []

    async def reconcile(_owner, _repo, _item, _jobs, **kwargs):
        run_number = int(kwargs["run_number"])
        attempted.append(run_number)
        if run_number == 8:
            return None
        return {
            "environment": "preview",
            "key": f"run-{run_number}",
            "source_sha": f"preview-{run_number}",
        }

    monkeypatch.setattr(pipeline_control.forgejo, "get_repo_info", repo_info)
    monkeypatch.setattr(pipeline_control.config, "PREVIEW_RUN_MAX_COUNT", 2)
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        pipeline_control,
        "_reconcile_environment_site",
        reconcile,
    )
    monkeypatch.setattr(
        pipeline_control.preview_artifacts,
        "prune_run_previews",
        lambda *_args, **_kwargs: [],
    )

    result = run(
        pipeline_control.reconcile_repository_deployments(
            "acme",
            "site",
            "token",
        )
    )

    assert attempted == [8, 7, 6]
    assert [deployment["key"] for deployment in result] == [
        "run-7",
        "run-6",
    ]


def test_reconcile_loop_runs_without_a_pipeline_page_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        called = asyncio.Event()

        async def reconcile(token: str) -> None:
            assert token == "service-token"
            called.set()

        monkeypatch.setattr(
            pipeline_control.config,
            "read_forgejo_token",
            lambda: "service-token",
        )
        monkeypatch.setattr(
            pipeline_control,
            "reconcile_tracked_repositories",
            reconcile,
        )
        task = asyncio.create_task(pipeline_control.reconcile_loop())
        await asyncio.wait_for(called.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    run(exercise())


def test_background_reconciliation_persists_production_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def repo_info(*_args):
        return {"default_branch": "main", "private": False}

    production_run = {
        "id": 88,
        "index_in_repo": 12,
        "event": "push",
        "prettyref": "main",
        "commit_sha": "workflow-sha",
        "status": "success",
    }
    client = FakeAsyncClient(
        [
            response(200, {"workflow_runs": [production_run]}),
            response(
                200,
                {
                    "jobs": [
                        {
                            "name": "Publish production Pages",
                            "status": "success",
                        }
                    ]
                },
            ),
        ]
    )
    reconciled: list[tuple[int, list[dict]]] = []

    async def reconcile(_owner, _repo, item, jobs, **kwargs):
        reconciled.append((int(item["index_in_repo"]), jobs))
        assert kwargs["run_number"] == 12
        return "b" * 40

    monkeypatch.setattr(pipeline_control.forgejo, "get_repo_info", repo_info)
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        pipeline_control,
        "_reconcile_production_revision",
        reconcile,
    )

    result = run(
        pipeline_control.reconcile_repository_deployments(
            "acme",
            "site",
            "token",
        )
    )

    assert result == [
        {
            "environment": "production",
            "run_number": 12,
            "source_sha": "b" * 40,
        }
    ]
    assert reconciled[0][0] == 12


def test_private_repository_reconciles_only_production_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def repo_info(*_args):
        return {"default_branch": "main", "private": True}

    production_run = {
        "id": 88,
        "index_in_repo": 12,
        "event": "push",
        "prettyref": "main",
        "commit_sha": "workflow-sha",
        "status": "success",
    }
    staging_run = {
        "id": 87,
        "index_in_repo": 11,
        "event": "workflow_dispatch",
        "event_payload": '{"inputs":{"environment":"staging"}}',
        "prettyref": "main",
        "commit_sha": "staging-sha",
        "status": "success",
    }
    preview_run = {
        "id": 86,
        "index_in_repo": 10,
        "event": "pull_request",
        "event_payload": '{"pull_request":{"number":4}}',
        "prettyref": "feature",
        "commit_sha": "preview-sha",
        "status": "success",
    }
    client = FakeAsyncClient(
        [
            response(
                200,
                {
                    "workflow_runs": [
                        preview_run,
                        staging_run,
                        production_run,
                    ]
                },
            ),
            response(
                200,
                {
                    "jobs": [
                        {
                            "name": "Publish production Pages",
                            "status": "success",
                        }
                    ]
                },
            ),
        ]
    )
    production_calls: list[int] = []

    async def reconcile_production(
        _owner,
        _repo,
        item,
        _jobs,
        **_kwargs,
    ):
        production_calls.append(int(item["index_in_repo"]))
        return "c" * 40

    async def reject_site_reconciliation(*_args, **_kwargs):
        raise AssertionError("private preview/staging must not be published")

    monkeypatch.setattr(pipeline_control.forgejo, "get_repo_info", repo_info)
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        pipeline_control,
        "_reconcile_production_revision",
        reconcile_production,
    )
    monkeypatch.setattr(
        pipeline_control,
        "_reconcile_environment_site",
        reject_site_reconciliation,
    )

    result = run(
        pipeline_control.reconcile_repository_deployments(
            "acme",
            "private-site",
            "token",
        )
    )

    assert result == [
        {
            "environment": "production",
            "run_number": 12,
            "source_sha": "c" * 40,
        }
    ]
    assert production_calls == [12]
    assert len(client.calls) == 2
    assert client.calls[1][1].endswith("/actions/runs/88/jobs")


def test_list_runs_normalizes_conclusion_actor_and_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def repo_info(*_args):
        return {"default_branch": "main"}

    client = FakeAsyncClient(
        [
            response(
                200,
                {
                    "workflow_runs": [
                        {
                            "id": 71,
                            "index_in_repo": 4,
                            "title": "NyankoFace staging · main",
                            "status": "success",
                            "event": "workflow_dispatch",
                            "prettyref": "main",
                            "commit_sha": "abcdef123456",
                            "workflow_id": "nyankoface-pipeline.yml",
                            "trigger_user": {"login": "alice"},
                        }
                    ]
                },
            ),
            response(
                200,
                [
                    {"name": "Build and test", "status": "success"},
                    {"name": "Staging artifact", "status": "success"},
                ],
            ),
        ]
    )
    monkeypatch.setattr(pipeline_control.forgejo, "get_repo_info", repo_info)
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )

    items = run(pipeline_control.list_runs("acme", "site", "token"))

    assert items[0]["status"] == "success"
    assert items[0]["environment"] == "staging"
    assert items[0]["actor"] == "alice"
    assert items[0]["job_count"] == 2
    assert items[0]["name"] == "nyankoface-pipeline.yml"
    assert items[0]["forgejo_run_id"] == 71
    assert items[0]["can_rerun"] is True
    assert items[0]["forgejo_url"].endswith("/actions/runs/4")


def test_list_runs_uses_upstream_page_and_preserves_total_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def repo_info(*_args):
        return {"default_branch": "main"}

    client = FakeAsyncClient([
        response(200, {
            "total_count": 101,
            "workflow_runs": [{
                "id": 72,
                "index_in_repo": 51,
                "title": "NyankoFace preview",
                "status": "success",
                "prettyref": "feature/page-two",
                "commit_sha": "abcdef123456",
                "workflow_id": "nyankoface-pipeline.yml",
            }],
        }),
        response(200, []),
    ])
    monkeypatch.setattr(pipeline_control.forgejo, "get_repo_info", repo_info)
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )

    result = run(pipeline_control.list_runs(
        "acme", "site", "token", page=3, limit=25, include_pagination=True,
    ))

    assert client.calls[0][2]["params"] == {"page": 3, "limit": 25}
    assert result["pagination"] == {
        "page": 3, "limit": 25, "total_count": 101, "total_pages": 5,
    }
    assert result["runs"][0]["run_number"] == 51


def test_list_runs_can_project_successful_production_without_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def repo_info(*_args):
        return {"default_branch": "main", "private": False}

    async def unexpected_reconciliation(*_args, **_kwargs):
        raise AssertionError("read-only listing must not reconcile deployments")

    client = FakeAsyncClient([
        response(200, {"workflow_runs": [{
            "id": 9200,
            "index_in_repo": 13,
            "workflow_id": "nyankoface-pipeline.yml",
            "title": "Publish production",
            "prettyref": "main",
            "status": "success",
            "event": "push",
            "updated_at": "2026-08-02T17:30:00Z",
        }]}),
        response(200, {"jobs": [{
            "id": 702,
            "name": "Publish production Pages",
            "status": "success",
        }]}),
    ])
    monkeypatch.setattr(pipeline_control.forgejo, "get_repo_info", repo_info)
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        pipeline_control,
        "_reconcile_environment_site",
        unexpected_reconciliation,
    )
    monkeypatch.setattr(
        pipeline_control,
        "_reconcile_production_revision",
        unexpected_reconciliation,
    )

    result = run(pipeline_control.list_runs(
        "acme",
        "site",
        "token",
        include_pagination=True,
        reconcile_deployments=False,
    ))

    assert result["runs"][0]["status"] == "success"
    assert result["runs"][0]["environment"] == "production"
    assert result["runs"][0]["deployment"] is None
    assert len(client.calls) == 2


def test_dispatch_syncs_settings_and_records_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def sync(*_args):
        return [{"name": "PUBLIC_URL", "kind": "variable", "scope": "build"}]

    async def targets(*_args):
        return [
            {
                "value": "node20",
                "available": True,
                "status": "online",
            }
        ]

    events: list[dict] = []
    client = FakeAsyncClient([response(204)])
    monkeypatch.setattr(pipeline_control, "sync_build_settings", sync)
    monkeypatch.setattr(pipeline_control, "list_runner_targets", targets)
    monkeypatch.setattr(
        pipeline_control,
        "record_event",
        lambda *args, **kwargs: events.append({"args": args, **kwargs}),
    )
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )

    result = run(
        pipeline_control.dispatch(
            "acme",
            "site",
            ".forgejo/workflows/nyankoface-pipeline.yml",
            "main",
            "production",
            {"approve_production": "true"},
            "token",
            "alice",
        )
    )

    assert result["status"] == "queued"
    assert result["synced_settings"][0]["name"] == "PUBLIC_URL"
    assert client.calls[0][2]["json"] == {
        "ref": "main",
        "inputs": {
            "approve_production": "true",
            "runner": "node20",
            "environment": "production",
        },
    }
    assert events[0]["args"][2] == "dispatch"
    assert events[0]["args"][3] == "alice"


def test_dispatch_settings_read_failure_is_retry_safe_before_any_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def targets(*_args):
        return [{"value": "node20", "available": True, "status": "online"}]

    sync = AsyncMock()
    monkeypatch.setattr(pipeline_control, "list_runner_targets", targets)
    monkeypatch.setattr(
        pipeline_control.space_environment,
        "build_settings",
        lambda *_: (_ for _ in ()).throw(RuntimeError("decrypt failed")),
    )
    monkeypatch.setattr(pipeline_control, "sync_build_setting", sync)

    with pytest.raises(pipeline_control.PipelineError) as exc:
        run(pipeline_control.dispatch(
            "acme", "site", "publish.yml", "main", "staging", {}, "token", "alice",
        ))

    assert exc.value.retry_safe is True
    assert exc.value.code == "pipeline_error"
    sync.assert_not_awaited()


def test_settings_failure_after_first_sync_remains_outcome_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline_control.space_environment,
        "build_settings",
        lambda *_: {
            "FIRST": {"kind": "variable", "scope": "build", "value": "1"},
            "SECOND": {"kind": "variable", "scope": "build", "value": "2"},
        },
    )
    sync = AsyncMock(side_effect=[
        {"name": "FIRST", "kind": "variable", "scope": "build"},
        pipeline_control.PipelineError("Second setting outcome is unknown."),
    ])
    monkeypatch.setattr(pipeline_control, "sync_build_setting", sync)

    with pytest.raises(pipeline_control.PipelineError) as exc:
        run(pipeline_control.sync_build_settings("acme", "site", "token"))

    assert exc.value.retry_safe is False
    assert sync.await_count == 2


@pytest.mark.parametrize(
    ("settings", "responses", "retry_safe"),
    [
        (
            {"ONLY": {"kind": "variable", "scope": "build", "value": "1"}},
            [httpx.ReadTimeout("lookup timeout")],
            True,
        ),
        (
            {
                "FIRST": {"kind": "secret", "scope": "build", "value": "1"},
                "SECOND": {"kind": "variable", "scope": "build", "value": "2"},
            },
            [response(204), httpx.ReadTimeout("lookup timeout")],
            False,
        ),
    ],
)
def test_variable_lookup_timeout_respects_prior_write_phase(
    monkeypatch: pytest.MonkeyPatch, settings, responses, retry_safe,
) -> None:
    client = FakeAsyncClient(responses)
    monkeypatch.setattr(
        pipeline_control.space_environment, "build_settings", lambda *_: settings,
    )
    monkeypatch.setattr(
        pipeline_control.httpx, "AsyncClient", lambda **_kwargs: client,
    )

    with pytest.raises(pipeline_control.PipelineError) as exc:
        run(pipeline_control.sync_build_settings("acme", "site", "token"))

    assert exc.value.retry_safe is retry_safe


@pytest.mark.parametrize(
    ("settings", "responses", "retry_safe"),
    [
        (
            {"ONLY": {"kind": "secret", "scope": "build", "value": "1"}},
            [response(409)],
            True,
        ),
        (
            {"ONLY": {"kind": "variable", "scope": "build", "value": "1"}},
            [response(404), response(422)],
            True,
        ),
        (
            {
                "FIRST": {"kind": "secret", "scope": "build", "value": "1"},
                "SECOND": {"kind": "variable", "scope": "build", "value": "2"},
            },
            [response(204), response(404), response(409)],
            False,
        ),
        (
            {"ONLY": {"kind": "secret", "scope": "build", "value": "1"}},
            [response(503)],
            False,
        ),
    ],
)
def test_setting_write_response_respects_prior_write_phase(
    monkeypatch: pytest.MonkeyPatch, settings, responses, retry_safe,
) -> None:
    client = FakeAsyncClient(responses)
    monkeypatch.setattr(
        pipeline_control.space_environment, "build_settings", lambda *_: settings,
    )
    monkeypatch.setattr(
        pipeline_control.httpx, "AsyncClient", lambda **_kwargs: client,
    )

    with pytest.raises(pipeline_control.PipelineError) as exc:
        run(pipeline_control.sync_build_settings("acme", "site", "token"))

    assert exc.value.retry_safe is retry_safe


@pytest.mark.parametrize("operation", ["secret_put", "variable_put", "variable_post", "delete"])
def test_environment_native_timeout_is_always_unknown_outcome(
    monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    replies = [httpx.ReadTimeout("outcome unknown")]
    if operation == "variable_put":
        replies = [response(200), *replies]
    elif operation == "variable_post":
        replies = [response(404), *replies]
    client = FakeAsyncClient(replies)
    monkeypatch.setattr(pipeline_control.httpx, "AsyncClient", lambda **_kwargs: client)
    with pytest.raises(pipeline_control.PipelineError) as captured:
        setting = {
            "name": "TOKEN", "kind": "secret" if operation == "secret_put" else "variable",
            "scope": "build", "value": "secret" if operation == "secret_put" else "value",
        }
        if operation == "secret_put":
            run(pipeline_control.sync_build_setting("acme", "site", setting, "token"))
        elif operation == "delete":
            run(pipeline_control.remove_build_setting("acme", "site", "TOKEN", "secret", "token"))
        else:
            run(pipeline_control.sync_build_setting("acme", "site", setting, "token"))
    assert captured.value.retry_safe is False
@pytest.mark.parametrize(("status", "retry_safe"), [
    (503, False), (400, True), (None, False),
])
def test_dispatch_classifies_post_request_outcome(
    monkeypatch: pytest.MonkeyPatch, status: int, retry_safe: bool,
) -> None:
    async def sync(*_args):
        return []

    async def targets(*_args):
        return [{"value": "node20", "available": True, "status": "online"}]

    monkeypatch.setattr(pipeline_control, "sync_build_settings", sync)
    monkeypatch.setattr(pipeline_control, "list_runner_targets", targets)
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: FakeAsyncClient([
            text_response(status, "upstream failed") if status else httpx.ReadTimeout("timeout")
        ]),
    )

    with pytest.raises(pipeline_control.PipelineError) as exc_info:
        run(pipeline_control.dispatch(
            "acme", "site", "publish.yml", "main", "staging", {}, "token", "alice",
        ))

    assert exc_info.value.status_code == 502
    assert exc_info.value.retry_safe is retry_safe


def test_dispatch_rejection_after_setting_sync_is_not_retry_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline_control,
        "sync_build_settings",
        AsyncMock(return_value=[{"name": "PUBLIC_URL", "kind": "variable"}]),
    )
    monkeypatch.setattr(
        pipeline_control,
        "list_runner_targets",
        AsyncMock(return_value=[{
            "value": "node20", "available": True, "status": "online",
        }]),
    )
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: FakeAsyncClient([text_response(400, "invalid input")]),
    )

    with pytest.raises(pipeline_control.PipelineError) as exc_info:
        run(pipeline_control.dispatch(
            "acme", "site", "publish.yml", "main", "staging", {}, "token", "alice",
        ))

    assert exc_info.value.status_code == 502
    assert exc_info.value.retry_safe is False


@pytest.mark.parametrize("responses", [
    [text_response(503, "failed")],
    [response(200, [])],
    [response(200, {"workflow_runs": [{"index_in_repo": 9, "id": 90}]}),
     text_response(503, "failed")],
    [response(200, {"workflow_runs": [{"index_in_repo": 9, "id": 90}]}),
     response(200, "invalid")],
])
def test_run_lookup_5xx_is_retry_safe_before_action(monkeypatch, responses) -> None:
    monkeypatch.setattr(
        pipeline_control.forgejo, "get_repo_info",
        AsyncMock(return_value={"default_branch": "main"}),
    )
    monkeypatch.setattr(
        pipeline_control.httpx, "AsyncClient",
        lambda **_: FakeAsyncClient(responses),
    )
    with pytest.raises(pipeline_control.PipelineError) as exc:
        run(pipeline_control._find_run("acme", "site", 9, "token"))
    assert exc.value.retry_safe is True


def test_runner_targets_report_online_offline_and_unregistered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeAsyncClient(
        [
            response(
                200,
                [
                    {
                        "uuid": "cpu-online",
                        "status": "idle",
                        "labels": ["node20"],
                    },
                    {
                        "uuid": "gpu-offline",
                        "status": "offline",
                        "labels": ["gpu"],
                    },
                ],
            ),
            response(200, []),
        ]
    )
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )

    targets = run(
        pipeline_control.list_runner_targets("acme", "site", "token")
    )

    assert targets == [
        {
            "value": "node20",
            "label": "CPU · Node.js 20",
            "available": True,
            "status": "online",
            "online": 1,
            "registered": 1,
        },
        {
            "value": "gpu",
            "label": "GPU · CUDA",
            "available": False,
            "status": "offline",
            "online": 0,
            "registered": 1,
        },
    ]


@pytest.mark.parametrize("runner", [
    {"id": 1, "labels": 1},
    {"id": 1, "labels": ["node20", 2]},
    "not-an-object",
])
def test_runner_targets_reject_malformed_labels(monkeypatch, runner) -> None:
    client = FakeAsyncClient([response(200, [runner]), response(200, [])])
    monkeypatch.setattr(
        pipeline_control.httpx, "AsyncClient", lambda **_kwargs: client,
    )
    with pytest.raises(pipeline_control.PipelineError) as exc:
        run(pipeline_control.list_runner_targets("acme", "site", "token"))
    assert exc.value.retry_safe is True


@pytest.mark.parametrize("reply", [httpx.ReadTimeout("timeout"), response(200, {}), response(503, {})])
def test_dispatch_runner_lookup_failure_is_retry_safe(monkeypatch, reply) -> None:
    monkeypatch.setattr(pipeline_control.httpx, "AsyncClient", lambda **_: FakeAsyncClient([reply]))
    with pytest.raises(pipeline_control.PipelineError) as exc:
        run(pipeline_control.dispatch(
            "acme", "site", "publish.yml", "main", "staging", {}, "token", "alice",
        ))
    assert exc.value.retry_safe is True


def test_rollback_repository_lookup_failure_is_retry_safe(monkeypatch) -> None:
    source = {"status": "success", "environment": "production"}
    monkeypatch.setattr(pipeline_control, "_find_run", AsyncMock(return_value=source))
    monkeypatch.setattr(pipeline_control.forgejo, "get_repo_info", AsyncMock(
        side_effect=httpx.ReadTimeout("timeout")))
    with pytest.raises(pipeline_control.PipelineError) as exc:
        run(pipeline_control.run_action("acme", "site", 7, "rollback", "token", "alice"))
    assert exc.value.retry_safe is True


def test_rollback_rejects_non_object_repository_payload_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = {"status": "success", "environment": "production"}
    dispatch = AsyncMock()
    monkeypatch.setattr(pipeline_control, "_find_run", AsyncMock(return_value=source))
    monkeypatch.setattr(
        pipeline_control.forgejo, "get_repo_info", AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(pipeline_control, "dispatch", dispatch)

    with pytest.raises(pipeline_control.PipelineError) as exc:
        run(pipeline_control.run_action(
            "acme", "site", 7, "rollback", "token", "alice",
        ))

    assert exc.value.retry_safe is True
    dispatch.assert_not_awaited()


def test_dispatch_rejects_a_known_unavailable_runner_before_secret_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def targets(*_args):
        return [
            {
                "value": "gpu",
                "available": False,
                "status": "unregistered",
            }
        ]

    async def unexpected_sync(*_args):
        raise AssertionError("settings must not sync for an unavailable runner")

    monkeypatch.setattr(pipeline_control, "list_runner_targets", targets)
    monkeypatch.setattr(
        pipeline_control,
        "sync_build_settings",
        unexpected_sync,
    )

    with pytest.raises(pipeline_control.PipelineError) as exc_info:
        run(
            pipeline_control.dispatch(
                "acme",
                "site",
                "nyankoface-pipeline.yml",
                "main",
                "staging",
                {"runner": "gpu"},
                "token",
                "alice",
            )
        )

    assert exc_info.value.code == "runner_unavailable"
    assert exc_info.value.status_code == 409
    assert exc_info.value.retry_safe is True


@pytest.mark.parametrize(("status", "retry_safe"), [(204, None), (409, True), (None, False)])
def test_cancel_uses_forgejo_v16_api_and_audit(
    monkeypatch: pytest.MonkeyPatch, status: int | None, retry_safe: bool | None,
) -> None:
    client = FakeAsyncClient([
        response(status) if status else httpx.ReadTimeout("timeout")
    ])
    events: list[dict] = []

    async def find_run(*_args):
        return {
            "run_number": 9,
            "forgejo_run_id": 71,
            "status": "running",
            "environment": "staging",
        }

    monkeypatch.setattr(pipeline_control, "_find_run", find_run)
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        pipeline_control,
        "record_event",
        lambda *args, **kwargs: events.append({"args": args, **kwargs}),
    )

    action = pipeline_control.run_action("acme", "site", 9, "cancel", "token", "alice")
    if retry_safe is not None:
        with pytest.raises(pipeline_control.PipelineError) as exc:
            run(action)
        assert exc.value.retry_safe is retry_safe
        return
    result = run(action)

    assert result == {"status": "accepted", "action": "cancel", "run_number": 9}
    assert client.calls[0][1].endswith("/actions/runs/71/cancel")
    assert events[0]["args"][2] == "cancel"


def test_rerun_uses_native_forgejo_run_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def find_run(*_args):
        return {"run_number": 9, "can_rerun": True}

    events: list[dict] = []

    monkeypatch.setattr(pipeline_control, "_find_run", find_run)
    monkeypatch.setattr(
        pipeline_control,
        "record_event",
        lambda *args, **kwargs: events.append({"args": args, **kwargs}),
    )

    result = run(
        pipeline_control.run_action(
            "acme", "site", 9, "rerun", "token", "alice"
        )
    )

    assert result == {
        "status": "native_action_required",
        "action": "rerun",
        "run_number": 9,
        "native_action_url": "/git/acme/site/actions/runs/9/rerun",
        "method": "POST",
    }
    assert events[0]["args"][2] == "native_rerun_requested"


def test_find_run_uses_forgejo_run_number_filter_for_retained_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def repo_info(*_args):
        return {"default_branch": "main"}

    target = {
        "id": 9001,
        "index_in_repo": 49,
        "workflow_id": "nyankoface-pipeline.yml",
        "event": "workflow_dispatch",
        "event_payload": (
            '{"inputs":{"environment":"production",'
            '"revision":"release-v1"}}'
        ),
        "prettyref": "main",
        "commit_sha": "event-sha",
        "status": "success",
        "updated": "2026-08-02T17:14:00Z",
        "trigger_user": {"login": "alice"},
    }
    client = FakeAsyncClient(
        [
            response(200, {"workflow_runs": [target]}),
            response(
                200,
                {
                    "jobs": [
                        {
                            "name": "Publish production Pages",
                            "status": "success",
                        }
                    ]
                },
            ),
        ]
    )

    async def revision(*_args, **_kwargs):
        return "d" * 40

    monkeypatch.setattr(pipeline_control.forgejo, "get_repo_info", repo_info)
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        pipeline_control,
        "_reconcile_production_revision",
        revision,
    )

    result = run(
        pipeline_control._find_run(
            "acme",
            "site",
            49,
            "token",
        )
    )

    assert result["run_number"] == 49
    assert result["forgejo_run_id"] == 9001
    assert result["environment"] == "production"
    assert result["deployed_revision"] == "d" * 40
    assert result["updated_at"] == "2026-08-02T17:14:00Z"
    assert client.calls[0][2]["params"] == {
        "run_number": 49,
        "limit": 1,
    }
    assert client.calls[1][1].endswith("/actions/runs/9001/jobs")


def test_find_run_rejects_a_server_response_for_another_run_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def repo_info(*_args):
        return {"default_branch": "main"}

    client = FakeAsyncClient(
        [
            response(
                200,
                {
                    "workflow_runs": [
                        {
                            "id": 9002,
                            "index_in_repo": 50,
                            "event": "push",
                        }
                    ]
                },
            ),
        ]
    )
    monkeypatch.setattr(pipeline_control.forgejo, "get_repo_info", repo_info)
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )

    with pytest.raises(
        pipeline_control.PipelineError,
        match="not found",
    ):
        run(
            pipeline_control._find_run(
                "acme",
                "site",
                1,
                "token",
            )
        )

    assert len(client.calls) == 1
    assert client.calls[0][2]["params"] == {
        "run_number": 1,
        "limit": 1,
    }


def test_run_metadata_reads_status_without_fetching_job_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def repo_info(*_args):
        return {"default_branch": "main"}

    client = FakeAsyncClient([
        response(200, {"workflow_runs": [{
            "id": 9100,
            "index_in_repo": 12,
            "workflow_id": "nyankoface-pipeline.yml",
            "title": "Metadata only",
            "prettyref": "main",
            "status": "queued",
            "updated_at": "2026-08-02T17:20:00Z",
        }]}),
        response(200, {"jobs": [{
            "id": 701,
            "name": "Build",
            "status": "queued",
            "started": None,
            "stopped": None,
        }]}),
    ])
    monkeypatch.setattr(pipeline_control.forgejo, "get_repo_info", repo_info)
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )

    result = run(pipeline_control.run_metadata("acme", "site", 12, "token"))

    assert result["updated_at"] == "2026-08-02T17:20:00Z"
    assert result["state"]["run"]["status"] == "waiting"
    assert result["jobs"] == [{
        "id": 0,
        "forgejo_job_id": 701,
        "name": "Build",
        "status": "queued",
        "conclusion": None,
        "started": None,
        "stopped": None,
    }]
    assert len(client.calls) == 2
    assert client.calls[1][1].endswith("/actions/runs/9100/jobs")
    assert all("/logs" not in call[1] for call in client.calls)


def test_run_metadata_reads_successful_production_without_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def repo_info(*_args):
        return {"default_branch": "main", "private": False}

    async def unexpected_reconciliation(*_args, **_kwargs):
        raise AssertionError("metadata read must not reconcile production")

    client = FakeAsyncClient([
        response(200, {"workflow_runs": [{
            "id": 9300,
            "index_in_repo": 14,
            "workflow_id": "nyankoface-pipeline.yml",
            "title": "Publish production",
            "prettyref": "main",
            "status": "success",
            "event": "push",
            "updated_at": "2026-08-02T17:35:00Z",
        }]}),
        response(200, {"jobs": [{
            "id": 703,
            "name": "Publish production Pages",
            "status": "success",
        }]}),
    ])
    monkeypatch.setattr(pipeline_control.forgejo, "get_repo_info", repo_info)
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        pipeline_control,
        "_reconcile_production_revision",
        unexpected_reconciliation,
    )

    result = run(pipeline_control.run_metadata("acme", "site", 14, "token"))

    assert result["state"]["run"]["status"] == "success"
    assert result["jobs"][0]["name"] == "Publish production Pages"
    assert len(client.calls) == 2
    assert all("/logs" not in call[1] for call in client.calls)


def test_approve_returns_forgejo_pr_trust_review_without_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def find_run(*_args):
        return {
            "run_number": 9,
            "can_approve": True,
            "approval_url": "/git/acme/site/pulls/4#pull-request-trust-panel",
        }

    events: list[dict] = []
    monkeypatch.setattr(pipeline_control, "_find_run", find_run)
    monkeypatch.setattr(
        pipeline_control,
        "record_event",
        lambda *args, **kwargs: events.append({"args": args, **kwargs}),
    )

    result = run(
        pipeline_control.run_action(
            "acme", "site", 9, "approve", "token", "alice"
        )
    )

    assert result["status"] == "review_required"
    assert result["approval_url"].endswith("#pull-request-trust-panel")
    assert events[0]["args"][2] == "approval_review_opened"


def test_rollback_dispatches_successful_production_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def find_run(*_args):
        return {
            "run_number": 9,
            "status": "success",
            "environment": "production",
            "head_sha": "abc123",
            "event_payload": '{"inputs":{"revision":"release-v2"}}',
            "name": "nyankoface-pipeline.yml",
        }

    async def repo_info(*_args):
        return {"default_branch": "main"}

    dispatched: list[dict] = []

    async def dispatch(*args, **kwargs):
        dispatched.append({"args": args, "kwargs": kwargs})
        return {"status": "queued"}

    monkeypatch.setattr(pipeline_control, "_find_run", find_run)
    monkeypatch.setattr(pipeline_control.forgejo, "get_repo_info", repo_info)
    monkeypatch.setattr(pipeline_control, "dispatch", dispatch)

    result = run(
        pipeline_control.run_action(
            "acme",
            "site",
            9,
            "rollback",
            "token",
            "alice",
        )
    )

    assert result["action"] == "rollback"
    assert dispatched[0]["args"][4] == "production"
    assert dispatched[0]["args"][5]["revision"] == "release-v2"
    assert dispatched[0]["args"][5]["approve_production"] == "true"
    assert dispatched[0]["kwargs"]["audit_action"] == "rollback"


def test_failed_job_rerun_uses_native_forgejo_job_endpoint_including_job_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def find_run(*_args):
        return {
            "run_number": 9,
            "status": "failure",
            "environment": "staging",
            "can_rerun": True,
        }

    async def detail(*_args):
        return {
            "jobs": [
                {"id": 0, "name": "Build and test", "status": "failure"},
                {"id": 1, "name": "Staging artifact", "status": "failure"},
            ]
        }

    events: list[dict] = []

    monkeypatch.setattr(pipeline_control, "_find_run", find_run)
    monkeypatch.setattr(pipeline_control, "run_detail", detail)
    monkeypatch.setattr(
        pipeline_control,
        "record_event",
        lambda *args, **kwargs: events.append({"args": args, **kwargs}),
    )

    result = run(
        pipeline_control.rerun_job(
            "acme",
            "site",
            9,
            0,
            "token",
            "alice",
        )
    )

    assert result["action"] == "rerun_job"
    assert result["job_id"] == 0
    assert result["status"] == "native_action_required"
    assert result["native_action_url"] == (
        "/git/acme/site/actions/runs/9/jobs/0/rerun"
    )
    assert result["method"] == "POST"
    assert events[0]["args"][2] == "native_rerun_job_requested"


def test_run_detail_uses_forgejo_job_positions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs = [
        {"id": 501, "name": "Build", "status": "success"},
        {"id": 502, "name": "Deploy", "status": "failure"},
    ]
    client = FakeAsyncClient(
        [
            response(200, jobs),
            text_response(
                200,
                "2026-07-30T10:00:00Z nyankoface-runner(version:v8.0.1) "
                "received task 1 of job build\n"
                "2026-07-30T10:00:01Z ⭐ Run Build\n"
                "2026-07-30T10:00:04Z ✅ Success - Build\n",
            ),
            text_response(
                200,
                "2026-07-30T10:00:02Z ⭐ Run Deploy\n"
                "2026-07-30T10:00:03Z ❌ Failure - Deploy\n",
            ),
        ]
    )

    async def find_run(*_args):
        return {
            "run_number": 7,
            "forgejo_run_id": 99,
            "display_title": "Test pipeline",
            "status": "failure",
            "can_cancel": False,
            "can_approve": False,
            "can_rerun": True,
            "updated_at": "2026-07-30T10:00:04Z",
        }

    redaction_loads: list[tuple] = []

    def build_settings(*args):
        redaction_loads.append(args)
        return {
            "TOKEN": {
                "kind": "secret",
                "scope": "build",
                "value": "runner-secret",
            }
        }

    monkeypatch.setattr(pipeline_control, "_find_run", find_run)
    monkeypatch.setattr(space_environment, "build_settings", build_settings)
    monkeypatch.setattr(
        pipeline_control.httpx,
        "AsyncClient",
        lambda **_kwargs: client,
    )

    detail = run(pipeline_control.run_detail("acme", "site", 7, "token"))

    assert [job["id"] for job in detail["jobs"]] == [0, 1]
    assert [job["forgejo_job_id"] for job in detail["jobs"]] == [501, 502]
    assert client.calls[0][1].endswith("/actions/runs/99/jobs")
    assert client.calls[1][1].endswith("/actions/jobs/501/logs")
    assert client.calls[2][1].endswith("/actions/jobs/502/logs")
    assert detail["jobs"][0]["steps"][0]["status"] == "success"
    assert detail["jobs"][1]["steps"][0]["status"] == "failure"
    assert detail["jobs"][0]["steps"][0]["duration"] == "3s"
    assert detail["jobs"][0]["duration"] == "4s"
    assert detail["jobs"][0]["runner"] == "nyankoface-runner · v8.0.1"
    assert detail["state"]["run"]["canRerun"] is True
    assert detail["state"]["run"]["forgejoRunId"] == 99
    assert detail["updated_at"] == "2026-07-30T10:00:04Z"
    assert redaction_loads == [("acme", "site")]


def test_job_log_stream_keeps_bounded_tail_and_full_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ChunkStream(httpx.AsyncByteStream):
        def __init__(self, content: bytes) -> None:
            self.content = content
            self.closed = False

        async def __aiter__(self):
            for byte in self.content:
                yield bytes([byte])

        async def aclose(self) -> None:
            self.closed = True

    body = (
        "2026-07-30T10:00:00Z nyankoface-runner(version:v8.0.1) "
        "received task 1 of job build\n"
        "2026-07-30T10:00:01Z ⭐ Run 日本語 build\n"
        + "".join(
            f"2026-07-30T10:00:02Z noise {index}\n"
            for index in range(2_500)
        )
        + "2026-07-30T10:00:04Z ✅ Success - 日本語 build\n"
    ).encode("utf-8")
    stream = ChunkStream(body)
    response = httpx.Response(200, stream=stream)
    response.request = httpx.Request("GET", "https://forgejo.test/logs")
    monkeypatch.setattr(pipeline_control, "JOB_LOG_CHUNK_BYTES", 1)

    summary = run(
        pipeline_control._scan_job_log(
            response,
            (),
            "success",
        )
    )
    run(response.aclose())

    assert len(summary["logs"]) == pipeline_control.MAX_JOB_LOG_LINES
    assert summary["logs"][0]["index"] == 503
    assert summary["logs"][-1]["index"] == 2_502
    assert summary["runner"] == "nyankoface-runner · v8.0.1"
    assert summary["duration"] == "4s"
    assert summary["steps"] == [
        {
            "summary": "日本語 build",
            "status": "success",
            "duration": "3s",
        }
    ]
    assert stream.closed is True


def test_job_log_stream_truncates_unbounded_lines_without_losing_next_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ChunkStream(httpx.AsyncByteStream):
        def __init__(self, content: bytes) -> None:
            self.content = content

        async def __aiter__(self):
            for offset in range(0, len(self.content), 7):
                yield self.content[offset : offset + 7]

        async def aclose(self) -> None:
            return None

    body = (
        b"2026-07-30T10:00:00Z "
        + (b"x" * 200)
        + b"\r\n2026-07-30T10:00:03Z next line without newline"
    )
    response = httpx.Response(200, stream=ChunkStream(body))
    response.request = httpx.Request("GET", "https://forgejo.test/logs")
    monkeypatch.setattr(pipeline_control, "MAX_JOB_LOG_LINE_BYTES", 48)
    monkeypatch.setattr(pipeline_control, "JOB_LOG_CHUNK_BYTES", 7)

    summary = run(
        pipeline_control._scan_job_log(
            response,
            (),
            "success",
        )
    )

    assert len(summary["logs"]) == 2
    assert summary["logs"][0]["message"].endswith("… [line truncated]")
    assert summary["logs"][1]["message"] == "next line without newline"
    assert summary["duration"] == "3s"


def test_logs_strip_ansi_and_redact_build_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        space_environment,
        "build_settings",
        lambda *_args: {
            "TOKEN": {
                "kind": "secret",
                "scope": "build",
                "value": "super-secret-value",
            }
        },
    )

    values = pipeline_control._log_redaction_values("acme", "site")
    redacted = pipeline_control._redact_log_text(
        "\x1b[31mTOKEN=super-secret-value\x1b[0m",
        values,
    )

    assert "\x1b" not in redacted
    assert "super-secret-value" not in redacted
    assert "TOKEN=***" in redacted


def test_steps_inherit_terminal_job_status_when_runner_omits_footer() -> None:
    lines = [
        {
            "timestamp": "2026-07-30T10:00:00Z",
            "message": "⭐ Run Main Check out repository",
        },
        {
            "timestamp": "2026-07-30T10:00:05Z",
            "message": "runner footer without an action result",
        },
    ]

    assert pipeline_control._steps_from_log(lines, "success") == [
        {
            "summary": "Main Check out repository",
            "status": "success",
            "duration": "5s",
        }
    ]


def test_log_metadata_handles_long_duration_and_missing_values() -> None:
    lines = [
        {
            "timestamp": "2026-07-30T10:00:00.0000000Z",
            "message": "runner-a(version:v8.0.1) received task 1 of job build",
        },
        {
            "timestamp": "2026-07-30T11:02:03.0000000Z",
            "message": "job complete",
        },
    ]

    assert pipeline_control._duration_from_logs(lines) == "1h 02m"
    assert pipeline_control._runner_from_logs(lines) == "runner-a · v8.0.1"
    assert pipeline_control._duration_from_logs([{"message": "no timestamp"}]) == ""
    assert pipeline_control._runner_from_logs([{"message": "no runner"}]) == ""


def test_scope_validation_and_runtime_build_separation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert space_environment._validate_scope("runtime") == "runtime"
    assert space_environment._validate_scope("build") == "build"
    assert space_environment._validate_scope("both") == "both"
    with pytest.raises(ValueError):
        space_environment._validate_scope("production")

    calls: list[tuple[str, ...]] = []

    def values(_owner, _repo, scopes):
        calls.append(tuple(scopes))
        return {
            "TOKEN": {
                "kind": "secret",
                "scope": scopes[0],
                "value": "value",
            }
        }

    monkeypatch.setattr(space_environment, "_values_for_scopes", values)
    assert space_environment.runtime_values("acme", "site") == {"TOKEN": "value"}
    assert space_environment.build_settings("acme", "site")["TOKEN"]["value"] == "value"
    assert calls == [("runtime", "both"), ("build", "both")]


def test_disabling_build_setting_removes_native_forgejo_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    removed: list[tuple] = []
    synced: list[tuple] = []

    async def remove(*args):
        removed.append(args)

    async def sync(*args):
        synced.append(args)
        return []

    monkeypatch.setattr(pipeline_control, "remove_build_setting", remove)
    monkeypatch.setattr(pipeline_control, "sync_build_setting", sync)

    run(
        main.reconcile_build_setting(
            "acme",
            "site",
            "token",
            {
                "name": "DEPLOY_TOKEN",
                "kind": "secret",
                "scope": "build",
                "enabled": True,
            },
            {
                "name": "DEPLOY_TOKEN",
                "kind": "secret",
                "scope": "build",
                "enabled": False,
            },
        )
    )

    assert removed == [
        ("acme", "site", "DEPLOY_TOKEN", "secret", "token")
    ]
    assert synced == []


def test_kind_change_stages_new_native_value_before_removing_old_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    async def sync(*_args):
        events.append("sync-new")
        return []

    async def remove(*_args):
        events.append("remove-old")

    monkeypatch.setattr(pipeline_control, "sync_build_setting", sync)
    monkeypatch.setattr(pipeline_control, "remove_build_setting", remove)

    run(
        main.reconcile_build_setting(
            "acme",
            "site",
            "token",
            {
                "name": "DEPLOY_TOKEN",
                "kind": "secret",
                "scope": "build",
                "enabled": True,
            },
            {
                "name": "DEPLOY_TOKEN",
                "kind": "variable",
                "scope": "build",
                "enabled": True,
            },
        )
    )

    assert events == ["sync-new", "remove-old"]


def test_kind_change_keeps_old_native_value_when_new_sync_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    removed: list[tuple] = []

    async def sync(*_args):
        raise pipeline_control.PipelineError("new native sync failed")

    async def remove(*args):
        removed.append(args)

    monkeypatch.setattr(pipeline_control, "sync_build_setting", sync)
    monkeypatch.setattr(pipeline_control, "remove_build_setting", remove)

    with pytest.raises(
        pipeline_control.PipelineError,
        match="new native sync failed",
    ):
        run(
            main.reconcile_build_setting(
                "acme",
                "site",
                "token",
                {
                    "name": "DEPLOY_TOKEN",
                    "kind": "secret",
                    "scope": "build",
                    "enabled": True,
                },
                {
                    "name": "DEPLOY_TOKEN",
                    "kind": "variable",
                    "scope": "build",
                    "enabled": True,
                },
            )
        )

    assert removed == []


def test_kind_change_removes_staged_value_when_old_removal_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    removed: list[tuple] = []

    async def sync(*_args):
        return []

    async def remove(*args):
        removed.append(args)
        if args[3] == "secret":
            raise pipeline_control.PipelineError(
                "old native removal failed", retry_safe=True,
            )

    monkeypatch.setattr(pipeline_control, "sync_build_setting", sync)
    monkeypatch.setattr(pipeline_control, "remove_build_setting", remove)

    with pytest.raises(
        pipeline_control.PipelineError,
        match="old native removal failed",
    ):
        run(
            main.reconcile_build_setting(
                "acme",
                "site",
                "token",
                {
                    "name": "DEPLOY_TOKEN",
                    "kind": "secret",
                    "scope": "build",
                    "enabled": True,
                },
                {
                    "name": "DEPLOY_TOKEN",
                    "kind": "variable",
                    "scope": "build",
                    "enabled": True,
                },
            )
        )

    assert removed == [
        ("acme", "site", "DEPLOY_TOKEN", "secret", "token"),
        ("acme", "site", "DEPLOY_TOKEN", "variable", "token"),
    ]


def test_kind_change_preserves_staged_value_when_old_removal_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    removed: list[tuple] = []
    async def sync(*_args): return []
    async def remove(*args):
        removed.append(args); raise pipeline_control.PipelineError("old native removal outcome unknown", retry_safe=False)
    monkeypatch.setattr(pipeline_control, "sync_build_setting", sync)
    monkeypatch.setattr(pipeline_control, "remove_build_setting", remove)
    with pytest.raises(pipeline_control.PipelineError) as captured:
        run(main.reconcile_build_setting("acme", "site", "token",
            {"name": "DEPLOY_TOKEN", "kind": "secret", "scope": "build", "enabled": True},
            {"name": "DEPLOY_TOKEN", "kind": "variable", "scope": "build", "enabled": True}))
    assert captured.value.retry_safe is False and removed == [("acme", "site", "DEPLOY_TOKEN", "secret", "token")]
def test_delete_keeps_local_secret_until_native_removal_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = {
        "name": "DEPLOY_TOKEN",
        "kind": "secret",
        "scope": "build",
        "enabled": True,
    }
    deleted: list[tuple] = []

    monkeypatch.setattr(
        space_environment,
        "get_setting_metadata",
        lambda *_args: previous,
    )
    monkeypatch.setattr(
        space_environment,
        "delete",
        lambda *args: deleted.append(args) or True,
    )

    async def fail_reconcile(*_args):
        raise pipeline_control.PipelineError("Forgejo unavailable")

    monkeypatch.setattr(main, "reconcile_build_setting", fail_reconcile)

    with pytest.raises(pipeline_control.PipelineError):
        run(
            main.delete_space_environment_setting(
                "acme",
                "site",
                "DEPLOY_TOKEN",
                "alice",
                "token",
            )
        )

    assert deleted == []


def test_delete_removes_native_setting_before_local_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    previous = {
        "name": "PUBLIC_URL",
        "kind": "variable",
        "scope": "both",
        "enabled": True,
    }
    monkeypatch.setattr(
        space_environment,
        "get_setting_metadata",
        lambda *_args: previous,
    )

    async def reconcile(*_args):
        events.append("native")

    def delete(*_args):
        events.append("local")
        return True

    monkeypatch.setattr(main, "reconcile_build_setting", reconcile)
    monkeypatch.setattr(space_environment, "delete", delete)

    assert run(
        main.delete_space_environment_setting(
            "acme", "site", "PUBLIC_URL", "alice", "token"
        )
    )
    assert events == ["native", "local"]


def test_delete_repairs_native_projection_when_row_changes_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = {"name": "PUBLIC_URL", "kind": "variable", "scope": "both", "enabled": True,
                "generation": 1, "updated_at": "2026-08-02T00:00:00Z"}
    current = {**previous, "value": "https://new.example", "generation": 2}
    reconciliations: list[tuple[dict | None, dict | None]] = []; delete_args: list[tuple] = []
    monkeypatch.setattr(space_environment, "get_setting_metadata", lambda *_: previous)
    monkeypatch.setattr(space_environment, "get_setting", lambda *_: current)
    monkeypatch.setattr(space_environment, "delete", lambda *args: delete_args.append(args) or False)

    async def reconcile(_owner, _repo, _token, old, new): reconciliations.append((old, new))
    monkeypatch.setattr(main, "reconcile_build_setting", reconcile)

    with pytest.raises(ValueError, match="changed during deletion"):
        run(main.delete_space_environment_setting("acme", "site", "PUBLIC_URL", "alice", "token", "variable"))
    assert delete_args[0][-2:] == ("variable", 1) and reconciliations == [(previous, None), (None, current)]


def test_upsert_restores_local_secret_when_native_sync_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = {
        "name": "DEPLOY_TOKEN",
        "kind": "secret",
        "scope": "build",
        "enabled": True,
        "value": "old-secret",
        "generation": 1,
        "updated_at": "2026-08-02T00:00:01Z",
    }
    writes: list[tuple] = []
    restores: list[tuple] = []

    monkeypatch.setattr(
        space_environment,
        "get_setting",
        lambda *_args: previous,
    )

    def upsert(*args):
        writes.append(args)
        return {
            "name": "DEPLOY_TOKEN",
            "kind": args[3],
            "scope": args[7],
                "enabled": args[6],
                "configured": True,
                "generation": 2,
                "updated_at": "2026-08-02T00:00:01Z",
            }

    monkeypatch.setattr(space_environment, "upsert", upsert)

    monkeypatch.setattr(
        space_environment,
        "restore_if_current",
        lambda *args: restores.append(args) or True,
    )

    async def fail_reconcile(*_args):
        raise pipeline_control.PipelineError("Rejected", retry_safe=True)

    monkeypatch.setattr(main, "reconcile_build_setting", fail_reconcile)

    with pytest.raises(pipeline_control.PipelineError):
        run(
            main.upsert_space_environment_setting(
                "acme",
                "site",
                "DEPLOY_TOKEN",
                "secret",
                "replacement",
                "alice",
                True,
                "runtime",
                "token",
            )
        )

    assert writes[0][4] == "replacement"
    assert writes[0][7] == "runtime"
    assert len(writes) == 1
    assert restores[0][-2] == 2
    assert restores[0][-1] == previous


def test_upsert_preserves_new_local_generation_on_unknown_native_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = {"name": "DEPLOY_TOKEN", "kind": "secret", "scope": "build", "enabled": True,
            "configured": True, "generation": 1, "updated_at": "2026-08-02T00:00:01Z"}
    monkeypatch.setattr(space_environment, "get_setting", lambda *_: None); monkeypatch.setattr(space_environment, "upsert", lambda *_: item); monkeypatch.setattr(space_environment, "restore_if_current", lambda *_: pytest.fail("rolled back unknown outcome"))
    async def fail_unknown(*_args): raise pipeline_control.PipelineError("Outcome unknown", retry_safe=False)
    monkeypatch.setattr(main, "reconcile_build_setting", fail_unknown)
    with pytest.raises(pipeline_control.PipelineError) as captured:
        run(main.upsert_space_environment_setting(
            "acme", "site", "DEPLOY_TOKEN", "secret", "new-secret", "alice", True, "build", "token", "secret",
        ))
    assert captured.value.retry_safe is False


def test_superseded_upsert_reapplies_latest_generation_to_native_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = {"name": "PUBLIC_URL", "kind": "variable", "scope": "build", "enabled": True, "configured": True,
             "value": "https://first.example", "generation": 1, "updated_at": "2026-08-02T00:00:01Z"}
    latest = {**first, "value": "https://latest.example", "generation": 2}
    reads = iter([None, latest])
    monkeypatch.setattr(space_environment, "get_setting", lambda *_: next(reads)); monkeypatch.setattr(space_environment, "upsert", lambda *_: first.copy())
    reconciled: list[tuple[dict | None, dict | None]] = []
    async def reconcile(_owner, _repo, _token, previous, current): reconciled.append((previous, current))
    monkeypatch.setattr(main, "reconcile_build_setting", reconcile)
    result = run(main.upsert_space_environment_setting("acme", "site", "PUBLIC_URL", "variable",
        "https://first.example", "alice", True, "build", "token", "variable"))
    synced = {**first, "value": "https://first.example"}
    assert result["updated_at"] == first["updated_at"] and reconciled == [(None, synced), (synced, latest)]


def test_upsert_syncs_secret_plaintext_without_returning_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_item = {
        "name": "DEPLOY_TOKEN",
        "kind": "secret",
        "scope": "build",
        "enabled": True,
        "configured": True,
    }
    reconciled: list[dict] = []
    monkeypatch.setattr(
        space_environment,
        "get_setting",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        space_environment,
        "upsert",
        lambda *_args: public_item.copy(),
    )

    async def reconcile(_owner, _repo, _token, _previous, current):
        reconciled.append(current)

    monkeypatch.setattr(main, "reconcile_build_setting", reconcile)

    result = run(
        main.upsert_space_environment_setting(
            "acme",
            "site",
            "DEPLOY_TOKEN",
            "secret",
            "replacement-secret",
            "alice",
            True,
            "build",
            "token",
        )
    )

    assert "value" not in result
    assert reconciled[0]["value"] == "replacement-secret"
    assert "value" not in public_item


def test_enabling_build_secret_reads_plaintext_for_native_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = {
        "name": "DEPLOY_TOKEN",
        "kind": "secret",
        "scope": "build",
        "enabled": False,
        "value": "stored-secret",
    }
    current = {**previous, "enabled": True}
    snapshots = iter((previous, current, current))
    reconciled: list[dict] = []
    monkeypatch.setattr(
        space_environment,
        "get_setting",
        lambda *_args: next(snapshots),
    )
    monkeypatch.setattr(
        space_environment,
        "set_enabled",
        lambda *_args: {
            key: value
            for key, value in current.items()
            if key != "value"
        },
    )

    async def reconcile(_owner, _repo, _token, old, new):
        reconciled.append({"old": old, "new": new})

    monkeypatch.setattr(main, "reconcile_build_setting", reconcile)

    result = run(
        main.set_space_environment_enabled(
            "acme",
            "site",
            "DEPLOY_TOKEN",
            True,
            "alice",
            "token",
        )
    )

    assert result is not None and "value" not in result
    assert reconciled[0]["new"]["value"] == "stored-secret"


@pytest.mark.parametrize("retry_safe", [True, False])
def test_set_enabled_restores_only_after_definite_native_rejection(
    monkeypatch: pytest.MonkeyPatch,
    retry_safe: bool,
) -> None:
    previous = {"name": "DEPLOY_TOKEN", "kind": "secret", "scope": "build", "enabled": False,
                "value": "stored-secret", "generation": 1, "updated_at": "2026-08-02T00:00:00Z"}
    current = {**previous, "enabled": True, "generation": 2}; snapshots = iter((previous, current, current))
    restored: list[tuple] = []
    monkeypatch.setattr(space_environment, "get_setting", lambda *_: next(snapshots))
    monkeypatch.setattr(space_environment, "set_enabled", lambda *_: {k: v for k, v in current.items() if k != "value"})
    monkeypatch.setattr(space_environment, "restore_if_current", lambda *args: restored.append(args) or True)
    async def reject(*_args): raise pipeline_control.PipelineError("native failure", retry_safe=retry_safe)
    monkeypatch.setattr(main, "reconcile_build_setting", reject)
    with pytest.raises(pipeline_control.PipelineError):
        run(main.set_space_environment_enabled("acme", "site", "DEPLOY_TOKEN", True, "alice", "token"))
    assert restored[0][-2:] == (2, previous) if retry_safe else restored == []


def test_upsert_rolls_back_local_change_on_unexpected_sync_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    restored: list[tuple] = []
    monkeypatch.setattr(
        space_environment,
        "get_setting",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        space_environment,
        "upsert",
        lambda *_args: {
            "name": "DEPLOY_TOKEN",
            "kind": "secret",
            "scope": "build",
            "enabled": True,
            "configured": True,
            "generation": 1,
            "updated_at": "2026-08-02T00:00:01Z",
        },
    )
    monkeypatch.setattr(
        space_environment,
        "restore_if_current",
        lambda *args: restored.append(args) or True,
    )

    async def fail_reconcile(*_args):
        raise KeyError("unexpected sync contract failure")

    monkeypatch.setattr(main, "reconcile_build_setting", fail_reconcile)

    with pytest.raises(KeyError, match="unexpected sync contract failure"):
        run(
            main.upsert_space_environment_setting(
                "acme",
                "site",
                "DEPLOY_TOKEN",
                "secret",
                "replacement-secret",
                "alice",
                True,
                "build",
                "token",
            )
        )

    assert restored[0][-2:] == (1, None)


def test_new_setting_is_removed_locally_when_native_sync_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    restored: list[tuple] = []
    monkeypatch.setattr(
        space_environment,
        "get_setting",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        space_environment,
        "upsert",
        lambda *_args: {
            "name": "PUBLIC_URL",
            "kind": "variable",
            "scope": "build",
            "enabled": True,
            "configured": True,
            "value": "https://example.test",
            "generation": 1,
            "updated_at": "2026-08-02T00:00:01Z",
        },
    )
    monkeypatch.setattr(
        space_environment,
        "restore_if_current",
        lambda *args: restored.append(args) or True,
    )

    async def fail_reconcile(*_args):
        raise pipeline_control.PipelineError("Rejected", retry_safe=True)

    monkeypatch.setattr(main, "reconcile_build_setting", fail_reconcile)

    with pytest.raises(pipeline_control.PipelineError):
        run(
            main.upsert_space_environment_setting(
                "acme",
                "site",
                "PUBLIC_URL",
                "variable",
                "https://example.test",
                "alice",
                True,
                "build",
                "token",
            )
        )

    assert restored[0][-2:] == (1, None)


def test_openapi_exposes_cookie_free_pipeline_contract() -> None:
    paths = main.app.openapi()["paths"]

    assert "/api/v1/pipelines/{owner}/{repo}" in paths
    assert "/api/v1/pipelines/{owner}/{repo}/install" in paths
    assert "/api/v1/pipelines/{owner}/{repo}/dispatch" in paths
    assert "/api/v1/pipelines/{owner}/{repo}/runs/{run_number}" in paths
    assert (
        "/api/v1/pipelines/{owner}/{repo}/runs/{run_number}/{action}"
        in paths
    )
    assert (
        "/api/v1/pipelines/{owner}/{repo}/runs/{run_number}/jobs/{job_id}/rerun"
        in paths
    )


def test_runner_uses_isolated_dind_and_configurable_capacity() -> None:
    root = Path(__file__).resolve().parents[2]
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    entrypoint = (
        root / "forgejo-actions-runner" / "entrypoint.sh"
    ).read_text(encoding="utf-8")
    dind_entrypoint = (
        root / "forgejo-actions-dind" / "entrypoint.sh"
    ).read_text(encoding="utf-8")

    assert "DOCKER_HOST: unix:///run/nyankoface-docker/docker.sock" in compose
    assert "tcp://forgejo-actions-dind:2375" not in compose
    assert (
        "command:\n"
        "      - dockerd\n"
        "      - -H\n"
        "      - unix:///run/nyankoface-docker/docker.sock"
        in compose
    )
    assert compose.count(
        "- forgejo-actions-docker-run:/run/nyankoface-docker"
    ) == 2
    assert "FORGEJO_RUNNER_CAPACITY" in compose
    assert "capacity: ${RUNNER_CAPACITY}" in entrypoint
    assert 'network: ""' in entrypoint
    assert "network: host" not in entrypoint
    assert "--cap-drop NET_RAW" in entrypoint
    assert "--add-host forgejo:host-gateway" in entrypoint
    assert "--cpus ${JOB_CPUS}" in entrypoint
    assert "--memory ${JOB_MEMORY}" in entrypoint
    assert "--pids-limit ${JOB_PIDS_LIMIT}" in entrypoint
    assert (
        "${FORGEJO_ROOT_URL:-${PUBLIC_BASE_URL:-https://localhost:8443}/git/}"
        in compose
    )
    assert "context: ./forgejo-actions-dind" in compose
    assert "TCP-LISTEN:3000,fork,reuseaddr" in dind_entrypoint
    assert "TCP:forgejo:3000" in dind_entrypoint


def test_seed_registers_pipeline_before_creating_pull_fixture() -> None:
    root = Path(__file__).resolve().parents[2]
    seed = (root / "seed" / "seed.sh").read_text(encoding="utf-8")
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")

    workflow = seed.index(
        '"pages-starter" \\\n'
        '  ".forgejo/workflows/nyankoface-pipeline.yml"'
    )
    registration = seed.index(
        'register_pipeline_repository "nyankoface" "pages-starter"'
    )
    pull_fixture = seed.index(
        'ensure_pull_detail_fixture "pages-starter"'
    )

    assert workflow < registration < pull_fixture
    assert "-H \"Authorization: Bearer ${TOKEN}\"" in seed
    assert "for attempt in $(seq 1 30)" in seed
    assert (
        '"${SPACES_RUNNER_API}/api/v1/pipelines/'
        '${owner}/${repo}/install"'
        in seed
    )
    seed_service = compose.split("\n  seed:", maxsplit=1)[1].split(
        "\n  maintenance-agent:",
        maxsplit=1,
    )[0]
    assert "SPACES_RUNNER_API: http://spaces-runner:8000" in seed_service
    assert "spaces-runner:\n        condition: service_started" in seed_service


@pytest.mark.parametrize(
    ("api_status", "job_statuses", "expected"),
    [
        ("blocked", ["running", "blocked"], "running"),
        ("blocked", ["waiting", "blocked"], "waiting"),
        ("blocked", ["success", "blocked", "skipped"], "success"),
        ("success", ["success", "failure"], "failure"),
        ("blocked", ["cancelled", "blocked"], "cancelled"),
        ("blocked", ["blocked"], "blocked"),
    ],
)
def test_effective_run_status_uses_actual_jobs(
    api_status: str,
    job_statuses: list[str],
    expected: str,
) -> None:
    jobs = [{"status": status} for status in job_statuses]

    assert pipeline_control._effective_run_status(api_status, jobs) == expected


def test_starter_uses_forgejo_workflow_path() -> None:
    assert pipeline_control.PIPELINE_WORKFLOW_PATH == (
        ".forgejo/workflows/nyankoface-pipeline.yml"
    )
