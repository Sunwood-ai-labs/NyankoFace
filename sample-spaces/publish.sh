#!/usr/bin/env bash
set -euo pipefail

API="${FORGEJO_API:-http://forgejo:3000/api/v1}"
SOURCE_ORG="${ORG_NAME:-nyankoface}"
SPACE_ORG="${SPACE_ORG_NAME:-seraphim-labs}"
ADMIN="${NYANKOFACE_ADMIN_USER:-nyankoface-admin}"
TOKEN="$(tr -d '\r\n' < "${FORGEJO_TOKEN_FILE:-/shared/token}")"

transfer_existing_sample() {
  local name="$1"
  local target_status source_status

  target_status="$(curl -sS -o /tmp/repo.json -w '%{http_code}' -H "Authorization: token ${TOKEN}" "${API}/repos/${SPACE_ORG}/${name}")"
  [ "$target_status" = "200" ] && return 0
  [ "$target_status" = "404" ] || {
    echo "Repository lookup failed for ${SPACE_ORG}/${name}: HTTP ${target_status}" >&2
    exit 1
  }

  source_status="$(curl -sS -o /tmp/source-repo.json -w '%{http_code}' -H "Authorization: token ${TOKEN}" "${API}/repos/${SOURCE_ORG}/${name}")"
  [ "$source_status" = "404" ] && return 0
  [ "$source_status" = "200" ] || {
    echo "Repository lookup failed for ${SOURCE_ORG}/${name}: HTTP ${source_status}" >&2
    exit 1
  }

  curl -fsS -X POST -H "Authorization: token ${TOKEN}" -H 'Content-Type: application/json' \
    -d "$(jq -n --arg owner "$SPACE_ORG" '{new_owner:$owner}')" \
    "${API}/repos/${SOURCE_ORG}/${name}/transfer" >/dev/null
  echo "Transferred ${SOURCE_ORG}/${name} to ${SPACE_ORG}"
}

# These Docker samples existed in early NyankoFace installations before their
# source directories were tracked. Transfer only when the repository already
# exists; never recreate a removed legacy sample.
for legacy_name in \
  sample-fastapi \
  sample-gradio \
  sample-nextjs \
  sample-nodejs \
  sample-react \
  sample-static-html \
  sample-streamlit \
  sample-vue
do
  transfer_existing_sample "$legacy_name"
done

for source_dir in /samples/sample-*; do
  [ -d "$source_dir" ] || continue
  name="$(basename "$source_dir")"
  dir="$(mktemp -d)"
  cp -R "$source_dir"/. "$dir"/
  rm -rf "$dir/.git"
  description="$(awk 'BEGIN{in_fm=0} /^---$/{in_fm++;next} in_fm==2 && /^$/{next} in_fm>=2 && /^# /{sub(/^# /,""); print; exit}' "$dir/README.md")"
  [ -n "$description" ] || description="Dockerized ${name} sample Space"

  status="$(curl -sS -o /tmp/repo.json -w '%{http_code}' -H "Authorization: token ${TOKEN}" "${API}/repos/${SPACE_ORG}/${name}")"
  if [ "$status" = "404" ]; then
    source_status="$(curl -sS -o /tmp/source-repo.json -w '%{http_code}' -H "Authorization: token ${TOKEN}" "${API}/repos/${SOURCE_ORG}/${name}")"
    if [ "$source_status" = "200" ] && [ "$SOURCE_ORG" != "$SPACE_ORG" ]; then
      curl -fsS -X POST -H "Authorization: token ${TOKEN}" -H 'Content-Type: application/json' \
        -d "$(jq -n --arg owner "$SPACE_ORG" '{new_owner:$owner}')" \
        "${API}/repos/${SOURCE_ORG}/${name}/transfer" >/dev/null
      echo "Transferred ${SOURCE_ORG}/${name} to ${SPACE_ORG}"
    elif [ "$source_status" = "404" ]; then
      curl -fsS -H "Authorization: token ${TOKEN}" -H 'Content-Type: application/json' \
        -d "$(jq -n --arg name "$name" --arg description "$description" '{name:$name,description:$description,private:false,auto_init:false,default_branch:"main"}')" \
        "${API}/orgs/${SPACE_ORG}/repos" >/dev/null
    else
      echo "Repository lookup failed for ${SOURCE_ORG}/${name}: HTTP ${source_status}" >&2
      exit 1
    fi
  elif [ "$status" != "200" ]; then
    echo "Repository lookup failed for ${name}: HTTP ${status}" >&2
    exit 1
  fi

  git -C "$dir" init -b main >/dev/null 2>&1 || true
  git -C "$dir" config user.name "NyankoFace Samples"
  git -C "$dir" config user.email "samples@nyankoface.local"
  git -C "$dir" add .
  if ! git -C "$dir" diff --cached --quiet; then
    GIT_AUTHOR_DATE="${SAMPLE_COMMIT_DATE:-2026-07-01T00:00:00Z}" \
      GIT_COMMITTER_DATE="${SAMPLE_COMMIT_DATE:-2026-07-01T00:00:00Z}" \
      git -C "$dir" commit -m "Add Dockerized ${name} sample" >/dev/null
  fi
  git -C "$dir" remote remove nyankoface >/dev/null 2>&1 || true
  git -C "$dir" remote add nyankoface "http://${ADMIN}:${TOKEN}@forgejo:3000/${SPACE_ORG}/${name}.git"
  git -C "$dir" push --force nyankoface main >/dev/null
  curl -fsS -X PUT -H "Authorization: token ${TOKEN}" -H 'Content-Type: application/json' \
    -d '{"topics":["space","cpu","docker","sample"]}' \
    "${API}/repos/${SPACE_ORG}/${name}/topics" >/dev/null
  echo "Published ${SPACE_ORG}/${name}"
  rm -rf "$dir"
done
