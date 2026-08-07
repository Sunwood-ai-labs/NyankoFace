from __future__ import annotations

import json
import os
import signal
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from agents import AGENTS, AgentProfile, review_delegation_comment
from config import Settings
from forgejo import ForgejoClient, PullRequest


@dataclass(frozen=True)
class IssueTask:
    owner: str
    repo: str
    issue_number: int
    title: str
    body: str
    default_branch: str
    issue_url: str
    follow_up: bool = False
    instruction: str = ""
    agent_key: str = "coding"
    reply_number: int | None = None
    ui_evidence_required: bool = False
    branch_override: str = ""
    comparison_branch: str = ""
    trigger_kind: str = "issue"
    trigger_sha: str = ""
    auto_merge_allowed: bool = True
    humanless_cycle: int = 0
    humanless_attempt: int = 1
    automation_attempt: int = 1
    review_only: bool = False
    response_only: bool = False

    @property
    def branch(self) -> str:
        return self.branch_override or f"agent/issue-{self.issue_number}"

    @property
    def conversation_number(self) -> int:
        return self.reply_number or self.issue_number


@dataclass(frozen=True)
class AgentResult:
    pull: PullRequest | None
    summary: str
    changed_files: list[str]
    merged: bool = False
    review_verdict: str = ""
    review_summary: str = ""


@dataclass(frozen=True)
class UiTestResult:
    name: str
    viewport: str
    result: str
    details: str


@dataclass(frozen=True)
class UiScreenshot:
    filename: str
    caption: str
    viewport: str
    url: str
    width: int
    height: int
    content: bytes


@dataclass(frozen=True)
class UiEvidence:
    summary: str
    tests: list[UiTestResult]
    screenshots: list[UiScreenshot]


@dataclass(frozen=True)
class ReviewCheck:
    name: str
    result: str
    evidence: str


@dataclass(frozen=True)
class ReviewFinding:
    severity: str
    title: str
    location: str
    details: str
    remediation: str


@dataclass(frozen=True)
class ReviewEvidence:
    verdict: str
    reviewed_sha: str
    summary: str
    requirements: list[ReviewCheck]
    checks: list[ReviewCheck]
    findings: list[ReviewFinding]
    screenshots: list[UiScreenshot]


class MaintenanceWorker:
    def __init__(self, settings: Settings):
        self.settings = settings

    def run(self, task: IssueTask) -> AgentResult:
        forgejo = ForgejoClient(self.settings)
        profile = AGENTS[task.agent_key]
        worktree = self.settings.workspace_dir / f"{task.owner}-{task.repo}-{task.issue_number}"
        try:
            existing = forgejo.existing_pull(task.owner, task.repo, task.branch)
            if existing and not task.follow_up and not task.review_only:
                return AgentResult(existing, "既存のメンテナンスPRを再利用しました。", [])
            if worktree.exists():
                shutil.rmtree(worktree)
            self.settings.workspace_dir.mkdir(parents=True, exist_ok=True)
            self._git(
                forgejo,
                None,
                "clone",
                "--branch",
                task.branch if existing else task.default_branch,
                forgejo.clone_url(task.owner, task.repo),
                str(worktree),
            )
            if not existing:
                self._git(forgejo, worktree, "checkout", "-b", task.branch)
            base_revision = self._git(forgejo, worktree, "rev-parse", "HEAD").strip()
            self._prepare_goal_workspace(worktree)

            if task.response_only:
                before = self._tracked_state(worktree)
                self._run_claude_prompt(worktree, self._response_prompt(task))
                after = self._tracked_state(worktree)
                if before != after:
                    raise RuntimeError(
                        "Answer-only Issue investigation modified tracked files"
                    )
                answer = self._collect_response_evidence(worktree)
                agent_client = ForgejoClient(
                    self.settings, self.settings.agent_token_file(profile.username)
                )
                try:
                    self._publish_response_comment(
                        agent_client, task, profile, answer
                    )
                finally:
                    agent_client.close()
                return AgentResult(None, answer["answer"], [])

            if task.review_only:
                if existing is None:
                    raise RuntimeError("Review recovery requires an existing open PR")
                changed = [
                    item
                    for item in self._git(
                        forgejo,
                        worktree,
                        "diff",
                        "--name-only",
                        f"origin/{task.default_branch}...HEAD",
                    ).splitlines()
                    if item.strip()
                ]
                if not changed:
                    raise RuntimeError("Review recovery PR has no changes against its base")
                review = self._run_independent_review(
                    forgejo, worktree, task, profile, existing, changed
                )
                merged = self._merge_if_approved(forgejo, task, existing, review)
                return AgentResult(
                    existing,
                    "公開済みPRを再利用し、独立レビューを再実行しました。",
                    changed,
                    merged=merged,
                    review_verdict=review.verdict,
                    review_summary=review.summary,
                )

            summary = self._run_claude_goal(worktree, task)

            # Claude is asked not to commit, but normalize any local commits it made.
            current_revision = self._git(forgejo, worktree, "rev-parse", "HEAD").strip()
            if current_revision != base_revision:
                self._git(forgejo, worktree, "reset", "--soft", base_revision)
            changed = self._changed_files(worktree)
            reuse_existing_head = bool(existing and task.follow_up and not changed)
            if reuse_existing_head:
                changed = [
                    item
                    for item in self._git(
                        forgejo,
                        worktree,
                        "diff",
                        "--name-only",
                        f"origin/{task.default_branch}...HEAD",
                    ).splitlines()
                    if item.strip()
                ]
                if not changed:
                    raise RuntimeError("Existing follow-up PR has no changes against its base")
                ui_evidence = None
            else:
                ui_evidence = self._collect_ui_evidence(worktree, task)
            if not changed and task.agent_key == "review" and existing:
                agent_client = ForgejoClient(self.settings, self.settings.agent_token_file(profile.username))
                try:
                    self._publish_completion_comment(
                        agent_client,
                        task,
                        profile,
                        existing,
                        [],
                        ui_evidence,
                        "独立レビュー完了（追加変更なし）",
                    )
                finally:
                    agent_client.close()
                return AgentResult(existing, summary, [])
            if not reuse_existing_head:
                self._validate_worktree(worktree, changed)
                self._git(forgejo, worktree, "config", "user.name", profile.display_name)
                self._git(forgejo, worktree, "config", "user.email", f"{profile.username}@agents.nyankoface.local")
                self._git(forgejo, worktree, "add", "--all")
                commit_message = (
                    f"chore: audit release {task.default_branch}"
                    if task.trigger_kind == "release"
                    else
                    f"fix: apply follow-up for issue #{task.issue_number}"
                    if task.follow_up
                    else f"fix: resolve issue #{task.issue_number}"
                )
                self._git(forgejo, worktree, "commit", "-m", commit_message)
                self._git(forgejo, worktree, "push", "origin", f"HEAD:refs/heads/{task.branch}")
            agent_client = ForgejoClient(self.settings, self.settings.agent_token_file(profile.username))
            try:
                pull = existing or agent_client.create_pull(
                    task.owner,
                    task.repo,
                    task.default_branch,
                    task.branch,
                    f"[Claude Goal + GLM] {task.title}",
                    self._pull_body(task, summary, changed),
                )
                comment_id, comment_body = self._publish_completion_comment(
                    agent_client,
                    task,
                    profile,
                    pull,
                    changed,
                    ui_evidence,
                    "独立レビュー待ち",
                )
            except Exception:
                agent_client.close()
                raise
            review = None
            merged = False
            try:
                if task.agent_key != "review":
                    review = self._run_independent_review(
                        forgejo, worktree, task, profile, pull, changed
                    )
                merged = self._merge_if_approved(forgejo, task, pull, review)
                if merged:
                    agent_client.edit_issue_comment(
                        task.owner,
                        task.repo,
                        comment_id,
                        comment_body.replace(
                            "独立レビュー待ち",
                            "独立レビュー承認済み・自動マージ済み",
                        ),
                    )
                elif review is not None and review.verdict == "rejected":
                    agent_client.edit_issue_comment(
                        task.owner,
                        task.repo,
                        comment_id,
                        comment_body.replace("独立レビュー待ち", "独立レビューで差し戻し"),
                    )
                    forgejo.comment_issue(
                        task.owner,
                        task.repo,
                        task.conversation_number,
                        f"🧭 @{profile.username} 独立レビューで差し戻されました。"
                        + "\n\n次の失敗項目・指摘を修正し、メンテナーへ再レビューを依頼してください。\n\n"
                        + self._rejection_feedback(review),
                    )
            finally:
                agent_client.close()
            return AgentResult(
                pull, summary, changed, merged=merged,
                review_verdict=review.verdict if review is not None else "",
                review_summary=review.summary if review is not None else "",
            )
        finally:
            forgejo.close()
            if worktree.exists():
                shutil.rmtree(worktree, ignore_errors=True)

    @staticmethod
    def _rejection_feedback(review: ReviewEvidence) -> str:
        lines = [
            f"- **failed requirement**: {item.name} — {item.evidence}"
            for item in review.requirements
            if item.result == "failed"
        ]
        lines.extend(
            f"- **failed check**: {item.name} — {item.evidence}"
            for item in review.checks
            if item.result == "failed"
        )
        lines.extend(
            f"- **{item.severity}**: {item.title} (`{item.location}`) — "
            f"{item.details} / 修正条件: {item.remediation}"
            for item in review.findings
        )
        return "\n".join(lines) or "- レビュー結果を再確認し、承認条件を満たしてください。"

    def _merge_if_approved(
        self,
        forgejo: ForgejoClient,
        task: IssueTask,
        pull: PullRequest,
        review: ReviewEvidence | None,
    ) -> bool:
        if not self.settings.auto_merge or review is None or review.verdict != "approved":
            return False
        if not task.auto_merge_allowed:
            return False
        current_head = forgejo.pull_head_sha(task.owner, task.repo, pull.number)
        if current_head != review.reviewed_sha:
            raise RuntimeError("PR head changed after independent review; refusing stale approval")
        forgejo.merge_pull(
            task.owner,
            task.repo,
            pull.number,
            expected_head_sha=review.reviewed_sha,
        )
        return True

    def _git(self, client: ForgejoClient, cwd: Path | None, *args: str) -> str:
        git_args = ["-c", f"safe.directory={cwd.resolve()}", *args] if cwd else list(args)
        process = subprocess.run(
            ["git", *git_args],
            cwd=cwd,
            env=client.git_environment(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=300,
        )
        if process.returncode != 0:
            output = process.stdout[-4000:].replace(client.token, "<redacted>")
            raise RuntimeError(f"git {' '.join(args[:2])} failed: {output}")
        return process.stdout

    def _prepare_goal_workspace(self, worktree: Path) -> None:
        if getattr(os, "geteuid", lambda: -1)() == 0:
            subprocess.run(
                ["chown", "-R", f"{self.settings.claude_user}:{self.settings.claude_user}", str(worktree)],
                check=True,
                timeout=120,
            )

    def _collect_ui_evidence(self, root: Path, task: IssueTask) -> UiEvidence | None:
        evidence_root = root / ".nyankoface-maintenance"
        report_path = evidence_root / "ui-report.json"
        if not report_path.is_file():
            if task.ui_evidence_required:
                raise RuntimeError(
                    "UI/app task did not produce .nyankoface-maintenance/ui-report.json with screenshots and UI tests"
                )
            return None
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"UI evidence report is invalid: {exc}") from exc

        raw_tests = payload.get("tests")
        raw_screenshots = payload.get("screenshots")
        if not isinstance(raw_tests, list) or not raw_tests:
            raise RuntimeError("UI evidence must list at least one executed UI test")
        if not isinstance(raw_screenshots, list) or len(raw_screenshots) < 2:
            raise RuntimeError("UI evidence must include mobile and desktop screenshots")
        if len(raw_screenshots) > 8:
            raise RuntimeError("UI evidence may include at most eight screenshots")

        tests: list[UiTestResult] = []
        for item in raw_tests:
            if not isinstance(item, dict):
                raise RuntimeError("Every UI test entry must be an object")
            result = str(item.get("result") or "").strip().lower()
            if result != "passed":
                raise RuntimeError(f"UI test did not pass: {item.get('name') or 'unnamed'}")
            name = str(item.get("name") or "").strip()
            details = str(item.get("details") or "").strip()
            if not name or not details:
                raise RuntimeError("Every UI test must include a name and concrete details")
            tests.append(
                UiTestResult(
                    name=name[:160],
                    viewport=str(item.get("viewport") or "—")[:40],
                    result="passed",
                    details=details[:600],
                )
            )

        screenshots_dir = (evidence_root / "screenshots").resolve()
        screenshots: list[UiScreenshot] = []
        for index, item in enumerate(raw_screenshots):
            if not isinstance(item, dict):
                raise RuntimeError("Every screenshot entry must be an object")
            relative = str(item.get("path") or "").strip()
            if not relative:
                name = str(item.get("name") or "").strip()
                if not name or Path(name).name != name:
                    raise RuntimeError("Every UI screenshot must include a safe path or filename")
                relative = str(Path(".nyankoface-maintenance") / "screenshots" / name)
            candidate = (root / relative).resolve(strict=False)
            if screenshots_dir != candidate and screenshots_dir not in candidate.parents:
                raise RuntimeError(f"UI screenshot must stay under .nyankoface-maintenance/screenshots: {relative}")
            try:
                content = candidate.read_bytes()
            except OSError as exc:
                raise RuntimeError(f"UI screenshot is missing: {relative}") from exc
            if len(content) > 10 * 1024 * 1024:
                raise RuntimeError(f"UI screenshot is larger than 10 MiB: {relative}")
            if len(content) < 24 or content[:8] != b"\x89PNG\r\n\x1a\n":
                raise RuntimeError(f"UI screenshot is not a valid PNG: {relative}")
            width, height = struct.unpack(">II", content[16:24])
            if width < 200 or height < 200:
                raise RuntimeError(f"UI screenshot is too small to review: {relative} ({width}x{height})")
            screenshots.append(
                UiScreenshot(
                    filename=f"ui-{index + 1}-{candidate.name}"[:240],
                    caption=str(item.get("caption") or candidate.stem)[:240],
                    viewport=str(item.get("viewport") or f"{width}x{height}")[:40],
                    url=str(item.get("url") or "")[:500],
                    width=width,
                    height=height,
                    content=content,
                )
            )
        if not any(shot.width <= 480 for shot in screenshots):
            raise RuntimeError("UI evidence is missing a mobile screenshot (width <= 480px)")
        if not any(shot.width >= 1024 for shot in screenshots):
            raise RuntimeError("UI evidence is missing a desktop screenshot (width >= 1024px)")

        raw_summary = payload.get("summary") or "UI変更を実画面で検証しました。"
        summary = (
            json.dumps(raw_summary, ensure_ascii=False, separators=(",", ": "))
            if isinstance(raw_summary, dict)
            else str(raw_summary)
        )
        evidence = UiEvidence(
            summary=summary[:1200],
            tests=tests,
            screenshots=screenshots,
        )
        shutil.rmtree(evidence_root)
        return evidence

    def _run_independent_review(
        self,
        maintainer_client: ForgejoClient,
        worktree: Path,
        task: IssueTask,
        implementation_profile: AgentProfile,
        pull: PullRequest,
        changed: list[str],
    ) -> ReviewEvidence:
        reviewer = AGENTS["review"]
        implementation_token = self.settings.agent_token_file(
            implementation_profile.username
        ).read_text(encoding="utf-8").strip()
        reviewer_token = self.settings.agent_token_file(reviewer.username).read_text(
            encoding="utf-8"
        ).strip()
        if not reviewer_token or reviewer_token == implementation_token:
            raise RuntimeError(
                "Independent reviewer must use a non-empty token distinct from the implementer"
            )
        maintainer_client.comment_issue(
            task.owner,
            task.repo,
            task.conversation_number,
            review_delegation_comment(
                implementation_profile,
                pull.number,
                pull.url,
                ui_review_required=task.ui_evidence_required,
            ),
        )
        reviewer_client = ForgejoClient(
            self.settings, self.settings.agent_token_file(reviewer.username)
        )
        try:
            reviewer_client.react_to_issue(
                task.owner, task.repo, task.conversation_number, "eyes"
            )
            reviewed_sha = maintainer_client.pull_head_sha(task.owner, task.repo, pull.number)
            local_sha = self._git(maintainer_client, worktree, "rev-parse", "HEAD").strip()
            if reviewed_sha != local_sha:
                raise RuntimeError("Local review checkout does not match current PR head")
            before = self._tracked_state(worktree)
            self._run_claude_prompt(
                worktree, self._review_prompt(task, pull, changed, reviewed_sha)
            )
            after = self._tracked_state(worktree)
            if before != after:
                raise RuntimeError("Independent reviewer modified tracked files; review must be read-only")
            evidence = self._collect_review_evidence(worktree, task, reviewed_sha)
            self._publish_review_comment(reviewer_client, task, pull, evidence)
            reviewer_client.react_to_issue(
                task.owner,
                task.repo,
                task.conversation_number,
                "+1" if evidence.verdict == "approved" else "-1",
            )
            return evidence
        finally:
            reviewer_client.close()

    def _tracked_state(self, root: Path) -> str:
        process = subprocess.run(
            ["git", "-c", f"safe.directory={root.resolve()}", "status", "--short", "--untracked-files=no"],
            cwd=root, check=True, text=True, capture_output=True, timeout=30,
        )
        return process.stdout

    def _collect_response_evidence(self, root: Path) -> dict[str, object]:
        report_path = root / ".nyankoface-maintenance" / "response-report.json"
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Answer-only response report is missing or invalid: {exc}"
            ) from exc
        summary = str(payload.get("summary") or "").strip()
        answer = str(payload.get("answer") or "").strip()
        confidence = str(payload.get("confidence") or "").strip().lower()
        references = payload.get("references")
        if not summary or not answer:
            raise RuntimeError("Answer-only response requires summary and answer")
        if confidence not in {"high", "medium", "low"}:
            raise RuntimeError(
                "Answer-only response confidence must be high, medium, or low"
            )
        if not isinstance(references, list) or not references:
            raise RuntimeError(
                "Answer-only response must include repository references"
            )
        clean_references: list[dict[str, str]] = []
        for item in references[:12]:
            if not isinstance(item, dict):
                raise RuntimeError("Every answer reference must be an object")
            path = str(item.get("path") or "").strip()
            reason = str(item.get("reason") or "").strip()
            if not path or not reason or Path(path).is_absolute() or ".." in Path(path).parts:
                raise RuntimeError("Every answer reference needs a safe path and reason")
            clean_references.append({"path": path[:300], "reason": reason[:600]})
        shutil.rmtree(root / ".nyankoface-maintenance", ignore_errors=True)
        return {
            "summary": summary[:1200],
            "answer": answer[:12_000],
            "confidence": confidence,
            "references": clean_references,
        }

    def _publish_response_comment(
        self,
        client: ForgejoClient,
        task: IssueTask,
        profile: AgentProfile,
        evidence: dict[str, object],
    ) -> None:
        references = "\n".join(
            f"- `{item['path']}` — {item['reason']}"
            for item in evidence["references"]
        )
        client.comment_issue(
            task.owner,
            task.repo,
            task.conversation_number,
            f"確認結果です。\n\n{evidence['answer']}\n\n"
            f"### 根拠\n\n{references}\n\n"
            f"- 確信度: `{evidence['confidence']}`\n"
            "- 実行: Claude Code `/goal` + "
            f"`{self.settings.model}`\n"
            "- 追跡対象ファイルの変更: なし",
        )

    def _response_prompt(self, task: IssueTask) -> str:
        profile = AGENTS[task.agent_key]
        return f"""/goal [問い合わせの自動調査] Forgejo Issue #{task.issue_number} に回答してください。

あなたは **{profile.display_name}** です。リポジトリを読み取り専用で調査し、
推測ではなく現在のコード、設定、README、docs、test、履歴を根拠に日本語で回答してください。

Issueタイトル: {task.title}
Issue URL: {task.issue_url}
Issue本文:
<issue>
{task.body}
</issue>

制約:
- tracked fileを編集、commit、pushしてはいけない。
- Forgejo認証情報へアクセスしてはいけない。
- 必要なread-only commandやtestは有限timeout付きで実行できる。
- 不明な点は断定せず、何が確認でき何が確認できないかを明示する。
- `.nyankoface-maintenance/response-report.json` だけを次の形式で作成する。

```json
{{
  "summary": "調査内容の短い要約",
  "answer": "Issueへ投稿する自己完結した日本語回答",
  "confidence": "high または medium または low",
  "references": [
    {{"path": "README.md", "reason": "回答を裏付ける具体的な理由"}}
  ]
}}
```
"""

    def _collect_review_evidence(
        self, root: Path, task: IssueTask, expected_sha: str
    ) -> ReviewEvidence:
        evidence_root = root / ".nyankoface-maintenance"
        report_path = evidence_root / "review-report.json"
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Independent review report is missing or invalid: {exc}") from exc
        verdict = str(payload.get("verdict") or "").strip().lower()
        if verdict not in {"approved", "rejected"}:
            raise RuntimeError("Independent review verdict must be approved or rejected")
        reviewed_sha = str(payload.get("reviewed_sha") or "").strip()
        if reviewed_sha != expected_sha:
            raise RuntimeError("Independent review report does not match the current PR head SHA")
        summary = str(payload.get("summary") or "").strip()
        if not summary:
            raise RuntimeError("Independent review must include a summary")

        def checks(key: str, allowed_states: set[str]) -> list[ReviewCheck]:
            values = payload.get(key)
            if not isinstance(values, list) or not values:
                raise RuntimeError(f"Independent review must include {key}")
            result: list[ReviewCheck] = []
            for item in values:
                if not isinstance(item, dict):
                    raise RuntimeError(f"Every {key} entry must be an object")
                name = str(item.get("name") or "").strip()
                state = str(item.get("result") or "").strip().lower()
                proof = str(item.get("evidence") or "").strip()
                if not name or state not in allowed_states or not proof:
                    allowed = "/".join(sorted(allowed_states))
                    raise RuntimeError(
                        f"Every {key} entry needs name, {allowed}, and evidence"
                    )
                result.append(ReviewCheck(name[:160], state, proof[:800]))
            return result

        requirements = checks("requirements", {"passed", "failed"})
        executed_checks = checks("checks", {"passed", "failed", "baseline"})
        raw_findings = payload.get("findings")
        if not isinstance(raw_findings, list):
            raise RuntimeError("Independent review must include a findings list")
        findings: list[ReviewFinding] = []
        for item in raw_findings:
            if not isinstance(item, dict):
                raise RuntimeError("Every review finding must be an object")
            severity = str(item.get("severity") or "").strip().lower()
            title = str(item.get("title") or "").strip()
            location = str(item.get("location") or "").strip()
            details = str(item.get("details") or "").strip()
            remediation = str(item.get("remediation") or "").strip()
            if (
                severity not in {"critical", "high", "medium", "low"}
                or not title or not location or not details or not remediation
            ):
                raise RuntimeError(
                    "Every finding needs severity, title, location, details, and remediation"
                )
            findings.append(
                ReviewFinding(
                    severity, title[:200], location[:300], details[:1000], remediation[:1000]
                )
            )
        failed = any(item.result == "failed" for item in requirements + executed_checks)
        blocking = bool(findings)
        if verdict == "approved" and (failed or blocking):
            verdict = "rejected"
            summary = (
                "レビュワー出力は承認を申告しましたが、failed項目または指摘が残っているため、"
                "ラッパーが安全側へ差し戻しました。\n\n" + summary
            )
        if verdict == "rejected" and not (failed or findings):
            raise RuntimeError("Reviewer rejected without a failed check or actionable finding")

        screenshots: list[UiScreenshot] = []
        if task.ui_evidence_required:
            screenshots = self._review_screenshots(root, payload)
        shutil.rmtree(evidence_root, ignore_errors=True)
        return ReviewEvidence(
            verdict, reviewed_sha, summary[:1600], requirements, executed_checks, findings, screenshots
        )

    def _review_screenshots(self, root: Path, payload: dict[str, object]) -> list[UiScreenshot]:
        raw = payload.get("screenshots")
        if not isinstance(raw, list) or len(raw) < 2:
            raise RuntimeError("UI review requires independent mobile and desktop screenshots")
        allowed = (root / ".nyankoface-maintenance" / "review-screenshots").resolve()
        screenshots: list[UiScreenshot] = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                raise RuntimeError("Every review screenshot must be an object")
            relative = str(item.get("path") or "")
            candidate = (root / relative).resolve(strict=False)
            if allowed != candidate and allowed not in candidate.parents:
                raise RuntimeError("Review screenshots must stay under review-screenshots")
            content = candidate.read_bytes()
            if len(content) < 24 or content[:8] != b"\x89PNG\r\n\x1a\n":
                raise RuntimeError(f"Review screenshot is not a valid PNG: {relative}")
            width, height = struct.unpack(">II", content[16:24])
            screenshots.append(UiScreenshot(
                f"review-{index + 1}-{candidate.name}"[:240],
                str(item.get("caption") or candidate.stem)[:240],
                str(item.get("viewport") or f"{width}x{height}")[:40],
                str(item.get("url") or "")[:500], width, height, content,
            ))
        if not any(shot.width <= 480 for shot in screenshots):
            raise RuntimeError("UI review is missing a mobile screenshot")
        if not any(shot.width >= 1024 for shot in screenshots):
            raise RuntimeError("UI review is missing a desktop screenshot")
        return screenshots

    def _publish_review_comment(
        self,
        client: ForgejoClient,
        task: IssueTask,
        pull: PullRequest,
        evidence: ReviewEvidence,
    ) -> tuple[int, str]:
        verdict_label = "✅ 承認" if evidence.verdict == "approved" else "⛔ 却下・差し戻し"
        requirement_rows = "\n".join(
            f"| {self._table_cell(item.name)} | {'✅' if item.result == 'passed' else '❌'} {item.result} | {self._table_cell(item.evidence)} |"
            for item in evidence.requirements
        )
        check_icons = {"passed": "✅", "failed": "❌", "baseline": "⚠️"}
        check_rows = "\n".join(
            f"| {self._table_cell(item.name)} | {check_icons[item.result]} {item.result} | {self._table_cell(item.evidence)} |"
            for item in evidence.checks
        )
        finding_rows = "\n".join(
            f"| `{item.severity}` | {self._table_cell(item.title)} | {self._table_cell(item.location)} | "
            f"{self._table_cell(item.details)} | {self._table_cell(item.remediation)} |"
            for item in evidence.findings
        ) or "| — | 指摘なし | — | ブロッキング指摘はありません。 | — |"
        reviewed_sha = evidence.reviewed_sha.strip()
        short_sha = reviewed_sha[:12]
        repository_url = pull.url.rsplit("/pulls/", 1)[0]
        commit_url = f"{repository_url}/commit/{reviewed_sha}"
        summary = self._review_summary(evidence.summary)
        body = (
            f"[PR #{pull.number}]({pull.url}) の独立レビュー結果です。\n\n"
            f"- 判定: **{verdict_label}**\n"
            f"- レビュー対象: [`{short_sha}`]({commit_url})\n"
            f"- 実行: Claude Code `/goal` + `{self.settings.model}`\n"
            "- 独立性: 実装担当とは別アカウント・読み取り専用レビュー\n\n"
            f"### レビュー概要\n\n{summary}\n\n"
            "### 要件トレーサビリティ\n\n| 要件 | 結果 | 根拠 |\n|---|---|---|\n"
            f"{requirement_rows}\n\n### 実行した検証\n\n| 検証 | 結果 | 根拠 |\n|---|---|---|\n"
            f"{check_rows}\n\n### 指摘\n\n| 重大度 | 指摘 | 場所 | 詳細 | 修正条件 |\n"
            f"|---|---|---|---|---|\n{finding_rows}"
        )
        if evidence.screenshots:
            body += "\n\n### レビュワー独自スクリーンショット\n\nアップロード中です。"
        comment = client.comment_issue(task.owner, task.repo, task.conversation_number, body)
        comment_id = int(comment["id"])
        if evidence.screenshots:
            images = []
            for shot in evidence.screenshots:
                attachment = client.upload_comment_attachment(
                    task.owner, task.repo, comment_id, shot.filename, shot.content
                )
                url = str(attachment.get("browser_download_url") or attachment.get("url") or "")
                if not url:
                    raise RuntimeError("Forgejo returned no reviewer screenshot URL")
                images.append(f"**{shot.caption}** — {shot.viewport} / PNG {shot.width}x{shot.height}\n\n![{shot.caption}]({url})")
            body = body.replace("アップロード中です。", "\n\n".join(images))
            client.edit_issue_comment(task.owner, task.repo, comment_id, body)
        return comment_id, body

    @staticmethod
    def _table_cell(value: str) -> str:
        return " ".join(value.replace("|", "\\|").split())

    @staticmethod
    def _review_summary(value: str, limit: int = 360) -> str:
        summary = " ".join(value.split())
        for prefix in (
            "独立レビュー(review-agent)として",
            "独立レビュー（review-agent）として",
            "独立レビュアー(review-agent)として",
            "独立レビュアー（review-agent）として",
            "review-agentとして",
        ):
            if summary.startswith(prefix):
                summary = summary[len(prefix):].lstrip(" 、。")
                break
        parts = [sentence.strip() for sentence in summary.split("。") if sentence.strip()]
        if len(summary) <= limit and len(parts) <= 3:
            return summary
        sentences: list[str] = []
        length = 0
        for sentence in parts:
            candidate = f"{sentence}。"
            if sentences and length + len(candidate) > limit:
                break
            sentences.append(candidate)
            length += len(candidate)
            if len(sentences) >= 3:
                break
        if sentences:
            return "".join(sentences)
        return f"{summary[:limit].rstrip()}…"

    def _publish_completion_comment(
        self,
        client: ForgejoClient,
        task: IssueTask,
        profile: AgentProfile,
        pull: PullRequest,
        changed: list[str],
        evidence: UiEvidence | None,
        status: str,
    ) -> tuple[int, str]:
        changed_text = ", ".join(f"`{path}`" for path in changed) or "なし"
        body = (
            "担当作業が完了しました。\n\n"
            f"- PR: [#{pull.number}]({pull.url})\n"
            f"- 変更ファイル: {changed_text}\n"
            f"- 実行: Claude Code `/goal` + `{self.settings.model}`\n"
            f"- 状態: {status}"
        )
        if evidence:
            rows = "\n".join(
                f"| {self._table_cell(test.name)} | {self._table_cell(test.viewport)} | ✅ passed | "
                f"{self._table_cell(test.details)} |"
                for test in evidence.tests
            )
            body += (
                f"\n\n### UIテスト\n\n{evidence.summary}\n\n"
                "| テスト | viewport | 結果 | 確認内容 |\n"
                "|---|---:|---|---|\n"
                f"{rows}\n\n### スクリーンショット\n\n添付画像をアップロード中です。"
            )
        comment = client.comment_issue(task.owner, task.repo, task.conversation_number, body)
        comment_id = int(comment["id"])
        if evidence:
            images: list[str] = []
            for shot in evidence.screenshots:
                attachment = client.upload_comment_attachment(
                    task.owner,
                    task.repo,
                    comment_id,
                    shot.filename,
                    shot.content,
                )
                url = str(
                    attachment.get("browser_download_url")
                    or attachment.get("download_url")
                    or attachment.get("url")
                    or ""
                )
                if not url:
                    raise RuntimeError(f"Forgejo returned no URL for UI screenshot {shot.filename}")
                meta = f"{shot.viewport} / PNG {shot.width}x{shot.height}"
                if shot.url:
                    meta += f" / `{shot.url}`"
                images.append(f"**{shot.caption}** — {meta}\n\n![{shot.caption}]({url})")
            body = body.replace("添付画像をアップロード中です。", "\n\n".join(images))
            client.edit_issue_comment(task.owner, task.repo, comment_id, body)
        return comment_id, body

    def _goal_prompt(self, task: IssueTask) -> str:
        profile = AGENTS[task.agent_key]
        release_context = ""
        if task.trigger_kind == "release":
            comparison = task.comparison_branch or "main"
            release_notes_contract = ""
            if task.agent_key == "docs":
                release_notes_contract = """
- branch名からversionを導出し、実際のdiff、変更ファイル、commit履歴、tag履歴を根拠に
  `RELEASE_NOTES.md` と既存docs構造に合うversion別リリースページを作成または更新する。
- リリースノートは利用者への影響、新機能、修正、破壊的変更、移行手順、検証結果を、
  該当するものだけ具体的に記載する。commit件名の羅列や根拠のない成功主張は禁止する。
- docsが複数localeを持つ場合は全localeを更新し、READMEと主要な運用文書もtruth-syncする。
"""
            release_context = f"""
リリースブランチ監査:
- 対象ブランチ: `{task.default_branch}`
- pushされたcommit: `{task.trigger_sha}`
- 比較元ブランチ: `{comparison}`
- 最初に `git diff origin/{comparison}...HEAD` とcommit履歴を読み、リリース差分全体を監査する。
- 問題があれば専門領域の範囲で修正する。問題がなくても、実施した確認、コマンド、根拠、残余リスクを
  `docs/release-audits/` 以下のMarkdownへ記録し、必ずレビュー可能なPR差分を作る。
- この監査PRは `{task.default_branch}` 向けに作成され、独立reviewの承認後にメンテナーが自動マージする。
{release_notes_contract}
"""
        if task.trigger_kind == "humanless":
            release_context = f"""
自動運用:
- cycle: `{task.humanless_cycle}`
- attempt: `{task.humanless_attempt}`
- このIssue、担当割当、実装、独立レビュー、マージは自動化されている。
- 初期開発ではREADME、リポジトリ説明、既存ファイルを製品briefとして、実際に利用できる最小製品を完成させる。
- 運用保守では現状、履歴、テスト、依存関係、利用者体験を調査し、担当領域で最も価値が高い改善を1つ選んで完遂する。
- 変更を小さく保つこと自体を目的にせず、選んだ改善をテスト・文書・運用可能性まで完成させる。
- 「人間に確認してください」「後で対応」では完了にしない。安全に実行可能な判断は自律的に行う。
- 独立reviewが却下した場合は、指摘を取り込んだ再試行が自動で行われる。
- 現在head SHAへの独立承認が得られた場合のみメンテナーが自動マージする。
"""
        follow_up = ""
        if task.follow_up:
            follow_up = f"""
今回の追加指示:
<follow-up>
{task.instruction}
</follow-up>
既存PRのブランチ上で、上記の追加指示に必要な変更を加えてください。
"""
        ui_evidence = ""
        if task.ui_evidence_required:
            ui_evidence = """

UI / アプリ変更の必須証跡:
- 実際にアプリを起動し、変更後の画面を操作して確認する。静的HTMLの推測だけで完了しない。
- preview serverはbackgroundで起動し、PIDを記録して `trap` または `finally` で必ず終了する。foreground serverや終了待ちのまま作業を止めない。
- test、lint、build、previewの各commandは `timeout 300s <command>` など必ず有限の時間制限を付ける。commandが終了しない場合は成功扱いせず、原因を直して再実行する。
- モバイル（幅480px以下）とデスクトップ（幅1024px以上）をそれぞれ1枚以上撮影する。
- 撮影には `python /app/capture_ui.py --url <URL> --output <PNG> --width <幅> --height <高さ>` を利用できる。
- `.nyankoface-maintenance/screenshots/` に実画面PNGを保存する。
- `.nyankoface-maintenance/ui-report.json` を次の形で作る。`tests` にはクリック、入力、状態変化、レスポンシブ、横overflow、console/page errorなど、実際に行ったUIテストを具体的に列挙する。
```json
{
  "summary": "実画面で確認した内容の要約",
  "tests": [
    {"name": "タスク追加", "viewport": "390x844", "result": "passed", "details": "追加後に推薦カードへ表示"}
  ],
  "screenshots": [
    {"path": ".nyankoface-maintenance/screenshots/mobile.png", "caption": "モバイルの変更後画面", "viewport": "390x844", "url": "http://127.0.0.1:8080/"},
    {"path": ".nyankoface-maintenance/screenshots/desktop.png", "caption": "デスクトップの変更後画面", "viewport": "1440x1000", "url": "http://127.0.0.1:8080/"}
  ]
}
```
- 全UIテストが `passed` で、2枚のPNGが実在しない限り完了扱いにならない。証跡ディレクトリはPRへcommitせず、Forgejo完了コメントへ添付するためラッパーが回収する。
"""
        return f"""/goal Forgejo Issue #{task.issue_number} をこのリポジトリで完全に解決してください。

あなたは **{profile.display_name}** です。専門領域は「{profile.focus}」です。
専門領域に集中しつつ、Issueを完了させるために必要な範囲では関連ファイルも変更できます。

Issueタイトル: {task.title}
Issue URL: {task.issue_url}
Issue本文:
<issue>
{task.body}
</issue>
{release_context}
{follow_up}
{ui_evidence}

完了条件:
- 実装を決める前に、リポジトリとローカル指示を確認する。
- Issueと追加指示の関連要件を、プロダクション品質で実装する。
- 無関係な挙動を維持し、既存の規約に従う。
- 関連するテスト、lint、ビルド、または絞り込んだ検証を実行する。
- 最終diffを読み直し、見つけた問題を修正する。
- push、PR作成、Forgejo認証情報へのアクセスは行わない。公開はラッパーが担当する。
- 実装と検証が完了した場合のみ終了し、本当にブロックされた場合は理由を明示する。
- 最後の実行結果サマリーは日本語で記述する。
"""

    def _review_prompt(
        self,
        task: IssueTask,
        pull: PullRequest,
        changed: list[str],
        reviewed_sha: str,
    ) -> str:
        files = "\n".join(f"- {path}" for path in changed) or "- 変更ファイルなし"
        ui_contract = ""
        if task.ui_evidence_required:
            ui_contract = """

UIレビューの追加必須条件:
- 実装担当のスクリーンショットを信用するだけでなく、現在のSHAから実アプリを起動して独自に操作する。
- クリックとキーボード操作、主要状態変化、横overflow、console error、page error、主要なアクセシビリティを確認する。
- モバイル（幅480px以下）とデスクトップ（幅1024px以上）を独自に撮影する。
- PNGを `.nyankoface-maintenance/review-screenshots/` に保存する。
- `review-report.json` の `screenshots` に path、caption、viewport、url を記録する。
- JSONの`screenshots`配列には、PNG実寸幅480px以下のモバイル画像と実寸幅1024px以上のデスクトップ画像を必ず1枚以上ずつ含める。撮影しただけでJSONから漏らさない。
- `python /app/capture_ui.py --url <URL> --output .nyankoface-maintenance/review-screenshots/<name>.png --width <幅> --height <高さ>` を利用できる。
- 最終JSONを書いた後に、列挙した各PNGの実寸を読み直してモバイル／デスクトップ双方の条件を満たすことを確認する。
"""
        return f"""/goal [独立レビュー専用] Forgejo PR #{pull.number} を厳格に評価してください。

あなたは **NyankoFace Review** (`review-agent`) です。実装担当とは別アカウントです。
コードを修正、commit、pushしてはいけません。読み取り専用で調査・実行・判定してください。
実装担当の自己申告を前提にせず、Issueの各要件と実際のdiff・挙動を照合してください。

Issueタイトル: {task.title}
Issue URL: {task.issue_url}
PR URL: {pull.url}
レビュー対象SHA: {reviewed_sha}
実装担当: {AGENTS[task.agent_key].username}
変更ファイル:
{files}

Issue本文:
<issue>
{task.body}
</issue>
{ui_contract}

必須評価:
- Issue要件を一項目ずつ追跡し、具体的なファイル・コマンド・実画面を根拠にする。
- `git diff origin/{task.default_branch}...HEAD` を全行確認する。
- リポジトリで定義済み、またはIssue差分に関連するテスト、lint、型検査、ビルドを実行する。
- lint／型検査／ビルドのscript・設定・依存がリポジトリに存在せず、Issueも導入を要求していない場合は「未設定のためN/A」とsummaryだけへ記録し、`requirements`／`checks` のどちらにもN/A項目を入れない。存在するcommandを実行できない場合はfailedにする。
- 全体checkの失敗が比較元branchでも同一に再現し、Issue差分と無関係であることを具体的に証明できた場合は、`checks` のresultを `baseline` とし、比較元での再現結果をevidenceへ記録する。Issueの変更箇所に対応する絞り込みcheckは必ず成功させる。比較元での再現を確認できない失敗はfailedにする。
- N/Aや既存baseline失敗を使って、Issue差分が生んだ失敗・証跡不足・回帰を隠してはいけない。
- `requirements` にはIssue本文の具体的要件だけを列挙し、各resultは必ず `passed` または `failed` にする。`not_applicable`、`N/A`、`skipped` など別の値は使用しない。
- 回帰、境界条件、エラー処理、セキュリティ、アクセシビリティを厳しく確認する。
- critical/high/medium/lowの別を問わず、指摘、失敗した要件、証跡不足が1件でもあれば必ず `rejected` にする。
- 根拠のない推測で承認しない。

`.nyankoface-maintenance/review-report.json` を次の厳密な形で作成してください:
```json
{{
  "verdict": "approved または rejected",
  "reviewed_sha": "{reviewed_sha}",
  "summary": "結論と主要根拠を2〜3文・360文字以内でまとめた日本語の総評。自己紹介や全検証項目の再列挙はしない",
  "requirements": [
    {{"name": "Issueの具体的要件", "result": "passed または failed", "evidence": "確認箇所と根拠"}}
  ],
  "checks": [
    {{"name": "実行したコマンドまたは操作", "result": "passed、failed、または比較元でも同一失敗を実証した baseline", "evidence": "終了コードや観測結果"}}
  ],
  "findings": [
    {{"severity": "critical/high/medium/low", "title": "指摘", "location": "file:line または画面/操作", "details": "再現条件と影響", "remediation": "承認に必要な修正"}}
  ],
  "screenshots": [
    {{"path": ".nyankoface-maintenance/review-screenshots/mobile.png", "caption": "モバイル独立レビュー", "viewport": "390x844", "url": "http://127.0.0.1:8080/"}},
    {{"path": ".nyankoface-maintenance/review-screenshots/desktop.png", "caption": "デスクトップ独立レビュー", "viewport": "1440x1000", "url": "http://127.0.0.1:8080/"}}
  ]
}}
```
承認時も `findings` は空配列として明示してください。最後のサマリーは日本語にしてください。
"""

    def _claude_command(self) -> list[str]:
        command = [
            "claude",
            "--model",
            self.settings.model,
            "--dangerously-skip-permissions",
            "--no-session-persistence",
            "--output-format",
            "json",
            "-p",
            self._goal_prompt_placeholder,
        ]
        if getattr(os, "geteuid", lambda: -1)() == 0:
            return ["runuser", "-u", self.settings.claude_user, "--", *command]
        return command

    @property
    def _goal_prompt_placeholder(self) -> str:
        return "__NYANKOFACE_GOAL_PROMPT__"

    def _run_claude_goal(self, worktree: Path, task: IssueTask) -> str:
        return self._run_claude_prompt(worktree, self._goal_prompt(task))

    def _run_claude_prompt(self, worktree: Path, prompt: str) -> str:
        command = self._claude_command()
        command[command.index(self._goal_prompt_placeholder)] = prompt
        with tempfile.TemporaryFile(mode="w+b") as output_file:
            process = subprocess.Popen(
                command,
                cwd=worktree,
                env=self.settings.claude_environment(),
                stdout=output_file,
                stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt",
            )
            timed_out = False
            try:
                process.wait(timeout=self.settings.goal_timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._terminate_process_tree(process)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self._terminate_process_tree(process, force=True)
                    process.wait(timeout=10)
            finally:
                # Claude may have started a preview server in the background. A
                # separate process group lets the wrapper clean it up even when
                # it inherited stdout, without blocking on an open PIPE.
                self._terminate_process_tree(process)
            output_file.flush()
            output_file.seek(0, os.SEEK_END)
            size = output_file.tell()
            output_file.seek(max(0, size - 100_000))
            output = output_file.read().decode("utf-8", errors="replace")
        if timed_out:
            raise RuntimeError(
                "Claude Code /goal timed out after "
                f"{self.settings.goal_timeout_seconds}s: {output[-6000:]}"
            )
        if process.returncode != 0:
            raise RuntimeError(f"Claude Code /goal failed (exit {process.returncode}): {output[-6000:]}")
        try:
            payload = json.loads(output)
            result = str(payload.get("result") or payload.get("message") or output)
        except json.JSONDecodeError:
            result = output
        if not result.strip():
            raise RuntimeError("Claude Code /goal returned no completion summary")
        return result.strip()[:12_000]

    @staticmethod
    def _terminate_process_tree(
        process: subprocess.Popen[bytes], *, force: bool = False
    ) -> None:
        if process.poll() is not None and os.name == "nt":
            return
        try:
            if os.name != "nt" and hasattr(os, "killpg"):
                os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
            elif process.poll() is None:
                process.kill() if force else process.terminate()
        except ProcessLookupError:
            return

    def _changed_files(self, root: Path) -> list[str]:
        process = subprocess.run(
            ["git", "-c", f"safe.directory={root.resolve()}", "status", "--porcelain=v1", "-z"],
            cwd=root,
            check=True,
            capture_output=True,
            timeout=30,
        )
        entries = process.stdout.decode("utf-8", errors="replace").split("\0")
        changed: list[str] = []
        index = 0
        while index < len(entries):
            entry = entries[index]
            index += 1
            if not entry:
                continue
            path = entry[3:]
            if entry[:2].strip() in {"R", "C"} and index < len(entries):
                path = entries[index]
                index += 1
            changed.append(path.replace("\\", "/"))
        return sorted(set(changed))

    def _validate_worktree(self, root: Path, changed: list[str]) -> None:
        root_resolved = root.resolve()
        for relative in changed:
            candidate = (root / relative).resolve(strict=False)
            if root_resolved != candidate and root_resolved not in candidate.parents:
                raise RuntimeError(f"Claude changed a path outside the cloned repository: {relative}")
        subprocess.run(
            ["git", "-c", f"safe.directory={root.resolve()}", "diff", "--check", "HEAD"],
            cwd=root,
            check=True,
            timeout=60,
        )

    def _pull_body(self, task: IssueTask, summary: str, changed: list[str]) -> str:
        files = "\n".join(f"- `{path}`" for path in changed)
        trigger = ""
        if task.trigger_kind == "release":
            trigger = (
                f"- トリガー: release branch push `{task.default_branch}` @ `{task.trigger_sha}`\n"
                f"- 比較元: `{task.comparison_branch or 'main'}`\n"
                "- マージ方針: 独立reviewが現在head SHAを承認した場合だけメンテナーが自動マージする\n"
            )
        return f"""## Claude Code `/goal` 実行結果

{summary}

### 変更ファイル

{files}

### 実行環境

- Claude Code組み込みの `/goal` コマンド
- モデル: Z.AIのAnthropic互換エンドポイント経由の `{self.settings.model}`
- ラッパー検証: `git diff --check`
{trigger}

Issue #{task.issue_number} を解決します。

> Goalエージェントはクローンしたリポジトリを調査・編集・テストできます。マージ前に実装担当とは別の `review-agent` の承認が必要です。
"""
