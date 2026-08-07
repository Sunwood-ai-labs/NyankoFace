---
title: Troubleshooting
type: reference
description: Diagnose common startup, routing, repository, and Space runtime failures.
readingTime: quick reference
tags: [diagnostics, logs, recovery]
related:
  - title: Platform map
    link: /wiki/platform-map
  - title: Getting started
    link: /guide/getting-started
---

# Troubleshooting

## The catalog is empty

Run `docker compose logs seed`. The seed job waits for Forgejo, creates or reuses the admin and API token, imports catalogs, and exits. Fix the first reported failure, then run `docker compose up seed` again.

## A Space stays in building or error

Inspect `docker compose logs spaces-runner` and request the Space status endpoint. Common causes are dependency installation failures, a missing `Dockerfile`, or an app that does not listen on port `7860`.

## The browser shows a certificate warning

The generated local certificate is self-signed. Accept it only for a host you control, or replace it with a trusted certificate as described in [Operations](./operations.md#tls).

## Pages loads without styles

Static generators must build for `/pages/OWNER/REPOSITORY/`. For VitePress, pass that value as the base. Confirm that `gh-pages` contains the built files rather than project source.

## A private repository appears publicly

Treat that as a security issue. Stop the deployment, preserve relevant logs without credentials, and follow the private reporting process in `SECURITY.md`.
