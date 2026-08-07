"""Environment-driven configuration for the spaces-runner service.

Contract (fixed by PLAN.md, do not rename):
    FORGEJO_API        e.g. http://forgejo:3000/api/v1
    FORGEJO_TOKEN_FILE e.g. /shared/token
    PUBLIC_BASE_URL    e.g. http://localhost:8090
    DOCKER_NETWORK     e.g. nyankoface
"""
from __future__ import annotations

import os
import re

FORGEJO_API: str = os.environ.get("FORGEJO_API", "http://forgejo:3000/api/v1").rstrip("/")
FORGEJO_TOKEN_FILE: str = os.environ.get("FORGEJO_TOKEN_FILE", "/shared/token")
PUBLIC_BASE_URL: str = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8090")
DOCKER_NETWORK: str = os.environ.get("DOCKER_NETWORK", "nyankoface")
# 0 disables automatic suspension. CPU-only imported Spaces are intended to
# remain available like ordinary local services.
IDLE_TIMEOUT_MINUTES: int = int(os.environ.get("IDLE_TIMEOUT_MINUTES", "0"))
MAX_RUNNING_SPACES: int = max(1, int(os.environ.get("MAX_RUNNING_SPACES", "24")))
SPACE_DEPLOY_TIMEOUT_SECONDS: int = max(
    10,
    int(os.environ.get("NYANKOFACE_SPACE_DEPLOY_TIMEOUT_SECONDS", "540")),
)
# Private repository content must stay inside Forgejo's native access-control
# boundary. The runner only serves public Spaces unless this is explicitly
# enabled in a separately isolated deployment.
ALLOW_PRIVATE_SPACES: bool = os.environ.get("NYANKOFACE_ALLOW_PRIVATE_SPACES", "false").lower() == "true"

# Derived: forgejo host:port for git clone URLs (http://forgejo:3000/...)
FORGEJO_GIT_BASE: str = FORGEJO_API.split("/api/")[0].rstrip("/")

SPACE_LABEL_KEY = "nyankoface.space"
SPACE_LABEL_VALUE = "1"
OWNER_LABEL_KEY = "nyankoface.owner"
REPO_LABEL_KEY = "nyankoface.repo"
GENERATION_LABEL_KEY = "nyankoface.generation"
REVISION_LABEL_KEY = "nyankoface.revision"

CONTAINER_PORT = 7860
MEMORY_LIMIT = "2g"

REAPER_INTERVAL_SECONDS = 60

AGENT_DATA_DIR: str = os.environ.get("AGENT_DATA_DIR", "/data/agents")
DATABASE_URL: str = os.environ.get(
    "DATABASE_URL",
    "postgresql://nyankoface:nyankoface-postgres@postgres:5432/nyankoface_metrics",
)
PIPELINE_DB_SCHEMA: str = os.environ.get(
    "NYANKOFACE_PIPELINE_DB_SCHEMA", "nyankoface_pipeline"
)
if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", PIPELINE_DB_SCHEMA):
    raise ValueError("NYANKOFACE_PIPELINE_DB_SCHEMA must be a safe PostgreSQL identifier")
AGENT_CREDENTIALS_FILE: str = os.path.join(AGENT_DATA_DIR, "credentials.json")
SPACE_SECRETS_KEY_FILE: str = os.environ.get(
    "SPACE_SECRETS_KEY_FILE", os.path.join(AGENT_DATA_DIR, "space-secrets.key")
)
CONTROL_TOKEN: str | None = os.environ.get("NYANKOFACE_CONTROL_TOKEN") or None
SPACE_API_RATE_LIMIT_PER_MINUTE: int = max(
    1, int(os.environ.get("NYANKOFACE_SPACE_API_RATE_LIMIT_PER_MINUTE", "60"))
)
# Deployment and preview artifacts only; pipeline audit/state lives in
# PostgreSQL under PIPELINE_DB_SCHEMA.
PIPELINE_DATA_DIR: str = os.environ.get(
    "NYANKOFACE_PIPELINE_DATA_DIR", os.path.join(AGENT_DATA_DIR, "pipelines")
)
PIPELINE_API_RATE_LIMIT_PER_MINUTE: int = max(
    1, int(os.environ.get("NYANKOFACE_PIPELINE_API_RATE_LIMIT_PER_MINUTE", "60"))
)
PIPELINE_RECONCILE_INTERVAL_SECONDS: int = max(
    10,
    int(os.environ.get("NYANKOFACE_PIPELINE_RECONCILE_INTERVAL_SECONDS", "60")),
)
PRODUCTION_RECONCILE_BATCH_SIZE: int = max(
    1,
    int(os.environ.get("NYANKOFACE_PRODUCTION_RECONCILE_BATCH_SIZE", "10")),
)
PIPELINE_DISCOVERY_BATCH_SIZE: int = max(
    1,
    int(os.environ.get("NYANKOFACE_PIPELINE_DISCOVERY_BATCH_SIZE", "20")),
)
PREVIEW_RUN_RETENTION_SECONDS: int = max(
    60,
    int(os.environ.get("NYANKOFACE_PREVIEW_RUN_RETENTION_DAYS", "7"))
    * 24
    * 60
    * 60,
)
PREVIEW_RUN_MAX_COUNT: int = max(
    1,
    int(os.environ.get("NYANKOFACE_PREVIEW_RUN_MAX_COUNT", "10")),
)

# Remote GPU workers are opt-in. CPU Spaces keep using the local LXC Docker
# engine unless a repository explicitly carries the ``gpu`` topic.
GPU_WORKERS_ENABLED: bool = os.environ.get("NYANKOFACE_GPU_WORKERS_ENABLED", "false").lower() == "true"
GPU_WORKER_LEASE_SECONDS: int = max(
    30, int(os.environ.get("NYANKOFACE_GPU_WORKER_LEASE_SECONDS", "90"))
)
GPU_WORKER_STALE_SECONDS: int = max(
    GPU_WORKER_LEASE_SECONDS,
    int(os.environ.get("NYANKOFACE_GPU_WORKER_STALE_SECONDS", "120")),
)


def read_forgejo_token() -> str | None:
    """Read the Forgejo API token, if the shared token file is present.

    Returns None (anonymous mode) when the file is missing or empty, which
    is a valid state (e.g. before `seed` has finished, or for pure public
    repo access).
    """
    try:
        with open(FORGEJO_TOKEN_FILE, "r", encoding="utf-8") as fh:
            token = fh.read().strip()
        return token or None
    except OSError:
        return None
