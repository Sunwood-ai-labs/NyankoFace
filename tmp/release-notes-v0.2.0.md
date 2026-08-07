![NyankoFace v0.2.0 release header](https://sunwood-ai-labs.github.io/NyankoFace/releases/release-header-v0.2.0.svg)

[![English release notes](https://img.shields.io/badge/docs-release_notes-2563eb)](https://sunwood-ai-labs.github.io/NyankoFace/guide/releases/v0.2.0) [![日本語リリースノート](https://img.shields.io/badge/docs-日本語-d946ef)](https://sunwood-ai-labs.github.io/NyankoFace/ja/guide/releases/v0.2.0) [![Walkthrough](https://img.shields.io/badge/docs-walkthrough-059669)](https://sunwood-ai-labs.github.io/NyankoFace/articles/nyankoface-v0-2-0)

NyankoFace v0.2.0 turns repository content into an auditable delivery workflow. The release covers the changes since v0.1.0 and adds guided Pages publishing, Forgejo Actions-backed Pipelines, protected Space environment APIs, portable Automations, and exact-head delivery guardrails.

## Highlights

- **Guided Pages publishing:** inspect real `gh-pages/index.html` or default-branch `docs/index.html` content, preview the write plan, and publish static HTML, docs, or VitePress from a dedicated wizard.
- **Repository Pipelines:** install, dispatch, inspect, retry, cancel, approve, and roll back Forgejo Actions runs with bounded logs, artifacts, audit records, and immutable deployment revisions.
- **Protected Space settings:** PAT-authenticated APIs manage runtime/build Variables and encrypted Secrets without returning secret values.
- **Portable Automations:** validate public `automation.toml` packages at immutable commits and export a normalized `enabled = false` bundle while rejecting secrets, private endpoints, unsafe paths, destructive commands, and mutable revisions.
- **Reliable public CPU Spaces:** anonymous users can launch public applications while owner-only management remains protected.
- **Safer delivery:** issue worktrees, checkpoints, scope budgets, exact-head Codex evidence, stable review snapshots, required GitHub Actions identity, and SHA-bound merges prevent stale evidence from authorizing a merge.

## Pipeline and runtime hardening

- Bound artifact downloads, archive entries, and job-log streaming.
- Prevent historical backfill from rolling staging deployments backward.
- Serialize production publication and preserve immutable deployed revisions.
- Expire stale previews and retire Pages output that no longer exists.
- Wait for Space HTTP readiness before reporting a successful deployment.
- Keep release/tag runs classified as production and isolate concurrent Forgejo jobs.

Visual capture remains a manual local/deployed-environment review and is intentionally not an automatic CI verdict.

## Upgrade notes

No repository format migration is required. Operators enabling Pipelines should review the new concurrency, resource, timeout, and retention settings in `.env.example`. Space owners can adopt the environment API incrementally; existing Docker Spaces and Pages sources remain compatible.

## Validation

The release candidate is validated through the repository CI suites, frontend type/build checks, Space runner and merge-guard tests, bilingual docs checks, the VitePress production build, SVG validation, and the release QA inventory gate.

**Full changelog:** https://github.com/Sunwood-ai-labs/NyankoFace/compare/v0.1.0...v0.2.0
