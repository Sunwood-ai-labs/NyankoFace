from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class LabelCandidate:
    name: str
    confidence: float
    reason: str


@dataclass(frozen=True)
class LabelDecision:
    candidates: tuple[LabelCandidate, ...]

    def above(self, threshold: float) -> tuple[LabelCandidate, ...]:
        return tuple(
            candidate
            for candidate in self.candidates
            if candidate.confidence >= threshold
        )


RULES: tuple[tuple[str, float, str, tuple[str, ...]], ...] = (
    (
        "bug",
        0.94,
        "不具合・再現・期待動作に関する語を検出",
        (
            r"\bbug\b",
            r"\bcrash(?:es|ed|ing)?\b",
            r"\bexception\b",
            r"\berror\b",
            r"不具合",
            r"バグ",
            r"壊れ",
            r"再現手順",
            r"期待動作",
            r"実際の動作",
            r"動かない",
        ),
    ),
    (
        "enhancement",
        0.90,
        "新機能・改善提案に関する語を検出",
        (
            r"\bfeature\b",
            r"\benhancement\b",
            r"\bproposal\b",
            r"機能追加",
            r"新機能",
            r"改善提案",
            r"追加して",
            r"できるように",
            r"ほしい",
            r"欲しい",
        ),
    ),
    (
        "documentation",
        0.95,
        "README・ガイド・説明に関する語を検出",
        (
            r"readme",
            r"(?<![a-z0-9_])docs?(?![a-z0-9_])",
            r"documentation",
            r"ドキュメント",
            r"説明不足",
            r"明文化",
            r"ガイド",
            r"手順書",
        ),
    ),
    (
        "question",
        0.86,
        "質問・追加情報の要求に関する語を検出",
        (
            r"\bquestion\b",
            r"\bhow (?:do|can|should)\b",
            r"\bwhy\b",
            r"質問",
            r"教えて",
            r"どうやって",
            r"どうすれば",
            r"確認したい",
        ),
    ),
    (
        "good first issue",
        0.92,
        "初心者向けであることが明示されている",
        (
            r"\bgood first issue\b",
            r"\bbeginner[- ]friendly\b",
            r"初心者向け",
            r"初めてでも",
        ),
    ),
)


def _matches(text: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def classify_labels(
    title: str,
    body: str,
    *,
    changed_files: Iterable[str] = (),
) -> LabelDecision:
    """Classify an Issue or PR without calling an external model.

    Deterministic rules make retries idempotent and keep the audit reason
    reproducible. Repository-specific policy is applied later by intersecting
    these candidates with the configured allowlist and existing labels.
    """

    text = f"{title}\n{body}"
    candidates: dict[str, LabelCandidate] = {}
    for name, confidence, reason, patterns in RULES:
        if _matches(text, patterns):
            candidates[name] = LabelCandidate(name, confidence, reason)

    files = tuple(path.strip().lower() for path in changed_files if path.strip())
    if files and all(
        path.startswith("docs/")
        or path.startswith(".github/")
        or path in {"readme.md", "readme.ja.md"}
        or path.endswith(".md")
        for path in files
    ):
        candidates["documentation"] = LabelCandidate(
            "documentation",
            0.98,
            "PRの変更ファイルがドキュメントだけで構成されている",
        )

    return LabelDecision(
        tuple(
            sorted(
                candidates.values(),
                key=lambda candidate: (-candidate.confidence, candidate.name),
            )
        )
    )
