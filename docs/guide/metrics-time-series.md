---
title: Measured metrics and time-series activity
type: guide
description: The event contract behind NyankoFace repository views, downloads, likes, and the measured activity graph.
readingTime: 8 min
tags: [metrics, downloads, analytics, postgres]
related:
  - title: Catalog metric sorting
    link: /guide/catalog-metric-sorting
  - title: Upgrade and data retention
    link: /guide/upgrading
---

# Measured metrics and time-series activity

The repository detail page's **Measured activity** panel is backed by the
PostgreSQL `nyankoface_metrics.metric_events` ledger. It does not use demo
series, click counters, random values, or estimates. The panel is rendered for
public repository detail, file, and Space surfaces; the download contract also
covers Automation bundles.

## Event contract

Each event stores only the fields needed to aggregate and audit activity:

| Field | Values / meaning |
| --- | --- |
| `event_type` | `view`, `download`, or `like` |
| `source` | `browser`, `agent`, `raw`, `lfs`, or `automation` |
| target | repository owner/name and an optional repository-relative artifact path |
| `actor_kind` | `anonymous`, `authenticated`, `agent`, or `system` |
| `outcome` | `success`, `failed`, `cancelled`, `denied`, `bot`, or `health_check` |
| `value` | `1` for a successful view/download, `+1` or `-1` for a like transition, `0` for a non-counted outcome |
| deduplication | an operation-scoped idempotency key when the source supplies one |
| time | an UTC `created_at` timestamp |

No IP address, bearer token, Forgejo PAT, cookie value, or secret is stored.
The `actor_kind` classification is intentionally coarse and is not an identity
or a permission grant.

## What counts

- A repository detail, Page, or Space view is one successful browser or agent
  event. The detail page uses a page-load idempotency key; repeated React
  mounts and retries do not increase the counter. Catalog cards and health
  checks do not call the view endpoint.
- A like is the active state of an agent's like. A successful `+1` transition
  adds one and a successful `-1` transition removes one. The primary key on
  `repo_likes` and the event ledger together make retries idempotent.
- A download is counted only when the NyankoFace proxy completes the response
  body for a public Raw file, resolved LFS object, or reviewed Automation
  bundle. Clicking a button is not sufficient. The direct Forgejo **Raw**
  navigation link is a preview, not a measured download.
- Failed, cancelled, denied, bot, and health-check outcomes may remain in the
  ledger for diagnostics, but have value `0` and never enter measured totals.
  The current public download paths do not classify health checks as user
  downloads and reject private repositories before proxying content.

The same successful event set feeds cumulative cards and the time series. A
download breakdown keeps `raw`, `lfs`, and `automation` separate instead of
pretending that their totals have the same delivery semantics.

## API contract

Public metrics are available below the runner gateway:

```http
GET /runner-api/metrics/repos/{owner}/{repo}
GET /runner-api/metrics/repos/{owner}/{repo}/timeseries?from=2026-08-01T00:00:00Z&to=2026-09-01T00:00:00Z&bucket=day&timezone=UTC
```

The time-series window is `[from, to)`. Omitted bounds mean the previous 30
days and the current UTC time. The maximum window is 366 days. `bucket` accepts
`day`, `week`, or `month`; `timezone` is an IANA timezone such as `UTC` or
`Asia/Tokyo`. Bucket labels are emitted in the requested timezone.

The response includes:

- `series[]`: `bucket_start`, `views`, `downloads`, active `likes`, like delta,
  and `downloads_by_source`;
- `totals`: period views/downloads, the active like count at `to`, and source
  totals;
- `data_state`: `data` when at least one measured event is available, or
  `no_data` when the period has no measured events;
- `updated_at`, `generated_at`, the requested timezone, and the definitions used
  for the response.

`no_data` is deliberately different from a confirmed zero inside a period with
measured events. If the metrics service or repository is unavailable, the UI
shows `unavailable` and does not substitute a zero.

The download recorder is an internal frontend-proxy contract. It requires the
frontend control token and must not be called directly by a browser:

```http
POST /runner-api/metrics/repos/{owner}/{repo}/downloads
Content-Type: application/json
X-NyankoFace-Control-Token: <frontend-control-token>

{
  "source": "raw",
  "artifact_path": "weights/model.bin",
  "idempotency_key": "one-browser-download-operation",
  "outcome": "success"
}
```

It accepts the three download sources and the six outcome values above. Private
repositories return the same not-found boundary as other public surfaces.

## Storage, migration, and retention

The ledger has target/time and event-type/source indexes, plus a partial unique
index for non-null idempotency keys. It is created by the runner's PostgreSQL
startup initialization. Existing `repo_views`, `browser_views`, and active
`repo_likes` rows are backfilled with stable `legacy:*` keys; rerunning startup
does not duplicate them. New writes update the legacy compatibility tables and
the canonical ledger in the same PostgreSQL transaction.

This release does not silently invent history and does not automatically prune
`metric_events`. The deployment's `nyankoface_metrics` backup and database
retention policy is therefore the retention boundary; operators must keep the
database dump and its restore evidence together. The API's 366-day window is a
query safety bound, not a deletion policy. Any later purge or re-aggregation
must be a reviewed maintenance migration that preserves active like state and
records its before/after counts.

Download events become eligible for aggregation when the response stream
finishes, so the graph can lag a just-completed download by one request. The
`updated_at` and `generated_at` fields make that delay visible. Re-aggregation
is deterministic: rerunning the same window, bucket, and timezone over the
same ledger produces the same series.

## UI and QA

The detail panel shows:

- cumulative measured views, downloads, and active likes;
- the Raw/LFS/Automation download breakdown;
- an SVG trend graph with exact point tooltips;
- an expandable table with the exact period, value, unit, and aggregation
  timezone; and
- distinct loading, unavailable, and no-data states.

Verify a release with a public repository and a test Automation/file fixture:

1. Open the repository detail page at desktop and mobile widths and confirm the
   page-load view idempotency key records once.
2. Complete one Raw, one LFS, and one Automation download. Compare the response
   status, `metric_events` row, cumulative API response, time-series bucket,
   source breakdown, and UI tooltip/table.
3. Repeat a request with the same operation key, then test a denied, failed,
   cancelled, bot, and health-check outcome. Confirm only successful events
   enter measured totals.
4. Repeat with an anonymous session, a logged-in browser, and an authenticated
   agent. Confirm only the coarse `actor_kind` changes and no private data is
   stored.
5. Test a period boundary, `Asia/Tokyo`, an empty period, a long period, and a
   metrics-service failure. Confirm no page-level horizontal overflow at 480px.

Visual capture belongs in `docs/evidence/issues/175/`; it is manual runtime
evidence and is not a CI gate.
