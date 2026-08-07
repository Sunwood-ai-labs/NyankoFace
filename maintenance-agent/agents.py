from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentProfile:
    key: str
    username: str
    display_name: str
    emoji: str
    focus: str


AGENTS: dict[str, AgentProfile] = {
    "designer": AgentProfile(
        "designer", "designer-agent", "NyankoFace Designer", "🎨",
        "UI/UX、レスポンシブ、テーマ、アクセシビリティ、スクリーンショット比較を担当する",
    ),
    "coding": AgentProfile(
        "coding", "coding-agent", "NyankoFace Coding", "🛠️",
        "アプリケーション実装、リファクタリング、テスト、ビルドを担当する",
    ),
    "docs": AgentProfile(
        "docs", "docs-agent", "NyankoFace Docs", "📚",
        "README、VitePress、設定例、再構築手順、リンク整合性を担当する",
    ),
    "security": AgentProfile(
        "security", "security-agent", "NyankoFace Security", "🛡️",
        "脅威分析、認証認可、秘密情報、依存関係、入力検証、サプライチェーン安全性を担当する",
    ),
    "review": AgentProfile(
        "review", "review-agent", "NyankoFace Review", "🔎",
        "diff、テスト、セキュリティ、回帰、要件充足を独立に評価し、コードを修正せず承認または差し戻す",
    ),
}

BY_USERNAME = {profile.username: profile for profile in AGENTS.values()}
MENTION_RE = re.compile(
    rf"@({'|'.join(re.escape(username) for username in BY_USERNAME)})\b",
    re.IGNORECASE,
)
MAINTAINER_USERNAME = "glm-maintainer"
MAINTAINER_MENTION_RE = re.compile(r"@glm-maintainer\b", re.IGNORECASE)

UI_KEYWORDS = (
    "ui", "ux", "css", "html", "frontend", "front-end", "react", "vue", "next.js", "nextjs",
    "streamlit", "gradio", "space", "アプリ", "画面", "デザイン", "レイアウト", "テーマ",
    "レスポンシブ", "モバイル", "スクショ", "スクリーンショット", "screenshot", "viewport", "accessibility", "a11y",
)


def mentioned_agent(body: str) -> AgentProfile | None:
    matches = {match.lower() for match in MENTION_RE.findall(body)}
    if len(matches) != 1:
        return None
    return BY_USERNAME[next(iter(matches))]


def mention_instruction(body: str, profile: AgentProfile) -> str:
    return re.sub(rf"@{re.escape(profile.username)}\b", "", body, count=1, flags=re.IGNORECASE).strip()


def mentions_maintainer(body: str) -> bool:
    return bool(MAINTAINER_MENTION_RE.search(body))


def maintainer_instruction(body: str) -> str:
    return MAINTAINER_MENTION_RE.sub("", body, count=1).strip()


def is_ui_task(title: str, body: str, profile: AgentProfile) -> bool:
    if profile.key == "designer":
        return True
    text = f"{title}\n{body}".lower()
    return any(keyword in text for keyword in UI_KEYWORDS)


def delegation_comment(profile: AgentProfile, instruction: str, *, follow_up: bool) -> str:
    summary = " ".join(instruction.split())[:600] or profile.focus
    context = "追加指示" if follow_up else "新しいIssue"
    return (
        f"🧭 {context}を分類しました。\n\n"
        f"@{profile.username} 次の作業を担当してください。\n\n"
        f"> {summary}\n\n"
        f"担当範囲: {profile.focus}\n\n"
        "進捗と完了結果は、担当アカウント自身がリアクションとコメントで更新します。"
    )


def review_delegation_comment(
    implementation_profile: AgentProfile,
    pull_number: int,
    pull_url: str,
    *,
    ui_review_required: bool,
) -> str:
    evidence = (
        "実アプリを操作し、モバイル／デスクトップ双方の独自スクリーンショットも提出してください。"
        if ui_review_required
        else "diff、要件、回帰、テスト結果を根拠付きで確認してください。"
    )
    return (
        "🧭 実装成果物を独立レビューへ移します。\n\n"
        f"@review-agent [PR #{pull_number}]({pull_url}) を厳格に評価してください。\n\n"
        f"> 実装担当の自己評価を前提にせず、Issue要件を一項目ずつ照合してください。{evidence}\n\n"
        "承認されるまで自動マージしません。重大度を付けた指摘が1件でも残る場合は却下してください。"
    )


def choose_agent(title: str, body: str) -> AgentProfile:
    text = f"{title}\n{body}".lower()
    if any(word in text for word in ("readme", "ドキュメント", "documentation", "vitepress", "docs/")):
        return AGENTS["docs"]
    if any(word in text for word in UI_KEYWORDS):
        return AGENTS["designer"]
    return AGENTS["coding"]


def classify_automatic_issue(
    title: str, body: str, labels: set[str]
) -> tuple[AgentProfile, bool]:
    """Return the specialist and whether the Issue is answer-only.

    Explicit bug/security-fix labels take precedence over question-like prose.
    Unknown Issues are investigated read-only instead of being allowed to make
    speculative product changes.
    """
    normalized_labels = {label.strip().lower() for label in labels}
    text = f"{title}\n{body}".lower()
    security = bool(
        normalized_labels & {"security", "vulnerability", "脆弱性", "セキュリティ"}
    ) or any(
        word in text
        for word in ("脆弱性", "security bug", "vulnerability", "認証回避", "情報漏えい")
    )
    bug = bool(
        normalized_labels
        & {"bug", "defect", "不具合", "バグ", "regression", "security"}
    ) or any(
        word in text
        for word in (
            "不具合",
            "バグ",
            "動かない",
            "壊れて",
            "エラー",
            "regression",
            "crash",
            "does not work",
        )
    )
    question = bool(
        normalized_labels
        & {"question", "support", "inquiry", "質問", "問い合わせ", "help wanted"}
    ) or any(
        word in text
        for word in (
            "質問",
            "問い合わせ",
            "教えて",
            "どうやって",
            "使い方",
            "how do",
            "how to",
            "why does",
        )
    )
    profile = AGENTS["security"] if security else choose_agent(title, body)
    return profile, bool(question and not bug) or not bug


def assign_agent(title: str, body: str) -> AgentProfile:
    """The maintainer owns routing; user-authored specialist mentions never override it."""
    return choose_agent(title, body)
