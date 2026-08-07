from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.fastmcp.exceptions import ToolError

from .lifecycle import (
    LifecycleError,
    MUTATING_SCOPES,
    TokenLifecycleStore,
    parse_token_expiry,
    token_digest,
)


@dataclass(frozen=True)
class TokenRecord:
    token_sha256: str
    client_id: str
    scopes: tuple[str, ...]
    expires_at: int | None = None
    forgejo_token_file: str | None = None
    forgejo_user_id: int = 0
    subject_id: str = ""
    subject_type: str = "human"
    repositories: tuple[str, ...] = ()
    repository_permissions: tuple[tuple[str, str], ...] = ()


class NyankoFaceTokenVerifier(TokenVerifier):
    """Verify opaque NyankoFace tokens from a root-owned JSON secret mount."""

    def __init__(
        self,
        token_file: Path,
        forgejo_identity_resolver: Callable[[str], Awaitable[int]],
    ):
        self.token_file = token_file
        self.store = TokenLifecycleStore(token_file)
        self.forgejo_identity_resolver = forgejo_identity_resolver

    def records(self) -> list[TokenRecord]:
        parsed: list[TokenRecord] = []
        try:
            data = self.store._read()
        except ValueError:
            return []
        subjects = {
            str(item.get("subject_id")): item
            for item in data.get("subjects", [])
            if isinstance(item, dict)
        }
        for item in data.get("tokens", []):
            if not isinstance(item, dict):
                continue
            digest = str(item.get("token_sha256", "")).lower()
            scopes = item.get("scopes", [])
            subject = subjects.get(str(item.get("subject_id", "")))
            if (
                len(digest) != 64
                or not isinstance(scopes, list)
                or any(not isinstance(scope, str) for scope in scopes)
                or not subject
            ):
                continue
            try:
                expires_at = (
                    parse_token_expiry(item["expires_at"])
                    if "expires_at" in item and item["expires_at"] is not None
                    else None
                )
                forgejo_user_id = int(subject.get("forgejo_user_id", 0))
            except (TypeError, ValueError, LifecycleError):
                continue
            if forgejo_user_id <= 0:
                continue
            parsed.append(TokenRecord(
                token_sha256=digest,
                client_id=str(item.get("client_id", "nyankoface-client")),
                scopes=tuple(scopes),
                expires_at=expires_at,
                forgejo_token_file=(
                    str(subject["forgejo_token_file"])
                    if subject.get("forgejo_token_file") else None
                ),
                forgejo_user_id=forgejo_user_id,
                subject_id=str(item.get("subject_id", "")),
                subject_type=str(item.get("subject_type", subject.get("subject_type", "human"))),
                repositories=tuple(str(target) for target in item.get("repositories", [])),
                repository_permissions=tuple(
                    (str(target), str(permission))
                    for target, permission in subject.get("repository_permissions", {}).items()
                ),
            ))
        return parsed

    def find(self, token: str) -> TokenRecord | None:
        digest = token_digest(token)
        try:
            result = self.store.find_digest(digest)
        except LifecycleError:
            return None
        if result is None:
            return None
        item, subject = result
        try:
            forgejo_user_id = int(subject.get("forgejo_user_id", 0))
        except (TypeError, ValueError):
            return None
        if forgejo_user_id <= 0:
            return None
        return TokenRecord(
            token_sha256=digest,
            client_id=str(item.get("client_id", "nyankoface-client")),
            scopes=tuple(str(scope) for scope in item.get("scopes", [])),
            expires_at=int(item["expires_at"]),
            forgejo_token_file=(
                str(subject["forgejo_token_file"])
                if subject.get("forgejo_token_file") else None
            ),
            forgejo_user_id=forgejo_user_id,
            subject_id=str(item["subject_id"]),
            subject_type=str(item.get("subject_type", subject.get("subject_type", "human"))),
            repositories=tuple(str(target) for target in item.get("repositories", [])),
            repository_permissions=tuple(
                (str(target), str(permission))
                for target, permission in subject.get("repository_permissions", {}).items()
            ),
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        record = self.find(token)
        if record is None:
            return None
        upstream = self.upstream_token(record)
        if not upstream or record.forgejo_user_id <= 0:
            return None
        try:
            resolved_user_id = await self.forgejo_identity_resolver(upstream)
        except (OSError, ToolError, ValueError):
            return None
        if resolved_user_id != record.forgejo_user_id:
            return None
        return AccessToken(
            token=token,
            client_id=record.client_id,
            scopes=list(record.scopes),
            expires_at=record.expires_at,
        )

    def current_record(self) -> TokenRecord:
        access = get_access_token()
        record = self.find(access.token) if access else None
        if record is None:
            raise ToolError("NyankoFace authentication is required")
        return record

    def require(self, scope: str, owner: str | None = None, repo: str | None = None) -> TokenRecord:
        record = self.current_record()
        if scope not in record.scopes:
            raise ToolError(f"Missing required NyankoFace scope: {scope}")
        if (owner is None) != (repo is None):
            raise ToolError("A complete repository target is required")
        if owner is not None and repo is not None:
            target = f"{owner}/{repo}".lower()
            repositories = {item.lower() for item in record.repositories}
            if repositories and target not in repositories:
                raise ToolError("Resource was not found or is not authorized")
            permission = {key.lower(): value for key, value in record.repository_permissions}.get(target)
            required = "write" if scope in MUTATING_SCOPES else "read"
            order = {"read": 1, "write": 2, "admin": 3}
            if permission is None or order.get(permission, 0) < order[required]:
                raise ToolError("Mapped Forgejo subject has insufficient repository permission")
        return record

    def upstream_token(self, record: TokenRecord) -> str | None:
        if not record.forgejo_token_file:
            return None
        try:
            return Path(record.forgejo_token_file).read_text(encoding="utf-8").strip() or None
        except (OSError, UnicodeDecodeError):
            return None
