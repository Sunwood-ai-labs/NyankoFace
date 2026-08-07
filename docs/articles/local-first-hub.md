---
title: Why a local AI hub?
type: article
description: A local-first platform is not a smaller cloud. It is a different answer to ownership, latency, and collaboration.
readingTime: 7 min read
updated: 2026-07-21
tags: [local-first, forgejo, docker, ownership]
related:
  - title: Platform map
    link: /wiki/platform-map
    note: See every service and public route.
  - title: Architecture guide
    link: /guide/architecture
    note: Inspect the deployment boundaries.
---

# Why a local AI hub?

The easy version of an AI hub is a gallery of cards. The difficult version is a place where every card still points to something a team can own: a repository, a revision, a runnable application, a discussion, and a history.

NyankoFace starts with that second definition.

## The durable objects already exist

Git already knows how to preserve files, revisions, branches, tags, authors, and review. Docker already knows how to package a web application and its runtime. NyankoFace does not hide either one. It uses Forgejo as the durable collaboration layer, then adds discovery and local execution around it.

That choice changes the meaning of the interface. A model card is not a decorative record in a separate database. A Space is not an iframe pointed at an unrelated demo. A Prompt revision is not overwritten when a new draft appears. The visible catalog remains connected to repository truth.

## Local-first is an operational boundary

“Local” does not merely describe `localhost`. It describes who controls the failure modes.

- Repository data stays in the Forgejo volume you operate.
- CPU-capable Spaces build and run on the Docker host you selected.
- TLS terminates at the shared gateway.
- Pages are produced from repository branches or directories.
- Agents act through scoped accounts and leave visible issue and pull-request history.

The result can still be shared over a private network. Local-first means that remote access is an explicit route into your system, not a migration of ownership out of it.

## The portal is a lens, not a second source of truth

NyankoFace's Next.js frontend makes repositories easier to browse as Models, Datasets, Spaces, Skills, MCPs, and Prompts. The portal may cache or reshape data for presentation, but Forgejo remains authoritative for source, permissions, history, and collaboration.

This avoids the most expensive form of drift: a beautiful catalog that no longer matches what can be cloned, reviewed, or run.

## What you trade for that control

Ownership has a cost. The operator must understand Docker resource limits, backups, repository permissions, and the security implications of building third-party Dockerfiles. NyankoFace makes those boundaries inspectable; it cannot make them disappear.

That is why the project includes an [operations guide](../guide/operations.md), [visual QA](../guide/visual-qa.md), and an independent [agent review gate](./independent-review.md). A local platform earns trust through evidence, not through the absence of warnings.
