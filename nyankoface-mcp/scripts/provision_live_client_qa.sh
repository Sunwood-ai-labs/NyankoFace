#!/usr/bin/env bash
# Provision short-lived, least-privilege credentials for manual live-client QA.
#
# This script intentionally writes plaintext credentials only to root-owned files
# outside Git and never prints them. Its stdout is a secret-free JSON summary.

set -euo pipefail
umask 077

: "${NYANKOFACE_MCP_IMAGE:=nyankoface-nyankoface-mcp}"
: "${NYANKOFACE_MCP_REGISTRY_DIR:=/opt/nyankoface/secrets/nyankoface-mcp}"
: "${NYANKOFACE_MCP_QA_SECRET_DIR:=/opt/nyankoface/secrets/nyankoface-mcp-live-qa}"
: "${NYANKOFACE_MCP_FORGEJO_USER_ID:?set NYANKOFACE_MCP_FORGEJO_USER_ID}"
: "${NYANKOFACE_MCP_FORGEJO_TOKEN_FILE:=/run/secrets/nyankoface-mcp-forgejo-user-token}"
: "${NYANKOFACE_MCP_REPOSITORY:=nyankoface/sample-model}"
: "${NYANKOFACE_MCP_REGISTRY_READER_GID:=10001}"

registry="${NYANKOFACE_MCP_REGISTRY_DIR}/registry.json"
audit="${NYANKOFACE_MCP_REGISTRY_DIR}/lifecycle-audit.jsonl"
actor="user:live-client-qa"
now="$(date +%s)"

install -d -m 0750 "${NYANKOFACE_MCP_REGISTRY_DIR}"
install -d -m 0700 "${NYANKOFACE_MCP_QA_SECRET_DIR}"
chgrp "${NYANKOFACE_MCP_REGISTRY_READER_GID}" "${NYANKOFACE_MCP_REGISTRY_DIR}"
chmod 0750 "${NYANKOFACE_MCP_REGISTRY_DIR}"

admin() {
  docker run --rm \
    --user 0:0 \
    -e NYANKOFACE_MCP_REGISTRY_READER_GID="${NYANKOFACE_MCP_REGISTRY_READER_GID}" \
    -v "${NYANKOFACE_MCP_REGISTRY_DIR}:/state" \
    "${NYANKOFACE_MCP_IMAGE}" \
    python -m nyankoface_mcp.admin \
    --registry /state/registry.json \
    --audit /state/lifecycle-audit.jsonl \
    --actor "${actor}" \
    --reauthenticated-at "${now}" \
    "$@"
}

subject_exists() {
  local subject_id="$1"
  [[ -e "${registry}" ]] || return 1
  python3 - "${registry}" "${subject_id}" <<'PY'
import json
import sys
from pathlib import Path

registry_path = Path(sys.argv[1])
subject_id = sys.argv[2]
payload = json.loads(registry_path.read_text(encoding="utf-8"))
raise SystemExit(0 if any(
    item.get("subject_id") == subject_id for item in payload.get("subjects", [])
) else 1)
PY
}

extract_issued_token() {
  local raw_json="$1"
  local token_file="$2"
  local metadata_file="$3"
  python3 - "${raw_json}" "${token_file}" "${metadata_file}" <<'PY'
import json
import os
import sys
from pathlib import Path

raw_path, token_path, metadata_path = map(Path, sys.argv[1:])
payload = json.loads(raw_path.read_text(encoding="utf-8"))
token = payload.pop("token")
token_path.write_text(token, encoding="utf-8")
os.chmod(token_path, 0o600)
metadata_path.write_text(
    json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
os.chmod(metadata_path, 0o600)
raw_path.unlink()
PY
}

issue_token() {
  local subject="$1"
  local client_id="$2"
  local variant="$3"
  local ttl="$4"
  shift 4
  local raw_json
  raw_json="$(mktemp "${NYANKOFACE_MCP_QA_SECRET_DIR}/.${client_id}-${variant}.XXXXXX")"
  admin issue-token "${subject}" \
    --client-id "${client_id}-${variant}" \
    --repository "${NYANKOFACE_MCP_REPOSITORY}" \
    --ttl-seconds "${ttl}" \
    "$@" >"${raw_json}"
  extract_issued_token \
    "${raw_json}" \
    "${NYANKOFACE_MCP_QA_SECRET_DIR}/${client_id}-${variant}.token" \
    "${NYANKOFACE_MCP_QA_SECRET_DIR}/${client_id}-${variant}.json"
}

for client in codex claude-desktop vscode; do
  subject="service:${client}-live"
  account_command="create-service-account"
  if subject_exists "${subject}"; then
    # A rerun refreshes the known QA mapping and revokes credentials from the
    # previous run before replacing its root-only files.
    account_command="remap-service-account"
  fi
  admin "${account_command}" "${subject}" \
    --forgejo-user-id "${NYANKOFACE_MCP_FORGEJO_USER_ID}" \
    --forgejo-token-file "${NYANKOFACE_MCP_FORGEJO_TOKEN_FILE}" \
    --allowed-scope catalog:read \
    --allowed-scope repos:read \
    --repository-permission "${NYANKOFACE_MCP_REPOSITORY}=read" >/dev/null

  issue_token "${subject}" "${client}" valid 7200 \
    --scope catalog:read --scope repos:read
  # search_catalog is explicitly allowed by the QA governance policy. Giving
  # this variant only repos:read lets the check reach scope authorization and
  # deterministically prove the missing catalog:read denial.
  issue_token "${subject}" "${client}" scope 7200 \
    --scope repos:read
  issue_token "${subject}" "${client}" expired 1 \
    --scope catalog:read --scope repos:read
  issue_token "${subject}" "${client}" revoked 7200 \
    --scope catalog:read --scope repos:read

  revoked_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["token_id"])' \
    "${NYANKOFACE_MCP_QA_SECRET_DIR}/${client}-revoked.json")"
  admin revoke-token "${revoked_id}" >/dev/null

  python3 - "${NYANKOFACE_MCP_QA_SECRET_DIR}/${client}-invalid.token" <<'PY'
import os
import secrets
import sys
from pathlib import Path

path = Path(sys.argv[1])
path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
os.chmod(path, 0o600)
PY
done

# Make the one-second credentials deterministically expired before consumers run.
sleep 2

python3 - "${NYANKOFACE_MCP_QA_SECRET_DIR}" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
clients = ("codex", "claude-desktop", "vscode")
states = ("valid", "scope", "expired", "revoked", "invalid")
summary = {
    "clients": list(clients),
    "states": list(states),
    "credential_files": sum((root / f"{client}-{state}.token").is_file()
                            for client in clients for state in states),
    "secrets_printed": False,
}
print(json.dumps(summary, separators=(",", ":"), sort_keys=True))
PY
