#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/deploy-home.sh [--validate-only]

Required runner environment:
  NYANKOFACE_DEPLOY_ENV_FILE   Absolute path to the private Compose .env file
  NYANKOFACE_GATEWAY_CERT_DIR  Absolute path to the private gateway cert directory

Optional runner environment:
  COMPOSE_PROFILES              Compose profiles to include, for example: mcp
  NYANKOFACE_COMPOSE_OVERRIDE_FILE
                                 Optional private Compose override file
  NYANKOFACE_DEPLOY_IGNORE_HEALTH_SERVICES
                                 Comma-separated known health exceptions
  NYANKOFACE_DEPLOY_TIMEOUT_SECONDS
  NYANKOFACE_DEPLOY_SMOKE_BASE_URL
                                 Optional public URL override for post-deploy smoke checks
  NYANKOFACE_DEPLOY_SMOKE_TIMEOUT_SECONDS
                                 Per-request smoke-check timeout (default: 20)
  NYANKOFACE_DEPLOY_SMOKE_INSECURE
                                 Set to 1 only when the smoke target uses an untrusted TLS certificate
EOF
}

die() {
  echo "::error::$*" >&2
  exit 1
}

log() {
  printf '[nyankoface-deploy] %s\n' "$*"
}

is_loopback_origin() {
  local candidate="$1"
  local authority="${candidate#*://}"
  authority="${authority%%/*}"
  local port
  if [[ "$authority" == "localhost" || "$authority" == "127.0.0.1" || "$authority" == "[::1]" ]]; then
    return 0
  fi
  if [[ "$authority" == localhost:* ]]; then
    port="${authority#*:}"
    [[ "$port" =~ ^[0-9]+$ ]] && return 0
  fi
  if [[ "$authority" == 127.0.0.1:* ]]; then
    port="${authority#*:}"
    [[ "$port" =~ ^[0-9]+$ ]] && return 0
  fi
  if [[ "$authority" == "[::1]:"* ]]; then
    port="${authority#*]:}"
    [[ "$port" =~ ^[0-9]+$ ]] && return 0
  fi
  return 1
}

is_ignored_health_service() {
  local service="$1"
  local candidate
  local candidates=()
  IFS=',' read -r -a candidates <<< "${NYANKOFACE_DEPLOY_IGNORE_HEALTH_SERVICES:-}"
  for candidate in "${candidates[@]}"; do
    candidate="${candidate#"${candidate%%[![:space:]]*}"}"
    candidate="${candidate%"${candidate##*[![:space:]]}"}"
    if [[ "$candidate" == "$service" ]]; then
      return 0
    fi
  done
  return 1
}

validate_only=0
case "${1:-}" in
  '') ;;
  --validate-only) validate_only=1 ;;
  --help|-h)
    usage
    exit 0
    ;;
  *)
    usage >&2
    die "unknown argument: $1"
    ;;
esac

if [[ -n "${NYANKOFACE_DEPLOY_REF:-}" && "${NYANKOFACE_DEPLOY_REF}" != "refs/heads/main" ]]; then
  die "refusing to deploy ${NYANKOFACE_DEPLOY_REF}; this workflow is limited to main"
fi

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"

: "${NYANKOFACE_DEPLOY_ENV_FILE:?NYANKOFACE_DEPLOY_ENV_FILE must point to a private .env file}"
: "${NYANKOFACE_GATEWAY_CERT_DIR:?NYANKOFACE_GATEWAY_CERT_DIR must point to a private cert directory}"

[[ "${NYANKOFACE_DEPLOY_ENV_FILE}" = /* ]] || die "NYANKOFACE_DEPLOY_ENV_FILE must be an absolute path"
[[ "${NYANKOFACE_GATEWAY_CERT_DIR}" = /* ]] || die "NYANKOFACE_GATEWAY_CERT_DIR must be an absolute path"

env_parent="$(dirname -- "${NYANKOFACE_DEPLOY_ENV_FILE}")"
[[ -d "$env_parent" ]] || die "the directory containing the private Compose env file does not exist"
[[ -d "${NYANKOFACE_GATEWAY_CERT_DIR}" ]] || die "gateway cert directory does not exist"

env_file="$(cd -- "$env_parent" && pwd -P)/$(basename -- "${NYANKOFACE_DEPLOY_ENV_FILE}")"
cert_dir="$(cd -- "${NYANKOFACE_GATEWAY_CERT_DIR}" && pwd -P)"
env_dir="$(dirname -- "${env_file}")"

[[ -f "$env_file" ]] || die "private Compose env file does not exist"
command -v docker >/dev/null 2>&1 || die "docker is not available to the runner"
docker info >/dev/null 2>&1 || die "the runner cannot access the Docker daemon"

# Compose resolves relative bind mounts from the checkout directory, while a
# private .env file normally keeps paths relative to its own directory. Export
# the known path-valued settings so the existing home configuration keeps
# working when the checkout is recreated by Actions.
dotenv_value() {
  local key="$1"
  awk -v key="$key" '
    /^[[:space:]]*#/ { next }
    {
      line = $0
      sub(/^[[:space:]]*/, "", line)
      sub(/[[:space:]]*\r?$/, "", line)
      if (index(line, key "=") != 1) next
      sub("^" key "=", "", line)
      if (line ~ /^".*"$/) {
        sub(/^"/, "", line)
        sub(/"$/, "", line)
      }
      print line
      exit
    }
  ' "$env_file"
}

normalize_path_setting() {
  local name="$1"
  local default_value="$2"
  local value="${!name:-}"

  if [[ -z "$value" ]]; then
    value="$(dotenv_value "$name")"
  fi
  if [[ -z "$value" ]]; then
    value="$default_value"
  fi
  [[ "$value" != *'${'* ]] || die "$name must not contain an unresolved variable expression"
  if [[ "$value" != /* ]]; then
    value="$env_dir/${value#./}"
  fi
  export "$name=$value"
}

export NYANKOFACE_GATEWAY_CERT_DIR="$cert_dir"
normalize_path_setting ZAI_AGENT_CONFIG ./maintenance-agent/zai.example.env
normalize_path_setting NYANKOFACE_MCP_STATE_DIR ./secrets/nyankoface-mcp
normalize_path_setting NYANKOFACE_MCP_FORGEJO_USER_TOKEN_FILE ./secrets/nyankoface-mcp-forgejo-user-token
normalize_path_setting NYANKOFACE_MCP_ADMIN_INTERNAL_TOKEN_FILE ./secrets/nyankoface-mcp-admin-internal-token

compose=(
  docker compose
  --project-name nyankoface
  --env-file "$env_file"
  --file "$repo_root/docker-compose.yml"
)

override_file="${NYANKOFACE_COMPOSE_OVERRIDE_FILE:-$env_dir/docker-compose.override.yml}"
if [[ "$override_file" != /* ]]; then
  override_file="$env_dir/${override_file#./}"
fi
if [[ -f "$override_file" ]]; then
  compose+=(--file "$override_file")
  private_override_enabled=1
elif [[ -n "${NYANKOFACE_COMPOSE_OVERRIDE_FILE:-}" ]]; then
  die "NYANKOFACE_COMPOSE_OVERRIDE_FILE does not exist"
else
  private_override_enabled=0
fi

show_status() {
  timeout --signal=KILL 10s "${compose[@]}" ps -a || true
}

smoke_tmp_dir=""
cleanup() {
  local exit_code=$?
  if [[ -n "$smoke_tmp_dir" && -d "$smoke_tmp_dir" ]]; then
    rm -rf -- "$smoke_tmp_dir"
  fi
  show_status
  exit "$exit_code"
}

trap cleanup EXIT

actual_sha="$(git -C "$repo_root" rev-parse HEAD)"
if [[ -n "${NYANKOFACE_DEPLOY_SHA:-}" && "${NYANKOFACE_DEPLOY_SHA}" != "$actual_sha" ]]; then
  die "checked out revision $actual_sha does not match the requested deployment revision"
fi

log "repository: NyankoFace"
log "revision: $actual_sha"
log "compose project: nyankoface"
if (( private_override_enabled )); then
  log "private Compose override: enabled"
fi
log "validating Docker Compose configuration"
"${compose[@]}" config --quiet

services_output="$("${compose[@]}" config --services)"
expected_services=()
while IFS= read -r service; do
  [[ -n "$service" ]] && expected_services+=("$service")
done <<< "$services_output"
((${#expected_services[@]} > 0)) || die "Docker Compose did not produce any services"

if (( validate_only )); then
  log "validation completed; deployment was not started"
  exit 0
fi

timeout_seconds="${NYANKOFACE_DEPLOY_TIMEOUT_SECONDS:-600}"
[[ "$timeout_seconds" =~ ^[0-9]+$ ]] || die "NYANKOFACE_DEPLOY_TIMEOUT_SECONDS must be an integer"

log "building and starting NyankoFace"
"${compose[@]}" up -d --build

log "waiting for configured services to become ready"
started_at="$SECONDS"
while :; do
  snapshot="$("${compose[@]}" ps -a --format '{{.Service}}|{{.State}}|{{.Health}}|{{.ExitCode}}')"
  declare -A found_services=()
  pending=0

  while IFS='|' read -r service state health exit_code; do
    [[ -n "$service" ]] || continue
    found_services["$service"]=1
    case "$state" in
      running)
        if [[ "$health" == "starting" || "$health" == "unhealthy" ]] && ! is_ignored_health_service "$service"; then
          pending=1
        fi
        ;;
      exited)
        if [[ "$service" == "seed" && "$exit_code" == "0" ]]; then
          :
        elif [[ "$exit_code" == "0" ]]; then
          die "service $service exited unexpectedly"
        else
          die "service $service exited with code ${exit_code:-unknown}"
        fi
        ;;
      restarting|created|paused)
        pending=1
        ;;
      dead)
        die "service $service is dead"
        ;;
      *)
        pending=1
        ;;
    esac
  done <<< "$snapshot"

  for service in "${expected_services[@]}"; do
    if [[ -z "${found_services[$service]+present}" ]]; then
      pending=1
    fi
  done

  if (( pending == 0 )); then
    log "all configured services are ready"
    break
  fi

  if (( SECONDS - started_at >= timeout_seconds )); then
    die "timed out waiting for NyankoFace services"
  fi
  sleep 5
done

run_public_smoke_test() {
  command -v curl >/dev/null 2>&1 || die "curl is required for the public deployment smoke test"

  local base_url="${NYANKOFACE_DEPLOY_SMOKE_BASE_URL:-}"
  if [[ -z "$base_url" ]]; then
    base_url="$(dotenv_value PUBLIC_BASE_URL)"
  fi
  [[ -n "$base_url" ]] || die "PUBLIC_BASE_URL or NYANKOFACE_DEPLOY_SMOKE_BASE_URL is required for the public smoke test"
  base_url="${base_url%/}"
  [[ "$base_url" == https://* || "$base_url" == http://* ]] || die "public smoke base URL must be HTTP(S)"

  local smoke_timeout="${NYANKOFACE_DEPLOY_SMOKE_TIMEOUT_SECONDS:-20}"
  [[ "$smoke_timeout" =~ ^[0-9]+$ && "$smoke_timeout" -gt 0 ]] || die "NYANKOFACE_DEPLOY_SMOKE_TIMEOUT_SECONDS must be a positive integer"

  smoke_tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/nyankoface-smoke.XXXXXX")"
  local curl_options=(--silent --show-error --max-time "$smoke_timeout" --retry 0)
  if [[ "${NYANKOFACE_DEPLOY_SMOKE_INSECURE:-0}" == "1" ]]; then
    curl_options+=(--insecure)
  fi

  local request_number=0
  local status headers body curl_error
  smoke_request() {
    local route="$1"
    request_number=$((request_number + 1))
    headers="$smoke_tmp_dir/headers-$request_number"
    body="$smoke_tmp_dir/body-$request_number"
    curl_error="$smoke_tmp_dir/error-$request_number"
    if ! status="$(curl "${curl_options[@]}" --dump-header "$headers" --output "$body" --write-out '%{http_code}' "$base_url$route" 2>"$curl_error")"; then
      die "public smoke request failed for $route"
    fi
  }

  smoke_request_authenticated() {
    local route="$1"
    local payload="$2"
    local bearer_token="$3"
    local protocol_version="${4:-}"
    local curl_config
    request_number=$((request_number + 1))
    headers="$smoke_tmp_dir/headers-$request_number"
    body="$smoke_tmp_dir/body-$request_number"
    curl_error="$smoke_tmp_dir/error-$request_number"
    curl_config="$(printf 'header = "Authorization: Bearer %s"' "$bearer_token")"
    if [[ -n "$protocol_version" ]]; then
      curl_config+=$'\n'
      curl_config+="header = \"MCP-Protocol-Version: ${protocol_version}\""
    fi
    if ! status="$(printf '%s\n' "$curl_config" | curl "${curl_options[@]}" \
      --config - \
      --header 'Accept: application/json, text/event-stream' \
      --header 'Content-Type: application/json' \
      --data "$payload" \
      --dump-header "$headers" --output "$body" --write-out '%{http_code}' \
      "$base_url$route" 2>"$curl_error")"; then
      die "authenticated public smoke request failed for $route"
    fi
  }

  log "checking public deployment at $base_url"

  smoke_request "/"
  [[ "$status" == "200" ]] || die "public smoke check: portal returned HTTP $status"
  grep -Fqi "NyankoFace" "$body" || die "public smoke check: portal identity is missing"
  grep -Eqi "SimpleHTTP|TIDELINE" "$body" && die "public smoke check: unexpected static server identity"

  smoke_request "/git/api/v1/version"
  [[ "$status" == "200" ]] || die "public smoke check: Forgejo API returned HTTP $status"
  grep -Eqi '^content-type:[[:space:]]*application/json' "$headers" || die "public smoke check: Forgejo API did not return JSON"
  grep -Eqi '"version"[[:space:]]*:' "$body" || die "public smoke check: Forgejo version payload is missing"

  smoke_request "/api/catalog/repositories?limit=1"
  [[ "$status" == "200" ]] || die "public smoke check: catalog API returned HTTP $status"
  grep -Eqi '^content-type:[[:space:]]*application/json' "$headers" || die "public smoke check: catalog API did not return JSON"
  grep -Eqi '"(ok|data|total_count)"[[:space:]]*:' "$body" || die "public smoke check: catalog payload is missing"

  local mcp_enabled=0
  for service in "${expected_services[@]}"; do
    if [[ "$service" == "nyankoface-mcp" ]]; then
      mcp_enabled=1
      break
    fi
  done
  if (( mcp_enabled )); then
    if [[ "$base_url" == http://* ]] && ! is_loopback_origin "$base_url"; then
      die "MCP public smoke requires HTTPS before forwarding the bearer token"
    fi
  smoke_request "/mcp"
    [[ "$status" == "401" ]] || die "public smoke check: MCP endpoint returned HTTP $status without credentials"
    grep -Eqi '^www-authenticate:.*resource_metadata=' "$headers" || die "public smoke check: MCP challenge has no resource metadata"
    grep -Fqi "resource_metadata=\"${base_url}/.well-known/oauth-protected-resource/mcp\"" "$headers" || die "public smoke check: MCP metadata origin does not match the public URL"

    local mcp_token_file="${NYANKOFACE_DEPLOY_MCP_TOKEN_FILE:-${NYANKOFACE_MCP_FORGEJO_USER_TOKEN_FILE:-}}"
    [[ -n "$mcp_token_file" && -f "$mcp_token_file" ]] || die "MCP public smoke requires NYANKOFACE_DEPLOY_MCP_TOKEN_FILE or NYANKOFACE_MCP_FORGEJO_USER_TOKEN_FILE"
    local mcp_token
    mcp_token="$(<"$mcp_token_file")"
    [[ -n "$mcp_token" && "$mcp_token" != *$'\r'* && "$mcp_token" != *$'\n'* && "$mcp_token" != *'"'* && "$mcp_token" != *$'\\'* ]] || die "MCP smoke token file is empty or contains unsupported characters"

    smoke_request_authenticated "/mcp" '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"nyankoface-deploy-smoke","version":"1.0"}}}' "$mcp_token"
    [[ "$status" == "200" ]] || die "public smoke check: authenticated MCP initialize returned HTTP $status"
    grep -Eqi '"result"[[:space:]]*:' "$body" || die "public smoke check: MCP initialize result is missing"
    grep -Eqi '"serverInfo"[[:space:]]*:' "$body" || die "public smoke check: MCP initialize server info is missing"
    local mcp_protocol_version
    mcp_protocol_version="$(tr -d '\r\n' < "$body" | sed -nE 's/.*"protocolVersion"[[:space:]]*:[[:space:]]*"([^"\\]+)".*/\1/p')"
    [[ "$mcp_protocol_version" =~ ^[A-Za-z0-9._-]+$ ]] || die "public smoke check: MCP initialize did not return a valid protocol version"

    smoke_request_authenticated "/mcp" '{"jsonrpc":"2.0","method":"notifications/initialized"}' "$mcp_token" "$mcp_protocol_version"
    [[ "$status" == "202" ]] || die "public smoke check: MCP initialized notification returned HTTP $status"

    smoke_request_authenticated "/mcp" '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' "$mcp_token" "$mcp_protocol_version"
    [[ "$status" == "200" ]] || die "public smoke check: authenticated MCP tools/list returned HTTP $status"
    grep -Eqi '"tools"[[:space:]]*:' "$body" || die "public smoke check: MCP tools/list result is missing"

    smoke_request_authenticated "/mcp" '{"jsonrpc":"2.0","id":3,"method":"resources/list","params":{}}' "$mcp_token" "$mcp_protocol_version"
    [[ "$status" == "200" ]] || die "public smoke check: authenticated MCP resources/list returned HTTP $status"
    grep -Eqi '"resources"[[:space:]]*:' "$body" || die "public smoke check: MCP resources/list result is missing"
  fi

  log "public deployment smoke test passed"
}

run_public_smoke_test
