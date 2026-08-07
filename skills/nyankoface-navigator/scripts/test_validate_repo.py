from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("validate_repo.py")


class ValidatorTests(unittest.TestCase):
    def run_validator(
        self,
        root: Path,
        goal: str,
        *topics: str,
    ) -> tuple[int, dict[str, object]]:
        command = [
            "python",
            str(SCRIPT),
            str(root),
            "--goal",
            goal,
            "--topics",
            *topics,
            "--json",
        ]
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        return result.returncode, json.loads(result.stdout)

    def test_knowledge_accepts_topics_without_formats(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "articles").mkdir()
            (root / "articles" / "hello.md").write_text(
                "---\ntitle: Hello\ntopics: [how-to]\n---\n\n# Hello\n",
                encoding="utf-8",
            )
            code, report = self.run_validator(root, "knowledge", "doc")
            self.assertEqual(code, 0, report)
            self.assertEqual(report["errors"], [])

    def test_pages_requires_no_topic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "docs").mkdir()
            (root / "docs" / "index.html").write_text("<title>Hello</title>", encoding="utf-8")
            code, report = self.run_validator(root, "pages")
            self.assertEqual(code, 0, report)

    def test_external_space_accepts_https_without_dockerfile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.md").write_text(
                "---\nexternal_url: https://example.com/app\n---\n",
                encoding="utf-8",
            )
            code, report = self.run_validator(root, "space", "space")
            self.assertEqual(code, 0, report)

    def test_docker_space_accepts_root_dockerfile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Dockerfile").write_text(
                "FROM python:3.12-slim\nEXPOSE 7860\nCMD [\"python\", \"app.py\", \"--host\", \"0.0.0.0\"]\n",
                encoding="utf-8",
            )
            code, report = self.run_validator(root, "space", "space")
            self.assertEqual(code, 0, report)

    def test_model_dataset_and_skill_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.md").write_text("# Card\n", encoding="utf-8")
            (root / "config.json").write_text("{}\n", encoding="utf-8")
            code, report = self.run_validator(root, "model", "model")
            self.assertEqual(code, 0, report)

            (root / "data").mkdir()
            code, report = self.run_validator(root, "dataset", "dataset")
            self.assertEqual(code, 0, report)

            (root / "SKILL.md").write_text(
                "---\nname: sample-skill\ndescription: Sample.\n---\n",
                encoding="utf-8",
            )
            code, report = self.run_validator(root, "skill", "skill")
            self.assertEqual(code, 0, report)

    def test_mcp_and_benchmark_require_runnable_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.md").write_text("# Runnable project\n", encoding="utf-8")
            (root / "requirements.txt").write_text("mcp\n", encoding="utf-8")
            (root / "server.py").write_text("print('server')\n", encoding="utf-8")
            code, report = self.run_validator(root, "mcp", "mcp")
            self.assertEqual(code, 0, report)

            (root / "run.py").write_text("print('benchmark')\n", encoding="utf-8")
            (root / "results").mkdir()
            code, report = self.run_validator(root, "benchmark", "benchmark")
            self.assertEqual(code, 0, report)

    def test_character_requires_a_real_format(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code, report = self.run_validator(root, "character", "character")
            self.assertEqual(code, 1)
            self.assertTrue(report["errors"])

    def test_automation_requires_safe_disabled_toml_and_matching_tag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "README.md").write_text("# Weekly report\n", encoding="utf-8")
            (root / "LICENSE").write_text("MIT\n", encoding="utf-8")
            safe = (
                'schema_version = 1\nname = "Weekly report"\n'
                'description = "Read-only repository summary."\nplatform = "codex"\n'
                'format = "automation"\nversion = "1.0.0"\nschedule_type = "weekly"\n'
                'timezone = "Asia/Tokyo"\ntrigger = "Monday 09:00"\n'
                'required_permissions = ["repository:read"]\nrequired_connectors = ["github"]\n'
                'workspace_required = false\ndelivery_type = "none"\n'
                'tested_on = ["Codex Desktop"]\ntags = ["report"]\nlicense = "MIT"\n'
                'enabled = false\nrequired_secrets = ["GITHUB_TOKEN"]\n'
            )
            (root / "automation.toml").write_text(safe, encoding="utf-8")
            (root / "automation.example.toml").write_text(safe, encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(root), "-c", "user.name=Test", "-c",
                 "user.email=test@example.com", "commit", "-qm", "automation"],
                check=True,
            )
            subprocess.run(["git", "-C", str(root), "tag", "v1.0.0"], check=True)
            code, report = self.run_validator(root, "automation", "automation")
            self.assertEqual(code, 0, report)

            (root / "automation.example.toml").write_text(
                safe + 'password = "published-secret"\n',
                encoding="utf-8",
            )
            code, report = self.run_validator(root, "automation", "automation")
            self.assertEqual(code, 1)
            self.assertTrue(report["errors"])
            (root / "automation.example.toml").write_text(safe, encoding="utf-8")

            (root / "automation.toml").write_text(
                safe.replace("enabled = false", "enabled = true") + 'token = "secret"\n',
                encoding="utf-8",
            )
            code, report = self.run_validator(root, "automation", "automation")
            self.assertEqual(code, 1)
            self.assertTrue(report["errors"])

    def test_prompt_requires_matching_topic_and_tag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "PROMPT.md").write_text("# Prompt\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "PROMPT.md"], check=True)
            subprocess.run(
                [
                    "git", "-C", str(root), "-c", "user.name=Test",
                    "-c", "user.email=test@example.com", "commit", "-qm", "prompt",
                ],
                check=True,
            )
            subprocess.run(["git", "-C", str(root), "tag", "v1"], check=True)
            code, report = self.run_validator(root, "prompt", "prompt", "version-v1")
            self.assertEqual(code, 0, report)


if __name__ == "__main__":
    unittest.main()
