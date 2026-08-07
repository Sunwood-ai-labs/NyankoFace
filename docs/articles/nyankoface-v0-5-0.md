---
title: Move state to a safer operating boundary
type: article
description: How NyankoFace v0.5.0 moves pipeline state into PostgreSQL and turns upgrades into a verified operator ceremony.
readingTime: 8 minutes
tags: [release, pipelines, postgres, operations]
---

![NyankoFace v0.5.0 release header](/releases/release-header-v0.5.0.svg)

# Move state to a safer operating boundary

The most important state in a delivery system is rarely the container that is
running right now. It is the history that explains what happened, the cursor
that tells reconciliation where to continue, and the evidence an operator can
use after a connection or process disappears. NyankoFace v0.5.0 moves that state
to PostgreSQL and makes the move explicit.

## A pipeline needs a durable home

Before v0.5.0, pipeline audit history and reconciliation state lived in a
SQLite file inside the metrics volume. That was convenient for the first
implementation, but it made the backup boundary easy to misunderstand: a
PostgreSQL dump alone did not contain the pipeline control plane.

The new runner stores audit rows, production state, cursors, and migration
markers in the `nyankoface_pipeline` schema of `nyankoface_metrics`. The health
endpoint checks the pipeline database as part of readiness. A missing database
or schema is a visible failure, not an invitation to start writing somewhere
else.

## Migration is a ceremony, not a guess

An existing installation is not silently converted at startup. The operator
stops the runner, preserves the SQLite source, and asks
`pipeline_migration.py` to verify the exact file. The command checks SQLite
integrity and the expected schema, validates row fields and timestamps, carries
over reconciliation state and cursors, records a SHA-256 source digest, and
refuses conflicts.

That ceremony has a useful property: a failed migration leaves the source in
place. A repeated run against the same verified source is safe, while an
unexpected change or incomplete target remains a blocked operation instead of
becoming a second, ambiguous history.

## Upgrades now describe the recovery boundary

The upgrade runbook treats a release as a change to a living system. It
quiesces writers before backups, covers all three PostgreSQL databases and the
named volumes, detects optional MCP state, protects credential sources, and
keeps the MCP archive and credential checks fail-closed. The restore helper is
an ordered restore operation rather than an atomic transaction: it validates
the MCP archives before replacing those state pieces, while `.env`, TLS, and
other volume steps still happen in sequence. Operators therefore keep the old
checkout and verified backups while comparing stable IDs, row counts, run
numbers, and health results after the change.

This is why the old checkout, a volume archive, and a database dump are kept
together. A rollback is not a button that makes a schema migration disappear;
it is a verified restore path that can be rehearsed before production.

## The visible surface should stay calm

While the control plane became more explicit, the portal received quieter
improvements. A repository blob view now follows the repository's default
branch and renders README Markdown with relative links and assets rooted at
the file's directory. Long Space organization names no longer push tabs and
runtime controls out of the header; the runner measures the space left after
the wrapped header on tablet and mobile layouts.

The validation workflow follows the same idea. Independent frontend, docs,
Python, runner, maintenance, and Compose checks can run in parallel, while a
single aggregate `validate` job keeps branch protection simple.

Repository activity is now measured from one PostgreSQL event ledger. The
detail panel joins successful browser/agent views, completed Raw/LFS/Automation
downloads, and active agent likes into the same cumulative and daily series.
Existing counters are backfilled with stable legacy keys; upgrades must keep the
`nyankoface_metrics` dump and its restore evidence. This release does not silently
invent history or prune the ledger, and the public series API is bounded to 366
days. See the [measured metrics and time-series guide](../guide/metrics-time-series)
for definitions, retention, and verification.

Continue with the [full v0.5.0 release notes](../guide/releases/v0.5.0.md),
the [Repository Pipelines guide](../guide/pipelines), or the [upgrade and data
retention runbook](../guide/upgrading).
