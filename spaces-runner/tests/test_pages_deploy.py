import asyncio
import base64
from unittest.mock import AsyncMock, patch

import forgejo
import httpx
import pages_deploy
import pytest


def run(coro):
    return asyncio.run(coro)


def public_repo(default_branch: str = "main") -> dict:
    return {
        "name": "demo",
        "private": False,
        "default_branch": default_branch,
    }


def published(source: str = "gh-pages") -> dict:
    return {
        "status": "published",
        "source": source,
        "source_ref": source if source == "gh-pages" else "main",
        "directory_prefix": "" if source == "gh-pages" else "docs",
    }


def test_static_deploy_creates_branch_and_returns_commit() -> None:
    with (
        patch.object(
            forgejo, "get_repo_info", AsyncMock(return_value=public_repo())
        ),
        patch.object(forgejo, "ensure_branch", AsyncMock(return_value=True)) as ensure,
        patch.object(
            forgejo,
            "upsert_repo_file",
            AsyncMock(
                return_value={
                    "sha": "abc123",
                    "branch": "gh-pages",
                    "path": "index.html",
                    "message": "pages: publish static starter",
                    "changed": True,
                }
            ),
        ) as upsert,
        patch.object(
            forgejo,
            "inspect_pages_source",
            AsyncMock(return_value=published()),
        ),
    ):
        result = run(
            pages_deploy.deploy(
                "acme", "demo", "gh-pages", "token", "alice"
            )
        )

    assert result["status"] == "published"
    assert result["commits"][0]["sha"] == "abc123"
    ensure.assert_awaited_once_with(
        "acme", "demo", "gh-pages", "main", "token"
    )
    upsert.assert_awaited_once()


@__import__("pytest").mark.parametrize("payload", [[], {"content": "%%%"}, {"content": "/w=="}, {"content": 7}])
def test_file_preflight_rejects_invalid_payload(payload) -> None:
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.return_value.status_code = 200
    client.get.return_value.json = lambda: payload
    with patch.object(forgejo.httpx, "AsyncClient", return_value=client), \
            __import__("pytest").raises(forgejo.ForgejoPreflightError):
        run(forgejo.upsert_repo_file("acme", "demo", "main", "x", "x", "m", None, "alice"))
    client.post.assert_not_awaited()


@pytest.mark.parametrize("payload", [[], {"commit": []}])
def test_file_write_rejects_invalid_success_payload_as_unknown(payload) -> None:
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.return_value.status_code = 404
    client.post.return_value.status_code = 201
    client.post.return_value.json = lambda: payload
    with patch.object(forgejo.httpx, "AsyncClient", return_value=client), \
            pytest.raises(forgejo.ForgejoError):
        run(forgejo.upsert_repo_file("acme", "demo", "main", "x", "x", "m", None, "alice"))
    client.post.assert_awaited_once()


def test_file_upsert_reports_whether_it_changed_repository() -> None:
    unchanged = AsyncMock()
    unchanged.__aenter__.return_value = unchanged
    unchanged.get.return_value.status_code = 200
    unchanged.get.return_value.json = lambda: {
        "sha": "blob",
        "last_commit_sha": "existing",
        "content": base64.b64encode(b"same").decode("ascii"),
    }
    with patch.object(forgejo.httpx, "AsyncClient", return_value=unchanged):
        result = run(forgejo.upsert_repo_file(
            "acme", "demo", "main", "x", "same", "m", None, "alice",
        ))
    assert result["changed"] is False
    unchanged.put.assert_not_awaited()

    changed = AsyncMock()
    changed.__aenter__.return_value = changed
    changed.get.return_value.status_code = 404
    changed.post.return_value.status_code = 201
    changed.post.return_value.json = lambda: {"commit": {"sha": "new"}}
    with patch.object(forgejo.httpx, "AsyncClient", return_value=changed):
        result = run(forgejo.upsert_repo_file(
            "acme", "demo", "main", "x", "new", "m", None, "alice",
        ))
    assert result["changed"] is True


@pytest.mark.parametrize("payload", [[], "repo", None])
def test_repository_lookup_rejects_non_object_payload(payload) -> None:
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.return_value.status_code = 200
    client.get.return_value.json = lambda: payload

    with (
        patch.object(forgejo.httpx, "AsyncClient", return_value=client),
        pytest.raises(
            forgejo.ForgejoPreflightError,
            match="invalid repository response",
        ),
    ):
        run(forgejo.get_repo_info("acme", "demo", None))


def test_repository_lookup_rejects_invalid_json() -> None:
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.return_value.status_code = 200
    client.get.return_value.json.side_effect = ValueError("invalid JSON")

    with (
        patch.object(forgejo.httpx, "AsyncClient", return_value=client),
        pytest.raises(
            forgejo.ForgejoPreflightError,
            match="invalid repository response",
        ),
    ):
        run(forgejo.get_repo_info("acme", "demo", None))


def test_pages_preflight_after_first_write_has_unknown_outcome() -> None:
    upsert = AsyncMock(side_effect=[
        {"sha": "first", "branch": "main", "path": "package.json", "message": "pages", "changed": True},
        forgejo.ForgejoPreflightError("invalid response"),
    ])
    with (
        patch.object(forgejo, "get_repo_info", AsyncMock(return_value=public_repo())),
        patch.object(forgejo, "upsert_repo_file", upsert),
        pytest.raises(pages_deploy.PagesOutcomeUnknown),
    ):
        run(pages_deploy.deploy("acme", "demo", "vitepress", "token", "alice"))


def test_first_write_rejection_remains_definite() -> None:
    rejected = forgejo.ForgejoWriteRejected("unprocessable")
    with (
        patch.object(forgejo, "get_repo_info", AsyncMock(return_value=public_repo())),
        patch.object(forgejo, "upsert_repo_file", AsyncMock(side_effect=rejected)),
        pytest.raises(forgejo.ForgejoWriteRejected),
    ):
        run(pages_deploy.deploy("acme", "demo", "docs", "token", "alice"))


def test_write_rejection_after_partial_deploy_is_unknown() -> None:
    upsert = AsyncMock(side_effect=[
        {"sha": "first", "branch": "main", "path": "package.json", "message": "pages", "changed": True},
        forgejo.ForgejoWriteRejected("unprocessable"),
    ])
    with (
        patch.object(forgejo, "get_repo_info", AsyncMock(return_value=public_repo())),
        patch.object(forgejo, "upsert_repo_file", upsert),
        pytest.raises(pages_deploy.PagesOutcomeUnknown),
    ):
        run(pages_deploy.deploy("acme", "demo", "vitepress", "token", "alice"))


def test_docs_deploy_uses_default_branch() -> None:
    with (
        patch.object(
            forgejo,
            "get_repo_info",
            AsyncMock(return_value=public_repo("trunk")),
        ),
        patch.object(
            forgejo,
            "upsert_repo_file",
            AsyncMock(
                return_value={
                    "sha": "def456",
                    "branch": "trunk",
                    "path": "docs/index.html",
                    "message": "pages: publish docs starter",
                    "changed": True,
                }
            ),
        ) as upsert,
        patch.object(
            forgejo,
            "inspect_pages_source",
            AsyncMock(return_value=published("docs")),
        ),
    ):
        result = run(
            pages_deploy.deploy("acme", "demo", "docs", None, "alice")
        )

    assert result["status"] == "published"
    args = upsert.await_args.args
    assert args[2:4] == ("trunk", "docs/index.html")


def test_vitepress_deploy_writes_source_and_waits_for_actions() -> None:
    commits = [
        {
            "sha": f"sha-{index}",
            "branch": "main",
            "path": item["path"],
            "message": "pages",
            "changed": True,
        }
        for index, item in enumerate(
            pages_deploy.deployment_plan("vitepress", "main")
        )
    ]
    with (
        patch.object(
            forgejo, "get_repo_info", AsyncMock(return_value=public_repo())
        ),
        patch.object(
            forgejo,
            "upsert_repo_file",
            AsyncMock(side_effect=commits),
        ) as upsert,
        patch.object(
            forgejo,
            "inspect_pages_source",
            AsyncMock(return_value={"status": "missing", "reasons": []}),
        ),
    ):
        result = run(
            pages_deploy.deploy(
                "acme", "demo", "vitepress", "token", "alice"
            )
        )

    assert result["status"] == "queued"
    assert upsert.await_count == 4
    assert result["actions_url"] == "/git/acme/demo/actions"


@pytest.mark.parametrize("failure", [ValueError("bad json"), AttributeError("bad schema")])
def test_post_write_inspection_parse_failure_is_unknown(failure) -> None:
    with (
        patch.object(forgejo, "get_repo_info", AsyncMock(return_value=public_repo())),
        patch.object(forgejo, "upsert_repo_file", AsyncMock(return_value={
            "sha": "new", "branch": "main", "path": "docs/index.html",
            "message": "pages", "changed": True,
        })),
        patch.object(forgejo, "inspect_pages_source", AsyncMock(side_effect=failure)),
        pytest.raises(pages_deploy.PagesOutcomeUnknown),
    ):
        run(pages_deploy.deploy("acme", "demo", "docs", "token", "alice"))


def test_noop_deploy_keeps_inspection_parse_failure_retry_safe() -> None:
    failure = ValueError("bad json")
    with (
        patch.object(forgejo, "get_repo_info", AsyncMock(return_value=public_repo())),
        patch.object(forgejo, "upsert_repo_file", AsyncMock(return_value={
            "sha": "old", "branch": "main", "path": "docs/index.html",
            "message": "pages", "changed": False,
        })),
        patch.object(forgejo, "inspect_pages_source", AsyncMock(side_effect=failure)),
        pytest.raises(ValueError),
    ):
        run(pages_deploy.deploy("acme", "demo", "docs", "token", "alice"))


def test_noop_deploy_keeps_inspection_transport_failure_retry_safe() -> None:
    failure = httpx.ReadTimeout("timeout")
    with (
        patch.object(forgejo, "get_repo_info", AsyncMock(return_value=public_repo())),
        patch.object(forgejo, "upsert_repo_file", AsyncMock(return_value={
            "sha": "old", "branch": "main", "path": "docs/index.html",
            "message": "pages", "changed": False,
        })),
        patch.object(forgejo, "inspect_pages_source", AsyncMock(side_effect=failure)),
        pytest.raises(httpx.HTTPError),
    ):
        run(pages_deploy.deploy("acme", "demo", "docs", "token", "alice"))


def test_private_repository_is_rejected_before_writes() -> None:
    with (
        patch.object(
            forgejo,
            "get_repo_info",
            AsyncMock(return_value={**public_repo(), "private": True}),
        ),
        patch.object(forgejo, "upsert_repo_file", AsyncMock()) as upsert,
    ):
        try:
            run(
                pages_deploy.deploy(
                    "acme", "secret", "docs", "token", "alice"
                )
            )
        except forgejo.ForgejoError as exc:
            assert "public repositories" in str(exc)
        else:
            raise AssertionError("private repository should be rejected")
    upsert.assert_not_awaited()
