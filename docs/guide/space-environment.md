# Space Variables and Secrets

NyankoFace repository owners can configure runtime and pipeline values from a Space detail page by selecting **Variables & Secrets**.

## Choose the right type

- **Variable**: non-sensitive configuration. Its value is visible to authorized repository writers.
- **Secret**: credentials or tokens. The value is encrypted before persistence and is never returned by list APIs or shown again after saving.

Names must match `[A-Z_][A-Z0-9_]{0,126}`. Saving an existing name rotates its value. Deletion requires a second confirmation click.

Choose `runtime` for the Space container, `build` for Forgejo Actions, or
`both` for both consumers. See [Repository pipelines](./pipelines) for the
native Forgejo synchronization and fork boundary.

## Security boundary

NyankoFace checks the active Forgejo browser session and requires write access to the target repository. Values are scoped to the exact `owner/repository` pair and are not copied by a Git clone or fork.

The runner stores ciphertext in PostgreSQL and keeps the Fernet key at `/data/agents/space-secrets.key` with mode `0600`. Audit rows contain only the setting name, kind, action, actor, and timestamp. Plaintext values are not logged.

Runtime-scoped values are passed only to `docker run`; they are not included in
the Docker build context, build arguments, image metadata, repository files, or
frontend responses. Build-scoped values are synchronized into Forgejo's native
repository Variables or Secrets and referenced only by trusted workflow jobs.
Restart the Space after changing a runtime value so the next container receives
it.

## Cookie-free API for CI and agents

The same encrypted store is available to external automation at
`/runner-api/v1/spaces/{owner}/{repo}/environment`. It uses a Forgejo personal
access token on every request and never accepts a browser cookie. Revoking the
PAT in Forgejo blocks the next request.

Use `read:repository` for list and audit calls. Mutation calls require
`write:repository` plus push permission on the exact repository. NyankoFace also
requires the repository to carry the `space` topic. The default limit is 60
requests per token per minute and can be changed with
`NYANKOFACE_SPACE_API_RATE_LIMIT_PER_MINUTE`.

```bash
export NYANKOFACE_URL="https://nyankoface.example.com"
export FORGEJO_PAT="replace-with-a-forgejo-pat"

# Metadata only. Neither Variable nor Secret values are returned.
curl --fail-with-body \
  -H "Authorization: Bearer ${FORGEJO_PAT}" \
  "${NYANKOFACE_URL}/runner-api/v1/spaces/acme/demo/environment"

# Idempotent upsert or Secret rotation. Add `"restart": true` to apply now.
# `expected_kind` is optional for v1 compatibility; send it for a kind guard.
curl --fail-with-body -X PUT \
  -H "Authorization: Bearer ${FORGEJO_PAT}" \
  -H "Content-Type: application/json" \
  -d '{"kind":"secret","value":"replace-me","enabled":true,"scope":"build"}' \
  "${NYANKOFACE_URL}/runner-api/v1/spaces/acme/demo/environment/SERVICE_TOKEN"

# Disable without deleting. The runtime changes after the next restart.
curl --fail-with-body -X PATCH \
  -H "Authorization: Bearer ${FORGEJO_PAT}" \
  -H "Content-Type: application/json" \
  -d '{"enabled":false}' \
  "${NYANKOFACE_URL}/runner-api/v1/spaces/acme/demo/environment/SERVICE_TOKEN"

# Delete is a successful no-op when the key is already absent.
curl --fail-with-body -X DELETE \
  -H "Authorization: Bearer ${FORGEJO_PAT}" \
  "${NYANKOFACE_URL}/runner-api/v1/spaces/acme/demo/environment/SERVICE_TOKEN"

# Apply all enabled values by recreating the CPU runtime container.
curl --fail-with-body -X POST \
  -H "Authorization: Bearer ${FORGEJO_PAT}" \
  -H "Content-Type: application/json" \
  -d '{"restart":true}' \
  "${NYANKOFACE_URL}/runner-api/v1/spaces/acme/demo/environment/apply"

# Value-free audit history.
curl --fail-with-body \
  -H "Authorization: Bearer ${FORGEJO_PAT}" \
  "${NYANKOFACE_URL}/runner-api/v1/spaces/acme/demo/environment/audit"
```

Every error has a stable `detail.code` and `detail.message`. `429` responses
include `Retry-After: 60`. Interactive API documentation is served at
`/runner-api/docs`; the OpenAPI document is `/runner-api/openapi.json`.

The browser management dialog and this API read and write the same
repository-scoped rows. Secrets remain write-only on both surfaces. Mutations
return `restart_required: true` unless the request performs a restart.

## Rotation, deletion, and recovery

1. Open **Variables & Secrets**.
2. Select **Rotate** or **Edit** to replace a value under the same name.
3. Select **Delete**, then **Confirm delete**, to remove it.

Back up the PostgreSQL database and `space-secrets.key` together. Restoring only one makes existing ciphertext unusable. Never commit the key or a plaintext secret.

The generation migration is not safe with mixed-version writers. Fence environment writes during rollout, or run a single Runner writer until every replica is upgraded.

## Remote GPU workers

CPU Spaces receive settings locally. Remote GPU execution currently fails closed when settings exist because a worker-specific encrypted delivery channel is not configured. Do not fall back to plaintext transport; add envelope encryption and per-worker authorization before enabling this path.

