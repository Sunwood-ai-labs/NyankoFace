#!/usr/bin/env python3
"""Search for duplicate Issues and publish one staged report as an operator."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from stage_report import (
    DEFAULT_MAX_PER_DAY,
    DEFAULT_MAX_PER_HOUR,
    ReportError,
    _atomic_write,
    _env_limit,
    _entry_time,
    isoformat,
    outbox_lock,
    read_entries,
    utc_now,
)


class PublishError(RuntimeError):
    """Raised when an operator publication cannot be completed safely."""


def _load_pending(outbox: Path, report_id: str) -> tuple[Path, dict[str, Any]]:
    path = outbox.expanduser().resolve() / "pending" / f"{report_id}.json"
    if not path.is_file():
        raise PublishError("pending report was not found")
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishError("pending report is not valid JSON") from exc
    if not isinstance(entry, dict) or entry.get("status") != "pending":
        raise PublishError("pending report has an invalid status")
    required = ("report_id", "fingerprint", "title", "markdown", "dedupe_query", "reporter")
    if any(not isinstance(entry.get(field), str) or not entry[field].strip() for field in required):
        raise PublishError("pending report is missing required fields")
    return path, entry


def _safe_serialized(entry: dict[str, Any]) -> str:
    serialized = json.dumps(entry, ensure_ascii=False, sort_keys=True)
    # Reuse the staging redaction contract by rejecting a value that should
    # never have survived the agent-side sanitizer. Avoid printing the value.
    if re.search(r"(?i)-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|\b(?:gh[pousr]|github_pat|xox[baprs]-)[A-Za-z0-9_\-.]+", serialized):
        raise PublishError("pending report contains credential-shaped material")
    if re.search(r"(?i)\b(?:Authorization\s*:\s*)?Bearer\s+(?!\[REDACTED\])[^\s,;]+", serialized):
        raise PublishError("pending report contains credential-shaped material")
    return serialized


def _run_gh(gh: Sequence[str], arguments: Sequence[str]) -> str:
    completed = subprocess.run(
        [*gh, *arguments],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        # Do not echo stderr: a misconfigured CLI or wrapper could include a
        # credential. The operator can inspect gh's own sanitized diagnostics.
        raise PublishError(f"GitHub CLI command failed with exit code {completed.returncode}")
    return completed.stdout.strip()


def _search_duplicates(gh: Sequence[str], repo: str, query: str) -> list[dict[str, Any]]:
    raw = _run_gh(
        gh,
        (
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--search",
            query,
            "--limit",
            "20",
            "--json",
            "number,title,url",
        ),
    )
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PublishError("GitHub CLI returned invalid duplicate-search JSON") from exc
    if not isinstance(value, list):
        raise PublishError("GitHub CLI returned an invalid duplicate-search result")
    matches: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        matches.append(
            {
                key: item.get(key)
                for key in ("number", "title", "url")
                if item.get(key) is not None
            }
        )
    return matches


def _published_count(outbox: Path, repo: str, now: datetime) -> tuple[int, int]:
    hour = 0
    day = 0
    for _, entry in read_entries(outbox):
        if entry.get("status") != "published" or entry.get("publish_repo") != repo:
            continue
        published_at = _entry_time(entry, "published_at")
        if published_at is None or published_at > now:
            continue
        age = now - published_at
        if age < timedelta(hours=1):
            hour += 1
        if age < timedelta(days=1):
            day += 1
    return hour, day


def _issue_url(output: str) -> str:
    match = re.search(r"https://[^\s]+/issues/\d+", output)
    if match:
        return match.group(0).rstrip(".,)")
    if output:
        return output.splitlines()[-1].strip()
    raise PublishError("GitHub CLI did not return an Issue URL")


def publish_report(
    *,
    outbox: Path,
    repo: str,
    report_id: str,
    gh: Sequence[str] = ("gh",),
    labels: Sequence[str] = (),
    now: datetime | None = None,
    max_per_hour: int | None = None,
    max_per_day: int | None = None,
) -> dict[str, Any]:
    outbox = outbox.expanduser().resolve()
    now = now or utc_now()
    max_per_hour = max_per_hour if max_per_hour is not None else _env_limit(
        "NYANKOFACE_ISSUE_REPORT_MAX_PER_HOUR", DEFAULT_MAX_PER_HOUR
    )
    max_per_day = max_per_day if max_per_day is not None else _env_limit(
        "NYANKOFACE_ISSUE_REPORT_MAX_PER_DAY", DEFAULT_MAX_PER_DAY
    )
    if max_per_hour < 1 or max_per_day < 1:
        raise PublishError("rate limits must be positive")
    source_path, entry = _load_pending(outbox, report_id)
    _safe_serialized(entry)

    with outbox_lock(outbox):
        # Re-read after taking the lock so two operator processes cannot
        # publish the same record concurrently.
        source_path, entry = _load_pending(outbox, report_id)
        recent_hour, recent_day = _published_count(outbox, repo, now)
        if recent_hour >= max_per_hour:
            raise PublishError("operator hourly publication limit reached")
        if recent_day >= max_per_day:
            raise PublishError("operator daily publication limit reached")

        matches = _search_duplicates(gh, repo, entry["dedupe_query"])
        if matches:
            return {
                "status": "duplicate",
                "report_id": report_id,
                "matches": matches,
            }

        body_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix=f"nyankoface-issue-{report_id}-",
                suffix=".md",
                dir=outbox,
                delete=False,
            ) as handle:
                body_path = Path(handle.name)
                handle.write(entry["markdown"])
            args = ["issue", "create", "--repo", repo, "--title", entry["title"], "--body-file", str(body_path)]
            for label in labels:
                args.extend(("--label", label))
            output = _run_gh(gh, args)
        finally:
            if body_path is not None:
                body_path.unlink(missing_ok=True)

        url = _issue_url(output)
        published = dict(entry)
        published.update(
            {
                "status": "published",
                "published_at": isoformat(now),
                "publish_repo": repo,
                "issue_url": url,
            }
        )
        destination = outbox / "published" / source_path.name
        _atomic_write(destination, published)
        source_path.unlink()
        return {"status": "published", "report_id": report_id, "issue_url": url}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    publish = subparsers.add_parser("publish", help="search and publish one staged report")
    publish.add_argument("--outbox", type=Path, required=True)
    publish.add_argument("--repo", required=True, help="GitHub repository in owner/name form")
    publish.add_argument("--report-id", required=True)
    publish.add_argument("--label", action="append", default=[])
    publish.add_argument("--gh", default="gh", help="operator GitHub CLI executable")
    publish.add_argument("--max-per-hour", type=int)
    publish.add_argument("--max-per-day", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command != "publish":
        print("error: unknown command", file=sys.stderr)
        return 2
    try:
        result = publish_report(
            outbox=args.outbox,
            repo=args.repo,
            report_id=args.report_id,
            gh=(args.gh,),
            labels=args.label,
            max_per_hour=args.max_per_hour,
            max_per_day=args.max_per_day,
        )
    except (PublishError, ReportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
