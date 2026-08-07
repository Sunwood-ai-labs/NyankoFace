from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread
from collections.abc import Callable
from typing import Any

import psycopg
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row

from agents import (
    AGENTS,
    BY_USERNAME,
    assign_agent,
    classify_automatic_issue,
    choose_agent,
    delegation_comment,
    is_ui_task,
    maintainer_instruction,
    mentions_maintainer,
)
from autolabel import LabelCandidate, classify_labels
from config import Settings
from forgejo import ForgejoClient
from worker import IssueTask, MaintenanceWorker


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("nyankoface-maintenance")
settings = Settings.load()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.workspace_dir.mkdir(parents=True, exist_ok=True)
database_url = settings.database_url
database_lock = Lock()
executor = ThreadPoolExecutor(max_workers=settings.max_workers, thread_name_prefix="claude-goal-maintenance")
worker = MaintenanceWorker(settings)
humanless_stop = Event()
humanless_thread: Thread | None = None
humanless_scan_lock = Lock()
humanless_topic_cache: dict[str, tuple[str, set[str]]] = {}


@asynccontextmanager
async def app_lifespan(_app: FastAPI):
    start_humanless_scheduler()
    try:
        yield
    finally:
        stop_humanless_scheduler()


app = FastAPI(
    title="NyankoFace Claude Goal Maintenance Agent",
    version="3.0.0",
    lifespan=app_lifespan,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_database() -> psycopg.Connection:
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    return psycopg.connect(database_url, row_factory=dict_row)


def initialize_database() -> None:
    with connect_database() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                delivery_id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                repo TEXT NOT NULL,
                issue_number INTEGER NOT NULL,
                status TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                pull_url TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                agent TEXT NOT NULL DEFAULT 'coding-agent',
                UNIQUE(owner, repo, issue_number)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS release_audits (
                owner TEXT NOT NULL,
                repo TEXT NOT NULL,
                branch TEXT NOT NULL,
                commit_sha TEXT NOT NULL,
                agent TEXT NOT NULL,
                issue_number INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY(owner, repo, branch, commit_sha, agent)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS humanless_cycles (
                owner TEXT NOT NULL,
                repo TEXT NOT NULL,
                cycle_number INTEGER NOT NULL,
                phase TEXT NOT NULL,
                agent TEXT NOT NULL,
                issue_number INTEGER NOT NULL DEFAULT 0,
                attempt INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                pull_url TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                next_run_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY(owner, repo, cycle_number)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS label_audits (
                delivery_id TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                repo TEXT NOT NULL,
                subject_number INTEGER NOT NULL,
                subject_kind TEXT NOT NULL,
                action TEXT NOT NULL,
                dry_run BOOLEAN NOT NULL,
                candidates TEXT NOT NULL DEFAULT '[]',
                applied TEXT NOT NULL DEFAULT '[]',
                skipped TEXT NOT NULL DEFAULT '[]',
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        columns = {
            row["column_name"]
            for row in db.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='jobs'"
            )
        }
        if "agent" not in columns:
            db.execute("ALTER TABLE jobs ADD COLUMN agent TEXT NOT NULL DEFAULT 'coding-agent'")
        db.execute(
            "UPDATE jobs SET status='interrupted', detail='Service restarted before the Claude Code /goal run completed', "
            "updated_at=%s WHERE status IN ('queued', 'running')",
            (utc_now(),),
        )

if database_url:
    initialize_database()


def update_job(delivery_id: str, status: str, detail: str = "", pull_url: str = "") -> None:
    with database_lock, connect_database() as db:
        db.execute(
            "UPDATE jobs SET status=%s, detail=%s, pull_url=%s, updated_at=%s WHERE delivery_id=%s",
            (status, detail[:4000], pull_url, utc_now(), delivery_id),
        )


def record_label_audit(
    *,
    delivery_id: str,
    owner: str,
    repo: str,
    subject_number: int,
    subject_kind: str,
    action: str,
    candidates: list[dict[str, Any]],
    applied: list[str],
    skipped: list[dict[str, str]],
) -> None:
    with database_lock, connect_database() as db:
        db.execute(
            "INSERT INTO label_audits("
            "delivery_id, owner, repo, subject_number, subject_kind, action, dry_run, "
            "candidates, applied, skipped, created_at"
            ") VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT(delivery_id) DO NOTHING",
            (
                delivery_id,
                owner,
                repo,
                subject_number,
                subject_kind,
                action,
                settings.auto_label_dry_run,
                json.dumps(candidates, ensure_ascii=False),
                json.dumps(applied, ensure_ascii=False),
                json.dumps(skipped, ensure_ascii=False),
                utc_now(),
            ),
        )


def _candidate_payload(candidate: LabelCandidate) -> dict[str, Any]:
    return {
        "name": candidate.name,
        "confidence": candidate.confidence,
        "reason": candidate.reason,
    }


def process_auto_labels(
    *,
    event: str,
    payload: dict[str, Any],
    delivery_id: str,
) -> dict[str, Any]:
    if not settings.auto_label_enabled:
        return {"enabled": False, "applied": [], "dry_run": settings.auto_label_dry_run}

    allowed_actions = {
        "issues": {"opened", "edited", "reopened"},
        "issue": {"opened", "edited", "reopened"},
        "pull_request": {"opened", "edited", "reopened", "synchronize"},
    }
    action = str(payload.get("action") or "")
    if action not in allowed_actions.get(event, set()):
        return {
            "enabled": True,
            "ignored": True,
            "reason": "action ignored",
            "applied": [],
            "dry_run": settings.auto_label_dry_run,
        }

    repository = payload.get("repository") or {}
    owner = str((repository.get("owner") or {}).get("login") or "")
    repo = str(repository.get("name") or "")
    if owner != settings.allowed_owner or not repo:
        return {
            "enabled": True,
            "ignored": True,
            "reason": "repository is outside the allowed owner",
            "applied": [],
            "dry_run": settings.auto_label_dry_run,
        }

    subject_kind = "pull_request" if event == "pull_request" else "issue"
    subject = payload.get(subject_kind) or {}
    number = int(subject.get("number") or payload.get("number") or 0)
    if number <= 0:
        return {
            "enabled": True,
            "ignored": True,
            "reason": "subject number missing",
            "applied": [],
            "dry_run": settings.auto_label_dry_run,
        }

    client = ForgejoClient(settings)
    try:
        changed_files = (
            client.pull_changed_files(owner, repo, number)
            if subject_kind == "pull_request"
            else []
        )
        decision = classify_labels(
            str(subject.get("title") or ""),
            str(subject.get("body") or ""),
            changed_files=changed_files,
        )
        candidates = list(decision.above(settings.auto_label_confidence))
        available = client.repository_labels(owner, repo)
        existing = {
            str(label.get("name") or "").strip().lower()
            for label in subject.get("labels", [])
            if isinstance(label, dict)
        }
        allowed = set(settings.auto_label_allowed)
        selected: list[str] = []
        skipped: list[dict[str, str]] = []
        for candidate in candidates:
            if candidate.name not in allowed:
                skipped.append(
                    {"name": candidate.name, "reason": "設定allowlistの対象外"}
                )
            elif candidate.name not in available:
                skipped.append(
                    {"name": candidate.name, "reason": "リポジトリに存在しない"}
                )
            elif candidate.name in existing:
                skipped.append(
                    {"name": candidate.name, "reason": "既に付与済み"}
                )
            else:
                selected.append(candidate.name)

        applied = [] if settings.auto_label_dry_run else selected
        if applied:
            client.add_issue_labels(
                owner,
                repo,
                number,
                [available[name] for name in applied],
            )
    finally:
        client.close()

    record_label_audit(
        delivery_id=delivery_id,
        owner=owner,
        repo=repo,
        subject_number=number,
        subject_kind=subject_kind,
        action=action,
        candidates=[_candidate_payload(candidate) for candidate in candidates],
        applied=applied,
        skipped=skipped,
    )
    logger.info(
        "Auto-label %s/%s %s #%s candidates=%s applied=%s dry_run=%s",
        owner,
        repo,
        subject_kind,
        number,
        [candidate.name for candidate in candidates],
        applied,
        settings.auto_label_dry_run,
    )
    return {
        "enabled": True,
        "subject": subject_kind,
        "number": number,
        "candidates": [_candidate_payload(candidate) for candidate in candidates],
        "applied": applied,
        "would_apply": selected,
        "skipped": skipped,
        "dry_run": settings.auto_label_dry_run,
    }


def update_release_audit(task: IssueTask, status: str) -> None:
    if task.trigger_kind != "release":
        return
    with database_lock, connect_database() as db:
        db.execute(
            "UPDATE release_audits SET status=%s, issue_number=%s, updated_at=%s "
            "WHERE owner=%s AND repo=%s AND branch=%s AND commit_sha=%s AND agent=%s",
            (
                status,
                task.issue_number,
                utc_now(),
                task.owner,
                task.repo,
                task.default_branch,
                task.trigger_sha,
                AGENTS[task.agent_key].username,
            ),
        )


def update_humanless_cycle(
    task: IssueTask,
    status: str,
    *,
    detail: str = "",
    pull_url: str = "",
    next_minutes: int | None = None,
) -> None:
    if task.trigger_kind != "humanless" or not task.humanless_cycle:
        return
    next_run = datetime.now(timezone.utc) + timedelta(
        minutes=next_minutes if next_minutes is not None else settings.humanless_interval_minutes
    )
    with database_lock, connect_database() as db:
        db.execute(
            "UPDATE humanless_cycles SET status=%s, attempt=%s, detail=%s, pull_url=%s, "
            "updated_at=%s, next_run_at=%s WHERE owner=%s AND repo=%s AND cycle_number=%s",
            (
                status,
                task.humanless_attempt,
                detail[:4000],
                pull_url,
                utc_now(),
                next_run,
                task.owner,
                task.repo,
                task.humanless_cycle,
            ),
        )


def touch_humanless_cycle(task: IssueTask) -> None:
    if task.trigger_kind != "humanless" or not task.humanless_cycle:
        return
    with database_lock, connect_database() as db:
        db.execute(
            "UPDATE humanless_cycles SET updated_at=%s "
            "WHERE owner=%s AND repo=%s AND cycle_number=%s "
            "AND status IN ('queued', 'running', 'retrying')",
            (utc_now(), task.owner, task.repo, task.humanless_cycle),
        )


def humanless_heartbeat(task: IssueTask, stop: Event) -> None:
    interval = max(30, min(60, settings.humanless_stale_seconds // 3))
    while not stop.wait(interval):
        try:
            touch_humanless_cycle(task)
        except Exception:
            logger.exception(
                "Could not renew humanless lease for %s/%s cycle %s",
                task.owner,
                task.repo,
                task.humanless_cycle,
            )


def process_job(delivery_id: str, task: IssueTask) -> None:
    profile = AGENTS[task.agent_key]
    heartbeat_stop = Event()
    heartbeat_thread: Thread | None = None
    update_job(delivery_id, "running", f"{profile.display_name} が Claude Code /goal を {settings.model} で実行中")
    update_release_audit(task, "running")
    update_humanless_cycle(task, "running")
    if task.trigger_kind == "humanless":
        heartbeat_thread = Thread(
            target=humanless_heartbeat,
            args=(task, heartbeat_stop),
            name=f"humanless-heartbeat-{task.owner}-{task.repo}-{task.humanless_cycle}",
            daemon=True,
        )
        heartbeat_thread.start()
    try:
        client = ForgejoClient(settings, settings.agent_token_file(profile.username))
        try:
            client.react_to_issue(task.owner, task.repo, task.conversation_number, "eyes")
        finally:
            client.close()
        result = worker.run(task)
        if result.pull is None:
            update_job(delivery_id, "completed", result.summary)
            client = ForgejoClient(
                settings, settings.agent_token_file(profile.username)
            )
            try:
                client.react_to_issue(
                    task.owner, task.repo, task.conversation_number, "rocket"
                )
            finally:
                client.close()
            logger.info(
                "Completed read-only response for %s/%s issue #%s",
                task.owner,
                task.repo,
                task.issue_number,
            )
            return
        if result.review_verdict == "rejected":
            update_job(
                delivery_id,
                "changes_requested",
                "独立レビューで差し戻されました。PRは未マージです。",
                result.pull.url,
            )
            update_release_audit(task, "changes_requested")
            if (
                task.trigger_kind == "humanless"
                and task.humanless_attempt < settings.humanless_max_attempts
            ):
                retry_attempt = task.humanless_attempt + 1
                retry_task = replace(
                    task,
                    follow_up=True,
                    review_only=False,
                    instruction=(
                        "独立レビューで差し戻されました。最新PRとIssue上のreview-agentコメントを確認し、"
                        "指摘を一件ずつ解消して、関連検証を再実行してください。\n\n"
                        f"レビュー総評:\n{result.review_summary}"
                    ),
                    humanless_attempt=retry_attempt,
                )
                retry_delivery = hashlib.sha256(
                    f"humanless-retry:{task.owner}/{task.repo}:{task.humanless_cycle}:{retry_attempt}".encode()
                ).hexdigest()
                update_humanless_cycle(
                    retry_task,
                    "retrying",
                    detail=result.review_summary,
                    pull_url=result.pull.url,
                    next_minutes=0,
                )
                def announce_retry() -> None:
                    retry_client = ForgejoClient(settings)
                    try:
                        retry_client.comment_issue(
                            retry_task.owner,
                            retry_task.repo,
                            retry_task.conversation_number,
                            f"🔁 自動運用cycle {retry_task.humanless_cycle} を再試行します。"
                            f" attempt {retry_attempt}/{settings.humanless_max_attempts} で"
                            f" @{profile.username} が独立レビュー指摘を解消します。",
                        )
                    finally:
                        retry_client.close()

                enqueue(
                    retry_task,
                    retry_delivery,
                    allow_retry=True,
                    announce=announce_retry,
                )
                logger.info(
                    "Humanless retry queued for %s/%s cycle %s attempt %s",
                    task.owner, task.repo, task.humanless_cycle, retry_attempt,
                )
                return
            if (
                task.trigger_kind in {"issue-auto", "release"}
                and task.automation_attempt < settings.automatic_retry_max_attempts
            ):
                retry_attempt = task.automation_attempt + 1
                retry_task = replace(
                    task,
                    follow_up=True,
                    review_only=False,
                    instruction=(
                        "独立レビューで差し戻されました。最新PRとIssue上のreview-agentコメントを確認し、"
                        "指摘を一件ずつ解消して、関連検証を再実行してください。\n\n"
                        f"レビュー総評:\n{result.review_summary}"
                    ),
                    automation_attempt=retry_attempt,
                )
                retry_delivery = hashlib.sha256(
                    (
                        f"automatic-review-retry:{task.trigger_kind}:"
                        f"{task.owner}/{task.repo}:{task.issue_number}:"
                        f"{task.trigger_sha}:{retry_attempt}"
                    ).encode()
                ).hexdigest()
                update_release_audit(retry_task, "retrying")

                def announce_automatic_retry() -> None:
                    retry_client = ForgejoClient(settings)
                    try:
                        retry_client.comment_issue(
                            retry_task.owner,
                            retry_task.repo,
                            retry_task.conversation_number,
                            "🔁 独立レビュー指摘を自動修正します。\n\n"
                            f"@{profile.username} が attempt "
                            f"{retry_attempt}/{settings.automatic_retry_max_attempts} で"
                            "既存PRを更新し、SHA拘束レビューを再実行します。",
                        )
                    finally:
                        retry_client.close()

                enqueue(
                    retry_task,
                    retry_delivery,
                    allow_retry=True,
                    announce=announce_automatic_retry,
                )
                logger.info(
                    "Automatic review retry queued for %s/%s issue #%s attempt %s",
                    task.owner,
                    task.repo,
                    task.issue_number,
                    retry_attempt,
                )
                return
            update_humanless_cycle(
                task,
                "changes_requested",
                detail=result.review_summary,
                pull_url=result.pull.url,
                next_minutes=settings.humanless_retry_minutes,
            )
            logger.info(
                "Review requested changes for %s/%s issue #%s -> PR %s",
                task.owner, task.repo, task.issue_number, result.pull.url,
            )
            return
        update_job(
            delivery_id,
            "completed" if result.merged or not settings.auto_merge else "awaiting_merge",
            result.summary,
            result.pull.url,
        )
        update_release_audit(task, "completed")
        update_humanless_cycle(
            task,
            "completed" if result.merged else "awaiting_merge",
            detail=result.summary,
            pull_url=result.pull.url,
        )
        client = ForgejoClient(settings, settings.agent_token_file(profile.username))
        try:
            client.react_to_issue(task.owner, task.repo, task.conversation_number, "rocket")
        finally:
            client.close()
        logger.info(
            "Completed %s/%s issue #%s -> PR %s (review=%s, merged=%s)",
            task.owner, task.repo, task.issue_number, result.pull.url,
            result.review_verdict or "n/a", result.merged,
        )
    except Exception as exc:  # fail closed and retain an inspectable job record
        message = str(exc)[:2000]
        pull_url = ""
        if task.trigger_kind == "humanless":
            try:
                lookup_client = ForgejoClient(settings)
                try:
                    published = lookup_client.existing_pull(
                        task.owner, task.repo, task.branch
                    )
                    pull_url = published.url if published else ""
                finally:
                    lookup_client.close()
            except Exception:
                logger.exception("Could not recover published PR URL after failure")
        update_job(delivery_id, "failed", message)
        update_release_audit(task, "failed")
        update_humanless_cycle(
            task,
            "failed",
            detail=message,
            pull_url=pull_url,
            next_minutes=settings.humanless_retry_minutes,
        )
        if (
            task.trigger_kind in {"issue-auto", "release"}
            and task.automation_attempt < settings.automatic_retry_max_attempts
        ):
            retry_attempt = task.automation_attempt + 1
            retry_task = replace(
                task,
                follow_up=True,
                review_only=False,
                instruction=(
                    "前回の自動実行は成果物公開前に失敗しました。同じIssueと既存PRを確認し、"
                    "未完了の作業を安全に再実行してください。\n\n"
                    f"前回エラー:\n{message}"
                ),
                automation_attempt=retry_attempt,
            )
            retry_delivery = hashlib.sha256(
                (
                    f"automatic-execution-retry:{task.trigger_kind}:"
                    f"{task.owner}/{task.repo}:{task.issue_number}:"
                    f"{task.trigger_sha}:{retry_attempt}"
                ).encode()
            ).hexdigest()
            update_release_audit(retry_task, "retrying")

            def announce_execution_retry() -> None:
                retry_client = ForgejoClient(settings)
                try:
                    retry_client.comment_issue(
                        retry_task.owner,
                        retry_task.repo,
                        retry_task.conversation_number,
                        "🔁 自動実行を安全に再試行します。\n\n"
                        f"@{profile.username} が attempt "
                        f"{retry_attempt}/{settings.automatic_retry_max_attempts} で"
                        "同じIssueと既存PRから再開します。",
                    )
                finally:
                    retry_client.close()

            enqueue(
                retry_task,
                retry_delivery,
                allow_retry=True,
                announce=announce_execution_retry,
            )
            logger.info(
                "Automatic execution retry queued for %s/%s issue #%s attempt %s",
                task.owner,
                task.repo,
                task.issue_number,
                retry_attempt,
            )
            return
        logger.error("Maintenance failed for %s/%s#%s: %s", task.owner, task.repo, task.issue_number, message)
        try:
            client = ForgejoClient(settings)
            client.react_to_issue(task.owner, task.repo, task.conversation_number, "confused")
            client.comment_issue(
                task.owner,
                task.repo,
                task.conversation_number,
                "🤖 Claude Code `/goal` は変更をpushせずに停止しました。"
                "Goalの実行に失敗したか、生成されたworktreeが公開前検証を通過しませんでした。"
                "メンテナーはサービスのジョブログを確認できます。",
            )
            client.close()
        except Exception:
            logger.exception("Could not post failure status to issue")
    finally:
        heartbeat_stop.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=2)


def signature_valid(raw_body: bytes, supplied: str | None) -> bool:
    if not supplied:
        return False
    secret = settings.read_webhook_secret().encode()
    expected = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    candidate = supplied.removeprefix("sha256=")
    return hmac.compare_digest(expected, candidate)


def payload_to_task(
    payload: dict[str, Any], *, issue_override: dict[str, Any] | None = None,
    follow_up: bool = False, instruction: str = "", agent_key: str = "coding",
    reply_number: int | None = None, ui_evidence_required: bool = False,
    trigger_kind: str = "issue", response_only: bool = False,
) -> IssueTask:
    repository = payload.get("repository") or {}
    issue = issue_override or payload.get("issue") or {}
    owner = (repository.get("owner") or {}).get("login") or ""
    repo = repository.get("name") or ""
    if owner != settings.allowed_owner:
        raise HTTPException(status_code=403, detail="Repository owner is not allowed")
    if not repo or not issue.get("number"):
        raise HTTPException(status_code=400, detail="Webhook is missing repository or issue data")
    return IssueTask(
        owner=owner,
        repo=repo,
        issue_number=int(issue["number"]),
        title=str(issue.get("title") or "Maintenance request")[:500],
        body=str(issue.get("body") or "")[:20_000],
        default_branch=str(repository.get("default_branch") or "main"),
        issue_url=str(issue.get("html_url") or issue.get("url") or ""),
        follow_up=follow_up,
        instruction=instruction[:20_000],
        agent_key=agent_key,
        reply_number=reply_number,
        ui_evidence_required=ui_evidence_required,
        trigger_kind=trigger_kind,
        response_only=response_only,
    )


def follow_up_instruction(body: str) -> str | None:
    stripped = body.strip()
    if not stripped.startswith("/goal"):
        return None
    instruction = stripped.removeprefix("/goal").strip()
    return instruction or None


def is_release_branch(branch: str) -> bool:
    return branch == "release" or branch.startswith("release/") or branch.startswith("release-")


def release_agent_branch(agent_key: str, release_branch: str, commit_sha: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", release_branch.lower()).strip("-")[:42] or "release"
    return f"agent/release-{agent_key}-{slug}-{commit_sha[:10]}"


def release_audit_title(agent_key: str, release_branch: str, commit_sha: str) -> str:
    label = "Security" if agent_key == "security" else "Documentation"
    return f"[Release audit][{label}] {release_branch} @ {commit_sha[:10]}"


def release_audit_body(
    agent_key: str,
    release_branch: str,
    commit_sha: str,
    comparison_branch: str,
) -> str:
    profile = AGENTS[agent_key]
    checklist = (
        """
- 認証・認可、入力検証、秘密情報、権限境界、コマンド／HTML／SQL injectionを確認する
- 依存関係、コンテナ、CI、サプライチェーン、危険な既定値を確認する
- 問題を修正し、実行したsecurity checkと残余リスクを監査記録へ残す
"""
        if agent_key == "security"
        else
        """
- release差分に対してREADME、VitePress、設定例、運用・再構築手順が正しいか確認する
- 新機能、破壊的変更、移行方法、検証方法が利用者に分かるよう不足文書を更新する
- commit件名だけに依存せず、実際のdiff、変更ファイル、tag履歴からリリースノートを作成する
- `release/vX.Y.Z` または `release-X.Y.Z` からversionを導出し、`RELEASE_NOTES.md` と既存docs構成に
  合わせたversion別リリースページを作成または更新する
- 多言語docsがある場合は、既存localeすべてで同じ出荷内容を記録する
- リリースノートの各主張を実装ファイルまたは実行した検証へ結び付け、未実行のcheckを成功と書かない
- リンクとコマンドを検証し、実行したdocumentation checkを監査記録へ残す
"""
    )
    return f"""<!-- nyankoface-maintenance:release-audit -->
@{profile.username} `{release_branch}` のリリース準備監査を担当してください。

## トリガー

- release branch: `{release_branch}`
- pushed commit: `{commit_sha}`
- comparison branch: `{comparison_branch}`

## 必須作業

- `git diff origin/{comparison_branch}...HEAD` とcommit履歴を全体確認する
{checklist.strip()}
- 問題がない場合も `docs/release-audits/` に確認根拠をMarkdownで追加する
- 関連するtest、lint、buildを実行し、失敗を隠さない
- `{release_branch}` をbaseとするPRを作り、人が確認できる状態で停止する

担当: **{profile.display_name}** — {profile.focus}
"""


def reserve_release_audit(
    owner: str,
    repo: str,
    branch: str,
    commit_sha: str,
    username: str,
) -> int | None:
    now = utc_now()
    with database_lock, connect_database() as db:
        row = db.execute(
            "SELECT issue_number, status FROM release_audits "
            "WHERE owner=%s AND repo=%s AND branch=%s AND commit_sha=%s AND agent=%s",
            (owner, repo, branch, commit_sha, username),
        ).fetchone()
        if row:
            if row["status"] != "failed":
                return None
            db.execute(
                "UPDATE release_audits SET status='preparing', updated_at=%s "
                "WHERE owner=%s AND repo=%s AND branch=%s AND commit_sha=%s AND agent=%s",
                (now, owner, repo, branch, commit_sha, username),
            )
            return int(row["issue_number"])
        db.execute(
            "INSERT INTO release_audits(owner, repo, branch, commit_sha, agent, status, created_at, updated_at) "
            "VALUES(%s, %s, %s, %s, %s, 'preparing', %s, %s)",
            (owner, repo, branch, commit_sha, username, now, now),
        )
    return 0


def set_release_audit_issue(
    owner: str,
    repo: str,
    branch: str,
    commit_sha: str,
    username: str,
    issue_number: int,
    status: str,
) -> None:
    with database_lock, connect_database() as db:
        db.execute(
            "UPDATE release_audits SET issue_number=%s, status=%s, updated_at=%s "
            "WHERE owner=%s AND repo=%s AND branch=%s AND commit_sha=%s AND agent=%s",
            (issue_number, status, utc_now(), owner, repo, branch, commit_sha, username),
        )


def process_release_push(payload: dict[str, Any]) -> dict[str, Any]:
    repository = payload.get("repository") or {}
    owner = str((repository.get("owner") or {}).get("login") or "")
    repo = str(repository.get("name") or "")
    ref = str(payload.get("ref") or "")
    branch = ref.removeprefix("refs/heads/") if ref.startswith("refs/heads/") else ""
    commit_sha = str(payload.get("after") or "")
    sender = str((payload.get("sender") or {}).get("login") or "")
    if owner != settings.allowed_owner:
        raise HTTPException(status_code=403, detail="Repository owner is not allowed")
    if not repo or not branch or not commit_sha:
        raise HTTPException(status_code=400, detail="Push webhook is missing repository, branch, or commit")
    if not is_release_branch(branch):
        return {"accepted": False, "reason": "branch is not a release branch"}
    if payload.get("deleted") or set(commit_sha) == {"0"}:
        return {"accepted": False, "reason": "release branch deletion ignored"}
    if sender in {"glm-maintainer", *BY_USERNAME}:
        return {"accepted": False, "reason": "agent-authored release push ignored"}

    comparison_branch = str(repository.get("default_branch") or "main")
    queued_agents: list[str] = []
    duplicate_agents: list[str] = []
    maintainer = ForgejoClient(settings)
    try:
        for agent_key in ("security", "docs"):
            profile = AGENTS[agent_key]
            issue_number = reserve_release_audit(
                owner, repo, branch, commit_sha, profile.username
            )
            if issue_number is None:
                duplicate_agents.append(profile.username)
                continue
            try:
                if issue_number == 0:
                    issue = maintainer.create_issue(
                        owner,
                        repo,
                        release_audit_title(agent_key, branch, commit_sha),
                        release_audit_body(agent_key, branch, commit_sha, comparison_branch),
                    )
                    issue_number = int(issue["number"])
                    issue_url = str(issue.get("html_url") or issue.get("url") or "")
                else:
                    issue = maintainer.issue(owner, repo, issue_number)
                    issue_url = str(issue.get("html_url") or issue.get("url") or "")
                task = IssueTask(
                    owner=owner,
                    repo=repo,
                    issue_number=issue_number,
                    title=release_audit_title(agent_key, branch, commit_sha),
                    body=release_audit_body(agent_key, branch, commit_sha, comparison_branch),
                    default_branch=branch,
                    issue_url=issue_url,
                    agent_key=agent_key,
                    branch_override=release_agent_branch(agent_key, branch, commit_sha),
                    comparison_branch=comparison_branch,
                    trigger_kind="release",
                    trigger_sha=commit_sha,
                    auto_merge_allowed=True,
                )
                delivery_id = hashlib.sha256(
                    f"release:{owner}/{repo}:{branch}:{commit_sha}:{profile.username}".encode()
                ).hexdigest()

                def announce_release_assignment(
                    current_task: IssueTask = task,
                    current_profile=profile,
                ) -> None:
                    maintainer.comment_issue(
                        current_task.owner,
                        current_task.repo,
                        current_task.issue_number,
                        "🧭 release branch pushを検出しました。\n\n"
                        f"@{current_profile.username} が `{current_task.default_branch}` "
                        f"@ `{current_task.trigger_sha[:10]}` を監査し、"
                        "同ブランチ向けのPRを作成します。独立レビュー承認後にメンテナーが自動マージします。",
                    )

                queued = enqueue(
                    task,
                    delivery_id,
                    allow_retry=True,
                    announce=announce_release_assignment,
                )
                set_release_audit_issue(
                    owner,
                    repo,
                    branch,
                    commit_sha,
                    profile.username,
                    issue_number,
                    "queued" if queued else "duplicate",
                )
                (queued_agents if queued else duplicate_agents).append(profile.username)
            except Exception:
                set_release_audit_issue(
                    owner,
                    repo,
                    branch,
                    commit_sha,
                    profile.username,
                    issue_number,
                    "failed",
                )
                raise
    finally:
        maintainer.close()
    return {
        "accepted": bool(queued_agents),
        "release_branch": branch,
        "commit": commit_sha,
        "queued_agents": queued_agents,
        "duplicate_agents": duplicate_agents,
        "auto_merge": settings.auto_merge,
    }


HUMANLESS_AGENT_ROTATION = ("designer", "security", "docs", "coding")


def humanless_issue_body(
    *,
    repo: str,
    description: str,
    cycle_number: int,
    phase: str,
    agent_key: str,
    previous_detail: str,
) -> str:
    profile = AGENTS[agent_key]
    if phase.startswith("bootstrap"):
        mission = """
README、リポジトリ説明、既存ファイルを製品briefとして読み、実際に使える最小製品を完成させてください。
未実装または骨組みだけなら、主要利用フロー、テスト、Dockerfile、起動手順、運用上必要な文書まで実装してください。
UIを持つ場合は実ブラウザで主要操作を確認し、モバイル／デスクトップの証跡を残してください。
"""
    else:
        mission = f"""
現在の製品、git履歴、README、テスト、依存関係、未解決の品質問題を調査してください。
{profile.focus}という担当領域から、利用者または運用者に最も価値が高い改善を1つ自律的に選び、
実装、回帰テスト、必要な文書更新まで完遂してください。単なる監査報告だけで終わらせず、
安全に修正可能な問題はこのcycleで修正してください。
"""
    prior = (
        f"\n## 前cycleの未解決情報\n\n{previous_detail[:3000]}\n"
        if previous_detail and phase.endswith("recovery")
        else ""
    )
    return f"""<!-- nyankoface-maintenance:humanless -->
## 自動運用cycle

- repository: `{repo}`
- cycle: `{cycle_number}`
- phase: `{phase}`
- specialist: `@{profile.username}`
- product description: {description or "READMEと既存実装から目的を推定する"}

このIssueは定期メンテナンスのスケジューラが作成しました。
安全に判断できる範囲を自律的に進めてください。

## Mission

{mission.strip()}
{prior}
## 完了条件

- 選んだ目的と採用理由をIssueの要件として明確化する
- プロダクション品質の実装を行う
- 関連するtest、lint、build、セキュリティ確認を実行する
- 実行不能または失敗を成功扱いにしない
- READMEや運用手順が現実と一致するよう更新する
- 独立した `review-agent` の現在SHAレビューを受ける
- 指摘された場合は最大{settings.humanless_max_attempts}回まで自動修正し、承認後は `glm-maintainer` が自動マージする

担当: **{profile.display_name}** — {profile.focus}
"""


def reserve_humanless_cycle(
    owner: str,
    repo: str,
) -> dict[str, Any] | None:
    now = datetime.now(timezone.utc)
    with database_lock, connect_database() as db:
        previous = db.execute(
            "SELECT cycle_number, phase, status, detail, agent, issue_number, attempt, "
            "pull_url, updated_at, next_run_at "
            "FROM humanless_cycles "
            "WHERE owner=%s AND repo=%s ORDER BY cycle_number DESC LIMIT 1",
            (owner, repo),
        ).fetchone()
        if previous:
            previous_status = str(previous["status"])
            previous_detail = str(previous["detail"] or "")
            previous_next_run = previous["next_run_at"]
            if previous_status in {"preparing", "queued", "running", "retrying"}:
                updated_at = previous["updated_at"]
                age_seconds = (
                    (now - updated_at).total_seconds()
                    if updated_at is not None
                    else settings.humanless_stale_seconds + 1
                )
                if age_seconds <= settings.humanless_stale_seconds:
                    return None
                previous_detail = (
                    f"前cycleのleaseが{int(age_seconds)}秒更新されなかったため、"
                    "停止したworkerとして自動回収しました。\n\n"
                    + previous_detail
                ).strip()
                db.execute(
                    "UPDATE humanless_cycles SET status='failed', detail=%s, "
                    "updated_at=%s, next_run_at=%s "
                    "WHERE owner=%s AND repo=%s AND cycle_number=%s",
                    (
                        previous_detail[:4000],
                        now,
                        now,
                        owner,
                        repo,
                        previous["cycle_number"],
                    ),
                )
                previous_status = "failed"
                previous_next_run = now
            if previous_next_run > now:
                return None
            recoverable = db.execute(
                "SELECT cycle_number, phase, detail, agent, issue_number, attempt, pull_url "
                "FROM humanless_cycles "
                "WHERE owner=%s AND repo=%s AND pull_url<>'' "
                "AND status IN ('failed', 'changes_requested', 'awaiting_merge') "
                "AND cycle_number > COALESCE(("
                "SELECT MAX(cycle_number) FROM humanless_cycles "
                "WHERE owner=%s AND repo=%s AND status='completed'"
                "), 0) "
                "ORDER BY cycle_number DESC LIMIT 1",
                (owner, repo, owner, repo),
            ).fetchone()
            if recoverable and str(recoverable.get("pull_url") or ""):
                cycle_number = int(recoverable["cycle_number"])
                previous_agent = str(recoverable["agent"] or "")
                agent_key = next(
                    (
                        key
                        for key, profile in AGENTS.items()
                        if profile.username == previous_agent and key != "review"
                    ),
                    "coding",
                )
                db.execute(
                    "UPDATE humanless_cycles SET status='superseded', updated_at=%s "
                    "WHERE owner=%s AND repo=%s AND cycle_number>%s "
                    "AND status<>'completed'",
                    (now, owner, repo, cycle_number),
                )
                db.execute(
                    "UPDATE humanless_cycles SET status='preparing', attempt=1, "
                    "updated_at=%s, next_run_at=%s "
                    "WHERE owner=%s AND repo=%s AND cycle_number=%s",
                    (now, now, owner, repo, cycle_number),
                )
                return {
                    "cycle_number": cycle_number,
                    "phase": "review-recovery",
                    "agent_key": agent_key,
                    "previous_detail": str(recoverable["detail"] or ""),
                    "issue_number": int(recoverable["issue_number"] or 0),
                    "pull_url": str(recoverable["pull_url"] or ""),
                    "resume_pull": True,
                }
            cycle_number = int(previous["cycle_number"]) + 1
            if previous_status in {"failed", "changes_requested", "awaiting_merge"}:
                phase = (
                    "bootstrap-recovery"
                    if str(previous["phase"] or "").startswith("bootstrap")
                    else "recovery"
                )
            else:
                phase = "maintenance"
            if phase.endswith("recovery"):
                previous_agent = str(previous["agent"] or "")
                agent_key = next(
                    (
                        key
                        for key, profile in AGENTS.items()
                        if profile.username == previous_agent and key != "review"
                    ),
                    "coding",
                )
            else:
                agent_key = HUMANLESS_AGENT_ROTATION[
                    (cycle_number - 2) % len(HUMANLESS_AGENT_ROTATION)
                ]
        else:
            cycle_number = 1
            phase = "bootstrap"
            agent_key = "coding"
            previous_detail = ""
        profile = AGENTS[agent_key]
        db.execute(
            "INSERT INTO humanless_cycles(owner, repo, cycle_number, phase, agent, status, "
            "created_at, updated_at, next_run_at) VALUES(%s, %s, %s, %s, %s, 'preparing', %s, %s, %s)",
            (owner, repo, cycle_number, phase, profile.username, now, now, now),
        )
    return {
        "cycle_number": cycle_number,
        "phase": phase,
        "agent_key": agent_key,
        "previous_detail": previous_detail,
        "issue_number": 0,
        "pull_url": "",
        "resume_pull": False,
    }


def set_humanless_cycle_issue(
    owner: str,
    repo: str,
    cycle_number: int,
    issue_number: int,
    status: str,
) -> None:
    with database_lock, connect_database() as db:
        if status == "duplicate":
            # A scan can rediscover a published PR after the original job has
            # already moved from preparing to running. Queue de-duplication is
            # expected in that race and must not make the durable lease look
            # inactive, otherwise every later scan would adopt it again.
            db.execute(
                "UPDATE humanless_cycles SET issue_number=%s "
                "WHERE owner=%s AND repo=%s AND cycle_number=%s",
                (issue_number, owner, repo, cycle_number),
            )
        elif status == "queued":
            # The worker may start before enqueue() returns. Preserve the
            # stronger running/retrying state instead of moving it backwards.
            db.execute(
                "UPDATE humanless_cycles SET issue_number=%s, "
                "status=CASE WHEN status='preparing' THEN 'queued' ELSE status END, "
                "updated_at=CASE WHEN status='preparing' THEN %s ELSE updated_at END "
                "WHERE owner=%s AND repo=%s AND cycle_number=%s",
                (issue_number, utc_now(), owner, repo, cycle_number),
            )
        else:
            db.execute(
                "UPDATE humanless_cycles SET issue_number=%s, status=%s, updated_at=%s "
                "WHERE owner=%s AND repo=%s AND cycle_number=%s",
                (issue_number, status, utc_now(), owner, repo, cycle_number),
            )


def adopt_published_humanless_pull(
    owner: str,
    repo: str,
    *,
    cycle_number: int,
    pull_url: str,
) -> dict[str, Any] | None:
    now = datetime.now(timezone.utc)
    with database_lock, connect_database() as db:
        row = db.execute(
            "SELECT cycle_number, phase, detail, agent, issue_number "
            "FROM humanless_cycles "
            "WHERE owner=%s AND repo=%s AND cycle_number=%s "
            "AND cycle_number > COALESCE(("
            "SELECT MAX(cycle_number) FROM humanless_cycles "
            "WHERE owner=%s AND repo=%s AND status='completed'"
            "), 0)",
            (owner, repo, cycle_number, owner, repo),
        ).fetchone()
        if not row or not int(row.get("issue_number") or 0):
            return None
        db.execute(
            "UPDATE humanless_cycles SET status='superseded', updated_at=%s "
            "WHERE owner=%s AND repo=%s AND cycle_number>%s "
            "AND status<>'completed'",
            (now, owner, repo, cycle_number),
        )
        db.execute(
            "UPDATE humanless_cycles SET status='preparing', attempt=1, pull_url=%s, "
            "updated_at=%s, next_run_at=%s "
            "WHERE owner=%s AND repo=%s AND cycle_number=%s",
            (pull_url, now, now, owner, repo, cycle_number),
        )
    previous_agent = str(row["agent"] or "")
    agent_key = next(
        (
            key
            for key, profile in AGENTS.items()
            if profile.username == previous_agent and key != "review"
        ),
        "coding",
    )
    return {
        "cycle_number": cycle_number,
        "phase": "review-recovery",
        "agent_key": agent_key,
        "previous_detail": str(row["detail"] or ""),
        "issue_number": int(row["issue_number"]),
        "pull_url": pull_url,
        "resume_pull": True,
    }


def queue_humanless_repository(
    repository: dict[str, Any],
    topics: set[str],
) -> dict[str, Any] | None:
    owner = settings.allowed_owner
    repo = str(repository.get("name") or "")
    if not repo or repository.get("archived") or repository.get("empty"):
        return None
    reserved = reserve_humanless_cycle(owner, repo)
    if not reserved:
        return None
    cycle_number = int(reserved["cycle_number"])
    phase = str(reserved["phase"])
    agent_key = str(reserved["agent_key"])
    profile = AGENTS[agent_key]
    issue_number = 0
    maintainer = ForgejoClient(settings)
    try:
        if not reserved.get("resume_pull"):
            published = maintainer.latest_open_pull(
                owner, repo, "agent/humanless-"
            )
            if published:
                published_pull, published_branch = published
                match = re.fullmatch(
                    r"agent/humanless-(\d+)-([a-z]+)", published_branch
                )
                if match:
                    adopted = adopt_published_humanless_pull(
                        owner,
                        repo,
                        cycle_number=int(match.group(1)),
                        pull_url=published_pull.url,
                    )
                    if adopted:
                        reserved = adopted
                        cycle_number = int(adopted["cycle_number"])
                        phase = str(adopted["phase"])
                        agent_key = str(adopted["agent_key"])
                        profile = AGENTS[agent_key]

        if reserved.get("resume_pull"):
            issue_number = int(reserved["issue_number"])
            branch = f"agent/humanless-{cycle_number}-{agent_key}"
            existing = maintainer.existing_pull(owner, repo, branch)
            if existing is None or not issue_number:
                with database_lock, connect_database() as db:
                    db.execute(
                        "UPDATE humanless_cycles SET status='failed', pull_url='', "
                        "detail=%s, updated_at=%s, next_run_at=%s "
                        "WHERE owner=%s AND repo=%s AND cycle_number=%s",
                        (
                            "保存されたPRを再取得できなかったため、新規recoveryへ切り替えます。",
                            utc_now(),
                            utc_now(),
                            owner,
                            repo,
                            cycle_number,
                        ),
                    )
                return None
            issue = maintainer.issue(owner, repo, issue_number)
            task = IssueTask(
                owner=owner,
                repo=repo,
                issue_number=issue_number,
                title=str(issue.get("title") or f"自動運用cycle {cycle_number}"),
                body=str(issue.get("body") or ""),
                default_branch=str(repository.get("default_branch") or "main"),
                issue_url=str(issue.get("html_url") or issue.get("url") or ""),
                agent_key=agent_key,
                branch_override=branch,
                trigger_kind="humanless",
                auto_merge_allowed=True,
                ui_evidence_required=("humanless-ui" in topics),
                humanless_cycle=cycle_number,
                humanless_attempt=1,
                review_only=True,
            )
            delivery_id = hashlib.sha256(
                f"humanless-review-recovery:{owner}/{repo}:{cycle_number}:{existing.head_sha}".encode()
            ).hexdigest()

            def announce_review_recovery() -> None:
                maintainer.comment_issue(
                    owner,
                    repo,
                    issue_number,
                    f"♻️ 自動運用は公開済み [PR #{existing.number}]({existing.url}) を"
                    "再利用し、実装を作り直さず独立レビューから自動回復します。\n\n"
                    "@review-agent の承認後に @glm-maintainer が自動マージします。",
                )

            queued = enqueue(
                task,
                delivery_id,
                allow_retry=True,
                announce=announce_review_recovery,
            )
            set_humanless_cycle_issue(
                owner, repo, cycle_number, issue_number, "queued" if queued else "duplicate"
            )
            return {
                "repo": repo,
                "cycle": cycle_number,
                "phase": "review-recovery",
                "agent": profile.username,
                "issue": issue_number,
                "pull": existing.url,
                "queued": queued,
            }

        title = (
            f"[自動開発] {repo} の初期プロダクトを完成させる"
            if phase.startswith("bootstrap")
            else f"[定期メンテナンス][cycle {cycle_number}] {profile.display_name} 自律改善"
        )
        body = humanless_issue_body(
            repo=repo,
            description=str(repository.get("description") or ""),
            cycle_number=cycle_number,
            phase=phase,
            agent_key=agent_key,
            previous_detail=str(reserved["previous_detail"]),
        )
        issue = maintainer.create_issue(owner, repo, title, body)
        issue_number = int(issue["number"])
        issue_url = str(issue.get("html_url") or issue.get("url") or "")
        task = IssueTask(
            owner=owner,
            repo=repo,
            issue_number=issue_number,
            title=title,
            body=body,
            default_branch=str(repository.get("default_branch") or "main"),
            issue_url=issue_url,
            agent_key=agent_key,
            branch_override=f"agent/humanless-{cycle_number}-{agent_key}",
            trigger_kind="humanless",
            auto_merge_allowed=True,
            ui_evidence_required=(
                "humanless-ui" in topics or agent_key == "designer"
            ),
            humanless_cycle=cycle_number,
            humanless_attempt=1,
        )
        delivery_id = hashlib.sha256(
            f"humanless:{owner}/{repo}:{cycle_number}:{profile.username}".encode()
        ).hexdigest()

        def announce() -> None:
            maintainer.comment_issue(
                owner,
                repo,
                issue_number,
                f"♾️ 自動運用cycle {cycle_number} を開始しました。\n\n"
                f"@{profile.username} が自律的に実装し、@review-agent の独立承認後に"
                " @glm-maintainer が自動マージします。",
            )

        queued = enqueue(task, delivery_id, allow_retry=False, announce=announce)
        set_humanless_cycle_issue(
            owner, repo, cycle_number, issue_number, "queued" if queued else "duplicate"
        )
        return {
            "repo": repo,
            "cycle": cycle_number,
            "phase": phase,
            "agent": profile.username,
            "issue": issue_number,
            "queued": queued,
        }
    except Exception:
        set_humanless_cycle_issue(owner, repo, cycle_number, issue_number, "failed")
        raise
    finally:
        maintainer.close()


def run_humanless_scan() -> list[dict[str, Any]]:
    if not settings.humanless_enabled:
        return []
    if not humanless_scan_lock.acquire(blocking=False):
        return []
    maintainer = ForgejoClient(settings)
    queued: list[dict[str, Any]] = []
    try:
        for repository in maintainer.organization_repositories(settings.allowed_owner):
            repo = str(repository.get("name") or "")
            if not repo:
                continue
            topics = {
                str(topic).strip().lower()
                for topic in (repository.get("topics") or [])
                if str(topic).strip()
            }
            if settings.humanless_topic not in topics:
                cache_key = f"{settings.allowed_owner}/{repo}"
                revision = str(repository.get("updated_at") or "")
                cached = humanless_topic_cache.get(cache_key)
                if cached and cached[0] == revision:
                    topics = cached[1]
                else:
                    topics = maintainer.repository_topics(settings.allowed_owner, repo)
                    humanless_topic_cache[cache_key] = (revision, topics)
            if settings.humanless_topic not in topics or "humanless-paused" in topics:
                continue
            result = queue_humanless_repository(repository, topics)
            if result:
                queued.append(result)
        return queued
    finally:
        maintainer.close()
        humanless_scan_lock.release()


def humanless_scheduler_loop() -> None:
    while not humanless_stop.is_set():
        try:
            queued = run_humanless_scan()
            if queued:
                logger.info("Humanless scan queued %s", queued)
        except Exception:
            logger.exception("Humanless scheduler scan failed")
        humanless_stop.wait(settings.humanless_scan_seconds)


def start_humanless_scheduler() -> None:
    global humanless_thread
    if not settings.humanless_enabled or humanless_thread is not None:
        return
    humanless_stop.clear()
    humanless_thread = Thread(
        target=humanless_scheduler_loop,
        name="humanless-maintenance-scheduler",
        daemon=True,
    )
    humanless_thread.start()
    logger.info(
        "Humanless scheduler started (topic=%s, interval=%sm)",
        settings.humanless_topic,
        settings.humanless_interval_minutes,
    )


def stop_humanless_scheduler() -> None:
    humanless_stop.set()


def enqueue(
    task: IssueTask,
    delivery_id: str,
    *,
    allow_retry: bool,
    announce: Callable[[], None] | None = None,
) -> bool:
    now = utc_now()
    with database_lock, connect_database() as db:
        row = db.execute(
            "SELECT delivery_id, status FROM jobs WHERE owner=%s AND repo=%s AND issue_number=%s",
            (task.owner, task.repo, task.issue_number),
        ).fetchone()
        if row:
            if not allow_retry or row["status"] in {"queued", "running"}:
                return False
            db.execute(
                "UPDATE jobs SET delivery_id=%s, status='queued', detail='', pull_url='', created_at=%s, updated_at=%s, agent=%s "
                "WHERE owner=%s AND repo=%s AND issue_number=%s",
                (delivery_id, now, now, AGENTS[task.agent_key].username, task.owner, task.repo, task.issue_number),
            )
        else:
            db.execute(
                "INSERT INTO jobs(delivery_id, owner, repo, issue_number, status, created_at, updated_at, agent) "
                "VALUES(%s, %s, %s, %s, 'queued', %s, %s, %s)",
                (delivery_id, task.owner, task.repo, task.issue_number, now, now, AGENTS[task.agent_key].username),
            )
    try:
        if announce:
            announce()
    except Exception:
        with database_lock, connect_database() as db:
            db.execute("DELETE FROM jobs WHERE delivery_id=%s AND status='queued'", (delivery_id,))
        raise
    executor.submit(process_job, delivery_id, task)
    return True


@app.get("/health")
def health() -> JSONResponse:
    ready = settings.readiness()
    try:
        with connect_database() as db:
            ready["database"] = db.execute("SELECT 1 AS ok").fetchone()["ok"] == 1
    except Exception:
        ready["database"] = False
    status = 200 if all(ready.values()) else 503
    return JSONResponse(
        status_code=status,
        content={
            "ok": status == 200,
            "model": settings.model,
            "max_workers": settings.max_workers,
            "humanless": {
                "enabled": settings.humanless_enabled,
                "topic": settings.humanless_topic,
                "scan_seconds": settings.humanless_scan_seconds,
                "interval_minutes": settings.humanless_interval_minutes,
                "max_attempts": settings.humanless_max_attempts,
                "stale_seconds": settings.humanless_stale_seconds,
            },
            "automatic_issues": {
                "enabled": settings.auto_issue_enabled,
                "topic": settings.auto_issue_topic,
                "max_review_attempts": settings.automatic_retry_max_attempts,
            },
            "automatic_labels": {
                "enabled": settings.auto_label_enabled,
                "dry_run": settings.auto_label_dry_run,
                "confidence": settings.auto_label_confidence,
                "allowed": list(settings.auto_label_allowed),
            },
            "dependencies": ready,
        },
    )


@app.get("/api/jobs")
def jobs() -> dict[str, Any]:
    with database_lock, connect_database() as db:
        rows = db.execute(
            "SELECT delivery_id, owner, repo, issue_number, status, detail, pull_url, agent, created_at, updated_at "
            "FROM jobs ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
    return {"jobs": [dict(row) for row in rows]}


@app.get("/api/humanless/cycles")
def humanless_cycles() -> dict[str, Any]:
    with database_lock, connect_database() as db:
        rows = db.execute(
            "SELECT owner, repo, cycle_number, phase, agent, issue_number, attempt, status, "
            "detail, pull_url, created_at, updated_at, next_run_at "
            "FROM humanless_cycles ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    return {
        "enabled": settings.humanless_enabled,
        "topic": settings.humanless_topic,
        "cycles": [dict(row) for row in rows],
    }


@app.get("/api/releases/audits")
def release_audits() -> dict[str, Any]:
    with database_lock, connect_database() as db:
        rows = db.execute(
            "SELECT owner, repo, branch, commit_sha, agent, issue_number, status, "
            "created_at, updated_at FROM release_audits "
            "ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    return {"audits": [dict(row) for row in rows]}


@app.get("/api/labels/audits")
def label_audits() -> dict[str, Any]:
    with database_lock, connect_database() as db:
        rows = db.execute(
            "SELECT delivery_id, owner, repo, subject_number, subject_kind, action, "
            "dry_run, candidates, applied, skipped, created_at "
            "FROM label_audits ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    return {
        "enabled": settings.auto_label_enabled,
        "dry_run": settings.auto_label_dry_run,
        "confidence": settings.auto_label_confidence,
        "allowed": list(settings.auto_label_allowed),
        "audits": [dict(row) for row in rows],
    }


@app.post("/api/labels/preview")
def preview_labels(payload: dict[str, Any]) -> dict[str, Any]:
    decision = classify_labels(
        str(payload.get("title") or ""),
        str(payload.get("body") or ""),
        changed_files=(
            str(path)
            for path in payload.get("changed_files", [])
            if isinstance(path, str)
        ),
    )
    candidates = decision.above(settings.auto_label_confidence)
    return {
        "dry_run": True,
        "confidence": settings.auto_label_confidence,
        "allowed": list(settings.auto_label_allowed),
        "candidates": [_candidate_payload(candidate) for candidate in candidates],
    }


@app.get("/api/agents")
def agents() -> dict[str, Any]:
    return {
        "agents": [
            {
                "key": profile.key,
                "username": profile.username,
                "display_name": profile.display_name,
                "emoji": profile.emoji,
                "focus": profile.focus,
                "mention": f"@{profile.username}",
            }
            for profile in AGENTS.values()
        ]
    }


@app.post("/webhooks/forgejo", status_code=202)
async def forgejo_webhook(
    request: Request,
    x_forgejo_event: str | None = Header(default=None),
    x_forgejo_delivery: str | None = Header(default=None),
    x_forgejo_signature: str | None = Header(default=None),
) -> dict[str, Any]:
    raw_body = await request.body()
    if not signature_valid(raw_body, x_forgejo_signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    if x_forgejo_event not in {
        "push",
        "issues",
        "issue",
        "pull_request",
        "issue_comment",
        "pull_request_comment",
    }:
        return {"accepted": False, "reason": "event ignored"}
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc
    if x_forgejo_event == "push":
        return process_release_push(payload)
    delivery_id = x_forgejo_delivery or hashlib.sha256(raw_body).hexdigest()
    auto_label = (
        process_auto_labels(
            event=x_forgejo_event,
            payload=payload,
            delivery_id=delivery_id,
        )
        if x_forgejo_event in {"issues", "issue", "pull_request"}
        else None
    )
    if x_forgejo_event == "pull_request":
        return {
            "accepted": bool(auto_label and not auto_label.get("ignored")),
            "auto_label": auto_label,
        }
    issue = payload.get("issue") or {}
    body = str(issue.get("body") or "")
    labels = {str(label.get("name", "")).lower() for label in issue.get("labels", []) if isinstance(label, dict)}
    sender = (payload.get("sender") or {}).get("login", "")
    if sender in {"glm-maintainer", *BY_USERNAME} or "agent:skip" in labels or "<!-- nyankoface-maintenance:skip -->" in body:
        return {"accepted": False, "reason": "issue opted out"}
    if x_forgejo_event in {"issues", "issue"}:
        if payload.get("action") != "opened":
            return {"accepted": False, "reason": "action ignored"}
        explicit_request = mentions_maintainer(body)
        automatic_request = False
        response_only = False
        if explicit_request:
            instruction = maintainer_instruction(body)
            profile = assign_agent(str(issue.get("title") or ""), instruction)
        else:
            if not settings.auto_issue_enabled:
                return {
                    "accepted": False,
                    "reason": "mention @glm-maintainer to start maintenance",
                }
            repository = payload.get("repository") or {}
            owner = str((repository.get("owner") or {}).get("login") or "")
            repo = str(repository.get("name") or "")
            if owner != settings.allowed_owner:
                raise HTTPException(
                    status_code=403, detail="Repository owner is not allowed"
                )
            if not repo:
                raise HTTPException(
                    status_code=400, detail="Webhook is missing repository data"
                )
            topic_client = ForgejoClient(settings)
            try:
                topics = topic_client.repository_topics(owner, repo)
            finally:
                topic_client.close()
            opted_in = {
                settings.auto_issue_topic,
                settings.humanless_topic,
            } & topics
            if not opted_in or "humanless-paused" in topics:
                return {
                    "accepted": False,
                    "reason": "repository is not opted into automatic Issue handling",
                }
            profile, response_only = classify_automatic_issue(
                str(issue.get("title") or ""), body, labels
            )
            instruction = body
            automatic_request = True
        task = payload_to_task(
            payload,
            instruction=instruction,
            agent_key=profile.key,
            ui_evidence_required=(
                not response_only
                and is_ui_task(
                    str(issue.get("title") or ""), instruction, profile
                )
            ),
            trigger_kind="issue-auto" if automatic_request else "issue",
            response_only=response_only,
        )
        def announce_delegation() -> None:
            client = ForgejoClient(settings)
            try:
                if automatic_request:
                    mode = (
                        "リポジトリを変更せず、根拠付きの回答を投稿"
                        if task.response_only
                        else "修正・検証・独立レビュー・自動マージ"
                    )
                    message = (
                        "Issueを受け付けました。\n\n"
                        f"@{profile.username} **{mode}** をお願いします。\n\n"
                        f"> {' '.join(task.title.split())[:300]}"
                    )
                else:
                    message = delegation_comment(
                        profile, f"{task.title}\n{task.body}", follow_up=False
                    )
                client.comment_issue(
                    task.owner, task.repo, task.issue_number, message
                )
            finally:
                client.close()
        queued = enqueue(task, delivery_id, allow_retry=False, announce=announce_delegation)
    else:
        if payload.get("action") not in {"created", "edited"}:
            return {"accepted": False, "reason": "comment action ignored"}
        comment_body = str((payload.get("comment") or {}).get("body") or "")
        if not mentions_maintainer(comment_body):
            return {"accepted": False, "reason": "comment must mention @glm-maintainer"}
        instruction = maintainer_instruction(comment_body)
        if not instruction:
            return {"accepted": False, "reason": "maintainer mention has no instruction"}
        repository = payload.get("repository") or {}
        owner = str((repository.get("owner") or {}).get("login") or "")
        repo = str(repository.get("name") or "")
        issue_number = int(issue.get("number") or 0)
        reply_number: int | None = None
        if issue.get("pull_request"):
            reply_number = issue_number
            client = ForgejoClient(settings)
            try:
                source_number = client.source_issue_number_for_pull(owner, repo, issue_number)
                if not source_number:
                    return {"accepted": False, "reason": "pull request is not managed by the agent"}
                issue = client.issue(owner, repo, source_number)
            finally:
                client.close()
        profile = choose_agent(str(issue.get("title") or ""), instruction)
        task = payload_to_task(
            payload, issue_override=issue, follow_up=True, instruction=instruction, agent_key=profile.key,
            reply_number=reply_number,
            ui_evidence_required=is_ui_task(str(issue.get("title") or ""), instruction, profile),
        )
        def announce_follow_up() -> None:
            client = ForgejoClient(settings)
            try:
                client.comment_issue(
                    task.owner, task.repo, task.conversation_number,
                    delegation_comment(profile, instruction, follow_up=True),
                )
            finally:
                client.close()
        queued = enqueue(task, delivery_id, allow_retry=True, announce=announce_follow_up)
    response = {
        "accepted": True,
        "duplicate": not queued,
        "issue": task.issue_number,
        "model": settings.model,
        "follow_up": task.follow_up,
        "agent": AGENTS[task.agent_key].username,
        "ui_evidence_required": task.ui_evidence_required,
        "response_only": task.response_only,
        "automatic": task.trigger_kind == "issue-auto",
    }
    if auto_label is not None:
        response["auto_label"] = auto_label
    return response
