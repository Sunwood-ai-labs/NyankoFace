---
title: Getting started
type: guide
description: Bring up a reproducible NyankoFace environment and verify its core services.
readingTime: 10 min
tags: [install, compose, first-run]
related:
  - title: Platform map
    link: /wiki/platform-map
  - title: Troubleshooting
    link: /guide/troubleshooting
---

# Getting started

## Prerequisites

- Docker Engine or Docker Desktop
- Docker Compose v2 (`docker compose`)
- Git for cloning and contributing
- Enough disk space for Forgejo data and Space images

Node.js and Python are not required on the host for the normal Compose path.

## Start a fresh environment

```bash
git clone https://github.com/Sunwood-ai-labs/NyankoFace.git
cd NyankoFace
cp .env.example .env
docker compose up -d --build
```

On Windows PowerShell, replace the copy command with:

```powershell
Copy-Item .env.example .env
```

Change `NYANKOFACE_ADMIN_PASSWORD` in `.env` before sharing the deployment. Open `https://localhost:8443`; the first local run uses a generated self-signed certificate, so the browser will show a development certificate warning.

## Confirm the stack

```bash
docker compose ps
docker compose logs seed
```

The `seed` service should finish successfully. Long-running services should report healthy or running states.

## Stop or rebuild

```bash
docker compose down
docker compose up -d --build
```

`docker compose down` keeps named volumes. Add `--volumes` only when you intentionally want to delete Forgejo repositories, users, tokens, and agent metrics.

## Next steps

- Understand the [architecture](./architecture.md).
- Publish a [Docker Space](./spaces.md).
- Publish a static site with [NyankoFace Pages](./pages.md).
- Review [operations and security](./operations.md).
