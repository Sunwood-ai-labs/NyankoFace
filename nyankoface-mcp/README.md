# NyankoFace MCP Server

Official MCP adapter for NyankoFace. It exposes the NyankoFace catalog,
caller-visible repositories, ref-fixed trees and files, Knowledge articles,
issues, and Space, Pages, and Pipeline status through one stateless Streamable
HTTP endpoint at `/mcp`, plus preview-first Issue and Space environment writes.

The catalog kinds are `model`, `dataset`, `space`, `skill`, `mcp`, `prompt`,
`doc`, `automation`, `character`, and `benchmark`; they are backed by real
NyankoFace repository data. Catalog and repository lists use bounded pagination.
JSON results expose `_meta.mime_type`, `_meta.updated_at`, `_meta.etag`, and
`_meta.cache_control`; files report `text/markdown` or `text/plain`.

Resources include `nyankoface://catalog/{kind}`,
`nyankoface://repos/{owner}/{repo}/tree/{ref_b64}`, and
`nyankoface://knowledge/{owner}/{slug}`. Five official prompts cover Space
diagnosis, Pages publication planning, Pipeline failure analysis, topic
validation, and content publication planning. Prompts only prepare evidence
and plans; only the explicitly documented Issue tools mutate state.

Tree Resource refs use unpadded UTF-8 base64url so branch names remain one URI
segment. For example, `main` is `bWFpbg` and `refs/heads/release` is
`cmVmcy9oZWFkcy9yZWxlYXNl`. The `get_tree` Tool continues to accept the plain
ref.

## Security boundary

- Every request requires either an opaque NyankoFace Bearer token with audience
  `nyankoface-api-v1`, or the caller's Forgejo token itself.
- Only the SHA-256 digest and non-secret lifecycle metadata are stored. Plaintext
  is returned exactly once by issue/rotation and cannot be listed later.
- Scopes are checked per tool/resource: `catalog:read`, `repos:read`,
  `issues:read`, `issues:write`, `spaces:read`, `variables:write`,
  `secrets:write`, `spaces:run`, `pages:read`, and `pipelines:read`.
  Repository counters use the separate `metrics:read` scope.
- Agents may send the same Forgejo token they already use for Forgejo as the
  MCP Bearer. NyankoFace validates that token against Forgejo `/user` and
  forwards the exact token upstream, so Forgejo remains the source of truth for
  repository read and write permissions. No second MCP credential or separate
  permission mapping is required for this mode.
- A caller-specific Forgejo token may still be mounted by file for an opaque
  lifecycle token mapping. No administrator PAT is used or returned. Missing,
  disabled, stale, or insufficient lifecycle mappings fail closed before an
  upstream request.
- A directly presented Forgejo token is never written to the lifecycle
  registry, logs, audit records, or MCP results. It remains request-scoped and
  is only passed to Forgejo/Runner as the upstream credential.
- Token scopes and repository constraints are checked on every request. Revoke,
  expiry, rotation, service-account disable, and remapping take effect on the
  next request.
- Private repositories are resolved using the caller identity. Credential file
  paths are denied; secret-shaped keys, known token formats, and secret
  assignments in text are redacted even for an authorized repository.
- The server is stateless. It returns no `Mcp-Session-Id` and can serve retries
  on another instance without sticky sessions.
- Issue writes require both `issues:write` and `repos:read`, preview, a
  subject/Tool/target/payload-bound five-minute confirmation, a current Forgejo
  push-permission check, and an idempotency key.
  Safety state is durable in the `nyankoface-mcp-state` volume. Audit events store
  metadata and a payload fingerprint, never Issue text or credentials.

Writable environment tools are `set_space_variable`, `delete_space_variable`,
`set_space_secret`, `delete_space_secret`, and `apply_space_environment`, in
addition to the documented Issue, Space lifecycle, Pages, and Pipeline tools.

## Write an Issue safely

Call an Issue Tool once with `preview: true` or `dry_run: true`. After reviewing
the returned target and fingerprint, repeat the exact payload with
`preview: false`, the returned `confirmation`, and a unique `idempotency_key`.
The same key and payload replays the first result without another mutation;
changed payloads and concurrent duplicates are rejected. Do not retry an
`upstream_outcome_unknown` result with a new key. Definite responses retain a
sanitized error code and explicit `retry_safe` classification instead of being
reported as an unknown transport outcome.

## Write Space environment safely

Variable, Secret, and apply tools need `variables:write`, `secrets:write`, or `spaces:run`, plus `repos:read` and push access. Stage a kind-bound batch, then apply it; timeouts are 120s for set/delete and 720s for apply. Values never
appear in metadata, errors, logs, audit, operations, or idempotency state. Load
Secrets directly from a trusted store. Keep the HMAC `.hmac-key` owner-only beside the write-safety database on shared storage and back up both together.

## Operational reads

| Tool / resource | Result |
|---|---|
| `get_space_environment_metadata` | environment `name`, `configured`, and `updated_at` only; never values |
| `list_pipeline_runs`, `get_pipeline_run` | bounded run listing and one run detail |
| `get_metrics` | repository view/like counters |
| `nyankoface://pipelines/{owner}/{repo}/runs` | first bounded page of pipeline runs as JSON |
| `nyankoface://api/openapi` | redacted Runner OpenAPI document as JSON |

Every repository operation rechecks the caller's current Forgejo read access.
Operational tools and all JSON resources include `_meta.mime_type`,
`_meta.etag`, cache guidance, and an `updated_at` value when the upstream data
provides one. Paginated results
also include page, limit, total count, and total pages. The ETag is carried in
the MCP JSON payload for client-side revalidation; it is not an HTTP response
header. Errors are JSON objects with a stable code, safe message, retryability,
and a suggested action. They never include upstream bodies, internal URLs, or
credentials.

## Authentication modes

For an agent that already authenticates to Forgejo, use that exact Forgejo
token as the MCP Bearer. The two requests below intentionally carry the same
secret value; do not mint or configure a second MCP token:

```http
Authorization: Bearer <FORGEJO_TOKEN>
```

NyankoFace checks the token with Forgejo on authentication and uses Forgejo's
current repository permissions for every repository operation. This means a
Forgejo token with push access can perform an MCP write, while a token without
that access receives the same denial it would receive from Forgejo. Preview,
confirmation, idempotency, policy, and secret-redaction safeguards remain
active for MCP writes.

Opaque NyankoFace lifecycle tokens remain available for clients that need a
separate, short-lived, repository- and scope-limited credential. That is an
optional compatibility mode, not a requirement for agents using Forgejo
tokens directly.

## Token lifecycle

The registry is a root-owned lifecycle store. Use the offline operator while
the future admin UI reuses the same backend. The OS permission on the registry
is the CLI authorization boundary; `--actor` and the reauthentication timestamp
are audit context supplied by a trusted local session, not end-user claims.

```bash
REGISTRY=secrets/nyankoface-mcp/registry.json
NOW=$(date +%s)
export PYTHONPATH=nyankoface-mcp
export NYANKOFACE_MCP_REGISTRY_READER_GID=10001

python -m nyankoface_mcp.admin --registry "$REGISTRY" --actor user:admin \
  --reauthenticated-at "$NOW" create-service-account service:codex-reader \
  --forgejo-user-id 42 \
  --forgejo-token-file /run/secrets/nyankoface-mcp-forgejo-user-token \
  --allowed-scope catalog:read --allowed-scope repos:read \
  --repository-permission nyankoface/example=read

python -m nyankoface_mcp.admin --registry "$REGISTRY" --actor user:admin \
  --reauthenticated-at "$NOW" issue-token service:codex-reader \
  --client-id codex --scope catalog:read --scope repos:read \
  --repository nyankoface/example --ttl-seconds 2592000
```

Run these commands as the root owner of the lifecycle store. The configured
reader GID matches the unprivileged MCP container. Atomic replacements retain a
root-owned `0640` registry inside a `0750` directory, so the container can read
the registry while other host users cannot. Do not grant this group write access.
At authentication time NyankoFace resolves the mounted PAT through Forgejo `/user`
and rejects the NyankoFace token unless that user ID equals the mapped subject.

The issue command prints the token once. Put it directly into the client secret
store; do not redirect it into Git, logs, chat, or normal application storage.
`list-tokens` never returns a plaintext token, digest, or Forgejo secret path.
Use `rotate-token TOKEN_ID`, `revoke-token TOKEN_ID`,
`disable-service-account SUBJECT_ID`, or `remap-service-account` for lifecycle
operations. All mutations require an administrator context reauthenticated no
more than 300 seconds ago and emit JSONL audit records without credentials.
The state transition and a secret-free audit outbox entry are written together;
if the JSONL sink is unavailable, the operation still returns its result and a
later mutation retries delivery. Writer serialization uses an OS advisory lock,
so a terminated operator cannot leave the lifecycle store permanently locked.

Store the least-privileged caller Forgejo PAT in its mounted Docker Secret.
Compose mounts `NYANKOFACE_MCP_STATE_DIR` read-only at `/run/nyankoface-mcp` so an
atomic host-side registry replacement is visible on the next request; mounting
one registry file would pin the old inode and delay revocation. Neither the
registry nor PAT is exposed through environment variables or MCP results.

Every record with `issues:write` must define an explicit, stable `subject_id`
that is unique among write-capable records. Missing or duplicate write subjects
fail closed; `client_id` fallback is available only to read-only records.

## Run

```bash
docker compose --profile mcp up -d --build nyankoface-mcp gateway
```

The default response is SSE. Set `NYANKOFACE_MCP_JSON_RESPONSE=true` when a client
requires a single JSON response. Both modes use the same stateless contract.

## Install the versioned package

Release artifacts contain a platform-independent wheel, source distribution,
and `SHA256SUMS`. Verify the checksum before installing the wheel:

```bash
sha256sum --check SHA256SUMS
python -m pip install ./nyankoface_mcp-0.1.0-py3-none-any.whl
nyankoface-mcp --version
```

The supported runtime is Python 3.11 through 3.13. Package metadata pins the
direct MCP/HTTP dependencies; `requirements.lock` fixes the complete container
runtime. The image label `org.opencontainers.image.version` and installed
package version must both be `0.1.0`. Release artifacts built from an
`nyankoface-mcp-v*` tag receive GitHub build-provenance attestations, verifiable
with `gh attestation verify ARTIFACT -R Sunwood-ai-labs/NyankoFace`.

The installed commands are:

- `nyankoface-mcp --version`, `validate-config`, `stdio`, and `serve-http`;
- `nyankoface-mcp-stdio`, the command used by local stdio clients;
- `nyankoface-mcp-server`, the official Streamable HTTP server image entry point.

## Stateless stdio adapter

Set the non-secret endpoint and inject the bearer from the client/OS secret
store into the child process environment:

```bash
export NYANKOFACE_MCP_REMOTE_URL="https://nyankoface.example/mcp"
export NYANKOFACE_MCP_TOKEN="$(secret-tool lookup service nyankoface-mcp)"
nyankoface-mcp validate-config
nyankoface-mcp-stdio
```

As an alternative to `NYANKOFACE_MCP_TOKEN`, set
`NYANKOFACE_MCP_CLIENT_TOKEN_FILE` to a service-account-readable file populated
by the secret store. Exactly one token source is required. The adapter accepts
no credential argument, emits only MCP JSON-RPC on stdout, sanitizes remote
errors, and starts no listener. Each input message becomes an independent
authenticated `POST`; remote session headers are never carried into the next
request, so the adapter adds neither persistence nor sticky routing.
Environment proxy discovery is disabled for this bearer-authenticated
transport. `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, and their lowercase forms
are ignored; use a directly reachable endpoint and configure a private CA with
`NYANKOFACE_MCP_CA_BUNDLE` when required.

MCP cancellation over independent Streamable HTTP requests is best-effort:
the protocol has no cross-request admission acknowledgement. The adapter drops
requests cancelled before forwarding, forwards active cancellation on reserved
capacity, and treats the cancelled local ID as terminal so a late remote JSON
or SSE response is never emitted as success. If reserved cancellation capacity
is exhausted, the adapter fails instead of silently dropping the notification.
Write tools remain protected independently by confirmation and idempotency.

## Clients

Codex can register the inherited-environment stdio command:

```bash
codex mcp add nyankoface -- nyankoface-mcp-stdio
```

Claude Desktop uses the same command in `claude_desktop_config.json`; launch
Claude Desktop from a secret-store wrapper that provides
`NYANKOFACE_MCP_TOKEN`, rather than writing it in this file:

```json
{
  "mcpServers": {
    "nyankoface": {
      "command": "nyankoface-mcp-stdio",
      "env": { "NYANKOFACE_MCP_REMOTE_URL": "https://nyankoface.example/mcp" }
    }
  }
}
```

VS Code (`.vscode/mcp.json`) can keep the token in a masked input rather than
source control:

```json
{
  "servers": {
    "nyankoface": {
      "type": "stdio",
      "command": "nyankoface-mcp-stdio",
      "env": {
        "NYANKOFACE_MCP_REMOTE_URL": "https://nyankoface.example/mcp",
        "NYANKOFACE_MCP_TOKEN": "${input:nyankoface-token}"
      }
    }
  },
  "inputs": [{
    "id": "nyankoface-token",
    "type": "promptString",
    "description": "NyankoFace MCP token",
    "password": true
  }]
}
```

These are baseline schemas, not live-client certification. Live Codex, Claude
Desktop, and VS Code evidence remains in the dedicated client issue.

## Upgrade, rollback, and uninstall

Install a verified newer wheel with `python -m pip install --upgrade ./WHEEL`.
Restart the client so it launches the new entry point. Roll back by installing
the previously retained, checksum-verified wheel with `--force-reinstall`.
Remove the adapter with `python -m pip uninstall nyankoface-mcp`; then delete its
client entry and revoke its bearer token. The server/image rollback procedure
is the same: select the earlier version tag, verify its provenance and digest,
then redeploy that exact image. Never reuse a token exposed during debugging.

See [the English guide](../docs/guide/mcp-server.md) or
[日本語ガイド](../docs/ja/guide/mcp-server.md) for resources, threat model, and
verification.

The two-container TLS load-balancing, retry, failover, and recovery contract is
in the [English HA runbook](../docs/guide/mcp-high-availability.md) and
[日本語HA runbook](../docs/ja/guide/mcp-high-availability.md). This topology is
single-Docker-host only; it does not claim NFS or multi-host SQLite support.

## Verification

```bash
python -m pip install -r nyankoface-mcp/requirements-dev.txt
PYTHONPATH=nyankoface-mcp python -m pytest -q nyankoface-mcp/tests
SOURCE_DATE_EPOCH=1767225600 python nyankoface-mcp/scripts/build_distribution.py --out-dir dist
docker compose --profile mcp config --quiet
```

The protocol tests cover initialize/capability negotiation, JSON and SSE,
stateless retry across server instances, invalid tokens, read-only tool schema,
private/other-subject repository denial, bounded file reads, ref/path traversal,
pagination/cache metadata, official prompts, and secret redaction.
Lifecycle coverage additionally includes one-time material, enumeration
resistance, constant-work digest lookup, privilege escalation, repository
constraints, mapping failure, expiry/revocation, leakage, and concurrent
rotation, audit-sink failure recovery, and terminated-operator lock recovery.
Write coverage includes bounded schemas, confirmation binding, cancellation
safety, and idempotent concurrency.

Primary references: the [MCP Transport specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
and the pinned [MCP Python SDK v1.26.0](https://github.com/modelcontextprotocol/python-sdk/tree/v1.26.0).
