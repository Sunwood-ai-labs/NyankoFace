"""Persistent, authenticated interaction metrics backed by PostgreSQL."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg
from psycopg.rows import dict_row

import config


DEFAULT_AGENTS = (
    ("luna-scout", "Luna Scout", "🌙", "Discovery agent for useful local apps"),
    ("patch-orbit", "Patch Orbit", "🛰️", "Builder agent testing developer tools"),
    ("mikan-reviewer", "Mikan Reviewer", "🍊", "Curator agent reviewing friendly utilities"),
)

METRIC_EVENT_OUTCOMES = frozenset({
    "success",
    "failed",
    "cancelled",
    "denied",
    "bot",
    "health_check",
})
METRIC_BUCKETS = frozenset({"day", "week", "month"})
DOWNLOAD_SOURCES = ("raw", "lfs", "automation")
ACTOR_KINDS = frozenset({"anonymous", "authenticated", "agent", "system"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _legacy_like_idempotency_key(agent_id: int, owner: str, repo: str, created_at: datetime) -> str:
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    created_at_us = (created_at.astimezone(timezone.utc) - epoch) // timedelta(microseconds=1)
    return f"legacy:like:{agent_id}:{owner}/{repo}:{created_at_us}"


def _connect() -> psycopg.Connection:
    return psycopg.connect(config.DATABASE_URL, row_factory=dict_row)


def database_ready() -> bool:
    with _connect() as db:
        return db.execute("SELECT 1 AS ok").fetchone()["ok"] == 1


def initialize() -> None:
    Path(config.AGENT_DATA_DIR).mkdir(parents=True, exist_ok=True)
    with _connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS agents (
                id BIGSERIAL PRIMARY KEY,
                slug TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                emoji TEXT NOT NULL,
                bio TEXT NOT NULL,
                api_key_hash TEXT NOT NULL UNIQUE,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS repo_views (
                id BIGSERIAL PRIMARY KEY,
                agent_id BIGINT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                owner TEXT NOT NULL,
                repo TEXT NOT NULL,
                idempotency_key TEXT,
                created_at TIMESTAMPTZ NOT NULL,
                UNIQUE(agent_id, idempotency_key)
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS repo_views_target ON repo_views(owner, repo)")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS browser_views (
                id BIGSERIAL PRIMARY KEY,
                owner TEXT NOT NULL,
                repo TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS browser_views_target ON browser_views(owner, repo)")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_views (
                id BIGSERIAL PRIMARY KEY,
                owner TEXT NOT NULL,
                repo TEXT NOT NULL,
                slug TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS knowledge_views_target ON knowledge_views(owner, repo, slug)"
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS repo_likes (
                agent_id BIGINT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                owner TEXT NOT NULL,
                repo TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY(agent_id, owner, repo)
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS repo_likes_target ON repo_likes(owner, repo)")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS metric_events (
                id BIGSERIAL PRIMARY KEY,
                event_type TEXT NOT NULL CHECK (event_type IN ('view', 'download', 'like')),
                source TEXT NOT NULL CHECK (source IN ('agent', 'browser', 'raw', 'lfs', 'automation')),
                owner TEXT NOT NULL,
                repo TEXT NOT NULL,
                artifact_path TEXT,
                actor_kind TEXT NOT NULL CHECK (actor_kind IN ('anonymous', 'authenticated', 'agent', 'system')),
                actor_id BIGINT REFERENCES agents(id) ON DELETE SET NULL,
                outcome TEXT NOT NULL CHECK (outcome IN ('success', 'failed', 'cancelled', 'denied', 'bot', 'health_check')),
                value INTEGER NOT NULL,
                idempotency_key TEXT,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS metric_events_target_time "
            "ON metric_events(owner, repo, created_at)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS metric_events_type_source "
            "ON metric_events(owner, repo, event_type, source, created_at)"
        )
        db.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS metric_events_idempotency
            ON metric_events(
                event_type,
                source,
                owner,
                repo,
                COALESCE(artifact_path, ''),
                actor_kind,
                idempotency_key
            )
            WHERE idempotency_key IS NOT NULL
            """
        )

    credentials_path = Path(config.AGENT_CREDENTIALS_FILE)
    existing_credentials: dict[str, str] = {}
    if credentials_path.exists():
        try:
            existing_credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing_credentials = {}

    credentials = dict(existing_credentials)
    with _connect() as db:
        for slug, display_name, emoji, bio in DEFAULT_AGENTS:
            row = db.execute("SELECT id FROM agents WHERE slug = %s", (slug,)).fetchone()
            if row:
                continue
            api_key = f"of_agent_{secrets.token_urlsafe(32)}"
            db.execute(
                "INSERT INTO agents(slug, display_name, emoji, bio, api_key_hash, created_at) "
                "VALUES(%s,%s,%s,%s,%s,%s)",
                (slug, display_name, emoji, bio, _hash_key(api_key), _now()),
            )
            credentials[slug] = api_key

    if credentials != existing_credentials:
        credentials_path.write_text(json.dumps(credentials, indent=2), encoding="utf-8")
        try:
            os.chmod(credentials_path, 0o600)
        except OSError:
            pass

    _backfill_metric_events()


def _backfill_metric_events() -> None:
    """Import the legacy counters into the canonical event ledger once.

    The old tables remain for compatibility with existing callers and seed data,
    but all new reads use ``metric_events``. Stable legacy keys make this safe to
    run on every service restart and preserve the original event timestamps.
    """
    with _connect() as db:
        db.execute(
            """
            INSERT INTO metric_events(
                event_type, source, owner, repo, actor_kind, actor_id,
                outcome, value, idempotency_key, created_at
            )
            SELECT 'view', 'agent', owner, repo, 'agent', agent_id,
                   'success', 1, 'legacy:repo-view:' || agent_id || ':' || id, created_at
            FROM repo_views
            ON CONFLICT DO NOTHING
            """
        )
        db.execute(
            """
            INSERT INTO metric_events(
                event_type, source, owner, repo, actor_kind,
                outcome, value, idempotency_key, created_at
            )
            SELECT 'view', 'browser', owner, repo, 'anonymous',
                   'success', 1, 'legacy:browser-view:' || id, created_at
            FROM browser_views
            ON CONFLICT DO NOTHING
            """
        )
        db.execute(
            """
            INSERT INTO metric_events(
                event_type, source, owner, repo, actor_kind, actor_id,
                outcome, value, idempotency_key, created_at
            )
            SELECT 'like', 'agent', owner, repo, 'agent', agent_id,
                   'success', 1,
                   'legacy:like:' || agent_id || ':' || owner || '/' || repo || ':'
                     || (EXTRACT(EPOCH FROM created_at) * 1000000)::BIGINT,
                   created_at
            FROM repo_likes
            ON CONFLICT DO NOTHING
            """
        )


def _insert_metric_event(
    db: psycopg.Connection,
    *,
    event_type: str,
    source: str,
    owner: str,
    repo: str,
    actor_kind: str,
    outcome: str,
    value: int,
    created_at: datetime | None = None,
    actor_id: int | None = None,
    artifact_path: str | None = None,
    idempotency_key: str | None = None,
) -> bool:
    if event_type not in {"view", "download", "like"}:
        raise ValueError("unsupported metric event type")
    if source not in {"agent", "browser", *DOWNLOAD_SOURCES}:
        raise ValueError("unsupported metric event source")
    if actor_kind not in ACTOR_KINDS:
        raise ValueError("unsupported metric actor kind")
    if outcome not in METRIC_EVENT_OUTCOMES:
        raise ValueError("unsupported metric event outcome")
    row = db.execute(
        """
        INSERT INTO metric_events(
            event_type, source, owner, repo, artifact_path, actor_kind,
            actor_id, outcome, value, idempotency_key, created_at
        )
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT DO NOTHING
        RETURNING id
        """,
        (
            event_type,
            source,
            owner,
            repo,
            artifact_path,
            actor_kind,
            actor_id,
            outcome,
            value,
            idempotency_key,
            created_at or _now(),
        ),
    ).fetchone()
    return bool(row)


def list_agents() -> list[dict[str, Any]]:
    with _connect() as db:
        rows = db.execute(
            """
            SELECT a.slug, a.display_name, a.emoji, a.bio,
                   COUNT(DISTINCT v.id) AS views,
                   COUNT(DISTINCT l.owner || '/' || l.repo) AS likes
            FROM agents a
            LEFT JOIN repo_views v ON v.agent_id = a.id
            LEFT JOIN repo_likes l ON l.agent_id = a.id
            GROUP BY a.id ORDER BY a.id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def authenticate(api_key: str | None) -> dict[str, Any] | None:
    if not api_key:
        return None
    candidate = _hash_key(api_key)
    with _connect() as db:
        rows = db.execute("SELECT * FROM agents").fetchall()
    for row in rows:
        if hmac.compare_digest(row["api_key_hash"], candidate):
            return dict(row)
    return None


def metrics(owner: str, repo: str) -> dict[str, Any]:
    with _connect() as db:
        row = db.execute(
            """
            SELECT
                COALESCE(SUM(value) FILTER (
                    WHERE event_type = 'view' AND source = 'agent' AND outcome = 'success'
                ), 0) AS agent_views,
                COALESCE(SUM(value) FILTER (
                    WHERE event_type = 'view' AND source = 'browser' AND outcome = 'success'
                ), 0) AS browser_views,
                COALESCE(SUM(value) FILTER (
                    WHERE event_type = 'download' AND outcome = 'success'
                ), 0) AS downloads,
                COALESCE(SUM(value) FILTER (
                    WHERE event_type = 'like' AND outcome = 'success'
                ), 0) AS likes,
                COALESCE(SUM(value) FILTER (
                    WHERE event_type = 'download' AND source = 'raw' AND outcome = 'success'
                ), 0) AS raw_downloads,
                COALESCE(SUM(value) FILTER (
                    WHERE event_type = 'download' AND source = 'lfs' AND outcome = 'success'
                ), 0) AS lfs_downloads,
                COALESCE(SUM(value) FILTER (
                    WHERE event_type = 'download' AND source = 'automation' AND outcome = 'success'
                ), 0) AS automation_downloads,
                MAX(created_at) FILTER (WHERE outcome = 'success') AS last_event_at
            FROM metric_events
            WHERE owner = %s AND repo = %s
            """,
            (owner, repo),
        ).fetchone()
        recent = db.execute(
            """
            SELECT a.slug, a.display_name, a.emoji, MAX(e.created_at) AS acted_at
            FROM metric_events e
            JOIN agents a ON a.id = e.actor_id
            WHERE e.owner = %s AND e.repo = %s
              AND e.actor_kind = 'agent'
              AND e.outcome = 'success'
              AND e.event_type IN ('view', 'like')
              AND e.value > 0
            GROUP BY a.id ORDER BY acted_at DESC LIMIT 3
            """,
            (owner, repo),
        ).fetchall()
    agent_views = int(row["agent_views"] or 0)
    browser_views = int(row["browser_views"] or 0)
    downloads = int(row["downloads"] or 0)
    likes = max(0, int(row["likes"] or 0))
    return {
        "owner": owner,
        "repo": repo,
        "views": agent_views + browser_views,
        "agent_views": agent_views,
        "browser_views": browser_views,
        "likes": likes,
        "downloads": downloads,
        "downloads_by_source": {
            "raw": int(row["raw_downloads"] or 0),
            "lfs": int(row["lfs_downloads"] or 0),
            "automation": int(row["automation_downloads"] or 0),
        },
        "recent_agents": [dict(row) for row in recent],
        "last_event_at": row["last_event_at"],
    }


def metrics_batch(repos: list[tuple[str, str]]) -> dict[str, dict[str, Any]]:
    unique_repos = list(dict.fromkeys(repos))
    result = {
        f"{owner}/{repo}": {
            "owner": owner,
            "repo": repo,
            "views": 0,
            "agent_views": 0,
            "browser_views": 0,
            "likes": 0,
            "downloads": 0,
            "downloads_by_source": {source: 0 for source in DOWNLOAD_SOURCES},
            "recent_agents": [],
        }
        for owner, repo in unique_repos
    }
    if not unique_repos:
        return result

    targets = [f"{owner}/{repo}" for owner, repo in unique_repos]
    with _connect() as db:
        event_rows = db.execute(
            """
            SELECT owner, repo, event_type, source, COALESCE(SUM(value), 0) AS value
            FROM metric_events
            WHERE owner || '/' || repo = ANY(%s)
              AND outcome = 'success'
            GROUP BY owner, repo, event_type, source
            """,
            (targets,),
        ).fetchall()

    for row in event_rows:
        item = result[f"{row['owner']}/{row['repo']}"]
        value = int(row["value"] or 0)
        if row["event_type"] == "view":
            item["views"] += value
            item["agent_views" if row["source"] == "agent" else "browser_views"] += value
        elif row["event_type"] == "download":
            item["downloads"] += value
            if row["source"] in DOWNLOAD_SOURCES:
                item["downloads_by_source"][row["source"]] += value
        elif row["event_type"] == "like":
            item["likes"] = max(0, item["likes"] + value)
    return result


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _bucket_start(value: datetime, bucket: str, zone: ZoneInfo) -> datetime:
    local = value.astimezone(zone)
    if bucket == "day":
        return local.replace(hour=0, minute=0, second=0, microsecond=0)
    if bucket == "week":
        start = local - timedelta(days=local.weekday())
        return start.replace(hour=0, minute=0, second=0, microsecond=0)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_bucket(value: datetime, bucket: str) -> datetime:
    if bucket == "day":
        return value + timedelta(days=1)
    if bucket == "week":
        return value + timedelta(days=7)
    if value.month == 12:
        return value.replace(year=value.year + 1, month=1, day=1)
    return value.replace(month=value.month + 1, day=1)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def timeseries(
    owner: str,
    repo: str,
    from_at: datetime,
    to_at: datetime,
    bucket: str = "day",
    timezone_name: str = "UTC",
) -> dict[str, Any]:
    if bucket not in METRIC_BUCKETS:
        raise ValueError("bucket must be day, week, or month")
    from_utc = _as_utc(from_at)
    to_utc = _as_utc(to_at)
    if from_utc >= to_utc:
        raise ValueError("from must be before to")
    if (to_utc - from_utc) > timedelta(days=366):
        raise ValueError("metric windows are limited to 366 days")
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone must be a valid IANA timezone") from exc

    first_bucket = _bucket_start(from_utc, bucket, zone)
    last_local = to_utc.astimezone(zone)
    bucket_starts: list[datetime] = []
    cursor = first_bucket
    while cursor < last_local and len(bucket_starts) <= 400:
        bucket_starts.append(cursor)
        cursor = _next_bucket(cursor, bucket)

    bucket_expression = "date_trunc(%s, created_at AT TIME ZONE %s) AT TIME ZONE %s"
    with _connect() as db:
        rows = db.execute(
            f"""
            SELECT
                {bucket_expression} AS bucket_start,
                COALESCE(SUM(value) FILTER (
                    WHERE event_type = 'view' AND outcome = 'success'
                ), 0) AS views,
                COALESCE(SUM(value) FILTER (
                    WHERE event_type = 'download' AND outcome = 'success'
                ), 0) AS downloads,
                COALESCE(SUM(value) FILTER (
                    WHERE event_type = 'like' AND outcome = 'success'
                ), 0) AS likes_delta,
                COALESCE(SUM(value) FILTER (
                    WHERE event_type = 'download' AND source = 'raw' AND outcome = 'success'
                ), 0) AS raw_downloads,
                COALESCE(SUM(value) FILTER (
                    WHERE event_type = 'download' AND source = 'lfs' AND outcome = 'success'
                ), 0) AS lfs_downloads,
                COALESCE(SUM(value) FILTER (
                    WHERE event_type = 'download' AND source = 'automation' AND outcome = 'success'
                ), 0) AS automation_downloads,
                COUNT(*) FILTER (WHERE outcome = 'success' AND value != 0) AS successful_events,
                MAX(created_at) FILTER (WHERE outcome = 'success') AS updated_at
            FROM metric_events
            WHERE owner = %s AND repo = %s
              AND created_at >= %s AND created_at < %s
            GROUP BY 1
            ORDER BY 1
            """,
            (bucket, timezone_name, timezone_name, owner, repo, from_utc, to_utc),
        ).fetchall()
        prior_like = db.execute(
            """
            SELECT COALESCE(SUM(value), 0) AS likes
            FROM metric_events
            WHERE owner = %s AND repo = %s
              AND event_type = 'like' AND outcome = 'success'
              AND created_at < %s
            """,
            (owner, repo, from_utc),
        ).fetchone()["likes"]

    by_bucket: dict[str, dict[str, Any]] = {}
    last_event_at: datetime | None = None
    for row in rows:
        key = row["bucket_start"].astimezone(zone).isoformat()
        by_bucket[key] = {
            "views": int(row["views"] or 0),
            "downloads": int(row["downloads"] or 0),
            "likes_delta": int(row["likes_delta"] or 0),
            "downloads_by_source": {
                "raw": int(row["raw_downloads"] or 0),
                "lfs": int(row["lfs_downloads"] or 0),
                "automation": int(row["automation_downloads"] or 0),
            },
            "successful_events": int(row["successful_events"] or 0),
        }
        if row["updated_at"] and (last_event_at is None or row["updated_at"] > last_event_at):
            last_event_at = row["updated_at"]

    likes_total = int(prior_like or 0)
    series: list[dict[str, Any]] = []
    total_views = 0
    total_downloads = 0
    total_downloads_by_source = {source: 0 for source in DOWNLOAD_SOURCES}
    has_data = likes_total != 0
    for start in bucket_starts:
        values = by_bucket.get(start.isoformat(), {
            "views": 0,
            "downloads": 0,
            "likes_delta": 0,
            "downloads_by_source": {source: 0 for source in DOWNLOAD_SOURCES},
            "successful_events": 0,
        })
        likes_total = max(0, likes_total + values["likes_delta"])
        total_views += values["views"]
        total_downloads += values["downloads"]
        for source in DOWNLOAD_SOURCES:
            total_downloads_by_source[source] += values["downloads_by_source"][source]
        has_data = has_data or values["successful_events"] > 0
        series.append({
            "bucket_start": start.isoformat(),
            "views": values["views"],
            "downloads": values["downloads"],
            "likes": likes_total,
            "likes_delta": values["likes_delta"],
            "downloads_by_source": values["downloads_by_source"],
        })

    return {
        "owner": owner,
        "repo": repo,
        "from": from_utc.isoformat(),
        "to": to_utc.isoformat(),
        "bucket": bucket,
        "timezone": timezone_name,
        "data_state": "data" if has_data else "no_data",
        "series": series,
        "totals": {
            "views": total_views,
            "downloads": total_downloads,
            "likes": likes_total,
            "downloads_by_source": total_downloads_by_source,
        },
        "updated_at": _iso(last_event_at),
        "generated_at": _iso(_now()),
        "definitions": {
            "window": "[from, to)",
            "views": "successful browser or agent detail-page events",
            "downloads": "completed NyankoFace-proxied raw, LFS, or Automation responses",
            "likes": "active agent likes reconstructed from successful +/-1 transitions",
            "failed_events": "recorded for audit but excluded from measured totals",
            "privacy": "no IP address, token, or secret is stored",
        },
    }


def record_view(agent_id: int, owner: str, repo: str, idempotency_key: str | None) -> tuple[bool, dict[str, Any]]:
    with _connect() as db:
        row = db.execute(
            """INSERT INTO repo_views(agent_id, owner, repo, idempotency_key, created_at)
               VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id, created_at""",
            (agent_id, owner, repo, idempotency_key, _now()),
        ).fetchone()
        created = bool(row)
        if created:
            _insert_metric_event(
                db,
                event_type="view",
                source="agent",
                owner=owner,
                repo=repo,
                actor_kind="agent",
                actor_id=agent_id,
                outcome="success",
                value=1,
                idempotency_key=f"legacy:repo-view:{agent_id}:{row['id']}",
                created_at=row["created_at"],
            )
    return created, metrics(owner, repo)


def record_browser_view(
    owner: str,
    repo: str,
    idempotency_key: str,
    actor_kind: str = "anonymous",
) -> tuple[bool, dict[str, Any]]:
    with _connect() as db:
        row = db.execute(
            """INSERT INTO browser_views(owner, repo, idempotency_key, created_at)
               VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id, created_at""",
            (owner, repo, idempotency_key, _now()),
        ).fetchone()
        created = bool(row)
        if created:
            _insert_metric_event(
                db,
                event_type="view",
                source="browser",
                owner=owner,
                repo=repo,
                actor_kind=actor_kind,
                outcome="success",
                value=1,
                idempotency_key=f"legacy:browser-view:{row['id']}",
                created_at=row["created_at"],
            )
    return created, metrics(owner, repo)


def record_download(
    owner: str,
    repo: str,
    source: str,
    artifact_path: str | None,
    idempotency_key: str,
    outcome: str = "success",
    actor_kind: str = "anonymous",
) -> tuple[bool, dict[str, Any]]:
    if source not in DOWNLOAD_SOURCES:
        raise ValueError("unsupported download source")
    if outcome not in METRIC_EVENT_OUTCOMES:
        raise ValueError("unsupported download outcome")
    with _connect() as db:
        created = _insert_metric_event(
            db,
            event_type="download",
            source=source,
            owner=owner,
            repo=repo,
            actor_kind=actor_kind,
            outcome=outcome,
            value=1 if outcome == "success" else 0,
            artifact_path=artifact_path,
            idempotency_key=idempotency_key,
        )
    return created, metrics(owner, repo)


def knowledge_metrics(owner: str, repo: str, slug: str) -> dict[str, Any]:
    with _connect() as db:
        views = db.execute(
            """SELECT COUNT(*) AS count FROM knowledge_views
               WHERE owner = %s AND repo = %s AND slug = %s""",
            (owner, repo, slug),
        ).fetchone()["count"]
    return {"owner": owner, "repo": repo, "slug": slug, "views": views}


def knowledge_metrics_batch(targets: list[tuple[str, str, str]]) -> dict[str, dict[str, Any]]:
    unique_targets = list(dict.fromkeys(targets))
    result = {
        f"{owner}/{repo}/{slug}": {
            "owner": owner,
            "repo": repo,
            "slug": slug,
            "views": 0,
        }
        for owner, repo, slug in unique_targets
    }
    if not unique_targets:
        return result

    keys = [f"{owner}/{repo}/{slug}" for owner, repo, slug in unique_targets]
    with _connect() as db:
        rows = db.execute(
            """SELECT owner, repo, slug, COUNT(*) AS count FROM knowledge_views
               WHERE owner || '/' || repo || '/' || slug = ANY(%s)
               GROUP BY owner, repo, slug""",
            (keys,),
        ).fetchall()
    for row in rows:
        result[f"{row['owner']}/{row['repo']}/{row['slug']}"]["views"] = row["count"]
    return result


def record_knowledge_view(
    owner: str, repo: str, slug: str, idempotency_key: str
) -> tuple[bool, dict[str, Any]]:
    with _connect() as db:
        row = db.execute(
            """INSERT INTO knowledge_views(owner, repo, slug, idempotency_key, created_at)
               VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id""",
            (owner, repo, slug, idempotency_key, _now()),
        ).fetchone()
    return bool(row), knowledge_metrics(owner, repo, slug)


def set_like(agent_id: int, owner: str, repo: str, liked: bool) -> tuple[bool, dict[str, Any]]:
    with _connect() as db:
        created_at: datetime | None = None
        if liked:
            like_row = db.execute(
                """INSERT INTO repo_likes(agent_id, owner, repo, created_at)
                   VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING created_at""",
                (agent_id, owner, repo, _now()),
            ).fetchone()
            changed = bool(like_row)
            created_at = like_row["created_at"] if like_row else None
        else:
            changed = db.execute(
                "DELETE FROM repo_likes WHERE agent_id = %s AND owner = %s AND repo = %s",
                (agent_id, owner, repo),
            ).rowcount > 0
        if changed:
            _insert_metric_event(
                db,
                event_type="like",
                source="agent",
                owner=owner,
                repo=repo,
                actor_kind="agent",
                actor_id=agent_id,
                outcome="success",
                value=1 if liked else -1,
                created_at=created_at,
                idempotency_key=(
                    _legacy_like_idempotency_key(agent_id, owner, repo, created_at)
                    if liked and created_at is not None
                    else None
                ),
            )
    return changed, metrics(owner, repo)
