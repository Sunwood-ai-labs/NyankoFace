---
name: nyankoface-issue-report
description: Stage reproducible, secret-free NyankoFace bug and improvement reports in a shared outbox, with deterministic Markdown, duplicate fingerprints, redaction, and bounded rate limits. Use when an agent observes a platform bug, regression, or improvement that should be routed to NyankoFace Issues without giving the agent GitHub credentials.
---

# NyankoFace Issue Report

Stage an observation locally, then let an authenticated operator search and
publish it. Agents never need GitHub credentials and must not create Issues
directly.

## Agent workflow

1. Confirm that the observation came from a reproducible request, log, or UI
   result. Do not turn guesses, private prompts, credentials, or personal data
   into a report.
2. Set `NYANKOFACE_ISSUE_OUTBOX` to the shared outbox path mounted for the
   agent. Keep the path outside the repository checkout.
3. Run `scripts/stage_report.py stage` with a title, summary, environment,
   reproduction steps, expected and actual behavior, impact, evidence, a
   suggested fix, the agent slug, and the observed source.
4. Share only the returned report ID and status. Do not print, copy, or attach
   the outbox file contents to an agent conversation.

The command redacts common bearer tokens, API keys, passwords, secret-shaped
assignments, private-key blocks, credentials in URLs, and secret paths before
writing. It generates a stable fingerprint, refuses repeated submissions, and
enforces per-agent hourly and daily limits. See
[references/report-contract.md](references/report-contract.md) for the exact
schema and field limits.

Example:

```bash
python scripts/stage_report.py stage \
  --outbox "$NYANKOFACE_ISSUE_OUTBOX" \
  --kind bug \
  --title "MCP initialize returns 426" \
  --summary "The public Streamable HTTP endpoint rejects initialize before MCP authentication." \
  --environment "HTTPS deployment through the configured gateway" \
  --reproduction-step "POST a JSON-RPC initialize request to the advertised /mcp URL." \
  --reproduction-step "Send Content-Type application/json and the Streamable HTTP Accept header." \
  --expected "The request reaches the MCP route and returns the documented MCP response." \
  --actual "The gateway returns HTTP 426 with an empty body." \
  --impact "Agents cannot use the official MCP route." \
  --evidence "HTTP status and response headers observed by the agent." \
  --suggested-fix "Check TLS termination and add an initialize regression test." \
  --reporter black-hermes \
  --source https://example.invalid/
```

## Operator workflow

Run `scripts/publish_report.py publish` from an operator environment that has
authenticated `gh` access. The script searches open Issues before creating
anything, applies the same rate limit, writes the Markdown body through a
temporary body file, and moves a successfully published record out of
`pending/`. It never accepts a token argument or puts `GH_TOKEN` in the
outbox.

```bash
python scripts/publish_report.py publish \
  --outbox "$NYANKOFACE_ISSUE_OUTBOX" \
  --repo Sunwood-ai-labs/NyankoFace \
  --report-id REPORT_ID
```

If duplicate candidates are found, keep the staged record pending and record
the disposition in the operator log. Do not force publication without a
human decision. If the GitHub command fails, the report remains pending for a
safe retry.

## Safety boundary

- Keep the outbox on a private shared volume with agent write access and
  operator read/publish access; do not mount GitHub credentials into agent
  containers.
- Treat `source` and `evidence` as public Issue content after publication.
- Do not include request headers, tokens, PATs, passwords, private prompts,
  secret values, raw logs, personal data, or private host details.
- Keep the generated report ID, not the report body, in agent-facing status
  messages.
