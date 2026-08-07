---
title: Agent operations
type: wiki
description: Identities, delegation, evidence, review states, and guarded auto-merge.
readingTime: 8 min reference
updated: 2026-07-21
tags: [agents, maintainer, reviewer, merge]
related:
  - title: Independent review story
    link: /articles/independent-review
    note: Read why the gate is designed this way.
  - title: Maintenance guide
    link: /guide/automated-maintenance
    note: Configure tokens and webhooks.
---

# Agent operations

## Identities

| Account | Responsibility | May implement? | May approve? |
|---|---|---:|---:|
| `glm-maintainer` | classify, delegate, publish, enforce gate, merge | wrapper only | no |
| `designer-agent` | UI/UX, responsive, theme, accessibility evidence | yes | no |
| `coding-agent` | application code, refactoring, tests, build | yes | no |
| `docs-agent` | README, VitePress, examples, reconstruction docs | yes | no |
| `security-agent` | threat analysis, auth, secrets, dependencies, validation, supply chain | yes | no |
| `review-agent` | read-only requirement/diff/test/security/regression review | no | yes |

## State transition

```text
Issue mentions maintainer
  → maintainer mentions one specialist
  → specialist publishes PR + evidence
  → maintainer mentions review-agent
  → reviewer evaluates exact head SHA
      ├─ rejected → PR remains open → maintainer rementions specialist
      └─ approved → wrapper rechecks SHA → guarded server-side merge

Release branch push
  → maintainer creates security and docs audit Issues
  → security-agent and docs-agent run in isolated clones
  → each publishes a PR targeting the release branch
  → review-agent evaluates each exact head SHA
  → glm-maintainer merges only after a clean, current-SHA independent approval
```

## UI evidence

The implementer and reviewer produce separate evidence. Each must include real mobile (width ≤480) and desktop (width ≥1024) PNGs, concrete interaction checks, and error/overflow results. The wrapper validates PNG signatures and actual dimensions rather than trusting labels in JSON.

## Approval invariants

Approval is valid only when every requirement and executed check passes, findings are empty, tracked files were unchanged by the reviewer, the recorded SHA equals the current PR head, and Forgejo accepts the same SHA in `head_commit_id`.

## Observable API

- `/api/agents` exposes registered personas and role contracts.
- `/api/jobs` exposes current assignment and job state.
- Forgejo issues and PRs preserve the human/maintainer/specialist/reviewer conversation.
