---
title: A Space is an app and a repository
type: article
description: Dockerfile-first Spaces keep varied web stacks honest without forcing them into one framework.
readingTime: 6 min read
updated: 2026-07-21
tags: [spaces, docker, gradio, nextjs]
related:
  - title: Runtime
    link: /wiki/runtime
    note: See lifecycle, routing, and resource boundaries.
  - title: Publish a Docker Space
    link: /guide/spaces
    note: Follow the practical contract.
---

# A Space is an app and a repository

Gradio, Streamlit, React, Vue, Next.js, FastAPI, and an ordinary Node server disagree about almost everything except one fact: they can all listen on a port inside a container.

That is enough for NyankoFace.

## The common contract stays small

Each Space is a Forgejo repository with a Dockerfile. The container must expose its web application on the expected internal port and remain usable behind a path-aware reverse proxy. The repository can carry source, assets, dependencies, documentation, and history in the structure native to its framework.

NyankoFace does not translate a Next.js project into a Gradio configuration or flatten a Vue app into static metadata. The Dockerfile remains the executable description.

## The card and the app tell different parts of the truth

The catalog card answers discovery questions: What does this do? Who owns it? Is it running? Which tags describe it? How many people viewed or liked it?

The repository answers maintenance questions: Which commit produced it? What dependencies does it install? How is it reviewed? Can another environment rebuild it?

The embedded app answers the final question: does the software actually work?

Treating all three as one Space prevents the familiar failure where a polished catalog points to a stale or generic demo.

## CPU-first is a useful constraint

The sample catalog avoids ZeroGPU and required GPU runtimes. That keeps the reference environment reproducible on a normal Docker host and makes startup behavior, resource limits, and failure messages easier to reason about. GPU support can be added deliberately; it is not smuggled into the baseline.

For the exact Docker contract and supported examples, continue to the [Spaces guide](../guide/spaces.md) or inspect the [runtime knowledge node](../wiki/runtime.md).
