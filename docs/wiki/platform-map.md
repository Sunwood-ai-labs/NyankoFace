---
title: Platform map
type: wiki
description: Services, public routes, state, and trust boundaries on one page.
readingTime: 5 min reference
updated: 2026-07-21
tags: [architecture, routes, services, state]
related:
  - title: Architecture guide
    link: /guide/architecture
    note: Read the deployment explanation.
  - title: Runtime
    link: /wiki/runtime
    note: Follow applications from source to process.
---

# Platform map

## Service ownership

| Service | Owns | Does not own |
|---|---|---|
| `gateway` | TLS, public routing, WebSockets | repository data or application builds |
| `frontend` | discovery and repository presentation | Git history or Space processes |
| `forgejo` | repositories, auth, permissions, issues, PRs, Actions metadata | host container lifecycle |
| `spaces-runner` | Space validation, clone, build, lifecycle, Pages serving | user identity source |
| `seed` | idempotent sample/bootstrap data | long-running request handling |
| `maintenance-agent` | Issue-triggered `/goal`, evidence gates, guarded merge | unrestricted host control |
| `forgejo-actions-runner` | repository workflows in isolated DinD | the host Docker socket |

## Public route map

```text
https://host/
├─ /models /datasets /spaces /skills /mcps /prompts → frontend
├─ /nyankoface/{repository}                         → frontend repository view
├─ /git/                                          → Forgejo
├─ /run/{owner}/{space}/                          → running Space proxy
├─ /runner-api/                                   → runner control/data API
└─ /pages/{owner}/{repository}/                   → published Pages
```

## State map

- **Forgejo volumes:** repositories, users, permissions, issues, PRs, Actions metadata.
- **Runner volumes:** registration, shared control token, runtime metadata.
- **Docker:** built images, running Space containers, build cache.
- **Git checkout:** Compose, frontend, service code, sample definitions, docs—never production secrets.

## Trust boundaries

The browser authenticates against Forgejo. The frontend asks the runner to perform privileged lifecycle operations through a shared internal token. The runner validates repository permission before control operations. Agent identities use separate scoped tokens; Claude runs as an unprivileged container user without the host Docker socket or bot credentials.
