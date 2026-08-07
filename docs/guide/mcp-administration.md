# MCP administration runbook

`/admin/mcp` is the administrator-only control plane for MCP service-account mappings, client tokens, policy, connection diagnostics, and audit evidence. This runbook describes the operational boundary delivered by [PR #150](https://github.com/Sunwood-ai-labs/NyankoFace/pull/150) and [PR #152](https://github.com/Sunwood-ai-labs/NyankoFace/pull/152). The [Issue #151 evidence index](../evidence/issues/151/README.md) records the exact runtime and visual checks for this documentation.

## Security boundary

- The browser calls `/api/admin/mcp/*`. The frontend BFF verifies Forgejo administrator membership before every request and forwards only bounded requests to the internal `mcp-admin` service.
- Admin BFF API requests at `/api/admin/mcp/*` fail with `401` when anonymous and `403` when the authenticated Forgejo subject is not an administrator. The `/admin/mcp` page itself redirects anonymous users to login and returns `404` for non-admin users or insecure transport. `mcp-admin` has no host-published port and is reachable only on the Compose network.
- The re-authentication form verifies the current Forgejo password directly with Forgejo. The password is not stored, forwarded to the admin service, written to logs, or retained after the form is cleared. The resulting five-minute, HttpOnly proof is bound to the browser session and administrator subject.
- The internal BFF-to-admin credential is read as a Docker secret only by `mcp-admin`. That service copies it with mode `0440` to the private `nyankoface-mcp-admin-bridge` volume; the frontend reads `/run/mcp-admin-bridge/token` read-only. The raw Docker secret is not mounted into the frontend and is never an environment variable or browser value.
- Service-account credentials may reference only names in `NYANKOFACE_MCP_FORGEJO_TOKEN_ALLOWLIST`. Each reference must be a readable, regular, non-symlink file directly below `NYANKOFACE_MCP_FORGEJO_TOKEN_ROOT`. Do not add the internal admin credential to this allowlist.
- Client token plaintext is returned only in a successful issue/rotate response to the already-authenticated BFF and is displayed once. Subsequent state, list, revoke, audit, and connection-test responses do not return it. After the dialog is closed or discarded, the UI no longer holds it and the registry, logs, and audit records do not retain recoverable plaintext.

## Start the MCP profile

Create secrets and MCP state outside the repository. Compose's `./secrets/...` defaults are convenient for local development but are not an external secret boundary. Set the three paths below to absolute locations before starting Compose. This Windows PowerShell example generates only the internal credential; use the deployment's secret-management procedure to populate the Forgejo token file.

```powershell
$secretRoot = Join-Path $env:ProgramData 'NyankoFace\secrets'
$stateRoot = Join-Path $env:ProgramData 'NyankoFace\mcp-state'
New-Item -ItemType Directory -Force $secretRoot, $stateRoot | Out-Null
$hostIdentities = @([Security.Principal.WindowsIdentity]::GetCurrent().Name)
# If Docker Desktop uses another host identity, add that identity explicitly.
# $hostIdentities += 'CONTOSO\nyankoface-docker'
$aclGrants = @($hostIdentities | ForEach-Object { '{0}:(OI)(CI)(F)' -f $_ })
foreach ($path in @($secretRoot, $stateRoot)) {
  icacls.exe $path /reset /T /C | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Failed to reset existing ACLs under $path" }
  icacls.exe $path /inheritance:r /T /C | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Failed to remove inherited ACLs from $path" }
  icacls.exe $path /grant:r $aclGrants /T /C | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Failed to protect ACLs on $path" }
}
$internalTokenPath = Join-Path $secretRoot 'nyankoface-mcp-admin-internal-token'
$forgejoTokenPath = Join-Path $secretRoot 'nyankoface-mcp-forgejo-user-token'
$bytes = New-Object byte[] 48
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
[Convert]::ToBase64String($bytes) | Set-Content -NoNewline -LiteralPath $internalTokenPath
$env:NYANKOFACE_MCP_ADMIN_INTERNAL_TOKEN_FILE = $internalTokenPath
$env:NYANKOFACE_MCP_FORGEJO_USER_TOKEN_FILE = $forgejoTokenPath
$env:NYANKOFACE_MCP_STATE_DIR = $stateRoot
```

Start or rebuild the bounded services, then inspect health without printing secret contents:

```bash
docker compose --profile mcp up -d --build frontend gateway nyankoface-mcp mcp-admin
docker compose --profile mcp ps
```

Do not publish port `8001`, bypass the BFF, or put secret values in `docker-compose.yml`, `.env`, screenshots, issue comments, or client configuration committed to Git.

## Operator flow

1. Open `/admin/mcp` as a Forgejo administrator and complete re-authentication. If the proof is missing, expired, changed, or bound to another session or subject, the request must fail closed.
2. Add or select one service-account mapping. Choose the Forgejo user, an allowlisted secret reference, the smallest required scopes, and explicit repository permissions.
3. Issue a client token with a subset of the mapping's scopes and repositories. Set the shortest practical TTL.
4. While the one-time dialog is open, use **Connection test** to check `initialize`, `tools/list`, and `resources/list`. The result separates reachability, HTTP/authentication failure, JSON-RPC failure, and usable tool/resource counts without echoing the token or upstream error text.
5. Copy the token only into a protected client secret store, then close or discard the dialog. Never put the plaintext in a ticket, shell history, screenshot, browser bookmark, or source file.
6. When a mapping is disabled or remapped, verify that its previous mapping-version tokens are revoked. Rotating a token revokes its predecessor.

### Safe client snippets

These examples intentionally contain placeholders only. Replace `<NYANKOFACE_HOST>` and `<TOKEN_FILE>` locally; never commit a real token.

#### Codex CLI

```powershell
$env:NYANKOFACE_MCP_TOKEN_FILE = '<TOKEN_FILE>'
$env:NYANKOFACE_MCP_TOKEN = (Get-Content -LiteralPath $env:NYANKOFACE_MCP_TOKEN_FILE -Raw).Trim()
codex mcp add nyankoface --url https://<NYANKOFACE_HOST>/mcp --bearer-token-env-var NYANKOFACE_MCP_TOKEN
```

#### Claude Desktop

```json
{
  "mcpServers": {
    "nyankoface": {
      "command": "nyankoface-mcp-stdio",
      "env": {
        "NYANKOFACE_MCP_REMOTE_URL": "https://<NYANKOFACE_HOST>/mcp",
        "NYANKOFACE_MCP_CLIENT_TOKEN_FILE": "<TOKEN_FILE>"
      }
    }
  }
}
```

#### VS Code

```json
{
  "servers": {
    "nyankoface": {
      "type": "http",
      "url": "https://<NYANKOFACE_HOST>/mcp",
      "headers": { "Authorization": "Bearer ${input:nyankoface-token}" }
    }
  },
  "inputs": [
    {
      "id": "nyankoface-token",
      "type": "promptString",
      "description": "NyankoFace MCP token",
      "password": true
    }
  ]
}
```

## Policy and audit

Policy updates include the displayed revision. A concurrent update returns a conflict; reload, inspect the new revision, and submit again. The default remains deny unless an explicit allow applies, and read-only rules deny matching writes.

Audit filters cover actual outcomes (`allowed`, `denied`, `failed`, `replayed`, and `changed`), subject, client, tool, time range, and bounded cursor pagination. Summary counts cover all matching records, not only the current page. Expanded records expose approved detail fields only; they do not return token plaintext, token digests, Forgejo PAT paths, idempotency fingerprints, or audit-chain hashes.

## Recovery runbook

- **Lost token:** revoke it immediately, issue a replacement with the smallest scope, and update the client's protected token store.
- **Suspected service-account compromise:** disable the mapping first, rotate the Forgejo credential secret, remap the account, then issue new client tokens.
- **Policy conflict:** reload before retrying. Never overwrite a revision that was not reviewed.
- **Admin backend unavailable:** check `mcp-admin` health, Docker secret mounts, and lifecycle/policy/audit volume permissions. Do not expose a public port to bypass the BFF.
- **Backup and restore:** back up the token registry and lifecycle audit from the configured `NYANKOFACE_MCP_STATE_DIR`, plus a consistent snapshot of the complete `nyankoface-mcp-state` volume. The snapshot must include the policy and audit databases, `/data/write-safety.sqlite3`, and its adjacent `.hmac-key`; these preserve idempotency and operation-reconciliation history. Restoring only part of this state can repeat an upstream write whose earlier result was unknown. After restore, verify admin/non-admin access, issue a short-lived constrained token, run a connection test, revoke it, and inspect the audit outcome.

## Release QA boundary

Manually inspect the real runtime at desktop and mobile widths in the base, solarpunk, and cyberpunk themes. Check tab wrapping, one-time-secret handling, contrast, controls, footer placement, and horizontal overflow. Screenshot generation is intentionally not a CI gate. The sanitized evidence for the current merged main is in [Issue #151](../evidence/issues/151/README.md).
