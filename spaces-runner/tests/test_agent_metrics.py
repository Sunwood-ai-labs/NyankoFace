import asyncio
from datetime import datetime, timedelta, timezone
import os
from unittest.mock import AsyncMock

import psycopg
import pytest
from fastapi import HTTPException

import agent_metrics
import config
import main


@pytest.fixture
def metrics_database(monkeypatch: pytest.MonkeyPatch, tmp_path):
    database_url = os.environ.get("NYANKOFACE_METRICS_TEST_DATABASE_URL") or os.environ.get(
        "NYANKOFACE_PIPELINE_TEST_DATABASE_URL"
    )
    if not database_url:
        pytest.skip("a PostgreSQL metrics test URL is not configured")
    monkeypatch.setattr(config, "DATABASE_URL", database_url)
    monkeypatch.setattr(config, "AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "AGENT_CREDENTIALS_FILE", str(tmp_path / "credentials.json"))
    try:
        with psycopg.connect(database_url) as db:
            db.execute("SELECT 1")
    except psycopg.Error as exc:
        pytest.skip(f"PostgreSQL metrics test database is unavailable: {exc}")

    agent_metrics.initialize()
    with psycopg.connect(database_url) as db:
        db.execute(
            "TRUNCATE metric_events, repo_views, browser_views, repo_likes, knowledge_views, agents "
            "RESTART IDENTITY CASCADE"
        )
    agent_metrics.initialize()
    yield


def agent_id() -> int:
    with psycopg.connect(config.DATABASE_URL, row_factory=psycopg.rows.dict_row) as db:
        return int(db.execute("SELECT id FROM agents ORDER BY id LIMIT 1").fetchone()["id"])


def agent_ids() -> list[int]:
    with psycopg.connect(config.DATABASE_URL, row_factory=psycopg.rows.dict_row) as db:
        return [int(row["id"]) for row in db.execute("SELECT id FROM agents ORDER BY id LIMIT 2").fetchall()]


def test_cumulative_metrics_use_one_idempotent_event_ledger(metrics_database) -> None:
    agent = agent_id()

    created, _ = agent_metrics.record_view(agent, "nyankoface", "metrics", "agent-view-1")
    assert created is True
    duplicate, _ = agent_metrics.record_view(agent, "nyankoface", "metrics", "agent-view-1")
    assert duplicate is False

    raw, _ = agent_metrics.record_download(
        "nyankoface", "metrics", "raw", "weights/model.bin", "download-raw-1"
    )
    assert raw is True
    duplicate_raw, _ = agent_metrics.record_download(
        "nyankoface", "metrics", "raw", "weights/model.bin", "download-raw-1"
    )
    assert duplicate_raw is False
    failed, _ = agent_metrics.record_download(
        "nyankoface", "metrics", "lfs", "weights/model.bin", "download-lfs-1", "failed"
    )
    assert failed is True

    liked, _ = agent_metrics.set_like(agent, "nyankoface", "metrics", True)
    assert liked is True
    unliked, _ = agent_metrics.set_like(agent, "nyankoface", "metrics", False)
    assert unliked is True

    result = agent_metrics.metrics("nyankoface", "metrics")
    assert result["views"] == 1
    assert result["agent_views"] == 1
    assert result["downloads"] == 1
    assert result["downloads_by_source"] == {"raw": 1, "lfs": 0, "automation": 0}
    assert result["likes"] == 0


def test_legacy_backfill_does_not_duplicate_live_events_or_cross_agents(metrics_database) -> None:
    first_agent, second_agent = agent_ids()

    first_created, _ = agent_metrics.record_view(first_agent, "nyankoface", "restart-safe", "shared-key")
    second_created, _ = agent_metrics.record_view(second_agent, "nyankoface", "restart-safe", "shared-key")
    browser_created, _ = agent_metrics.record_browser_view("nyankoface", "restart-safe", "browser-key")
    liked, _ = agent_metrics.set_like(first_agent, "nyankoface", "restart-safe", True)
    assert first_created is True
    assert second_created is True
    assert browser_created is True
    assert liked is True

    before_restart = agent_metrics.metrics("nyankoface", "restart-safe")
    agent_metrics._backfill_metric_events()
    after_restart = agent_metrics.metrics("nyankoface", "restart-safe")

    assert before_restart == after_restart
    assert after_restart["agent_views"] == 2
    assert after_restart["browser_views"] == 1
    assert after_restart["likes"] == 1


def test_timeseries_distinguishes_data_from_no_data_and_reconstructs_likes(metrics_database) -> None:
    agent = agent_id()
    agent_metrics.record_browser_view("nyankoface", "series", "browser-1")
    agent_metrics.record_download("nyankoface", "series", "automation", "release.toml", "download-1")
    agent_metrics.set_like(agent, "nyankoface", "series", True)

    now = datetime.now(timezone.utc)
    measured = agent_metrics.timeseries(
        "nyankoface",
        "series",
        now - timedelta(days=2),
        now + timedelta(minutes=1),
        "day",
        "UTC",
    )
    assert measured["data_state"] == "data"
    assert measured["totals"] == {
        "views": 1,
        "downloads": 1,
        "likes": 1,
        "downloads_by_source": {"raw": 0, "lfs": 0, "automation": 1},
    }
    assert any(point["views"] == 1 for point in measured["series"])
    assert any(point["downloads"] == 1 for point in measured["series"])
    assert measured["series"][-1]["likes"] == 1

    empty = agent_metrics.timeseries(
        "nyankoface",
        "series",
        now - timedelta(days=365),
        now - timedelta(days=300),
        "week",
        "UTC",
    )
    assert empty["data_state"] == "no_data"
    assert empty["totals"]["views"] == 0
    assert empty["totals"]["downloads"] == 0


def test_timeseries_rejects_unbounded_windows_and_unknown_timezones(metrics_database) -> None:
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="366 days"):
        agent_metrics.timeseries("nyankoface", "metrics", now - timedelta(days=367), now)
    with pytest.raises(ValueError, match="IANA"):
        agent_metrics.timeseries("nyankoface", "metrics", now - timedelta(days=1), now, timezone_name="Not/AZone")


def test_public_metrics_boundary_hides_private_repositories(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        main.forgejo,
        "get_repo_info",
        AsyncMock(return_value={"private": True}),
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(main.verify_public_repo("nyankoface", "private-metrics"))

    assert error.value.status_code == 404
    assert error.value.detail == "The public repository was not found"


def test_metrics_batch_skips_repositories_that_are_no_longer_public(monkeypatch: pytest.MonkeyPatch) -> None:
    async def verify(owner: str, repo: str) -> None:
        if repo == "private-metrics":
            raise HTTPException(status_code=404, detail="The public repository was not found")

    monkeypatch.setattr(main, "verify_public_repo", verify)
    captured: list[tuple[str, str]] = []

    def metrics_batch(targets: list[tuple[str, str]]) -> dict[str, dict[str, str]]:
        captured.extend(targets)
        return {f"{owner}/{repo}": {"owner": owner, "repo": repo} for owner, repo in targets}

    monkeypatch.setattr(main.agent_metrics, "metrics_batch", metrics_batch)
    payload = main.RepoMetricsBatchRequest(repos=[
        main.RepoMetricsTarget(owner="nyankoface", repo="public-metrics"),
        main.RepoMetricsTarget(owner="nyankoface", repo="private-metrics"),
    ])

    result = asyncio.run(main.api_repo_metrics_batch(payload))

    assert captured == [("nyankoface", "public-metrics")]
    assert result == {"nyankoface/public-metrics": {"owner": "nyankoface", "repo": "public-metrics"}}


def test_download_metric_requires_frontend_control(monkeypatch: pytest.MonkeyPatch) -> None:
    request = main.Request({
        "type": "http", "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": "/api/metrics/repos/nyankoface/metrics/downloads",
        "raw_path": b"/api/metrics/repos/nyankoface/metrics/downloads",
        "query_string": b"", "headers": [], "server": ("test", 80),
        "client": ("test", 1), "root_path": "",
    })
    payload = main.DownloadMetricRequest(
        source="raw", artifact_path="weights/model.bin", idempotency_key="download-1",
    )
    monkeypatch.setattr(config, "CONTROL_TOKEN", "control-token")

    with pytest.raises(HTTPException) as error:
        asyncio.run(main.api_download_metric(request, "nyankoface", "metrics", payload, None))
    assert error.value.status_code == 403

    monkeypatch.setattr(main, "verify_public_repo", AsyncMock())
    monkeypatch.setattr(
        main.agent_metrics,
        "record_download",
        lambda *_args: (True, {"downloads": 1}),
    )
    result = asyncio.run(
        main.api_download_metric(request, "nyankoface", "metrics", payload, "control-token")
    )
    assert result["created"] is True
