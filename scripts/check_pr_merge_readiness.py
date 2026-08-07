#!/usr/bin/env python3
"""Block a PR merge until the current head is reviewed and checks are green."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any


PASSING_CONCLUSIONS = {"SUCCESS", "SKIPPED", "NEUTRAL"}
ACCEPTABLE_REVIEW_STATES = {"APPROVED", "COMMENTED"}
DEFAULT_REQUIRED_WORKFLOW = "CI"


@dataclass
class Readiness:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.errors


def evaluate(
    pr: dict[str, Any],
    reviews: list[dict[str, Any]],
    threads: list[dict[str, Any]],
    reviewer: str,
    allow_large_scope: str = "",
    initial_head: str = "",
    required_checks: tuple[str, ...] = ("validate",),
    required_workflow: str = DEFAULT_REQUIRED_WORKFLOW,
) -> Readiness:
    result = Readiness()
    head = str(pr.get("headRefOid") or "")
    if pr.get("isDraft"):
        result.errors.append("PR is still a draft.")
    if not head:
        result.errors.append("PR head SHA is unavailable.")
    if initial_head and initial_head != head:
        result.errors.append(
            "PR head changed while review state was collected "
            f"({initial_head[:12]} -> {head[:12]}). Run the guard again."
        )

    exact_head_reviews = [
        review
        for review in reviews
        if str((review.get("user") or {}).get("login") or "").lower()
        == reviewer.lower()
        and str(review.get("commit_id") or "") == head
    ]
    latest_review = max(
        exact_head_reviews,
        key=lambda review: (
            str(review.get("submitted_at") or ""),
            int(review.get("id") or 0),
        ),
        default=None,
    )
    latest_change_request = max(
        (
            review
            for review in exact_head_reviews
            if str(review.get("state") or "").upper() == "CHANGES_REQUESTED"
        ),
        key=lambda review: (
            str(review.get("submitted_at") or ""),
            int(review.get("id") or 0),
        ),
        default=None,
    )
    if latest_review is None:
        result.errors.append(
            f"{reviewer} has not completed a review on current head {head[:12]}."
        )
    elif latest_change_request is not None and not any(
        (
            str(review.get("submitted_at") or ""),
            int(review.get("id") or 0),
        )
        > (
            str(latest_change_request.get("submitted_at") or ""),
            int(latest_change_request.get("id") or 0),
        )
        and str(review.get("state") or "").upper()
        in {"APPROVED", "DISMISSED"}
        for review in exact_head_reviews
    ):
        result.errors.append(
            f"{reviewer}'s exact-head change request has not been cleared by "
            "a later approval or dismissal."
        )
    elif (
        str(latest_review.get("state") or "").upper()
        not in ACCEPTABLE_REVIEW_STATES
    ):
        result.errors.append(
            f"{reviewer}'s latest exact-head review is "
            f"{str(latest_review.get('state') or 'UNKNOWN').upper()}."
        )

    unresolved = [thread for thread in threads if not thread.get("isResolved")]
    if unresolved:
        result.errors.append(
            f"{len(unresolved)} review thread(s) are still unresolved."
        )

    checks = pr.get("statusCheckRollup") or []
    pending: list[str] = []
    failed: list[str] = []
    if not checks:
        result.errors.append("No CI checks are registered for the PR.")
    visible_check_names = set()
    for check in checks:
        name = str(check.get("name") or check.get("context") or "")
        workflow = str(check.get("workflowName") or "")
        details_url = str(check.get("detailsUrl") or "")
        if (
            name == "validate"
            and required_workflow
            and (
                workflow != required_workflow
                or "/actions/runs/" not in details_url
                or str(check.get("appSlug") or "") != "github-actions"
            )
        ):
            continue
        visible_check_names.add(name)
    missing_checks = [
        name for name in required_checks if name not in visible_check_names
    ]
    if missing_checks:
        result.errors.append(
            "Required CI checks are missing: " + ", ".join(missing_checks)
        )
    for check in checks:
        name = str(check.get("name") or check.get("context") or "unnamed check")
        status = str(check.get("status") or "").upper()
        conclusion = str(check.get("conclusion") or check.get("state") or "").upper()
        if status and status != "COMPLETED":
            pending.append(name)
        elif conclusion not in PASSING_CONCLUSIONS:
            failed.append(f"{name} ({conclusion or 'UNKNOWN'})")
    if pending:
        result.errors.append("Pending checks: " + ", ".join(pending))
    if failed:
        result.errors.append("Failing checks: " + ", ".join(failed))

    commit_value = pr.get("commits") or 0
    commit_count = (
        len(commit_value) if isinstance(commit_value, list) else int(commit_value)
    )
    scope = {
        "files": int(pr.get("changedFiles") or 0),
        "changes": int(pr.get("additions") or 0) + int(pr.get("deletions") or 0),
        "commits": commit_count,
    }
    exceeded = [
        f"{name}={value}>{limit}"
        for name, value, limit in (
            ("files", scope["files"], 25),
            ("changes", scope["changes"], 2_000),
            ("commits", scope["commits"], 20),
        )
        if value > limit
    ]
    if exceeded and not allow_large_scope.strip():
        result.errors.append(
            "PR scope budget exceeded ("
            + ", ".join(exceeded)
            + "); split the PR or pass --allow-large-scope with a reason."
        )
    elif exceeded:
        result.warnings.append(
            "Large PR explicitly accepted: "
            + allow_large_scope.strip()
            + " ("
            + ", ".join(exceeded)
            + ")."
        )
    return result


def _gh_json(args: list[str]) -> Any:
    completed = subprocess.run(
        ["gh", *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


def _load_threads(repo: str, number: int) -> list[dict[str, Any]]:
    owner, name = repo.split("/", 1)
    query = """
query($owner:String!, $name:String!, $number:Int!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    pullRequest(number:$number) {
      reviewThreads(first:100, after:$cursor) {
        nodes { id isResolved }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}"""
    threads: list[dict[str, Any]] = []
    cursor = ""
    while True:
        args = [
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-f",
            f"owner={owner}",
            "-f",
            f"name={name}",
            "-F",
            f"number={number}",
        ]
        if cursor:
            args.extend(["-f", f"cursor={cursor}"])
        payload = _gh_json(args)
        connection = payload["data"]["repository"]["pullRequest"]["reviewThreads"]
        threads.extend(connection["nodes"])
        if not connection["pageInfo"]["hasNextPage"]:
            return threads
        cursor = connection["pageInfo"]["endCursor"]


def _load_snapshot(
    repo: str, number: int, pr_fields: str
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    pr = _gh_json(
        ["pr", "view", str(number), "--repo", repo, "--json", pr_fields]
    )
    head = str(pr.get("headRefOid") or "")
    check_runs = _gh_json(
        ["api", f"repos/{repo}/commits/{head}/check-runs"]
    ).get("check_runs", [])
    identities = {
        (str(run.get("name") or ""), str(run.get("details_url") or "")): str(
            (run.get("app") or {}).get("slug") or ""
        )
        for run in check_runs
    }
    for check in pr.get("statusCheckRollup") or []:
        check["appSlug"] = identities.get(
            (
                str(check.get("name") or ""),
                str(check.get("detailsUrl") or ""),
            ),
            "",
        )
    review_pages = _gh_json(
        [
            "api",
            f"repos/{repo}/pulls/{number}/reviews",
            "--paginate",
            "--slurp",
        ]
    )
    reviews = [review for page in review_pages for review in page]
    comment_pages = _gh_json(
        [
            "api",
            f"repos/{repo}/issues/{number}/comments",
            "--paginate",
            "--slurp",
        ]
    )
    for page in comment_pages:
        for comment in page:
            synthetic = _clean_review_from_comment(comment, head)
            if synthetic is not None:
                reviews.append(synthetic)
    return pr, reviews, _load_threads(repo, number)


def _clean_review_from_comment(
    comment: dict[str, Any], head: str
) -> dict[str, Any] | None:
    if str((comment.get("user") or {}).get("login") or "").lower() != (
        "chatgpt-codex-connector[bot]"
    ):
        return None
    body = str(comment.get("body") or "")
    if "Codex Review: Didn't find any major issues." not in body:
        return None
    match = re.search(
        r"\*\*Reviewed commit:\*\* `([0-9a-fA-F]{7,40})`",
        body,
    )
    if match is None or not head.lower().startswith(match.group(1).lower()):
        return None
    return {
        "id": int(comment.get("id") or 0),
        "user": comment.get("user") or {},
        "commit_id": head,
        "state": "COMMENTED",
        "submitted_at": comment.get("created_at") or "",
    }


def _snapshot_signature(
    snapshot: tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]
) -> str:
    pr, reviews, threads = snapshot
    normalized = {
        "pr": pr,
        "reviews": [
            {
                "id": review.get("id"),
                "commit_id": review.get("commit_id"),
                "state": review.get("state"),
                "submitted_at": review.get("submitted_at"),
                "user": (review.get("user") or {}).get("login"),
            }
            for review in reviews
        ],
        "threads": threads,
    }
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="GitHub owner/repository")
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument(
        "--reviewer",
        default="chatgpt-codex-connector[bot]",
        help="Required reviewer login",
    )
    parser.add_argument(
        "--allow-large-scope",
        default="",
        metavar="REASON",
        help="Explicit reason for exceeding the PR scope budget",
    )
    parser.add_argument(
        "--required-check",
        action="append",
        default=None,
        help="Required CI context; repeat for multiple checks (default: validate)",
    )
    parser.add_argument(
        "--required-workflow",
        default=DEFAULT_REQUIRED_WORKFLOW,
        help="GitHub Actions workflow expected to own the validate check",
    )
    args = parser.parse_args()

    pr_fields = (
        "isDraft,headRefOid,statusCheckRollup,changedFiles,"
        "additions,deletions,commits"
    )
    previous_signature = ""
    snapshot = None
    for _ in range(3):
        candidate = _load_snapshot(args.repo, args.pr, pr_fields)
        signature = _snapshot_signature(candidate)
        if signature == previous_signature:
            snapshot = candidate
            break
        previous_signature = signature
    if snapshot is None:
        print(
            "BLOCKED: PR head, checks, reviews, or review threads changed while "
            "the readiness snapshot was collected. Run the guard again.",
            file=sys.stderr,
        )
        return 1
    pr, reviews, threads = snapshot
    result = evaluate(
        pr,
        reviews,
        threads,
        args.reviewer,
        args.allow_large_scope,
        str(pr.get("headRefOid") or ""),
        tuple(args.required_check or ["validate"]),
        args.required_workflow,
    )
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    if result.ready:
        print(
            f"READY: PR #{args.pr} head {pr['headRefOid'][:12]} is safe to merge."
        )
        return 0
    for error in result.errors:
        print(f"BLOCKED: {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
