---
title: Catalog anatomy
type: wiki
description: How repository-backed asset types, metadata, tags, and revisions fit together.
readingTime: 6 min reference
updated: 2026-07-21
tags: [models, datasets, skills, mcps, prompts]
related:
  - title: Local-first hub
    link: /articles/local-first-hub
    note: Understand why repositories remain authoritative.
  - title: Glossary
    link: /wiki/glossary
    note: Resolve catalog terminology.
---

# Catalog anatomy

NyankoFace presents several asset types, but they share one invariant: the visible entity maps to a real Forgejo repository or immutable repository revision.

| Type | Primary content | Distinctive behavior |
|---|---|---|
| Model | weights/configuration/model card | model-oriented browsing and inference information |
| Dataset | tabular/media files/dataset card | split and viewer presentation |
| Space | Dockerfile and web application source | local build, start, health, proxy, metrics |
| Skill | `SKILL.md` plus supporting files | rendered instructions and relationship graph |
| MCP | server code/configuration/docs | tool-server discovery and repository files |
| Prompt | prompt source and metadata | immutable version/revision switching |

## Topics and tags

Repository topics are Forgejo metadata used for broad discovery. Asset tags can be more specific and multiple: a Space may carry `space`, `gradio`, and `audio` together. The UI should not pretend those are mutually exclusive categories.

## Revision semantics

Files show branch and commit history. Prompts additionally expose named versions such as `v4.1` and `v4.2`; switching a revision changes the content being viewed without overwriting older material. Links should preserve the selected revision when a user shares a prompt page.

## Authority and cache

Forgejo is authoritative. The frontend may batch requests and cache rendered README data for speed, but cache keys must retain owner, repository, and revision identity. A stale or generic card must never become a substitute for the underlying repository.
