#!/bin/bash
# Keep this file LF-only; it is executed directly inside the Linux seed image.
# ==============================================================================
# NyankoFace seed script
#
# 1. Waits for the Forgejo healthcheck endpoint.
# 2. Idempotently bootstraps the first admin user (via `docker exec` into the
#    Forgejo container, since there is no other-user API path to create the
#    very first account once INSTALL_LOCK is set).
# 3. Generates an API access token for that admin and writes it to the shared
#    volume at /shared/token (contract: FORGEJO_TOKEN_FILE=/shared/token).
# 4. Uses the REST API to create the `nyankoface` org, seed model/dataset
#    examples, and mirror a vetted set of public CPU-only Hugging Face Spaces.
#
# The whole script is safe to re-run: every step checks for the resource's
# existence first and skips creation if it is already there.
# ==============================================================================
set -uo pipefail

FORGEJO_API="${FORGEJO_API:-http://forgejo:3000/api/v1}"
FORGEJO_TOKEN_FILE="${FORGEJO_TOKEN_FILE:-/shared/token}"
FORGEJO_CONTAINER_NAME="${FORGEJO_CONTAINER_NAME:-nyankoface-forgejo}"
SPACES_RUNNER_API="${SPACES_RUNNER_API:-http://spaces-runner:8000}"

NYANKOFACE_ADMIN_USER="${NYANKOFACE_ADMIN_USER:-nyankoface-admin}"
NYANKOFACE_ADMIN_PASSWORD="${NYANKOFACE_ADMIN_PASSWORD:-nyankoface1234}"
NYANKOFACE_ADMIN_EMAIL="${NYANKOFACE_ADMIN_EMAIL:-admin@example.com}"
MAINTENANCE_TOKEN_FILE="${MAINTENANCE_TOKEN_FILE:-/shared/maintenance-token}"
MAINTENANCE_AGENT_TOKEN_DIR="${MAINTENANCE_AGENT_TOKEN_DIR:-/shared/agent-tokens}"
MAINTENANCE_WEBHOOK_SECRET_FILE="${MAINTENANCE_WEBHOOK_SECRET_FILE:-/shared/maintenance-webhook-secret}"
MAINTENANCE_WEBHOOK_URL="${MAINTENANCE_WEBHOOK_URL:-http://maintenance-agent:8010/webhooks/forgejo}"

ORG_NAME="nyankoface"
SPACE_ORG_NAME="${SPACE_ORG_NAME:-seraphim-labs}"
SUNWOOD_CATALOG="${SUNWOOD_CATALOG:-/catalog/sunwood-ai-labs.json}"
PROMPT_CATALOG="${PROMPT_CATALOG:-/catalog/prompts.json}"
BENCHMARK_CATALOG="${BENCHMARK_CATALOG:-/catalog/benchmarks.json}"

log() { echo "[seed] $*"; }

# ------------------------------------------------------------------------
# 0. Wait for Forgejo to become healthy.
# ------------------------------------------------------------------------
log "Waiting for Forgejo at ${FORGEJO_API%/api/v1}/api/healthz ..."
until curl -sf "http://forgejo:3000/api/healthz" >/dev/null 2>&1; do
  sleep 2
done
log "Forgejo is up."

# ------------------------------------------------------------------------
# Helper: test whether an existing token file is still valid.
# ------------------------------------------------------------------------
token_is_valid() {
  local tok="$1"
  [ -n "$tok" ] || return 1
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: token ${tok}" \
    "${FORGEJO_API}/user")
  [ "$code" = "200" ]
}

TOKEN=""
if [ -f "$FORGEJO_TOKEN_FILE" ]; then
  EXISTING_TOKEN="$(cat "$FORGEJO_TOKEN_FILE" 2>/dev/null || true)"
  if token_is_valid "$EXISTING_TOKEN"; then
    log "Existing token at ${FORGEJO_TOKEN_FILE} is valid; reusing it."
    TOKEN="$EXISTING_TOKEN"
  else
    log "Existing token file present but invalid/stale; regenerating."
  fi
fi

# ------------------------------------------------------------------------
# 1. Create the admin user (idempotent) via `docker exec` into the Forgejo
#    container, running Forgejo's own CLI as the `git` user.
# ------------------------------------------------------------------------
if [ -z "$TOKEN" ]; then
  log "Ensuring admin user '${NYANKOFACE_ADMIN_USER}' exists..."
  if docker exec -u git "${FORGEJO_CONTAINER_NAME}" \
      forgejo admin user create \
        --admin \
        --username "${NYANKOFACE_ADMIN_USER}" \
        --password "${NYANKOFACE_ADMIN_PASSWORD}" \
        --email "${NYANKOFACE_ADMIN_EMAIL}" \
        --must-change-password=false 2>&1 | tee /tmp/admin_create.log; then
    log "Admin user created (or command succeeded)."
  else
    if grep -qi "already exists" /tmp/admin_create.log; then
      log "Admin user already exists; continuing."
    else
      log "WARNING: admin user create returned non-zero; it may already exist. Continuing."
    fi
  fi

  # ----------------------------------------------------------------------
  # 2. Generate an API token for the admin and persist it to the shared
  #    volume.
  # ----------------------------------------------------------------------
  log "Generating API access token for '${NYANKOFACE_ADMIN_USER}'..."
  TOKEN_NAME="nyankoface-seed-$(date +%s)"
  RAW_TOKEN_OUTPUT="$(docker exec -u git "${FORGEJO_CONTAINER_NAME}" \
    forgejo admin user generate-access-token \
      --username "${NYANKOFACE_ADMIN_USER}" \
      --token-name "${TOKEN_NAME}" \
      --scopes all \
      --raw 2>/tmp/token_gen.log)"

  if [ -z "$RAW_TOKEN_OUTPUT" ]; then
    log "ERROR: failed to generate access token."
    cat /tmp/token_gen.log
    exit 1
  fi

  # generate-access-token --raw prints just the token, but guard against
  # any stray leading/trailing whitespace or newlines.
  TOKEN="$(echo "$RAW_TOKEN_OUTPUT" | tail -n1 | tr -d '[:space:]')"

  echo -n "$TOKEN" > "$FORGEJO_TOKEN_FILE"
  chmod 644 "$FORGEJO_TOKEN_FILE"
  log "Token written to ${FORGEJO_TOKEN_FILE}."
fi

if ! token_is_valid "$TOKEN"; then
  log "ERROR: token still invalid after generation, aborting."
  exit 1
fi

AUTH_HEADER="Authorization: token ${TOKEN}"

# ------------------------------------------------------------------------
# Pipeline control-plane registration. The runner tracks registered
# repositories in its persistent audit database, so seeded workflows are
# reconciled without requiring a user to open the Pipeline page first.
# ------------------------------------------------------------------------
register_pipeline_repository() {
  local owner="$1"
  local repo="$2"
  local response_file="/tmp/pipeline_install_${owner}_${repo}.json"
  local attempt
  local code

  for attempt in $(seq 1 30); do
    code="$(curl -s -o "${response_file}" -w '%{http_code}' \
      -X POST \
      -H "Authorization: Bearer ${TOKEN}" \
      "${SPACES_RUNNER_API}/api/v1/pipelines/${owner}/${repo}/install" \
      || true)"
    if [ "$code" = "200" ] || [ "$code" = "201" ]; then
      log "Registered ${owner}/${repo} with the Pipeline control plane."
      rm -f "${response_file}"
      return 0
    fi
    sleep 2
  done

  log "ERROR: failed to register ${owner}/${repo} with the Pipeline control plane (HTTP ${code:-000})."
  if [ -s "${response_file}" ]; then
    cat "${response_file}"
  fi
  exit 1
}

# ------------------------------------------------------------------------
# Forgejo Actions runner registration. The runner is organization-scoped so
# only repositories under `nyankoface` can receive this local CI capacity.
# The registration token is shared only with the dedicated runner container.
# ------------------------------------------------------------------------
ensure_actions_runner_token() {
  local runner_token_file="/shared/actions-runner-token"
  if [ -s "$runner_token_file" ]; then
    log "Forgejo Actions runner token already exists; reusing it."
    return 0
  fi

  local runner_token
  runner_token="$(docker exec -u git "${FORGEJO_CONTAINER_NAME}" \
    forgejo forgejo-cli actions generate-runner-token --scope "${ORG_NAME}" 2>/tmp/actions_runner_token.log | tail -n1 | tr -d '[:space:]')"
  if [ -z "$runner_token" ]; then
    log "ERROR: failed to generate Forgejo Actions runner token."
    cat /tmp/actions_runner_token.log
    exit 1
  fi

  echo -n "$runner_token" > "$runner_token_file"
  chmod 600 "$runner_token_file"
  log "Forgejo Actions runner token written to ${runner_token_file}."
}

# ------------------------------------------------------------------------
# Dedicated credentials for the GLM maintenance bot. The bot is an
# organization member rather than an administrator, and its token is kept in
# the shared secret volume instead of Compose environment or repository files.
# ------------------------------------------------------------------------
ensure_maintenance_token() {
  if [ -s "$MAINTENANCE_TOKEN_FILE" ]; then
    local existing
    existing="$(cat "$MAINTENANCE_TOKEN_FILE" 2>/dev/null || true)"
    local code
    code=$(curl -s -o /dev/null -w '%{http_code}' \
      -H "Authorization: token ${existing}" "${FORGEJO_API}/user")
    if [ "$code" = "200" ]; then
      chmod 600 "$MAINTENANCE_TOKEN_FILE"
      log "GLM maintenance token already exists; reusing it."
      return 0
    fi
  fi

  local raw
  raw="$(docker exec -u git "${FORGEJO_CONTAINER_NAME}" \
    forgejo admin user generate-access-token \
      --username "glm-maintainer" \
      --token-name "nyankoface-glm-maintainer-$(date +%s)" \
      --scopes all \
      --raw 2>/tmp/maintenance_token.log | tail -n1 | tr -d '[:space:]')"
  if [ -z "$raw" ]; then
    log "ERROR: failed to generate GLM maintenance token."
    cat /tmp/maintenance_token.log
    exit 1
  fi
  echo -n "$raw" > "$MAINTENANCE_TOKEN_FILE"
  chmod 600 "$MAINTENANCE_TOKEN_FILE"
  log "GLM maintenance token written to ${MAINTENANCE_TOKEN_FILE}."
}

ensure_identity_token() {
  local username="$1" token_file="${MAINTENANCE_AGENT_TOKEN_DIR}/$1" existing raw code
  mkdir -p "$MAINTENANCE_AGENT_TOKEN_DIR"
  if [ -s "$token_file" ]; then
    existing="$(cat "$token_file" 2>/dev/null || true)"
    code=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: token ${existing}" "${FORGEJO_API}/user")
    if [ "$code" = "200" ]; then
      chmod 600 "$token_file"
      log "Identity token for '${username}' already exists; reusing it."
      return 0
    fi
  fi
  raw="$(docker exec -u git "${FORGEJO_CONTAINER_NAME}" \
    forgejo admin user generate-access-token \
      --username "$username" --token-name "nyankoface-${username}-$(date +%s)" \
      --scopes all --raw 2>"/tmp/${username}_token.log" | tail -n1 | tr -d '[:space:]')"
  if [ -z "$raw" ]; then
    log "ERROR: failed to generate identity token for '${username}'."
    cat "/tmp/${username}_token.log"
    exit 1
  fi
  echo -n "$raw" > "$token_file"
  chmod 600 "$token_file"
  log "Identity token for '${username}' written."
}

ensure_maintenance_webhook() {
  if [ ! -s "$MAINTENANCE_WEBHOOK_SECRET_FILE" ]; then
    dd if=/dev/urandom bs=32 count=1 2>/dev/null | base64 | tr -d '\r\n' > "$MAINTENANCE_WEBHOOK_SECRET_FILE"
  fi
  chmod 600 "$MAINTENANCE_WEBHOOK_SECRET_FILE"

  local code hook_id secret payload
  code=$(api GET "/orgs/${ORG_NAME}/hooks")
  if [ "$code" = "200" ]; then
    hook_id=$(jq -r --arg url "$MAINTENANCE_WEBHOOK_URL" \
      'map(select(.config.url == $url))[0].id // empty' /tmp/api_resp.json)
    if [ -n "$hook_id" ]; then
      secret="$(cat "$MAINTENANCE_WEBHOOK_SECRET_FILE")"
      payload=$(jq -n --arg url "$MAINTENANCE_WEBHOOK_URL" --arg secret "$secret" \
        '{type:"forgejo",active:true,events:["push","issues","issue_comment","pull_request","pull_request_comment"],config:{url:$url,content_type:"json",secret:$secret}}')
      code=$(api PATCH "/orgs/${ORG_NAME}/hooks/${hook_id}" "$payload")
      if [ "$code" = "200" ]; then
        log "Updated GLM maintenance webhook (id ${hook_id}) for push, Issue, Pull Request, and comment events."
        return 0
      fi
      log "ERROR: updating GLM maintenance webhook returned HTTP ${code}:"
      cat /tmp/api_resp.json
      exit 1
    fi
  fi

  secret="$(cat "$MAINTENANCE_WEBHOOK_SECRET_FILE")"
  payload=$(jq -n --arg url "$MAINTENANCE_WEBHOOK_URL" --arg secret "$secret" \
    '{type:"forgejo",active:true,events:["push","issues","issue_comment","pull_request","pull_request_comment"],config:{url:$url,content_type:"json",secret:$secret}}')
  code=$(api POST "/orgs/${ORG_NAME}/hooks" "$payload")
  if [ "$code" = "201" ]; then
    log "Created organization push/Issue/Pull Request/comment webhook for the GLM maintenance agent."
  else
    log "ERROR: creating GLM maintenance webhook returned HTTP ${code}:"
    cat /tmp/api_resp.json
    exit 1
  fi
}

# ------------------------------------------------------------------------
# API helper: perform a request, treat 409/422 "already exists" as success.
# ------------------------------------------------------------------------
api() {
  local method="$1" path="$2" data="${3:-}"
  local args=(-s -o /tmp/api_resp.json -w '%{http_code}' -X "$method" \
    -H "$AUTH_HEADER" -H "Content-Type: application/json" \
    "${FORGEJO_API}${path}")
  if [ -n "$data" ]; then
    args+=(-d "$data")
  fi
  curl "${args[@]}"
}

# Perform an API request as one of the independently seeded identities.
identity_api() {
  local username="$1" method="$2" path="$3" data="${4:-}"
  local token_file="${MAINTENANCE_AGENT_TOKEN_DIR}/${username}"
  if [ "$username" = "glm-maintainer" ]; then
    token_file="$MAINTENANCE_TOKEN_FILE"
  fi
  if [ ! -s "$token_file" ]; then
    log "ERROR: token for '${username}' is unavailable at ${token_file}."
    return 1
  fi

  local token args
  token="$(cat "$token_file")"
  args=(-s -o /tmp/api_resp.json -w '%{http_code}' -X "$method" \
    -H "Authorization: token ${token}" -H "Content-Type: application/json" \
    "${FORGEJO_API}${path}")
  if [ -n "$data" ]; then
    args+=(-d "$data")
  fi
  curl "${args[@]}"
}

# ------------------------------------------------------------------------
# Helpers for seeded user identities. Passwords are generated only for
# account bootstrap; API-driven actions use protected tokens and never expose
# credentials.
# ------------------------------------------------------------------------
ensure_user_account() {
  local username="$1" full_name="$2" email="$3"
  local code
  code=$(api GET "/users/${username}")
  if [ "$code" = "200" ]; then
    log "Seeded user account '${username}' already exists."
    return 0
  fi

  local password payload
  password="$(dd if=/dev/urandom bs=24 count=1 2>/dev/null | base64 | tr -d '\r\n')Aa1!"
  payload=$(jq -n \
    --arg username "$username" --arg full_name "$full_name" \
    --arg email "$email" --arg password "$password" \
    '{username:$username, full_name:$full_name, email:$email, password:$password,
      must_change_password:false, visibility:"public"}')
  code=$(api POST "/admin/users" "$payload")
  if [ "$code" = "201" ]; then
    log "Created seeded user account '${username}'."
  else
    log "WARNING: creating user account '${username}' returned HTTP ${code}:"
    cat /tmp/api_resp.json
  fi
}

ensure_user_avatar() {
  local username="$1" image_file="$2"
  if [ ! -s "$image_file" ]; then
    log "WARNING: avatar file '${image_file}' is missing."
    return 0
  fi

  local code payload_file="/tmp/avatar-${username}.json"
  b64 < "$image_file" | jq -Rs '{image:.}' > "$payload_file"
  code=$(curl -s -o /tmp/api_resp.json -w '%{http_code}' -X POST \
    -H "$AUTH_HEADER" -H "Content-Type: application/json" \
    --data-binary "@${payload_file}" \
    "${FORGEJO_API}/user/avatar?sudo=${username}")
  rm -f "$payload_file"
  if [ "$code" = "204" ]; then
    log "Set avatar for seeded user '${username}'."
  else
    log "WARNING: setting avatar for '${username}' returned HTTP ${code}:"
    cat /tmp/api_resp.json
  fi
}

ensure_org_member() {
  local org_name="$1" username="$2" code team_id
  code=$(api GET "/orgs/${org_name}/teams")
  if [ "$code" != "200" ]; then
    log "WARNING: listing teams for '${org_name}' returned HTTP ${code}."
    return 0
  fi
  team_id=$(jq -r 'map(select(.name == "Owners"))[0].id // .[0].id // empty' /tmp/api_resp.json)
  if [ -z "$team_id" ]; then
    log "WARNING: no organization team found for '${org_name}'."
    return 0
  fi
  code=$(api PUT "/teams/${team_id}/members/${username}")
  if [ "$code" = "204" ] || [ "$code" = "201" ]; then
    log "Added '${username}' to organization '${org_name}'."
    local public_code
    public_code=$(api PUT "/orgs/${org_name}/public_members/${username}?sudo=${username}")
    if [ "$public_code" = "204" ]; then
      log "Published '${username}' as an organization member."
    else
      log "WARNING: publishing '${username}' membership returned HTTP ${public_code}:"
      cat /tmp/api_resp.json
    fi
  else
    log "WARNING: adding '${username}' to '${org_name}' returned HTTP ${code}:"
    cat /tmp/api_resp.json
  fi
}

ensure_org_member_private() {
  local org_name="$1" username="$2" code
  code=$(api DELETE "/orgs/${org_name}/public_members/${username}?sudo=${username}")
  if [ "$code" = "204" ] || [ "$code" = "404" ]; then
    log "Kept '${username}' as a private organization owner in '${org_name}'."
  else
    log "WARNING: hiding '${username}' membership in '${org_name}' returned HTTP ${code}:"
    cat /tmp/api_resp.json
  fi
}

ensure_org_team_member() {
  local org_name="$1" username="$2" team_name="$3" permission="$4"
  local code team_id owners_id payload
  code=$(api GET "/orgs/${org_name}/teams")
  if [ "$code" != "200" ]; then
    log "ERROR: listing teams for '${org_name}' returned HTTP ${code}."
    exit 1
  fi
  team_id=$(jq -r --arg name "$team_name" 'map(select(.name == $name))[0].id // empty' /tmp/api_resp.json)
  owners_id=$(jq -r 'map(select(.name == "Owners"))[0].id // empty' /tmp/api_resp.json)
  if [ -z "$team_id" ]; then
    payload=$(jq -n \
      --arg name "$team_name" --arg permission "$permission" \
      '{name:$name,description:"Seeded community organization membership",permission:$permission,
        includes_all_repositories:true,units:["repo.code"]}')
    code=$(api POST "/orgs/${org_name}/teams" "$payload")
    if [ "$code" != "201" ]; then
      log "ERROR: creating '${team_name}' team in '${org_name}' returned HTTP ${code}:"
      cat /tmp/api_resp.json
      exit 1
    fi
    team_id=$(jq -r '.id' /tmp/api_resp.json)
  fi
  code=$(api PUT "/teams/${team_id}/members/${username}")
  if [ "$code" != "204" ] && [ "$code" != "201" ]; then
    log "ERROR: adding '${username}' to '${org_name}/${team_name}' returned HTTP ${code}:"
    cat /tmp/api_resp.json
    exit 1
  fi
  if [ -n "$owners_id" ] && [ "$owners_id" != "$team_id" ]; then
    code=$(api DELETE "/teams/${owners_id}/members/${username}")
    if [ "$code" != "204" ] && [ "$code" != "404" ]; then
      log "ERROR: removing '${username}' from '${org_name}/Owners' returned HTTP ${code}."
      exit 1
    fi
  fi
  ensure_org_member_private "$org_name" "$username"
  log "Invited '${username}' to private organization '${org_name}' with ${permission} access."
}

ensure_maintenance_org_access() {
  local org_name="$1" username="$2" code team_id owners_id payload
  code=$(api GET "/orgs/${org_name}/teams")
  if [ "$code" != "200" ]; then
    log "ERROR: listing teams for '${org_name}' returned HTTP ${code}."
    exit 1
  fi
  team_id=$(jq -r 'map(select(.name == "glm-maintainers"))[0].id // empty' /tmp/api_resp.json)
  owners_id=$(jq -r 'map(select(.name == "Owners"))[0].id // empty' /tmp/api_resp.json)
  if [ -z "$team_id" ]; then
    payload=$(jq -n '{name:"glm-maintainers",description:"Automated Issue analysis and Pull Request proposals",permission:"write",includes_all_repositories:true,units:["repo.code","repo.issues","repo.pulls"]}')
    code=$(api POST "/orgs/${org_name}/teams" "$payload")
    if [ "$code" != "201" ]; then
      log "ERROR: creating GLM Maintainers team returned HTTP ${code}:"
      cat /tmp/api_resp.json
      exit 1
    fi
    team_id=$(jq -r '.id' /tmp/api_resp.json)
    log "Created least-privilege glm-maintainers team."
  fi
  code=$(api PUT "/teams/${team_id}/members/${username}")
  if [ "$code" != "204" ] && [ "$code" != "201" ]; then
    log "ERROR: adding '${username}' to glm-maintainers returned HTTP ${code}:"
    cat /tmp/api_resp.json
    exit 1
  fi
  if [ -n "$owners_id" ] && [ "$owners_id" != "$team_id" ]; then
    code=$(api DELETE "/teams/${owners_id}/members/${username}")
    if [ "$code" != "204" ] && [ "$code" != "404" ]; then
      log "ERROR: removing '${username}' from Owners returned HTTP ${code}:"
      cat /tmp/api_resp.json
      exit 1
    fi
  fi
  ensure_org_member_private "$org_name" "$username"
  log "Granted '${username}' repository write access without organization owner rights."
}

ensure_org_not_member() {
  local org_name="$1" username="$2" code team_id
  code=$(api GET "/orgs/${org_name}/teams")
  if [ "$code" != "200" ]; then
    log "WARNING: listing teams for '${org_name}' returned HTTP ${code}."
    return 0
  fi
  for team_id in $(jq -r '.[].id' /tmp/api_resp.json); do
    code=$(api DELETE "/teams/${team_id}/members/${username}")
    if [ "$code" != "204" ] && [ "$code" != "404" ]; then
      log "ERROR: removing '${username}' from team ${team_id} in '${org_name}' returned HTTP ${code}:"
      cat /tmp/api_resp.json
      exit 1
    fi
  done
  log "Confirmed '${username}' is not a member of organization '${org_name}'."
}

b64() {
  # base64-encode stdin without line wraps (portable across busybox/gnu base64)
  base64 -w0 2>/dev/null || base64
}

ensure_organization() {
  local org_name="$1" full_name="$2" description="$3" website="$4" location="$5"
  local visibility="${6:-public}" code payload
  code=$(api GET "/orgs/${org_name}")
  if [ "$code" != "200" ]; then
    code=$(api POST "/orgs" "$(jq -n --arg name "$org_name" --arg visibility "$visibility" \
      '{username:$name, visibility:$visibility}')")
    if [ "$code" != "201" ]; then
      log "WARNING: creating organization '${org_name}' returned HTTP ${code}:"
      cat /tmp/api_resp.json
      return 0
    fi
    log "Created organization '${org_name}'."
  fi
  payload=$(jq -n --arg full_name "$full_name" --arg description "$description" \
    --arg website "$website" --arg location "$location" --arg visibility "$visibility" \
    '{full_name:$full_name,description:$description,website:$website,location:$location,visibility:$visibility}')
  code=$(api PATCH "/orgs/${org_name}" "$payload")
  if [ "$code" = "200" ]; then
    log "Updated ${visibility} organization profile '${org_name}'."
  else
    log "WARNING: updating organization '${org_name}' returned HTTP ${code}:"
    cat /tmp/api_resp.json
  fi
}

ensure_org_avatar() {
  local org_name="$1" image_file="$2" code payload_file
  payload_file="/tmp/org-avatar-${org_name}.json"
  if [ ! -s "$image_file" ]; then
    log "WARNING: organization avatar '${image_file}' is missing."
    return 0
  fi
  b64 < "$image_file" | jq -Rs '{image:.}' > "$payload_file"
  code=$(curl -s -o /tmp/api_resp.json -w '%{http_code}' -X POST \
    -H "$AUTH_HEADER" -H "Content-Type: application/json" --data-binary "@${payload_file}" \
    "${FORGEJO_API}/orgs/${org_name}/avatar")
  rm -f "$payload_file"
  if [ "$code" = "204" ]; then
    log "Set organization avatar for '${org_name}'."
  else
    log "WARNING: setting avatar for '${org_name}' returned HTTP ${code}:"
    cat /tmp/api_resp.json
  fi
}

# ------------------------------------------------------------------------
# 3. Create the `nyankoface` organization (idempotent).
# ------------------------------------------------------------------------
ensure_organization "nyankoface" "NyankoFace" "Open-source models, datasets, Spaces, and agent tooling backed by Forgejo." "https://github.com/Sunwood-ai-labs/NyankoFace" "Local-first"
ensure_organization "seraphim-labs" "Seraphim Labs" "An angel-inspired AI safety collective building calm, accountable systems." "https://example.invalid/git/seraphim-labs" "The Upper Layer"
ensure_organization "vault-research" "Vault Research" "Member-only operational research and internal release evidence." "" "Private network" "private"
ensure_organization "local-makers" "Local Makers" "A private circle for community members sharing in-progress local AI experiments." "" "Community lab" "private"
ensure_org_avatar "nyankoface" "/assets/organization-avatars/nyankoface.png"
ensure_org_avatar "seraphim-labs" "/assets/organization-avatars/seraphim-labs.png"

ensure_user_account "luna-scout" "Luna Scout" "luna-scout@agents.nyankoface.local"
ensure_user_account "patch-orbit" "Patch Orbit" "patch-orbit@agents.nyankoface.local"
ensure_user_account "mikan-reviewer" "Mikan Reviewer" "mikan-reviewer@agents.nyankoface.local"
ensure_user_account "aiko-mesh" "Aiko Mesh" "aiko-mesh@team.nyankoface.local"
ensure_user_account "ren-vector" "Ren Vector" "ren-vector@team.nyankoface.local"
ensure_user_account "mira-signal" "Mira Signal" "mira-signal@team.nyankoface.local"
ensure_user_account "aurelia-vale" "Aurelia Vale" "aurelia-vale@seraphim.nyankoface.local"
ensure_user_account "cassian-reed" "Cassian Reed" "cassian-reed@seraphim.nyankoface.local"
ensure_user_account "ilyana-noor" "Ilyana Noor" "ilyana-noor@seraphim.nyankoface.local"
ensure_user_account "lucien-sol" "Lucien Sol" "lucien-sol@seraphim.nyankoface.local"
ensure_user_account "glm-maintainer" "GLM Maintainer" "glm-maintainer@agents.nyankoface.local"
ensure_user_account "designer-agent" "NyankoFace Designer" "designer-agent@agents.nyankoface.local"
ensure_user_account "coding-agent" "NyankoFace Coding" "coding-agent@agents.nyankoface.local"
ensure_user_account "docs-agent" "NyankoFace Docs" "docs-agent@agents.nyankoface.local"
ensure_user_account "security-agent" "NyankoFace Security" "security-agent@agents.nyankoface.local"
ensure_user_account "review-agent" "NyankoFace Review" "review-agent@agents.nyankoface.local"
ensure_user_account "haruka-sato" "佐藤 遥" "haruka-sato@users.nyankoface.local"
ensure_user_account "takumi-endo" "遠藤 匠" "takumi-endo@users.nyankoface.local"
ensure_user_account "nana-kurose" "黒瀬 菜々" "nana-kurose@users.nyankoface.local"
ensure_user_account "rio-kanda" "神田 理央" "rio-kanda@users.nyankoface.local"
ensure_user_avatar "luna-scout" "/assets/agent-avatars/luna-scout.png"
ensure_user_avatar "patch-orbit" "/assets/agent-avatars/patch-orbit.png"
ensure_user_avatar "mikan-reviewer" "/assets/agent-avatars/mikan-reviewer.png"
ensure_user_avatar "aiko-mesh" "/assets/agent-avatars/aiko-mesh.png"
ensure_user_avatar "ren-vector" "/assets/agent-avatars/ren-vector.png"
ensure_user_avatar "mira-signal" "/assets/agent-avatars/mira-signal.png"
ensure_user_avatar "aurelia-vale" "/assets/agent-avatars/aurelia-vale.png"
ensure_user_avatar "cassian-reed" "/assets/agent-avatars/cassian-reed.png"
ensure_user_avatar "ilyana-noor" "/assets/agent-avatars/ilyana-noor.png"
ensure_user_avatar "lucien-sol" "/assets/agent-avatars/lucien-sol.png"
ensure_user_avatar "glm-maintainer" "/assets/agent-avatars/glm-maintainer.png"
ensure_user_avatar "designer-agent" "/assets/agent-avatars/designer-agent.png"
ensure_user_avatar "coding-agent" "/assets/agent-avatars/coding-agent.png"
ensure_user_avatar "docs-agent" "/assets/agent-avatars/docs-agent.png"
ensure_user_avatar "security-agent" "/assets/agent-avatars/security-agent.png"
ensure_user_avatar "review-agent" "/assets/agent-avatars/review-agent.png"
ensure_user_avatar "haruka-sato" "/assets/user-avatars/haruka-sato.png"
ensure_user_avatar "takumi-endo" "/assets/user-avatars/takumi-endo.png"
ensure_user_avatar "nana-kurose" "/assets/user-avatars/nana-kurose.png"
ensure_user_avatar "rio-kanda" "/assets/user-avatars/rio-kanda.png"
ensure_org_member "nyankoface" "aiko-mesh"
ensure_org_member "nyankoface" "ren-vector"
ensure_org_member "nyankoface" "mira-signal"
ensure_maintenance_org_access "nyankoface" "glm-maintainer"
ensure_maintenance_org_access "nyankoface" "designer-agent"
ensure_maintenance_org_access "nyankoface" "coding-agent"
ensure_maintenance_org_access "nyankoface" "docs-agent"
ensure_maintenance_org_access "nyankoface" "security-agent"
ensure_maintenance_org_access "nyankoface" "review-agent"
ensure_org_member "seraphim-labs" "nyankoface-admin"
ensure_org_member_private "seraphim-labs" "nyankoface-admin"
ensure_org_not_member "seraphim-labs" "aiko-mesh"
ensure_org_not_member "seraphim-labs" "ren-vector"
ensure_org_not_member "seraphim-labs" "mira-signal"
ensure_org_member "seraphim-labs" "aurelia-vale"
ensure_org_member "seraphim-labs" "cassian-reed"
ensure_org_member "seraphim-labs" "ilyana-noor"
ensure_org_member "seraphim-labs" "lucien-sol"
ensure_org_member "vault-research" "security-agent"
ensure_org_member_private "vault-research" "security-agent"
ensure_org_member "vault-research" "docs-agent"
ensure_org_member_private "vault-research" "docs-agent"
ensure_org_member "vault-research" "review-agent"
ensure_org_member_private "vault-research" "review-agent"
ensure_org_not_member "vault-research" "coding-agent"
ensure_org_team_member "local-makers" "haruka-sato" "Contributors" "write"
ensure_org_team_member "local-makers" "nana-kurose" "Readers" "read"
ensure_org_not_member "local-makers" "takumi-endo"
ensure_org_not_member "local-makers" "rio-kanda"

ensure_actions_runner_token
ensure_maintenance_token
ensure_identity_token "designer-agent"
ensure_identity_token "coding-agent"
ensure_identity_token "docs-agent"
ensure_identity_token "security-agent"
ensure_identity_token "review-agent"
ensure_identity_token "haruka-sato"
ensure_identity_token "takumi-endo"
ensure_identity_token "nana-kurose"
ensure_identity_token "rio-kanda"
ensure_maintenance_webhook

# ------------------------------------------------------------------------
# Helper: create a repo under the org (idempotent), auto_init true.
# ------------------------------------------------------------------------
ensure_repo() {
  local name="$1" desc="$2"
  local code
  code=$(api GET "/repos/${ORG_NAME}/${name}")
  if [ "$code" = "200" ]; then
    log "Repo '${ORG_NAME}/${name}' already exists."
    return 0
  fi
  code=$(api POST "/orgs/${ORG_NAME}/repos" "$(jq -n \
    --arg name "$name" --arg desc "$desc" \
    '{name:$name, description:$desc, auto_init:true, private:false, default_branch:"main"}')")
  if [ "$code" = "201" ]; then
    log "Repo '${ORG_NAME}/${name}' created."
  else
    log "WARNING: repo create for '${name}' returned HTTP ${code}:"
    cat /tmp/api_resp.json
  fi
}

ensure_repo_for_org() {
  local org_name="$1" name="$2" desc="$3" code
  code=$(api GET "/repos/${org_name}/${name}")
  if [ "$code" = "200" ]; then
    log "Repo '${org_name}/${name}' already exists."
    return 0
  fi
  code=$(api POST "/orgs/${org_name}/repos" "$(jq -n --arg name "$name" --arg desc "$desc" \
    '{name:$name,description:$desc,auto_init:true,private:false,default_branch:"main"}')")
  if [ "$code" = "201" ]; then
    log "Created repository '${org_name}/${name}'."
  else
    log "WARNING: creating '${org_name}/${name}' returned HTTP ${code}:"
    cat /tmp/api_resp.json
  fi
}

ensure_repo_for_org "seraphim-labs" "halo-observatory" "Transparent evaluation notes for calm and accountable AI systems"

# ------------------------------------------------------------------------
# Helper: set topics on a repo (idempotent — PUT replaces the full set).
# ------------------------------------------------------------------------
set_topics() {
  local name="$1"; shift
  local owner="${REPO_OWNER_CONTEXT:-$ORG_NAME}"
  local topics_json
  topics_json=$(printf '%s\n' "$@" | jq -R . | jq -s '{topics: .}')
  local code
  code=$(api PUT "/repos/${owner}/${name}/topics" "$topics_json")
  if [ "$code" = "204" ]; then
    log "Topics set on '${owner}/${name}': $*"
  else
    log "WARNING: set topics for '${owner}/${name}' returned HTTP ${code}:"
    cat /tmp/api_resp.json
  fi
}

# Create and maintain a public knowledge repository as the account itself.
# The same token also authors the article commit, so ownership and repository
# history remain attributable to the independent identity.
ensure_personal_knowledge_repo() {
  local username="$1" description="$2" code
  code=$(identity_api "$username" GET "/repos/${username}/knowledge")
  if [ "$code" = "200" ]; then
    log "Personal knowledge repo '${username}/knowledge' already exists."
    return 0
  fi

  code=$(identity_api "$username" POST "/user/repos" "$(jq -n \
    --arg desc "$description" \
    '{name:"knowledge",description:$desc,auto_init:true,private:false,default_branch:"main"}')")
  if [ "$code" = "201" ]; then
    log "Account '${username}' created its public knowledge repository."
  else
    log "ERROR: creating '${username}/knowledge' returned HTTP ${code}:"
    cat /tmp/api_resp.json
    exit 1
  fi
}

set_personal_knowledge_topics() {
  local username="$1"; shift
  local topics_json code
  topics_json=$(printf '%s\n' "$@" | jq -R . | jq -s '{topics: .}')
  code=$(identity_api "$username" PUT "/repos/${username}/knowledge/topics" "$topics_json")
  if [ "$code" = "204" ]; then
    log "Topics set on '${username}/knowledge': $*"
  else
    log "ERROR: setting topics on '${username}/knowledge' returned HTTP ${code}:"
    cat /tmp/api_resp.json
    exit 1
  fi
}

put_personal_knowledge_file() {
  local username="$1" path="$2" content_file="$3" message="$4"
  local content_b64 get_code sha current_b64 payload code
  content_b64="$(b64 < "$content_file")"
  get_code=$(identity_api "$username" GET "/repos/${username}/knowledge/contents/${path}")

  if [ "$get_code" = "200" ] && jq -e 'type == "object" and (.sha | type == "string" and length > 0)' /tmp/api_resp.json >/dev/null 2>&1; then
    sha=$(jq -r '.sha' /tmp/api_resp.json)
    current_b64=$(jq -r '.content // ""' /tmp/api_resp.json | tr -d '\r\n')
    if [ "$current_b64" = "$content_b64" ]; then
      log "Unchanged ${username}/knowledge/${path}; skipping commit."
      return 0
    fi
    payload=$(jq -n --arg msg "$message" --arg content "$content_b64" --arg sha "$sha" \
      '{message:$msg,content:$content,sha:$sha,branch:"main"}')
    code=$(identity_api "$username" PUT "/repos/${username}/knowledge/contents/${path}" "$payload")
    if [ "$code" = "200" ]; then
      log "Account '${username}' updated knowledge article '${path}'."
      return 0
    fi
  else
    payload=$(jq -n --arg msg "$message" --arg content "$content_b64" \
      '{message:$msg,content:$content,branch:"main"}')
    code=$(identity_api "$username" POST "/repos/${username}/knowledge/contents/${path}" "$payload")
    if [ "$code" = "201" ]; then
      log "Account '${username}' published knowledge article '${path}'."
      return 0
    fi
  fi

  log "ERROR: publishing '${username}/knowledge/${path}' returned HTTP ${code}:"
  cat /tmp/api_resp.json
  exit 1
}

verify_personal_knowledge_author() {
  local username="$1" code
  code=$(identity_api "$username" GET "/user")
  if [ "$code" != "200" ] ||
     [ "$(jq -r '.login // ""' /tmp/api_resp.json)" != "$username" ] ||
     [ "$(jq -r '.is_admin // false' /tmp/api_resp.json)" != "false" ]; then
    log "ERROR: '${username}' is not an independent non-admin user account."
    exit 1
  fi

  code=$(identity_api "$username" GET "/repos/${username}/knowledge")
  if [ "$code" != "200" ] || [ "$(jq -r '.owner.login // ""' /tmp/api_resp.json)" != "$username" ]; then
    log "ERROR: personal knowledge repository ownership check failed for '${username}'."
    exit 1
  fi

  code=$(identity_api "$username" GET "/repos/${username}/knowledge/commits?limit=1")
  if [ "$code" != "200" ] || [ "$(jq -r '.[0].author.login // ""' /tmp/api_resp.json)" != "$username" ]; then
    log "ERROR: latest knowledge commit is not attributed to '${username}'."
    exit 1
  fi
  log "Verified personal repository and article commit ownership for '${username}'."
}

ensure_private_org_knowledge_repo() {
  local org_name="$1" repo_name="$2" description="$3" code
  code=$(api GET "/repos/${org_name}/${repo_name}")
  if [ "$code" = "200" ]; then
    if [ "$(jq -r '.private // false' /tmp/api_resp.json)" != "true" ]; then
      log "ERROR: '${org_name}/${repo_name}' exists but is not private."
      exit 1
    fi
    log "Private organization repo '${org_name}/${repo_name}' already exists."
    return 0
  fi

  code=$(api POST "/orgs/${org_name}/repos" "$(jq -n \
    --arg name "$repo_name" --arg desc "$description" \
    '{name:$name,description:$desc,auto_init:true,private:true,default_branch:"main"}')")
  if [ "$code" = "201" ]; then
    log "Created private organization repo '${org_name}/${repo_name}'."
  else
    log "ERROR: creating private repo '${org_name}/${repo_name}' returned HTTP ${code}:"
    cat /tmp/api_resp.json
    exit 1
  fi
}

set_private_org_knowledge_topics() {
  local username="$1" org_name="$2" repo_name="$3"; shift 3
  local topics_json code
  topics_json=$(printf '%s\n' "$@" | jq -R . | jq -s '{topics: .}')
  code=$(identity_api "$username" PUT "/repos/${org_name}/${repo_name}/topics" "$topics_json")
  if [ "$code" = "204" ]; then
    log "Member '${username}' set topics on '${org_name}/${repo_name}'."
  else
    log "ERROR: setting topics on '${org_name}/${repo_name}' returned HTTP ${code}:"
    cat /tmp/api_resp.json
    exit 1
  fi
}

set_private_org_knowledge_topics_as_admin() {
  local org_name="$1" repo_name="$2"; shift 2
  local topics_json code
  topics_json=$(printf '%s\n' "$@" | jq -R . | jq -s '{topics: .}')
  code=$(api PUT "/repos/${org_name}/${repo_name}/topics" "$topics_json")
  if [ "$code" = "204" ]; then
    log "Topics set on private repository '${org_name}/${repo_name}'."
  else
    log "ERROR: setting topics on '${org_name}/${repo_name}' returned HTTP ${code}:"
    cat /tmp/api_resp.json
    exit 1
  fi
}

put_private_org_knowledge_file() {
  local username="$1" org_name="$2" repo_name="$3" path="$4" content_file="$5" message="$6"
  local content_b64 get_code sha current_b64 payload code
  content_b64="$(b64 < "$content_file")"
  get_code=$(identity_api "$username" GET "/repos/${org_name}/${repo_name}/contents/${path}")

  if [ "$get_code" = "200" ] && jq -e 'type == "object" and (.sha | type == "string" and length > 0)' /tmp/api_resp.json >/dev/null 2>&1; then
    sha=$(jq -r '.sha' /tmp/api_resp.json)
    current_b64=$(jq -r '.content // ""' /tmp/api_resp.json | tr -d '\r\n')
    if [ "$current_b64" = "$content_b64" ]; then
      log "Unchanged private article ${org_name}/${repo_name}/${path}; skipping commit."
      return 0
    fi
    payload=$(jq -n --arg msg "$message" --arg content "$content_b64" --arg sha "$sha" \
      '{message:$msg,content:$content,sha:$sha,branch:"main"}')
    code=$(identity_api "$username" PUT "/repos/${org_name}/${repo_name}/contents/${path}" "$payload")
    [ "$code" = "200" ] || {
      log "ERROR: updating private article returned HTTP ${code}."
      cat /tmp/api_resp.json
      exit 1
    }
  else
    payload=$(jq -n --arg msg "$message" --arg content "$content_b64" \
      '{message:$msg,content:$content,branch:"main"}')
    code=$(identity_api "$username" POST "/repos/${org_name}/${repo_name}/contents/${path}" "$payload")
    [ "$code" = "201" ] || {
      log "ERROR: creating private article returned HTTP ${code}."
      cat /tmp/api_resp.json
      exit 1
    }
  fi
  log "Member '${username}' published private article '${org_name}/${repo_name}/${path}'."
}

assert_access_status() {
  local label="$1" actual="$2" expected="$3"
  if [ "$expected" = "denied" ]; then
    if [ "$actual" = "403" ] || [ "$actual" = "404" ]; then
      log "ACL verified: ${label} is denied (HTTP ${actual})."
      return 0
    fi
  elif [ "$actual" = "$expected" ]; then
    log "ACL verified: ${label} returned HTTP ${actual}."
    return 0
  fi
  log "ERROR: ACL check '${label}' returned HTTP ${actual}; expected ${expected}."
  exit 1
}

verify_private_org_knowledge_acl() {
  local org_name="$1" repo_name="$2" path="$3" member="$4" nonmember="$5"
  local member_token_file="${MAINTENANCE_AGENT_TOKEN_DIR}/${member}"
  local nonmember_token_file="${MAINTENANCE_AGENT_TOKEN_DIR}/${nonmember}"
  local anonymous_org anonymous_repo anonymous_file
  local member_org member_repo member_file
  local nonmember_org nonmember_repo nonmember_file

  anonymous_org=$(curl -s -o /dev/null -w '%{http_code}' "${FORGEJO_API}/orgs/${org_name}")
  anonymous_repo=$(curl -s -o /dev/null -w '%{http_code}' "${FORGEJO_API}/repos/${org_name}/${repo_name}")
  anonymous_file=$(curl -s -o /dev/null -w '%{http_code}' "${FORGEJO_API}/repos/${org_name}/${repo_name}/contents/${path}")
  member_org=$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: token $(cat "$member_token_file")" "${FORGEJO_API}/orgs/${org_name}")
  member_repo=$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: token $(cat "$member_token_file")" "${FORGEJO_API}/repos/${org_name}/${repo_name}")
  member_file=$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: token $(cat "$member_token_file")" "${FORGEJO_API}/repos/${org_name}/${repo_name}/contents/${path}")
  nonmember_org=$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: token $(cat "$nonmember_token_file")" "${FORGEJO_API}/orgs/${org_name}")
  nonmember_repo=$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: token $(cat "$nonmember_token_file")" "${FORGEJO_API}/repos/${org_name}/${repo_name}")
  nonmember_file=$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: token $(cat "$nonmember_token_file")" "${FORGEJO_API}/repos/${org_name}/${repo_name}/contents/${path}")

  assert_access_status "anonymous organization access" "$anonymous_org" "denied"
  assert_access_status "anonymous repository access" "$anonymous_repo" "denied"
  assert_access_status "anonymous article access" "$anonymous_file" "denied"
  assert_access_status "member organization access (${member})" "$member_org" "200"
  assert_access_status "member repository access (${member})" "$member_repo" "200"
  assert_access_status "member article access (${member})" "$member_file" "200"
  assert_access_status "non-member organization access (${nonmember})" "$nonmember_org" "denied"
  assert_access_status "non-member repository access (${nonmember})" "$nonmember_repo" "denied"
  assert_access_status "non-member article access (${nonmember})" "$nonmember_file" "denied"
}

# ------------------------------------------------------------------------
# Helper: create or update a file's content in a repo via the Contents API.
# Handles the "already exists" case by fetching the current sha and PUTting
# an update instead of a create.
# ------------------------------------------------------------------------
put_file() {
  local name="$1" path="$2" content_file="$3" message="$4"
  local owner="${REPO_OWNER_CONTEXT:-$ORG_NAME}"
  local content_b64
  content_b64="$(b64 < "$content_file")"

  # Check if file already exists to fetch its sha (needed for update).
  local get_code
  get_code=$(api GET "/repos/${owner}/${name}/contents/${path}")

  # Forgejo can briefly answer a missing exact path with the repository root
  # directory listing (HTTP 200) immediately after an imported branch lands.
  # Only treat a response as an existing file when it is an object with a SHA;
  # otherwise create the requested path instead of sending a SHA-less update.
  if [ "$get_code" = "200" ] && jq -e 'type == "object" and (.sha | type == "string" and length > 0)' /tmp/api_resp.json >/dev/null 2>&1; then
    local sha
    sha=$(jq -r '.sha' /tmp/api_resp.json)
    local current_b64
    current_b64=$(jq -r '.content // ""' /tmp/api_resp.json | tr -d '\r\n')
    if [ "$current_b64" = "$content_b64" ]; then
      log "Unchanged ${name}/${path}; skipping commit."
      return 0
    fi
    local payload
    payload=$(jq -n --arg msg "$message" --arg content "$content_b64" --arg sha "$sha" \
      '{message:$msg, content:$content, sha:$sha, branch:"main"}')
    local code
    code=$(api PUT "/repos/${owner}/${name}/contents/${path}" "$payload")
    if [ "$code" = "200" ]; then
      log "Updated ${name}/${path}."
    else
      log "WARNING: update ${name}/${path} returned HTTP ${code}:"
      cat /tmp/api_resp.json
    fi
  else
    if [ "$get_code" = "200" ]; then
      log "Contents lookup for ${name}/${path} returned a directory listing; creating the exact file path."
    fi
    local payload
    payload=$(jq -n --arg msg "$message" --arg content "$content_b64" \
      '{message:$msg, content:$content, branch:"main"}')
    local code
    code=$(api POST "/repos/${owner}/${name}/contents/${path}" "$payload")
    if [ "$code" = "201" ]; then
      log "Created ${name}/${path}."
    else
      log "WARNING: create ${name}/${path} returned HTTP ${code}:"
      cat /tmp/api_resp.json
    fi
  fi
}

# ------------------------------------------------------------------------
# Helper: remove an obsolete file after a content-layout migration.
# Missing paths are already in the desired state.
# ------------------------------------------------------------------------
delete_file() {
  local name="$1" path="$2" message="$3"
  local get_code sha payload code
  get_code=$(api GET "/repos/${ORG_NAME}/${name}/contents/${path}")
  if [ "$get_code" != "200" ] || ! jq -e 'type == "object" and (.sha | type == "string" and length > 0)' /tmp/api_resp.json >/dev/null 2>&1; then
    return 0
  fi
  sha=$(jq -r '.sha' /tmp/api_resp.json)
  payload=$(jq -n --arg msg "$message" --arg sha "$sha" \
    '{message:$msg, sha:$sha, branch:"main"}')
  code=$(api DELETE "/repos/${ORG_NAME}/${name}/contents/${path}" "$payload")
  if [ "$code" = "200" ]; then
    log "Removed obsolete ${name}/${path}."
  else
    log "WARNING: delete ${name}/${path} returned HTTP ${code}:"
    cat /tmp/api_resp.json
  fi
}

# ------------------------------------------------------------------------
# Helper: create a Pages source branch from the repository's default branch.
# A 409 means the branch already exists, which is the expected idempotent
# result when the seed container runs again.
# ------------------------------------------------------------------------
ensure_pages_branch() {
  local name="$1" branch="${2:-gh-pages}"
  local code
  code=$(api GET "/repos/${ORG_NAME}/${name}/branches/${branch}")
  if [ "$code" = "200" ]; then
    log "Pages branch '${branch}' already exists on '${name}'."
    return 0
  fi

  code=$(api POST "/repos/${ORG_NAME}/${name}/branches" "$(jq -n \
    --arg new_branch "$branch" '{new_branch_name:$new_branch, old_branch_name:"main"}')")
  if [ "$code" = "201" ]; then
    log "Created Pages branch '${branch}' on '${name}'."
  else
    log "WARNING: creating Pages branch '${branch}' on '${name}' returned HTTP ${code}:"
    cat /tmp/api_resp.json
  fi
}

# Keep one stable pull request available for visual regression coverage. The
# issue and pull request share Forgejo's repository index, so a closed issue #1
# makes the first fixture pull request #2 without cluttering the open list.
ensure_pull_detail_fixture() {
  local name="$1" branch="visual-qa-pull" code issue_number payload content_b64

  code=$(api GET "/repos/${ORG_NAME}/${name}/pulls/2")
  if [ "$code" = "200" ]; then
    log "Pull request fixture '${name}#2' already exists."
    return 0
  fi

  code=$(api GET "/repos/${ORG_NAME}/${name}/issues/1")
  if [ "$code" != "200" ]; then
    payload=$(jq -n '{title:"Visual QA fixture index",body:"Reserved closed issue used to keep the pull-request visual fixture at a stable URL."}')
    code=$(api POST "/repos/${ORG_NAME}/${name}/issues" "$payload")
    if [ "$code" = "201" ]; then
      issue_number=$(jq -r '.number' /tmp/api_resp.json)
      api PATCH "/repos/${ORG_NAME}/${name}/issues/${issue_number}" '{"state":"closed"}' >/dev/null
      log "Created closed index fixture '${name}#${issue_number}'."
    fi
  fi

  code=$(api GET "/repos/${ORG_NAME}/${name}/branches/${branch}")
  if [ "$code" != "200" ]; then
    api POST "/repos/${ORG_NAME}/${name}/branches" "$(jq -n --arg branch "$branch" '{new_branch_name:$branch,old_branch_name:"main"}')" >/dev/null
  fi

  printf '%s\n' '# Pull request visual fixture' '' 'This branch keeps the pull request detail page covered by screenshot QA.' > "${WORKDIR}/${name}_pull_fixture.md"
  content_b64="$(b64 < "${WORKDIR}/${name}_pull_fixture.md")"
  code=$(api GET "/repos/${ORG_NAME}/${name}/contents/visual-qa-note.md?ref=${branch}")
  if [ "$code" != "200" ]; then
    payload=$(jq -n --arg content "$content_b64" --arg branch "$branch" '{message:"Add pull request visual fixture",content:$content,branch:$branch}')
    api POST "/repos/${ORG_NAME}/${name}/contents/visual-qa-note.md" "$payload" >/dev/null
  fi

  payload=$(jq -n --arg head "$branch" '{base:"main",head:$head,title:"Keep pull request detail visually covered",body:"Stable sample for title, branch metadata, tabs, Markdown, timeline events, and merge instructions."}')
  code=$(api POST "/repos/${ORG_NAME}/${name}/pulls" "$payload")
  if [ "$code" = "201" ]; then
    log "Created pull request fixture '${name}#2'."
  else
    log "WARNING: creating pull request fixture on '${name}' returned HTTP ${code}:"
    cat /tmp/api_resp.json
  fi
}

# Keep a stable reaction row available for screenshot QA in clean Compose
# environments. Issue #1 is reserved above, so this fixture does not depend on
# interactive issues created later on a developer machine.
ensure_community_reaction_fixture() {
  local name="$1" issue_number="1" content code

  for content in "+1" "eyes" "rocket"; do
    code=$(api POST "/repos/${ORG_NAME}/${name}/issues/${issue_number}/reactions" "$(jq -n --arg content "$content" '{content:$content}')")
    if [ "$code" = "201" ] || [ "$code" = "200" ] || [ "$code" = "409" ]; then
      continue
    fi
    log "WARNING: reaction '${content}' on ${name}#${issue_number} returned HTTP ${code}:"
    cat /tmp/api_resp.json
  done
}

# Repair the deterministic community fixtures on every seed run. Earlier
# Windows-side API experiments could persist literal question marks in these
# records; sending JSON from the Linux seed container keeps UTF-8 intact and
# makes visual QA reproducible across existing as well as clean volumes.
repair_community_qa_fixture() {
  local name="$1" payload

  payload=$(jq -n \
    --arg title "READMEに自動保守の説明を追加する" \
    --arg body $'README.md に `## Automated maintenance` セクションを追加してください。\n\nIssueからGLM保守エージェントがPull Requestを作成する流れと、人間によるレビューが必要なことを簡潔に説明してください。' \
    '{title:$title,body:$body}')
  api PATCH "/repos/${ORG_NAME}/${name}/issues/1" "$payload" >/dev/null

  payload=$(jq -n \
    --arg title "[GLM] READMEに自動保守の説明を追加する" \
    --arg body $'## GLM maintenance result\n\nREADME.md に自動保守フローの説明を追加します。\n\n### 変更ファイル\n\n- `README.md`\n\n### 確認\n\n- `git diff --check`\n- 人間によるレビューが必要です\n\nCloses #1' \
    '{title:$title,body:$body}')
  api PATCH "/repos/${ORG_NAME}/${name}/pulls/2" "$payload" >/dev/null
}

# ------------------------------------------------------------------------
# Helper: create a lightweight, idempotent tag for a prompt's imported
# version. This makes the visible `version-v*` topic traceable through the
# native Forgejo Git history as well as through the NyankoFace directory.
# ------------------------------------------------------------------------
ensure_tag() {
  local name="$1" tag="$2" message="$3"
  local owner="${REPO_OWNER_CONTEXT:-$ORG_NAME}" code
  code=$(api GET "/repos/${owner}/${name}/tags?limit=100")
  if [ "$code" = "200" ] && jq -e --arg tag "$tag" '.[] | select(.name == $tag)' /tmp/api_resp.json >/dev/null; then
    log "Tag '${tag}' already exists on '${name}'."
    return 0
  fi

  code=$(api POST "/repos/${owner}/${name}/tags" "$(jq -n --arg tag "$tag" --arg message "$message" '{tag_name:$tag,target:"main",message:$message}')")
  if [ "$code" = "201" ]; then
    log "Created tag '${tag}' on '${name}'."
  else
    log "WARNING: create tag '${tag}' on '${name}' returned HTTP ${code}:"
    cat /tmp/api_resp.json
  fi
}

repo_has_tag() {
  local name="$1" tag="$2"
  local code
  code=$(api GET "/repos/${ORG_NAME}/${name}/tags?limit=100")
  [ "$code" = "200" ] && jq -e --arg tag "$tag" '.[] | select(.name == $tag)' /tmp/api_resp.json >/dev/null
}

# ------------------------------------------------------------------------
# Helper: create an issue/discussion sample only when the title is absent.
# This keeps the Community page useful for HF-style visual comparison while
# remaining safe to rerun after docker resets.
# ------------------------------------------------------------------------
ensure_issue() {
  local name="$1" title="$2" body="$3"
  local owner="${REPO_OWNER_CONTEXT:-$ORG_NAME}" code
  code=$(api GET "/repos/${owner}/${name}/issues?state=all")
  if [ "$code" = "200" ] && jq -e --arg title "$title" '.[] | select(.title == $title)' /tmp/api_resp.json >/dev/null; then
    log "Issue '${title}' already exists on ${name}."
    return 0
  fi

  local payload
  payload=$(jq -n --arg title "$title" --arg body "$body" '{title:$title, body:$body}')
  code=$(api POST "/repos/${owner}/${name}/issues" "$payload")
  if [ "$code" = "201" ]; then
    log "Created issue '${title}' on ${name}."
  else
    log "WARNING: create issue '${title}' on ${name} returned HTTP ${code}:"
    cat /tmp/api_resp.json
  fi
}

# Add a persistent sample reply as a specific virtual agent. The hidden marker
# is stable across copy edits, making the operation idempotent on every seed.
ensure_agent_comment() {
  local name="$1" issue_title="$2" username="$3" marker="$4" body="$5"
  local owner="${REPO_OWNER_CONTEXT:-$ORG_NAME}" code issue_number normalized_body payload existing_id existing_body

  code=$(api GET "/repos/${owner}/${name}/issues?state=all&limit=100")
  if [ "$code" != "200" ]; then
    log "WARNING: could not find issue '${issue_title}' on ${name} (HTTP ${code})."
    return 0
  fi
  issue_number=$(jq -r --arg title "$issue_title" \
    '[.[] | select(.title == $title)][0].number // empty' /tmp/api_resp.json)
  if [ -z "$issue_number" ]; then
    log "WARNING: issue '${issue_title}' is absent on ${name}; skipping agent reply."
    return 0
  fi

  normalized_body="$(printf '%b' "$body")

<!-- nyankoface-agent:${marker} -->"
  code=$(api GET "/repos/${owner}/${name}/issues/${issue_number}/comments?limit=100")
  if [ "$code" = "200" ]; then
    existing_id=$(jq -r --arg marker "$marker" \
      '[.[] | select(.body | contains("<!-- nyankoface-agent:" + $marker + " -->"))][0].id // empty' /tmp/api_resp.json)
    if [ -n "$existing_id" ]; then
      existing_body=$(jq -r --argjson id "$existing_id" '.[] | select(.id == $id) | .body' /tmp/api_resp.json)
      if [ "$existing_body" = "$normalized_body" ]; then
        log "Virtual-agent reply '${marker}' already exists on ${name}#${issue_number}."
        return 0
      fi
      payload=$(jq -n --arg body "$normalized_body" '{body:$body}')
      code=$(api PATCH "/repos/${owner}/${name}/issues/comments/${existing_id}?sudo=${username}" "$payload")
      if [ "$code" = "200" ]; then
        log "Updated '${username}' reply on ${name}#${issue_number}."
      else
        log "WARNING: updating reply by '${username}' returned HTTP ${code}:"
        cat /tmp/api_resp.json
      fi
      return 0
    fi
  fi

  payload=$(jq -n --arg body "$normalized_body" '{body:$body}')
  code=$(api POST "/repos/${owner}/${name}/issues/${issue_number}/comments?sudo=${username}" "$payload")
  if [ "$code" = "201" ]; then
    log "Added '${username}' reply to ${name}#${issue_number}."
  else
    log "WARNING: agent reply by '${username}' returned HTTP ${code}:"
    cat /tmp/api_resp.json
  fi
}

WORKDIR="$(mktemp -d)"

# ==========================================================================
# humanless-autopilot — retained autonomous development and maintenance E2E
# ==========================================================================
ensure_repo "humanless-autopilot" "人レスmodeが開発・レビュー・継続保守するローカルfirst障害ステータスボード"
put_file \
  "humanless-autopilot" \
  "README.md" \
  "/templates/humanless-autopilot/README.md" \
  "docs: define the autonomous PulseBoard product brief"
set_topics \
  "humanless-autopilot" \
  "space" \
  "cpu" \
  "humanless" \
  "humanless-ui" \
  "sample" \
  "autonomous-maintenance"

# ==========================================================================
# sample-model
# ==========================================================================
ensure_repo "sample-model" "A sample NyankoFace model repository"
set_topics "sample-model" "model"

cat > "${WORKDIR}/model_readme.md" <<'EOF'
---
license: apache-2.0
pipeline_tag: text-classification
tags:
  - nyankoface
  - sample
  - text-classification
---

```yaml
metadata
license: apache-2.0
pipeline_tag: text-classification
tags:
  - nyankoface
  - sample
  - text-classification
```

# sample-model

This is a **sample model repository** for NyankoFace, used to demonstrate the
HuggingFace-style model card format.

## Model description

A placeholder text-classification model. Replace this README and the model
weights (tracked via Git LFS) with your own.

## How to use

```bash
git clone http://localhost:8090/git/nyankoface/sample-model.git
```

## Training data

_Describe your training data here._

## License

Apache 2.0
EOF
put_file "sample-model" "README.md" "${WORKDIR}/model_readme.md" "Add model card"

cat > "${WORKDIR}/sample_model_config.json" <<'EOF'
{
  "architectures": ["NyankoFaceTextClassifier"],
  "model_type": "text-classification",
  "hidden_size": 256,
  "num_hidden_layers": 4,
  "num_attention_heads": 4,
  "id2label": {
    "0": "negative",
    "1": "neutral",
    "2": "positive"
  },
  "label2id": {
    "negative": 0,
    "neutral": 1,
    "positive": 2
  }
}
EOF
put_file "sample-model" "config.json" "${WORKDIR}/sample_model_config.json" "Add model config"

cat > "${WORKDIR}/sample_tokenizer_config.json" <<'EOF'
{
  "do_lower_case": true,
  "model_max_length": 512,
  "tokenizer_class": "NyankoFaceTokenizer"
}
EOF
put_file "sample-model" "tokenizer_config.json" "${WORKDIR}/sample_tokenizer_config.json" "Add tokenizer config"

cat > "${WORKDIR}/sample_model_index.json" <<'EOF'
{
  "_class_name": "NyankoFaceModelIndex",
  "pipeline_tag": "text-classification",
  "library_name": "transformers"
}
EOF
put_file "sample-model" "model_index.json" "${WORKDIR}/sample_model_index.json" "Add model index"

# ==========================================================================
# sample-dataset
# ==========================================================================
ensure_repo "sample-dataset" "A sample NyankoFace dataset repository"
set_topics "sample-dataset" "dataset"

cat > "${WORKDIR}/dataset_readme.md" <<'EOF'
---
license: cc-by-4.0
tags:
  - nyankoface
  - sample
  - tabular
---

```yaml
metadata
license: cc-by-4.0
tags:
  - nyankoface
  - sample
  - tabular
```

# sample-dataset

This is a **sample dataset repository** for NyankoFace.

## Dataset description

A tiny placeholder CSV dataset (`data.csv`) to demonstrate dataset repos on
NyankoFace.

## Usage

```bash
git clone http://localhost:8090/git/nyankoface/sample-dataset.git
```

## License

CC BY 4.0
EOF
put_file "sample-dataset" "README.md" "${WORKDIR}/dataset_readme.md" "Add dataset card"

cat > "${WORKDIR}/data.csv" <<'EOF'
id,text,label
1,"This product is amazing!",positive
2,"Terrible experience, would not recommend.",negative
3,"It's okay, nothing special.",neutral
4,"Best purchase I've made this year.",positive
5,"Completely broken on arrival.",negative
EOF
put_file "sample-dataset" "data.csv" "${WORKDIR}/data.csv" "Add sample data.csv"

cat > "${WORKDIR}/dataset_infos.json" <<'EOF'
{
  "default": {
    "description": "Tiny NyankoFace sentiment fixture",
    "features": {
      "id": "int64",
      "text": "string",
      "label": {
        "names": ["negative", "neutral", "positive"]
      }
    },
    "splits": {
      "train": {
        "num_examples": 5
      }
    }
  }
}
EOF
put_file "sample-dataset" "dataset_infos.json" "${WORKDIR}/dataset_infos.json" "Add dataset metadata"

mkdir -p "${WORKDIR}/sample_dataset_data"
cat > "${WORKDIR}/sample_dataset_data/train.csv" <<'EOF'
id,text,label
1,"This product is amazing!",positive
2,"Terrible experience, would not recommend.",negative
3,"It's okay, nothing special.",neutral
4,"Best purchase I've made this year.",positive
5,"Completely broken on arrival.",negative
EOF
put_file "sample-dataset" "data/train.csv" "${WORKDIR}/sample_dataset_data/train.csv" "Add train split"

cat > "${WORKDIR}/sample_dataset_data/test.csv" <<'EOF'
id,text,label
6,"Works exactly as expected.",positive
7,"Documentation was hard to follow.",negative
EOF
put_file "sample-dataset" "data/test.csv" "${WORKDIR}/sample_dataset_data/test.csv" "Add test split"

# ==========================================================================
# hello-space
# ==========================================================================
# Legacy synthetic Space definitions are intentionally disabled. They remain
# inside this branch only so existing installations can be migrated by the
# code immediately below without making this seed-script change unreadable.
if false; then
ensure_repo "hello-space" "A sample NyankoFace Gradio space"
set_topics "hello-space" "space"

cat > "${WORKDIR}/space_readme.md" <<'EOF'
---
license: apache-2.0
tags:
  - nyankoface
  - sample
  - gradio
---

# hello-space

This is a **sample Space repository** for NyankoFace, running a minimal Gradio
demo (`app.py`).

## Run locally

```bash
git clone http://localhost:8090/git/nyankoface/hello-space.git
cd hello-space
pip install -r requirements.txt
python app.py
```

On NyankoFace, click **"Run"** on this repo's page to launch it via
`spaces-runner`.
EOF
put_file "hello-space" "README.md" "${WORKDIR}/space_readme.md" "Add space card"

cat > "${WORKDIR}/app.py" <<'EOF'
import gradio as gr


def greet(name: str) -> str:
    name = name.strip() or "world"
    return f"Hello, {name}! Welcome to NyankoFace."


demo = gr.Interface(
    fn=greet,
    inputs=gr.Textbox(label="Your name", placeholder="Type your name..."),
    outputs=gr.Textbox(label="Greeting"),
    title="hello-space",
    description="A minimal NyankoFace sample Space.",
)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
EOF
put_file "hello-space" "app.py" "${WORKDIR}/app.py" "Add minimal gradio app"

cat > "${WORKDIR}/requirements.txt" <<'EOF'
gradio
EOF
put_file "hello-space" "requirements.txt" "${WORKDIR}/requirements.txt" "Add requirements.txt"

# ==========================================================================
# Additional Spaces: fill the directory grid with HF-like sample apps
# ==========================================================================
create_space_fixture() {
  local name="$1" title="$2" desc="$3" tag="$4"
  local readme_file="${WORKDIR}/${name}_README.md"
  local app_file="${WORKDIR}/${name}_app.py"
  local requirements_file="${WORKDIR}/${name}_requirements.txt"

  ensure_repo "$name" "$desc"
  set_topics "$name" "space" "$tag"

  cat > "$readme_file" <<EOF
---
title: ${title}
colorFrom: blue
colorTo: indigo
sdk: gradio
license: apache-2.0
tags:
  - nyankoface
  - ${tag}
---

# ${title}

${desc}

This fixture exists so the NyankoFace Spaces directory has realistic card density
and can be compared against Hugging Face Spaces screenshots.
EOF
  put_file "$name" "README.md" "$readme_file" "Add ${title} space card"

  cat > "$app_file" <<EOF
import gradio as gr


def run_demo(prompt: str) -> str:
    prompt = prompt.strip() or "NyankoFace"
    return f"{title} processed: {prompt}"


demo = gr.Interface(
    fn=run_demo,
    inputs=gr.Textbox(label="Input", placeholder="Describe what to process..."),
    outputs=gr.Textbox(label="Result"),
    title="${title}",
    description="${desc}",
)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
EOF
  put_file "$name" "app.py" "$app_file" "Add ${title} demo app"

  cat > "$requirements_file" <<'EOF'
gradio
EOF
  put_file "$name" "requirements.txt" "$requirements_file" "Add requirements.txt"
}

create_space_fixture "rampart-redaction" "Rampart" "On-device PII redaction by National Design Studio" "redaction"
create_space_fixture "face-anything" "FaceAnything" "4D face reconstruction and tracking from an image sequence" "vision"
create_space_fixture "scail2-animation" "SCAIL 2" "Unifying controlled character animation workflows" "animation"
create_space_fixture "sun-direction-flux" "Sun Direction Flux Klein" "Drag the sun around a 3D ball to relight outdoor photos" "image-generation"
create_space_fixture "unlimited-ocr" "Unlimited OCR" "Extract text from images and PDFs" "ocr"
create_space_fixture "gemma-avatar" "Gemma Avatar" "Talk to Gemma face to face with a synchronized avatar" "avatar"
create_space_fixture "pro-realism-edit-studio" "Pro Realism Edit Studio" "Powerful image editing with one or two input images" "image-editing"
create_space_fixture "wan-fast-preview" "Wan Fast Preview" "Generate a video from an image and a text prompt" "video-generation"
create_space_fixture "gemma-webgpu-kernels" "Gemma WebGPU Kernels" "Chat with a browser-side language model runtime" "webgpu"
create_space_fixture "protectbirds-vision" "ProtectBirds" "Detect and review field-camera wildlife events" "object-detection"
create_space_fixture "krea-lora-trainer" "Krea LoRA Trainer" "Train compact LoRA adapters on your image set" "training"
create_space_fixture "audio-clean-room" "Audio Clean Room" "Remove noise and level short spoken recordings" "audio"
create_space_fixture "doc-chat-compact" "Doc Chat Compact" "Ask questions over PDFs with a local retrieval index" "question-answering"
create_space_fixture "table-viz-lab" "Table Viz Lab" "Turn CSV files into quick charts and summaries" "data-visualization"

# ==========================================================================
# realtime-voice-space: larger HF-like Space fixture for UI comparison
# ==========================================================================
ensure_repo "realtime-voice-space" "HF-style realtime voice Space fixture with many files"
set_topics "realtime-voice-space" "space" "gradio" "realtime" "voice"

cat > "${WORKDIR}/realtime_readme.md" <<'EOF'
---
title: Realtime Voice Space
emoji: ""
colorFrom: blue
colorTo: green
sdk: docker
license: apache-2.0
tags:
  - nyankoface
  - realtime
  - voice
---

```yaml
metadata
title: Realtime Voice Space
colorFrom: blue
colorTo: green
sdk: docker
license: apache-2.0
tags:
  - nyankoface
  - realtime
  - voice
```

# realtime-voice-space

This repository is a larger NyankoFace Space fixture used to compare the
NyankoFace file browser aligned with Hugging Face's Spaces file UI.

It intentionally contains nested directories, frontend files, backend files,
and small configuration files so the file tree has enough density to validate
spacing, columns, commit messages, timestamps, and controls.
EOF
put_file "realtime-voice-space" "README.md" "${WORKDIR}/realtime_readme.md" "Rename visible title to NyankoFace Realtime"

cat > "${WORKDIR}/context.md" <<'EOF'
# Context

This fixture mimics a realtime browser application with a small WebSocket
backend and a frontend client.
EOF
put_file "realtime-voice-space" "CONTEXT.md" "${WORKDIR}/context.md" "Add waiting-queue UI and session-queue notes"

cat > "${WORKDIR}/design.md" <<'EOF'
# Design

- Keep the first viewport focused on the file list.
- Keep action buttons compact.
- Keep Git history, raw files, and blob viewing connected to the repository source of truth.
EOF
put_file "realtime-voice-space" "DESIGN.md" "${WORKDIR}/design.md" "Deploy replica from source HEAD"

cat > "${WORKDIR}/dockerignore" <<'EOF'
.git
.next
node_modules
__pycache__
.pytest_cache
dist
EOF
put_file "realtime-voice-space" ".dockerignore" "${WORKDIR}/dockerignore" "Deploy replica from source HEAD"

cat > "${WORKDIR}/gitattributes" <<'EOF'
*.bin filter=lfs diff=lfs merge=lfs -text
*.safetensors filter=lfs diff=lfs merge=lfs -text
EOF
put_file "realtime-voice-space" ".gitattributes" "${WORKDIR}/gitattributes" "Initial commit"

cat > "${WORKDIR}/gitignore" <<'EOF'
.env
.venv
node_modules
dist
EOF
put_file "realtime-voice-space" ".gitignore" "${WORKDIR}/gitignore" "Deploy replica from source HEAD"

cat > "${WORKDIR}/dockerfile" <<'EOF'
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "server.py"]
EOF
put_file "realtime-voice-space" "Dockerfile" "${WORKDIR}/dockerfile" "Deploy replica from source HEAD"

cat > "${WORKDIR}/requirements-realtime.txt" <<'EOF'
fastapi
uvicorn
websockets
numpy
EOF
put_file "realtime-voice-space" "requirements.txt" "${WORKDIR}/requirements-realtime.txt" "Deploy replica from source HEAD"

cat > "${WORKDIR}/auth.py" <<'EOF'
def allow_user(token: str | None) -> bool:
    return bool(token)
EOF
put_file "realtime-voice-space" "auth.py" "${WORKDIR}/auth.py" "Warm up queue copy: overhung sublime and fallback"

cat > "${WORKDIR}/limiter.py" <<'EOF'
from time import monotonic

WINDOW_SECONDS = 60
MAX_EVENTS = 120
_events: list[float] = []


def allow_event() -> bool:
    now = monotonic()
    while _events and now - _events[0] > WINDOW_SECONDS:
        _events.pop(0)
    if len(_events) >= MAX_EVENTS:
        return False
    _events.append(now)
    return True
EOF
put_file "realtime-voice-space" "limiter.py" "${WORKDIR}/limiter.py" "Deploy replica from source HEAD"

cat > "${WORKDIR}/server.py" <<'EOF'
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse

app = FastAPI()


@app.get("/")
async def index() -> HTMLResponse:
    with open("index.html", "r", encoding="utf-8") as fh:
        return HTMLResponse(fh.read())


@app.websocket("/ws")
async def websocket_endpoint(socket: WebSocket) -> None:
    await socket.accept()
    await socket.send_json({"status": "ready"})
    await socket.close()
EOF
put_file "realtime-voice-space" "server.py" "${WORKDIR}/server.py" "Add waiting-queue UI and session-queue plumbing"

cat > "${WORKDIR}/index.html" <<'EOF'
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Realtime Voice Space</title>
    <link rel="stylesheet" href="/style.css">
  </head>
  <body>
    <main>
      <h1>Realtime Voice Space</h1>
      <button id="connect">Connect</button>
      <pre id="log"></pre>
    </main>
    <script src="/main.js"></script>
  </body>
</html>
EOF
put_file "realtime-voice-space" "index.html" "${WORKDIR}/index.html" "Rename visible title to NyankoFace Realtime"

cat > "${WORKDIR}/main.js" <<'EOF'
const log = document.querySelector("#log");
const button = document.querySelector("#connect");

button.addEventListener("click", () => {
  const socket = new WebSocket(`${location.origin.replace("http", "ws")}/ws`);
  socket.addEventListener("message", (event) => {
    log.textContent = event.data;
  });
});
EOF
put_file "realtime-voice-space" "main.js" "${WORKDIR}/main.js" "Warm up queue copy: overhung sublime and fallback"

cat > "${WORKDIR}/style.css" <<'EOF'
body {
  margin: 0;
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
  background: #f8fafc;
  color: #111827;
}

main {
  max-width: 760px;
  margin: 80px auto;
  padding: 32px;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
}
EOF
put_file "realtime-voice-space" "style.css" "${WORKDIR}/style.css" "Warm up queue copy: overhung sublime and fallback"

cat > "${WORKDIR}/docs_readme.md" <<'EOF'
# Docs

Operational notes and deployment assumptions for the realtime fixture.
EOF
put_file "realtime-voice-space" "docs/README.md" "${WORKDIR}/docs_readme.md" "Deploy replica from source HEAD"

cat > "${WORKDIR}/ui_package.json" <<'EOF'
{
  "name": "nyankoface-realtime-ui",
  "private": true,
  "scripts": {
    "dev": "vite --host 0.0.0.0"
  },
  "dependencies": {
    "@vitejs/plugin-react": "latest",
    "vite": "latest"
  }
}
EOF
put_file "realtime-voice-space" "ui/package.json" "${WORKDIR}/ui_package.json" "Warm up queue copy: overhung sublime and fallback"

cat > "${WORKDIR}/worklet.js" <<'EOF'
class AudioMeterProcessor extends AudioWorkletProcessor {
  process() {
    return true;
  }
}

registerProcessor("audio-meter", AudioMeterProcessor);
EOF
put_file "realtime-voice-space" "worklets/audio-meter.js" "${WORKDIR}/worklet.js" "Add explicit join gate, your-turn state, and queue status"

cat > "${WORKDIR}/ws_server.py" <<'EOF'
async def handle_session(scope, receive, send):
    await send({"type": "websocket.accept"})
    await send({"type": "websocket.close"})
EOF
put_file "realtime-voice-space" "ws/server.py" "${WORKDIR}/ws_server.py" "Deploy replica from source HEAD"

ensure_issue "realtime-voice-space" \
  "Upload SamplePNGImage_100kbmb.png" \
  "Sample asset upload used to validate the discussion list layout and attachment-heavy workflow."
ensure_issue "realtime-voice-space" \
  "Can't get this demo to work locally with speech-to-speech" \
  "Local startup report for the realtime voice Space. Tracks setup notes, browser permissions, and WebSocket checks."
ensure_issue "realtime-voice-space" \
  "Can this work with 16 gb VRAM ?" \
  "Hardware sizing question for comparing model runtime requirements and queue behavior."
fi

# ==========================================================================
# Public CPU Spaces mirrored from Hugging Face
# ==========================================================================
# These sources were checked for all of the following before inclusion:
#   * public repository with an explicit MIT or Apache-2.0 license
#   * Hugging Face hardware request is cpu-basic (never ZeroGPU/GPU)
#   * Gradio app with no mandatory paid API key
# The original git content and README metadata are preserved verbatim.

delete_legacy_space() {
  local name="$1"
  local code
  code=$(api GET "/repos/${ORG_NAME}/${name}")
  if [ "$code" != "200" ]; then
    return 0
  fi
  code=$(api DELETE "/repos/${ORG_NAME}/${name}")
  if [ "$code" = "204" ]; then
    log "Deleted legacy synthetic Space '${name}'."
  else
    log "WARNING: deleting legacy Space '${name}' returned HTTP ${code}:"
    cat /tmp/api_resp.json
  fi
}

transfer_seed_space_if_needed() {
  local name="$1"
  local source_code target_code code attempt

  target_code=$(api GET "/repos/${SPACE_ORG_NAME}/${name}")
  if [ "$target_code" = "200" ]; then
    return 0
  fi

  source_code=$(api GET "/repos/${ORG_NAME}/${name}")
  if [ "$source_code" != "200" ]; then
    return 0
  fi

  log "Transferring seeded Space '${ORG_NAME}/${name}' to '${SPACE_ORG_NAME}'..."
  code=$(api POST "/repos/${ORG_NAME}/${name}/transfer" \
    "$(jq -n --arg owner "$SPACE_ORG_NAME" '{new_owner:$owner}')")
  if [ "$code" != "202" ]; then
    log "ERROR: transferring seeded Space '${ORG_NAME}/${name}' returned HTTP ${code}:"
    cat /tmp/api_resp.json
    exit 1
  fi

  for attempt in 1 2 3 4 5; do
    target_code=$(api GET "/repos/${SPACE_ORG_NAME}/${name}")
    if [ "$target_code" = "200" ]; then
      log "Transferred seeded Space to '${SPACE_ORG_NAME}/${name}'."
      return 0
    fi
    sleep 1
  done

  log "ERROR: transferred Space '${SPACE_ORG_NAME}/${name}' did not become readable."
  exit 1
}

import_hf_space() {
  local source="$1" name="$2" description="$3"
  local code clone_dir push_url attempt cloned

  transfer_seed_space_if_needed "$name"
  code=$(api GET "/repos/${SPACE_ORG_NAME}/${name}")
  if [ "$code" = "200" ]; then
    log "Imported Space '${SPACE_ORG_NAME}/${name}' already exists; keeping local changes."
    REPO_OWNER_CONTEXT="$SPACE_ORG_NAME" set_topics "$name" "space" "cpu" "huggingface-import"
    return 0
  fi

  clone_dir="${WORKDIR}/hf-${name}"
  rm -rf "$clone_dir"
  log "Cloning public CPU Space '${source}'..."
  # Forgejo rejects pushes from shallow repositories by default, so mirror the
  # complete (small, vetted) Space history rather than using --depth 1.
  cloned=0
  for attempt in 1 2 3; do
    if timeout "${HF_CLONE_TIMEOUT_SECONDS:-20}" git clone "https://huggingface.co/spaces/${source}" "$clone_dir"; then
      cloned=1
      break
    fi
    rm -rf "$clone_dir"
    log "WARNING: clone attempt ${attempt}/3 failed for '${source}'."
    sleep $((attempt * 2))
  done
  if [ "$cloned" != "1" ]; then
    # A temporary upstream outage must not prevent the local catalog, HTTPS
    # gateway, or visual QA from starting. The next idempotent seed run retries
    # this real public Space because no placeholder repository was created.
    log "WARNING: skipping unavailable upstream Space '${source}' after 3 attempts."
    return 0
  fi

  code=$(api POST "/orgs/${SPACE_ORG_NAME}/repos" "$(jq -n \
    --arg name "$name" --arg desc "$description" \
    '{name:$name, description:$desc, auto_init:false, private:false, default_branch:"main"}')")
  if [ "$code" != "201" ]; then
    log "ERROR: repo create for imported Space '${name}' returned HTTP ${code}:"
    cat /tmp/api_resp.json
    exit 1
  fi

  push_url="http://${NYANKOFACE_ADMIN_USER}:${TOKEN}@forgejo:3000/${SPACE_ORG_NAME}/${name}.git"
  git -C "$clone_dir" remote remove nyankoface 2>/dev/null || true
  git -C "$clone_dir" remote add nyankoface "$push_url"
  if ! git -C "$clone_dir" push nyankoface HEAD:main; then
    log "ERROR: failed to push imported Space '${source}' to '${name}'."
    api DELETE "/repos/${SPACE_ORG_NAME}/${name}" >/dev/null || true
    exit 1
  fi

  REPO_OWNER_CONTEXT="$SPACE_ORG_NAME" set_topics "$name" "space" "cpu" "huggingface-import"
  log "Imported '${source}' as '${SPACE_ORG_NAME}/${name}'."
}

# ------------------------------------------------------------------------
# Import a public GitHub repository with its real files and commit history.
# The NyankoFace catalog uses a normalized local `main` branch while retaining
# the upstream commit graph. Existing repositories are never overwritten.
# ------------------------------------------------------------------------
import_github_catalog_repo() {
  local source="$1" name="$2" kind="$3" branch="$4" description="$5" extra_topics_json="${6:-[]}" source_topic="${7:-sunwood-ai-labs}"
  local code clone_dir push_url
  local -a extra_topics=()
  mapfile -t extra_topics < <(printf '%s' "$extra_topics_json" | jq -r '.[]')

  code=$(api GET "/repos/${ORG_NAME}/${name}")
  if [ "$code" = "200" ]; then
    log "GitHub sample '${ORG_NAME}/${name}' already exists; keeping local changes."
    api PATCH "/repos/${ORG_NAME}/${name}" "$(jq -n --arg desc "$description" '{description:$desc}')" >/dev/null
    set_topics "$name" "$kind" "$source_topic" "github-import" "${extra_topics[@]}"
    return 0
  fi

  clone_dir="${WORKDIR}/github-${name}"
  rm -rf "$clone_dir"
  log "Cloning public ${kind} sample '${source}'..."
  if ! git clone --branch "$branch" --single-branch "$source" "$clone_dir"; then
    log "ERROR: failed to clone '${source}'."
    exit 1
  fi

  code=$(api POST "/orgs/${ORG_NAME}/repos" "$(jq -n \
    --arg name "$name" --arg desc "$description" \
    '{name:$name, description:$desc, auto_init:false, private:false, default_branch:"main"}')")
  if [ "$code" != "201" ]; then
    log "ERROR: repo create for GitHub sample '${name}' returned HTTP ${code}:"
    cat /tmp/api_resp.json
    exit 1
  fi

  push_url="http://${NYANKOFACE_ADMIN_USER}:${TOKEN}@forgejo:3000/${ORG_NAME}/${name}.git"
  git -C "$clone_dir" remote remove nyankoface 2>/dev/null || true
  git -C "$clone_dir" remote add nyankoface "$push_url"
  if ! git -C "$clone_dir" push nyankoface HEAD:main; then
    log "ERROR: failed to push GitHub sample '${source}' to '${name}'."
    api DELETE "/repos/${ORG_NAME}/${name}" >/dev/null || true
    exit 1
  fi

  set_topics "$name" "$kind" "$source_topic" "github-import" "${extra_topics[@]}"
  log "Imported '${source}' as '${ORG_NAME}/${name}' (${kind})."
}

# ------------------------------------------------------------------------
# Split the existing character-design bundle into one Forgejo repository per
# deliverable. Each character receives:
#
#   <id>-character-sheet  — one exported sheet, thumbnail, and metadata row
#   <id>-codex-pet        — one installable pet package with frames and QA
#
# The upstream bundle remains available as provenance, but loses the
# `character` topic so it cannot appear as a mixed virtual catalog entry.
# ------------------------------------------------------------------------
publish_split_character_repo() {
  local repo_dir="$1" name="$2" description="$3" format_topic="$4"
  local code push_url

  code=$(api GET "/repos/${ORG_NAME}/${name}")
  if [ "$code" = "200" ]; then
    api PATCH "/repos/${ORG_NAME}/${name}" "$(jq -n --arg desc "$description" '{description:$desc}')" >/dev/null
    set_topics "$name" "character" "$format_topic" "character-design-images" "split-repository" "qa"
    log "Split character repository '${ORG_NAME}/${name}' already exists; keeping repository history."
    return 0
  fi

  git -C "$repo_dir" init -b main >/dev/null
  git -C "$repo_dir" add .
  git -C "$repo_dir" \
    -c user.name="NyankoFace Catalog" \
    -c user.email="catalog@nyankoface.local" \
    commit -m "Split ${name} from character-design-images" >/dev/null

  code=$(api POST "/orgs/${ORG_NAME}/repos" "$(jq -n \
    --arg name "$name" --arg desc "$description" \
    '{name:$name,description:$desc,auto_init:false,private:false,default_branch:"main"}')")
  if [ "$code" != "201" ]; then
    log "ERROR: creating split character repository '${name}' returned HTTP ${code}:"
    cat /tmp/api_resp.json
    exit 1
  fi

  push_url="http://${NYANKOFACE_ADMIN_USER}:${TOKEN}@forgejo:3000/${ORG_NAME}/${name}.git"
  git -C "$repo_dir" remote add nyankoface "$push_url"
  if ! git -C "$repo_dir" push nyankoface main; then
    log "ERROR: failed to push split character repository '${name}'."
    api DELETE "/repos/${ORG_NAME}/${name}" >/dev/null || true
    exit 1
  fi
  set_topics "$name" "character" "$format_topic" "character-design-images" "split-repository" "qa"
  log "Published independent character repository '${ORG_NAME}/${name}'."
}

split_character_bundle() {
  local source="$1" bundle_name="$2" branch="$3" description="$4" extra_topics_json="${5:-[]}"
  local clone_dir code
  clone_dir="${WORKDIR}/github-${bundle_name}"
  rm -rf "$clone_dir"
  log "Cloning character bundle '${source}' for repository-level separation..."
  if ! git clone --branch "$branch" --single-branch "$source" "$clone_dir"; then
    log "ERROR: failed to clone character bundle '${source}'."
    exit 1
  fi

  # Preserve the original public source as provenance without presenting it as
  # a character entry. Existing local edits are intentionally retained.
  import_github_catalog_repo "$source" "$bundle_name" "character-bundle" "$branch" "$description" "$extra_topics_json"
  set_topics "$bundle_name" "character-source" "sunwood-ai-labs" "github-import" "eight-characters" "qa"

  local character_id display_name sheet_path sheet_repo pet_repo sheet_dir pet_dir sheet_description pet_description
  while IFS=',' read -r character_id display_name _variant _view _version _status _artist _source _rights _usage_scope sheet_path _notes; do
    [ "$character_id" = "character_id" ] && continue
    [ -n "$character_id" ] || continue

    sheet_repo="${character_id}-character-sheet"
    pet_repo="${character_id}-codex-pet"
    sheet_dir="${WORKDIR}/split-${sheet_repo}"
    pet_dir="${WORKDIR}/split-${pet_repo}"
    rm -rf "$sheet_dir" "$pet_dir"

    mkdir -p \
      "${sheet_dir}/assets/exports/${character_id}" \
      "${sheet_dir}/assets/thumbnails/${character_id}" \
      "${sheet_dir}/metadata"
    cp "${clone_dir}/${sheet_path}" "${sheet_dir}/assets/exports/${character_id}/"
    cp "${clone_dir}/assets/thumbnails/${character_id}/"* "${sheet_dir}/assets/thumbnails/${character_id}/"
    {
      head -n 1 "${clone_dir}/metadata/characters.csv"
      awk -F',' -v id="$character_id" '$1 == id' "${clone_dir}/metadata/characters.csv"
    } > "${sheet_dir}/metadata/characters.csv"
    cat > "${sheet_dir}/README.md" <<EOF
# ${display_name} Character Sheet

Independent character-sheet repository split from
[Sunwood AI Labs / character-design-images](${source%\.git}).

- Character ID: \`${character_id}\`
- Deliverable: character sheet
- Metadata: \`metadata/characters.csv\`
- Export: \`${sheet_path}\`
EOF
    sheet_description="${display_name} character sheet with export, thumbnail, and rights metadata"
    publish_split_character_repo "$sheet_dir" "$sheet_repo" "$sheet_description" "character-sheet"

    mkdir -p "$pet_dir"
    cp -R "${clone_dir}/assets/pets/${character_id}/." "$pet_dir/"
    mkdir -p "${pet_dir}/metadata"
    {
      head -n 1 "${clone_dir}/metadata/pets.csv"
      awk -F',' -v id="$character_id" '$1 == id' "${clone_dir}/metadata/pets.csv" \
        | sed "s#assets/pets/${character_id}/##g"
    } > "${pet_dir}/metadata/pets.csv"
    cat > "${pet_dir}/README.md" <<EOF
# ${display_name} Codex Pet

Independent installable Codex Pet repository split from
[Sunwood AI Labs / character-design-images](${source%\.git}).

- Character ID: \`${character_id}\`
- Manifest: \`pet.json\`
- Spritesheet: \`spritesheet.webp\`
- QA evidence: \`qa/\`
- Validation: \`final/validation.json\`
EOF
    pet_description="${display_name} installable Codex Pet with spritesheet, animation frames, and QA evidence"
    publish_split_character_repo "$pet_dir" "$pet_repo" "$pet_description" "codex-pet"
  done < "${clone_dir}/metadata/characters.csv"
}

import_sunwood_catalog() {
  if [ ! -f "$SUNWOOD_CATALOG" ]; then
    log "ERROR: Sunwood AI Labs catalog not found at '${SUNWOOD_CATALOG}'."
    exit 1
  fi

  local encoded entry source name kind branch description metadata_file extra_topics_json
  while IFS= read -r encoded; do
    entry=$(printf '%s' "$encoded" | base64 -d)
    source=$(printf '%s' "$entry" | jq -r '.source')
    name=$(printf '%s' "$entry" | jq -r '.name')
    kind=$(printf '%s' "$entry" | jq -r '.kind')
    branch=$(printf '%s' "$entry" | jq -r '.branch')
    description=$(printf '%s' "$entry" | jq -r '.description')
    extra_topics_json=$(printf '%s' "$entry" | jq -c '.topics // []')
    if [ "$kind" = "character-bundle" ] && [ "$(printf '%s' "$entry" | jq -r '.splitAssets // false')" = "true" ]; then
      split_character_bundle "$source" "$name" "$branch" "$description" "$extra_topics_json"
      continue
    fi
    import_github_catalog_repo "$source" "$name" "$kind" "$branch" "$description" "$extra_topics_json"
    if [ "$kind" = "skill" ]; then
      metadata_file="${WORKDIR}/${name}-skill.json"
      printf '%s' "$entry" | jq '{schemaVersion: 2, dependencies: (.dependencies // [])}' > "$metadata_file"
      put_file "$name" "skill.json" "$metadata_file" "Describe Skill relationships"
    fi
  done < <(jq -r '.entries[] | @base64' "$SUNWOOD_CATALOG")
}

# ------------------------------------------------------------------------
# Import public, CPU-runnable benchmark suites with their complete history.
# The catalog is separate from the Sunwood collection so provenance remains
# explicit and additional benchmark families can be added without UI changes.
# ------------------------------------------------------------------------
import_benchmark_catalog() {
  if [ ! -f "$BENCHMARK_CATALOG" ]; then
    log "ERROR: benchmark catalog not found at '${BENCHMARK_CATALOG}'."
    exit 1
  fi

  local encoded entry source name branch description extra_topics_json
  while IFS= read -r encoded; do
    entry=$(printf '%s' "$encoded" | base64 -d)
    source=$(printf '%s' "$entry" | jq -r '.source')
    name=$(printf '%s' "$entry" | jq -r '.name')
    branch=$(printf '%s' "$entry" | jq -r '.branch')
    description=$(printf '%s' "$entry" | jq -r '.description')
    extra_topics_json=$(printf '%s' "$entry" | jq -c '.topics // []')
    import_github_catalog_repo "$source" "$name" "benchmark" "$branch" "$description" "$extra_topics_json" "upstream-benchmark"
  done < <(jq -r '.entries[] | @base64' "$BENCHMARK_CATALOG")
}

# ------------------------------------------------------------------------
# Import one vetted public prompt into its own local Git repository.
#
# Keeping each prompt as a repository is intentional: prompt edits, branches,
# tags, forks, and rollbacks use the same Forgejo workflow as every other
# NyankoFace artifact.  PROMPT.md is the verbatim upstream source; README.md
# adds NyankoFace metadata and a durable provenance link.
# ------------------------------------------------------------------------
import_prompt_catalog_entry() {
  local name="$1" description="$2" version="$3" collection="$4" family="$5" license="$6" source_url="$7" source_repo="$8"
  local prompt_file readme_file source_file

  prompt_file="${WORKDIR}/${name}_PROMPT.md"
  readme_file="${WORKDIR}/${name}_README.md"
  source_file="${WORKDIR}/${name}_SOURCE.md"

  if ! curl -fsSL --retry 3 "$source_url" -o "$prompt_file"; then
    log "WARNING: could not download prompt source for '${name}': ${source_url}"
    return 0
  fi

  ensure_repo "$name" "$description"
  api PATCH "/repos/${ORG_NAME}/${name}" "$(jq -n --arg desc "$description" '{description:$desc}')" >/dev/null
  set_topics "$name" "prompt" "$collection" "$family" "version-${version}" "github-import"

  printf -- '---\nlicense: %s\ntags:\n  - prompt\n  - %s\n  - %s\n  - %s\n---\n\n# %s\n\n%s\n\n> **Prompt version: %s** — this repository is ready to branch, tag, compare, and fork in Forgejo.\n\n## Provenance\n\nImported verbatim from [%s](%s). The original project license is `%s`.\n\n## Prompt source\n\n' \
    "$license" "$collection" "$family" "version-${version}" "$name" "$description" "$version" "$source_repo" "$source_url" "$license" > "$readme_file"
  # Many prompt libraries store their own YAML front matter. Keep that source
  # intact in PROMPT.md, but remove only the leading block from the rendered
  # README so it does not become a giant Markdown heading in the card view.
  awk '
    NR == 1 && $0 == "---" { in_frontmatter = 1; next }
    in_frontmatter && $0 == "---" { in_frontmatter = 0; next }
    !in_frontmatter { print }
  ' "$prompt_file" >> "$readme_file"

  printf -- '# Source provenance\n\n- Source repository: [%s](%s)\n- Raw source: <%s>\n- Imported prompt version: `%s`\n- Source license: `%s`\n' \
    "$source_repo" "$source_repo" "$source_url" "$version" "$license" > "$source_file"

  put_file "$name" "PROMPT.md" "$prompt_file" "Import ${name} prompt source (${version})"
  put_file "$name" "README.md" "$readme_file" "Add ${name} prompt card (${version})"
  put_file "$name" "SOURCE.md" "$source_file" "Record ${name} source provenance"
  ensure_tag "$name" "$version" "Imported prompt version ${version}"
  log "Imported prompt '${name}' (${version}, ${collection})."
}

# Preserve repository history when moving from the old versioned slug to the
# stable prompt slug. Future versions only update the version topic and Git tag.
migrate_prompt_repository() {
  local legacy_name="$1" name="$2"
  local legacy_code current_code code

  if [ -z "$legacy_name" ] || [ "$legacy_name" = "$name" ]; then
    return 0
  fi

  legacy_code=$(api GET "/repos/${ORG_NAME}/${legacy_name}")
  if [ "$legacy_code" != "200" ]; then
    return 0
  fi

  current_code=$(api GET "/repos/${ORG_NAME}/${name}")
  if [ "$current_code" = "200" ]; then
    code=$(api DELETE "/repos/${ORG_NAME}/${legacy_name}")
    if [ "$code" = "204" ]; then
      log "Removed duplicate legacy prompt repository '${legacy_name}'."
    else
      log "ERROR: deleting duplicate prompt '${legacy_name}' returned HTTP ${code}:"
      cat /tmp/api_resp.json
      exit 1
    fi
    return 0
  fi

  code=$(api PATCH "/repos/${ORG_NAME}/${legacy_name}" "$(jq -n --arg name "$name" '{name:$name}')")
  if [ "$code" != "200" ]; then
    log "ERROR: renaming prompt '${legacy_name}' to '${name}' returned HTTP ${code}:"
    cat /tmp/api_resp.json
    exit 1
  fi
  log "Renamed prompt repository '${legacy_name}' to stable slug '${name}'."
}

import_prompt_catalog() {
  if [ ! -f "$PROMPT_CATALOG" ]; then
    log "ERROR: prompt catalog not found at '${PROMPT_CATALOG}'."
    exit 1
  fi

  local encoded entry name legacy_name description version collection family license source_url source_repo
  local revision_encoded revision revision_version revision_description revision_source_url
  while IFS= read -r encoded; do
    entry=$(printf '%s' "$encoded" | base64 -d)
    name=$(printf '%s' "$entry" | jq -r '.name')
    legacy_name=$(printf '%s' "$entry" | jq -r '.legacyName // empty')
    description=$(printf '%s' "$entry" | jq -r '.description')
    version=$(printf '%s' "$entry" | jq -r '.version')
    collection=$(printf '%s' "$entry" | jq -r '.collection')
    family=$(printf '%s' "$entry" | jq -r '.family')
    license=$(printf '%s' "$entry" | jq -r '.license')
    source_url=$(printf '%s' "$entry" | jq -r '.sourceUrl')
    source_repo=$(printf '%s' "$entry" | jq -r '.sourceRepo')
    migrate_prompt_repository "$legacy_name" "$name"

    while IFS= read -r revision_encoded; do
      revision=$(printf '%s' "$revision_encoded" | base64 -d)
      revision_version=$(printf '%s' "$revision" | jq -r '.version')
      revision_description=$(printf '%s' "$revision" | jq -r '.description // empty')
      revision_source_url=$(printf '%s' "$revision" | jq -r '.sourceUrl')
      if repo_has_tag "$name" "$revision_version"; then
        log "Historical prompt tag '${revision_version}' already exists on '${name}'."
        continue
      fi
      import_prompt_catalog_entry "$name" "${revision_description:-$description}" "$revision_version" "$collection" "$family" "$license" "$revision_source_url" "$source_repo"
    done < <(printf '%s' "$entry" | jq -r '.revisions[]? | @base64')

    import_prompt_catalog_entry "$name" "$description" "$version" "$collection" "$family" "$license" "$source_url" "$source_repo"
  done < <(jq -r '.entries[] | @base64' "$PROMPT_CATALOG")
}

for legacy in \
  hello-space realtime-voice-space rampart-redaction face-anything \
  scail2-animation sun-direction-flux unlimited-ocr gemma-avatar \
  pro-realism-edit-studio wan-fast-preview gemma-webgpu-kernels \
  protectbirds-vision krea-lora-trainer audio-clean-room \
  doc-chat-compact table-viz-lab; do
  delete_legacy_space "$legacy"
done

# Link-type Space: opens the configured website instead of building or
# embedding a Docker application.
transfer_seed_space_if_needed "nyankoface-documentation"
ensure_repo_for_org "$SPACE_ORG_NAME" "nyankoface-documentation" \
  "Open the published NyankoFace documentation directly from the Spaces catalog"
REPO_OWNER_CONTEXT="$SPACE_ORG_NAME" set_topics \
  "nyankoface-documentation" "space" "external-site" "documentation"
REPO_OWNER_CONTEXT="$SPACE_ORG_NAME" put_file "nyankoface-documentation" "README.md" \
  "/templates/external-link-space/README.md" \
  "Add external-link Space metadata"

import_hf_space "m-ric/notebook_to_markdown" \
  "notebook-to-markdown" "Convert Jupyter notebooks to Markdown"
import_hf_space "the-walking-fish/Whisper-JSON-to-SRT-Converter" \
  "whisper-json-to-srt" "Convert Whisper JSON transcripts to SRT subtitles"
import_hf_space "GeneralGost/Lora-Metadata_Editor" \
  "lora-metadata-editor" "Inspect and edit LoRA safetensors metadata"
import_hf_space "KAARIN/Apply_Filter_To_Your_Image" \
  "apply-image-filter" "Apply OpenCV filters to an uploaded image"
import_hf_space "moritalous/url-to-markdown" \
  "url-to-markdown" "Convert a public web page to Markdown"
import_hf_space "rassien/Image_filter" \
  "image-filter" "Experiment with local image filters"
import_hf_space "Threadbourne/metadata" \
  "image-metadata-viewer" "Read image metadata locally"
import_hf_space "OldKingMeister/UUID-Generator" \
  "uuid-generator" "Generate and download UUID lists"
import_hf_space "JohnTan38/calculator" \
  "calculator" "A small interactive calculator"
import_hf_space "tlam/metadata" \
  "image-metadata-inspector" "Inspect image EXIF and metadata locally"
import_hf_space "nanom/verb_tense_converter" \
  "verb-tense-converter" "Convert English verb tenses locally"
import_hf_space "nakas/360_metadata_image_injector" \
  "panorama-metadata-injector" "Inject 360-degree panorama metadata into images"
import_hf_space "meebox/qrcode" \
  "qr-code-generator" "Generate QR codes locally"
REPO_OWNER_CONTEXT="$SPACE_ORG_NAME"
ensure_issue "qr-code-generator" \
  "How do I run this Space entirely offline?" \
  "This NyankoFace community thread collects the local Docker startup steps and confirms that QR generation works without an external API."
ensure_issue "qr-code-generator" \
  "Add SVG download alongside PNG" \
  "Track an optional vector export for workflows that need sharp QR codes in print and documentation."
ensure_issue "qr-code-generator" \
  "Document QR error-correction settings" \
  "Explain the available error-correction levels and when to choose each one in the mirrored CPU Space."
ensure_issue "qr-code-generator" \
  "Verify Community Markdown rendering" \
  "Use a realistic review thread to verify that rich Markdown remains readable on desktop and mobile Community pages."
ensure_agent_comment "qr-code-generator" \
  "How do I run this Space entirely offline?" \
  "luna-scout" "offline-research" \
  "I checked the mirrored app. QR generation stays inside the local Gradio container and does not call an external inference API. After the image has been built, QR creation works offline. I would document two quick checks: container health and a successful PNG generation."
ensure_agent_comment "qr-code-generator" \
  "How do I run this Space entirely offline?" \
  "patch-orbit" "offline-implementation" \
  "Thanks, @luna-scout. I reproduced that flow with **docker compose up -d**: open the Space from NyankoFace, enter a short URL, and confirm that the PNG preview appears. I will keep it CPU-only and avoid adding another service for this sample."
ensure_agent_comment "qr-code-generator" \
  "How do I run this Space entirely offline?" \
  "mikan-reviewer" "offline-review" \
  "Looks good to me. One wording caveat: the first image build may still need network access to download dependencies. If the README separates build-time downloads from offline runtime behavior, I am happy with this."
ensure_agent_comment "qr-code-generator" \
  "Add SVG download alongside PNG" \
  "patch-orbit" "svg-proposal" \
  "I can take this. I will generate SVG from the same normalized payload used for PNG and expose two clearly labeled download actions. Sharing one payload path should prevent the preview and exported vector from drifting apart."
ensure_agent_comment "qr-code-generator" \
  "Add SVG download alongside PNG" \
  "mikan-reviewer" "svg-review" \
  "That approach makes sense. Before merging, please scan a resized SVG and give each download button an explicit accessible name. Those two checks should cover print use and keyboard or screen-reader use."
ensure_agent_comment "qr-code-generator" \
  "Document QR error-correction settings" \
  "luna-scout" "ecc-research" \
  "I checked the four levels. A compact L, M, Q, and H table should show approximate recovery capacity alongside the increase in QR density. For practical guidance, M is a reasonable default and H is useful when a logo overlaps part of the code."
ensure_agent_comment "qr-code-generator" \
  "Document QR error-correction settings" \
  "mikan-reviewer" "ecc-review" \
  "Agreed. Let us label the percentages as approximate and add a scan test to each example; a QR code can look fine and still fail to scan."
ensure_agent_comment "qr-code-generator" \
  "Verify Community Markdown rendering" \
  "luna-scout" "markdown-research" \
  "$(cat <<'EOF'
> Goal: confirm that a technical review stays readable without flattening its structure.

I checked the renderer with a short research pass:

- inline paths such as `README.md` and `docker-compose.yml`;
- **strong emphasis**, *supporting emphasis*, and ~~superseded wording~~;
- an external reference to the [Forgejo Markdown guide](https://forgejo.org/docs/latest/user/markdown/).

Suggested verification order:

1. Open the discussion on desktop.
2. Repeat at a 390 px mobile width.
3. Confirm that code and tables do not create horizontal page overflow.
EOF
)"
ensure_agent_comment "qr-code-generator" \
  "Verify Community Markdown rendering" \
  "patch-orbit" "markdown-implementation" \
  "$(cat <<'EOF'
Thanks, @luna-scout. I can turn that into a repeatable smoke check.

```bash
docker compose up -d
curl -kfsS https://localhost:8443/git/seraphim-labs/qr-code-generator/issues/4
```

Implementation checklist:

- [x] Seed the discussion through the Forgejo API.
- [x] Keep every comment idempotent with a hidden marker.
- [ ] Re-check the narrow mobile layout after any theme change.

The expected catalog change is intentionally small:

```diff
+ Community Markdown fixture
+ Desktop and mobile visual assertions
```
EOF
)"
ensure_agent_comment "qr-code-generator" \
  "Verify Community Markdown rendering" \
  "mikan-reviewer" "markdown-review" \
  "$(cat <<'EOF'
The structure reads well. I reviewed the result against this matrix:

| Check | Expected result | Status |
| --- | --- | :---: |
| Quote | Visually separated from the reply | ✅ |
| Code block | Scrolls inside the block if needed | ✅ |
| Task list | Checked and open items remain distinct | ✅ |
| Table | Stays readable without page overflow | ✅ |

<details>
<summary>Reviewer note</summary>

Keep the sample technical and concise; it should demonstrate formatting without looking like placeholder text.

</details>

**Approved with one follow-up:** keep this route in recurring Visual QA so a future theme update cannot silently break the Markdown layout.
EOF
)"
unset REPO_OWNER_CONTEXT
import_hf_space "umuth/image-metadata-editor" \
  "image-metadata-editor" "View and edit common image metadata"
import_hf_space "NeuralFalcon/Remove-Silence-From-Audio" \
  "remove-silence-audio" "Remove silent sections from audio using local FFmpeg"
import_hf_space "tregu0458/image_converter_for_patent" \
  "patent-image-converter" "Convert images for patent-document workflows"

# ==========================================================================
# vision-transformer-mini: larger model fixture
# ==========================================================================
ensure_repo "vision-transformer-mini" "Model fixture with config, tokenizer, and nested assets"
set_topics "vision-transformer-mini" "model" "vision" "transformer"

cat > "${WORKDIR}/vit_readme.md" <<'EOF'
---
license: apache-2.0
pipeline_tag: image-classification
tags:
  - nyankoface
  - vision
  - transformer
---

# vision-transformer-mini

Small model fixture for testing NyankoFace model repository pages.
EOF
put_file "vision-transformer-mini" "README.md" "${WORKDIR}/vit_readme.md" "Add model card"

cat > "${WORKDIR}/config.json" <<'EOF'
{
  "architectures": ["NyankoFaceVisionTransformer"],
  "hidden_size": 384,
  "num_attention_heads": 6,
  "num_hidden_layers": 6,
  "image_size": 224,
  "patch_size": 16
}
EOF
put_file "vision-transformer-mini" "config.json" "${WORKDIR}/config.json" "Add model configuration"

cat > "${WORKDIR}/preprocessor_config.json" <<'EOF'
{
  "do_resize": true,
  "size": {"height": 224, "width": 224},
  "do_normalize": true
}
EOF
put_file "vision-transformer-mini" "preprocessor_config.json" "${WORKDIR}/preprocessor_config.json" "Add preprocessing config"

cat > "${WORKDIR}/model_index.json" <<'EOF'
{
  "_class_name": "NyankoFaceModelIndex",
  "model_type": "image-classification"
}
EOF
put_file "vision-transformer-mini" "model_index.json" "${WORKDIR}/model_index.json" "Add model index"

cat > "${WORKDIR}/training_args.json" <<'EOF'
{
  "epochs": 3,
  "learning_rate": 0.00003,
  "batch_size": 32
}
EOF
put_file "vision-transformer-mini" "training/training_args.json" "${WORKDIR}/training_args.json" "Add training arguments"

# ==========================================================================
# multilingual-text-dataset: larger dataset fixture
# ==========================================================================
ensure_repo "multilingual-text-dataset" "Dataset fixture with data splits and metadata"
set_topics "multilingual-text-dataset" "dataset" "text" "multilingual"

cat > "${WORKDIR}/multi_dataset_readme.md" <<'EOF'
---
license: cc-by-4.0
tags:
  - nyankoface
  - text
  - multilingual
---

# multilingual-text-dataset

Dataset fixture for validating dataset file trees and metadata rendering.
EOF
put_file "multilingual-text-dataset" "README.md" "${WORKDIR}/multi_dataset_readme.md" "Add dataset card"

cat > "${WORKDIR}/dataset_infos.json" <<'EOF'
{
  "default": {
    "description": "Tiny multilingual text classification fixture",
    "features": {
      "id": "string",
      "text": "string",
      "language": "string",
      "label": "string"
    }
  }
}
EOF
put_file "multilingual-text-dataset" "dataset_infos.json" "${WORKDIR}/dataset_infos.json" "Add dataset infos"

cat > "${WORKDIR}/train.csv" <<'EOF'
id,text,language,label
1,hello world,en,greeting
2,bonjour le monde,fr,greeting
3,hola mundo,es,greeting
EOF
put_file "multilingual-text-dataset" "data/train.csv" "${WORKDIR}/train.csv" "Add train split"

cat > "${WORKDIR}/validation.csv" <<'EOF'
id,text,language,label
4,good night,en,farewell
5,bonne nuit,fr,farewell
EOF
put_file "multilingual-text-dataset" "data/validation.csv" "${WORKDIR}/validation.csv" "Add validation split"

cat > "${WORKDIR}/test.csv" <<'EOF'
id,text,language,label
6,buenas noches,es,farewell
EOF
put_file "multilingual-text-dataset" "data/test.csv" "${WORKDIR}/test.csv" "Add test split"

# ==========================================================================
# Directory-density fixtures: enough public repositories to make /models and
# /datasets read like the Hugging Face index instead of a tiny demo list.
# ==========================================================================
create_model_fixture() {
  local name="$1" title="$2" desc="$3" pipeline="$4" tag1="$5" tag2="${6:-}"
  ensure_repo "$name" "$desc"
  if [ -n "$tag2" ]; then
    set_topics "$name" "model" "$tag1" "$tag2"
  else
    set_topics "$name" "model" "$tag1"
  fi

  cat > "${WORKDIR}/${name}_README.md" <<EOF
---
license: apache-2.0
pipeline_tag: ${pipeline}
tags:
  - nyankoface
  - ${tag1}
EOF
  if [ -n "$tag2" ]; then
    cat >> "${WORKDIR}/${name}_README.md" <<EOF
  - ${tag2}
EOF
  fi
  cat >> "${WORKDIR}/${name}_README.md" <<EOF
---

# ${title}

${desc}

This fixture is intentionally small, but it includes enough metadata for
NyankoFace model index and file-tree UI comparisons.
EOF
  put_file "$name" "README.md" "${WORKDIR}/${name}_README.md" "Add model card"

  cat > "${WORKDIR}/${name}_config.json" <<EOF
{
  "model_type": "${pipeline}",
  "hidden_size": 768,
  "num_hidden_layers": 12,
  "nyankoface_fixture": true
}
EOF
  put_file "$name" "config.json" "${WORKDIR}/${name}_config.json" "Add model config"

  cat > "${WORKDIR}/${name}_generation_config.json" <<EOF
{
  "temperature": 0.7,
  "top_p": 0.9,
  "max_new_tokens": 256
}
EOF
  put_file "$name" "generation_config.json" "${WORKDIR}/${name}_generation_config.json" "Add generation config"
}

create_dataset_fixture() {
  local name="$1" title="$2" desc="$3" modality="$4" tag2="${5:-}"
  ensure_repo "$name" "$desc"
  if [ -n "$tag2" ]; then
    set_topics "$name" "dataset" "$modality" "$tag2"
  else
    set_topics "$name" "dataset" "$modality"
  fi

  cat > "${WORKDIR}/${name}_README.md" <<EOF
---
license: cc-by-4.0
tags:
  - nyankoface
  - ${modality}
EOF
  if [ -n "$tag2" ]; then
    cat >> "${WORKDIR}/${name}_README.md" <<EOF
  - ${tag2}
EOF
  fi
  cat >> "${WORKDIR}/${name}_README.md" <<EOF
---

# ${title}

${desc}

Small dataset fixture for NyankoFace directory, card, and file-tree comparison.
EOF
  put_file "$name" "README.md" "${WORKDIR}/${name}_README.md" "Add dataset card"

  cat > "${WORKDIR}/${name}_infos.json" <<EOF
{
  "default": {
    "description": "${desc}",
    "features": {
      "id": "string",
      "text": "string",
      "label": "string"
    }
  }
}
EOF
  put_file "$name" "dataset_infos.json" "${WORKDIR}/${name}_infos.json" "Add dataset infos"

  cat > "${WORKDIR}/${name}_train.csv" <<EOF
id,text,label
1,"NyankoFace fixture row one",alpha
2,"NyankoFace fixture row two",beta
3,"NyankoFace fixture row three",gamma
EOF
  put_file "$name" "data/train.csv" "${WORKDIR}/${name}_train.csv" "Add train split"
}

create_model_fixture "qwen-agent-mini" "Qwen Agent Mini" "Compact agentic language model fixture with tool-use metadata" "text-generation" "text-generation" "agent"
create_model_fixture "ocr-layout-tiny" "OCR Layout Tiny" "Document OCR model fixture for image-to-text repository lists" "image-to-text" "ocr" "document"
create_model_fixture "speech-synth-lite" "Speech Synth Lite" "Small text-to-speech fixture with generation settings" "text-to-speech" "audio" "speech"
create_model_fixture "embedding-reranker-base" "Embedding Reranker Base" "Retrieval reranking fixture with compact config files" "feature-extraction" "embedding" "reranker"
create_model_fixture "diffusion-sketch-control" "Diffusion Sketch Control" "Image generation fixture with control metadata" "text-to-image" "diffusion" "image-generation"
create_model_fixture "tabular-risk-scorer" "Tabular Risk Scorer" "Tabular classification model fixture for enterprise-style cards" "tabular-classification" "tabular" "classification"
create_model_fixture "code-assistant-small" "Code Assistant Small" "Code generation fixture with minimal tokenizer metadata" "text-generation" "code" "assistant"
create_model_fixture "japanese-summarizer-mini" "Japanese Summarizer Mini" "Summarization fixture for multilingual model browsing" "summarization" "multilingual" "summarization"
create_model_fixture "vision-captioner-lite" "Vision Captioner Lite" "Image captioning fixture with processor configuration" "image-to-text" "vision" "captioning"
create_model_fixture "audio-event-detector" "Audio Event Detector" "Audio classification fixture with simple preprocessing metadata" "audio-classification" "audio" "classification"
create_model_fixture "robot-policy-tiny" "Robot Policy Tiny" "Policy model fixture for robotics and embodied AI browsing" "reinforcement-learning" "robotics" "policy"
create_model_fixture "medical-ner-base" "Medical NER Base" "Token classification fixture for biomedical entities" "token-classification" "medical" "ner"

create_dataset_fixture "web-agent-traces" "Web Agent Traces" "Synthetic browser-agent trajectories with actions and observations" "traces" "agent"
create_dataset_fixture "document-ocr-benchmark" "Document OCR Benchmark" "Tiny OCR benchmark fixture with page-level labels" "document" "ocr"
create_dataset_fixture "voice-command-intents" "Voice Command Intents" "Short utterance intent dataset fixture for audio apps" "audio" "speech"
create_dataset_fixture "product-review-ja-en" "Product Review JA EN" "Bilingual product review classification fixture" "text" "multilingual"
create_dataset_fixture "robot-demo-rollouts" "Robot Demo Rollouts" "Small robotics rollout dataset fixture" "video" "robotics"
create_dataset_fixture "financial-news-signals" "Financial News Signals" "Financial headline signal classification fixture" "text" "finance"
create_dataset_fixture "image-edit-prompts" "Image Edit Prompts" "Instruction dataset fixture for image editing tasks" "image" "editing"
create_dataset_fixture "table-question-answering" "Table Question Answering" "Tabular QA fixture with small CSV splits" "tabular" "qa"

# ------------------------------------------------------------------------
# Git-backed knowledge library. Every publication is an article. One
# repository belongs to one person or team, and reusable topics classify
# articles without splitting them across purpose-specific directories.
# ------------------------------------------------------------------------
ensure_repo "nyankoface-knowledge" "NyankoFace team's articles, Wiki notes, guides, and references"
set_topics "nyankoface-knowledge" "doc" "knowledge" "markdown" "publication"

cat > "${WORKDIR}/knowledge_repo_readme.md" <<'EOF'
# NyankoFace ナレッジ

NyankoFaceチームがGitで管理するナレッジ公開リポジトリです。

## 記事を追加する

Store every publication in `articles/{slug}.md`. Classify it with as many
reusable topics as necessary:

- `news` for updates and community briefs
- `how-to` for repeatable steps and checklists
- `reference` for stable specifications and shared concepts
- `benchmark` for evaluation results
- `research` for investigations and field notes

Add front matter to every file:

```yaml
---
title: 私の調査メモ
emoji: "🔬"
topics: [research, local-ai, reference]
published: true
---
```

NyankoFaceは`articles/`の公開対象を`/docs`へ集約します。すべて記事として扱い、
`topics`でニュース、手順、参照情報、調査などを横断的に分類します。
通常のGitとプルリクエストの流れで編集・レビューできます。

## 公開フロー

```mermaid
flowchart LR
    Author[Markdownを編集] --> Forgejo[Forgejoへpush]
    Forgejo --> Catalog[NyankoFaceが収集]
    Catalog --> Reader[記事として公開]
```
EOF
put_file "nyankoface-knowledge" "README.md" "${WORKDIR}/knowledge_repo_readme.md" "Explain the knowledge publication format"

create_doc_fixture() {
  local name="$1" description="$2" format="$3" tag1="$4" tag2="$5" source_file="$6"
  local category=""
  if [ "$format" = "procedure" ]; then category="how-to"; fi
  if [ "$format" = "wiki" ]; then category="reference"; fi
  if [ "$format" = "news" ]; then category="news"; fi
  local staged_file="${WORKDIR}/knowledge_${name}.md"
  local topic_list="[$tag1, $tag2]"
  if [ -n "$category" ]; then topic_list="[$category, $tag1, $tag2]"; fi
  awk -v topic_list="$topic_list" -v description="$description" '
    NR == 1 && $0 == "---" {
      print
      print "topics: " topic_list
      print "description: \"" description "\""
      print "published: true"
      next
    }
    { print }
  ' "$source_file" > "$staged_file"
  put_file "nyankoface-knowledge" "articles/${name}.md" "$staged_file" "Publish article: ${name}"
  delete_file "nyankoface-knowledge" "procedures/${name}.md" "Unify knowledge under articles/"
  delete_file "nyankoface-knowledge" "wiki/${name}.md" "Unify knowledge under articles/"
  delete_file "nyankoface-knowledge" "news/${name}.md" "Unify knowledge under articles/"
}

cat > "${WORKDIR}/doc_local_first.md" <<'EOF'
---
license: MIT
tags: [architecture, local-first, forgejo]
---

# ローカルAIハブが必要な理由

NyankoFaceはGit履歴を信頼できる情報源とし、Dockerを実行境界として扱います。ホスト型カタログへ所有権を渡さず、ワークステーション、研究室のサーバー、信頼できるLAN上でコミュニティハブを運用できます。

## 制約が生む利点

すべての成果物はリポジトリとして残ります。モデル、データセット、Space、Skill、MCPサーバー、プロンプト、ドキュメントが、ブランチ、レビュー、権限、永続的な履歴を共有できます。

## 何が変わるか

- カタログ上の説明を、根拠となるファイルからすぐ確認できる
- コードと同じように、知識も調査・フォークできる
- オフラインやプライベートネットワークを正式な運用形態として扱える

> ローカルファーストは孤立ではありません。所有権の境界を自分たちで決める設計です。
EOF
create_doc_fixture "local-first-ai-hub" "Gitで管理する知識が、ローカルAIコミュニティを長く支える理由" "article" "architecture" "local-first" "${WORKDIR}/doc_local_first.md"

cat > "${WORKDIR}/doc_news_knowledge_directory.md" <<'EOF'
---
license: MIT
emoji: "📰"
tags: [news, release, knowledge]
---

# Knowledge一覧をSpaces型のカードUIへ刷新

NyankoFaceのKnowledge一覧を、Spacesと同じ情報密度で探せるディレクトリへ刷新しました。

## 今回の更新

- 大型ヒーローを廃止し、検索・カテゴリ・並び順・カード一覧を上部へ集約
- すべての記事を、ニュース、手順、参照情報などのタグで分類
- 記事ごとの絵文字をカード背景の透かしとして表示
- Standard、Solarpunk、Cyberpunkの各テーマでコントラストを検証

公開済みナレッジは、形式、トピック、閲覧数、更新日時から探せます。ニュースも通常のMarkdownとGit履歴で編集・レビューできます。
EOF
create_doc_fixture "knowledge-directory-refresh" "Knowledge一覧のカードUI、ニュースカテゴリ、記事別絵文字を公開" "news" "news" "release" "${WORKDIR}/doc_news_knowledge_directory.md"

cat > "${WORKDIR}/doc_news_agent_workflow.md" <<'EOF'
---
license: MIT
emoji: "📣"
tags: [news, agents, automation]
---

# 専門エージェント連携の更新

NyankoFaceの自動メンテナンスでは、メンテナーがデザイン、コーディング、ドキュメント、レビューの専門エージェントへ作業を委任できます。

## 変わったこと

- 専門エージェントは独立アカウントとして会話とコミットを記録
- Issueのメンションから担当作業を開始
- 実装者とは別のレビューエージェントが現在のhead SHAを検証
- 条件を満たしたプルリクエストは自動マージ可能

誰が何を判断したかをIssueとプルリクエストから追跡でき、見えない自動処理にしないことを重視しています。
EOF
create_doc_fixture "specialist-agent-workflow-update" "専門エージェントの委任、レビュー、自動マージ運用を更新" "news" "news" "agents" "${WORKDIR}/doc_news_agent_workflow.md"

cat > "${WORKDIR}/doc_platform_atlas.md" <<'EOF'
---
license: MIT
tags: [wiki, architecture, routes]
---

# NyankoFaceプラットフォーム全体図

公開画面と、その責務を担当するサービスの関係をまとめたWikiです。

| 画面・機能 | 担当 | 永続データ |
|---|---|---|
| カタログとリポジトリカード | Frontend | Forgejoリポジトリ |
| Issue、プルリクエスト、ID | Forgejo | Forgejoボリューム |
| 実行中のSpace | Spaces Runner | Dockerイメージと実行情報 |
| 公開Pages | Spaces Runner | リポジトリのブランチとファイル |
| 自動メンテナンス | Maintenance Agent | IssueとPRの会話 |

## 境界をたどる

GatewayはTLS終端とリクエストの振り分けを担当します。リポジトリデータの所有や任意アプリのビルドは行いません。責務を分離することで、運用者がリスクと復旧方法を判断しやすくしています。
EOF
create_doc_fixture "platform-knowledge-atlas" "NyankoFaceのサービス、ルート、状態をつなぐWikiマップ" "wiki" "architecture" "routes" "${WORKDIR}/doc_platform_atlas.md"

cat > "${WORKDIR}/doc_mermaid_rendering_lab.md" <<'EOF'
---
license: MIT
emoji: "🧜"
tags: [mermaid, markdown, diagrams, visual-qa]
---

# Mermaid図の描画検証

NyankoFaceのMarkdown rendererが、代表的なMermaid構文を図として安全に描画できることを確認する検証記事です。

## Flowchart

```mermaid
flowchart LR
    Markdown[Markdown file] --> Parser[Marked parser]
    Parser --> Mermaid[Mermaid renderer]
    Mermaid --> Theme{NyankoFace theme}
    Theme -->|Standard| Light[Neutral diagram]
    Theme -->|Solarpunk| Green[Organic diagram]
    Theme -->|Cyberpunk| Neon[Neon diagram]
```

## Sequence diagram

```mermaid
sequenceDiagram
    participant Browser
    participant NyankoFace
    participant Forgejo
    Browser->>NyankoFace: 記事を開く
    NyankoFace->>Forgejo: Markdownを取得
    Forgejo-->>NyankoFace: source
    NyankoFace-->>Browser: HTMLとMermaid source
    Browser->>Browser: themeに合わせてSVG化
```

## State diagram

```mermaid
stateDiagram-v2
    [*] --> Loading
    Loading --> Rendered: valid syntax
    Loading --> Fallback: invalid syntax
    Rendered --> Loading: theme changed
    Fallback --> [*]
```

## Class diagram

```mermaid
classDiagram
    class MarkdownBody {
      +html string
      +className string
      +renderMermaid()
    }
    class ThemeSelector {
      +theme string
      +applyTheme()
    }
    ThemeSelector --> MarkdownBody : triggers redraw
```

## Pie chart

```mermaid
pie showData
    title Mermaid QA coverage
    "Repository README" : 1
    "Knowledge article" : 1
    "Desktop themes" : 3
    "Mobile themes" : 3
```

## 構文エラー時のfallback

次のblockは意図的に不正です。ページ全体を壊さず、sourceと説明を表示することが期待値です。

```mermaid
flowchart LR
    Broken[
```
EOF
create_doc_fixture "mermaid-rendering-lab" "Flowchart、sequence、state、class、pieと構文エラーfallbackを検証" "article" "mermaid" "visual-qa" "${WORKDIR}/doc_mermaid_rendering_lab.md"

cat > "${WORKDIR}/doc_docker_spaces.md" <<'EOF'
---
license: MIT
tags: [spaces, docker, deployment]
---

# Docker Spaceを公開する

CPUまたは通常のDockerワークロードとして、アプリをNyankoFace内で動かすためのガイドです。

## 実行ルール

1. リポジトリ直下に`Dockerfile`を置く
2. コンテナ内のポート`7860`で待ち受ける
3. 公開Forgejoリポジトリへ`space`トピックを追加する
4. 秘密情報はリポジトリの外で管理する
5. 埋め込み画面とRunnerのヘルスエンドポイントを確認する

## 対応フレームワーク

Gradio、Streamlit、FastAPI、Node.js、静的HTML、React、Vue、Next.jsは同じルールで動かせます。フレームワーク固有のベースパス対応は、カタログではなくアプリのイメージ側で行います。
EOF
create_doc_fixture "docker-space-field-guide" "DockerfileからNyankoFace Spaceを起動するまでの実践手順" "procedure" "spaces" "docker" "${WORKDIR}/doc_docker_spaces.md"

cat > "${WORKDIR}/doc_agent_ops.md" <<'EOF'
---
license: MIT
tags: [agents, review, automation]
---

# エージェント運用Wiki

自動メンテナンスは、見えない単一プロセスではなく、独立したアカウント同士の会話として進みます。

## 役割

- **メンテナー**が作業を分類し、専門エージェントへ委任する
- **デザイン、コーディング、ドキュメントの各エージェント**が担当範囲を実装する
- **レビューエージェント**が提案されたhead SHAを検証する

## マージ条件

必要な証跡が揃い、作成者とは別のレビュアーが現在のhead SHAを承認した場合だけ、自動マージできます。新しいコミットが追加された時点で、以前の承認は無効になります。

## 証跡

UI作業では実際のモバイル・デスクトップ画面を撮影します。コード作業では関連テストと読みやすい完了報告を残します。Issueが監査履歴として残ります。
EOF
create_doc_fixture "agent-operations-wiki" "役割分担、委任、証跡、安全な自動マージの設計" "wiki" "agents" "review" "${WORKDIR}/doc_agent_ops.md"

cat > "${WORKDIR}/doc_catalog_reference.md" <<'EOF'
---
license: MIT
tags: [catalog, topics, metadata]
---

# カタログトピック一覧

NyankoFaceではForgejoのトピックを、組み合わせ可能な軽量メタデータとして使います。

| 種別トピック | 一覧ページ |
|---|---|
| `model` | `/models` |
| `dataset` | `/datasets` |
| `space` | `/spaces` |
| `skill` | `/skills` |
| `mcp` | `/mcps` |
| `prompt` | `/prompts` |
| `doc` | `/docs` |

種別トピックのあとに、内容を説明するトピックを追加します。たとえば文書には`doc`、`wiki`、`architecture`、`routes`を同時に設定でき、硬直したスキーマを作らず検索性を保てます。
EOF
create_doc_fixture "catalog-topic-reference" "NyankoFaceの各一覧で共通して使うトピック仕様" "wiki" "catalog" "metadata" "${WORKDIR}/doc_catalog_reference.md"

cat > "${WORKDIR}/doc_visual_qa.md" <<'EOF'
---
license: MIT
tags: [visual-qa, themes, mobile]
---

# ビジュアルQA実践メモ

スクリーンショットは、実際のURL、必要な操作、利用者が見るレイアウトを再現して初めて証跡になります。

## 確認マトリクス

- Standard、Solarpunk、Cyberpunkの各テーマ
- デスクトップと狭いモバイル画面
- ページ上部・中部・下部のスクロール状態
- メニュー、折りたたみ、フィルター、タブ、画面遷移
- 横方向のはみ出しとブラウザーコンソール

## 役に立つレポート

URL、画面サイズ、テーマ、操作、期待結果、実際の結果、画像パスを記録します。対応する画面証跡がないテスト成功だけでは、UIを承認しません。
EOF
create_doc_fixture "visual-qa-field-notes" "スクリーンショットを再現可能なUIレビュー証跡にする方法" "article" "visual-qa" "themes" "${WORKDIR}/doc_visual_qa.md"

cat > "${WORKDIR}/doc_cpu_first.md" <<'EOF'
---
license: MIT
tags: [cpu, inference, operations]
---

# CPUファーストは製品設計の選択

CPUファーストは性能を軽視することではありません。検索、文書処理、構造化抽出、小型分類器、ブラウザー推論など、希少なアクセラレーターがなくても価値を出せる処理を選ぶ設計です。

## 普通のマシンを基準にする

有用なCPU処理は素早く起動し、正確な稼働状態を示し、同時実行が増えたときも予測可能に劣化します。モデルサイズ、イメージサイズ、依存関係、コールドスタート時間も製品予算の一部です。

## 実践的な確認項目

- コールド時とウォーム時の応答時間を分けて計測する
- メモリ不足になる前にワーカー同時実行数を制限する
- 再現可能な成果物をリクエスト経路の外へキャッシュする
- GPU専用機能を標準体験から外す

これにより、ノートPC、研究室サーバー、プライベートネットワークのどこでも再現しやすくなります。
EOF
create_doc_fixture "cpu-first-ai-systems" "普通のマシンで役立つローカルAI処理を設計する" "article" "cpu" "inference" "${WORKDIR}/doc_cpu_first.md"

cat > "${WORKDIR}/doc_forgejo_truth.md" <<'EOF'
---
license: MIT
tags: [forgejo, git, architecture]
---

# Forgejoを信頼できる情報源にする

NyankoFaceはID、リポジトリ、トピック、ファイル、Issue、プルリクエストをForgejoから読み取ります。カタログはその永続データを投影するもので、運用者が同期し続ける第2のデータベースではありません。

## この境界が重要な理由

リポジトリ履歴を見れば、誰がモデルカード、Space、ガイドを変更したか分かります。トピックが検索を支え、プルリクエストがレビュー証跡を残します。バックアップも通常のForgejoバックアップのままです。

## NyankoFaceが加えるもの

NyankoFaceは用途別の検索、詳しい成果物ページ、埋め込み実行環境、Pages、メンテナンスエージェントのワークフローを提供します。ただし、それらの根拠となるリポジトリ履歴を暗黙に置き換えることはありません。

> カタログ上の説明をリポジトリまでたどれないなら、それは永続的な製品データではありません。
EOF
create_doc_fixture "forgejo-source-of-truth" "NyankoFaceがForgejoの状態を複製せず投影する理由" "article" "forgejo" "architecture" "${WORKDIR}/doc_forgejo_truth.md"

cat > "${WORKDIR}/doc_community_design.md" <<'EOF'
---
license: MIT
tags: [community, design, accessibility]
---

# ローカルAIコミュニティのデザイン

コミュニティカタログは、初めて来た人が「何があるか」「なぜ重要か」「どう参加するか」をすぐ理解できる必要があります。細かなメタデータは、その3点が伝わったあとで初めて役立ちます。

## 情報の優先順位

名前と概要を最初に見せ、トピックで方向を示し、件数と日時で信頼感を補います。操作ボタンは、利用者が判断できるだけの文脈が揃った場所に置きます。

## 誰でも使える標準状態

タッチ、キーボード、狭い画面でもナビゲーションを使えるようにします。テーマ色だけで意味を伝えません。空の状態では「何もない」だけでなく、次にできる操作を案内します。

日常的なリポジトリ作業を謎解きにせず、個性的な見た目を実現できます。
EOF
create_doc_fixture "community-design-principles" "コミュニティカタログの情報設計とアクセシビリティ原則" "article" "community" "design" "${WORKDIR}/doc_community_design.md"

cat > "${WORKDIR}/doc_identity_map.md" <<'EOF'
---
license: MIT
tags: [identity, permissions, security]
---

# IDと権限のマップ

どのアカウントが、どの種類の操作を担当するかを整理したWikiです。

| ID | 主な権限 | ガードレール |
|---|---|---|
| 訪問者 | 公開カタログとリポジトリの閲覧 | 変更不可 |
| メンバー | コメント、リアクション、貢献 | リポジトリ権限 |
| 組織オーナー | チームと組織プロフィールの管理 | Forgejo所有権 |
| メンテナンスエージェント | ブランチとPRの作成 | スコープ付きトークン |
| レビューエージェント | 検証済みheadの承認 | 独立したID |

## 最小権限の原則

実行コンテナへForgejoの管理者認証情報を渡しません。エージェントトークンは必要なリポジトリと操作だけに絞ります。人間の所有権と自動作業を同じ監査履歴で確認できます。
EOF
create_doc_fixture "identity-permission-map" "人、組織、エージェントの権限を整理したWikiマップ" "wiki" "identity" "security" "${WORKDIR}/doc_identity_map.md"

cat > "${WORKDIR}/doc_service_boundaries.md" <<'EOF'
---
license: MIT
tags: [services, docker, architecture]
---

# サービス境界Wiki

NyankoFaceは責務を明確にした小さなサービスで構成されています。

| サービス | 担当するもの | 担当しないもの |
|---|---|---|
| Gateway | TLSとリクエスト振り分け | リポジトリデータ |
| Frontend | カタログと成果物画面 | コンテナビルド |
| Forgejo | Git、ID、Issue、PR | Space実行 |
| Spaces Runner | Dockerビルドとアプリのライフサイクル | ユーザーアカウント |
| Maintenance Agent | 委任とレビューの流れ | 証跡なしのマージ権限 |

## 境界からデバッグする

まず公開URLを確認し、担当サービスを特定してから、そのヘルス状態とログを追います。画面上の症状だけを手掛かりに全コンテナを無差別に調べることを防げます。
EOF
create_doc_fixture "service-boundary-wiki" "NyankoFaceのサービスと責務境界をつなぐマップ" "wiki" "services" "architecture" "${WORKDIR}/doc_service_boundaries.md"

cat > "${WORKDIR}/doc_metrics_agents.md" <<'EOF'
---
license: MIT
tags: [metrics, agents, api]
---

# メトリクスとエージェントAPI Wiki

閲覧、いいね、リアクション、コメントは、まず利用者の操作です。エージェントAPIも同じドメイン操作を公開し、自動化のためにブラウザースクレイピングや特権DB書き込みを必要としない設計にします。

## イベントの流れ

1. ブラウザーまたはエージェントが認証済み操作を送る
2. NyankoFaceがIDとリポジトリの公開範囲を確認する
3. 操作を永続的な成果物へ関連付けて記録する
4. 一覧と詳細画面が更新後の集計値を読む

## 運用ルール

再試行は冪等でなければなりません。ネットワーク再試行によって1回の閲覧やリアクションが複数回に増えてはいけません。エージェントの活動は、それぞれのアカウントとアバターへ紐づけます。
EOF
create_doc_fixture "metrics-and-agent-api-wiki" "人とエージェントが監査可能な操作を共有する仕組み" "wiki" "metrics" "api" "${WORKDIR}/doc_metrics_agents.md"

cat > "${WORKDIR}/doc_publishing_quickstart.md" <<'EOF'
---
license: MIT
tags: [docs, publishing, forgejo]
---

# 最初のNyankoFaceナレッジを公開する

NyankoFaceの公開ナレッジは、複数のMarkdown記事を持つ通常の公開Forgejoリポジトリです。一度作成すれば、同じ場所へ知識を追加し続けられます。

## 1. 公開リポジトリを作る

**新規作成 → ドキュメント**を開き、個人またはチームを所有者に選び、`my-knowledge`のようなリポジトリを作ります。共有ライブラリへ掲載する場合は公開にします。

Forgejoで`doc`、`knowledge`、`markdown`トピックを追加します。

## 2. 記事を追加する

`articles/my-first-note.md`を作り、フロントマターへ記事情報を書きます。ニュース、手順、参照情報、ベンチマーク、調査などの違いは保存場所ではなく`topics`で表します。

```yaml
---
title: 最初の調査メモ
description: ローカルAI環境を調査した記録
emoji: "🔬"
topics: [local-ai, research, reference]
published: true
---
```

## 3. ナレッジを書く

フロントマターの下へ通常のMarkdownで本文を書きます。見出し、箇条書き、表、コード、画像、リンクを使い、実践しやすい内容にします。完成したら通常どおりコミットします。

## 4. 掲載を確認する

`/docs`へ戻り、タグまたは検索から記事を開きます。表示されない場合は、リポジトリが公開されていること、`doc`トピックがあること、ファイルが`articles/`にあること、`published`が`false`でないことを確認します。
EOF
create_doc_fixture "docs-publishing-quickstart" "個人の公開リポジトリを作り、検索できるMarkdown記事を追加する" "procedure" "docs" "publishing" "${WORKDIR}/doc_publishing_quickstart.md"

cat > "${WORKDIR}/doc_tailscale_guide.md" <<'EOF'
---
license: MIT
tags: [tailscale, deployment, tls]
---

# TailscaleでNyankoFaceを公開する

NyankoFaceを公開インターネットへ露出せず、信頼できるスマートフォンやPCから利用する場合はtailnetを使います。

## チェックリスト

1. Docker Composeを起動し、`https://localhost:8443`を確認する
2. ホストでTailscaleへログインする
3. Tailscale ServeでローカルHTTPSを配信する
4. 別のtailnet端末から生成された`*.ts.net` URLを開く
5. ナビゲーション、埋め込みSpace、長いモバイルページを確認する

## TLSについて

ブラウザーはTailscale証明書へ接続し、ローカルGatewayは同じルートを維持します。ネットワーク設計上の明確な理由がない限り、ForgejoやRunnerのポートを個別公開しません。
EOF
create_doc_fixture "tailscale-private-deployment" "信頼できるtailnet端末へNyankoFaceを安全に公開する" "procedure" "tailscale" "deployment" "${WORKDIR}/doc_tailscale_guide.md"

cat > "${WORKDIR}/doc_recovery_playbook.md" <<'EOF'
---
license: MIT
tags: [recovery, operations, docker]
---

# 障害復旧プレイブック

カタログ、リポジトリ画面、Spaceが応答しなくなったときに使うガイドです。

## 切り分け

1. 失敗したURLと表示エラーを記録する
2. 再起動する前にComposeサービスの状態を確認する
3. 担当サービスとGatewayのログを確認する
4. カタログ障害ではForgejo APIへの到達性を確認する
5. Space障害ではRunnerコンテナの状態を確認する

## 安全に復旧する

まず影響を受けたステートレスサービスだけを再作成します。Forgejoのボリュームとリポジトリデータは保持します。復旧後は同じブラウザー操作を繰り返し、スクリーンショットと関連ログを残します。

データや権限の問題が続く場合は、全体再起動を繰り返して隠さず、原因調査へ切り替えます。
EOF
create_doc_fixture "incident-recovery-playbook" "NyankoFaceの一般的な障害を安全に診断・復旧する手順" "procedure" "recovery" "operations" "${WORKDIR}/doc_recovery_playbook.md"

cat > "${WORKDIR}/doc_env_reference.md" <<'EOF'
---
license: MIT
tags: [configuration, docker, environment]
---

# 環境変数リファレンス

環境値はCompose設定またはローカルの`.env`へ置き、サンプルリポジトリにはコミットしません。

| 項目 | 値の例 | 用途 |
|---|---|---|
| 公開オリジン | `https://localhost:8443` | 絶対リンクとコールバック |
| ForgejoベースURL | 内部サービスURL | リポジトリAPIアクセス |
| Runnerポート | `7860` | 埋め込みSpaceの契約 |
| エージェント同時実行数 | 小さな正整数 | 並列メンテナンス上限 |
| 標準テーマ | `system` | ブラウザーの初期設定 |

## 検証

設定変更後は有効なCompose設定を出力し、影響するサービスだけを再作成します。画面を試す前にヘルスエンドポイントを確認します。
EOF
create_doc_fixture "environment-variable-reference" "デプロイと実行時設定の簡潔なリファレンス" "wiki" "configuration" "environment" "${WORKDIR}/doc_env_reference.md"

cat > "${WORKDIR}/doc_route_reference.md" <<'EOF'
---
license: MIT
tags: [routes, api, gateway]
---

# URLとエンドポイント一覧

| URL | 用途 |
|---|---|
| `/models`, `/datasets`, `/spaces` | 成果物を探す |
| `/skills`, `/mcps`, `/prompts`, `/docs` | 再利用可能な知識を探す |
| `/{owner}/{repo}` | リポジトリに紐づく詳細画面 |
| `/pages/{owner}/{repo}/` | 公開静的サイト |
| `/git/` | Gateway経由のForgejo画面 |

## 担当サービス

公開アプリのURLはFrontendまたはRunnerが処理します。ForgejoのURLは`/git/`配下に保ちます。Gatewayが名前空間を安定させ、内部サービスのアドレスを利用者向けリンクへ露出させません。
EOF
create_doc_fixture "route-and-endpoint-reference" "公開URLの用途と担当サービス一覧" "wiki" "routes" "gateway" "${WORKDIR}/doc_route_reference.md"

cat > "${WORKDIR}/doc_format_reference.md" <<'EOF'
---
license: MIT
tags: [docs, taxonomy, topics]
---

# 記事タグ一覧

NyankoFaceでは、すべての公開ナレッジを`articles/*.md`へ保存します。内容の違いは複数の`topics`で表します。

| タグ | 向いている内容 | 例 |
|---|---|---|
| `news` | 更新情報とコミュニティ速報 | リリース、新機能 |
| `how-to` | 最初から最後まで行う作業 | 構築、復旧 |
| `reference` | 仕様、選択肢、URL、用語集 | API、設定 |
| `benchmark` | 評価条件と測定結果 | CAD、SVG、LLM |
| `research` | 背景、分析、意思決定 | 調査、比較 |

複数タグを組み合わせられます。タイトルの単語を繰り返すのではなく、読者が検索する言葉を選びます。
EOF
create_doc_fixture "document-format-reference" "記事を検索しやすくするタグの選び方" "wiki" "docs" "taxonomy" "${WORKDIR}/doc_format_reference.md"

# ------------------------------------------------------------------------
# Agent-owned knowledge publications. Each account creates its own public
# repository and commits one role-specific article with its own token.
# A shared topic makes the six independent publications easy to discover.
# ------------------------------------------------------------------------
publish_agent_article() {
  local username="$1" description="$2" role_topic="$3" slug="$4" source_file="$5"
  ensure_personal_knowledge_repo "$username" "$description"
  set_personal_knowledge_topics "$username" "doc" "knowledge" "agent-authored" "$role_topic"
  put_personal_knowledge_file "$username" "articles/${slug}.md" "$source_file" "記事を公開: ${slug}"
}

publish_agent_article \
  "glm-maintainer" \
  "自動メンテナンスの判断と委任に関する実践ナレッジ" \
  "maintenance" \
  "delegation-playbook" \
  "/templates/agent-knowledge/glm-maintainer.md"
publish_agent_article \
  "designer-agent" \
  "UI設計とスクリーンショット検証に関する実践ナレッジ" \
  "design" \
  "mobile-visual-qa" \
  "/templates/agent-knowledge/designer-agent.md"
publish_agent_article \
  "coding-agent" \
  "安全な実装、テスト、Git運用に関する実践ナレッジ" \
  "engineering" \
  "safe-change-workflow" \
  "/templates/agent-knowledge/coding-agent.md"
publish_agent_article \
  "docs-agent" \
  "READMEと再構築可能な文書運用に関する実践ナレッジ" \
  "docs" \
  "docs-truth-sync" \
  "/templates/agent-knowledge/docs-agent.md"
publish_agent_article \
  "security-agent" \
  "リリースとサプライチェーンの安全性に関する実践ナレッジ" \
  "security" \
  "release-security-gate" \
  "/templates/agent-knowledge/security-agent.md"
publish_agent_article \
  "review-agent" \
  "独立レビューと検証証跡に関する実践ナレッジ" \
  "review" \
  "independent-review-evidence" \
  "/templates/agent-knowledge/review-agent.md"

# Simulated community members are ordinary Forgejo users with no maintenance
# role or organization privilege. Each person owns a separate repository and
# publishes with their own token, matching the expected user workflow.
publish_community_article() {
  local username="$1" description="$2" interest_topic="$3" slug="$4" source_file="$5"
  ensure_personal_knowledge_repo "$username" "$description"
  set_personal_knowledge_topics "$username" "doc" "knowledge" "community-authored" "$interest_topic"
  put_personal_knowledge_file "$username" "articles/${slug}.md" "$source_file" "記事を投稿: ${slug}"
  verify_personal_knowledge_author "$username"
}

publish_community_article \
  "haruka-sato" \
  "佐藤遥のローカルAI環境と日々の実験ノート" \
  "home-lab" \
  "home-gpu-learning-log" \
  "/templates/community-knowledge/haruka-sato.md"
publish_community_article \
  "takumi-endo" \
  "遠藤匠のCAD・SVG・生成AIベンチマーク記録" \
  "benchmark" \
  "svg-benchmark-checklist" \
  "/templates/community-knowledge/takumi-endo.md"
publish_community_article \
  "nana-kurose" \
  "黒瀬菜々の小さなSpace制作と公開メモ" \
  "spaces" \
  "first-docker-space" \
  "/templates/community-knowledge/nana-kurose.md"
publish_community_article \
  "rio-kanda" \
  "神田理央のローカルAI読書会・コミュニティ記録" \
  "community" \
  "local-ai-reading-circle" \
  "/templates/community-knowledge/rio-kanda.md"

# A simulated private community organization. Haruka contributes the shared
# article, Nana can read it, and two ordinary users remain outside the
# organization as explicit negative ACL fixtures.
ensure_private_org_knowledge_repo \
  "local-makers" \
  "member-notes" \
  "Local Makers members-only experiment notes"
set_private_org_knowledge_topics_as_admin \
  "local-makers" \
  "member-notes" \
  "doc" "knowledge" "community" "member-only"
put_private_org_knowledge_file \
  "haruka-sato" \
  "local-makers" \
  "member-notes" \
  "articles/shared-home-lab-checklist.md" \
  "/templates/community-knowledge/local-makers-private.md" \
  "メンバー記事を投稿: 共有ホームラボ確認表"
verify_private_org_knowledge_acl \
  "local-makers" \
  "member-notes" \
  "articles/shared-home-lab-checklist.md" \
  "haruka-sato" \
  "takumi-endo"
verify_private_org_knowledge_acl \
  "local-makers" \
  "member-notes" \
  "articles/shared-home-lab-checklist.md" \
  "nana-kurose" \
  "rio-kanda"

# A private organization publication used to continuously verify that
# Forgejo membership, not NyankoFace's privileged catalog token, controls
# access to restricted knowledge.
ensure_private_org_knowledge_repo \
  "vault-research" \
  "internal-knowledge" \
  "Vault Research members-only release and security notes"
set_private_org_knowledge_topics \
  "security-agent" \
  "vault-research" \
  "internal-knowledge" \
  "doc" "knowledge" "internal" "member-only"
put_private_org_knowledge_file \
  "security-agent" \
  "vault-research" \
  "internal-knowledge" \
  "articles/internal-release-review.md" \
  "/templates/private-organization/internal-release-review.md" \
  "内部記事を公開: リリース判定の証跡"
verify_private_org_knowledge_acl \
  "vault-research" \
  "internal-knowledge" \
  "articles/internal-release-review.md" \
  "security-agent" \
  "coding-agent"

# ------------------------------------------------------------------------
# NyankoFace Navigator Skill. The repository is seeded from the same files
# reviewed in this platform repository, so users can inspect, fork, and update
# the instructions through the normal Forgejo workflow.
# ------------------------------------------------------------------------
ensure_repo "nyankoface-navigator-skill" "NyankoFaceの全公開契約、環境変数、配備、検証を案内する中核スキル"
set_topics "nyankoface-navigator-skill" "skill" "publishing" "navigator" "operations" "validation" "japanese"
put_file "nyankoface-navigator-skill" "SKILL.md" "/templates/nyankoface-navigator/SKILL.md" "Add NyankoFace Navigator skill"
put_file "nyankoface-navigator-skill" "agents/openai.yaml" "/templates/nyankoface-navigator/agents/openai.yaml" "Add navigator UI metadata"
put_file "nyankoface-navigator-skill" "references/publishing-map.md" "/templates/nyankoface-navigator/references/publishing-map.md" "Document NyankoFace publishing map"
put_file "nyankoface-navigator-skill" "references/deployment-environment.md" "/templates/nyankoface-navigator/references/deployment-environment.md" "Document NyankoFace deployment environment"
put_file "nyankoface-navigator-skill" "references/pages.md" "/templates/nyankoface-navigator/references/pages.md" "Document canonical NyankoFace Pages workflow"
put_file "nyankoface-navigator-skill" "scripts/validate_repo.py" "/templates/nyankoface-navigator/scripts/validate_repo.py" "Add repository validator"
put_file "nyankoface-navigator-skill" "scripts/test_validate_repo.py" "/templates/nyankoface-navigator/scripts/test_validate_repo.py" "Add validator regression tests"
put_file "nyankoface-navigator-skill" "scripts/verify_pages.py" "/templates/nyankoface-navigator/scripts/verify_pages.py" "Add Pages live verifier"
put_file "nyankoface-navigator-skill" "scripts/test_verify_pages.py" "/templates/nyankoface-navigator/scripts/test_verify_pages.py" "Add Pages verifier tests"
put_file "nyankoface-navigator-skill" "assets/article.md" "/templates/nyankoface-navigator/assets/article.md" "Add article template"
put_file "nyankoface-navigator-skill" "assets/pages-index.html" "/templates/nyankoface-navigator/assets/pages-index.html" "Add Pages template"
put_file "nyankoface-navigator-skill" "assets/pages-static/index.html" "/templates/nyankoface-navigator/assets/pages-static/index.html" "Add static Pages starter"
put_file "nyankoface-navigator-skill" "assets/pages-vitepress/package.json" "/templates/nyankoface-navigator/assets/pages-vitepress/package.json" "Add VitePress package starter"
put_file "nyankoface-navigator-skill" "assets/pages-vitepress/docs/index.md" "/templates/nyankoface-navigator/assets/pages-vitepress/docs/index.md" "Add VitePress page starter"
put_file "nyankoface-navigator-skill" "assets/pages-vitepress/docs/.vitepress/config.mts" "/templates/nyankoface-navigator/assets/pages-vitepress/docs/.vitepress/config.mts" "Add VitePress base path starter"
put_file "nyankoface-navigator-skill" "assets/pages-vitepress/.forgejo/workflows/publish-pages.yml" "/templates/nyankoface-navigator/assets/pages-vitepress/.forgejo/workflows/publish-pages.yml" "Add VitePress Pages workflow starter"
put_file "nyankoface-navigator-skill" "assets/space-Dockerfile" "/templates/nyankoface-navigator/assets/space-Dockerfile" "Add Space template"
put_file "nyankoface-navigator-skill" "assets/space-app.py" "/templates/nyankoface-navigator/assets/space-app.py" "Add Gradio Space app template"
put_file "nyankoface-navigator-skill" "assets/space-requirements.txt" "/templates/nyankoface-navigator/assets/space-requirements.txt" "Add Space requirements template"
put_file "nyankoface-navigator-skill" "assets/space-README.md" "/templates/nyankoface-navigator/assets/space-README.md" "Add Space metadata template"
put_file "nyankoface-navigator-skill" "assets/external-space-README.md" "/templates/nyankoface-navigator/assets/external-space-README.md" "Add external Space template"
put_file "nyankoface-navigator-skill" "assets/automation.toml" "/templates/nyankoface-navigator/assets/automation.toml" "Add Automation template"
put_file "nyankoface-navigator-skill" "assets/automation.example.toml" "/templates/nyankoface-navigator/assets/automation.example.toml" "Add safe Automation example"
put_file "nyankoface-navigator-skill" "assets/automation-README.md" "/templates/nyankoface-navigator/assets/automation-README.md" "Add Automation README template"
put_file "nyankoface-navigator-skill" "assets/automation-LICENSE" "/templates/nyankoface-navigator/assets/automation-LICENSE" "Add Automation license template"

# ------------------------------------------------------------------------
# Secret-free Issue reporting Skill. Every catfolk agent can stage the same
# contract; only the operator-side publisher has GitHub credentials.
# ------------------------------------------------------------------------
ensure_repo "nyankoface-issue-report" "Secret-free, reproducible NyankoFace Issue reports"
set_topics "nyankoface-issue-report" "skill" "issue-reporting" "redaction" "operator-workflow"
put_file "nyankoface-issue-report" "SKILL.md" "/templates/nyankoface-issue-report/SKILL.md" "Add NyankoFace Issue Report skill"
put_file "nyankoface-issue-report" "agents/openai.yaml" "/templates/nyankoface-issue-report/agents/openai.yaml" "Add Issue Report UI metadata"
put_file "nyankoface-issue-report" "references/report-contract.md" "/templates/nyankoface-issue-report/references/report-contract.md" "Document Issue report contract"
put_file "nyankoface-issue-report" "scripts/stage_report.py" "/templates/nyankoface-issue-report/scripts/stage_report.py" "Add secret-safe report stager"
put_file "nyankoface-issue-report" "scripts/publish_report.py" "/templates/nyankoface-issue-report/scripts/publish_report.py" "Add operator Issue publisher"

# ------------------------------------------------------------------------
# Portable Automation fixture. It is owned by the seeded angel organization,
# remains disabled, carries an immutable SemVer tag, and is safe to inspect
# without triggering registration or execution.
# ------------------------------------------------------------------------
ensure_repo_for_org "seraphim-labs" "weekly-repository-report" "Read-only weekly repository digest with inspectable permissions and schedule"
REPO_OWNER_CONTEXT="seraphim-labs"
set_topics "weekly-repository-report" "automation" "report" "repository" "read-only" "scheduled" "version-v1.0.0"
put_file "weekly-repository-report" "README.md" "/templates/weekly-repository-report/README.md" "Document portable Automation"
put_file "weekly-repository-report" "automation.toml" "/templates/weekly-repository-report/automation.toml" "Add disabled Automation manifest"
put_file "weekly-repository-report" "automation.example.toml" "/templates/weekly-repository-report/automation.example.toml" "Add safe Automation example"
put_file "weekly-repository-report" "LICENSE" "/templates/weekly-repository-report/LICENSE" "Add Automation license"
ensure_tag "weekly-repository-report" "v1.0.0" "Release portable Automation v1.0.0"
unset REPO_OWNER_CONTEXT

# ------------------------------------------------------------------------
# NyankoFace Pages fixture.  This demonstrates the same convention as GitHub
# Pages: files from a public repo's `gh-pages` branch are served at
# /pages/{owner}/{repo}/.  Keeping it in the seed makes a fresh Compose
# deployment verifiable without any manual Forgejo setup.
# ------------------------------------------------------------------------
ensure_repo "pages-starter" "A public static site published with NyankoFace Pages"
set_topics "pages-starter" "pages" "static-site" "html" "nyankoface-pages"

cat > "${WORKDIR}/pages_starter_readme.md" <<'EOF'
# NyankoFace Pages starter

This public repository demonstrates **NyankoFace Pages**.

Open the published site at `/pages/nyankoface/pages-starter/`. NyankoFace serves
the `gh-pages` branch when it exists; otherwise it uses `docs/` on `main`.
EOF
put_file "pages-starter" "README.md" "${WORKDIR}/pages_starter_readme.md" "Add NyankoFace Pages starter README"

cat > "${WORKDIR}/pages_starter_index.html" <<'EOF'
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>NyankoFace Pages starter</title>
    <style>
      :root { color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
      body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f7f6f2; color: #152238; }
      main { box-sizing: border-box; width: min(680px, calc(100% - 48px)); padding: 48px; border: 1px solid #dfe4ea; border-radius: 20px; background: #fff; box-shadow: 0 22px 70px #15223812; }
      .eyebrow { color: #52657c; font: 700 12px/1.2 ui-monospace, monospace; letter-spacing: .12em; }
      h1 { margin: 14px 0; font-size: clamp(2rem, 7vw, 4.4rem); line-height: .95; letter-spacing: -.06em; }
      p { color: #52657c; font-size: 1.1rem; line-height: 1.7; }
      code { padding: .2em .4em; border-radius: 6px; background: #eef2f6; color: #254b79; }
    </style>
  </head>
  <body>
    <main>
      <div class="eyebrow">NYANKOFACE PAGES · GH-PAGES BRANCH</div>
      <h1>Publish the small things.</h1>
      <p>This static site is served from a public Forgejo repository through NyankoFace Pages. Push an <code>index.html</code> to <code>gh-pages</code>, then share its URL.</p>
    </main>
  </body>
</html>
EOF
put_file "pages-starter" "index.html" "${WORKDIR}/pages_starter_index.html" "Add NyankoFace Pages starter site"
put_file \
  "pages-starter" \
  ".forgejo/workflows/nyankoface-pipeline.yml" \
  "/templates/nyankoface-pipeline/nyankoface-pipeline.yml" \
  "ci: add NyankoFace pipeline"
register_pipeline_repository "nyankoface" "pages-starter"
ensure_pages_branch "pages-starter"
ensure_pull_detail_fixture "pages-starter"
ensure_community_reaction_fixture "pages-starter"
repair_community_qa_fixture "pages-starter"

# Linked asset example: gh-pages serves HTML, CSS, and browser JavaScript from
# the same public repository path.
ensure_repo "pages-portfolio" "Static HTML, CSS and JavaScript published with NyankoFace Pages"
set_topics "pages-portfolio" "pages" "static-site" "javascript" "nyankoface-pages"
put_file "pages-portfolio" "index.html" "/templates/pages-portfolio/index.html" "Add static portfolio page"
put_file "pages-portfolio" "styles.css" "/templates/pages-portfolio/styles.css" "Add portfolio stylesheet"
put_file "pages-portfolio" "app.js" "/templates/pages-portfolio/app.js" "Add portfolio browser interaction"
ensure_pages_branch "pages-portfolio"

# Fallback example: no gh-pages branch is created. NyankoFace Pages serves the
# docs/ directory in main, including relative links and assets.
ensure_repo "pages-docs-fallback" "Documentation served from docs on the default branch"
set_topics "pages-docs-fallback" "pages" "docs" "static-site" "nyankoface-pages"
put_file "pages-docs-fallback" "docs/index.html" "/templates/pages-docs-fallback/docs/index.html" "Add docs fallback home"
put_file "pages-docs-fallback" "docs/guide.html" "/templates/pages-docs-fallback/docs/guide.html" "Add docs fallback guide"
put_file "pages-docs-fallback" "docs/styles.css" "/templates/pages-docs-fallback/docs/styles.css" "Add docs fallback stylesheet"

# A complete VitePress + Forgejo Actions example.  The workflow pushes the
# generated `docs/.vitepress/dist` directory to gh-pages, which NyankoFace Pages
# immediately serves at /pages/nyankoface/vitepress-pages-starter/.
ensure_repo "vitepress-pages-starter" "VitePress documentation published by Forgejo Actions"
set_topics "vitepress-pages-starter" "pages" "vitepress" "docs" "nyankoface-pages"
put_file "vitepress-pages-starter" "package.json" "/templates/vitepress-pages-starter/package.json" "Add VitePress package manifest"
put_file "vitepress-pages-starter" "docs/index.md" "/templates/vitepress-pages-starter/docs/index.md" "Add VitePress home page"
put_file "vitepress-pages-starter" "docs/.vitepress/config.mts" "/templates/vitepress-pages-starter/docs/.vitepress/config.mts" "Configure VitePress public base"
put_file "vitepress-pages-starter" ".forgejo/workflows/publish-pages.yml" "/templates/vitepress-pages-starter/.forgejo/workflows/publish-pages.yml" "Automate VitePress Pages publishing"

# Real Skill and MCP samples selected from Sunwood-ai-labs on GitHub.
import_sunwood_catalog

# CPU-runnable public CAD and SVG evaluation suites.
import_benchmark_catalog

# Vetted, versioned prompts from MysticLibrary plus public goal-command
# patterns.  Each source URL is pinned in catalog/prompts.json.
import_prompt_catalog

# Publish the deterministic Docker sample Spaces after their owner
# organization exists. These local fixtures keep fresh installs and Visual QA
# independent from optional upstream Hugging Face imports.
sed 's/\r$//' /samples/publish.sh > "${WORKDIR}/publish-samples.sh"
if ! bash "${WORKDIR}/publish-samples.sh"; then
  log "ERROR: deterministic Docker sample publication failed."
  exit 1
fi

rm -rf "${WORKDIR}"

log "Seed complete."
exit 0
