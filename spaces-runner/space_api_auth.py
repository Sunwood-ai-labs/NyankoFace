"""Cookie-free Forgejo PAT authorization for the public Space API."""
from __future__ import annotations

import hashlib
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

import httpx
from fastapi import HTTPException

import config


@dataclass(frozen=True)
class SpaceApiPrincipal:
    login: str
    token: str
    scopes: tuple[str, ...]


_rate_lock = threading.Lock()
_rate_events: dict[str, deque[float]] = defaultdict(deque)


def api_error(
    status: int,
    code: str,
    message: str,
    *,
    headers: dict[str, str] | None = None,
    retry_safe: bool | None = None,
) -> HTTPException:
    detail: dict[str, str | bool] = {"code": code, "message": message}
    if retry_safe is not None:
        detail["retry_safe"] = retry_safe
    return HTTPException(
        status_code=status,
        detail=detail,
        headers=headers,
    )


def bearer_token(authorization: str | None) -> str:
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise api_error(
            401,
            "invalid_token",
            "A Forgejo personal access token is required as a Bearer token.",
        )
    token = authorization[len(prefix):].strip()
    if len(token) < 20:
        raise api_error(401, "invalid_token", "The Bearer token is invalid.")
    return token


def check_rate_limit(
    token: str,
    *,
    limit_per_minute: int | None = None,
    namespace: str = "space-environment",
    label: str = "Space environment API",
) -> None:
    now = time.monotonic()
    key = f"{namespace}:{hashlib.sha256(token.encode('utf-8')).hexdigest()}"
    limit = limit_per_minute or config.SPACE_API_RATE_LIMIT_PER_MINUTE
    with _rate_lock:
        events = _rate_events[key]
        while events and events[0] <= now - 60:
            events.popleft()
        if len(events) >= limit:
            raise api_error(
                429,
                "rate_limit_exceeded",
                f"The {label} rate limit was exceeded.",
                headers={"Retry-After": "60"},
            )
        events.append(now)


def _scope_allows(scopes: tuple[str, ...], write: bool) -> bool:
    if not scopes:
        return True
    normalized = {scope.strip().lower() for scope in scopes}
    if "all" in normalized or "sudo" in normalized:
        return True
    if write:
        return bool(
            normalized
            & {
                "write:repository",
                "write:repo",
                "repo",
            }
        )
    return bool(
        normalized
        & {
            "read:repository",
            "write:repository",
            "read:repo",
            "write:repo",
            "repo",
        }
    )


def _forgejo_json(response: httpx.Response, message: str) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        raise api_error(
            503, "forgejo_unavailable", message, retry_safe=True,
        ) from exc
    if not isinstance(payload, dict):
        raise api_error(503, "forgejo_unavailable", message, retry_safe=True)
    return payload


async def authorize_space_pat(
    authorization: str | None,
    owner: str,
    repo: str,
    *,
    write: bool,
    require_space: bool = True,
    rate_limit_per_minute: int | None = None,
    rate_limit_namespace: str = "space-environment",
    rate_limit_label: str = "Space environment API",
) -> SpaceApiPrincipal:
    token = bearer_token(authorization)
    check_rate_limit(
        token,
        limit_per_minute=rate_limit_per_minute,
        namespace=rate_limit_namespace,
        label=rate_limit_label,
    )
    headers = {
        "Accept": "application/json",
        "Authorization": f"token {token}",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            user_response = await client.get(f"{config.FORGEJO_API}/user", headers=headers)
    except httpx.HTTPError as exc:
        raise api_error(
            503,
            "forgejo_unavailable",
            "Forgejo could not validate the token.",
            retry_safe=True,
        ) from exc
    if user_response.status_code in (401, 403):
        raise api_error(401, "invalid_token", "The Forgejo token is invalid or revoked.")
    if user_response.status_code != 200:
        raise api_error(
            503,
            "forgejo_unavailable",
            "Forgejo could not validate the token.",
            retry_safe=True,
        )
    user = _forgejo_json(user_response, "Forgejo returned an invalid user response.")
    login = str(user.get("login") or "").strip()
    if not login:
        raise api_error(401, "invalid_token", "The Forgejo token has no user identity.")
    raw_scopes = (
        user_response.headers.get("x-oauth-scopes")
        or user_response.headers.get("x-scopes")
        or ""
    )
    scopes = tuple(scope.strip() for scope in raw_scopes.split(",") if scope.strip())
    if not _scope_allows(scopes, write):
        raise api_error(
            403,
            "insufficient_scope",
            "This token does not have the required repository scope.",
        )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            repo_response = await client.get(
                f"{config.FORGEJO_API}/repos/{owner}/{repo}",
                headers=headers,
            )
    except httpx.HTTPError as exc:
        raise api_error(
            503,
            "forgejo_unavailable",
            "Forgejo could not validate repository access.",
            retry_safe=True,
        ) from exc
    if repo_response.status_code == 404:
        # Do not reveal whether a repository exists to an unauthorized token.
        raise api_error(
            404,
            "space_not_found",
            "The Space was not found or is not accessible to this token.",
        )
    if repo_response.status_code in (401, 403):
        raise api_error(
            403,
            "repository_forbidden",
            "This token cannot access the requested repository.",
        )
    if repo_response.status_code != 200:
        raise api_error(
            503,
            "forgejo_unavailable",
            "Forgejo could not validate repository access.",
            retry_safe=True,
        )
    repo_info = _forgejo_json(
        repo_response, "Forgejo returned an invalid repository response.",
    )
    raw_topics = repo_info.get("topics", [])
    if not isinstance(raw_topics, list) or not all(
        isinstance(topic, str) for topic in raw_topics
    ):
        raise api_error(
            503,
            "forgejo_unavailable",
            "Forgejo returned invalid repository topics.",
            retry_safe=True,
        )
    topics = set(raw_topics)
    if require_space and "space" not in topics:
        raise api_error(404, "space_not_found", "The repository is not an NyankoFace Space.")
    permissions = repo_info.get("permissions", {})
    if not isinstance(permissions, dict):
        raise api_error(503, "forgejo_unavailable",
                        "Forgejo returned invalid repository permissions.", retry_safe=True)
    allowed = permissions.get("push") if write else permissions.get("pull")
    if allowed is not True:
        raise api_error(
            403,
            "repository_forbidden",
            "Write permission is required." if write else "Read permission is required.",
        )
    return SpaceApiPrincipal(login=login, token=token, scopes=scopes)


def token_fingerprint(token: str) -> str:
    """Return a short audit-safe token identifier without retaining the token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def reset_rate_limits_for_tests() -> None:
    with _rate_lock:
        _rate_events.clear()
