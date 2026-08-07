import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest.mock import AsyncMock

import gpu_control
import pytest
from gpu_control import worker_matches


def test_gpu_worker_matches_vram_and_features():
    capabilities = {
        "docker": True,
        "gpu_count": 1,
        "gpu_devices": [{"id": "0", "free_vram_mb": 16384}],
        "free_vram_mb": 16384,
        "features": ["nvidia", "cuda"],
    }
    assert worker_matches(
        capabilities,
        {"gpu": True, "min_vram_mb": 12288, "features": ["nvidia"]},
    )


def test_gpu_worker_rejects_insufficient_vram():
    capabilities = {
        "docker": True,
        "gpu_count": 1,
        "gpu_devices": [{"id": "0", "free_vram_mb": 8192}],
        "free_vram_mb": 8192,
        "features": ["nvidia"],
    }
    assert not worker_matches(
        capabilities,
        {"gpu": True, "min_vram_mb": 12288, "features": ["nvidia"]},
    )


def test_gpu_worker_rejects_missing_feature_or_docker():
    assert not worker_matches(
        {
            "docker": True,
            "gpu_count": 1,
            "free_vram_mb": 24576,
            "features": ["nvidia"],
        },
        {"gpu": True, "features": ["cuda"]},
    )


def test_gpu_worker_rejects_fragmented_vram():
    capabilities = {
        "docker": True,
        "gpu_count": 2,
        "gpu_devices": [
            {"id": "0", "free_vram_mb": 8192},
            {"id": "1", "free_vram_mb": 8192},
        ],
        "free_vram_mb": 16384,
        "features": ["nvidia"],
    }
    assert not worker_matches(
        capabilities,
        {"gpu": True, "gpu_count": 1, "min_vram_mb": 12288},
    )
    assert not worker_matches(
        {
            "docker": False,
            "gpu_count": 1,
            "free_vram_mb": 24576,
            "features": ["nvidia"],
        },
        {"gpu": True},
    )


def test_concurrent_enqueue_creates_exactly_one_repo_job(monkeypatch):
    lock = threading.Lock()
    state = {"job": None, "inserts": 0}

    class FakeConnection:
        def __init__(self):
            self.locked = False

        def execute(self, sql, params=None):
            if "pg_advisory_xact_lock" in sql:
                assert params == ("acme/demo",)
                lock.acquire()
                self.locked = True
                return None
            if "SELECT * FROM gpu_jobs" in sql:
                return FakeResult(state["job"])
            if "INSERT INTO gpu_jobs" in sql:
                state["inserts"] += 1
                state["job"] = {
                    "id": "replacement-job",
                    "owner": params[1],
                    "repo": params[2],
                    "revision": params[3],
                    "status": "queued",
                }
                return FakeResult(state["job"])
            raise AssertionError(sql)

        def close(self):
            if self.locked:
                lock.release()

    class FakeResult:
        def __init__(self, row):
            self.row = row

        def fetchone(self):
            return self.row

    @contextmanager
    def connect():
        connection = FakeConnection()
        try:
            yield connection
        finally:
            connection.close()

    monkeypatch.setattr(gpu_control, "_connect", connect)

    def enqueue(identity):
        return gpu_control.enqueue_job(*identity, "abc123", {"gpu": True})

    with ThreadPoolExecutor(max_workers=2) as executor:
        jobs = list(executor.map(enqueue, [("Acme", "Demo"), ("acme", "demo")]))

    assert state["inserts"] == 1
    assert [job["id"] for job in jobs] == ["replacement-job", "replacement-job"]
    assert state["job"]["owner"] == "acme"
    assert state["job"]["repo"] == "demo"


def test_async_job_read_is_cancelled_by_one_end_to_end_deadline(monkeypatch):
    query_cancelled = asyncio.Event()

    class FakeConnection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, sql, params):
            assert "SELECT * FROM gpu_jobs" in sql
            assert params == ("job-1",)
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                query_cancelled.set()
                raise

    async def slow_connect(*_args, **_kwargs):
        await asyncio.sleep(0.01)
        return FakeConnection()

    monkeypatch.setattr(
        gpu_control.psycopg.AsyncConnection,
        "connect",
        slow_connect,
    )

    async def scenario():
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(gpu_control.get_job_async("job-1"), timeout=0.02)
        assert query_cancelled.is_set()

    asyncio.run(scenario())


def test_async_job_read_returns_database_row(monkeypatch):
    row = {"id": "job-1", "status": "cancelled"}

    class FakeResult:
        async def fetchone(self):
            return row

    class FakeConnection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, _sql, _params):
            return FakeResult()

    connect = AsyncMock(return_value=FakeConnection())
    monkeypatch.setattr(gpu_control.psycopg.AsyncConnection, "connect", connect)

    assert asyncio.run(gpu_control.get_job_async("job-1")) == row
    connect.assert_awaited_once_with(
        gpu_control.config.DATABASE_URL,
        row_factory=gpu_control.dict_row,
    )


def test_cancel_unavailable_job_is_immediately_terminal(monkeypatch):
    class FakeResult:
        def fetchone(self):
            return {"id": "job-1", "status": "cancelled"}

    class FakeConnection:
        def execute(self, sql, params):
            assert "status IN ('queued', 'unavailable')" in sql
            assert params == ("acme", "demo")
            return FakeResult()

    @contextmanager
    def connect():
        yield FakeConnection()

    monkeypatch.setattr(gpu_control, "_connect", connect)

    result = gpu_control.cancel_repo_job("Acme", "Demo")

    assert result == {"id": "job-1", "status": "cancelled"}


def test_list_repo_jobs_groups_case_insensitively(monkeypatch):
    class FakeResult:
        def fetchall(self):
            return []

    class FakeConnection:
        def execute(self, sql):
            assert "DISTINCT ON (lower(owner), lower(repo))" in sql
            assert "lower(owner) AS owner, lower(repo) AS repo" in sql
            return FakeResult()

    @contextmanager
    def connect():
        yield FakeConnection()

    monkeypatch.setattr(gpu_control, "_connect", connect)

    assert gpu_control.list_repo_jobs() == []
