from __future__ import annotations

import json
import ipaddress
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import idna


DEFAULT_RUNTIME_STATE_DIR = Path(tempfile.mkdtemp(prefix="nyankoface-mcp-"))
DEFAULT_WRITE_STATE_PATH = DEFAULT_RUNTIME_STATE_DIR / "write-safety.sqlite3"
DEFAULT_POLICY_STATE_PATH = DEFAULT_RUNTIME_STATE_DIR / "policy.sqlite3"
DEFAULT_AUDIT_STATE_PATH = DEFAULT_RUNTIME_STATE_DIR / "audit.sqlite3"


_PRIVATE_SERVICE_HOSTS = {
    "forgejo",
    "frontend",
    "gateway",
    "nyankoface-mcp",
    "spaces-runner",
}
_PRIVATE_DNS_SUFFIXES = (
    ".cluster.local",
    ".corp",
    ".home",
    ".home.arpa",
    ".internal",
    ".intranet",
    ".lan",
    ".local",
    ".localhost",
    ".private",
    ".production",
    ".svc",
    ".test",
    ".namespace",
)

def _canonical_hostname(hostname: str) -> str:
    dotted = (
        hostname
        .replace("\u3002", ".")
        .replace("\uff0e", ".")
        .replace("\uff61", ".")
        .rstrip(".")
    )
    try:
        return str(ipaddress.ip_address(dotted)).casefold()
    except ValueError:
        try:
            return idna.encode(
                dotted,
                uts46=True,
                transitional=False,
                std3_rules=True,
            ).decode("ascii").casefold()
        except idna.IDNAError as exc:
            raise ValueError("PUBLIC_BASE_URL must use a valid public hostname") from exc

def normalize_public_base_url(value: str, *, allow_test_public_base_url: bool = False) -> str:
    """Normalize the public origin and fail closed on private network hosts.

    ``PUBLIC_BASE_URL`` is used by MCP's OAuth protected-resource metadata and
    therefore becomes visible in ``WWW-Authenticate`` responses.  Localhost is
    retained for local development, but LAN, container, loopback-IP, and
    internal DNS origins are rejected before the server can advertise them.
    """
    if not isinstance(value, str):
        raise ValueError("PUBLIC_BASE_URL must be an HTTP(S) URL")
    candidate = value.strip().rstrip("/")
    if "\\" in candidate:
        raise ValueError("PUBLIC_BASE_URL must use a public origin without backslashes")
    if "%" in candidate:
        raise ValueError("PUBLIC_BASE_URL must use a public origin without percent-encoded authority")
    if "?" in candidate or "#" in candidate:
        raise ValueError("PUBLIC_BASE_URL must be a public origin without credentials, a query, or a fragment")
    parsed = urlsplit(candidate)
    hostname = _canonical_hostname(parsed.hostname or "")
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise ValueError("PUBLIC_BASE_URL must be an HTTP(S) URL")
    if parsed.path not in {"", "/"}:
        raise ValueError("PUBLIC_BASE_URL must be a public origin without a path")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("PUBLIC_BASE_URL must not contain credentials, a query, or a fragment")

    is_private_host = (
        hostname != "localhost"
        and (
            hostname in _PRIVATE_SERVICE_HOSTS
            or ("." not in hostname and ":" not in hostname)
            or hostname.endswith(_PRIVATE_DNS_SUFFIXES)
            or _is_non_global_ip(hostname)
        )
    )
    if allow_test_public_base_url and hostname == "ha.test":
        is_private_host = False
    if is_private_host:
        raise ValueError(
            "PUBLIC_BASE_URL must use a public origin; private or internal hosts are not allowed"
        )
    authority_host = f"[{hostname}]" if ":" in hostname else hostname
    if parsed.port is not None:
        authority_host = f"{authority_host}:{parsed.port}"
    return f"{parsed.scheme.lower()}://{authority_host}"


def _is_non_global_ip(hostname: str) -> bool:
    if _looks_like_legacy_ipv4(hostname):
        legacy_ipv4 = _legacy_ipv4_address(hostname)
        return legacy_ipv4 is None or legacy_ipv4.is_multicast or not legacy_ipv4.is_global
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return address.is_multicast or not address.is_global


def _legacy_ipv4_address(hostname: str) -> ipaddress.IPv4Address | None:
    """Parse resolver-style dotted IPv4 spellings before routing decisions."""
    parts = hostname.split(".")
    if not 1 <= len(parts) <= 4:
        return None
    values = [_legacy_ipv4_component(part) for part in parts]
    if any(value is None for value in values):
        return None
    numeric_values = [value for value in values if value is not None]
    limits = {1: [0xFFFFFFFF], 2: [0xFF, 0xFFFFFF], 3: [0xFF, 0xFF, 0xFFFF], 4: [0xFF] * 4}[len(numeric_values)]
    if any(value > limit for value, limit in zip(numeric_values, limits, strict=True)):
        return None
    if len(numeric_values) == 1:
        packed = numeric_values[0]
    elif len(numeric_values) == 2:
        packed = (numeric_values[0] << 24) | numeric_values[1]
    elif len(numeric_values) == 3:
        packed = (numeric_values[0] << 24) | (numeric_values[1] << 16) | numeric_values[2]
    else:
        packed = (numeric_values[0] << 24) | (numeric_values[1] << 16) | (numeric_values[2] << 8) | numeric_values[3]
    return ipaddress.IPv4Address(packed)


def _looks_like_legacy_ipv4(hostname: str) -> bool:
    parts = hostname.split(".")
    return 1 <= len(parts) <= 4 and all(
        part.isdecimal() or part.casefold().startswith("0x")
        for part in parts
    )


def _legacy_ipv4_component(part: str) -> int | None:
    lowered = part.casefold()
    try:
        if lowered.startswith("0x"):
            if not re.fullmatch(r"0x[0-9a-f]+", lowered):
                return None
            return int(lowered[2:], 16)
        if len(part) > 1 and part.startswith("0"):
            if not re.fullmatch(r"0[0-7]*", part):
                return None
            return int(part, 8)
        if part.isdecimal():
            return int(part, 10)
    except ValueError:
        return None
    return None


@dataclass(frozen=True)
class Settings:
    forgejo_api: str = "http://forgejo:3000/api/v1"
    catalog_api: str = "http://frontend:3000"
    runner_api: str = "http://spaces-runner:8000/api"
    public_base_url: str = "https://localhost:8443"
    allow_test_public_base_url: bool = False
    token_file: Path = Path("/run/nyankoface-mcp/registry.json")
    request_timeout_seconds: float = 15.0
    max_file_bytes: int = 262_144
    json_response: bool = False
    listen_port: int = 8000
    instance_id: str = "nyankoface-mcp"
    allowed_hosts: tuple[str, ...] = ("localhost:*", "127.0.0.1:*", "nyankoface-mcp:8000")
    allowed_origins: tuple[str, ...] = ()
    # Compose explicitly mounts /data for durable production state.  A writable
    # private per-process temp directory keeps imports and local tooling isolated
    # when the service is run outside its container (for example in CI).
    write_state_path: Path = DEFAULT_WRITE_STATE_PATH
    policy_state_path: Path = DEFAULT_POLICY_STATE_PATH
    audit_state_path: Path = DEFAULT_AUDIT_STATE_PATH
    audit_retention_seconds: int = 7_776_000
    confirmation_ttl_seconds: int = 300
    idempotency_ttl_seconds: int = 86_400

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "public_base_url",
            normalize_public_base_url(
                self.public_base_url,
                allow_test_public_base_url=self.allow_test_public_base_url,
            ),
        )

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            forgejo_api=os.getenv("FORGEJO_API", cls.forgejo_api).rstrip("/"),
            catalog_api=os.getenv("NYANKOFACE_CATALOG_API", cls.catalog_api).rstrip("/"),
            runner_api=os.getenv("RUNNER_API", cls.runner_api).rstrip("/"),
            public_base_url=os.getenv("PUBLIC_BASE_URL", cls.public_base_url).rstrip("/"),
            allow_test_public_base_url=os.getenv(
                "NYANKOFACE_MCP_ALLOW_TEST_PUBLIC_BASE_URL", "false",
            ).lower() in {"1", "true", "yes"},
            token_file=Path(os.getenv("NYANKOFACE_MCP_TOKEN_FILE", str(cls.token_file))),
            request_timeout_seconds=float(os.getenv("NYANKOFACE_MCP_REQUEST_TIMEOUT_SECONDS", "15")),
            max_file_bytes=int(os.getenv("NYANKOFACE_MCP_MAX_FILE_BYTES", "262144")),
            json_response=os.getenv("NYANKOFACE_MCP_JSON_RESPONSE", "false").lower() in {"1", "true", "yes"},
            listen_port=int(os.getenv("NYANKOFACE_MCP_LISTEN_PORT", "8000")),
            instance_id=os.getenv("NYANKOFACE_MCP_INSTANCE_ID", os.getenv("HOSTNAME", "nyankoface-mcp")),
            allowed_hosts=tuple(filter(None, os.getenv(
                "NYANKOFACE_MCP_ALLOWED_HOSTS", "localhost:*,127.0.0.1:*,nyankoface-mcp:8000",
            ).split(","))),
            allowed_origins=tuple(filter(None, os.getenv("NYANKOFACE_MCP_ALLOWED_ORIGINS", "").split(","))),
            write_state_path=Path(os.getenv(
                "NYANKOFACE_MCP_WRITE_STATE_PATH", str(cls.write_state_path),
            )),
            policy_state_path=Path(os.getenv(
                "NYANKOFACE_MCP_POLICY_STATE_PATH", str(cls.policy_state_path),
            )),
            audit_state_path=Path(os.getenv(
                "NYANKOFACE_MCP_AUDIT_STATE_PATH", str(cls.audit_state_path),
            )),
            audit_retention_seconds=int(os.getenv(
                "NYANKOFACE_MCP_AUDIT_RETENTION_SECONDS", "7776000",
            )),
            confirmation_ttl_seconds=int(os.getenv(
                "NYANKOFACE_MCP_CONFIRMATION_TTL_SECONDS", "300",
            )),
            idempotency_ttl_seconds=int(os.getenv(
                "NYANKOFACE_MCP_IDEMPOTENCY_TTL_SECONDS", "86400",
            )),
        )


def load_token_records(path: Path) -> list[dict]:
    """Load opaque-token metadata without ever returning token material."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    records = payload.get("tokens", []) if isinstance(payload, dict) else []
    return [item for item in records if isinstance(item, dict)]
