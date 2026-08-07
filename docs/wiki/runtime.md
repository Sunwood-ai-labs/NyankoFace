---
title: Runtime
type: wiki
description: The lifecycle and routing contracts behind Docker Spaces, Pages, and Actions.
readingTime: 7 min reference
updated: 2026-07-21
tags: [spaces, pages, actions, docker]
related:
  - title: A Space is app + repository
    link: /articles/docker-spaces
    note: Read the reasoning behind Dockerfile-first.
  - title: Spaces guide
    link: /guide/spaces
    note: Build and publish an application.
---

# Runtime

## Space lifecycle

```text
repository → validate → clone/fetch → Docker build → container start
     ↑                                                   ↓
 catalog ← status/metrics ← health and capacity ← path proxy
```

CPU Spaces may start on demand. The runner enforces a bounded running capacity and can surface paused, building, running, failed, or stopped state. A catalog label must reflect runtime truth rather than a hard-coded fixture.

### Space contract

- A Dockerfile is present.
- The application listens on the documented internal port and a non-loopback interface.
- The app tolerates its proxied path and forwarded headers.
- Health/startup completes within configured limits.
- Secrets are supplied at runtime, not committed.

## Pages lifecycle

Pages serves static output from `gh-pages` when present, otherwise from the configured `docs/` source on `main`. Forgejo Actions can build VitePress or another generator before publication. Pages are static and do not receive Space container privileges.

## Actions isolation

The Forgejo runner uses a dedicated Docker-in-Docker daemon. This prevents repository workflows from inheriting the host Docker socket used by the NyankoFace operator. Isolation is a boundary, not a promise that arbitrary workflows are harmless; repository permissions and runner policy still matter.

## Route behavior

Space applications are reached through `/run/{owner}/{repo}/`. Pages use `/pages/{owner}/{repo}/`. Both remain behind the same gateway and TLS endpoint as the portal and Forgejo, so apps must avoid assuming they own `/` on the public host.
