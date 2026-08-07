---
title: Weekly repository report
tags: [automation, report, repository, read-only]
license: mit
---

# Weekly repository report

This sample Codex Automation prepares a concise weekly repository digest. It
reads Issues, Pull Requests, and commit metadata; it does not edit files,
approve work, merge branches, or send the result to an external destination.

## Review before use

1. Open the Automation preflight in NyankoFace.
2. Confirm the immutable commit SHA, schedule, timezone, permission, connector,
   workspace scope, and delivery mode.
3. Download or copy the normalized configuration. It remains
   `enabled = false`.
4. Supply credentials through the destination runtime's secret store. Never
   paste a token into this repository.
5. Enable the Automation only after reviewing the imported configuration.

Browsing this repository does not register or execute the Automation.

## Version policy

- `schema_version` changes only when the file contract changes.
- `version` follows semantic versioning.
- Every published version has a matching immutable Git tag such as `v1.0.0`.
