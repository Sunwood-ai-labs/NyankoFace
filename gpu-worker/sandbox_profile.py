"""Fail-closed, opt-in Docker options for private worker deployments.

The public example keeps this feature disabled. A private deployment can mount
its own profile file and allow only selected repository slugs to use the
additional runtime visibility needed by a host-integrated diagnostic app.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROFILE_ENVIRONMENT_KEY = "WORKER_RUNTIME_PROFILE_FILE"
DEFAULT_PROFILE_FILE = "/run/nyankoface/runtime-profile.json"


@dataclass(frozen=True)
class MetadataMount:
    source: str
    target: str


@dataclass(frozen=True)
class RuntimeProfile:
    repositories: frozenset[str]
    share_namespaces: bool
    metadata_mount: MetadataMount | None


def _repository_slug(owner: Any, repo: Any) -> str:
    owner_text = str(owner or "").strip().strip("/").lower()
    repo_text = str(repo or "").strip().strip("/").lower()
    if not owner_text or not repo_text or "/" in owner_text or "/" in repo_text:
        return ""
    return f"{owner_text}/{repo_text}"


def _slug_from_item(item: Any) -> str:
    if not isinstance(item, str):
        return ""
    parts = item.split("/", 1)
    if len(parts) != 2:
        return ""
    return _repository_slug(parts[0], parts[1])


def _absolute_linux_path(value: Any) -> str | None:
    candidate = str(value or "").strip()
    if not candidate or not candidate.startswith("/") or candidate == "/":
        return None
    return candidate


def _profile_path() -> Path:
    return Path(os.environ.get(PROFILE_ENVIRONMENT_KEY, DEFAULT_PROFILE_FILE))


def _read_document() -> dict[str, Any]:
    try:
        value = json.loads(_profile_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def load_profile() -> RuntimeProfile:
    document = _read_document()
    raw_repositories = document.get("repositories", [])
    if not isinstance(raw_repositories, list):
        raw_repositories = []
    repositories = frozenset(
        slug
        for item in raw_repositories
        for slug in [_slug_from_item(item)]
        if slug
    )

    raw_mount = document.get("metadata_mount")
    metadata_mount: MetadataMount | None = None
    if isinstance(raw_mount, dict) and raw_mount.get("read_only") is True:
        source = _absolute_linux_path(raw_mount.get("source"))
        target = _absolute_linux_path(raw_mount.get("target"))
        if source and target:
            metadata_mount = MetadataMount(source=source, target=target)

    return RuntimeProfile(
        repositories=repositories,
        share_namespaces=document.get("share_namespaces") is True,
        metadata_mount=metadata_mount,
    )


def docker_options_for(owner: Any, repo: Any) -> dict[str, Any]:
    """Return extra Docker options only for an explicitly trusted repository.

    The profile must opt into namespace sharing and a read-only metadata mount.
    Any missing, malformed, or incomplete setting returns an empty option set.
    """
    profile = load_profile()
    if not profile.share_namespaces or profile.metadata_mount is None:
        return {}
    if _repository_slug(owner, repo) not in profile.repositories:
        return {}

    mount = profile.metadata_mount
    return {
        "pid_mode": "host",
        "uts_mode": "host",
        "volumes": {
            mount.source: {
                "bind": mount.target,
                "mode": "ro",
            }
        },
    }
