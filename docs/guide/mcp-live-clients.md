---
title: Live MCP client QA
description: Reproduce secret-safe NyankoFace MCP checks in Codex, Claude Desktop, and VS Code.
---

# Live MCP client QA

This guide separates **real-client manual QA** from the protocol checks that are
safe to automate. Never commit a token, PAT, client log, or client configuration
containing a literal credential.

Agents use one credential: the same Forgejo token is sent to Forgejo and as the
MCP Bearer. A separate MCP lifecycle token is only needed when deliberately
testing the optional scoped service-account mode.

## Supported client paths

| Client | Supported transport used here | Credential handling |
|---|---|---|
| Codex CLI | remote Streamable HTTP | the Forgejo token from an inherited environment variable |
| Claude Desktop | local stdio adapter | the same Forgejo token from a protected file |
| VS Code | remote Streamable HTTP | the same Forgejo token in the password input |

Codex can register the remote endpoint without putting the credential on its
command line:

```powershell
$env:NYANKOFACE_MCP_TOKEN = (Get-Content $env:NYANKOFACE_FORGEJO_TOKEN_FILE -Raw).Trim()
codex mcp add nyankoface --url https://nyankoface.example/mcp `
  --bearer-token-env-var NYANKOFACE_MCP_TOKEN
```

Claude Desktop's remote custom connectors use authless or OAuth authorization;
they do not provide a static bearer field. Install the verified host package
before using the local stdio command (from this checkout:
`python -m pip install --upgrade ./nyankoface-mcp`, or install the verified wheel),
validate its non-secret configuration, and register the local stdio adapter in
`%APPDATA%\Claude\claude_desktop_config.json` instead:

```json
{
  "mcpServers": {
    "nyankoface": {
      "command": "nyankoface-mcp-stdio",
      "env": {
        "NYANKOFACE_MCP_REMOTE_URL": "https://nyankoface.example/mcp",
        "NYANKOFACE_MCP_CLIENT_TOKEN_FILE": "C:\\restricted\\forgejo.token"
      }
    }
  }
}
```

Fully quit and restart Claude Desktop after changing the file. For packaged
Windows installs, confirm the effective roaming path under the app package's
`LocalCache` rather than assuming the unpackaged path.

For VS Code, copy [`nyankoface-mcp/examples/vscode-mcp.json`](https://github.com/Sunwood-ai-labs/NyankoFace/blob/main/nyankoface-mcp/examples/vscode-mcp.json)
to `.vscode/mcp.json` or the user-profile MCP configuration, then replace only
the `<NYANKOFACE_HOST>` host placeholder; keep the template's `/mcp` path.
Keep the password input and do not replace it with a literal token.

These examples were checked against the official
[Codex MCP guide](https://developers.openai.com/codex/mcp/),
[VS Code MCP configuration reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration),
[Claude Desktop local-server guide](https://modelcontextprotocol.io/docs/develop/connect-local-servers),
and [Claude remote connector guide](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp).

## Manual checklist

For the full agent workflow matrix, see [Operational MCP use-case matrix](mcp-operational-use-cases.md).

1. For agent-mode QA, use the Forgejo token already assigned to that agent; do not provision a second MCP token. Use a different short-lived lifecycle credential only when testing the optional lifecycle mode.
2. Record client, OS, server revision, and execution time without recording the
   token value or token-file contents.
3. Confirm initialize/capability negotiation, Tools, Resources, and one bounded
   read. A client-native resource browser is preferable to an AI chat prompt.
4. Repeat protocol checks with valid, revoked, and invalid Forgejo credentials.
   For lifecycle mode, also check insufficient-scope, expired, and revoked
   states. Expect `401` before initialization for invalid credentials. Forgejo
   repository read/write authorization must match the same token used against
   Forgejo directly.
5. If a private deployment has multiple instances, perform any instance-isolation
   check inside that private environment. Do not publish instance names, image
   identifiers, addresses, or runtime identifiers.
6. Scan the sanitized summary for credential material before committing it.
7. Snapshot raw native logs outside Git, scan them against every QA credential,
   and commit only source labels, byte counts, SHA-256 values, and sanitized
   state records. A blocked native run must remain `blocked`, even when its
   protocol identity passes.

The helper scripts are intentionally separate from the desktop QA:

```bash
bash nyankoface-mcp/scripts/provision_live_client_qa.sh
python nyankoface-mcp/scripts/run_live_client_protocol.py --help
```

The provisioner writes root-only credentials outside Git and prints only a
secret-free count. The protocol runner reads one token file, supports expected
authentication failures, and fails if the credential appears in its summary.
CI may exercise these scripts and protocol behavior; CI must not claim desktop
UI or screenshot coverage.

## Versioned result for issue #130

This public snapshot retains the protocol QA procedure and client-safety
contracts. Deployment-specific result records, instance counts, image digests,
runtime identifiers, raw logs, and screenshots are intentionally kept in
private working records rather than published here.

Raw artifacts should remain outside Git. Record only the minimum sanitized
result needed for review, revoke temporary credentials, restore client
configuration, and confirm that no token or private deployment identifier is
included before sharing a report.
