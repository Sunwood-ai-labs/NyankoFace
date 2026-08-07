---
title: Measure the surface, preserve the evidence
type: article
description: How NyankoFace v0.6.0 turns repository activity into a measured event stream without making the operator guess.
readingTime: 7 minutes
tags: [release, metrics, downloads, operations, interface]
---

![NyankoFace v0.6.0 release header](/releases/release-header-v0.6.0.svg)

# Measure the surface, preserve the evidence

A platform can display a number and still leave an operator unsure what the
number means. A click is not a completed download. A missing metrics service is
not a confirmed zero. A logo exploration is not a production decision. NyankoFace
v0.6.0 treats those distinctions as part of the product surface.

## One ledger, several honest views

The release adds `nyankoface_metrics.metric_events` as the canonical event ledger.
Successful browser and agent views, completed Raw/LFS/Automation downloads, and
active agent likes can now be read through the same aggregation boundary. That
means the cumulative repository card and the daily graph do not have to invent
separate histories.

The event contract is deliberately small. It records the event type, source,
repository target, coarse actor kind, outcome, value, operation key when one is
available, and UTC time. It does not store IP addresses, bearer tokens, Forgejo
PATs, cookies, or secrets. Failed, denied, cancelled, bot, and health-check
outcomes can remain useful diagnostics without becoming measured activity.

## Completion is the boundary

Downloads reveal why the boundary matters. A button click only expresses intent;
the proxy can count a Raw file, LFS object, or Automation bundle after the
response body finishes. The source remains visible in the breakdown, so an
operator can distinguish a model artifact from an Automation package instead of
flattening both into a decorative number.

The same rule makes retries safer. When a source supplies an operation key, the
ledger's unique index prevents a repeated request from manufacturing another
event. A graph may therefore lag a just-completed download by one request, but
the delay is visible through `updated_at` and `generated_at` rather than hidden
behind a guessed counter.

## Empty is not unavailable

The UI has three meanings that are easy to confuse when a product is rushed:
measured data, a measured period with no events, and an unavailable service.
NyankoFace exposes them as `data`, `no_data`, and `unavailable`. The time-series
API accepts day, week, or month buckets and an IANA timezone, but bounds the
query window to 366 days. That is a query safety limit, not a retention policy.

The ledger is created at runner startup. Existing view and like counters are
backfilled with stable legacy keys, and the old compatibility tables remain in
place. The initialization is automatic and idempotent, but it is still durable
data work: operators must back up `nyankoface_metrics` and retain restore evidence.
The service does not silently prune history.

## Calm surfaces make evidence usable

The release also contains smaller interface changes that protect the same
principle. Navigation menus close after a selection so the next page is not
covered by the previous context. The audited brand surfaces keep shared naming
and identity legible. Space headers measure the room left after wrapping on
tablet and mobile layouts, keeping tabs, metrics, and runtime controls in the
same conversation as the Space identity.

The MCP setup story follows the same boundary. The remote endpoint remains
authenticated Streamable HTTP, while the local stdio adapter is a compatibility
path that forwards one request at a time without inventing a server session.
Configuration comes from environment or restricted files, validation reports
the token source rather than the token, and the README contract is tested so a
copy-pasted setup does not quietly become a credential leak.

## Evidence before identity

NyankoFace also keeps the logo decision explicit. The ten candidate directions and
variant matrix are stored in the Issue #177 evidence surface. That gives the
project a reusable visual conversation without pretending the exploration is a
final brand decision. The existing production logo remains stable until a
separate direction is selected and implemented.

Continue with the [v0.6.0 release notes](../guide/releases/v0.6.0), the [measured
metrics and time-series guide](../guide/metrics-time-series), or the [upgrade and
data retention runbook](../guide/upgrading). The [release QA inventory](https://github.com/Sunwood-ai-labs/NyankoFace/blob/main/tmp/release-qa-v0.6.0.md)
keeps the claims, validation commands, docs review, and publication evidence in
one place.
