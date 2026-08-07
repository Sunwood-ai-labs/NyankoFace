from __future__ import annotations

import os
import hashlib
import hmac
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, Mock, call, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class GoalWorkerTests(unittest.TestCase):
    def test_browser_image_installs_japanese_and_emoji_fonts(self) -> None:
        dockerfile = (Path(__file__).parents[1] / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("fonts-noto-cjk", dockerfile)
        self.assertIn("fonts-noto-color-emoji", dockerfile)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / "token").write_text("test-token", encoding="utf-8")
        (root / "secret").write_text("test-secret", encoding="utf-8")
        os.environ.update(
            {
                "FORGEJO_TOKEN_FILE": str(root / "token"),
                "WEBHOOK_SECRET_FILE": str(root / "secret"),
                "ZAI_ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic",
                "ZAI_API_KEY": "test-key",
                "MAINTENANCE_MODEL": "glm-5.2",
                "MAINTENANCE_MAX_WORKERS": "2",
                "MAINTENANCE_AUTO_MERGE": "true",
                "MAINTENANCE_HUMANLESS_ENABLED": "false",
                "MAINTENANCE_HUMANLESS_TOPIC": "humanless",
                "MAINTENANCE_HUMANLESS_SCAN_SECONDS": "300",
                "MAINTENANCE_HUMANLESS_INTERVAL_MINUTES": "1440",
                "MAINTENANCE_HUMANLESS_RETRY_MINUTES": "60",
                "MAINTENANCE_HUMANLESS_MAX_ATTEMPTS": "3",
                "MAINTENANCE_HUMANLESS_STALE_SECONDS": "900",
                "MAINTENANCE_AUTO_ISSUE_ENABLED": "false",
                "MAINTENANCE_AUTO_ISSUE_TOPIC": "humanless-issues",
                "MAINTENANCE_AUTO_LABEL_ENABLED": "false",
                "MAINTENANCE_DATA_DIR": str(root / "data"),
                "MAINTENANCE_WORKSPACE_DIR": str(root / "work"),
            }
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_claude_environment_uses_anthropic_compatible_endpoint(self) -> None:
        from config import Settings

        env = Settings.load().claude_environment()
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://api.z.ai/api/anthropic")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "test-key")
        self.assertEqual(env["ANTHROPIC_MODEL"], "glm-5.2")
        self.assertEqual(env["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "glm-4.5-air")
        self.assertEqual(env["ANTHROPIC_DEFAULT_SONNET_MODEL"], "glm-5.2")
        self.assertEqual(env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"], "1000000")
        self.assertNotIn("CLAUDE_CODE_ENABLE_EXPERIMENTAL_ADVISOR_TOOL", env)

    def test_worker_concurrency_is_bounded(self) -> None:
        from config import Settings

        self.assertEqual(Settings.load().max_workers, 2)
        self.assertTrue(Settings.load().auto_merge)
        with patch.dict(os.environ, {"MAINTENANCE_MAX_WORKERS": "99"}):
            self.assertEqual(Settings.load().max_workers, 4)

    def test_auto_label_settings_are_explicit_and_bounded(self) -> None:
        from config import Settings

        with patch.dict(
            os.environ,
            {
                "MAINTENANCE_AUTO_LABEL_ENABLED": "true",
                "MAINTENANCE_AUTO_LABEL_DRY_RUN": "true",
                "MAINTENANCE_AUTO_LABEL_ALLOWED": "bug, documentation",
                "MAINTENANCE_AUTO_LABEL_CONFIDENCE": "9",
            },
        ):
            configured = Settings.load()
        self.assertTrue(configured.auto_label_enabled)
        self.assertTrue(configured.auto_label_dry_run)
        self.assertEqual(configured.auto_label_allowed, ("bug", "documentation"))
        self.assertEqual(configured.auto_label_confidence, 1.0)

    def test_auto_label_preserves_existing_and_only_uses_repository_labels(self) -> None:
        import main

        client = MagicMock()
        client.repository_labels.return_value = {"bug": 10, "question": 20}
        payload = {
            "action": "opened",
            "repository": {
                "name": "demo",
                "owner": {"login": "nyankoface"},
            },
            "issue": {
                "number": 42,
                "title": "不具合: 保存できない",
                "body": "再現手順があります。どうすれば直せますか？",
                "labels": [{"name": "bug"}],
            },
        }
        configured = replace(
            main.settings,
            auto_label_enabled=True,
            auto_label_dry_run=False,
            auto_label_allowed=("bug", "question", "enhancement"),
            auto_label_confidence=0.85,
        )

        with patch.object(main, "settings", configured), patch.object(
            main, "ForgejoClient", return_value=client
        ), patch.object(main, "record_label_audit") as audit:
            result = main.process_auto_labels(
                event="issues",
                payload=payload,
                delivery_id="label-delivery",
            )

        client.add_issue_labels.assert_called_once_with(
            "nyankoface", "demo", 42, [20]
        )
        self.assertEqual(result["applied"], ["question"])
        self.assertIn(
            {"name": "bug", "reason": "既に付与済み"},
            result["skipped"],
        )
        audit.assert_called_once()

    def test_auto_label_dry_run_never_writes(self) -> None:
        import main

        client = MagicMock()
        client.repository_labels.return_value = {"enhancement": 30}
        payload = {
            "action": "opened",
            "repository": {
                "name": "demo",
                "owner": {"login": "nyankoface"},
            },
            "issue": {
                "number": 43,
                "title": "新機能を追加してほしい",
                "body": "",
                "labels": [],
            },
        }
        configured = replace(
            main.settings,
            auto_label_enabled=True,
            auto_label_dry_run=True,
            auto_label_allowed=("enhancement",),
            auto_label_confidence=0.85,
        )

        with patch.object(main, "settings", configured), patch.object(
            main, "ForgejoClient", return_value=client
        ), patch.object(main, "record_label_audit"):
            result = main.process_auto_labels(
                event="issues",
                payload=payload,
                delivery_id="dry-label-delivery",
            )

        client.add_issue_labels.assert_not_called()
        self.assertEqual(result["applied"], [])
        self.assertEqual(result["would_apply"], ["enhancement"])

    def test_humanless_settings_are_explicit_and_bounded(self) -> None:
        from config import Settings

        settings = Settings.load()
        self.assertFalse(settings.humanless_enabled)
        self.assertEqual(settings.humanless_topic, "humanless")
        self.assertEqual(settings.humanless_scan_seconds, 300)
        self.assertEqual(settings.humanless_interval_minutes, 1440)
        self.assertEqual(settings.humanless_max_attempts, 3)
        self.assertEqual(settings.humanless_stale_seconds, 900)
        self.assertFalse(settings.auto_issue_enabled)
        self.assertEqual(settings.auto_issue_topic, "humanless-issues")
        with patch.dict(
            os.environ,
            {
                "MAINTENANCE_HUMANLESS_ENABLED": "true",
                "MAINTENANCE_HUMANLESS_SCAN_SECONDS": "1",
                "MAINTENANCE_HUMANLESS_MAX_ATTEMPTS": "99",
                "MAINTENANCE_HUMANLESS_STALE_SECONDS": "1",
            },
        ):
            bounded = Settings.load()
        self.assertTrue(bounded.humanless_enabled)
        self.assertEqual(bounded.humanless_scan_seconds, 30)
        self.assertEqual(bounded.humanless_max_attempts, 5)
        self.assertEqual(bounded.humanless_stale_seconds, 120)

    def test_forgejo_merge_uses_guarded_server_side_merge(self) -> None:
        from config import Settings
        from forgejo import ForgejoClient

        client = ForgejoClient(Settings.load())
        client._request = Mock()
        client.merge_pull("nyankoface", "demo", 7, expected_head_sha="abc123")
        client._request.assert_called_once_with(
            "POST",
            "/repos/nyankoface/demo/pulls/7/merge",
            json={
                "Do": "merge",
                "delete_branch_after_merge": True,
                "head_commit_id": "abc123",
            },
        )
        client.close()

    def test_prompt_invokes_builtin_goal_with_completion_conditions(self) -> None:
        from config import Settings
        from worker import IssueTask, MaintenanceWorker

        worker = MaintenanceWorker(Settings.load())
        prompt = worker._goal_prompt(
            IssueTask("nyankoface", "demo", 7, "Fix the page", "Run its tests", "main", "https://example/7")
        )
        self.assertTrue(prompt.startswith("/goal "))
        self.assertIn("Issue #7", prompt)
        self.assertIn("関連するテスト", prompt)
        self.assertIn("実行結果サマリーは日本語", prompt)

    def test_follow_up_prompt_includes_comment_instruction(self) -> None:
        from config import Settings
        from worker import IssueTask, MaintenanceWorker

        task = IssueTask(
            "nyankoface", "demo", 7, "ページ修正", "最初の要件", "main", "https://example/7",
            follow_up=True, instruction="見出しも日本語にしてください",
        )
        prompt = MaintenanceWorker(Settings.load())._goal_prompt(task)
        self.assertIn("今回の追加指示", prompt)
        self.assertIn("見出しも日本語にしてください", prompt)
        self.assertIn("既存PRのブランチ上", prompt)

    def test_clean_follow_up_reuses_existing_pr_head_for_review(self) -> None:
        from dataclasses import replace

        from config import Settings
        from forgejo import PullRequest
        from worker import IssueTask, MaintenanceWorker, ReviewCheck, ReviewEvidence

        settings = replace(
            Settings.load(),
            workspace_dir=Path(self.temp.name) / "work",
            auto_merge=True,
        )
        worker = MaintenanceWorker(settings)
        task = IssueTask(
            "nyankoface",
            "demo",
            27,
            "再レビュー",
            "既存SHAを再レビュー",
            "main",
            "https://forgejo/issues/27",
            branch_override="agent/issue-27",
            follow_up=True,
            instruction="現在headを再レビューしてください",
            auto_merge_allowed=True,
        )
        pull = PullRequest(28, "https://forgejo/pulls/28", "abc123")
        forgejo = MagicMock()
        forgejo.existing_pull.return_value = pull
        agent_client = MagicMock()
        git_calls = []

        def fake_git(_client, _cwd, *args):
            git_calls.append(args)
            if args[0] == "clone":
                Path(args[-1]).mkdir(parents=True)
            if args[:2] == ("rev-parse", "HEAD"):
                return "abc123\n"
            if args[:2] == ("diff", "--name-only"):
                return "app.js\nsrc/logic.js\ntests/logic.test.js\n"
            return ""

        check = ReviewCheck("Issue要件", "passed", "現在SHAで確認")
        review = ReviewEvidence("approved", "abc123", "承認", [check], [check], [], [])
        with patch("worker.ForgejoClient", side_effect=[forgejo, agent_client]), patch.object(
            worker, "_git", side_effect=fake_git
        ), patch.object(worker, "_prepare_goal_workspace"), patch.object(
            worker, "_run_claude_goal", return_value="変更不要"
        ), patch.object(worker, "_changed_files", return_value=[]), patch.object(
            worker, "_publish_completion_comment", return_value=(100, "独立レビュー待ち")
        ), patch.object(
            worker, "_run_independent_review", return_value=review
        ) as run_review, patch.object(
            worker, "_merge_if_approved", return_value=True
        ):
            result = worker.run(task)

        self.assertTrue(result.merged)
        self.assertEqual(
            result.changed_files, ["app.js", "src/logic.js", "tests/logic.test.js"]
        )
        run_review.assert_called_once()
        self.assertFalse(any(call and call[0] in {"commit", "push"} for call in git_calls))

    def test_pull_request_conversation_can_reply_separately_from_source_issue(self) -> None:
        from worker import IssueTask

        task = IssueTask(
            "nyankoface", "demo", 18, "レビュー", "元Issue", "main", "https://example/18",
            follow_up=True, instruction="レビューしてください", agent_key="review", reply_number=19,
        )
        self.assertEqual(task.branch, "agent/issue-18")
        self.assertEqual(task.conversation_number, 19)

    def test_release_branch_patterns_are_explicit(self) -> None:
        from main import is_release_branch

        self.assertTrue(is_release_branch("release"))
        self.assertTrue(is_release_branch("release/v2.4.0"))
        self.assertTrue(is_release_branch("release-candidate"))
        self.assertFalse(is_release_branch("feature/release-button"))
        self.assertFalse(is_release_branch("main"))

    def test_release_agent_branches_are_stable_and_distinct(self) -> None:
        from main import release_agent_branch

        security = release_agent_branch("security", "release/v2.4.0", "abcdef1234567890")
        docs = release_agent_branch("docs", "release/v2.4.0", "abcdef1234567890")
        self.assertEqual(security, "agent/release-security-release-v2-4-0-abcdef1234")
        self.assertEqual(docs, "agent/release-docs-release-v2-4-0-abcdef1234")

    def test_release_push_queues_security_and_docs_pr_jobs(self) -> None:
        import main

        payload = {
            "ref": "refs/heads/release/v2.4.0",
            "after": "abcdef1234567890",
            "sender": {"login": "release-manager"},
            "repository": {
                "name": "demo",
                "default_branch": "main",
                "owner": {"login": "nyankoface"},
            },
        }
        client = MagicMock()
        client.create_issue.side_effect = [
            {"number": 71, "html_url": "https://forgejo/issues/71"},
            {"number": 72, "html_url": "https://forgejo/issues/72"},
        ]
        queued_tasks = []
        with patch.object(main, "reserve_release_audit", side_effect=[0, 0]), patch.object(
            main, "set_release_audit_issue"
        ), patch.object(main, "ForgejoClient", return_value=client), patch.object(
            main,
            "enqueue",
            side_effect=lambda task, *_args, **_kwargs: queued_tasks.append(task) or True,
        ):
            result = main.process_release_push(payload)

        self.assertTrue(result["accepted"])
        self.assertEqual(result["queued_agents"], ["security-agent", "docs-agent"])
        self.assertTrue(result["auto_merge"])
        self.assertEqual([task.agent_key for task in queued_tasks], ["security", "docs"])
        self.assertEqual([task.default_branch for task in queued_tasks], ["release/v2.4.0"] * 2)
        self.assertEqual([task.comparison_branch for task in queued_tasks], ["main"] * 2)
        self.assertTrue(all(task.trigger_kind == "release" for task in queued_tasks))
        self.assertTrue(all(task.auto_merge_allowed for task in queued_tasks))
        self.assertNotEqual(queued_tasks[0].branch, queued_tasks[1].branch)

    def test_non_release_push_is_ignored(self) -> None:
        import main

        payload = {
            "ref": "refs/heads/feature/demo",
            "after": "abcdef1234567890",
            "sender": {"login": "developer"},
            "repository": {
                "name": "demo",
                "default_branch": "main",
                "owner": {"login": "nyankoface"},
            },
        }
        with patch.object(main, "reserve_release_audit") as reserve:
            result = main.process_release_push(payload)
        self.assertFalse(result["accepted"])
        reserve.assert_not_called()

    def test_release_prompt_requires_full_diff_and_audit_artifact(self) -> None:
        from config import Settings
        from worker import IssueTask, MaintenanceWorker

        task = IssueTask(
            "nyankoface",
            "demo",
            71,
            "Release security audit",
            "Review the release",
            "release/v2.4.0",
            "https://forgejo/issues/71",
            agent_key="security",
            branch_override="agent/release-security-release-v2-4-0-abcdef1234",
            comparison_branch="main",
            trigger_kind="release",
            trigger_sha="abcdef1234567890",
            auto_merge_allowed=True,
        )
        prompt = MaintenanceWorker(Settings.load())._goal_prompt(task)
        self.assertIn("NyankoFace Security", prompt)
        self.assertIn("git diff origin/main...HEAD", prompt)
        self.assertIn("docs/release-audits/", prompt)

    def test_docs_release_prompt_requires_diff_backed_release_notes(self) -> None:
        from config import Settings
        from worker import IssueTask, MaintenanceWorker

        task = IssueTask(
            "nyankoface",
            "demo",
            72,
            "Release docs",
            "Prepare release documentation",
            "release/v2.4.0",
            "https://forgejo/issues/72",
            agent_key="docs",
            branch_override="agent/release-docs-release-v2-4-0-abcdef1234",
            comparison_branch="main",
            trigger_kind="release",
            trigger_sha="abcdef1234567890",
            auto_merge_allowed=True,
        )
        prompt = MaintenanceWorker(Settings.load())._goal_prompt(task)

        self.assertIn("RELEASE_NOTES.md", prompt)
        self.assertIn("version別リリースページ", prompt)
        self.assertIn("実際のdiff", prompt)
        self.assertIn("全locale", prompt)
        self.assertIn("abcdef1234567890", prompt)
        self.assertIn("メンテナーが自動マージ", prompt)

    def test_release_audit_merges_after_independent_approval(self) -> None:
        from config import Settings
        from forgejo import PullRequest
        from worker import IssueTask, MaintenanceWorker, ReviewCheck, ReviewEvidence

        check = ReviewCheck("release requirement", "passed", "verified")
        review = ReviewEvidence("approved", "abc123", "approved", [check], [check], [], [])
        task = IssueTask(
            "nyankoface",
            "demo",
            71,
            "Release security audit",
            "Review",
            "release/v2.4.0",
            "https://forgejo/issues/71",
            agent_key="security",
            trigger_kind="release",
            trigger_sha="abc123",
            auto_merge_allowed=True,
        )
        client = Mock()
        client.pull_head_sha.return_value = "abc123"
        self.assertTrue(
            MaintenanceWorker(Settings.load())._merge_if_approved(
                client, task, PullRequest(72, "https://forgejo/pulls/72", "abc123"), review
            )
        )
        client.pull_head_sha.assert_called_once_with("nyankoface", "demo", 72)
        client.merge_pull.assert_called_once_with(
            "nyankoface", "demo", 72, expected_head_sha="abc123"
        )

    def test_humanless_bootstrap_queues_without_human_issue(self) -> None:
        import main

        repository = {
            "name": "autopilot-sample",
            "description": "チーム向けの軽量ステータスボード",
            "default_branch": "main",
            "archived": False,
            "empty": False,
        }
        client = MagicMock()
        client.latest_open_pull.return_value = None
        client.create_issue.return_value = {
            "number": 81,
            "html_url": "https://forgejo/issues/81",
        }
        captured = []
        with patch.object(
            main,
            "reserve_humanless_cycle",
            return_value={
                "cycle_number": 1,
                "phase": "bootstrap",
                "agent_key": "coding",
                "previous_detail": "",
            },
        ), patch.object(main, "ForgejoClient", return_value=client), patch.object(
            main, "set_humanless_cycle_issue"
        ), patch.object(
            main,
            "enqueue",
            side_effect=lambda task, *_args, **kwargs: (
                kwargs["announce"](),
                captured.append(task),
                True,
            )[-1],
        ):
            result = main.queue_humanless_repository(
                repository, {"humanless", "humanless-ui"}
            )

        self.assertTrue(result["queued"])
        self.assertEqual(result["phase"], "bootstrap")
        self.assertEqual(captured[0].trigger_kind, "humanless")
        self.assertEqual(captured[0].branch, "agent/humanless-1-coding")
        self.assertTrue(captured[0].ui_evidence_required)
        self.assertTrue(captured[0].auto_merge_allowed)
        issue_body = client.create_issue.call_args.args[3]
        self.assertIn("定期メンテナンスのスケジューラ", issue_body)
        self.assertIn("実際に使える最小製品", issue_body)
        client.comment_issue.assert_called_once()

    def test_humanless_scan_only_selects_opted_in_repositories(self) -> None:
        import main
        from dataclasses import replace

        repositories = [
            {"name": "active", "topics": ["humanless"], "default_branch": "main"},
            {"name": "normal", "topics": ["demo"], "default_branch": "main"},
            {
                "name": "paused",
                "topics": ["humanless", "humanless-paused"],
                "default_branch": "main",
            },
        ]
        client = MagicMock()
        client.organization_repositories.return_value = repositories
        with patch.object(
            main, "settings", replace(main.settings, humanless_enabled=True)
        ), patch.object(main, "ForgejoClient", return_value=client), patch.object(
            main,
            "queue_humanless_repository",
            return_value={"repo": "active", "queued": True},
        ) as queue:
            result = main.run_humanless_scan()

        self.assertEqual(result, [{"repo": "active", "queued": True}])
        queue.assert_called_once_with(repositories[0], {"humanless"})

    def test_stale_humanless_cycle_recovers_with_the_same_specialist(self) -> None:
        import main

        now = datetime.now(timezone.utc)
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.execute.return_value.fetchone.return_value = {
            "cycle_number": 1,
            "phase": "bootstrap",
            "status": "running",
            "detail": "worker stopped",
            "agent": "coding-agent",
            "updated_at": now - timedelta(seconds=1800),
            "next_run_at": now + timedelta(hours=1),
        }
        with patch.object(main, "connect_database", return_value=connection), patch.object(
            main,
            "settings",
            replace(main.settings, humanless_stale_seconds=900),
        ):
            reserved = main.reserve_humanless_cycle("nyankoface", "autopilot-sample")

        self.assertIsNotNone(reserved)
        self.assertEqual(reserved["cycle_number"], 2)
        self.assertEqual(reserved["phase"], "bootstrap-recovery")
        self.assertEqual(reserved["agent_key"], "coding")
        self.assertIn("lease", reserved["previous_detail"])
        statements = [entry.args[0] for entry in connection.execute.call_args_list]
        self.assertTrue(any("status='failed'" in statement for statement in statements))
        body = main.humanless_issue_body(
            repo="autopilot-sample",
            description="sample",
            cycle_number=2,
            phase=reserved["phase"],
            agent_key=reserved["agent_key"],
            previous_detail=reserved["previous_detail"],
        )
        self.assertIn("実際に使える最小製品", body)
        self.assertIn("前cycleの未解決情報", body)

    def test_fresh_humanless_cycle_keeps_its_lease(self) -> None:
        import main

        now = datetime.now(timezone.utc)
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.execute.return_value.fetchone.return_value = {
            "cycle_number": 4,
            "phase": "maintenance",
            "status": "running",
            "detail": "",
            "agent": "designer-agent",
            "updated_at": now,
            "next_run_at": now,
        }
        with patch.object(main, "connect_database", return_value=connection), patch.object(
            main,
            "settings",
            replace(main.settings, humanless_stale_seconds=900),
        ):
            reserved = main.reserve_humanless_cycle("nyankoface", "autopilot-sample")

        self.assertIsNone(reserved)
        self.assertEqual(connection.execute.call_count, 1)

    def test_duplicate_review_recovery_does_not_replace_the_active_lease(self) -> None:
        import main

        connection = MagicMock()
        connection.__enter__.return_value = connection
        with patch.object(main, "connect_database", return_value=connection):
            main.set_humanless_cycle_issue(
                "nyankoface", "autopilot-sample", 8, 13, "duplicate"
            )

        statement, parameters = connection.execute.call_args.args
        self.assertIn("SET issue_number=%s", statement)
        self.assertNotIn("status=", statement)
        self.assertEqual(parameters, (13, "nyankoface", "autopilot-sample", 8))

    def test_queued_transition_cannot_move_a_running_cycle_backwards(self) -> None:
        import main

        connection = MagicMock()
        connection.__enter__.return_value = connection
        with patch.object(main, "connect_database", return_value=connection):
            main.set_humanless_cycle_issue(
                "nyankoface", "autopilot-sample", 8, 13, "queued"
            )

        statement = connection.execute.call_args.args[0]
        self.assertIn(
            "CASE WHEN status='preparing' THEN 'queued' ELSE status END",
            statement,
        )

    def test_failed_cycle_with_a_published_pr_recovers_review_before_new_work(self) -> None:
        import main

        now = datetime.now(timezone.utc)
        previous = {
            "cycle_number": 10,
            "phase": "recovery",
            "status": "failed",
            "detail": "review process stopped",
            "agent": "coding-agent",
            "issue_number": 16,
            "attempt": 1,
            "pull_url": "",
            "updated_at": now - timedelta(minutes=10),
            "next_run_at": now - timedelta(minutes=1),
        }
        recoverable = {
            "cycle_number": 8,
            "phase": "recovery",
            "detail": "review process stopped",
            "agent": "coding-agent",
            "issue_number": 13,
            "attempt": 1,
            "pull_url": "https://forgejo/pulls/14",
        }
        connection = MagicMock()
        connection.__enter__.return_value = connection

        def execute(sql, *_args):
            cursor = MagicMock()
            cursor.fetchone.return_value = (
                recoverable if "pull_url<>''" in sql else previous
            )
            return cursor

        connection.execute.side_effect = execute
        with patch.object(main, "connect_database", return_value=connection):
            reserved = main.reserve_humanless_cycle("nyankoface", "autopilot-sample")

        self.assertEqual(reserved["cycle_number"], 8)
        self.assertEqual(reserved["phase"], "review-recovery")
        self.assertEqual(reserved["issue_number"], 13)
        self.assertTrue(reserved["resume_pull"])
        statements = [entry.args[0] for entry in connection.execute.call_args_list]
        self.assertTrue(any("status='superseded'" in statement for statement in statements))
        self.assertTrue(any("status='preparing'" in statement for statement in statements))

    def test_review_recovery_reuses_open_pr_without_creating_an_issue(self) -> None:
        import main
        from forgejo import PullRequest

        repository = {
            "name": "autopilot-sample",
            "description": "sample",
            "default_branch": "main",
        }
        client = MagicMock()
        client.existing_pull.return_value = PullRequest(
            14, "https://forgejo/pulls/14", "abc123"
        )
        client.issue.return_value = {
            "number": 13,
            "title": "[定期メンテナンス][cycle 8] recovery",
            "body": "review the published result",
            "html_url": "https://forgejo/issues/13",
        }
        captured = []
        with patch.object(
            main,
            "reserve_humanless_cycle",
            return_value={
                "cycle_number": 8,
                "phase": "review-recovery",
                "agent_key": "coding",
                "previous_detail": "review stopped",
                "issue_number": 13,
                "pull_url": "https://forgejo/pulls/14",
                "resume_pull": True,
            },
        ), patch.object(main, "ForgejoClient", return_value=client), patch.object(
            main, "set_humanless_cycle_issue"
        ), patch.object(
            main,
            "enqueue",
            side_effect=lambda task, *_args, **kwargs: (
                kwargs["announce"](),
                captured.append(task),
                True,
            )[-1],
        ):
            result = main.queue_humanless_repository(
                repository, {"humanless", "humanless-ui"}
            )

        self.assertEqual(result["phase"], "review-recovery")
        self.assertEqual(result["pull"], "https://forgejo/pulls/14")
        self.assertTrue(captured[0].review_only)
        self.assertEqual(captured[0].branch, "agent/humanless-8-coding")
        self.assertEqual(captured[0].issue_number, 13)
        client.create_issue.assert_not_called()
        client.comment_issue.assert_called_once()

    def test_scanner_adopts_latest_published_pr_when_database_url_was_lost(self) -> None:
        import main
        from forgejo import PullRequest

        repository = {
            "name": "autopilot-sample",
            "description": "sample",
            "default_branch": "main",
        }
        client = MagicMock()
        client.latest_open_pull.return_value = (
            PullRequest(14, "https://forgejo/pulls/14", "abc123"),
            "agent/humanless-8-coding",
        )
        client.existing_pull.return_value = PullRequest(
            14, "https://forgejo/pulls/14", "abc123"
        )
        client.issue.return_value = {
            "number": 13,
            "title": "cycle 8",
            "body": "recover",
            "html_url": "https://forgejo/issues/13",
        }
        captured = []
        with patch.object(
            main,
            "reserve_humanless_cycle",
            return_value={
                "cycle_number": 11,
                "phase": "recovery",
                "agent_key": "coding",
                "previous_detail": "",
                "issue_number": 0,
                "pull_url": "",
                "resume_pull": False,
            },
        ), patch.object(
            main,
            "adopt_published_humanless_pull",
            return_value={
                "cycle_number": 8,
                "phase": "review-recovery",
                "agent_key": "coding",
                "previous_detail": "review stopped",
                "issue_number": 13,
                "pull_url": "https://forgejo/pulls/14",
                "resume_pull": True,
            },
        ) as adopt, patch.object(
            main, "ForgejoClient", return_value=client
        ), patch.object(
            main, "set_humanless_cycle_issue"
        ), patch.object(
            main,
            "enqueue",
            side_effect=lambda task, *_args, **kwargs: (
                captured.append(task),
                True,
            )[-1],
        ):
            result = main.queue_humanless_repository(
                repository, {"humanless", "humanless-ui"}
            )

        adopt.assert_called_once_with(
            "nyankoface",
            "autopilot-sample",
            cycle_number=8,
            pull_url="https://forgejo/pulls/14",
        )
        self.assertEqual(result["cycle"], 8)
        self.assertTrue(captured[0].review_only)
        client.create_issue.assert_not_called()

    def test_forgejo_selects_newest_open_humanless_pull(self) -> None:
        from config import Settings
        from forgejo import ForgejoClient

        client = ForgejoClient(Settings.load())
        with patch.object(
            client,
            "_request",
            return_value=[
                {
                    "number": 3,
                    "html_url": "https://forgejo/pulls/3",
                    "head": {
                        "ref": "agent/humanless-2-coding",
                        "sha": "old",
                    },
                },
                {
                    "number": 14,
                    "html_url": "https://forgejo/pulls/14",
                    "head": {
                        "ref": "agent/humanless-8-coding",
                        "sha": "new",
                    },
                },
                {
                    "number": 15,
                    "html_url": "https://forgejo/pulls/15",
                    "head": {"ref": "feature/unrelated", "sha": "other"},
                },
            ],
        ):
            selected = client.latest_open_pull(
                "nyankoface", "autopilot-sample", "agent/humanless-"
            )
        client.close()

        self.assertEqual(selected[0].number, 14)
        self.assertEqual(selected[0].head_sha, "new")
        self.assertEqual(selected[1], "agent/humanless-8-coding")

    def test_humanless_goal_prompt_forbids_waiting_for_a_human(self) -> None:
        from config import Settings
        from worker import IssueTask, MaintenanceWorker

        task = IssueTask(
            "nyankoface",
            "autopilot-sample",
            81,
            "[自動開発] 初期プロダクト",
            "実際に利用できるアプリを作る",
            "main",
            "https://example/81",
            ui_evidence_required=True,
            trigger_kind="humanless",
            humanless_cycle=1,
            humanless_attempt=1,
            review_only=True,
        )
        prompt = MaintenanceWorker(Settings.load())._goal_prompt(task)
        self.assertIn("自動運用", prompt)
        self.assertIn("自動化されている", prompt)
        self.assertIn("「人間に確認してください」「後で対応」では完了にしない", prompt)
        self.assertIn("独立review", prompt)
        self.assertIn("preview server", prompt)
        self.assertIn("timeout 300s", prompt)
        self.assertIn("必ず終了", prompt)

    def test_humanless_rejection_queues_bounded_automatic_retry(self) -> None:
        import main
        from forgejo import PullRequest
        from worker import AgentResult, IssueTask

        task = IssueTask(
            "nyankoface",
            "autopilot-sample",
            81,
            "[自動開発] 初期プロダクト",
            "実装する",
            "main",
            "https://example/81",
            trigger_kind="humanless",
            humanless_cycle=1,
            humanless_attempt=1,
        )
        result = AgentResult(
            PullRequest(82, "https://forgejo/pulls/82", "abc123"),
            "実装完了",
            ["index.html"],
            merged=False,
            review_verdict="rejected",
            review_summary="モバイル操作の証跡が不足",
        )
        client = MagicMock()
        with patch.object(main, "update_job"), patch.object(
            main, "update_release_audit"
        ), patch.object(main, "update_humanless_cycle"), patch.object(
            main, "ForgejoClient", return_value=client
        ), patch.object(main.worker, "run", return_value=result), patch.object(
            main, "enqueue", return_value=True
        ) as enqueue:
            main.process_job("humanless-delivery", task)

        retry_task = enqueue.call_args.args[0]
        self.assertTrue(retry_task.follow_up)
        self.assertFalse(retry_task.review_only)
        self.assertEqual(retry_task.humanless_attempt, 2)
        self.assertIn("モバイル操作の証跡が不足", retry_task.instruction)
        self.assertTrue(enqueue.call_args.kwargs["allow_retry"])

    def test_automatic_issue_rejection_updates_the_existing_pr_with_a_bounded_retry(self) -> None:
        import main
        from forgejo import PullRequest
        from worker import AgentResult, IssueTask

        task = IssueTask(
            "nyankoface",
            "autopilot-sample",
            91,
            "未知値を拒否できない",
            "許可値だけを受け付ける",
            "main",
            "https://example/91",
            trigger_kind="issue-auto",
            automation_attempt=1,
        )
        result = AgentResult(
            PullRequest(92, "https://forgejo/pulls/92", "abc123"),
            "実装完了",
            ["src/logic.js"],
            merged=False,
            review_verdict="rejected",
            review_summary="既存バックアップの回帰テストが不足",
        )
        client = MagicMock()
        with patch.object(main, "update_job"), patch.object(
            main, "update_release_audit"
        ), patch.object(main, "update_humanless_cycle"), patch.object(
            main, "ForgejoClient", return_value=client
        ), patch.object(main.worker, "run", return_value=result), patch.object(
            main, "enqueue", return_value=True
        ) as enqueue:
            main.process_job("automatic-issue-delivery", task)

        retry_task = enqueue.call_args.args[0]
        self.assertEqual(retry_task.automation_attempt, 2)
        self.assertTrue(retry_task.follow_up)
        self.assertEqual(retry_task.branch, task.branch)
        self.assertIn("既存バックアップの回帰テストが不足", retry_task.instruction)
        self.assertTrue(enqueue.call_args.kwargs["allow_retry"])

    def test_automatic_issue_review_retries_stop_at_the_configured_limit(self) -> None:
        import main
        from forgejo import PullRequest
        from worker import AgentResult, IssueTask

        task = IssueTask(
            "nyankoface",
            "autopilot-sample",
            93,
            "未知値を拒否できない",
            "許可値だけを受け付ける",
            "main",
            "https://example/93",
            trigger_kind="issue-auto",
            automation_attempt=2,
        )
        result = AgentResult(
            PullRequest(94, "https://forgejo/pulls/94", "def456"),
            "実装完了",
            ["src/logic.js"],
            merged=False,
            review_verdict="rejected",
            review_summary="境界値が未解決",
        )
        client = MagicMock()
        configured = replace(main.settings, automatic_retry_max_attempts=2)
        with patch.object(main, "settings", configured), patch.object(
            main, "update_job"
        ), patch.object(main, "update_release_audit"), patch.object(
            main, "update_humanless_cycle"
        ), patch.object(main, "ForgejoClient", return_value=client), patch.object(
            main.worker, "run", return_value=result
        ), patch.object(main, "enqueue") as enqueue:
            main.process_job("automatic-issue-limit", task)

        enqueue.assert_not_called()

    def test_automatic_issue_execution_failure_is_retried_with_the_same_bound(self) -> None:
        import main
        from worker import IssueTask

        task = IssueTask(
            "nyankoface",
            "autopilot-sample",
            95,
            "APIが一時切断された",
            "処理を完了する",
            "main",
            "https://example/95",
            trigger_kind="issue-auto",
            automation_attempt=1,
        )
        client = MagicMock()
        with patch.object(main, "update_job"), patch.object(
            main, "update_release_audit"
        ), patch.object(main, "update_humanless_cycle"), patch.object(
            main, "ForgejoClient", return_value=client
        ), patch.object(
            main.worker, "run", side_effect=RuntimeError("connection closed mid-response")
        ), patch.object(main, "enqueue", return_value=True) as enqueue:
            main.process_job("automatic-execution-failure", task)

        retry_task = enqueue.call_args.args[0]
        self.assertEqual(retry_task.automation_attempt, 2)
        self.assertEqual(retry_task.branch, task.branch)
        self.assertIn("connection closed mid-response", retry_task.instruction)
        self.assertTrue(enqueue.call_args.kwargs["allow_retry"])

    def test_security_agent_is_a_distinct_specialist_identity(self) -> None:
        from agents import AGENTS, mentioned_agent

        profile = AGENTS["security"]
        self.assertEqual(profile.username, "security-agent")
        self.assertIn("認証認可", profile.focus)
        self.assertEqual(mentioned_agent("@security-agent releaseを確認"), profile)

    def test_maintainer_mention_is_the_user_entrypoint(self) -> None:
        from agents import maintainer_instruction, mentions_maintainer

        self.assertTrue(mentions_maintainer("@glm-maintainer モバイルの余白をスクショで確認して"))
        self.assertEqual(
            maintainer_instruction("@glm-maintainer モバイルの余白をスクショで確認して"),
            "モバイルの余白をスクショで確認して",
        )

    def test_specialist_mention_does_not_override_maintainer_routing(self) -> None:
        from agents import assign_agent

        profile = assign_agent("READMEを更新", "@coding-agent アプリのテストを修正してください")
        self.assertEqual(profile.username, "docs-agent")

    def test_initial_issue_classifier_prefers_docs_then_design_then_code(self) -> None:
        from agents import choose_agent

        self.assertEqual(choose_agent("READMEを更新", "再構築手順" ).key, "docs")
        self.assertEqual(choose_agent("モバイルUI", "CSSの余白を直す").key, "designer")
        self.assertEqual(choose_agent("表示を再確認", "スクリーンショットを撮影").key, "designer")
        self.assertEqual(choose_agent("表示を再確認", "モバイルとデスクトップで確認").key, "designer")
        self.assertEqual(choose_agent("API追加", "JSON endpointを実装").key, "coding")

    def test_automatic_issue_classifier_separates_fixes_and_answers(self) -> None:
        from agents import classify_automatic_issue

        bug_agent, bug_response = classify_automatic_issue(
            "モバイル画面が動かない", "ボタンでエラーになります", {"bug"}
        )
        question_agent, question_response = classify_automatic_issue(
            "APIの使い方", "どうやって認証しますか？", {"question"}
        )
        security_agent, security_response = classify_automatic_issue(
            "認証回避の脆弱性", "修正してください", {"security"}
        )

        self.assertEqual(bug_agent.key, "designer")
        self.assertFalse(bug_response)
        self.assertEqual(question_agent.key, "coding")
        self.assertTrue(question_response)
        self.assertEqual(security_agent.key, "security")
        self.assertFalse(security_response)

    def test_ui_task_detection_covers_designer_and_app_work(self) -> None:
        from agents import AGENTS, is_ui_task

        self.assertTrue(is_ui_task("API", "JSONだけ", AGENTS["designer"]))
        self.assertTrue(is_ui_task("アプリ画面", "ボタンを直す", AGENTS["coding"]))
        self.assertFalse(is_ui_task("API", "JSON endpoint", AGENTS["coding"]))

    def test_maintainer_delegation_visibly_mentions_the_specialist(self) -> None:
        from agents import AGENTS, delegation_comment

        message = delegation_comment(
            AGENTS["docs"],
            "READMEと再構築手順を更新してください",
            follow_up=False,
        )
        self.assertIn("@docs-agent 次の作業を担当してください", message)
        self.assertIn("READMEと再構築手順", message)
        self.assertIn("担当アカウント自身", message)

    def test_delegation_announcement_precedes_worker_submission(self) -> None:
        import main
        from worker import IssueTask

        events: list[str] = []
        task = IssueTask("nyankoface", "demo", 42, "README", "更新", "main", "https://example/42", agent_key="docs")
        database = MagicMock()
        database.__enter__.return_value = database
        database.execute.return_value.fetchone.return_value = None
        with patch.object(main, "connect_database", return_value=database), patch.object(
            main.executor, "submit", side_effect=lambda *args: events.append("submit")
        ):
            queued = main.enqueue(
                task,
                "delivery-order",
                allow_retry=False,
                announce=lambda: events.append("mention"),
            )
        self.assertTrue(queued)
        self.assertEqual(events, ["mention", "submit"])

    def test_new_issue_without_maintainer_mention_is_not_started(self) -> None:
        import main
        from config import Settings
        from fastapi.testclient import TestClient

        payload = {
            "action": "opened",
            "sender": {"login": "human-user"},
            "repository": {
                "name": "demo",
                "default_branch": "main",
                "owner": {"login": "nyankoface"},
            },
            "issue": {"number": 50, "title": "UI修正", "body": "余白を直して", "labels": []},
        }
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        signature = hmac.new(b"test-secret", raw, hashlib.sha256).hexdigest()
        with patch.object(main, "settings", Settings.load()), patch.object(main, "enqueue") as enqueue:
            response = TestClient(main.app).post(
                "/webhooks/forgejo",
                content=raw,
                headers={
                    "Content-Type": "application/json",
                    "X-Forgejo-Event": "issues",
                    "X-Forgejo-Delivery": "no-maintainer",
                    "X-Forgejo-Signature": signature,
                },
            )
        self.assertEqual(response.status_code, 202)
        self.assertFalse(response.json()["accepted"])
        enqueue.assert_not_called()

    def test_agent_authored_comment_cannot_requeue_its_own_issue(self) -> None:
        import main
        from config import Settings
        from fastapi.testclient import TestClient

        payload = {
            "action": "created",
            "sender": {"login": "coding-agent"},
            "repository": {
                "name": "demo",
                "default_branch": "main",
                "owner": {"login": "nyankoface"},
            },
            "issue": {
                "number": 50,
                "title": "自動修正",
                "body": "不具合を直してください",
                "labels": [],
            },
            "comment": {
                "body": "@glm-maintainer 修正結果を確認してください",
            },
        }
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        signature = hmac.new(b"test-secret", raw, hashlib.sha256).hexdigest()
        with patch.object(main, "settings", Settings.load()), patch.object(
            main, "enqueue"
        ) as enqueue:
            response = TestClient(main.app).post(
                "/webhooks/forgejo",
                content=raw,
                headers={
                    "Content-Type": "application/json",
                    "X-Forgejo-Event": "issue_comment",
                    "X-Forgejo-Delivery": "agent-self-comment",
                    "X-Forgejo-Signature": signature,
                },
            )

        self.assertEqual(response.status_code, 202)
        self.assertFalse(response.json()["accepted"])
        self.assertEqual(response.json()["reason"], "issue opted out")
        enqueue.assert_not_called()

    def test_maintainer_mention_starts_ui_job_and_chooses_specialist(self) -> None:
        import main
        from config import Settings
        from fastapi.testclient import TestClient

        payload = {
            "action": "opened",
            "sender": {"login": "human-user"},
            "repository": {
                "name": "demo",
                "default_branch": "main",
                "owner": {"login": "nyankoface"},
            },
            "issue": {
                "number": 51,
                "title": "モバイルUI修正",
                "body": "@glm-maintainer ボタン余白を直してスクショで確認して",
                "labels": [],
            },
        }
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        signature = hmac.new(b"test-secret", raw, hashlib.sha256).hexdigest()
        with patch.object(main, "settings", Settings.load()), patch.object(
            main, "enqueue", return_value=True
        ) as enqueue:
            response = TestClient(main.app).post(
                "/webhooks/forgejo",
                content=raw,
                headers={
                    "Content-Type": "application/json",
                    "X-Forgejo-Event": "issues",
                    "X-Forgejo-Delivery": "with-maintainer",
                    "X-Forgejo-Signature": signature,
                },
            )
        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.json()["accepted"])
        self.assertEqual(response.json()["agent"], "designer-agent")
        self.assertTrue(response.json()["ui_evidence_required"])
        task = enqueue.call_args.args[0]
        self.assertEqual(task.agent_key, "designer")
        self.assertTrue(task.ui_evidence_required)

    def test_opted_in_question_is_answered_without_a_maintainer_mention(self) -> None:
        import main
        from config import Settings
        from fastapi.testclient import TestClient

        payload = {
            "action": "opened",
            "sender": {"login": "human-user"},
            "repository": {
                "name": "demo",
                "default_branch": "main",
                "owner": {"login": "nyankoface"},
            },
            "issue": {
                "number": 52,
                "title": "APIの使い方を教えて",
                "body": "認証はどうやって設定しますか？",
                "labels": [{"name": "question"}],
            },
        }
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        signature = hmac.new(b"test-secret", raw, hashlib.sha256).hexdigest()
        specialist = MagicMock()
        specialist.repository_topics.return_value = {"humanless-issues"}
        configured = replace(Settings.load(), auto_issue_enabled=True)
        with patch.object(main, "settings", configured), patch.object(
            main, "ForgejoClient", return_value=specialist
        ), patch.object(
            main,
            "enqueue",
            side_effect=lambda _task, *_args, **kwargs: (
                kwargs["announce"](),
                True,
            )[-1],
        ) as enqueue:
            response = TestClient(main.app).post(
                "/webhooks/forgejo",
                content=raw,
                headers={
                    "Content-Type": "application/json",
                    "X-Forgejo-Event": "issues",
                    "X-Forgejo-Delivery": "automatic-question",
                    "X-Forgejo-Signature": signature,
                },
            )

        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.json()["accepted"])
        self.assertTrue(response.json()["automatic"])
        self.assertTrue(response.json()["response_only"])
        task = enqueue.call_args.args[0]
        self.assertEqual(task.trigger_kind, "issue-auto")
        self.assertTrue(task.response_only)
        self.assertFalse(task.ui_evidence_required)
        announcement = specialist.comment_issue.call_args.args[3]
        self.assertIn("Issueを受け付けました。", announcement)
        self.assertIn("@coding-agent", announcement)
        self.assertNotIn("人レス", announcement)
        self.assertNotIn("人間のメンション", announcement)

    def test_answer_comment_does_not_repeat_the_agent_identity(self) -> None:
        from agents import AGENTS
        from config import Settings
        from worker import IssueTask, MaintenanceWorker

        client = MagicMock()
        task = IssueTask(
            "nyankoface",
            "demo",
            52,
            "APIの使い方を教えて",
            "認証はどうやって設定しますか？",
            "main",
            "https://example.test/issues/52",
            response_only=True,
        )
        evidence = {
            "answer": "環境変数で設定します。",
            "confidence": "high",
            "references": [
                {"path": "README.md", "reason": "設定例を確認"},
            ],
        }

        MaintenanceWorker(Settings.load())._publish_response_comment(
            client, task, AGENTS["coding"], evidence
        )

        body = client.comment_issue.call_args.args[3]
        self.assertTrue(body.startswith("確認結果です。"))
        self.assertNotIn("NyankoFace Coding", body)
        self.assertNotIn("coding-agent", body)
        self.assertNotIn("リポジトリを読み取り専用で調査", body)

    def test_opted_in_bug_is_queued_for_fix_review_and_auto_merge(self) -> None:
        import main
        from config import Settings
        from fastapi.testclient import TestClient

        payload = {
            "action": "opened",
            "sender": {"login": "human-user"},
            "repository": {
                "name": "demo",
                "default_branch": "main",
                "owner": {"login": "nyankoface"},
            },
            "issue": {
                "number": 53,
                "title": "モバイル画面が動かない",
                "body": "保存ボタンでエラーになります",
                "labels": [{"name": "bug"}],
            },
        }
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        signature = hmac.new(b"test-secret", raw, hashlib.sha256).hexdigest()
        specialist = MagicMock()
        specialist.repository_topics.return_value = {"humanless"}
        configured = replace(Settings.load(), auto_issue_enabled=True)
        with patch.object(main, "settings", configured), patch.object(
            main, "ForgejoClient", return_value=specialist
        ), patch.object(main, "enqueue", return_value=True) as enqueue:
            response = TestClient(main.app).post(
                "/webhooks/forgejo",
                content=raw,
                headers={
                    "Content-Type": "application/json",
                    "X-Forgejo-Event": "issues",
                    "X-Forgejo-Delivery": "automatic-bug",
                    "X-Forgejo-Signature": signature,
                },
            )

        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.json()["automatic"])
        self.assertFalse(response.json()["response_only"])
        self.assertEqual(response.json()["agent"], "designer-agent")
        task = enqueue.call_args.args[0]
        self.assertFalse(task.response_only)
        self.assertTrue(task.auto_merge_allowed)
        self.assertTrue(task.ui_evidence_required)

    def test_answer_only_report_requires_repository_references(self) -> None:
        from config import Settings
        from worker import MaintenanceWorker

        root = Path(self.temp.name) / "answer"
        report = root / ".nyankoface-maintenance" / "response-report.json"
        report.parent.mkdir(parents=True)
        report.write_text(
            json.dumps(
                {
                    "summary": "認証設定を確認",
                    "answer": "環境変数で設定します。",
                    "confidence": "high",
                    "references": [
                        {
                            "path": "README.md",
                            "reason": "設定手順が記載されている",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        evidence = MaintenanceWorker(Settings.load())._collect_response_evidence(root)

        self.assertEqual(evidence["confidence"], "high")
        self.assertEqual(evidence["references"][0]["path"], "README.md")
        self.assertFalse(report.parent.exists())

    def test_specialist_prompt_contains_role_contract(self) -> None:
        from config import Settings
        from worker import IssueTask, MaintenanceWorker

        task = IssueTask(
            "nyankoface", "demo", 8, "UI修正", "余白を直す", "main", "https://example/8",
            agent_key="designer",
        )
        prompt = MaintenanceWorker(Settings.load())._goal_prompt(task)
        self.assertIn("NyankoFace Designer", prompt)
        self.assertIn("スクリーンショット比較", prompt)

    def test_ui_prompt_requires_real_mobile_and_desktop_evidence(self) -> None:
        from config import Settings
        from worker import IssueTask, MaintenanceWorker

        task = IssueTask(
            "nyankoface", "demo", 8, "UI修正", "余白を直す", "main", "https://example/8",
            agent_key="designer", ui_evidence_required=True,
        )
        prompt = MaintenanceWorker(Settings.load())._goal_prompt(task)
        self.assertIn("/app/capture_ui.py", prompt)
        self.assertIn("ui-report.json", prompt)
        self.assertIn("モバイル", prompt)
        self.assertIn("デスクトップ", prompt)
        self.assertIn("実際に行ったUIテスト", prompt)

    def test_ui_evidence_requires_passed_tests_and_two_real_png_sizes(self) -> None:
        from config import Settings
        from worker import IssueTask, MaintenanceWorker

        root = Path(self.temp.name) / "repo"
        shots = root / ".nyankoface-maintenance" / "screenshots"
        shots.mkdir(parents=True)

        def png(width: int, height: int) -> bytes:
            return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", width, height)

        (shots / "mobile.png").write_bytes(png(390, 844))
        (shots / "desktop.png").write_bytes(png(1440, 1000))
        report = {
            "summary": "追加と横overflowを確認",
            "tests": [
                {"name": "タスク追加", "viewport": "390x844", "result": "passed", "details": "推薦へ表示"}
            ],
            "screenshots": [
                {"path": ".nyankoface-maintenance/screenshots/mobile.png", "caption": "mobile"},
                {"path": ".nyankoface-maintenance/screenshots/desktop.png", "caption": "desktop"},
            ],
        }
        (root / ".nyankoface-maintenance" / "ui-report.json").write_text(
            json.dumps(report), encoding="utf-8"
        )
        task = IssueTask(
            "nyankoface", "demo", 9, "UI", "fix", "main", "https://example/9",
            ui_evidence_required=True,
        )
        evidence = MaintenanceWorker(Settings.load())._collect_ui_evidence(root, task)
        self.assertIsNotNone(evidence)
        self.assertEqual([shot.width for shot in evidence.screenshots], [390, 1440])
        self.assertFalse((root / ".nyankoface-maintenance").exists())

    def test_ui_evidence_is_mandatory_for_ui_tasks(self) -> None:
        from config import Settings
        from worker import IssueTask, MaintenanceWorker

        root = Path(self.temp.name) / "repo"
        root.mkdir()
        task = IssueTask(
            "nyankoface", "demo", 9, "UI", "fix", "main", "https://example/9",
            ui_evidence_required=True,
        )
        with self.assertRaisesRegex(RuntimeError, "ui-report.json"):
            MaintenanceWorker(Settings.load())._collect_ui_evidence(root, task)

    def test_ui_evidence_accepts_safe_screenshot_names(self) -> None:
        from config import Settings
        from worker import IssueTask, MaintenanceWorker

        root = Path(self.temp.name) / "repo-name-evidence"
        shots = root / ".nyankoface-maintenance" / "screenshots"
        shots.mkdir(parents=True)

        def png(width: int, height: int) -> bytes:
            return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", width, height)

        (shots / "mobile.png").write_bytes(png(390, 844))
        (shots / "desktop.png").write_bytes(png(1440, 1000))
        (root / ".nyankoface-maintenance" / "ui-report.json").write_text(
            json.dumps({
                "summary": {"verdict": "passed", "configs_tested": 2},
                "tests": [{"name": "操作", "result": "passed", "details": "実ブラウザで確認"}],
                "screenshots": [
                    {"name": "mobile.png", "caption": "mobile", "viewport": "390x844"},
                    {"name": "desktop.png", "caption": "desktop", "viewport": "1440x1000"},
                ],
            }),
            encoding="utf-8",
        )
        task = IssueTask(
            "nyankoface", "demo", 10, "UI", "fix", "main", "https://example/10",
            ui_evidence_required=True,
        )
        evidence = MaintenanceWorker(Settings.load())._collect_ui_evidence(root, task)
        self.assertEqual([shot.width for shot in evidence.screenshots], [390, 1440])
        self.assertIn('\"verdict\": \"passed\"', evidence.summary)

    def test_review_prompt_is_read_only_strict_and_sha_bound(self) -> None:
        from config import Settings
        from forgejo import PullRequest
        from worker import IssueTask, MaintenanceWorker

        task = IssueTask(
            "nyankoface", "demo", 12, "モバイルUI", "余白と操作を直す", "main",
            "https://example/12", agent_key="designer", ui_evidence_required=True,
        )
        prompt = MaintenanceWorker(Settings.load())._review_prompt(
            task, PullRequest(13, "https://forgejo/pr/13", "abc123"), ["index.html"], "abc123"
        )
        self.assertIn("review-agent", prompt)
        self.assertIn("コードを修正、commit、pushしてはいけません", prompt)
        self.assertIn("critical/high/medium", prompt)
        self.assertIn("モバイル", prompt)
        self.assertIn("デスクトップ", prompt)
        self.assertIn("PNG実寸幅480px以下", prompt)
        self.assertIn("撮影しただけでJSONから漏らさない", prompt)
        self.assertIn("未設定のためN/A", prompt)
        self.assertIn("summaryだけへ記録", prompt)
        self.assertIn("not_applicable", prompt)
        self.assertIn("比較元branchでも同一に再現", prompt)
        self.assertIn("Issueの変更箇所に対応する絞り込みcheckは必ず成功", prompt)
        self.assertIn('"reviewed_sha": "abc123"', prompt)

    def test_review_report_rejects_false_approval(self) -> None:
        from config import Settings
        from worker import IssueTask, MaintenanceWorker

        root = Path(self.temp.name) / "review"
        evidence = root / ".nyankoface-maintenance"
        evidence.mkdir(parents=True)
        report = {
            "verdict": "approved",
            "reviewed_sha": "abc123",
            "summary": "問題なし",
            "requirements": [{"name": "ボタン", "result": "failed", "evidence": "クリック不能"}],
            "checks": [{"name": "test", "result": "passed", "evidence": "1 passed"}],
            "findings": [],
        }
        (evidence / "review-report.json").write_text(json.dumps(report), encoding="utf-8")
        task = IssueTask("nyankoface", "demo", 12, "UI", "fix", "main", "https://example/12")
        result = MaintenanceWorker(Settings.load())._collect_review_evidence(root, task, "abc123")
        self.assertEqual(result.verdict, "rejected")
        self.assertIn("安全側へ差し戻し", result.summary)

    def test_review_report_allows_proven_baseline_check_failure(self) -> None:
        from config import Settings
        from worker import IssueTask, MaintenanceWorker

        root = Path(self.temp.name) / "review-baseline"
        evidence = root / ".nyankoface-maintenance"
        evidence.mkdir(parents=True)
        report = {
            "verdict": "approved",
            "reviewed_sha": "abc123",
            "summary": "全体checkの既存失敗は比較元でも同一再現。Issue差分は合格。",
            "requirements": [{"name": "未知値を拒否", "result": "passed", "evidence": "focused test"}],
            "checks": [
                {
                    "name": "npm test",
                    "result": "baseline",
                    "evidence": "HEADとorigin/mainで同じR009、変更ファイル外",
                },
                {"name": "focused test", "result": "passed", "evidence": "5/5"},
            ],
            "findings": [],
        }
        (evidence / "review-report.json").write_text(json.dumps(report), encoding="utf-8")
        task = IssueTask("nyankoface", "demo", 27, "JSON", "未知値を拒否", "main", "https://example/27")

        result = MaintenanceWorker(Settings.load())._collect_review_evidence(
            root, task, "abc123"
        )

        self.assertEqual(result.verdict, "approved")
        self.assertEqual(result.checks[0].result, "baseline")

    def test_review_report_is_bound_to_current_head_sha(self) -> None:
        from config import Settings
        from worker import IssueTask, MaintenanceWorker

        root = Path(self.temp.name) / "review-sha"
        evidence = root / ".nyankoface-maintenance"
        evidence.mkdir(parents=True)
        report = {
            "verdict": "approved",
            "reviewed_sha": "old-sha",
            "summary": "問題なし",
            "requirements": [{"name": "要件", "result": "passed", "evidence": "diff確認"}],
            "checks": [{"name": "test", "result": "passed", "evidence": "exit 0"}],
            "findings": [],
        }
        (evidence / "review-report.json").write_text(json.dumps(report), encoding="utf-8")
        task = IssueTask("nyankoface", "demo", 12, "API", "fix", "main", "https://example/12")
        with self.assertRaisesRegex(RuntimeError, "current PR head SHA"):
            MaintenanceWorker(Settings.load())._collect_review_evidence(root, task, "new-sha")

    def test_auto_merge_requires_approved_current_head_review(self) -> None:
        from config import Settings
        from forgejo import PullRequest
        from worker import IssueTask, MaintenanceWorker, ReviewCheck, ReviewEvidence

        worker = MaintenanceWorker(Settings.load())
        task = IssueTask("nyankoface", "demo", 12, "UI", "fix", "main", "https://example/12")
        pull = PullRequest(13, "https://forgejo/pr/13", "abc123")
        check = ReviewCheck("要件", "passed", "根拠")
        approved = ReviewEvidence("approved", "abc123", "承認", [check], [check], [], [])
        rejected = ReviewEvidence("rejected", "abc123", "却下", [check], [check], [], [])
        client = Mock()
        client.pull_head_sha.return_value = "abc123"

        self.assertFalse(worker._merge_if_approved(client, task, pull, rejected))
        client.merge_pull.assert_not_called()
        self.assertTrue(worker._merge_if_approved(client, task, pull, approved))
        client.merge_pull.assert_called_once_with(
            "nyankoface", "demo", 13, expected_head_sha="abc123"
        )

    def test_rejection_feedback_includes_failed_checks_without_findings(self) -> None:
        from config import Settings
        from worker import MaintenanceWorker, ReviewCheck, ReviewEvidence

        passed = ReviewCheck("unit tests", "passed", "74/74")
        failed_requirement = ReviewCheck(
            "Docker build", "failed", "docker daemon is unavailable"
        )
        failed_check = ReviewCheck(
            "published route", "failed", "public iframe returned 502"
        )
        review = ReviewEvidence(
            "rejected",
            "abc123",
            "差し戻し",
            [failed_requirement],
            [passed, failed_check],
            [],
            [],
        )

        feedback = MaintenanceWorker(Settings.load())._rejection_feedback(review)

        self.assertIn("failed requirement", feedback)
        self.assertIn("docker daemon is unavailable", feedback)
        self.assertIn("failed check", feedback)
        self.assertIn("public iframe returned 502", feedback)

    def test_auto_merge_refuses_stale_reviewer_approval(self) -> None:
        from config import Settings
        from forgejo import PullRequest
        from worker import IssueTask, MaintenanceWorker, ReviewCheck, ReviewEvidence

        check = ReviewCheck("要件", "passed", "根拠")
        review = ReviewEvidence("approved", "reviewed-sha", "承認", [check], [check], [], [])
        task = IssueTask("nyankoface", "demo", 12, "UI", "fix", "main", "https://example/12")
        client = Mock()
        client.pull_head_sha.return_value = "changed-after-review"
        with self.assertRaisesRegex(RuntimeError, "stale approval"):
            MaintenanceWorker(Settings.load())._merge_if_approved(
                client, task, PullRequest(13, "https://forgejo/pr/13"), review
            )
        client.merge_pull.assert_not_called()

    def test_maintainer_review_delegation_mentions_separate_reviewer(self) -> None:
        from agents import AGENTS, review_delegation_comment

        body = review_delegation_comment(
            AGENTS["designer"], 13, "https://forgejo/pr/13", ui_review_required=True
        )
        self.assertIn("@review-agent", body)
        self.assertIn("実装成果物を独立レビューへ移します", body)
        self.assertNotIn("NyankoFace Designer", body)
        self.assertIn("承認されるまで自動マージしません", body)
        self.assertIn("モバイル／デスクトップ", body)

    def test_review_comment_does_not_repeat_the_reviewer_identity(self) -> None:
        from config import Settings
        from forgejo import PullRequest
        from worker import IssueTask, MaintenanceWorker, ReviewCheck, ReviewEvidence

        client = Mock()
        client.comment_issue.return_value = {"id": 51}
        check = ReviewCheck("要件", "passed", "確認済み")
        evidence = ReviewEvidence(
            "approved",
            "e38b3423d6bf484f09fc2f34bd7319d18ed65217",
            "独立レビュー(review-agent)として要件を満たしていることを確認しました。",
            [check],
            [check],
            [],
            [],
        )
        task = IssueTask(
            "nyankoface", "demo", 10, "UI", "fix", "main", "https://example/10"
        )

        _, body = MaintenanceWorker(Settings.load())._publish_review_comment(
            client, task, PullRequest(11, "https://forgejo/pr/11"), evidence
        )

        self.assertTrue(body.startswith("[PR #11]"))
        self.assertIn("### レビュー概要", body)
        self.assertIn("[`e38b3423d6bf`](https://forgejo/pr/11/commit/", body)
        self.assertNotIn("レビュー対象SHA", body)
        self.assertNotIn("独立レビュー(review-agent)として", body)
        self.assertNotIn("NyankoFace Review", body)
        self.assertNotIn("review-agent", body)

    def test_review_summary_keeps_at_most_three_sentences(self) -> None:
        from worker import MaintenanceWorker

        summary = MaintenanceWorker._review_summary(
            "第一の結論です。第二の根拠です。第三の補足です。第四の詳細は表に任せます。"
        )

        self.assertEqual(summary, "第一の結論です。第二の根拠です。第三の補足です。")

    def test_completion_comment_uploads_and_embeds_ui_screenshots(self) -> None:
        from agents import AGENTS
        from config import Settings
        from forgejo import PullRequest
        from worker import IssueTask, MaintenanceWorker, UiEvidence, UiScreenshot, UiTestResult

        client = Mock()
        client.comment_issue.return_value = {"id": 42}
        client.upload_comment_attachment.side_effect = [
            {"browser_download_url": "https://forgejo/attachments/mobile.png"},
            {"browser_download_url": "https://forgejo/attachments/desktop.png"},
        ]
        evidence = UiEvidence(
            "実操作済み",
            [UiTestResult("追加", "390x844", "passed", "推薦カードへ表示")],
            [
                UiScreenshot("mobile.png", "モバイル", "390x844", "http://app", 390, 844, b"png"),
                UiScreenshot("desktop.png", "デスクトップ", "1440x1000", "http://app", 1440, 1000, b"png"),
            ],
        )
        task = IssueTask("nyankoface", "demo", 10, "UI", "fix", "main", "https://example/10")
        comment_id, body = MaintenanceWorker(Settings.load())._publish_completion_comment(
            client, task, AGENTS["designer"], PullRequest(11, "https://forgejo/pr/11"),
            ["css/styles.css"], evidence, "検証済み・マージ処理中",
        )
        self.assertEqual(comment_id, 42)
        self.assertIn("### UIテスト", body)
        self.assertIn("推薦カードへ表示", body)
        self.assertIn("![モバイル](https://forgejo/attachments/mobile.png)", body)
        self.assertTrue(body.startswith("担当作業が完了しました。"))
        for profile in AGENTS.values():
            self.assertNotIn(profile.display_name, body)
            self.assertNotIn(profile.username, body)
        self.assertEqual(client.upload_comment_attachment.call_count, 2)
        client.edit_issue_comment.assert_called_once()

    def test_command_uses_claude_code_and_not_bounded_json_planner(self) -> None:
        from config import Settings
        from worker import MaintenanceWorker

        command = MaintenanceWorker(Settings.load())._claude_command()
        self.assertIn("claude", command)
        self.assertIn("--dangerously-skip-permissions", command)
        self.assertNotIn("--json-schema", command)

    def test_goal_runner_uses_file_output_and_cleans_process_group(self) -> None:
        from config import Settings
        from worker import MaintenanceWorker

        root = Path(self.temp.name) / "repo"
        root.mkdir()
        process = Mock(pid=1234, returncode=0)
        process.wait.return_value = 0
        process.poll.return_value = 0

        def start(*_args, **kwargs):
            kwargs["stdout"].write(b'{"result":"completed"}')
            kwargs["stdout"].flush()
            return process

        worker = MaintenanceWorker(Settings.load())
        with patch("worker.subprocess.Popen", side_effect=start) as popen, patch.object(
            worker, "_terminate_process_tree"
        ) as terminate:
            result = worker._run_claude_prompt(root, "test prompt")

        self.assertEqual(result, "completed")
        self.assertNotEqual(popen.call_args.kwargs["stdout"], subprocess.PIPE)
        terminate.assert_called_once_with(process)

    def test_goal_runner_terminates_process_group_on_timeout(self) -> None:
        from config import Settings
        from worker import MaintenanceWorker

        root = Path(self.temp.name) / "repo"
        root.mkdir()
        process = Mock(pid=1234, returncode=-15)
        process.wait.side_effect = [subprocess.TimeoutExpired("claude", 1), 0]
        process.poll.return_value = None

        def start(*_args, **kwargs):
            kwargs["stdout"].write(b"partial output")
            kwargs["stdout"].flush()
            return process

        worker = MaintenanceWorker(Settings.load())
        with patch("worker.subprocess.Popen", side_effect=start), patch.object(
            worker, "_terminate_process_tree"
        ) as terminate:
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                worker._run_claude_prompt(root, "test prompt")

        self.assertEqual(terminate.call_args_list[0], call(process))

    def test_root_git_scopes_safe_directory_to_the_clone(self) -> None:
        from config import Settings
        from worker import MaintenanceWorker

        root = Path(self.temp.name) / "repo"
        root.mkdir()
        client = Mock()
        client.git_environment.return_value = os.environ.copy()
        client.token = "secret"
        completed = Mock(returncode=0, stdout="ok")
        with patch("worker.subprocess.run", return_value=completed) as run:
            MaintenanceWorker(Settings.load())._git(client, root, "status", "--short")
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["git", "-c", f"safe.directory={root.resolve()}"])

    def test_changed_file_scan_scopes_safe_directory_to_the_clone(self) -> None:
        from config import Settings
        from worker import MaintenanceWorker

        root = Path(self.temp.name) / "repo"
        root.mkdir()
        completed = Mock(returncode=0, stdout=b" M README.md\0")
        with patch("worker.subprocess.run", return_value=completed) as run:
            changed = MaintenanceWorker(Settings.load())._changed_files(root)
        self.assertEqual(changed, ["README.md"])
        self.assertEqual(
            run.call_args.args[0][:3],
            ["git", "-c", f"safe.directory={root.resolve()}"],
        )

    def test_repeated_reaction_conflict_is_idempotent(self) -> None:
        from config import Settings
        from forgejo import ForgejoClient

        with patch("forgejo.httpx.Client") as client_type:
            response = Mock(status_code=409)
            client_type.return_value.post.return_value = response
            client = ForgejoClient(Settings.load())
            client.react_to_issue("nyankoface", "demo", 7, "eyes")
        response.raise_for_status.assert_not_called()


if __name__ == "__main__":
    unittest.main()
