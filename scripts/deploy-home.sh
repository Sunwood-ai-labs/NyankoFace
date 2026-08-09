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
EOF
}

die() {
  echo "::error::$*" >&2
  exit 1
}

log() {
  printf '[nyankoface-deploy] %s\n' "$*"
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
  "${compose[@]}" ps -a || true
}

trap show_status EXIT

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
    exit 0
  fi

  if (( SECONDS - started_at >= timeout_seconds )); then
    die "timed out waiting for NyankoFace services"
  fi
  sleep 5
done
