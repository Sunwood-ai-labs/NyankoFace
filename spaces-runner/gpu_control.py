"""Persistent control plane for pull-based remote GPU workers.

The database is the source of truth. Workers only receive jobs after an
authenticated claim and must continuously renew a short lease.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

import config


SCHEMA = """
CREATE TABLE IF NOT EXISTS gpu_workers (
    id uuid PRIMARY KEY,
    name text NOT NULL,
    credential_hash text NOT NULL UNIQUE,
    capabilities jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'offline',
    max_jobs integer NOT NULL DEFAULT 1,
    running_jobs integer NOT NULL DEFAULT 0,
    last_seen_at timestamptz,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS gpu_worker_enrollment_tokens (
    token_hash text PRIMARY KEY,
    name text NOT NULL,
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS gpu_jobs (
    id uuid PRIMARY KEY,
    owner text NOT NULL,
    repo text NOT NULL,
    revision text NOT NULL,
    status text NOT NULL DEFAULT 'queued',
    requirements jsonb NOT NULL DEFAULT '{}'::jsonb,
    worker_id uuid REFERENCES gpu_workers(id),
    lease_expires_at timestamptz,
    runtime_url text,
    runtime_token text,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    created_by text NOT NULL DEFAULT 'nyankoface'
);
CREATE INDEX IF NOT EXISTS gpu_jobs_schedulable
    ON gpu_jobs(status, created_at);
CREATE TABLE IF NOT EXISTS gpu_job_events (
    id bigserial PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES gpu_jobs(id) ON DELETE CASCADE,
    worker_id uuid REFERENCES gpu_workers(id),
    kind text NOT NULL,
    idempotency_key text,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(job_id, idempotency_key)
);
ALTER TABLE gpu_job_events
    ADD COLUMN IF NOT EXISTS idempotency_key text;
CREATE UNIQUE INDEX IF NOT EXISTS gpu_job_events_idempotency
    ON gpu_job_events(job_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
"""

ACTIVE_STATUSES = ("leased", "building", "running", "stopping")
TERMINAL_STATUSES = ("completed", "failed", "cancelled")
EVENT_TO_STATUS = {
    "building": "building",
    "running": "running",
    "stopping": "stopping",
    "completed": "completed",
    "failed": "failed",
}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _connect():
    return psycopg.connect(config.DATABASE_URL, row_factory=dict_row)


def initialize() -> None:
    with _connect() as conn:
        conn.execute(SCHEMA)


def issue_enrollment_token(name: str, ttl_minutes: int = 15) -> dict[str, Any]:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=max(1, min(ttl_minutes, 1440)))
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO gpu_worker_enrollment_tokens(token_hash, name, expires_at)
            VALUES (%s, %s, %s)
            """,
            (_hash(token), name, expires_at),
        )
    return {"token": token, "name": name, "expires_at": expires_at.isoformat()}


def enroll(token: str) -> dict[str, Any] | None:
    credential = secrets.token_urlsafe(48)
    worker_id = uuid.uuid4()
    with _connect() as conn:
        row = conn.execute(
            """
            UPDATE gpu_worker_enrollment_tokens
               SET consumed_at = now()
             WHERE token_hash = %s
               AND consumed_at IS NULL
               AND expires_at > now()
         RETURNING name
            """,
            (_hash(token),),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            """
            INSERT INTO gpu_workers(id, name, credential_hash)
            VALUES (%s, %s, %s)
            """,
            (worker_id, row["name"], _hash(credential)),
        )
    return {"worker_id": str(worker_id), "credential": credential, "name": row["name"]}


def authenticate(credential: str) -> dict[str, Any] | None:
    with _connect() as conn:
        return conn.execute(
            """
            SELECT * FROM gpu_workers
             WHERE credential_hash = %s AND revoked_at IS NULL
            """,
            (_hash(credential),),
        ).fetchone()


def register(worker_id: str, capabilities: dict[str, Any], max_jobs: int) -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute(
            """
            UPDATE gpu_workers
               SET capabilities = %s::jsonb,
                   max_jobs = %s,
                   status = 'online',
                   last_seen_at = now()
             WHERE id = %s AND revoked_at IS NULL
         RETURNING *
            """,
            (json.dumps(capabilities), max(1, min(max_jobs, 16)), worker_id),
        ).fetchone()
    if not row:
        raise KeyError(worker_id)
    return row


def heartbeat(worker_id: str, capabilities: dict[str, Any], running_jobs: int) -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute(
            """
            UPDATE gpu_workers
               SET capabilities = %s::jsonb,
                   running_jobs = %s,
                   status = 'online',
                   last_seen_at = now()
             WHERE id = %s AND revoked_at IS NULL
         RETURNING id, status, last_seen_at
            """,
            (json.dumps(capabilities), max(0, running_jobs), worker_id),
        ).fetchone()
        desired = conn.execute(
            """
            SELECT id, status FROM gpu_jobs
             WHERE worker_id = %s AND status IN ('cancel_requested')
            """,
            (worker_id,),
        ).fetchall()
    if not row:
        raise KeyError(worker_id)
    return {"worker": row, "actions": [{"job_id": str(item["id"]), "action": "stop"} for item in desired]}


def worker_matches(capabilities: dict[str, Any], requirements: dict[str, Any]) -> bool:
    """Return whether a worker satisfies the deliberately small v1 contract."""
    required_count = max(1, int(requirements.get("gpu_count", 1)))
    if requirements.get("gpu") and int(capabilities.get("gpu_count", 0)) < required_count:
        return False
    minimum_vram = int(requirements.get("min_vram_mb", 0))
    devices = capabilities.get("gpu_devices") or []
    if devices:
        eligible_devices = [
            device
            for device in devices
            if int(device.get("free_vram_mb", 0)) >= minimum_vram
        ]
        if len(eligible_devices) < required_count:
            return False
    elif int(capabilities.get("free_vram_mb", 0)) < minimum_vram * required_count:
        return False
    required_features = set(requirements.get("features") or [])
    if not required_features.issubset(set(capabilities.get("features") or [])):
        return False
    return bool(capabilities.get("docker", False))


def enqueue_job(owner: str, repo: str, revision: str, requirements: dict[str, Any]) -> dict[str, Any]:
    owner, repo = owner.lower(), repo.lower()
    with _connect() as conn:
        # Serialize the lookup-and-insert sequence across runner instances. This
        # is especially important after restart waits for a cancellation: two
        # concurrent callers must converge on one replacement job.
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (f"{owner}/{repo}",),
        )
        existing = conn.execute(
            """
            SELECT * FROM gpu_jobs
             WHERE lower(owner) = %s AND lower(repo) = %s
               AND status NOT IN ('completed', 'failed', 'cancelled')
          ORDER BY created_at DESC LIMIT 1
            """,
            (owner, repo),
        ).fetchone()
        if existing:
            return existing
        return conn.execute(
            """
            INSERT INTO gpu_jobs(id, owner, repo, revision, requirements)
            VALUES (%s, %s, %s, %s, %s::jsonb)
            RETURNING *
            """,
            (uuid.uuid4(), owner, repo, revision, json.dumps(requirements)),
        ).fetchone()


def claim_job(worker: dict[str, Any]) -> dict[str, Any] | None:
    capabilities = worker.get("capabilities") or {}
    if worker["running_jobs"] >= worker["max_jobs"]:
        return None
    lease_until = datetime.now(timezone.utc) + timedelta(seconds=config.GPU_WORKER_LEASE_SECONDS)
    with _connect() as conn:
        candidates = conn.execute(
            """
            SELECT * FROM gpu_jobs
             WHERE status = 'queued'
          ORDER BY created_at
             FOR UPDATE SKIP LOCKED
            """
        ).fetchall()
        selected = next(
            (item for item in candidates if worker_matches(capabilities, item["requirements"] or {})),
            None,
        )
        if not selected:
            return None
        job = conn.execute(
            """
            UPDATE gpu_jobs
               SET status = 'leased', worker_id = %s,
                   lease_expires_at = %s, updated_at = now()
             WHERE id = %s AND status = 'queued'
         RETURNING *
            """,
            (worker["id"], lease_until, selected["id"]),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO gpu_job_events(job_id, worker_id, kind, details)
            VALUES (%s, %s, 'leased', '{}'::jsonb)
            """,
            (job["id"], worker["id"]),
        )
        return job


def renew_lease(worker_id: str, job_id: str) -> dict[str, Any] | None:
    lease_until = datetime.now(timezone.utc) + timedelta(seconds=config.GPU_WORKER_LEASE_SECONDS)
    with _connect() as conn:
        return conn.execute(
            """
            UPDATE gpu_jobs SET lease_expires_at = %s, updated_at = now()
             WHERE id = %s AND worker_id = %s
               AND status IN ('leased', 'building', 'running', 'stopping')
         RETURNING id, status, lease_expires_at
            """,
            (lease_until, job_id, worker_id),
        ).fetchone()


def record_event(
    worker_id: str,
    job_id: str,
    kind: str,
    details: dict[str, Any],
    idempotency_key: str | None = None,
) -> dict[str, Any] | None:
    next_status = EVENT_TO_STATUS.get(kind)
    runtime_url = details.get("runtime_url") if kind == "running" else None
    runtime_token = details.get("runtime_token") if kind == "running" else None
    error = details.get("error") if kind == "failed" else None
    safe_details = {key: value for key, value in details.items() if key != "runtime_token"}
    with _connect() as conn:
        if idempotency_key:
            existing = conn.execute(
                """
                SELECT 1 FROM gpu_job_events
                 WHERE job_id = %s AND idempotency_key = %s
                """,
                (job_id, idempotency_key),
            ).fetchone()
            if existing:
                return get_job(job_id, conn)
        conn.execute(
            """
            INSERT INTO gpu_job_events(
                job_id, worker_id, kind, idempotency_key, details
            )
            VALUES (%s, %s, %s, %s, %s::jsonb)
            """,
            (job_id, worker_id, kind, idempotency_key, json.dumps(safe_details)),
        )
        if not next_status:
            return get_job(job_id, conn)
        return conn.execute(
            """
            UPDATE gpu_jobs
               SET status = %s,
                   runtime_url = COALESCE(%s, runtime_url),
                   runtime_token = COALESCE(%s, runtime_token),
                   error = COALESCE(%s, error),
                   updated_at = now()
             WHERE id = %s AND worker_id = %s
         RETURNING *
            """,
            (
                next_status,
                runtime_url,
                runtime_token,
                error,
                job_id,
                worker_id,
            ),
        ).fetchone()


def get_job(job_id: str, conn=None) -> dict[str, Any] | None:
    if conn is not None:
        return conn.execute("SELECT * FROM gpu_jobs WHERE id = %s", (job_id,)).fetchone()
    with _connect() as own_conn:
        return get_job(job_id, own_conn)


async def get_job_async(job_id: str) -> dict[str, Any] | None:
    """Read a job through psycopg's cancellation-capable async transport."""
    conn = await psycopg.AsyncConnection.connect(
        config.DATABASE_URL,
        row_factory=dict_row,
    )
    async with conn:
        result = await conn.execute(
            "SELECT * FROM gpu_jobs WHERE id = %s",
            (job_id,),
        )
        return await result.fetchone()


def get_repo_job(owner: str, repo: str) -> dict[str, Any] | None:
    owner, repo = owner.lower(), repo.lower()
    with _connect() as conn:
        return conn.execute(
            """
            SELECT * FROM gpu_jobs
             WHERE lower(owner) = %s AND lower(repo) = %s
          ORDER BY created_at DESC LIMIT 1
            """,
            (owner, repo),
        ).fetchone()


def list_repo_jobs() -> list[dict[str, Any]]:
    """Return the newest visible remote job for each repository."""
    with _connect() as conn:
        return conn.execute(
            """
            SELECT DISTINCT ON (lower(owner), lower(repo))
                   lower(owner) AS owner, lower(repo) AS repo,
                   status, worker_id, error, updated_at
              FROM gpu_jobs
             WHERE status NOT IN ('completed', 'cancelled')
          ORDER BY lower(owner), lower(repo), created_at DESC
            """
        ).fetchall()


def cancel_repo_job(owner: str, repo: str) -> dict[str, Any] | None:
    owner, repo = owner.lower(), repo.lower()
    with _connect() as conn:
        return conn.execute(
            """
            UPDATE gpu_jobs
               SET status = CASE
                   WHEN status IN ('queued', 'unavailable') THEN 'cancelled'
                   ELSE 'cancel_requested'
               END,
                   updated_at = now()
             WHERE id = (
                 SELECT id FROM gpu_jobs
                  WHERE lower(owner) = %s AND lower(repo) = %s
                    AND status NOT IN ('completed', 'failed', 'cancelled')
               ORDER BY created_at DESC LIMIT 1
             )
         RETURNING *
            """,
            (owner, repo),
        ).fetchone()


def runtime_route(owner: str, repo: str) -> dict[str, Any] | None:
    job = get_repo_job(owner, repo)
    if job and job["status"] == "running" and job["runtime_url"]:
        return {
            "url": job["runtime_url"],
            "token": job["runtime_token"],
            "job_id": str(job["id"]),
        }
    return None


def list_workers() -> list[dict[str, Any]]:
    with _connect() as conn:
        return conn.execute(
            """
            SELECT id, name, capabilities, status, max_jobs, running_jobs,
                   last_seen_at, revoked_at, created_at
              FROM gpu_workers ORDER BY created_at
            """
        ).fetchall()


def revoke_worker(worker_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        worker = conn.execute(
            """
            UPDATE gpu_workers
               SET revoked_at = now(), status = 'revoked'
             WHERE id = %s AND revoked_at IS NULL
         RETURNING id, name, status, revoked_at
            """,
            (worker_id,),
        ).fetchone()
        if worker:
            conn.execute(
                """
                UPDATE gpu_jobs SET status = 'unavailable', updated_at = now()
                 WHERE worker_id = %s
                   AND status IN ('leased', 'building', 'running', 'stopping')
                """,
                (worker_id,),
            )
        return worker


def reap_expired() -> dict[str, int]:
    stale_before = datetime.now(timezone.utc) - timedelta(seconds=config.GPU_WORKER_STALE_SECONDS)
    with _connect() as conn:
        workers = conn.execute(
            """
            UPDATE gpu_workers SET status = 'offline'
             WHERE revoked_at IS NULL AND last_seen_at < %s AND status <> 'offline'
            """,
            (stale_before,),
        ).rowcount
        jobs = conn.execute(
            """
            UPDATE gpu_jobs
               SET status = 'queued', worker_id = NULL,
                   lease_expires_at = NULL, runtime_url = NULL,
                   runtime_token = NULL, updated_at = now()
             WHERE status IN ('leased', 'building')
               AND lease_expires_at < now()
            """
        ).rowcount
        unavailable = conn.execute(
            """
            UPDATE gpu_jobs SET status = 'unavailable', updated_at = now()
             WHERE status = 'running'
               AND worker_id IN (
                   SELECT id FROM gpu_workers WHERE status = 'offline'
               )
            """
        ).rowcount
    return {"workers_offline": workers, "jobs_requeued": jobs, "runtimes_unavailable": unavailable}
