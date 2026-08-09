---
title: Operational MCP use-case matrix
description: End-to-end scenarios for agents using NyankoFace with one Forgejo token.
---

# Operational MCP use-case matrix

This matrix represents the work an agent actually performs after connecting to
NyankoFace. Every authenticated request uses the same Forgejo token for the
Forgejo API and the MCP Bearer credential. The live runner never executes a
mutation; write behavior is verified with isolated fixtures.

## Test cases

| Case | Agent workflow | Acceptance checks |
|---|---|---|
| UC-01 | Connect and discover capabilities | unauthenticated initialize is 401; authenticated initialize, initialized notification, tools/list, and resources/list succeed; the OpenAPI resource is advertised |
| UC-02 | Find a published Knowledge repository and inspect it | search_catalog(doc) returns a public repository; get_repository, get_tree, an available file read, and get_knowledge all return non-error results |
| UC-03 | Triage repository issues | list_repositories and list_issues return valid bounded lists; get_issue is exercised when the selected repository has an open issue; a token without Forgejo read:issue is recorded as an upstream permission boundary, not as a false success |
| UC-04 | Plan a change safely | create_issue with preview=true returns a confirmation; the live scenario does not execute a mutation; isolated tests cover confirmation and idempotency execution |
| UC-05 | Enforce authorization boundaries | invalid credentials are rejected; explicit deny/read-only policy, unauthorized repositories, and lifecycle service-account default deny remain covered by contract tests |

## Run the live scenario

Run this from a checkout with a protected token file. Do not put the token on
the command line and do not save the JSON output with credentials.

    python nyankoface-mcp/scripts/run_operational_use_cases.py --url https://nyankoface.example/mcp --token-file C:\restricted\forgejo.token --client codex --client-version 1.0

The runner discovers a public doc repository and a push-authorized repository
from the caller-visible catalog. If the live dataset has no open issue, UC-03
records get_issue as skipped_no_open_issue. If the Forgejo token lacks
read:issue, it records skipped_upstream_permission with the upstream error
without treating the call as successful. The fixture test still exercises the
complete list-to-detail flow. Use issue-owner, issue-repo, and issue-number
when a controlled issue fixture is available, together with
require-issue-detail.

## Evidence requirements

- Record only statuses, counts, repository identities, and server revision.
- Never print or commit token values, token files, raw client logs, or
  confirmation values.
- Keep live writes preview-only. Verify actual execution, confirmation
  binding, and idempotency in isolated tests with a fake upstream.
- A successful initialize or tools/list is not sufficient evidence for this
  matrix; each case must reach its representative tools/call.
