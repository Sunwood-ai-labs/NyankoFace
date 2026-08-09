import hashlib
import json
import time
from pathlib import Path

import pytest

from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.auth.provider import AccessToken

from nyankoface_mcp.auth import NyankoFaceTokenVerifier, TokenRecord
from nyankoface_mcp.lifecycle import DECLARED_SCOPES


async def resolve_user_42(_token: str) -> int:
    if _token not in {"caller-pat", "forgejo-pat-used-as-the-single-mcp-credential"}:
        raise ToolError("invalid Forgejo token")
    return 42


@pytest.mark.asyncio
async def test_forgejo_token_is_accepted_directly_and_keeps_registry_empty(tmp_path, monkeypatch):
    token = "forgejo-pat-used-as-the-single-mcp-credential"
    verifier = NyankoFaceTokenVerifier(tmp_path / "missing-registry.json", resolve_user_42)

    access = await verifier.verify_token(token)

    assert access is not None
    assert access.client_id == "forgejo-user:42"
    assert set(access.scopes) == set(DECLARED_SCOPES)
    assert verifier.records() == []
    monkeypatch.setattr("nyankoface_mcp.auth.get_access_token", lambda: access)
    record = verifier.current_record()
    assert verifier.upstream_token(record) == token
    assert verifier.require("issues:write", "nyankoface", "demo") == record
    assert not (tmp_path / "missing-registry.json").exists()


@pytest.mark.asyncio
async def test_invalid_direct_forgejo_token_is_rejected(tmp_path):
    async def reject(_token: str) -> int:
        raise ToolError("invalid Forgejo token")

    verifier = NyankoFaceTokenVerifier(tmp_path / "missing-registry.json", reject)

    assert await verifier.verify_token("invalid-forgejo-pat") is None


@pytest.mark.asyncio
async def test_verifies_hashed_token_and_rejects_expired(tmp_path):
    token_file = tmp_path / "tokens.json"
    token_file.write_text(json.dumps({"version": 2, "subjects": [{
        "subject_id": "service:codex",
        "subject_type": "service_account",
        "enabled": True,
        "forgejo_user_id": 42,
        "forgejo_token_file": str(tmp_path / "forgejo-token"),
        "allowed_scopes": ["catalog:read"],
        "repository_permissions": {"nyankoface/demo": "read"},
        "mapping_version": 1,
    }], "tokens": [
        {
            "token_sha256": hashlib.sha256(b"valid").hexdigest(),
            "token_id": "valid-id",
            "client_id": "codex",
            "subject_id": "service:codex",
            "subject_type": "service_account",
            "audience": "nyankoface-api-v1",
            "scopes": ["catalog:read"],
            "repositories": ["nyankoface/demo"],
            "mapping_version": 1,
            "expires_at": int(time.time()) + 60,
            "revoked_at": None,
        },
        {
            "token_sha256": hashlib.sha256(b"expired").hexdigest(),
            "token_id": "expired-id",
            "client_id": "old",
            "subject_id": "service:codex",
            "audience": "nyankoface-api-v1",
            "scopes": ["catalog:read"],
            "repositories": ["nyankoface/demo"],
            "mapping_version": 1,
            "expires_at": int(time.time()) - 1,
            "revoked_at": None,
        },
        {
            "token_sha256": hashlib.sha256(b"epoch-expired").hexdigest(),
            "token_id": "epoch-id",
            "client_id": "epoch",
            "subject_id": "service:codex",
            "audience": "nyankoface-api-v1",
            "scopes": ["catalog:read"],
            "repositories": ["nyankoface/demo"],
            "mapping_version": 1,
            "expires_at": 0,
            "revoked_at": None,
        },
    ]}), encoding="utf-8")
    (tmp_path / "forgejo-token").write_text("caller-pat", encoding="utf-8")
    verifier = NyankoFaceTokenVerifier(token_file, resolve_user_42)

    access = await verifier.verify_token("valid")
    assert access is not None
    assert access.client_id == "codex"
    assert access.scopes == ["catalog:read"]
    assert await verifier.verify_token("expired") is None
    assert await verifier.verify_token("epoch-expired") is None
    assert await verifier.verify_token("unknown") is None


def test_missing_or_invalid_token_file_fails_closed(tmp_path):
    missing = NyankoFaceTokenVerifier(tmp_path / "missing.json", resolve_user_42)
    assert missing.records() == []
    invalid_file = tmp_path / "invalid.json"
    invalid_file.write_text("not json", encoding="utf-8")
    assert NyankoFaceTokenVerifier(invalid_file, resolve_user_42).records() == []
    invalid_file.write_bytes(b"\xff")
    verifier = NyankoFaceTokenVerifier(invalid_file, resolve_user_42)
    assert verifier.records() == []
    assert verifier.find("opaque-token") is None
    invalid_file.write_text('{"version":2,"subjects":[],"tokens":["bad"]}', encoding="utf-8")
    assert NyankoFaceTokenVerifier(invalid_file, resolve_user_42).find("opaque-token") is None


@pytest.mark.parametrize("invalid_expiry", ["4102444800", 1e999, True, -1])
def test_records_reject_non_integer_or_out_of_range_expiry(tmp_path, invalid_expiry):
    token_file = tmp_path / "tokens.json"
    token_file.write_text(json.dumps({"version": 2, "subjects": [{
        "subject_id": "service:codex", "forgejo_user_id": 42,
    }], "tokens": [{
        "token_sha256": "0" * 64, "subject_id": "service:codex",
        "scopes": ["repos:read"], "expires_at": invalid_expiry,
    }]}), encoding="utf-8")
    assert NyankoFaceTokenVerifier(token_file, resolve_user_42).records() == []


def test_committed_registry_and_compose_mount_caller_secrets():
    service_root = Path(__file__).resolve().parents[1]
    repository_root = service_root.parent
    example = json.loads((service_root / "registry.example.json").read_text(encoding="utf-8"))
    record = example["tokens"][0]
    subject = example["subjects"][0]
    assert subject["forgejo_token_file"] == "/run/secrets/nyankoface-mcp-forgejo-user-token"
    assert "repos:read" in record["scopes"]
    assert set(record["scopes"]) <= set(subject["allowed_scopes"])

    compose = (repository_root / "docker-compose.yml").read_text(encoding="utf-8")
    assert "NYANKOFACE_MCP_FORGEJO_USER_TOKEN_FILE" in compose
    assert compose.count("nyankoface-mcp-forgejo-user-token") >= 3
    assert "NYANKOFACE_MCP_STATE_DIR" in compose
    assert ":/run/nyankoface-mcp:ro" in compose
    assert "nyankoface-mcp-tokens:" not in compose


def test_invalid_utf8_upstream_pat_fails_closed(tmp_path):
    pat_file = tmp_path / "forgejo-token"
    pat_file.write_bytes(b"\xff")
    verifier = NyankoFaceTokenVerifier(tmp_path / "registry.json", resolve_user_42)
    record = TokenRecord("0" * 64, "qa", ("repos:read",), forgejo_token_file=str(pat_file))
    assert verifier.upstream_token(record) is None


def test_repository_constraint_and_mapped_permission_fail_closed(tmp_path, monkeypatch):
    verifier = NyankoFaceTokenVerifier(tmp_path / "registry.json", resolve_user_42)
    record = TokenRecord(
        token_sha256="0" * 64,
        client_id="qa",
        scopes=("repos:read", "issues:write"),
        repositories=("nyankoface/demo",),
        repository_permissions=(("nyankoface/demo", "read"),),
    )
    monkeypatch.setattr(verifier, "current_record", lambda: record)
    assert verifier.require("repos:read", "nyankoface", "demo") is record
    with pytest.raises(ToolError, match="not found or is not authorized"):
        verifier.require("repos:read", "nyankoface", "other")
    with pytest.raises(ToolError, match="insufficient"):
        verifier.require("issues:write", "nyankoface", "demo")


@pytest.mark.asyncio
async def test_pat_owner_must_match_mapped_forgejo_user(tmp_path):
    token_file = tmp_path / "tokens.json"
    pat_file = tmp_path / "forgejo-token"
    pat_file.write_text("other-user-pat", encoding="utf-8")
    token_file.write_text(json.dumps({"version": 2, "subjects": [{
        "subject_id": "service:codex",
        "subject_type": "service_account",
        "enabled": True,
        "forgejo_user_id": 42,
        "forgejo_token_file": str(pat_file),
        "allowed_scopes": ["repos:read"],
        "repository_permissions": {"nyankoface/demo": "read"},
        "mapping_version": 1,
    }], "tokens": [{
        "token_sha256": hashlib.sha256(b"valid").hexdigest(),
        "token_id": "valid-id",
        "client_id": "codex",
        "subject_id": "service:codex",
        "subject_type": "service_account",
        "audience": "nyankoface-api-v1",
        "scopes": ["repos:read"],
        "repositories": ["nyankoface/demo"],
        "mapping_version": 1,
        "expires_at": int(time.time()) + 60,
        "revoked_at": None,
    }]}), encoding="utf-8")

    async def resolve_other_user(_token: str) -> int:
        return 7

    verifier = NyankoFaceTokenVerifier(token_file, resolve_other_user)
    assert await verifier.verify_token("valid") is None


@pytest.mark.asyncio
async def test_token_without_explicit_audience_fails_closed(tmp_path):
    token_file = tmp_path / "tokens.json"
    pat_file = tmp_path / "forgejo-token"
    pat_file.write_text("caller-pat", encoding="utf-8")
    token_file.write_text(json.dumps({"version": 2, "subjects": [{
        "subject_id": "service:codex", "subject_type": "service_account",
        "enabled": True, "forgejo_user_id": 42, "forgejo_token_file": str(pat_file),
        "allowed_scopes": ["repos:read"],
        "repository_permissions": {"nyankoface/demo": "read"}, "mapping_version": 1,
    }], "tokens": [{
        "token_sha256": hashlib.sha256(b"valid").hexdigest(), "token_id": "valid-id",
        "client_id": "codex", "subject_id": "service:codex",
        "subject_type": "service_account", "scopes": ["repos:read"],
        "repositories": ["nyankoface/demo"], "mapping_version": 1,
        "expires_at": int(time.time()) + 60, "revoked_at": None,
    }]}), encoding="utf-8")

    verifier = NyankoFaceTokenVerifier(token_file, resolve_user_42)
    assert await verifier.verify_token("valid") is None
