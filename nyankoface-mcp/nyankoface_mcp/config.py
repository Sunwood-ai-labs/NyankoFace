from __future__ import annotations

import json
import ipaddress
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


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
    ".internal",
    ".intranet",
    ".lan",
    ".local",
    ".private",
    ".svc",
    ".test",
)


def normalize_public_base_url(value: str) -> str:
    """Normalize the public origin and fail closed on private network hosts.

    ``PUBLIC_BASE_URL`` is used by MCP's OAuth protected-resource metadata and
    therefore becomes visible in ``WWW-Authenticate`` responses.  Localhost is
    retained for local development, but LAN, container, loopback-IP, and
    internal DNS origins are rejected before the server can advertise them.
    """
    if not isinstance(value, str):
        raise ValueError("PUBLIC_BASE_URL must be an HTTP(S) URL")
    candidate = value.strip().rstrip("/")
    parsed = urlsplit(candidate)
    hostname = (parsed.hostname or "").rstrip(".").casefold()
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise ValueError("PUBLIC_BASE_URL must be an HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("PUBLIC_BASE_URL must not contain credentials, a query, or a fragment")

    is_private_host = (
        hostname != "localhost"
        and (
            hostname in _PRIVATE_SERVICE_HOSTS
            or "." not in hostname
            or hostname.endswith(_PRIVATE_DNS_SUFFIXES)
            or _is_non_global_ip(hostname)
        )
    )
    if is_private_host:
        raise ValueError(
            "PUBLIC_BASE_URL must use a public origin; private or internal hosts are not allowed"
        )
    return candidate


def _is_non_global_ip(hostname: str) -> bool:
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return not address.is_global


@dataclass(frozen=True)
class Settings:
    forgejo_api: str = "http://forgejo:3000/api/v1"
    catalog_api: str = "http://frontend:3000"
    runner_api: str = "http://spaces-runner:8000/api"
    public_base_url: str = "https://localhost:8443"
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
        object.__setattr__(self, "public_base_url", normalize_public_base_url(self.public_base_url))

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            forgejo_api=os.getenv("FORGEJO_API", cls.forgejo_api).rstrip("/"),
            catalog_api=os.getenv("NYANKOFACE_CATALOG_API", cls.catalog_api).rstrip("/"),
            runner_api=os.getenv("RUNNER_API", cls.runner_api).rstrip("/"),
            public_base_url=os.getenv("PUBLIC_BASE_URL", cls.public_base_url).rstrip("/"),
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
