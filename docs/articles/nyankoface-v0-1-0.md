---
title: From repositories to a local AI community
type: article
description: A guided tour of what NyankoFace v0.1.0 connects and why those boundaries matter.
readingTime: 8 minutes
tags: [release, architecture, operations]
---

![NyankoFace v0.1.0 release header](/releases/release-header-v0.1.0.svg)

# From repositories to a local AI community

NyankoFace v0.1.0 starts with a deliberately small premise: the durable objects of an AI community should remain ordinary Git repositories and ordinary applications.

## Keep the source of truth boring

Forgejo owns files, commits, tags, Issues, Pull Requests, users, organizations, teams, stars, and forks. NyankoFace adds a discovery and runtime layer without inventing a second repository database. Topics classify Models, Datasets, Spaces, Characters, Benchmarks, Skills, MCPs, Prompts, and Knowledge.

That boundary makes the catalog portable. A clone is still a clone, a tag is still immutable, and rebuilding the portal does not rewrite project history.

## Treat a Space as an application

A root Dockerfile is the common contract. Framework-specific samples—Gradio, static HTML, React, Vue, Next.js, Streamlit, FastAPI, and Node.js—listen on port `7860`, while the runner handles build, lifecycle, and proxying.

Public applications can be launched without a Forgejo session. Destructive or configuration-changing controls remain owner-only. Existing services can instead use `external_url`, and static documentation can use NyankoFace Pages.

## Keep deployment details private

The public snapshot documents application boundaries and safe runtime contracts, but omits deployment-specific hostnames, addresses, hardware topology, credentials, and operator access paths. Keep those details in a private operations repository.

## Make automation leave evidence

The maintenance flow is not a hidden cron job. A coordinator classifies work, delegates to a specialist identity, runs Claude Code `/goal`, opens a Pull Request, and requests an independent review against a fixed commit SHA. Auto-merge is fail-closed when evidence, labels, or review state is missing.

## Verify the surface people actually use

NyankoFace’s visual suite captures desktop and mobile routes across Standard, Solarpunk, and Cyberpunk themes. It scrolls long pages, exercises menus and controls, validates Markdown and Mermaid rendering, and stores the screenshots beside the implementation evidence.

The result is not just a catalog and not just a runner. It is a local collaboration surface whose data, applications, automation, and verification can all be inspected.

Continue with the [full v0.1.0 release notes](../guide/releases/v0.1.0.md) or [build your first deployment](../guide/getting-started.md).
