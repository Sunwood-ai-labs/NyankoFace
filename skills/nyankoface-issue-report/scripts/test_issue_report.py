from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from publish_report import PublishError, publish_report
from stage_report import ReportError, stage_report


NOW = datetime(2026, 8, 9, 1, 2, 3, tzinfo=timezone.utc)


def stage_kwargs(outbox: Path, **overrides):
    values = {
        "outbox": outbox,
        "report_kind": "bug",
        "title": "MCP initialize returns 426",
        "summary": "The public MCP endpoint rejects a valid initialize request.",
        "environment": "HTTPS deployment behind the NyankoFace gateway.",
        "reproduction_steps": [
            "POST JSON-RPC initialize to /mcp.",
            "Send the Streamable HTTP content and accept headers.",
        ],
        "expected": "The MCP upstream returns the initialize response.",
        "actual": "The gateway returns HTTP 426.",
        "impact": "Agents cannot use the configured MCP route.",
        "evidence": ["Observed status and response headers from the public endpoint."],
        "suggested_fix": "Repair the TLS termination route and add an initialize check.",
        "reporter": "black-hermes",
        "source": "https://example.invalid/mcp",
        "staged_at": NOW,
    }
    values.update(overrides)
    return values


class IssueReportTests(unittest.TestCase):
    def test_stage_redacts_credentials_and_writes_deterministic_markdown(self):
        with tempfile.TemporaryDirectory() as temporary:
            outbox = Path(temporary)
            result = stage_report(
                **stage_kwargs(
                    outbox,
                    summary="Authorization: Bearer ghp_example_secret was observed; password=unsafe.",
                    evidence=["https://example.invalid/check?token=unsafe&ok=1"],
                    source="https://user:password@example.invalid/mcp",
                )
            )
            self.assertEqual(result["status"], "staged")
            self.assertGreater(result["redactions_applied"], 0)
            path = Path(result["path"])
            entry = json.loads(path.read_text(encoding="utf-8"))
            serialized = json.dumps(entry, ensure_ascii=False)
            self.assertNotIn("ghp_example_secret", serialized)
            self.assertNotIn("password=unsafe", serialized)
            self.assertNotIn("token=unsafe", serialized)
            self.assertNotIn("user:password@", serialized)
            self.assertIn("## Reproduction steps", entry["markdown"])
            self.assertIn("1. POST JSON-RPC initialize", entry["markdown"])
            self.assertEqual(entry["schema_version"], 1)

    def test_duplicate_fingerprint_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            outbox = Path(temporary)
            first = stage_report(**stage_kwargs(outbox))
            second = stage_report(**stage_kwargs(outbox))
            self.assertEqual(first["status"], "staged")
            self.assertEqual(second["status"], "duplicate")
            self.assertEqual(first["report_id"], second["report_id"])
            self.assertEqual(len(list((outbox / "pending").glob("*.json"))), 1)

    def test_rate_limit_is_per_reporter_and_does_not_cross_agents(self):
        with tempfile.TemporaryDirectory() as temporary:
            outbox = Path(temporary)
            stage_report(**stage_kwargs(outbox, max_per_hour=1))
            with self.assertRaisesRegex(ReportError, "hourly"):
                stage_report(
                    **stage_kwargs(
                        outbox,
                        title="A different report",
                        max_per_hour=1,
                    )
                )
            other = stage_report(
                **stage_kwargs(outbox, title="A different report", reporter="white-athena", max_per_hour=1)
            )
            self.assertEqual(other["status"], "staged")

    def test_observation_time_is_timezone_aware(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ReportError, "timezone"):
                stage_report(**stage_kwargs(Path(temporary), observed_at="2026-08-09T01:02:03"))

    def test_publish_searches_before_create_and_moves_successful_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staged = stage_report(**stage_kwargs(root))
            fake = root / "fake-gh.py"
            log = root / "gh.log"
            fake.write_text(
                "import json, os, sys\n"
                f"open({str(log)!r}, 'a', encoding='utf-8').write(json.dumps(sys.argv[1:]) + '\\n')\n"
                "if sys.argv[1:3] == ['issue', 'list']:\n"
                "    print('[]')\n"
                "else:\n"
                "    print('https://github.com/Sunwood-ai-labs/NyankoFace/issues/99')\n",
                encoding="utf-8",
            )
            result = publish_report(
                outbox=root,
                repo="Sunwood-ai-labs/NyankoFace",
                report_id=staged["report_id"],
                gh=(sys.executable, str(fake)),
                now=NOW,
            )
            self.assertEqual(result["status"], "published")
            self.assertFalse((root / "pending" / f"{staged['report_id']}.json").exists())
            published = root / "published" / f"{staged['report_id']}.json"
            self.assertTrue(published.exists())
            calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(calls[0][:2], ["issue", "list"])
            self.assertEqual(calls[1][:2], ["issue", "create"])
            self.assertNotIn("Bearer", log.read_text(encoding="utf-8"))

    def test_publish_keeps_duplicate_pending_and_does_not_create(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staged = stage_report(**stage_kwargs(root))
            fake = root / "fake-gh.py"
            log = root / "gh.log"
            fake.write_text(
                "import json, sys\n"
                f"open({str(log)!r}, 'a', encoding='utf-8').write(json.dumps(sys.argv[1:]) + '\\n')\n"
                "if sys.argv[1:3] == ['issue', 'list']:\n"
                "    print(json.dumps([{'number': 8, 'title': 'Existing', 'url': 'https://github.com/example/repo/issues/8'}]))\n"
                "else:\n"
                "    raise SystemExit('create must not run')\n",
                encoding="utf-8",
            )
            result = publish_report(
                outbox=root,
                repo="Sunwood-ai-labs/NyankoFace",
                report_id=staged["report_id"],
                gh=(sys.executable, str(fake)),
                now=NOW,
            )
            self.assertEqual(result["status"], "duplicate")
            self.assertTrue((root / "pending" / f"{staged['report_id']}.json").exists())
            calls = log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(calls), 1)

    def test_publish_rejects_missing_record_without_calling_gh(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(PublishError, "not found"):
                publish_report(
                    outbox=Path(temporary),
                    repo="Sunwood-ai-labs/NyankoFace",
                    report_id="missing",
                    gh=("does-not-exist",),
                    now=NOW,
                )


if __name__ == "__main__":
    unittest.main()
