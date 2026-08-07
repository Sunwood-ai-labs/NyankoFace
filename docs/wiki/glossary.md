---
title: Glossary
type: reference
description: Precise definitions for NyankoFace routes, assets, states, and configuration terms.
readingTime: Quick reference
updated: 2026-07-21
tags: [definitions, configuration, routes]
related:
  - title: Platform map
    link: /wiki/platform-map
    note: Put the terms into system context.
  - title: Troubleshooting
    link: /guide/troubleshooting
    note: Diagnose a concrete failure.
---

# Glossary

**Asset type**  
The presentation role of a repository: Model, Dataset, Space, Skill, MCP, or Prompt.

**Docker Space**  
A Forgejo repository containing a Dockerfile-backed web application that the Space runner can build and proxy.

**Forgejo**  
The authoritative Git, identity, permission, issue, pull-request, and Actions service behind NyankoFace.

**Knowledge atlas**  
This concept-oriented wiki layer. It explains relationships and points to practical guides and narrative field notes.

**NyankoFace Pages**<br>
Static repository publishing under `/pages/{owner}/{repo}/`, sourced from a Pages branch or directory and optionally built by Forgejo Actions.

**Prompt revision**  
An immutable selectable version of prompt content, for example `v4.2`, preserved in the URL and repository history.

**Reviewed SHA**  
The exact pull-request head commit independently evaluated by `review-agent`. A different current head invalidates approval.

**Runner control token**  
An internal shared secret used between trusted NyankoFace services for lifecycle API calls. It is not a user session token.

**Topic / tag**  
A topic is repository-level Forgejo metadata; tags are multi-valued asset descriptors used by NyankoFace presentation and filtering.

**Visual QA**  
Automated and manual inspection across pages, themes, viewport sizes, scroll positions, interactions, and contrast.
