from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from config import Settings


@dataclass(frozen=True)
class PullRequest:
    number: int
    url: str
    head_sha: str = ""


class ForgejoClient:
    def __init__(self, settings: Settings, token_file: Path | None = None):
        self.settings = settings
        self.token = (token_file or settings.forgejo_token_file).read_text(encoding="utf-8").strip()
        self.client = httpx.Client(
            base_url=settings.forgejo_api,
            headers={"Authorization": f"token {self.token}"},
            timeout=30,
        )

    def close(self) -> None:
        self.client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.client.request(method, path, **kwargs)
        response.raise_for_status()
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def existing_pull(self, owner: str, repo: str, branch: str) -> PullRequest | None:
        pulls = self._request("GET", f"/repos/{owner}/{repo}/pulls", params={"state": "open", "limit": 50})
        for pull in pulls:
            if pull.get("head", {}).get("ref") == branch:
                return PullRequest(
                    number=int(pull["number"]),
                    url=pull.get("html_url") or pull.get("url", ""),
                    head_sha=str((pull.get("head") or {}).get("sha") or ""),
                )
        return None

    def latest_open_pull(
        self, owner: str, repo: str, branch_prefix: str
    ) -> tuple[PullRequest, str] | None:
        pulls = self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls",
            params={"state": "open", "limit": 50},
        )
        matching = [
            pull
            for pull in pulls
            if str((pull.get("head") or {}).get("ref") or "").startswith(branch_prefix)
        ]
        if not matching:
            return None
        pull = max(matching, key=lambda item: int(item.get("number") or 0))
        branch = str((pull.get("head") or {}).get("ref") or "")
        return (
            PullRequest(
                number=int(pull["number"]),
                url=pull.get("html_url") or pull.get("url", ""),
                head_sha=str((pull.get("head") or {}).get("sha") or ""),
            ),
            branch,
        )

    def create_pull(
        self,
        owner: str,
        repo: str,
        base: str,
        branch: str,
        title: str,
        body: str,
    ) -> PullRequest:
        pull = self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            json={"base": base, "head": branch, "title": title[:240], "body": body},
        )
        return PullRequest(
            number=int(pull["number"]),
            url=pull.get("html_url") or pull.get("url", ""),
            head_sha=str((pull.get("head") or {}).get("sha") or ""),
        )

    def pull_head_sha(self, owner: str, repo: str, pull_number: int) -> str:
        pull = self._request("GET", f"/repos/{owner}/{repo}/pulls/{pull_number}")
        sha = str((pull.get("head") or {}).get("sha") or "")
        if not sha:
            raise RuntimeError(f"Forgejo returned no head SHA for PR #{pull_number}")
        return sha

    def merge_pull(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        *,
        expected_head_sha: str = "",
    ) -> None:
        payload: dict[str, Any] = {
            "Do": "merge",
            "delete_branch_after_merge": True,
        }
        if expected_head_sha:
            payload["head_commit_id"] = expected_head_sha
        self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pull_number}/merge",
            json=payload,
        )

    def comment_issue(self, owner: str, repo: str, issue_number: int, body: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            json={"body": body[:20_000]},
        )

    def create_issue(self, owner: str, repo: str, title: str, body: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues",
            json={"title": title[:240], "body": body[:20_000]},
        )

    def edit_issue_comment(self, owner: str, repo: str, comment_id: int, body: str) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/repos/{owner}/{repo}/issues/comments/{comment_id}",
            json={"body": body[:20_000]},
        )

    def upload_comment_attachment(
        self,
        owner: str,
        repo: str,
        comment_id: int,
        filename: str,
        content: bytes,
    ) -> dict[str, Any]:
        response = self.client.post(
            f"/repos/{owner}/{repo}/issues/comments/{comment_id}/assets",
            params={"name": filename},
            files={"attachment": (filename, content, "image/png")},
        )
        response.raise_for_status()
        return response.json()

    def react_to_issue(self, owner: str, repo: str, issue_number: int, content: str) -> None:
        response = self.client.post(
            f"/repos/{owner}/{repo}/issues/{issue_number}/reactions",
            json={"content": content},
        )
        # A repeated webhook may try to add the same reaction again. Forgejo
        # reports that as a conflict; the desired visible state already exists.
        if response.status_code not in {200, 201, 409}:
            response.raise_for_status()

    def issue(self, owner: str, repo: str, issue_number: int) -> dict[str, Any]:
        return self._request("GET", f"/repos/{owner}/{repo}/issues/{issue_number}")

    def repository_labels(self, owner: str, repo: str) -> dict[str, int]:
        labels: dict[str, int] = {}
        page = 1
        while True:
            batch = self._request(
                "GET",
                f"/repos/{owner}/{repo}/labels",
                params={"page": page, "limit": 50},
            )
            for label in batch:
                name = str(label.get("name") or "").strip().lower()
                label_id = int(label.get("id") or 0)
                if name and label_id:
                    labels[name] = label_id
            if len(batch) < 50:
                return labels
            page += 1

    def add_issue_labels(
        self, owner: str, repo: str, issue_number: int, labels: list[int]
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/labels",
            json={"labels": labels},
        )

    def pull_changed_files(
        self, owner: str, repo: str, pull_number: int
    ) -> list[str]:
        files = self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{pull_number}/files",
        )
        return [
            str(item.get("filename") or "").strip()
            for item in files
            if str(item.get("filename") or "").strip()
        ]

    def organization_repositories(self, owner: str) -> list[dict[str, Any]]:
        repositories: list[dict[str, Any]] = []
        page = 1
        while True:
            batch = self._request(
                "GET",
                f"/orgs/{owner}/repos",
                params={"page": page, "limit": 50},
            )
            repositories.extend(batch)
            if len(batch) < 50:
                return repositories
            page += 1

    def repository_topics(self, owner: str, repo: str) -> set[str]:
        payload = self._request("GET", f"/repos/{owner}/{repo}/topics")
        return {
            str(topic).strip().lower()
            for topic in (payload.get("topics") or [])
            if str(topic).strip()
        }

    def source_issue_number_for_pull(self, owner: str, repo: str, pull_number: int) -> int | None:
        pull = self._request("GET", f"/repos/{owner}/{repo}/pulls/{pull_number}")
        branch = str((pull.get("head") or {}).get("ref") or "")
        match = re.fullmatch(r"agent/issue-(\d+)", branch)
        return int(match.group(1)) if match else None

    def git_environment(self) -> dict[str, str]:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", "/home/maintainer"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.extraHeader",
            "GIT_CONFIG_VALUE_0": "Authorization: Basic "
            + base64.b64encode(f"glm-maintainer:{self.token}".encode()).decode(),
        }
        return env

    def clone_url(self, owner: str, repo: str) -> str:
        return f"{self.settings.forgejo_git_base}/{owner}/{repo}.git"
