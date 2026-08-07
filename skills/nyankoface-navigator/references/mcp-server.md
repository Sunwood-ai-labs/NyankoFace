# NyankoFace MCP Server

Use the official endpoint when an agent must search, read, or safely update Issues in an existing
NyankoFace deployment. Use an `mcp` topic repository when publishing a distinct
third-party MCP implementation to the catalog; these are different surfaces.

## Connection workflow

1. Obtain the deployment's HTTPS `/mcp` URL.
2. Ask for the smallest scopes needed: `catalog:read`, `repos:read`,
   `issues:read`, `issues:write`, `spaces:read`, `pages:read`, `pipelines:read`,
   `metrics:read`, `spaces:run`, `variables:write`, `secrets:write`,
   `pages:deploy`, or `pipelines:write`.
3. Keep the plaintext NyankoFace token in the client's secret store/environment.
4. Configure Codex or VS Code from `nyankoface-mcp/README.md`.
5. Initialize, list tools/resources, and call one operation.
6. Treat authorization/not-found as intentionally indistinguishable. Never ask
   for an admin PAT or ask the operator to paste a Secret into the conversation.

Supported reads include caller-visible repository lists, ref-fixed trees and
files, real catalog kinds (`skill`, `mcp`, `prompt`, and `doc` included), and
published Knowledge. Prefer the official prompts for Space diagnosis, Pages
publication planning, Pipeline failure analysis, topic validation, and content
publication planning. Treat `_meta.etag`, `_meta.updated_at`, and pagination as
the cache and continuation contract. Never synthesize a ref or follow a path
containing literal or encoded traversal.
Tree Resource URIs encode refs as unpadded UTF-8 base64url in the `ref_b64`
segment; use plain refs with the `get_tree` Tool.

The endpoint is stateless Streamable HTTP. A retry may reach another instance;
do not depend on `Mcp-Session-Id`, sticky routing, or implicit server memory.

For `create_issue`, `update_issue`, or `comment_issue`, always:

1. send the complete payload with `preview: true`;
   the token must have both `issues:write` and `repos:read`;
2. inspect the canonical target and payload fingerprint;
3. send the unchanged payload with `preview: false`, the returned short-lived
   `confirmation`, and a newly generated `idempotency_key`;
4. preserve that key for an exact retry and never retry
   `upstream_outcome_unknown` with another key.

Never reuse a confirmation for another subject, Tool, repository, or edited
payload. Do not ask for a Secret in Issue text.

The same workflow applies to `start_space`, `stop_space`, `restart_space`, `deploy_pages`,
`dispatch_pipeline`, `cancel_pipeline`, and `rollback_pipeline`; each also needs
`repos:read` and its matching write scope. After execution, retain `operation_id` and read
`nyankoface://operations/{operation_id}` (or call `get_operation`) until terminal.
Operation reads recheck current Forgejo access. Only one operation may run per Space, Pages
repository, Pipeline repository, or Pipeline run target. On timeout/disconnect, preserve the original key and
inspect the operation; never generate a new key to force another dispatch.
An exact-key retry while pending returns the existing URI; invalid cancel/rollback state is definite.
After verifying an unknown outcome independently, preview and confirm
`reconcile_operation` with `applied` or `not_applied`; never release the lock by hand.

Space Variable, Secret, and apply tools respectively need `variables:write`, `secrets:write`, or `spaces:run`, plus `repos:read`. Stage before apply; keep one
idempotency key through unknown outcomes. Load Secrets directly from a trusted
store and never expose values in conversation or metadata. Timeouts are 120s
for set/delete and 720s for apply. Keep the HMAC `.hmac-key` owner-only beside the write-safety database on shared storage; back up/restore both together.

For operational inspection, prefer `get_space_environment_metadata`,
`list_pipeline_runs`, `get_pipeline_run`, and `get_metrics`. Environment
metadata never contains values. Treat `_meta.etag` as payload revalidation
metadata, honor `_meta.cache`, and use structured error `action` only after
checking `retryable`. The pipeline-runs and OpenAPI resources use JSON MIME.

Do not claim Claude Desktop support for this static-Bearer Phase 1 endpoint.
Claude Desktop remote connectors require the Settings > Connectors flow and
authless or OAuth authorization. OAuth, client distribution, and live Claude
Desktop verification are tracked in #116.
