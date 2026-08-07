# NyankoFace API authentication

Use this reference for management automation that controls repositories, Issues,
Spaces, Secrets, Pipelines, metrics, or reactions.

## Target contract

- Prefer the public `/api/v1` facade and an opaque NyankoFace Bearer token.
- Request every scope required by the action matrix and no broader scopes.
- Send a unique `Idempotency-Key` for mutating `POST`, `PUT`, `PATCH`, and `DELETE`
  requests. Reuse it only when retrying the exact same payload.
- Human tokens are scope-only and are not repository-bound; NyankoFace checks the
  mapped human's current Forgejo permission on every resource request. Use an
  explicit immutable resource grant when a repository-bound service account is
  required.
- Bootstrap that service-account grant only through
  `POST /api/v1/admin/service-account-resource-grants`. It requires a current
  administrator, reauthentication within 300 seconds, and current Forgejo
  owner/administrator authority on every target. Bindings are immutable;
  revoke the old grant before replacing one. If its original owner departs, a
  freshly reauthenticated successor administrator with current authority on
  every target can perform the audited revocation.
- Each service-account grant stores immutable `allowed_scopes` and target
  records shaped as `{repository_id, required_permission}`. The permission is
  derived from the action matrix at grant creation. Every resource request
  rechecks that the dedicated Forgejo user meets each target record and the
  requested action's permission; it is not an ambiguous presence-only check.
- Every service-account token stores the immutable `resource_grant_id` selected
  at issue. Rotation preserves that exact ID, requests resolve only that grant's
  current version, and revocation selects tokens by the matching ID. A token
  bound to an old grant never adopts a replacement grant.
- Requested human scopes are capped by the authoritative, default-empty
  per-subject grant. An administrator with fresh reauthentication manages that
  grant through `/api/v1/admin/subjects/{subject_id}/scope-grants`; a grant
  reduction immediately revokes tokens that no longer fit it.
- Token issue and rotation return plaintext only in the initial
  `Cache-Control: no-store` response. A same-key retry returns
  `409 idempotency_result_not_replayable` and non-secret operation metadata,
  never the credential and never a second mutation.
- Treat Secret values as write-only. Never print, cache, inspect, or expect them
  in a response.
- Surface the API `request_id` when reporting failures.
- Honor `429` retry metadata. NyankoFace enforces shared deployment-wide 60-second
  quotas and burst buckets before credential lookup or protected stores; do not
  retry around those limits.
- Store tokens in the operating system credential store or an injected secret;
  never place them in repository files, command history, URLs, or screenshots.

The authoritative [scope and security contract](https://github.com/Sunwood-ai-labs/NyankoFace/blob/main/docs/contracts/nyankoface-api-v1-security.json)
and [unified API ADR](https://sunwood-ai-labs.github.io/NyankoFace/guide/unified-api)
live in the NyankoFace repository and public documentation.

## Transition rule

Until an equivalent facade route is released, a documented legacy Forgejo PAT
or Agent-key route may be used. Keep that credential isolated to the call, and
do not silently reinterpret it as an NyankoFace token. Follow advertised
`Deprecation`, `Sunset`, and successor links, then migrate before the removal
date.

## Native Git boundary

Git HTTPS/SSH clone and push, Git LFS, and unsupported advanced Forgejo APIs stay
native. Use Forgejo Git credentials for those operations. Never send an
NyankoFace API token as a Git password and never proxy Git data through `/api/v1`.
