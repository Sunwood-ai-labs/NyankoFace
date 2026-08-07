---
title: Upgrade and data retention
type: guide
description: Public-safe upgrade and rollback checks for NyankoFace.
readingTime: 4 min
tags: [upgrade, recovery, safety]
related:
  - title: Operations
    link: /guide/operations
  - title: Release v0.6.0
    link: /guide/releases/v0.6.0
---

# Upgrade and data retention

This public runbook focuses on release checks. Deployment-specific migration
commands and private infrastructure details are intentionally omitted.

## Upgrade checklist

1. Read the release notes and record the exact revision being installed.
2. Export or snapshot application data using the private deployment procedure.
3. Validate configuration without exposing secret values.
4. Rebuild or restart the affected services in a private environment.
5. Verify authentication, repository browsing, one Space, and the docs build.

## Rollback

Keep the previously verified image or revision until the new version passes its
checks. If rollback is required, restore that exact artifact and re-run the
health and access checks before removing any retained data.

## Retention boundary

Backups, database dumps, certificates, logs containing identifiers, and secret
files belong outside Git. The public repository should contain only reproducible
source, sanitized examples, and documentation that does not identify private
hosts or endpoints.
