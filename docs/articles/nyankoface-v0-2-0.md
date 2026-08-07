---
title: From repository files to a delivery control plane
type: article
description: How NyankoFace v0.2.0 connects Pages, Pipelines, protected settings, and review evidence.
readingTime: 7 minutes
tags: [release, pipelines, pages, automation]
---

![NyankoFace v0.2.0 release header](/releases/release-header-v0.2.0.svg)

# From repository files to a delivery control plane

NyankoFace v0.1.0 established Git repositories as the durable source of truth. v0.2.0 follows the next practical question: how does a repository move from files to a published site or running application without hiding the evidence?

## Publish Pages without guessing

The Pages inspector checks actual content rather than assuming a branch name is enough. It tries `gh-pages/index.html`, then the default branch `docs/index.html`, and reports published, missing, private, or upstream-error states. The deployment wizard shows the target branch and files before it writes anything, then returns the commit, log, and public URL.

## Operate Pipelines from the repository

The Pipelines tab exposes Forgejo Actions runs without creating a second workflow database. Operators can follow jobs and steps, stream bounded logs, inspect artifacts, retry a failed job, cancel a run, approve a protected deployment, or roll production back to a selected immutable revision.

The difficult part is not drawing buttons. It is preserving ordering and identity: older history must not replace newer staging, tags must remain production, concurrent runs must not overwrite one another, and artifacts must belong to the checked-out revision.

## Keep configuration secret and automation portable

Space Variables and Secrets now have authenticated, cookie-independent APIs. The API returns metadata and audit history, never the stored secret value. Runtime and build scope are separate so a build setting can reach Forgejo Actions without leaking into an unrelated runtime response.

Portable Automations take the opposite approach to execution: they are cataloged and downloadable, but always normalized to `enabled = false`. NyankoFace validates an immutable public revision and rejects packages that contain secret-like values, private endpoints, unsafe paths, destructive commands, or unknown schema fields.

## Make review evidence part of delivery

The v0.2.0 delivery work also exposed how stale review evidence can become dangerous. The merge guard now requires the exact Pull Request head, the repository's own `CI / validate` GitHub Actions check, no unresolved review threads, and a current Codex Review. It collects the head, checks, reviews, and threads until two snapshots match, then the merge command pins the verified SHA.

This is also why NyankoFace keeps screenshot capture out of automatic CI verdicts. Structural checks belong in CI; appearance still needs a real browser, the intended deployment, and human comparison.

Continue with the [full v0.2.0 release notes](../guide/releases/v0.2.0.md), [Repository pipelines](../guide/pipelines.md), or [change delivery](../guide/change-delivery.md).
