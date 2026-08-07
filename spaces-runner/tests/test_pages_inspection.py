import asyncio
from unittest.mock import AsyncMock, patch

import forgejo


def run(coro):
    return asyncio.run(coro)


def public_repo(default_branch: str = "main") -> dict:
    return {
        "name": "demo",
        "private": False,
        "default_branch": default_branch,
    }


def pages_tombstone() -> bytes:
    return (
        b'{"schema":1,"repository":"acme/demo",'
        b'"sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        b'"run_id":"31","run_number":"9","event":"workflow_dispatch",'
        b'"environment":"production","operation":"delete"}'
    )


def test_prefers_publishable_gh_pages_root() -> None:
    with (
        patch.object(forgejo, "get_repo_info", AsyncMock(return_value=public_repo())),
        patch.object(
            forgejo,
            "fetch_pages_asset",
            AsyncMock(
                side_effect=[
                    (404, b"", None),
                    (200, b"<html></html>", "text/html"),
                ]
            ),
        ) as fetch_asset,
    ):
        inspection = run(forgejo.inspect_pages_source("acme", "demo", None))

    assert inspection["status"] == "published"
    assert inspection["source"] == "gh-pages"
    assert inspection["source_ref"] == "gh-pages"
    assert inspection["directory_prefix"] == ""
    assert inspection["index_path"] == "index.html"
    assert inspection["checks"] == [
        {
            "id": "gh-pages_index",
            "source": "gh-pages",
            "ref": "gh-pages",
            "path": "index.html",
            "ok": True,
            "status": 200,
        }
    ]
    assert fetch_asset.await_args_list[0].args == (
        "acme",
        "demo",
        "gh-pages",
        "",
        ".nyankoface-pages-tombstone.json",
        None,
    )
    assert fetch_asset.await_args_list[1].args == (
        "acme", "demo", "gh-pages", "", "index.html", None
    )


def test_uses_docs_when_gh_pages_has_no_index() -> None:
    with (
        patch.object(
            forgejo,
            "get_repo_info",
            AsyncMock(return_value=public_repo("trunk")),
        ),
        patch.object(
            forgejo,
            "fetch_pages_asset",
            AsyncMock(
                side_effect=[
                    (404, b"", None),
                    (404, b"", None),
                    (200, b"<html></html>", "text/html"),
                ]
            ),
        ),
    ):
        inspection = run(forgejo.inspect_pages_source("acme", "demo", None))

    assert inspection["status"] == "published"
    assert inspection["source"] == "docs"
    assert inspection["source_ref"] == "trunk"
    assert inspection["directory_prefix"] == "docs"
    assert inspection["index_path"] == "docs/index.html"
    assert [check["status"] for check in inspection["checks"]] == [404, 200]


def test_reports_every_missing_publish_source() -> None:
    with (
        patch.object(forgejo, "get_repo_info", AsyncMock(return_value=public_repo())),
        patch.object(
            forgejo,
            "fetch_pages_asset",
            AsyncMock(side_effect=[(404, b"", None)] * 6),
        ),
    ):
        inspection = run(forgejo.inspect_pages_source("acme", "demo", None))
        source = run(forgejo.get_pages_source("acme", "demo", None))

    assert inspection["status"] == "missing"
    assert inspection["source"] is None
    assert [check["path"] for check in inspection["checks"]] == [
        "index.html",
        "docs/index.html",
    ]
    assert inspection["reasons"]
    assert source is None


def test_private_repository_is_never_inspected_or_published() -> None:
    private_repo = {**public_repo(), "private": True}
    with (
        patch.object(forgejo, "get_repo_info", AsyncMock(return_value=private_repo)),
        patch.object(forgejo, "fetch_pages_asset", AsyncMock()) as fetch_asset,
    ):
        inspection = run(forgejo.inspect_pages_source("acme", "secret", "token"))

    assert inspection["status"] == "private"
    assert inspection["public"] is False
    assert inspection["source"] is None
    assert inspection["checks"] == []
    fetch_asset.assert_not_awaited()


def test_valid_production_tombstone_suppresses_docs_fallback() -> None:
    with (
        patch.object(forgejo, "get_repo_info", AsyncMock(return_value=public_repo())),
        patch.object(
            forgejo,
            "fetch_pages_asset",
            AsyncMock(return_value=(200, pages_tombstone(), "application/json")),
        ) as fetch_asset,
    ):
        inspection = run(forgejo.inspect_pages_source("acme", "demo", None))

    assert inspection["status"] == "missing"
    assert inspection["source"] is None
    assert inspection["checks"] == []
    assert "intentionally disabled" in inspection["reasons"][0]
    assert fetch_asset.await_count == 1


def test_invalid_production_tombstone_fails_closed() -> None:
    with (
        patch.object(forgejo, "get_repo_info", AsyncMock(return_value=public_repo())),
        patch.object(
            forgejo,
            "fetch_pages_asset",
            AsyncMock(return_value=(200, b'{"operation":"delete"}', "application/json")),
        ) as fetch_asset,
    ):
        inspection = run(forgejo.inspect_pages_source("acme", "demo", None))

    assert inspection["status"] == "error"
    assert "marker is invalid" in inspection["reasons"][0]
    assert fetch_asset.await_count == 1


def test_upstream_failure_is_not_reported_as_missing_configuration() -> None:
    with (
        patch.object(forgejo, "get_repo_info", AsyncMock(return_value=public_repo())),
        patch.object(
            forgejo,
            "fetch_pages_asset",
            AsyncMock(
                side_effect=[
                    (404, b"", None),
                    (503, b"", None),
                ]
            ),
        ),
    ):
        inspection = run(forgejo.inspect_pages_source("acme", "demo", None))

    assert inspection["status"] == "error"
    assert inspection["checks"][0]["status"] == 503
    assert "HTTP 503" in inspection["reasons"][0]


def test_tombstone_lookup_failure_is_not_reported_as_missing() -> None:
    with (
        patch.object(forgejo, "get_repo_info", AsyncMock(return_value=public_repo())),
        patch.object(
            forgejo,
            "fetch_pages_asset",
            AsyncMock(return_value=(503, b"", None)),
        ),
    ):
        inspection = run(forgejo.inspect_pages_source("acme", "demo", None))

    assert inspection["status"] == "error"
    assert inspection["checks"] == []
    assert ".nyankoface-pages-tombstone.json" in inspection["reasons"][0]
