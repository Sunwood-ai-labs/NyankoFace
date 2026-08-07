from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, unquote

import httpx
from mcp.server.fastmcp.exceptions import ToolError

from .config import Settings


class WriteResponseError(ToolError):
    """A sanitized, definite upstream response failure after write dispatch."""

    def __init__(self, message: str, code: str, retry_safe: bool):
        super().__init__(message)
        self.code = code
        self.retry_safe = retry_safe

CATALOG_KINDS = {
    "model", "dataset", "space", "skill", "mcp", "prompt", "doc",
    "automation", "character", "benchmark",
}
SPACE_START_STATUSES = frozenset({
    "queued", "leased", "building", "running", "unavailable",
})
SPACE_STOP_STATUSES = frozenset({"stopped", "cancelled", "cancel_requested"})
PAGES_DEPLOY_STATUSES = frozenset({"published", "queued", "failed"})
PIPELINE_DISPATCH_STATUSES = frozenset({"queued"})
PIPELINE_CANCEL_STATUSES = frozenset({"accepted"})
ENVIRONMENT_MUTATION_TIMEOUT_SECONDS = 120.0
ENVIRONMENT_APPLY_TIMEOUT_SECONDS = 720.0
JWK_PRIVATE_KEYS = frozenset({"d", "p", "q", "dp", "dq", "qi", "oth", "k"})
SECRET_KEY_COMPONENT = (
    r"(?:"
    r"(?-i:(?<![A-Za-z0-9])(?:basicAuth|registryAuth)(?![A-Za-z0-9]))|"
    r"(?<![A-Z0-9])(?:SECRET|TOKEN|AUTH|PWD|PASS(?:WORD|WD|PHRASE|CODE)?|CREDENTIALS?|AUTHORIZATION|"
    r"PRIVATE[_ -]?KEY|API[_ -]?KEY)(?![A-Z0-9])|"
    r"(?-i:(?<=[a-z0-9])(?:Token|Secret|Pwd|Pass(?:word|wd|phrase|code)?|Credentials?|Authorization|"
    r"PrivateKey|ApiKey)(?![a-z]))"
    r")"
)
SECRET_KEYS = re.compile(SECRET_KEY_COMPONENT, re.I)
SECRET_PATHS = re.compile(
    r"(^|/)("
    r"\.env($|\.)|.*secret.*|.*credential.*|"
    r"id_(rsa|dsa|ecdsa|ed25519)$|"
    r".*(?:private|key).*\.pem$|"
    r".*\.(key|p12|pfx|pkcs12|pk8|ppk|jks|keystore|kdbx)$|"
    r"\.npmrc$|\.pypirc$|\.netrc$|\.git-credentials$|\.gitconfig$|"
    r"\.docker/config\.json$|\.dockercfg$|\.aws/(credentials|config)$|"
    r"\.config/gcloud/(application_default_credentials\.json|credentials\.db)$|"
    r"\.kube/config$|\.ssh(/|$)|\.vault-token$|\.terraformrc$|"
    r"\.htpasswd$|\.pgpass$|auth\.json$"
    r")",
    re.I,
)
SECRET_VALUES = re.compile(
    r"(?i)("
    r"bearer\s+[a-z0-9._~+/=-]{16,}|"
    r"(?:ghp|gho|ghu|ghs|ghr|github_pat)-?[a-z0-9_-]{16,}|"
    r"(?<![a-z0-9_])sk-[a-z0-9_-]{16,}(?![a-z0-9_-])|"
    r"npm_[a-z0-9]{16,}|"
    r"age-secret-key-1[0-9a-z]{20,}|"
    r"(?:AKIA|ASIA)[A-Z0-9]{16}|"
    r"xox[baprs]-[a-z0-9-]{10,}"
    r")"
)
CONNECTION_PASSWORDS = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^/\s@]+(@)")
SECRET_ASSIGNMENTS = re.compile(
    r"(?im)("
    r"(?:"
    rf"[\"'][^\"'\r\n]*{SECRET_KEY_COMPONENT}[^\"'\r\n]*[\"']|"
    rf"[A-Z0-9_. -]*{SECRET_KEY_COMPONENT}[A-Z0-9_. -]*"
    r")\s*[:=](?![ \t]*[\"'\[\{])[ \t]*)"
    r"[^\r\n,;}]+"
)
SECRET_VALUE_START = re.compile(
    r"(?im)(?:"
    rf"[\"'][^\"'\r\n]*{SECRET_KEY_COMPONENT}[^\"'\r\n]*[\"']|"
    rf"[A-Z0-9_. -]*{SECRET_KEY_COMPONENT}[A-Z0-9_. -]*"
    r")\s*[:=]\s*(?P<value>[\[\{\"'])"
)
SECRET_YAML_BLOCK_START = re.compile(
    r"^(?P<indent>[ \t]*)(?P<list>-\s+)?(?P<key>"
    r"(?:"
    rf"[\"'][^\"'\r\n]*{SECRET_KEY_COMPONENT}[^\"'\r\n]*[\"']|"
    rf"[A-Z0-9_. -]*{SECRET_KEY_COMPONENT}[A-Z0-9_. -]*"
    r"))[ \t]*:[ \t]*(?:(?P<marker>[|>][^\r\n]*)|"
    r"(?P<plain>(?![ \t]*[\[\{\"'])[^\r\n]*\S[^\r\n]*))?"
    r"[ \t]*(?P<newline>\r?\n)?\Z",
    re.I,
)
PRIVATE_KEY_BLOCKS = re.compile(
    r"-----BEGIN (?P<label>[A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?)-----"
    r".*?"
    r"-----END (?P=label)-----",
    re.I | re.S,
)
SLUG = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
REF_FORBIDDEN = re.compile(r"[\x00-\x20\x7f~^:?*\[\\]")
ENCODED_REF_DELIMITER = re.compile(r"%(?:2f|5c)", re.I)


def operational_error(
    code: str,
    message: str,
    action: str,
    *,
    retryable: bool,
) -> ToolError:
    """Return a stable actionable error without upstream bodies or locations."""
    return ToolError(json.dumps({
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "action": action,
        }
    }, ensure_ascii=False, separators=(",", ":")))


def operational_error_code(error: ToolError) -> str | None:
    """Return the stable code carried by an operational ToolError."""
    try:
        payload = json.loads(str(error))
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    details = payload.get("error")
    if not isinstance(details, dict):
        return None
    code = details.get("code")
    return code if isinstance(code, str) else None


def _latest_updated_at(value: Any) -> str | None:
    candidates: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"updated_at", "updated", "stopped", "started", "created_at"} and item:
                candidates.append(str(item))
            candidates.extend(filter(None, [_latest_updated_at(item)]))
    elif isinstance(value, list):
        for item in value:
            candidates.extend(filter(None, [_latest_updated_at(item)]))
    return max(candidates) if candidates else None


def resource_document(
    data: Any,
    *,
    max_age: int = 30,
    pagination: dict[str, int] | None = None,
    sanitizer: Callable[[Any], Any] | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    """Wrap safe JSON data in the cache contract shared by tools/resources."""
    safe = (sanitizer or redact)(data)
    etag_representation: dict[str, Any] = {"data": safe}
    if pagination is not None:
        etag_representation["pagination"] = pagination
    if updated_at is not None:
        etag_representation["updated_at"] = updated_at
    canonical = json.dumps(
        etag_representation,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    metadata: dict[str, Any] = {
        "mime_type": "application/json",
        "etag": f'W/"{hashlib.sha256(canonical.encode("utf-8")).hexdigest()}"',
        "cache": {"visibility": "private", "max_age": max_age},
        "updated_at": updated_at or _latest_updated_at(safe),
    }
    if pagination is not None:
        metadata["pagination"] = pagination
    return {"data": safe, "_meta": metadata}


def _indent_width(value: str) -> int:
    return len(value.expandtabs(4))


def _redact_yaml_blocks(value: str) -> str:
    lines = value.splitlines(keepends=True)
    result: list[str] = []
    index = 0
    while index < len(lines):
        match = SECRET_YAML_BLOCK_START.match(lines[index])
        if match is None:
            result.append(lines[index])
            index += 1
            continue

        base_width = _indent_width(
            match.group("indent") + (match.group("list") or "")
        )
        marker = match.group("marker")
        end = index + 1
        child_indent: str | None = None
        while end < len(lines):
            body_line = lines[end]
            if not body_line.strip():
                end += 1
                continue
            leading = re.match(r"[ \t]*", body_line).group(0)
            if body_line[len(leading):].startswith("#"):
                end += 1
                continue
            width = _indent_width(leading)
            sequence_text = body_line[len(leading):].rstrip("\r\n")
            indentationless_item = (
                marker is None
                and width == base_width
                and re.match(r"-(?:[ \t]|$)", sequence_text) is not None
            )
            if width <= base_width and not indentationless_item:
                break
            if width > base_width:
                child_indent = child_indent or leading
            end += 1

        newline = match.group("newline") or "\n"
        prefix = f'{match.group("indent")}{match.group("list") or ""}{match.group("key")}: '
        if marker is None:
            result.append(f"{prefix}[REDACTED]{newline}")
        else:
            result.append(f"{prefix}{marker}{newline}")
            result.append(f"{child_indent or match.group('indent') + '  '}[REDACTED]{newline}")
        index = end
    return "".join(result)


def _structured_value_end(value: str, start: int) -> tuple[int, str] | None:
    if value.startswith("[REDACTED]", start):
        return None
    opening = value[start]
    if opening in {'"', "'"}:
        delimiter = opening * 3 if value.startswith(opening * 3, start) else opening
        index = start + len(delimiter)
        while index < len(value):
            if delimiter == "'" and value.startswith("''", index):
                index += 2
                continue
            if value.startswith(delimiter, index):
                return index + len(delimiter), f"{delimiter}[REDACTED]{delimiter}"
            if value[index] == "\\" and opening == '"':
                index += 2
            else:
                index += 1
        return None

    pairs = {"[": "]", "{": "}"}
    stack = [pairs[opening]]
    quote: str | None = None
    index = start + 1
    while index < len(value):
        if quote is not None:
            if value.startswith(quote, index):
                index += len(quote)
                quote = None
            elif value[index] == "\\" and quote.startswith('"'):
                index += 2
            else:
                index += 1
            continue
        if value.startswith('"""', index) or value.startswith("'''", index):
            quote = value[index:index + 3]
            index += 3
            continue
        if value[index] in {'"', "'"}:
            quote = value[index]
            index += 1
            continue
        if value[index] == "#":
            newline = value.find("\n", index)
            index = len(value) if newline < 0 else newline + 1
            continue
        if value[index] in pairs:
            stack.append(pairs[value[index]])
        elif value[index] in {"}", "]"}:
            if value[index] != stack[-1]:
                return None
            stack.pop()
            if not stack:
                return index + 1, '"[REDACTED]"'
        index += 1
    return None


def _redact_structured_assignments(value: str) -> str:
    parts: list[str] = []
    cursor = 0
    search_from = 0
    while match := SECRET_VALUE_START.search(value, search_from):
        start = match.start("value")
        if value.startswith("[REDACTED]", start):
            search_from = start + len("[REDACTED]")
            continue
        boundary = _structured_value_end(value, start)
        if boundary is None:
            parts.extend((value[cursor:start], '"[REDACTED]"'))
            cursor = len(value)
            break
        end, replacement = boundary
        parts.extend((value[cursor:start], replacement))
        cursor = end
        search_from = end
    if not parts:
        return value
    parts.append(value[cursor:])
    return "".join(parts)


def redact_text(value: str) -> str:
    value = CONNECTION_PASSWORDS.sub(r"\1[REDACTED]\2", value)
    try:
        structured = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        structured = None
    if isinstance(structured, (dict, list)):
        trailing_newline = "\n" if value.endswith(("\n", "\r")) else ""
        return json.dumps(redact(structured), ensure_ascii=False, indent=2) + trailing_newline

    value = PRIVATE_KEY_BLOCKS.sub("[REDACTED]", value)
    value = _redact_yaml_blocks(value)
    value = _redact_structured_assignments(value)

    def redact_assignment(match: re.Match[str]) -> str:
        prefix = match.group(1)
        assigned = match.group(0)[len(prefix):]
        if assigned.lstrip().startswith(("|", ">")):
            return match.group(0)
        if len(assigned) >= 2 and assigned[0] == assigned[-1] and assigned[0] in {'"', "'"}:
            return f"{prefix}{assigned[0]}[REDACTED]{assigned[-1]}"
        return f"{prefix}[REDACTED]"

    value = SECRET_ASSIGNMENTS.sub(redact_assignment, value)
    return SECRET_VALUES.sub("[REDACTED]", value)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        jwk_private = JWK_PRIVATE_KEYS if isinstance(value.get("kty"), str) else ()
        return {
            key: "[REDACTED]"
            if key in jwk_private or SECRET_KEYS.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


OPENAPI_IDENTIFIER_MAPS = {"properties", "schemas", "$defs"}


def sanitize_openapi(value: Any, *, identifier_map: bool = False) -> Any:
    """Remove sensitive examples while preserving structural schema identifiers."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.casefold() in {"example", "examples", "default"}:
                continue
            if not identifier_map and (
                SECRET_KEYS.search(key_text) or SECRET_PATHS.search(key_text)
            ):
                result[key_text] = "[REDACTED]"
                continue
            if key_text in OPENAPI_IDENTIFIER_MAPS and isinstance(item, dict):
                result[key_text] = sanitize_openapi(item, identifier_map=True)
                continue
            result[key_text] = sanitize_openapi(item)
        return result
    if isinstance(value, list):
        return [sanitize_openapi(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def validate_repo_identity(owner: str, repo: str) -> None:
    if (
        not SLUG.fullmatch(owner)
        or not SLUG.fullmatch(repo)
        or owner in {".", ".."}
        or repo in {".", ".."}
    ):
        raise ToolError("Invalid repository identity")


def validate_ref(value: str) -> str:
    ref = value
    decoded = unquote(ref)
    segments = ref.split("/")
    decoded_segments = decoded.split("/")
    if (
        not ref
        or len(ref) > 200
        or ref != ref.strip()
        or REF_FORBIDDEN.search(ref)
        or ref == "@"
        or ref.startswith("/")
        or ref.endswith("/")
        or ref.endswith(".")
        or ".." in ref
        or "@{" in ref
        or any(
            segment in {"", ".", ".."}
            or segment.startswith(".")
            or segment.endswith(".lock")
            for segment in segments
        )
        or ENCODED_REF_DELIMITER.search(ref)
        or (decoded != ref and (
            ".." in decoded
            or "@{" in decoded
            or any(segment in {"", ".", ".."} for segment in decoded_segments)
        ))
    ):
        raise ToolError("Invalid repository ref")
    return ref


def validate_content_path(value: str) -> str:
    clean = value.strip("/")
    decoded = unquote(clean)
    if (
        not clean
        or clean != value
        or decoded != clean
        or "\\" in clean
        or any(segment in {"", ".", ".."} for segment in clean.split("/"))
        or SECRET_PATHS.search(clean)
    ):
        raise ToolError("This file path is not available through the MCP read API")
    return clean


def response_metadata(
    payload: Any,
    upstream_etag: str | None = None,
    cache_control: str = "private, max-age=60",
) -> dict[str, Any]:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    updated = None
    candidates = payload.get("items", []) if isinstance(payload, dict) else []
    if isinstance(payload, dict):
        updated = payload.get("updated_at") or payload.get("updatedAt")
    if not updated and isinstance(candidates, list):
        timestamps = [
            str(item.get("updated_at") or item.get("updatedAt"))
            for item in candidates if isinstance(item, dict) and (item.get("updated_at") or item.get("updatedAt"))
        ]
        updated = max(timestamps, default=None)
    return {
        "mime_type": "application/json",
        "updated_at": updated,
        "etag": upstream_etag or f'"sha256-{hashlib.sha256(canonical.encode()).hexdigest()}"',
        "cache_control": cache_control,
    }


class NyankoFaceAdapter:
    """Boundary over public NyankoFace/Forgejo APIs; never uses an admin PAT."""

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    async def _get(
        self,
        base: str,
        path: str,
        token: str | None = None,
        params: dict | None = None,
        auth_scheme: str = "token",
        operation: str = "NyankoFace read",
        sanitizer: Callable[[Any], Any] | None = None,
    ) -> Any:
        payload, _ = await self._get_with_metadata(
            base,
            path,
            token,
            params,
            auth_scheme,
            operation,
            sanitizer,
        )
        return payload

    async def _get_with_metadata(
        self,
        base: str,
        path: str,
        token: str | None = None,
        params: dict | None = None,
        auth_scheme: str = "token",
        operation: str = "NyankoFace read",
        sanitizer: Callable[[Any], Any] | None = None,
    ) -> tuple[Any, dict[str, str]]:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"{auth_scheme} {token}"
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.request_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.get(f"{base}{path}", headers=headers, params=params)
        except httpx.HTTPError as exc:
            raise operational_error(
                "upstream_unavailable",
                f"{operation} is temporarily unavailable",
                "Retry the read after the upstream service is healthy.",
                retryable=True,
            ) from exc
        if response.status_code in {401, 403, 404}:
            raise operational_error(
                "not_found_or_unauthorized",
                "Resource was not found or is not authorized",
                "Verify the repository identity and the caller's current read permission.",
                retryable=False,
            )
        if response.status_code == 429:
            raise operational_error(
                "rate_limited",
                f"{operation} is temporarily rate limited",
                "Retry after the service's rate-limit window resets.",
                retryable=True,
            )
        if response.status_code >= 500:
            raise operational_error(
                "upstream_unavailable",
                f"{operation} is temporarily unavailable",
                "Retry the read after the upstream service is healthy.",
                retryable=True,
            )
        if response.status_code >= 400:
            raise operational_error(
                "upstream_rejected",
                f"{operation} could not be completed",
                "Check the requested parameters and current repository state.",
                retryable=False,
            )
        try:
            return (sanitizer or redact)(response.json()), {
                "etag": response.headers.get("etag", ""),
                "last-modified": response.headers.get("last-modified", ""),
                "cache-control": response.headers.get("cache-control", ""),
                "x-total-count": response.headers.get("x-total-count", ""),
            }
        except ValueError as exc:
            raise operational_error(
                "invalid_upstream_response",
                f"{operation} returned an invalid response",
                "Retry after the upstream service is healthy.",
                retryable=True,
            ) from exc

    async def _write(
        self,
        method: str,
        path: str,
        token: str | None,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        if not token:
            raise ToolError("Resource was not found or is not authorized")
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.request_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.request(
                    method,
                    f"{self.settings.forgejo_api}{path}",
                    headers={"Accept": "application/json", "Authorization": f"token {token}"},
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise ToolError("NyankoFace upstream is temporarily unavailable") from exc
        if response.status_code in {401, 403, 404}:
            raise WriteResponseError(
                "Resource was not found or is not authorized", "upstream_rejected", True,
            )
        if response.status_code >= 400:
            raise WriteResponseError(
                f"NyankoFace upstream returned HTTP {response.status_code}",
                "upstream_http_error",
                response.status_code < 500,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise WriteResponseError(
                "NyankoFace upstream returned invalid JSON", "invalid_upstream_response", False,
            ) from exc
        if not isinstance(payload, dict):
            raise WriteResponseError(
                "NyankoFace upstream returned invalid JSON", "invalid_upstream_response", False,
            )
        return redact(payload)

    async def _control_write(
        self,
        path: str,
        token: str | None,
        allowed_statuses: frozenset[str],
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Dispatch one PAT-authenticated Runner mutation with a strict result projection."""
        if not token:
            raise ToolError("Resource was not found or is not authorized")
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.request_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    f"{self.settings.runner_api}{path}",
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {token}",
                    },
                    json=body or {},
                )
        except httpx.HTTPError as exc:
            raise ToolError("NyankoFace control API is temporarily unavailable") from exc
        try:
            response_payload = response.json()
        except ValueError as exc:
            if response.status_code < 400:
                raise WriteResponseError(
                    "NyankoFace control API returned invalid JSON",
                    "invalid_upstream_response",
                    False,
                ) from exc
            response_payload = {}
        if response.status_code >= 400:
            detail = response_payload.get("detail", {}) if isinstance(response_payload, dict) else {}
            if not isinstance(detail, dict):
                detail = {}
            code = str(detail.get("code") or "control_rejected")
            message = str(detail.get("message") or "NyankoFace control request was rejected")
            declared_retry_safe = detail.get("retry_safe")
            retry_safe = (
                declared_retry_safe
                if isinstance(declared_retry_safe, bool)
                else response.status_code < 500
            )
            raise WriteResponseError(
                message,
                code,
                retry_safe,
            )
        if (
            not isinstance(response_payload, dict)
            or not isinstance(response_payload.get("status"), str)
            or response_payload["status"].strip() not in allowed_statuses
        ):
            raise WriteResponseError(
                "NyankoFace control API returned an invalid response",
                "invalid_upstream_response",
                False,
            )
        allowed = {
            "owner", "repo", "status", "execution", "job_id", "revision", "url",
            "method", "public_url", "actions_url", "workflow", "ref", "environment",
            "action", "run_number",
        }
        return redact({key: value for key, value in response_payload.items() if key in allowed})

    async def _environment_write(
        self,
        method: str,
        path: str,
        token: str | None,
        operation: str,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        expected_name: str | None = None,
        expected_kind: str | None = None,
        expected_scope: str | None = None,
        expected_revision: str | None = None,
    ) -> dict[str, Any]:
        """Mutate environment state without reflecting confidential input or errors."""
        if not token:
            raise ToolError("Resource was not found or is not authorized")
        timeout = (ENVIRONMENT_APPLY_TIMEOUT_SECONDS if operation == "apply"
                   else ENVIRONMENT_MUTATION_TIMEOUT_SECONDS)
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                transport=self.transport,
            ) as client:
                response = await client.request(
                    method,
                    f"{self.settings.runner_api}{path}",
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {token}",
                    },
                    json=body,
                    params=params,
                )
        except httpx.HTTPError as exc:
            raise ToolError("NyankoFace environment API is temporarily unavailable") from exc
        if response.status_code >= 400:
            # Runner validation and proxy bodies can echo submitted values.
            # Never forward them across this write-only boundary. Preserve only
            # an explicitly boolean retry classification from structured JSON.
            retry_safe = response.status_code < 500
            try:
                error_payload = response.json()
            except ValueError:
                error_payload = None
            detail = error_payload.get("detail") if isinstance(error_payload, dict) else None
            if isinstance(detail, dict) and isinstance(detail.get("retry_safe"), bool):
                retry_safe = detail["retry_safe"]
            raise WriteResponseError(
                "NyankoFace environment request was rejected",
                "environment_rejected",
                retry_safe,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise WriteResponseError(
                "NyankoFace environment API returned an invalid response",
                "invalid_upstream_response",
                False,
            ) from exc
        if not isinstance(payload, dict):
            raise WriteResponseError(
                "NyankoFace environment API returned an invalid response",
                "invalid_upstream_response",
                False,
            )
        allowed_shapes = {
            "set": {"item", "restart_required", "runtime"},
            "delete": {"deleted", "name", "restart_required", "runtime"},
            "apply": {"status", "restart_required", "runtime"},
        }
        allowed_keys = allowed_shapes.get(operation)
        item = payload.get("item")
        valid = allowed_keys is not None and set(payload).issubset(allowed_keys)
        if operation == "set":
            valid = valid and isinstance(item, dict) and (
                item.get("name") == expected_name
                and item.get("kind") == expected_kind
                and item.get("scope") == expected_scope
                and item.get("enabled") is True
                and item.get("configured") is True
                and payload.get("restart_required") is True
                and "runtime" in payload
                and payload.get("runtime") is None
            )
        elif operation == "delete":
            valid = valid and isinstance(payload.get("deleted"), bool) and (
                payload.get("name") == expected_name
                and payload.get("restart_required") is True
                and "runtime" in payload
                and payload.get("runtime") is None
            )
        elif operation == "apply":
            runtime = payload.get("runtime")
            valid = valid and payload.get("status") == "applied" and (
                payload.get("restart_required") is False
                and isinstance(runtime, dict)
                and runtime.get("status") == "running"
                and (
                    expected_revision is None
                    or runtime.get("revision") == expected_revision
                )
            )
        if not valid:
            raise WriteResponseError(
                "NyankoFace environment API returned an invalid response",
                "invalid_upstream_response",
                False,
            )
        result: dict[str, Any] = {}
        for key in ("status", "deleted", "name", "restart_required"):
            if key in payload and isinstance(payload[key], (str, bool)):
                result[key] = payload[key]
        if isinstance(item, dict):
            result["item"] = {
                key: item[key]
                for key in (
                    "name", "kind", "scope", "enabled", "configured",
                    "created_at", "updated_at",
                )
                if key in item and isinstance(item[key], (str, bool, int, float))
            }
        runtime = payload.get("runtime")
        if isinstance(runtime, dict):
            result["runtime"] = {
                key: runtime[key]
                for key in ("status", "execution", "job_id", "revision")
                if key in runtime and isinstance(runtime[key], (str, bool, int, float))
            }
        return redact(result)

    async def _get_bounded_file_json(self, path: str, token: str | None, params: dict) -> dict:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"token {token}"
        encoded_limit = 4 * ((self.settings.max_file_bytes + 2) // 3)
        response_limit = encoded_limit + 16_384
        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds,
                                         transport=self.transport) as client:
                async with client.stream("GET", f"{self.settings.forgejo_api}{path}",
                                         headers=headers, params=params) as response:
                    if response.status_code in {401, 403, 404}:
                        raise ToolError("Resource was not found or is not authorized")
                    if response.status_code >= 400:
                        raise ToolError(f"NyankoFace upstream returned HTTP {response.status_code}")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > response_limit:
                            raise ToolError("Only bounded regular files are available")
                        body.extend(chunk)
        except httpx.HTTPError as exc:
            raise ToolError("NyankoFace upstream is temporarily unavailable") from exc
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise ToolError("NyankoFace upstream returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ToolError("NyankoFace upstream returned invalid JSON")
        return payload

    async def search_catalog(self, kind: str, query: str = "", page: int = 1, limit: int = 20) -> dict:
        if kind not in CATALOG_KINDS:
            raise ToolError(f"Unsupported catalog kind: {kind}")
        page = max(1, page)
        limit = min(100, max(1, limit))
        payload, headers = await self._get_with_metadata(
            self.settings.catalog_api,
            "/api/catalog/repositories",
            params={"topic": kind, "q": query, "page": page, "limit": limit},
        )
        items = payload.get("items", payload.get("data", [])) if isinstance(payload, dict) else []
        # Defense in depth: catalog results are public only.
        safe = [item for item in items if isinstance(item, dict) and not item.get("private")]
        result = {
            "kind": kind,
            "page": int(payload.get("page", page)),
            "limit": int(payload.get("limit", limit)),
            "totalCount": int(payload.get("totalCount", len(safe))),
            "totalPages": int(payload.get("totalPages", 1)),
            "items": safe,
        }
        result["_meta"] = response_metadata(result, headers.get("etag") or None)
        return result

    async def list_repositories(
        self, query: str, page: int, limit: int, token: str | None,
    ) -> dict:
        page = max(1, page)
        limit = min(100, max(1, limit))
        payload, headers = await self._get_with_metadata(
            self.settings.forgejo_api,
            "/repos/search",
            token,
            {"q": query, "page": page, "limit": limit, "sort": "updated", "order": "desc"},
        )
        items = payload.get("data", []) if isinstance(payload, dict) else []
        if token is None:
            items = [item for item in items if isinstance(item, dict) and not item.get("private")]
        header_total = headers.get("x-total-count", "")
        total = int(header_total) if header_total.isdigit() else (
            int(payload.get("total_count", len(items))) if isinstance(payload, dict) else len(items)
        )
        result = {
            "page": page,
            "limit": limit,
            "totalCount": total,
            "items": items,
        }
        result["totalPages"] = max(1, (result["totalCount"] + limit - 1) // limit)
        result["_meta"] = response_metadata(result, headers.get("etag") or None)
        return result

    async def get_current_user_id(self, token: str) -> int:
        payload, _headers = await self._get_with_metadata(
            self.settings.forgejo_api,
            "/user",
            token,
        )
        user_id = payload.get("id") if isinstance(payload, dict) else None
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
            raise ToolError("NyankoFace upstream returned an invalid Forgejo identity")
        return user_id

    async def get_repository(self, owner: str, repo: str, token: str | None) -> dict:
        validate_repo_identity(owner, repo)
        payload, headers = await self._get_with_metadata(
            self.settings.forgejo_api,
            f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}",
            token,
        )
        if payload.get("private") and token is None:
            raise ToolError("Resource was not found or is not authorized")
        payload["_meta"] = response_metadata(payload, headers.get("etag") or None)
        return payload

    async def get_file(
        self,
        owner: str,
        repo: str,
        path: str,
        ref: str | None,
        token: str | None,
    ) -> dict:
        validate_repo_identity(owner, repo)
        clean = validate_content_path(path)
        repository = await self.get_repository(owner, repo, token)
        if repository.get("private") and token is None:
            raise ToolError("Resource was not found or is not authorized")
        effective_ref = validate_ref(ref) if ref and ref.strip() else validate_ref(repository.get("default_branch") or "main")
        payload = await self._get_bounded_file_json(
            f"/repos/{owner}/{repo}/contents/{quote(clean, safe='/')}",
            token,
            {"ref": effective_ref},
        )
        if payload.get("type") != "file" or int(payload.get("size", 0)) > self.settings.max_file_bytes:
            raise ToolError("Only bounded regular files are available")
        encoded = payload.get("content", "")
        encoded_limit = 4 * ((self.settings.max_file_bytes + 2) // 3)
        if not isinstance(encoded, str) or len(encoded) > encoded_limit:
            raise ToolError("Only bounded regular files are available")
        try:
            decoded = base64.b64decode(encoded, validate=True)
            if len(decoded) > self.settings.max_file_bytes:
                raise ToolError("Only bounded regular files are available")
            text = decoded.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ToolError("File is not UTF-8 text") from exc
        return {
            "owner": owner,
            "repo": repo,
            "path": clean,
            "ref": effective_ref,
            "sha": payload.get("sha"),
            "text": redact(text),
            "_meta": {
                "mime_type": "text/markdown" if clean.lower().endswith((".md", ".mdx")) else "text/plain",
                "updated_at": repository.get("updated_at"),
                "etag": f'"{payload.get("sha")}"' if payload.get("sha") else None,
                "cache_control": "private, max-age=60",
            },
        }

    async def get_tree(self, owner: str, repo: str, ref: str, token: str | None) -> dict:
        validate_repo_identity(owner, repo)
        effective_ref = validate_ref(ref)
        repository = await self.get_repository(owner, repo, token)
        payload, headers = await self._get_with_metadata(
            self.settings.forgejo_api,
            f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/contents",
            token,
            {"ref": effective_ref},
        )
        if not isinstance(payload, list):
            raise ToolError("NyankoFace upstream returned an invalid repository tree")
        entries = [item for item in payload if isinstance(item, dict)]
        result = {
            "owner": owner,
            "repo": repo,
            "ref": effective_ref,
            "updated_at": repository.get("updated_at"),
            "entries": entries,
        }
        result["_meta"] = response_metadata(result, headers.get("etag") or None)
        return result

    async def get_knowledge(self, owner: str, slug: str, token: str | None) -> dict:
        if not SLUG.fullmatch(owner) or owner in {".", ".."} or not SLUG.fullmatch(slug) or slug in {".", ".."}:
            raise ToolError("Invalid knowledge identity")
        # Knowledge is published from public `doc` repositories. The frontend
        # endpoint revalidates repository visibility for every detail request.
        payload, headers = await self._get_with_metadata(
            self.settings.catalog_api,
            f"/api/knowledge/{quote(owner, safe='')}/{quote(slug, safe='')}",
        )
        if not isinstance(payload, dict):
            raise ToolError("NyankoFace upstream returned invalid knowledge content")
        result = dict(payload)
        result["_meta"] = response_metadata(
            result,
            headers.get("etag") or None,
            headers.get("cache-control") or "private, no-cache, must-revalidate",
        )
        return result

    async def list_issues(self, owner: str, repo: str, state: str, page: int, limit: int, token: str | None) -> dict:
        validate_repo_identity(owner, repo)
        await self.get_repository(owner, repo, token)
        if state not in {"open", "closed", "all"}:
            raise ToolError("state must be open, closed, or all")
        items = await self._get(
            self.settings.forgejo_api,
            f"/repos/{owner}/{repo}/issues",
            token,
            {"state": state, "page": max(1, page), "limit": min(100, max(1, limit))},
        )
        return {"items": items if isinstance(items, list) else []}

    async def get_issue(self, owner: str, repo: str, number: int, token: str | None) -> dict:
        validate_repo_identity(owner, repo)
        if number < 1:
            raise ToolError("Issue number must be positive")
        await self.get_repository(owner, repo, token)
        return await self._get(self.settings.forgejo_api, f"/repos/{owner}/{repo}/issues/{number}", token)

    async def authorize_issue_write(self, owner: str, repo: str, token: str | None) -> None:
        validate_repo_identity(owner, repo)
        if not token:
            raise ToolError("Resource was not found or is not authorized")
        repository = await self.get_repository(owner, repo, token)
        permissions = repository.get("permissions")
        if not isinstance(permissions, dict) or not (
            permissions.get("push") is True or permissions.get("admin") is True
        ):
            raise ToolError("Resource was not found or is not authorized")

    async def authorize_control_write(self, owner: str, repo: str, token: str | None) -> None:
        await self.authorize_issue_write(owner, repo, token)

    async def create_issue(
        self, owner: str, repo: str, title: str, body: str, token: str | None,
    ) -> dict[str, Any]:
        return await self._write(
            "POST", f"/repos/{owner}/{repo}/issues", token,
            {"title": title, "body": body},
        )

    async def update_issue(
        self,
        owner: str,
        repo: str,
        number: int,
        changes: dict[str, Any],
        token: str | None,
    ) -> dict[str, Any]:
        return await self._write(
            "PATCH", f"/repos/{owner}/{repo}/issues/{number}", token, changes,
        )

    async def comment_issue(
        self, owner: str, repo: str, number: int, body: str, token: str | None,
    ) -> dict[str, Any]:
        return await self._write(
            "POST", f"/repos/{owner}/{repo}/issues/{number}/comments", token,
            {"body": body},
        )

    async def control_space(
        self, action: str, owner: str, repo: str, token: str | None,
    ) -> dict[str, Any]:
        if action not in {"start", "stop", "restart"}:
            raise ToolError("Unsupported Space control action")
        return await self._control_write(
            f"/v1/spaces/{quote(owner, safe='')}/{quote(repo, safe='')}/{action}",
            token,
            SPACE_STOP_STATUSES if action == "stop" else SPACE_START_STATUSES,
        )

    async def set_space_environment(
        self,
        owner: str,
        repo: str,
        name: str,
        kind: str,
        value: str,
        scope: str,
        token: str | None,
    ) -> dict[str, Any]:
        return await self._environment_write(
            "PUT",
            f"/v1/spaces/{quote(owner, safe='')}/{quote(repo, safe='')}/environment/{quote(name, safe='')}",
            token,
            "set",
            {
                "kind": kind,
                "expected_kind": kind,
                "value": value,
                "scope": scope,
                "enabled": True,
                "restart": False,
            },
            expected_name=name,
            expected_kind=kind,
            expected_scope=scope,
        )

    async def delete_space_environment(
        self,
        owner: str,
        repo: str,
        name: str,
        kind: str,
        token: str | None,
    ) -> dict[str, Any]:
        return await self._environment_write(
            "DELETE",
            f"/v1/spaces/{quote(owner, safe='')}/{quote(repo, safe='')}/environment/{quote(name, safe='')}",
            token,
            "delete",
            params={"expected_kind": kind, "restart": "false"},
            expected_name=name,
        )

    async def apply_space_environment(
        self,
        owner: str,
        repo: str,
        revision: str | None,
        token: str | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"restart": True}
        if revision is not None:
            body["revision"] = revision
        return await self._environment_write(
            "POST",
            f"/v1/spaces/{quote(owner, safe='')}/{quote(repo, safe='')}/environment/apply",
            token,
            "apply",
            body,
            expected_revision=revision,
        )

    async def deploy_pages(
        self, owner: str, repo: str, method: str, token: str | None,
    ) -> dict[str, Any]:
        return await self._control_write(
            f"/v1/pages/{quote(owner, safe='')}/{quote(repo, safe='')}/deploy",
            token,
            PAGES_DEPLOY_STATUSES,
            {"method": method, "confirmed": True},
        )

    async def dispatch_pipeline(
        self,
        owner: str,
        repo: str,
        workflow: str,
        ref: str,
        environment: str,
        inputs: dict[str, str],
        token: str | None,
    ) -> dict[str, Any]:
        return await self._control_write(
            f"/v1/pipelines/{quote(owner, safe='')}/{quote(repo, safe='')}/dispatch",
            token,
            PIPELINE_DISPATCH_STATUSES,
            {"workflow": workflow, "ref": ref, "environment": environment, "inputs": inputs},
        )

    async def pipeline_action(
        self,
        action: str,
        owner: str,
        repo: str,
        run_number: int,
        token: str | None,
    ) -> dict[str, Any]:
        if action not in {"cancel", "rollback"}:
            raise ToolError("Unsupported pipeline action")
        return await self._control_write(
            f"/v1/pipelines/{quote(owner, safe='')}/{quote(repo, safe='')}/runs/{run_number}/{action}",
            token,
            PIPELINE_CANCEL_STATUSES if action == "cancel" else PIPELINE_DISPATCH_STATUSES,
        )

    async def get_status(self, surface: str, owner: str, repo: str, token: str | None) -> dict:
        if surface not in {"spaces", "pages", "pipelines"}:
            raise ToolError("Unsupported status surface")
        await self.get_repository(owner, repo, token)
        if surface == "pipelines":
            if not token:
                raise ToolError("Resource was not found or is not authorized")
            return await self._get(
                self.settings.runner_api,
                f"/v1/pipelines/{owner}/{repo}",
                token,
                auth_scheme="Bearer",
                operation="Pipeline status",
            )
        return await self._get(
            self.settings.runner_api,
            f"/{surface}/{owner}/{repo}/status",
            operation=f"{surface.title()} status",
        )

    async def get_space_environment_metadata(
        self, owner: str, repo: str, token: str | None,
    ) -> dict:
        repository = await self.get_repository(owner, repo, token)
        if not token:
            raise operational_error(
                "upstream_identity_required",
                "Space environment metadata requires a caller Forgejo identity",
                "Configure a least-privileged caller token with repository read permission.",
                retryable=False,
            )
        payload = await self._get(
            self.settings.runner_api,
            f"/v1/spaces/{owner}/{repo}/environment",
            token,
            auth_scheme="Bearer",
            operation="Space environment metadata",
        )
        source = payload.get("items", []) if isinstance(payload, dict) else []
        items = [{
            "name": str(item.get("name", "")),
            "configured": bool(item.get("configured")),
            "updated_at": item.get("updated_at"),
        } for item in source if isinstance(item, dict) and item.get("name")]
        return resource_document(
            {"owner": owner, "repo": repo, "items": items,
             "updated_at": _latest_updated_at(items) or repository.get("updated_at")},
        )

    async def list_pipeline_runs(
        self, owner: str, repo: str, page: int, limit: int, token: str | None,
    ) -> dict:
        page = max(1, page)
        limit = min(50, max(1, limit))
        await self.get_repository(owner, repo, token)
        if not token:
            raise operational_error(
                "upstream_identity_required",
                "Pipeline run metadata requires a caller Forgejo identity",
                "Configure a least-privileged caller token with repository read permission.",
                retryable=False,
            )
        payload = await self._get(
            self.settings.runner_api,
            f"/v1/pipelines/{owner}/{repo}/runs",
            token,
            {"page": page, "limit": limit},
            auth_scheme="Bearer",
            operation="Pipeline runs",
        )
        runs = payload.get("runs", []) if isinstance(payload, dict) else []
        runs = runs if isinstance(runs, list) else []
        upstream_pagination = payload.get("pagination", {}) if isinstance(payload, dict) else {}
        pagination = {
            "page": int(upstream_pagination.get("page", page)),
            "limit": int(upstream_pagination.get("limit", limit)),
            "total_count": int(upstream_pagination.get("total_count", len(runs))),
            "total_pages": int(upstream_pagination.get("total_pages", 1)),
        }
        return resource_document(
            {"owner": owner, "repo": repo, "items": runs},
            pagination=pagination,
        )

    async def get_pipeline_run(
        self, owner: str, repo: str, run_number: int, token: str | None,
    ) -> dict:
        if run_number < 1:
            raise ToolError("Pipeline run number must be positive")
        await self.get_repository(owner, repo, token)
        if not token:
            raise operational_error(
                "upstream_identity_required",
                "Pipeline run metadata requires a caller Forgejo identity",
                "Configure a least-privileged caller token with repository read permission.",
                retryable=False,
            )
        payload = await self._get(
            self.settings.runner_api,
            f"/v1/pipelines/{owner}/{repo}/runs/{run_number}/metadata",
            token,
            auth_scheme="Bearer",
            operation="Pipeline run",
        )
        state = payload.get("state", {}) if isinstance(payload, dict) else {}
        source_run = state.get("run", {}) if isinstance(state, dict) else {}
        source_run = source_run if isinstance(source_run, dict) else {}
        safe_run_keys = {
            "title", "status", "canCancel", "canApprove", "canRerun",
            "approvalUrl", "done", "forgejoRunId",
        }
        source_jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
        safe_job_keys = {
            "id", "forgejo_job_id", "name", "status", "conclusion",
            "started", "stopped",
        }
        jobs = [
            {key: item.get(key) for key in safe_job_keys if key in item}
            for item in source_jobs
            if isinstance(item, dict)
        ]
        data = {
            "owner": owner,
            "repo": repo,
            "run_number": run_number,
            "updated_at": payload.get("updated_at") if isinstance(payload, dict) else None,
            "run": {key: source_run.get(key) for key in safe_run_keys if key in source_run},
            "jobs": jobs,
        }
        return resource_document(data)

    async def get_metrics(self, owner: str, repo: str, token: str | None) -> dict:
        repository = await self.get_repository(owner, repo, token)
        payload = await self._get(
            self.settings.runner_api,
            f"/metrics/repos/{owner}/{repo}",
            operation="Repository metrics",
        )
        source = payload if isinstance(payload, dict) else {}
        counters = {
            key: int(value)
            for key in ("views", "agent_views", "browser_views", "likes")
            if isinstance((value := source.get(key)), int)
            and not isinstance(value, bool)
        }
        return resource_document(
            {"owner": owner, "repo": repo, **counters},
            max_age=15,
            updated_at=repository.get("updated_at"),
        )

    async def get_openapi(self) -> dict:
        payload = await self._get(
            self.settings.runner_api,
            "/openapi.json",
            operation="OpenAPI document",
            sanitizer=sanitize_openapi,
        )
        return resource_document(payload, max_age=300, sanitizer=sanitize_openapi)
