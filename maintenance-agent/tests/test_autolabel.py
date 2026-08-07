from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class AutoLabelClassifierTests(unittest.TestCase):
    def test_bug_and_documentation_reasons_are_deterministic(self) -> None:
        from autolabel import classify_labels

        decision = classify_labels(
            "READMEの不具合を修正",
            "再現手順と期待動作を追記してください。",
        )

        candidates = {candidate.name: candidate for candidate in decision.candidates}
        self.assertGreaterEqual(candidates["bug"].confidence, 0.9)
        self.assertGreaterEqual(candidates["documentation"].confidence, 0.9)
        self.assertIn("検出", candidates["bug"].reason)

    def test_docs_only_pull_request_is_documentation(self) -> None:
        from autolabel import classify_labels

        decision = classify_labels(
            "Copy edits",
            "Polish the examples.",
            changed_files=("README.md", "docs/guide/operations.md"),
        )

        candidates = {candidate.name: candidate for candidate in decision.candidates}
        self.assertEqual(candidates["documentation"].confidence, 0.98)
        self.assertIn("変更ファイル", candidates["documentation"].reason)

    def test_ambiguous_text_returns_no_candidate(self) -> None:
        from autolabel import classify_labels

        decision = classify_labels("Catalog note", "This is a neutral status update.")

        self.assertEqual(decision.candidates, ())


if __name__ == "__main__":
    unittest.main()
