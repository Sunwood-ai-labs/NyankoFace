from __future__ import annotations

import pathlib
import tomllib

from nyankoface_mcp import __version__


ROOT = pathlib.Path(__file__).parents[1]


def test_package_metadata_and_runtime_version_match():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert metadata["name"] == "nyankoface-mcp"
    assert metadata["version"] == __version__
    assert metadata["requires-python"] == ">=3.11,<3.14"
    assert metadata["license"] == "MIT"
    assert set(metadata["scripts"]) == {
        "nyankoface-mcp", "nyankoface-mcp-admin-server", "nyankoface-mcp-server", "nyankoface-mcp-stdio",
    }
    assert metadata["dependencies"] == [
        "httpx==0.28.1", "mcp==1.26.0", "starlette==1.3.1", "uvicorn==0.41.0",
    ]


def test_image_is_pinned_and_carries_package_version():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "python:3.12.11-slim-bookworm@sha256:" in dockerfile
    assert 'ARG NYANKOFACE_MCP_VERSION=0.1.0' in dockerfile
    assert 'org.opencontainers.image.version="${NYANKOFACE_MCP_VERSION}"' in dockerfile
    assert 'CMD ["nyankoface-mcp-server"]' in dockerfile


def test_compose_shared_state_writers_use_group_writable_umask():
    compose = (ROOT.parent / "docker-compose.yml").read_text(encoding="utf-8")
    assert 'umask 0002 &&' in compose
    assert 'exec nyankoface-mcp-admin-server' in compose
    assert 'umask 0002 && exec nyankoface-mcp-server' in compose
    assert 'cap_drop: ["ALL"]' in compose
    assert 'cap_add: ["CHOWN", "FOWNER"]' in compose
    assert 'nyankoface-mcp-admin-bridge:/run/mcp-admin-bridge' in compose
    assert 'install -D -m 0440 /run/secrets/nyankoface-mcp-admin-internal-token' in compose
    frontend = compose.split("\n  frontend:\n", 1)[1].split("\n  mcp-admin:\n", 1)[0]
    assert "nyankoface-mcp-admin-internal-token" not in frontend


def test_container_runtime_lock_pins_every_dependency():
    lock_lines = [
        line for line in (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    assert lock_lines
    assert all(line.count("==") == 1 for line in lock_lines)
    assert {line.lower().split("==", 1)[0] for line in lock_lines}.issuperset({
        "httpx", "mcp", "uvicorn", "pydantic", "starlette", "certifi",
    })
