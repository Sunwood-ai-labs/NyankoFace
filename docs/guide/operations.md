---
title: Operations
type: guide
description: Public-safe operational habits for running NyankoFace.
readingTime: 4 min
tags: [operations, safety]
related:
  - title: Architecture
    link: /guide/architecture
  - title: Upgrade and data retention
    link: /guide/upgrading
---

# Operations

This public guide covers repeatable safety practices. Private deployment
topology, hostnames, addresses, and environment-specific runbooks are kept out
of the public repository.

## Before starting

1. Copy `.env.example` to a local, untracked `.env` file.
2. Replace every bootstrap credential and keep tokens in a secret store.
3. Review which repositories are allowed to publish runnable Spaces.
4. Check the compose configuration without printing secret values.

## During operation

- Review application and runner logs without copying credentials into issues.
- Keep registration and write permissions limited to trusted maintainers.
- Treat imported Dockerfiles and runtime dependencies as untrusted code.
- Record only public-safe diagnostics; remove hostnames, addresses, and internal
  URLs before sharing logs or screenshots.

## Recovery

Keep deployment backups outside the repository and test restoration privately.
After a recovery, verify health, authentication, repository access, and one
representative Space. Do not commit backup archives, database dumps, certificates,
tokens, or host-specific configuration.
