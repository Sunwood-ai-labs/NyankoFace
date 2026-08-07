#!/usr/bin/env python3
"""Validate one repository against NyankoFace's discoverable publishing contracts."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path
from urllib.parse import urlparse


TYPE_TOPICS = {
    "model": "model",
    "dataset": "dataset",
    "space": "space",
    "knowledge": "doc",
    "skill": "skill",
    "mcp": "mcp",
    "prompt": "prompt",
    "character": "character",
    "benchmark": "benchmark",
    "automation": "automation",
    "pages": None,
}


class Report:
    def __init__(self, goal: str) -> None:
        self.goal = goal
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def emit(self, as_json: bool) -> int:
        ok = not self.errors
        if as_json:
            print(json.dumps(
                {
                    "ok": ok,
                    "goal": self.goal,
                    "errors": self.errors,
                    "warnings": self.warnings,
                },
                ensure_ascii=False,
                indent=2,
            ))
        else:
            for message in self.errors:
                print(f"ERROR: {message}")
            for message in self.warnings:
                print(f"WARN: {message}")
            label = "OK" if ok else "NG"
            print(
                f"{label}: {self.goal} contract "
                f"({len(self.errors)} error(s), {len(self.warnings)} warning(s))"
            )
        return 0 if ok else 1


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def git_lines(root: Path, *args: str) -> list[str]:
    result = git(root, *args)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def git_file(root: Path, ref: str, path: str) -> bool:
    return git(root, "cat-file", "-e", f"{ref}:{path}").returncode == 0


def frontmatter(text: str) -> str:
    normalized = text.replace("\r\n", "\n")
    match = re.match(r"^---[ \t]*\n(.*?)\n---[ \t]*(?:\n|$)", normalized, re.DOTALL)
    return match.group(1) if match else ""


def scalar(meta: str, key: str) -> str | None:
    match = re.search(
        rf"(?m)^{re.escape(key)}:\s*['\"]?([^'\"\n]+?)['\"]?\s*$",
        meta,
    )
    return match.group(1).strip() if match else None


def has_key(meta: str, key: str) -> bool:
    return re.search(rf"(?m)^{re.escape(key)}\s*:", meta) is not None


def read(path: Path, report: Report) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        report.error(f"{path.name}: file is not valid UTF-8")
        return ""


def validate_topics(topics: list[str] | None, goal: str, report: Report) -> None:
    required = TYPE_TOPICS[goal]
    if required is None:
        if topics and "pages" in topics:
            report.warn("Pages does not require a pages topic; the branch/file contract controls discovery.")
        return
    if topics is None:
        report.warn("Forgejo topics were not supplied; rerun with --topics using the live topic list.")
    elif required not in topics:
        report.error(f"required Forgejo topic is missing: {required}")


def validate_pages(root: Path, report: Report) -> None:
    refs = ("gh-pages", "refs/heads/gh-pages", "origin/gh-pages", "refs/remotes/origin/gh-pages")
    gh_ref = next((ref for ref in refs if git_file(root, ref, "index.html")), None)
    branch_exists = any(git(root, "rev-parse", "--verify", "--quiet", ref).returncode == 0 for ref in refs)
    if branch_exists and not gh_ref:
        report.error("gh-pages exists but its root does not contain index.html")
    elif not branch_exists and not (root / "docs" / "index.html").is_file():
        report.error("add index.html to gh-pages or docs/index.html to the default branch")
    if (root / "docs" / "index.html").is_file() and branch_exists:
        report.warn("gh-pages takes precedence; default-branch docs/index.html will not be served.")


def validate_space(root: Path, report: Report) -> None:
    readme = root / "README.md"
    meta = frontmatter(read(readme, report)) if readme.is_file() else ""
    external_url = scalar(meta, "external_url")
    if external_url:
        parsed = urlparse(external_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            report.error("README external_url must be an absolute HTTP or HTTPS URL")
        return

    dockerfile = root / "Dockerfile"
    if not dockerfile.is_file():
        report.error("add a root Dockerfile, or declare a valid README external_url")
        return
    docker_text = read(dockerfile, report)
    if "7860" not in docker_text:
        report.warn("Dockerfile does not mention the required container port 7860.")
    if not re.search(r"(?:0\.0\.0\.0|--host(?:=|\s+)0\.0\.0\.0)", docker_text):
        report.warn("confirm the application binds 0.0.0.0 rather than localhost.")


def validate_knowledge(root: Path, report: Report) -> None:
    directory = root / "articles"
    articles = sorted(directory.glob("*.md")) if directory.is_dir() else []
    if not articles:
        report.error("articles/ contains no top-level Markdown article")
        return
    nested = sorted(directory.glob("**/*.md"))
    if len(nested) > len(articles):
        report.warn("nested articles are not indexed; keep publications directly under articles/.")
    for article in articles:
        meta = frontmatter(read(article, report))
        if not meta:
            report.error(f"{article.name}: missing YAML frontmatter")
            continue
        if not has_key(meta, "title"):
            report.error(f"{article.name}: missing title")
        if not (has_key(meta, "topics") or has_key(meta, "tags")):
            report.error(f"{article.name}: add composable topics or tags")
        if has_key(meta, "formats"):
            report.warn(f"{article.name}: formats is not used by the current Knowledge reader.")


def validate_skill(root: Path, report: Report) -> None:
    path = root / "SKILL.md"
    if not path.is_file():
        report.error("missing required source: SKILL.md")
        return
    meta = frontmatter(read(path, report))
    for key in ("name", "description"):
        if not has_key(meta, key):
            report.error(f"SKILL.md: missing {key} frontmatter")


def validate_prompt(root: Path, topics: list[str] | None, report: Report) -> None:
    if not (root / "PROMPT.md").is_file():
        report.error("missing required source: PROMPT.md")
    tags = set(git_lines(root, "tag", "--list"))
    version_topics = {
        value.removeprefix("version-")
        for value in (topics or [])
        if re.fullmatch(r"version-v\d+(?:\.\d+)*", value, re.IGNORECASE)
    }
    if not tags:
        report.error("add an immutable v* Git version tag")
    if topics is not None and not version_topics:
        report.error("add a version-v* Forgejo topic")
    elif topics is not None and not (version_topics & tags):
        report.error("no version-v* topic has a matching Git tag")


def validate_mcp(root: Path, report: Report) -> None:
    if not (root / "README.md").is_file():
        report.error("missing required source: README.md")
    manifests = ("pyproject.toml", "requirements.txt", "package.json", "Cargo.toml", "go.mod")
    entrypoints = ("server.py", "main.py", "src", "server", "index.js", "index.ts")
    if not any((root / name).exists() for name in manifests):
        report.error("add an MCP dependency manifest")
    if not any((root / name).exists() for name in entrypoints):
        report.error("add a runnable MCP server entrypoint")


def validate_character(root: Path, report: Report) -> None:
    purupuru = (root / "avatar" / "default-settings.json").is_file() and any(
        (root / "avatar").glob("eyes-*-mouth-*.png")
    )
    pet = (
        (root / "pet.json").is_file() and (root / "spritesheet.webp").is_file()
    ) or any(
        path.with_name("spritesheet.webp").is_file()
        for path in (root / "assets" / "pets").glob("*/pet.json")
    )
    sheets = (root / "metadata" / "characters.csv").is_file() and (
        root / "assets" / "exports"
    ).is_dir()
    if not (purupuru or pet or sheets):
        report.error("add a detected PuruPuru, Codex Pet, or character-sheet file contract")


def validate_benchmark(root: Path, report: Report) -> None:
    if not (root / "README.md").is_file():
        report.error("missing required source: README.md")
    runner_names = (
        "Dockerfile", "pyproject.toml", "requirements.txt", "package.json",
        "run.py", "runner.py", "run.sh", "run.ps1",
    )
    if not any((root / name).exists() for name in runner_names):
        report.error("add a reproducible runner or dependency configuration")
    result_signals = ("results", "reports", "RESULTS.md", "leaderboard.json")
    if not any((root / name).exists() for name in result_signals):
        report.warn("retain at least one result or report artifact for reproducibility.")


def validate_automation_public_text(raw: str, name: str, report: Report) -> None:
    secret_assignment = re.search(
        r"(?im)^\s*(?:api[_-]?key|token|password|cookie|authorization|client[_-]?secret)\s*=",
        raw,
    )
    unsafe_value = re.search(
        r"(?i)(?:-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bBearer\s+\S{12,}|https?://[^/\s:@]+:[^@\s/]+@)",
        raw,
    )
    absolute_path = re.search(
        r"(?i)(?:[A-Za-z]:[\\/]|/(?:Users|home|root)/)",
        raw,
    )
    if secret_assignment or unsafe_value:
        report.error(f"{name}: embedded credential-like values are not publishable")
    if absolute_path:
        report.error(f"{name}: replace machine-specific absolute paths with placeholders")


def validate_automation(root: Path, report: Report) -> None:
    required_files = ("README.md", "automation.toml", "automation.example.toml", "LICENSE")
    for name in required_files:
        if not (root / name).is_file():
            report.error(f"missing required source: {name}")
    example_path = root / "automation.example.toml"
    if example_path.is_file():
        example_raw = read(example_path, report)
        if len(example_raw.encode("utf-8")) > 256 * 1024:
            report.error("automation.example.toml exceeds 262144 bytes")
        else:
            try:
                tomllib.loads(example_raw)
            except tomllib.TOMLDecodeError:
                report.error("automation.example.toml is not valid TOML")
            validate_automation_public_text(
                example_raw, "automation.example.toml", report
            )
    path = root / "automation.toml"
    if not path.is_file():
        return
    raw = read(path, report)
    if len(raw.encode("utf-8")) > 256 * 1024:
        report.error("automation.toml exceeds 262144 bytes")
        return
    try:
        config = tomllib.loads(raw)
    except tomllib.TOMLDecodeError:
        report.error("automation.toml is not valid TOML")
        return
    required_keys = (
        "schema_version", "name", "description", "platform", "format", "version",
        "schedule_type", "timezone", "trigger", "required_permissions",
        "required_connectors", "workspace_required", "delivery_type", "tested_on",
        "tags", "license", "enabled",
    )
    for key in required_keys:
        if key not in config:
            report.error(f"automation.toml: missing {key}")
    if config.get("schema_version") != 1:
        report.error("automation.toml: schema_version must be 1")
    if config.get("format") != "automation":
        report.error('automation.toml: format must be "automation"')
    if config.get("enabled") is not False:
        report.error("automation.toml: published Automations must set enabled = false")
    version = config.get("version")
    if not isinstance(version, str) or not re.fullmatch(
        r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?",
        version,
    ):
        report.error("automation.toml: version must use semantic versioning")
    elif f"v{version}" not in set(git_lines(root, "tag", "--list")):
        report.error(f"add immutable Git tag v{version}")
    validate_automation_public_text(raw, "automation.toml", report)


def validate_card_type(root: Path, goal: str, report: Report) -> None:
    readme = root / "README.md"
    if not readme.is_file():
        report.error("missing required source: README.md")
        return
    asset_patterns = {
        "model": ("*.safetensors", "*.bin", "*.onnx", "config.json"),
        "dataset": ("*.csv", "*.json", "*.jsonl", "*.parquet", "data"),
    }
    if not any(any(root.glob(pattern)) for pattern in asset_patterns[goal]):
        report.warn(f"{goal} has no detected asset; document an external retrieval command in README.md.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--goal", choices=TYPE_TOPICS, required=True)
    parser.add_argument("--topics", nargs="*", default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    root = args.path.resolve()
    report = Report(args.goal)
    if not root.is_dir():
        report.error(f"repository path does not exist: {root}")
        return report.emit(args.as_json)

    validate_topics(args.topics, args.goal, report)
    validators = {
        "pages": lambda: validate_pages(root, report),
        "space": lambda: validate_space(root, report),
        "knowledge": lambda: validate_knowledge(root, report),
        "skill": lambda: validate_skill(root, report),
        "prompt": lambda: validate_prompt(root, args.topics, report),
        "mcp": lambda: validate_mcp(root, report),
        "character": lambda: validate_character(root, report),
        "benchmark": lambda: validate_benchmark(root, report),
        "automation": lambda: validate_automation(root, report),
        "model": lambda: validate_card_type(root, "model", report),
        "dataset": lambda: validate_card_type(root, "dataset", report),
    }
    validators[args.goal]()
    return report.emit(args.as_json)


if __name__ == "__main__":
    raise SystemExit(main())
