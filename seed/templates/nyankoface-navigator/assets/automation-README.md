---
title: Portable Automation
tags: [automation, read-only]
license: mit
---

# Portable Automation

This repository publishes one reviewable Automation. Browsing it does not
register or execute the Automation.

## Review before use

1. Inspect the NyankoFace preflight and immutable commit SHA.
2. Confirm the schedule, permissions, connectors, workspace scope, and delivery.
3. Download or copy the normalized manifest; it remains `enabled = false`.
4. Supply credentials through the destination runtime's secret store.
5. Enable it only after reviewing the imported configuration.

Pair each semantic version with an immutable Git tag such as `v1.0.0`.
