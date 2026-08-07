from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _integer(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _boolean(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    forgejo_api: str
    forgejo_git_base: str
    forgejo_token_file: Path
    webhook_secret_file: Path
    zai_base_url: str
    zai_api_key: str
    model: str
    data_dir: Path
    workspace_dir: Path
    allowed_owner: str
    claude_user: str
    goal_timeout_seconds: int
    max_workers: int
    agent_token_dir: Path
    auto_merge: bool
    humanless_enabled: bool
    humanless_topic: str
    humanless_scan_seconds: int
    humanless_interval_minutes: int
    humanless_retry_minutes: int
    humanless_max_attempts: int
    humanless_stale_seconds: int
    auto_issue_enabled: bool
    auto_issue_topic: str
    automatic_retry_max_attempts: int
    auto_label_enabled: bool
    auto_label_dry_run: bool
    auto_label_allowed: tuple[str, ...]
    auto_label_confidence: float
    database_url: str

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            forgejo_api=os.getenv("FORGEJO_API", "http://forgejo:3000/api/v1").rstrip("/"),
            forgejo_git_base=os.getenv("FORGEJO_GIT_BASE", "http://forgejo:3000").rstrip("/"),
            forgejo_token_file=Path(os.getenv("FORGEJO_TOKEN_FILE", "/shared/maintenance-token")),
            webhook_secret_file=Path(os.getenv("WEBHOOK_SECRET_FILE", "/shared/maintenance-webhook-secret")),
            zai_base_url=os.getenv("ZAI_ANTHROPIC_BASE_URL", "https://api.z.ai/api/anthropic").rstrip("/"),
            zai_api_key=os.getenv("ZAI_API_KEY", ""),
            model=os.getenv("MAINTENANCE_MODEL", "glm-5.2"),
            data_dir=Path(os.getenv("MAINTENANCE_DATA_DIR", "/data")),
            workspace_dir=Path(os.getenv("MAINTENANCE_WORKSPACE_DIR", "/work")),
            allowed_owner=os.getenv("MAINTENANCE_ALLOWED_OWNER", "nyankoface"),
            claude_user=os.getenv("MAINTENANCE_CLAUDE_USER", "maintainer"),
            goal_timeout_seconds=_integer("MAINTENANCE_GOAL_TIMEOUT_SECONDS", 3600),
            max_workers=max(1, min(_integer("MAINTENANCE_MAX_WORKERS", 2), 4)),
            agent_token_dir=Path(os.getenv("MAINTENANCE_AGENT_TOKEN_DIR", "/shared/agent-tokens")),
            auto_merge=_boolean("MAINTENANCE_AUTO_MERGE"),
            humanless_enabled=_boolean("MAINTENANCE_HUMANLESS_ENABLED"),
            humanless_topic=os.getenv("MAINTENANCE_HUMANLESS_TOPIC", "humanless").strip().lower(),
            humanless_scan_seconds=max(30, _integer("MAINTENANCE_HUMANLESS_SCAN_SECONDS", 300)),
            humanless_interval_minutes=max(
                1, _integer("MAINTENANCE_HUMANLESS_INTERVAL_MINUTES", 1440)
            ),
            humanless_retry_minutes=max(
                1, _integer("MAINTENANCE_HUMANLESS_RETRY_MINUTES", 60)
            ),
            humanless_max_attempts=max(
                1, min(_integer("MAINTENANCE_HUMANLESS_MAX_ATTEMPTS", 3), 5)
            ),
            humanless_stale_seconds=max(
                120, _integer("MAINTENANCE_HUMANLESS_STALE_SECONDS", 900)
            ),
            auto_issue_enabled=_boolean("MAINTENANCE_AUTO_ISSUE_ENABLED"),
            auto_issue_topic=os.getenv(
                "MAINTENANCE_AUTO_ISSUE_TOPIC", "humanless-issues"
            ).strip().lower(),
            automatic_retry_max_attempts=max(
                1, min(_integer("MAINTENANCE_AUTOMATIC_RETRY_MAX_ATTEMPTS", 3), 5)
            ),
            auto_label_enabled=_boolean("MAINTENANCE_AUTO_LABEL_ENABLED", True),
            auto_label_dry_run=_boolean("MAINTENANCE_AUTO_LABEL_DRY_RUN"),
            auto_label_allowed=tuple(
                label.strip().lower()
                for label in os.getenv(
                    "MAINTENANCE_AUTO_LABEL_ALLOWED",
                    "bug,enhancement,documentation,question,good first issue",
                ).split(",")
                if label.strip()
            ),
            auto_label_confidence=max(
                0.0,
                min(1.0, _float("MAINTENANCE_AUTO_LABEL_CONFIDENCE", 0.85)),
            ),
            database_url=os.getenv("DATABASE_URL", ""),
        )

    def agent_token_file(self, username: str) -> Path:
        return self.agent_token_dir / username

    def read_forgejo_token(self) -> str:
        return self.forgejo_token_file.read_text(encoding="utf-8").strip()

    def read_webhook_secret(self) -> str:
        return self.webhook_secret_file.read_text(encoding="utf-8").strip()

    def claude_environment(self) -> dict[str, str]:
        home = f"/home/{self.claude_user}"
        return {
            "PATH": os.environ.get("PATH", ""),
            "HOME": home,
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "ANTHROPIC_BASE_URL": self.zai_base_url,
            "ANTHROPIC_AUTH_TOKEN": self.zai_api_key,
            "ANTHROPIC_MODEL": self.model,
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": "glm-4.5-air",
            "ANTHROPIC_DEFAULT_SONNET_MODEL": self.model,
            "ANTHROPIC_DEFAULT_OPUS_MODEL": self.model,
            "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "1000000",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "API_TIMEOUT_MS": "3000000",
        }

    def readiness(self) -> dict[str, bool]:
        return {
            "forgejo_token": self.forgejo_token_file.is_file() and self.forgejo_token_file.stat().st_size > 0,
            "webhook_secret": self.webhook_secret_file.is_file() and self.webhook_secret_file.stat().st_size > 0,
            "zai_api_key": bool(self.zai_api_key),
            "specialist_tokens": all(
                self.agent_token_file(username).is_file()
                for username in (
                    "designer-agent",
                    "coding-agent",
                    "docs-agent",
                    "security-agent",
                    "review-agent",
                )
            ),
        }
