import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1] / "check_pr_merge_readiness.py"
)
SPEC = importlib.util.spec_from_file_location("merge_guard", SCRIPT)
merge_guard = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = merge_guard
SPEC.loader.exec_module(merge_guard)


class MergeReadinessTests(unittest.TestCase):
    def base_pr(self):
        return {
            "headRefOid": "a" * 40,
            "isDraft": False,
            "statusCheckRollup": [
                {
                    "name": "validate",
                    "workflowName": "CI",
                    "detailsUrl": "https://github.com/example/repo/actions/runs/1/job/2",
                    "appSlug": "github-actions",
                    "status": "COMPLETED",
                    "conclusion": "SUCCESS",
                }
            ],
            "changedFiles": 4,
            "additions": 80,
            "deletions": 20,
            "commits": 3,
        }

    def review(self, sha=None):
        return {
            "id": 1,
            "user": {"login": "chatgpt-codex-connector"},
            "commit_id": sha or "a" * 40,
            "state": "COMMENTED",
            "submitted_at": "2026-07-31T00:00:00Z",
        }

    def test_accepts_exact_head_review_green_checks_and_resolved_threads(self):
        result = merge_guard.evaluate(
            self.base_pr(),
            [self.review()],
            [{"isResolved": True}],
            "chatgpt-codex-connector",
        )
        self.assertTrue(result.ready)

    def test_blocks_stale_review_pending_check_and_unresolved_thread(self):
        pr = self.base_pr()
        pr["statusCheckRollup"][0]["status"] = "IN_PROGRESS"
        result = merge_guard.evaluate(
            pr,
            [self.review("b" * 40)],
            [{"isResolved": False}],
            "chatgpt-codex-connector",
        )
        self.assertFalse(result.ready)
        self.assertEqual(len(result.errors), 3)

    def test_large_scope_requires_an_explicit_reason(self):
        pr = self.base_pr()
        pr["changedFiles"] = 87
        blocked = merge_guard.evaluate(
            pr,
            [self.review()],
            [],
            "chatgpt-codex-connector",
        )
        accepted = merge_guard.evaluate(
            pr,
            [self.review()],
            [],
            "chatgpt-codex-connector",
            "single generated migration",
        )
        self.assertFalse(blocked.ready)
        self.assertTrue(accepted.ready)
        self.assertEqual(len(accepted.warnings), 1)

    def test_blocks_when_head_changes_during_state_collection(self):
        result = merge_guard.evaluate(
            self.base_pr(),
            [self.review()],
            [],
            "chatgpt-codex-connector",
            initial_head="b" * 40,
        )
        self.assertFalse(result.ready)
        self.assertIn("head changed", result.errors[0])

    def test_blocks_when_no_ci_checks_are_registered(self):
        pr = self.base_pr()
        pr["statusCheckRollup"] = []
        result = merge_guard.evaluate(
            pr,
            [self.review()],
            [],
            "chatgpt-codex-connector",
        )
        self.assertFalse(result.ready)
        self.assertIn("No CI checks", result.errors[0])

    def test_blocks_when_only_an_unrelated_check_is_registered(self):
        pr = self.base_pr()
        pr["statusCheckRollup"][0]["name"] = "external-advisory"
        result = merge_guard.evaluate(
            pr,
            [self.review()],
            [],
            "chatgpt-codex-connector",
        )
        self.assertFalse(result.ready)
        self.assertTrue(
            any("Required CI checks are missing: validate" in error
                for error in result.errors)
        )

    def test_blocks_same_named_check_from_an_unrelated_workflow(self):
        pr = self.base_pr()
        pr["statusCheckRollup"][0]["workflowName"] = "External validation"
        result = merge_guard.evaluate(
            pr,
            [self.review()],
            [],
            "chatgpt-codex-connector",
        )
        self.assertFalse(result.ready)
        self.assertTrue(
            any("Required CI checks are missing: validate" in error
                for error in result.errors)
        )

    def test_blocks_same_named_check_from_an_unrelated_app(self):
        pr = self.base_pr()
        pr["statusCheckRollup"][0]["appSlug"] = "external-ci"
        result = merge_guard.evaluate(
            pr,
            [self.review()],
            [],
            "chatgpt-codex-connector",
        )
        self.assertFalse(result.ready)
        self.assertTrue(
            any("Required CI checks are missing: validate" in error
                for error in result.errors)
        )

    def test_snapshot_signature_tracks_review_and_thread_state(self):
        snapshot = (
            self.base_pr(),
            [self.review()],
            [{"id": "thread-1", "isResolved": True}],
        )
        changed = (
            self.base_pr(),
            [self.review()],
            [{"id": "thread-1", "isResolved": False}],
        )
        self.assertNotEqual(
            merge_guard._snapshot_signature(snapshot),
            merge_guard._snapshot_signature(changed),
        )

    def test_accepts_exact_head_clean_review_comment(self):
        head = "a" * 40
        comment = {
            "id": 42,
            "user": {"login": "chatgpt-codex-connector[bot]"},
            "created_at": "2026-07-31T00:00:00Z",
            "body": (
                "Codex Review: Didn't find any major issues. Swish!\n\n"
                "**Reviewed commit:** `aaaaaaaaaa`"
            ),
        }
        review = merge_guard._clean_review_from_comment(comment, head)
        self.assertIsNotNone(review)
        result = merge_guard.evaluate(
            self.base_pr(),
            [review],
            [],
            "chatgpt-codex-connector[bot]",
        )
        self.assertTrue(result.ready)

    def test_rejects_stale_or_non_connector_clean_review_comments(self):
        head = "a" * 40
        comment = {
            "id": 42,
            "user": {"login": "chatgpt-codex-connector[bot]"},
            "created_at": "2026-07-31T00:00:00Z",
            "body": (
                "Codex Review: Didn't find any major issues. Swish!\n\n"
                "**Reviewed commit:** `bbbbbbbbbb`"
            ),
        }
        self.assertIsNone(
            merge_guard._clean_review_from_comment(comment, head)
        )
        comment["user"]["login"] = "untrusted-bot[bot]"
        comment["body"] = comment["body"].replace("bbbbbbbbbb", "aaaaaaaaaa")
        self.assertIsNone(
            merge_guard._clean_review_from_comment(comment, head)
        )

    def test_blocks_dismissed_or_change_requested_exact_head_reviews(self):
        for state in ("DISMISSED", "CHANGES_REQUESTED"):
            review = self.review()
            review["state"] = state
            result = merge_guard.evaluate(
                self.base_pr(),
                [review],
                [],
                "chatgpt-codex-connector",
            )
            self.assertFalse(result.ready, state)

    def test_uses_latest_review_state_for_the_exact_head(self):
        accepted = self.review()
        rejected = self.review()
        rejected.update(
            {
                "id": 2,
                "state": "CHANGES_REQUESTED",
                "submitted_at": "2026-07-31T00:01:00Z",
            }
        )
        result = merge_guard.evaluate(
            self.base_pr(),
            [accepted, rejected],
            [],
            "chatgpt-codex-connector",
        )
        self.assertFalse(result.ready)
        self.assertTrue(
            any("change request has not been cleared" in error
                for error in result.errors)
        )

    def test_comment_does_not_clear_an_earlier_change_request(self):
        rejected = self.review()
        rejected["state"] = "CHANGES_REQUESTED"
        comment = self.review()
        comment.update(
            {
                "id": 2,
                "submitted_at": "2026-07-31T00:01:00Z",
            }
        )
        result = merge_guard.evaluate(
            self.base_pr(),
            [rejected, comment],
            [],
            "chatgpt-codex-connector",
        )
        self.assertFalse(result.ready)
        self.assertTrue(
            any("change request has not been cleared" in error
                for error in result.errors)
        )

    def test_later_dismissal_clears_an_earlier_change_request(self):
        rejected = self.review()
        rejected["state"] = "CHANGES_REQUESTED"
        dismissed = self.review()
        dismissed.update(
            {
                "id": 2,
                "state": "DISMISSED",
                "submitted_at": "2026-07-31T00:01:00Z",
            }
        )
        comment = self.review()
        comment.update(
            {
                "id": 3,
                "submitted_at": "2026-07-31T00:02:00Z",
            }
        )
        result = merge_guard.evaluate(
            self.base_pr(),
            [rejected, dismissed, comment],
            [],
            "chatgpt-codex-connector",
        )
        self.assertTrue(result.ready)


if __name__ == "__main__":
    unittest.main()
