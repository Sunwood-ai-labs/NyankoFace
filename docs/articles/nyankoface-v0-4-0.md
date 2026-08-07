---
title: Connect safely, operate auditably
type: article
description: How NyankoFace v0.4.0 turns agent access into a scoped, recoverable, and observable platform boundary.
readingTime: 7 minutes
tags: [release, mcp, security, operations]
---

![NyankoFace v0.4.0 release header](/releases/release-header-v0.4.0.svg)

# Connect safely, operate auditably

An agent interface becomes useful when it can do more than answer a question. It also becomes risky at that moment. NyankoFace v0.4.0 treats the MCP endpoint as a platform boundary: identify the caller, narrow the scope, make the intended mutation explicit, preserve what happened, and keep the next request independent from the previous process.

## Start with a stateless read boundary

The official MCP server exposes catalog, repository, Knowledge, Issue, Space, Pages, Pipeline, metrics, and OpenAPI data through scoped Tools and Resources. A request is authorized against the caller's current Forgejo identity and repository permission. A private repository that the caller cannot see is not revealed by a different error from a missing repository.

The boundary is intentionally boring to operate. Streamable HTTP does not create a server-side conversation, and the next request can land on either replica. Resource calls use the same authorization and redaction path as Tools, so a client cannot bypass a check by changing primitives.

## Turn a write into a small ceremony

An Issue comment, a Space variable, a Secret, a Pages deployment, or a Pipeline control is not just another HTTP call. The client first previews the canonical target and payload, then repeats the exact payload with a short-lived confirmation and an idempotency key. The server binds that confirmation to the subject, Tool, target, and payload fingerprint.

Durable leases separate work that has not dispatched from work whose upstream result is unknown. If the connection disappears after dispatch, NyankoFace preserves the unknown outcome instead of guessing that a retry is safe. Reconciliation is an explicit operator action. Audit rows record identity, target, outcome, request, and timing without storing Issue text, tokens, PATs, or Secret values.

That shape makes failure visible without making duplicate mutation the default recovery strategy.

## Package the same boundary for local clients

Some clients start a command and speak newline-delimited JSON-RPC rather than opening a remote HTTP connection. The versioned `nyankoface-mcp` distribution includes a stdio adapter for that path. It forwards each request as an independent authenticated HTTP request, keeps the bearer in an environment or protected token file, ignores process-level proxy discovery, bounds queues, and suppresses late responses after cancellation.

Codex, Claude Desktop, and VS Code each have a documented setup path. The live-client evidence records startup, invalid-credential, read-only, and representative read behavior without committing raw tokens or client configuration. The remote static-Bearer endpoint remains distinct from Claude Desktop's OAuth-oriented remote connector path; the local stdio launcher is the compatibility baseline.

## Let replicas fail independently

The MCP Compose profile runs two server processes behind nginx. Policy, audit, idempotency, and write-safety state live on a shared coordination boundary, while HTTP request handling remains stateless. HA checks make each replica the sole backend in turn and confirm that initialization, tool/resource discovery, and a representative read still land on the expected instance.

The practical benefit is not that a failure disappears. It is that a single instance can be removed, restarted, or replaced without turning process-local conversation state into a hidden dependency.

## Give operators a control plane

The `/admin/mcp` console makes token lifecycle, service-account mapping, policy revisions, connection diagnostics, and audit evidence visible to administrators. Fresh Forgejo reauthentication protects the browser flow. The internal bridge credential is a Docker Secret, service-account token references are allowlisted, and a client token is displayed only once.

This is the same design principle as the client boundary: access is scoped, state transitions are explicit, and the evidence needed to recover is kept without retaining the credential itself.

Continue with the [full v0.4.0 release notes](../guide/releases/v0.4.0.md), the [MCP Server guide](../guide/mcp-server.md), or the [MCP administration runbook](../guide/mcp-administration.md).
