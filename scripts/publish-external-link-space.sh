#!/usr/bin/env bash
set -euo pipefail

repo_root="${1:-/opt/nyankoface}"
cd "$repo_root"

if [[ ! -f .env ]]; then
  echo "NyankoFace .env was not found under $repo_root" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
. ./.env
set +a

: "${NYANKOFACE_ADMIN_USER:?NYANKOFACE_ADMIN_USER is required}"
: "${NYANKOFACE_ADMIN_PASSWORD:?NYANKOFACE_ADMIN_PASSWORD is required}"

api="${NYANKOFACE_INTERNAL_API:-https://127.0.0.1:8443/git/api/v1}"
repository="nyankoface-documentation"
fixture="seed/templates/external-link-space"
auth="${NYANKOFACE_ADMIN_USER}:${NYANKOFACE_ADMIN_PASSWORD}"

if [[ ! -f "$fixture/README.md" ]]; then
  echo "Fixture not found: $fixture/README.md" >&2
  exit 1
fi

create_response="$(mktemp)"
topic_response="$(mktemp)"
work="$(mktemp -d)"
trap 'rm -rf "$work" "$create_response" "$topic_response"' EXIT

create_code="$(
  curl -ksS -o "$create_response" -w '%{http_code}' \
    -u "$auth" \
    -H 'Content-Type: application/json' \
    -X POST "$api/orgs/nyankoface/repos" \
    --data '{
      "name": "nyankoface-documentation",
      "description": "Open the published NyankoFace documentation directly from the Spaces catalog",
      "private": false,
      "default_branch": "main"
    }'
)"

if [[ "$create_code" != "201" && "$create_code" != "409" && "$create_code" != "422" ]]; then
  echo "Forgejo repository creation failed with HTTP $create_code" >&2
  cat "$create_response" >&2
  exit 1
fi

topic_code="$(
  curl -ksS -o "$topic_response" -w '%{http_code}' \
    -u "$auth" \
    -H 'Content-Type: application/json' \
    -X PUT "$api/repos/nyankoface/$repository/topics" \
    --data '{
      "topics": [
        "space",
        "external-site",
        "documentation"
      ]
    }'
)"

if [[ "$topic_code" != "200" && "$topic_code" != "204" ]]; then
  echo "Forgejo topic update failed with HTTP $topic_code" >&2
  cat "$topic_response" >&2
  exit 1
fi

cp -a "$fixture/." "$work/"
git -C "$work" init -q -b main
git -C "$work" config user.name "NyankoFace Samples"
git -C "$work" config user.email "samples@nyankoface.local"
git -C "$work" add .
git -C "$work" commit -q -m "Add external-link Space"
git -C "$work" remote add origin \
  "https://127.0.0.1:8443/git/nyankoface/$repository.git"

basic="$(printf '%s' "$auth" | base64 -w0)"
git -C "$work" \
  -c http.sslVerify=false \
  -c "http.extraHeader=Authorization: Basic $basic" \
  push -q --force origin main

printf 'repo_http=%s topics_http=%s commit=%s\n' \
  "$create_code" "$topic_code" "$(git -C "$work" rev-parse --short HEAD)"
