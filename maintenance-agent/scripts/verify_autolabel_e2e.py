#!/usr/bin/env python3
"""Create one Issue and one docs-only PR, then verify automatic labels.

Run this inside the maintenance-agent container after the seed job has updated
the organization webhook:

    docker exec nyankoface-maintenance-agent \
      python /app/scripts/verify_autolabel_e2e.py

The script creates the repository labels explicitly as test fixtures. The
automatic labeler itself never creates a label and can only select labels that
already exist in the target repository.
"""

from __future__ import annotations

import argparse
import base64
import json
import time
from pathlib import Path
from typing import Any

import httpx


LABEL_FIXTURES = {
    "bug": "d73a4a",
    "enhancement": "2f81f7",
    "documentation": "8250df",
    "question": "a371f7",
    "good first issue": "7057ff",
}


class Forgejo:
    def __init__(self, api: str, token: str):
        self.client = httpx.Client(
            base_url=api.rstrip("/"),
            headers={"Authorization": f"token {token}"},
            timeout=30,
        )

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.client.request(method, path, **kwargs)
        response.raise_for_status()
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def close(self) -> None:
        self.client.close()


def ensure_labels(client: Forgejo, owner: str, repo: str) -> None:
    labels = client.request("GET", f"/repos/{owner}/{repo}/labels")
    existing = {str(label["name"]).lower() for label in labels}
    for name, color in LABEL_FIXTURES.items():
        if name in existing:
            continue
        client.request(
            "POST",
            f"/repos/{owner}/{repo}/labels",
            json={
                "name": name,
                "color": color,
                "description": "NyankoFace automatic-label E2E fixture",
            },
        )


def label_names(item: dict[str, Any]) -> list[str]:
    return sorted(str(label["name"]) for label in item.get("labels") or [])


def wait_for_labels(
    client: Forgejo,
    path: str,
    expected: set[str],
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        item = client.request("GET", path)
        if expected.issubset(set(label_names(item))):
            return item
        time.sleep(2)
    item = client.request("GET", path)
    raise RuntimeError(
        f"Timed out waiting for {sorted(expected)} on {path}; "
        f"found {label_names(item)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://forgejo:3000/api/v1")
    parser.add_argument("--token-file", type=Path, default=Path("/shared/token"))
    parser.add_argument("--owner", default="nyankoface")
    parser.add_argument("--repo", default="pages-starter")
    parser.add_argument("--base", default="main")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    token = args.token_file.read_text(encoding="utf-8").strip()
    client = Forgejo(args.api, token)
    suffix = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    branch = f"qa/autolabel-{suffix}"

    try:
        ensure_labels(client, args.owner, args.repo)

        issue = client.request(
            "POST",
            f"/repos/{args.owner}/{args.repo}/issues",
            json={
                "title": f"[QA {suffix}] ドキュメントの手順を確認したい",
                "body": (
                    "<!-- nyankoface-maintenance:skip -->\n\n"
                    "README の公開手順について質問です。どうすれば確認できますか？\n\n"
                    "自動ラベルのスクリーンショット検証用Issueです。"
                ),
            },
        )
        issue_number = int(issue["number"])
        issue = wait_for_labels(
            client,
            f"/repos/{args.owner}/{args.repo}/issues/{issue_number}",
            {"documentation", "question"},
            args.timeout,
        )

        client.request(
            "POST",
            f"/repos/{args.owner}/{args.repo}/branches",
            json={"new_branch_name": branch, "old_branch_name": args.base},
        )
        file_path = f"docs/auto-label-e2e-{suffix}.md"
        client.request(
            "POST",
            f"/repos/{args.owner}/{args.repo}/contents/{file_path}",
            json={
                "branch": branch,
                "message": f"docs: add auto-label E2E evidence {suffix}",
                "content": base64.b64encode(
                    (
                        "# Automatic label E2E evidence\n\n"
                        f"Generated at `{suffix}` by the reproducible verifier.\n"
                    ).encode("utf-8")
                ).decode("ascii"),
            },
        )
        pull = client.request(
            "POST",
            f"/repos/{args.owner}/{args.repo}/pulls",
            json={
                "base": args.base,
                "head": branch,
                "title": f"[QA {suffix}] neutral pull request title",
                "body": (
                    "<!-- nyankoface-maintenance:skip -->\n\n"
                    "Changed-file classification verification."
                ),
            },
        )
        pull_number = int(pull["number"])
        pull = wait_for_labels(
            client,
            f"/repos/{args.owner}/{args.repo}/issues/{pull_number}",
            {"documentation"},
            args.timeout,
        )

        print(
            json.dumps(
                {
                    "repository": f"{args.owner}/{args.repo}",
                    "issue": {
                        "number": issue_number,
                        "url": issue.get("html_url"),
                        "labels": label_names(issue),
                    },
                    "pull_request": {
                        "number": pull_number,
                        "url": pull.get("html_url"),
                        "branch": branch,
                        "changed_file": file_path,
                        "labels": label_names(pull),
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        client.close()


if __name__ == "__main__":
    main()
