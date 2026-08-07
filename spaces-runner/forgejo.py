"""Thin helpers for talking to the Forgejo API (repo existence / topics)."""
from __future__ import annotations

import base64
import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

import httpx

import config


class ForgejoError(Exception):
    """Raised when a repo can't be verified against Forgejo."""


class ForgejoPreflightError(ForgejoError):
    """Raised when a read-only Forgejo preflight fails before a write."""


class ForgejoWriteRejected(ForgejoError):
    """Forgejo definitively rejected a write without applying it."""


class ForgejoOutcomeUnknown(ForgejoError):
    """A Forgejo write may have been applied before its response failed."""

_PAGES_TOMBSTONE_PATH = ".nyankoface-pages-tombstone.json"
_COMMIT_SHA = re.compile(r"^[0-9a-f]{40,64}$")


def _headers(token: str | None) -> dict[str, str]:
    return {"Authorization": f"token {token}"} if token else {}


async def get_repo_info(owner: str, repo: str, token: str | None) -> dict:
    """Fetch repo metadata from Forgejo. Raises ForgejoError if not found."""
    headers = {"Authorization": f"token {token}"} if token else {}
    url = f"{config.FORGEJO_API}/repos/{owner}/{repo}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code == 404:
        raise ForgejoError(f"repository {owner}/{repo} not found")
    if resp.status_code != 200:
        raise ForgejoError(f"forgejo API returned {resp.status_code} for {owner}/{repo}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise ForgejoPreflightError(
            "Forgejo returned an invalid repository response"
        ) from exc
    if not isinstance(payload, Mapping):
        raise ForgejoPreflightError(
            "Forgejo returned an invalid repository response"
        )
    return dict(payload)


async def ensure_branch(
    owner: str,
    repo: str,
    branch: str,
    source_branch: str,
    token: str | None,
) -> bool:
    """Ensure ``branch`` exists, returning True only when it was created."""
    headers = _headers(token)
    branch_path = quote(branch, safe="")
    base_url = f"{config.FORGEJO_API}/repos/{owner}/{repo}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                f"{base_url}/branches/{branch_path}", headers=headers
            )
        except httpx.HTTPError as exc:
            raise ForgejoPreflightError("Forgejo branch check failed") from exc
        if response.status_code == 200:
            return False
        if response.status_code != 404:
            raise ForgejoPreflightError(
                f"Forgejo returned HTTP {response.status_code} while checking {branch}"
            )
        try:
            response = await client.post(
                f"{base_url}/branches",
                headers=headers,
                json={
                    "new_branch_name": branch,
                    "old_branch_name": source_branch,
                },
            )
        except httpx.HTTPError as exc:
            raise ForgejoOutcomeUnknown("Forgejo branch creation outcome is unknown") from exc
    if response.status_code not in (200, 201):
        if 400 <= response.status_code < 500:
            raise ForgejoWriteRejected(
                f"Forgejo rejected branch creation with HTTP {response.status_code}"
            )
        raise ForgejoOutcomeUnknown(
            f"Forgejo returned HTTP {response.status_code} while creating {branch}"
        )
    return True


async def upsert_repo_file(
    owner: str,
    repo: str,
    branch: str,
    path: str,
    content: str,
    message: str,
    token: str | None,
    actor: str,
) -> dict[str, Any]:
    """Create or replace a UTF-8 repository file and return its commit."""
    headers = _headers(token)
    safe_actor = re.sub(r"[^A-Za-z0-9._-]", "-", actor).strip(".-") or "nyankoface-pages"
    encoded_path = quote(path.strip("/"), safe="/")
    base_url = (
        f"{config.FORGEJO_API}/repos/{owner}/{repo}/contents/{encoded_path}"
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            current = await client.get(base_url, headers=headers, params={"ref": branch})
        except httpx.HTTPError as exc:
            raise ForgejoPreflightError("Forgejo file check failed") from exc
        sha = None
        if current.status_code == 200:
            try:
                current_data = current.json()
            except (ValueError, AttributeError) as exc:
                raise ForgejoPreflightError("Forgejo file check was invalid") from exc
            if not isinstance(current_data, dict):
                raise ForgejoPreflightError("Forgejo file check was invalid")
            sha = current_data.get("sha")
            encoded_current = current_data.get("content")
            if encoded_current:
                try:
                    current_content = base64.b64decode(encoded_current, validate=True).decode("utf-8")
                except (TypeError, ValueError) as exc:
                    raise ForgejoPreflightError("Forgejo file content was invalid") from exc
                if current_content == content:
                    return {
                        "sha": current_data.get("last_commit_sha") or sha or "",
                        "branch": branch,
                        "path": path,
                        "message": message,
                        "changed": False,
                    }
        elif current.status_code != 404:
            raise ForgejoPreflightError(
                f"Forgejo returned HTTP {current.status_code} while reading {path}"
            )
        payload = {
            "branch": branch,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "message": message,
            "author": {"name": safe_actor, "email": f"{safe_actor}@nyankoface.local"},
            "committer": {"name": safe_actor, "email": f"{safe_actor}@nyankoface.local"},
        }
        if sha:
            payload["sha"] = sha
        try:
            if sha:
                response = await client.put(base_url, headers=headers, json=payload)
            else:
                response = await client.post(base_url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise ForgejoOutcomeUnknown(
                f"Forgejo file write outcome is unknown for {path}"
            ) from exc
    if response.status_code not in (200, 201):
        detail = response.text[:240]
        if 400 <= response.status_code < 500:
            raise ForgejoWriteRejected(
                f"Forgejo rejected writing {path} with HTTP {response.status_code}: {detail}"
            )
        raise ForgejoOutcomeUnknown(
            f"Forgejo returned HTTP {response.status_code} while writing {path}: {detail}"
        )
    try:
        data = response.json()
    except (ValueError, AttributeError) as exc:
        raise ForgejoOutcomeUnknown(
            "Forgejo returned an invalid file write response"
        ) from exc
    if not isinstance(data, dict):
        raise ForgejoOutcomeUnknown("Forgejo returned an invalid file write response")
    commit = data.get("commit")
    if commit is not None and not isinstance(commit, dict):
        raise ForgejoOutcomeUnknown("Forgejo returned an invalid file write response")
    commit = commit or {}
    commit_sha = commit.get("sha") or commit.get("id") or ""
    return {
        "sha": commit_sha,
        "branch": branch,
        "path": path,
        "message": message,
        "changed": True,
    }


async def get_repo_topics(owner: str, repo: str, token: str | None) -> list[str]:
    headers = {"Authorization": f"token {token}"} if token else {}
    url = f"{config.FORGEJO_API}/repos/{owner}/{repo}/topics"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code != 200:
        return []
    data = resp.json()
    return data.get("topics", [])


async def get_pages_source(owner: str, repo: str, token: str | None) -> tuple[str, str] | None:
    """Return the public Pages source as ``(ref, directory_prefix)``.

    The compatible conventions are the same small subset most repositories
    expect from GitHub Pages: a dedicated ``gh-pages`` branch at its root, or
    a ``docs/`` directory on the default branch. Private repositories are
    never exposed through the unauthenticated Pages endpoint.
    """
    inspection = await inspect_pages_source(owner, repo, token)
    if inspection["status"] != "published":
        return None
    return (inspection["source_ref"], inspection["directory_prefix"])


async def inspect_pages_source(owner: str, repo: str, token: str | None) -> dict:
    """Inspect every supported Pages source and explain the result.

    Detection and delivery intentionally share this function. A branch alone
    is not a deployable site: the selected source must contain ``index.html``.
    """
    repo_info = await get_repo_info(owner, repo, token)
    default_branch = repo_info.get("default_branch") or "main"
    base = {
        "owner": owner,
        "repo": repo,
        "public": not bool(repo_info.get("private")),
        "default_branch": default_branch,
        "source": None,
        "source_ref": None,
        "directory_prefix": None,
        "index_path": None,
        "checks": [],
        "reasons": [],
    }
    if repo_info.get("private"):
        return {
            **base,
            "status": "private",
            "reasons": ["NyankoFace Pages only publishes public repositories."],
        }

    tombstone_status, tombstone_body, _ = await fetch_pages_asset(
        owner,
        repo,
        "gh-pages",
        "",
        _PAGES_TOMBSTONE_PATH,
        token,
    )
    if tombstone_status == 200:
        try:
            tombstone = json.loads(tombstone_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            tombstone = None
        expected_repository = f"{owner}/{repo}"
        if (
            not isinstance(tombstone, dict)
            or tombstone.get("schema") != 1
            or tombstone.get("repository") != expected_repository
            or tombstone.get("environment") != "production"
            or tombstone.get("operation") != "delete"
            or not _COMMIT_SHA.fullmatch(str(tombstone.get("sha") or ""))
            or not str(tombstone.get("run_id") or "").isdigit()
            or not str(tombstone.get("run_number") or "").isdigit()
            or not str(tombstone.get("event") or "").strip()
        ):
            return {
                **base,
                "status": "error",
                "reasons": [
                    "The production Pages deletion marker is invalid."
                ],
            }
        return {
            **base,
            "status": "missing",
            "reasons": [
                "The latest production deployment intentionally disabled Pages."
            ],
        }
    if tombstone_status != 404:
        return {
            **base,
            "status": "error",
            "reasons": [
                f"Forgejo returned HTTP {tombstone_status} while checking "
                f"{_PAGES_TOMBSTONE_PATH}."
            ],
        }

    candidates = [
        ("gh-pages", "gh-pages", "", "index.html"),
        ("docs", default_branch, "docs", "docs/index.html"),
    ]
    for source, ref, directory_prefix, index_path in candidates:
        status, _, _ = await fetch_pages_asset(
            owner, repo, ref, directory_prefix, "index.html", token
        )
        exists = status == 200
        base["checks"].append(
            {
                "id": f"{source}_index",
                "source": source,
                "ref": ref,
                "path": index_path,
                "ok": exists,
                "status": status,
            }
        )
        if exists:
            return {
                **base,
                "status": "published",
                "source": source,
                "source_ref": ref,
                "directory_prefix": directory_prefix,
                "index_path": index_path,
            }
        if status != 404:
            return {
                **base,
                "status": "error",
                "reasons": [
                    f"Forgejo returned HTTP {status} while checking {index_path}."
                ],
            }

    return {
        **base,
        "status": "missing",
        "reasons": [
            "Add index.html at the root of the gh-pages branch, "
            "or add docs/index.html on the default branch."
        ],
    }


async def fetch_pages_asset(
    owner: str,
    repo: str,
    ref: str,
    directory_prefix: str,
    asset_path: str,
    token: str | None,
) -> tuple[int, bytes, str | None]:
    """Load an asset from Forgejo's raw endpoint without touching disk."""
    path_parts = [part for part in (directory_prefix, asset_path) if part]
    raw_path = "/".join(path_parts)
    headers = {"Authorization": f"token {token}"} if token else {}
    url = f"{config.FORGEJO_API}/repos/{owner}/{repo}/raw/{ref}/{raw_path}"
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
        response = await client.get(url, headers=headers)
    return response.status_code, response.content, response.headers.get("content-type")


async def verify_space_repo(owner: str, repo: str, token: str | None) -> None:
    """Raise ForgejoError unless the repo exists and carries the `space` topic."""
    repo_info = await get_repo_info(owner, repo, token)
    if repo_info.get("private") and not config.ALLOW_PRIVATE_SPACES:
        raise ForgejoError("private Spaces are disabled by NYANKOFACE_ALLOW_PRIVATE_SPACES")
    topics = await get_repo_topics(owner, repo, token)
    if "space" not in topics:
        raise ForgejoError(f"repository {owner}/{repo} does not have the 'space' topic")


async def get_default_revision(owner: str, repo: str, token: str | None) -> str:
    """Resolve the default branch to an immutable commit SHA."""
    repo_info = await get_repo_info(owner, repo, token)
    branch = repo_info.get("default_branch") or "main"
    headers = {"Authorization": f"token {token}"} if token else {}
    url = f"{config.FORGEJO_API}/repos/{owner}/{repo}/branches/{branch}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url, headers=headers)
    if response.status_code != 200:
        raise ForgejoError(f"could not resolve {owner}/{repo}@{branch}")
    try:
        payload = response.json()
    except (ValueError, AttributeError) as exc:
        raise ForgejoError("Forgejo returned an invalid branch response") from exc
    if not isinstance(payload, dict):
        raise ForgejoError("Forgejo returned an invalid branch response")
    commit = payload.get("commit")
    if commit is not None and not isinstance(commit, dict):
        raise ForgejoError("Forgejo returned an invalid branch response")
    commit = commit or {}
    revision = commit.get("id") or commit.get("sha")
    if not revision:
        raise ForgejoError(f"Forgejo returned no commit SHA for {owner}/{repo}@{branch}")
    return revision


def clone_url(owner: str, repo: str, token: str | None) -> str:
    """Build a clone URL for the repo, authenticated when a token is available.

    Forgejo (like Gitea) accepts an OAuth2-style basic-auth login of
    `oauth2:<token>` as username with the token as password-equivalent, which
    works without needing to know the actual account username.
    """
    host = config.FORGEJO_GIT_BASE.split("://", 1)[-1]
    scheme = config.FORGEJO_GIT_BASE.split("://", 1)[0]
    if token:
        return f"{scheme}://oauth2:{token}@{host}/{owner}/{repo}.git"
    return f"{scheme}://{host}/{owner}/{repo}.git"
