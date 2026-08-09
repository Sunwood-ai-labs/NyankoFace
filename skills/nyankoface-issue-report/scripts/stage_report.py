#!/usr/bin/env python3
"""Stage a secret-free NyankoFace Issue report in a shared outbox."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence


SCHEMA_VERSION = 1
MAX_TEXT_LENGTH = 8192
MAX_LIST_ITEMS = 20
MAX_LIST_ITEM_LENGTH = 2048
DEFAULT_MAX_PER_HOUR = 5
DEFAULT_MAX_PER_DAY = 20
OUTBOX_ENV = "NYANKOFACE_ISSUE_OUTBOX"
REPORTER_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.+?-----END [A-Z0-9 ]*PRIVATE KEY-----", re.I | re.S),
        "[REDACTED_PRIVATE_KEY]",
    ),
    (
        re.compile(r"(\bAuthorization\s*:\s*Bearer\s+)[^\s,;]+", re.I),
        r"\1[REDACTED]",
    ),
    (
        re.compile(r"(\bBearer\s+)(?!\[REDACTED\])[^\s,;]+", re.I),
        r"\1[REDACTED]",
    ),
    (
        re.compile(r"\b(?:gh[pousr]|github_pat|xox[baprs]-)[A-Za-z0-9_\-.]+", re.I),
        "[REDACTED_TOKEN]",
    ),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
        "[REDACTED_JWT]",
    ),
    (
        re.compile(
            r"(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|passwd|secret|token)\b\s*[:=]\s*)([\"']?)([^,\s\"']+)",
            re.I,
        ),
        r"\1[REDACTED]",
    ),
    (
        re.compile(r"([?&](?:token|api[_-]?key|password|secret|sig|signature)=)[^&#\s]+", re.I),
        r"\1[REDACTED]",
    ),
    (
        re.compile(r"(https?://)[^/\s:@]+:[^@\s]+@", re.I),
        r"\1[REDACTED]@",
    ),
    (
        re.compile(r"(?:/run/secrets/|/opt/[^\s]*/secrets/|[A-Za-z]:[\\/][^\s]*[\\/]secrets[\\/])[^\s,;]+", re.I),
        "[REDACTED_SECRET_PATH]",
    ),
)


class ReportError(ValueError):
    """Raised when a report cannot be safely staged."""


def redact_text(value: str) -> tuple[str, int]:
    """Redact common credential forms and return text plus replacement count."""
    redacted = value.replace("\x00", " ")
    count = 0
    for pattern, replacement in _SECRET_PATTERNS:
        redacted, substitutions = pattern.subn(replacement, redacted)
        count += substitutions
    return redacted, count


def _normalize_text(value: str, field: str, *, limit: int = MAX_TEXT_LENGTH) -> tuple[str, int]:
    if not isinstance(value, str):
        raise ReportError(f"{field} must be text")
    redacted, count = redact_text(value)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in redacted.replace("\r\n", "\n").split("\n")]
    normalized = "\n".join(line for line in lines if line)
    if not normalized:
        raise ReportError(f"{field} must not be empty")
    if len(normalized) > limit:
        raise ReportError(f"{field} exceeds {limit} characters")
    return normalized, count


def _normalize_list(values: Sequence[str], field: str) -> tuple[list[str], int]:
    if not values:
        raise ReportError(f"{field} must contain at least one item")
    if len(values) > MAX_LIST_ITEMS:
        raise ReportError(f"{field} contains more than {MAX_LIST_ITEMS} items")
    result: list[str] = []
    redactions = 0
    for index, value in enumerate(values, start=1):
        normalized, count = _normalize_text(value, f"{field}[{index}]", limit=MAX_LIST_ITEM_LENGTH)
        result.append(normalized)
        redactions += count
    return result, redactions


def _parse_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReportError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ReportError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _report_fingerprint(report_kind: str, title: str, report: dict[str, Any]) -> str:
    content = {"report_kind": report_kind, "title": title, "report": report}
    return hashlib.sha256(_canonical(content).encode("utf-8")).hexdigest()


def _inline(value: str) -> str:
    return value.replace("`", "'").replace("\n", " ")


def render_markdown(
    *,
    report_kind: str,
    title: str,
    reporter: str,
    source: str,
    observed_at: str,
    report: dict[str, Any],
) -> str:
    steps = "\n".join(f"{index}. {item}" for index, item in enumerate(report["reproduction_steps"], start=1))
    evidence = "\n".join(f"- {item}" for item in report["evidence"])
    return "\n".join(
        (
            "<!-- Generated by the NyankoFace issue report contract. Do not add credentials. -->",
            "## Summary",
            report["summary"],
            "## Environment",
            report["environment"],
            "## Reproduction steps",
            steps,
            "## Expected behavior",
            report["expected"],
            "## Actual behavior",
            report["actual"],
            "## Impact",
            report["impact"],
            "## Evidence",
            evidence,
            "## Suggested fix",
            report["suggested_fix"],
            "## Reporter",
            f"- Agent: `{_inline(reporter)}`",
            f"- Source: {_inline(source)}",
            f"- Report kind: `{_inline(report_kind)}`",
            f"- Observed at: `{_inline(observed_at)}`",
            "",
        )
    )


def _env_limit(name: str, default: int) -> int:
    value = os.environ.get(name, "")
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ReportError(f"{name} must be a positive integer") from exc
    if parsed < 1:
        raise ReportError(f"{name} must be a positive integer")
    return parsed


def _entry_time(entry: dict[str, Any], key: str) -> datetime | None:
    value = entry.get(key)
    if not isinstance(value, str):
        return None
    try:
        return _parse_time(value, key)
    except ReportError:
        return None


def _json_files(directory: Path) -> Iterator[Path]:
    if not directory.exists():
        return
    yield from sorted(directory.glob("*.json"))


def read_entries(outbox: Path) -> Iterator[tuple[Path, dict[str, Any]]]:
    for directory in (outbox / "pending", outbox / "published"):
        for path in _json_files(directory):
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(entry, dict):
                yield path, entry


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".report-", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))
            handle.write("\n")
        try:
            os.chmod(temporary, 0o640)
        except OSError:
            pass
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink(missing_ok=True)


@contextmanager
def outbox_lock(outbox: Path) -> Iterator[None]:
    """Use atomic directory creation for a short cross-platform writer lock."""
    outbox.mkdir(parents=True, exist_ok=True)
    lock = outbox / ".lock"
    deadline = time.monotonic() + 10
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                age = 0
            if age > 120:
                shutil.rmtree(lock, ignore_errors=True)
                continue
            if time.monotonic() >= deadline:
                raise ReportError("outbox is busy")
            time.sleep(0.05)
    try:
        yield
    finally:
        shutil.rmtree(lock, ignore_errors=True)


def _enforce_rate_limit(
    outbox: Path,
    reporter: str,
    now: datetime,
    max_per_hour: int,
    max_per_day: int,
) -> None:
    recent_hour = 0
    recent_day = 0
    for _, entry in read_entries(outbox):
        if entry.get("reporter") != reporter:
            continue
        staged = _entry_time(entry, "staged_at")
        if staged is None or staged > now:
            continue
        age = now - staged
        if age < timedelta(hours=1):
            recent_hour += 1
        if age < timedelta(days=1):
            recent_day += 1
    if recent_hour >= max_per_hour:
        raise ReportError("agent hourly report limit reached")
    if recent_day >= max_per_day:
        raise ReportError("agent daily report limit reached")


def stage_report(
    *,
    outbox: Path,
    report_kind: str,
    title: str,
    summary: str,
    environment: str,
    reproduction_steps: Sequence[str],
    expected: str,
    actual: str,
    impact: str,
    evidence: Sequence[str],
    suggested_fix: str,
    reporter: str,
    source: str,
    observed_at: str | None = None,
    staged_at: datetime | None = None,
    max_per_hour: int | None = None,
    max_per_day: int | None = None,
) -> dict[str, Any]:
    if report_kind not in {"bug", "enhancement"}:
        raise ReportError("report kind must be bug or enhancement")
    if not REPORTER_RE.fullmatch(reporter):
        raise ReportError("reporter must be a lowercase agent slug")

    normalized_title, redactions = _normalize_text(title, "title", limit=200)
    normalized_title = " ".join(normalized_title.split())
    fields: dict[str, Any] = {}
    for field, value in (
        ("summary", summary),
        ("environment", environment),
        ("expected", expected),
        ("actual", actual),
        ("impact", impact),
        ("suggested_fix", suggested_fix),
    ):
        fields[field], count = _normalize_text(value, field)
        redactions += count
    fields["reproduction_steps"], count = _normalize_list(reproduction_steps, "reproduction_steps")
    redactions += count
    fields["evidence"], count = _normalize_list(evidence, "evidence")
    redactions += count

    now = staged_at or utc_now()
    observed = _parse_time(observed_at, "observed_at") if observed_at else now
    observed_iso = isoformat(observed)
    source_value, count = _normalize_text(source, "source", limit=2048)
    redactions += count
    markdown = render_markdown(
        report_kind=report_kind,
        title=normalized_title,
        reporter=reporter,
        source=source_value,
        observed_at=observed_iso,
        report=fields,
    )
    fingerprint = _report_fingerprint(report_kind, normalized_title, fields)
    report_id = fingerprint[:20]
    outbox = outbox.expanduser().resolve()
    pending = outbox / "pending"
    published = outbox / "published"
    max_per_hour = max_per_hour if max_per_hour is not None else _env_limit(
        "NYANKOFACE_ISSUE_REPORT_MAX_PER_HOUR", DEFAULT_MAX_PER_HOUR
    )
    max_per_day = max_per_day if max_per_day is not None else _env_limit(
        "NYANKOFACE_ISSUE_REPORT_MAX_PER_DAY", DEFAULT_MAX_PER_DAY
    )
    if max_per_hour < 1 or max_per_day < 1:
        raise ReportError("rate limits must be positive")

    entry: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "report_id": report_id,
        "fingerprint": fingerprint,
        "status": "pending",
        "report_kind": report_kind,
        "title": normalized_title,
        "reporter": reporter,
        "source": source_value,
        "observed_at": observed_iso,
        "staged_at": isoformat(now),
        "report": fields,
        "markdown": markdown,
        "dedupe_query": f'"{normalized_title.replace(chr(34), "")[:180]}" in:title',
        "redactions_applied": redactions,
    }

    with outbox_lock(outbox):
        pending.mkdir(parents=True, exist_ok=True)
        published.mkdir(parents=True, exist_ok=True)
        for path, existing in read_entries(outbox):
            if existing.get("fingerprint") == fingerprint:
                return {"status": "duplicate", "report_id": report_id, "path": str(path)}
        _enforce_rate_limit(outbox, reporter, now, max_per_hour, max_per_day)
        path = pending / f"{report_id}.json"
        _atomic_write(path, entry)
    return {"status": "staged", "report_id": report_id, "path": str(path), "redactions_applied": redactions}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    stage = subparsers.add_parser("stage", help="stage one sanitized report")
    stage.add_argument("--outbox", type=Path, help=f"shared outbox path; defaults to ${OUTBOX_ENV}")
    stage.add_argument("--kind", choices=("bug", "enhancement"), required=True)
    stage.add_argument("--title", required=True)
    stage.add_argument("--summary", required=True)
    stage.add_argument("--environment", required=True)
    stage.add_argument("--reproduction-step", action="append", dest="reproduction_steps", required=True)
    stage.add_argument("--expected", required=True)
    stage.add_argument("--actual", required=True)
    stage.add_argument("--impact", required=True)
    stage.add_argument("--evidence", action="append", required=True)
    stage.add_argument("--suggested-fix", required=True)
    stage.add_argument("--reporter", required=True)
    stage.add_argument("--source", required=True)
    stage.add_argument("--observed-at")
    stage.add_argument("--staged-at", help=argparse.SUPPRESS)
    stage.add_argument("--max-per-hour", type=int)
    stage.add_argument("--max-per-day", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command != "stage":
        raise ReportError("unknown command")
    staged_at = _parse_time(args.staged_at, "staged_at") if args.staged_at else None
    try:
        outbox = args.outbox or (Path(os.environ[OUTBOX_ENV]) if os.environ.get(OUTBOX_ENV) else None)
        if outbox is None:
            raise ReportError(f"set {OUTBOX_ENV} or pass --outbox")
        result = stage_report(
            outbox=outbox,
            report_kind=args.kind,
            title=args.title,
            summary=args.summary,
            environment=args.environment,
            reproduction_steps=args.reproduction_steps,
            expected=args.expected,
            actual=args.actual,
            impact=args.impact,
            evidence=args.evidence,
            suggested_fix=args.suggested_fix,
            reporter=args.reporter,
            source=args.source,
            observed_at=args.observed_at,
            staged_at=staged_at,
            max_per_hour=args.max_per_hour,
            max_per_day=args.max_per_day,
        )
    except ReportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
