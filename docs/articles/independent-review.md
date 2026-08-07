---
title: Put another set of eyes before merge
type: article
description: How NyankoFace turns specialist agents, an explicit coordinator, and independent evidence into a safe auto-merge gate.
readingTime: 9 min read
updated: 2026-07-21
tags: [agents, review, auto-merge, evidence]
related:
  - title: Agent operations
    link: /wiki/agent-operations
    note: Reference the identities and state transitions.
  - title: Automated maintenance guide
    link: /guide/automated-maintenance
    note: Configure and run the workflow.
---

# Put another set of eyes before merge

Automation becomes dangerous when “finished” and “approved” collapse into the same event. NyankoFace deliberately keeps them separate.

## A visible chain of responsibility

A user mentions `@glm-maintainer`. The maintainer classifies the request and visibly delegates to one specialist account: design, coding, or documentation. That account runs Claude Code `/goal`, changes the repository, executes relevant checks, and publishes a pull request with evidence.

Then the work stops moving forward.

The maintainer explicitly mentions `@review-agent`. The reviewer receives the pull-request URL and exact head SHA, but a read-only contract. It must inspect the requirement, diff, tests, regressions, security implications, and—when the interface changed—the running application at mobile and desktop sizes.

## Why the SHA matters

An approval without an immutable subject is only an opinion about the past. The reviewer records `reviewed_sha`; immediately before merge, the wrapper asks Forgejo for the current head again. If those values differ, merge is refused.

The merge request also includes Forgejo's `head_commit_id`. This gives the server one final chance to reject a stale decision.

## Fail closed, visibly

The gate rejects the PR when any requirement or executed check fails, any finding remains, reviewer screenshots are missing, the reviewer modified tracked files, the report contradicts itself, or the head changed.

Rejection is not a hidden worker error. The reviewer account publishes the findings, and the maintainer mentions the specialist with the remediation. The PR remains open.

## Evidence from a real run

In [Issue #25](https://example.invalid/git/nyankoface/pages-starter/issues/25), the specialist verified a back-to-top interaction. The maintainer then assigned a separate reviewer. The reviewer independently ran the app, passed 10 requirements and 9 checks, attached eight screenshots, approved SHA `b55a7369…`, and reported zero findings. Only then was [PR #26](https://example.invalid/git/nyankoface/pages-starter/pulls/26) merged.

The important outcome is not that an agent merged code. It is that the conversation contains enough identity, state, and evidence to explain why it was allowed to merge.
