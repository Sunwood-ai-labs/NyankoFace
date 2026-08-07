# Navigation performance

NyankoFace gives immediate feedback for internal navigation, renders route-specific loading skeletons, and records aggregate navigation latency without storing URLs or user data.

## Runtime behavior

- Internal links use Next.js client navigation instead of full document reloads.
- A progress line and pressed state appear immediately; repeated activation is suppressed until navigation finishes.
- Slow transitions expose a retry action after 15 seconds. Back/forward navigation and reduced-motion preferences are supported.
- Public knowledge metadata is cached in-process for `KNOWLEDGE_CACHE_TTL_SECONDS` (60 seconds by default) with in-flight request coalescing. Private or authenticated repository content is never added to this cache.

## Measurement

`GET /api/performance/navigation` returns bounded p50/p95 summaries by route class. The corresponding `POST` endpoint accepts only normalized route classes, duration, feedback delay, outcome, viewport class, and cache state. It rejects paths and arbitrary metadata. Ingestion also requires browser same-origin fetch metadata and is limited to 30 samples per gateway client address per minute so direct clients cannot freely replace the bounded observation window. The in-memory limiter retains at most 4,096 active client buckets and discards expired buckets before refusing new clients.

Set `NYANKOFACE_PERFORMANCE_LOG=1` to emit structured server phase timings for API, database, Forgejo, and Markdown work. Leave it disabled unless the logs are actively being inspected.

Visual verification remains a manual browser step. CI covers types, telemetry validation, and production builds; it does not claim to validate rendered appearance.

## Space navigation and runtime readiness

Space detail pages render their repository header and controls without waiting for the runtime API. The runtime badge and application panel share one client-side status provider, so opening a Space does not start duplicate status polls. Space repositories also skip the unrelated Pages-source inspection performed for model and dataset repositories.

Runtime progress is reported as `checking`, `queued`, `leased`, `building`, `starting`, `warming`, `running`, `stopping`, `stopped`, `offline`, `unavailable`, `failed`, or `error`. Transitional states poll every 2 seconds, running Spaces every 10 seconds, and stopped Spaces every 15 seconds. Other terminal states wait 20 seconds before the next check. Each status request has an 8-second timeout, and navigation away aborts the outstanding request.

The embedded application loads independently after the runtime reaches `running`. Before mounting the iframe, NyankoFace probes the `/run/` endpoint every 750 milliseconds and ignores transient gateway responses such as `space is not running`. The existing 20-second readiness budget covers this probe and iframe load; expiry produces a visible retry action instead of an endless loading state or a stale JSON error page. Start and stop operations expose their current operation, disable conflicting controls, and refresh the shared status immediately after the runner responds.

For manual QA and diagnostics, the application panel exposes normalized state through `data-runtime-phase`, `data-runtime-request-ms`, `data-iframe-phase`, and `data-iframe-duration-ms`. The detail route also emits server phase timing when `NYANKOFACE_PERFORMANCE_LOG=1`. Verify CPU, GPU, and external Spaces in their real deployed environments; browser captures remain a manual release check.

Run the focused anonymous desktop/mobile audit against a real deployment with:

```bash
VISUAL_QA_BASE_URL=http://localhost:8090 \
PUBLIC_SPACE_REPO=sample-vue \
npm run audit:public-space --prefix visual-tests
```

For repeatable before/after navigation measurements, run two frontend revisions on separate origins and use:

```bash
BASELINE_URL=http://localhost:3102 \
CANDIDATE_URL=http://localhost:3103 \
SPACE_NAV_TARGET=/seraphim-labs/sample-vue \
SPACE_NAV_SAMPLES=10 \
npm run benchmark:space-navigation --prefix visual-tests
```

The local #103 verification measured ten cold and ten warm samples per revision. Baseline-to-candidate p50 changed from 358 ms to 67 ms cold and from 359 ms to 67 ms warm. Cold p95 changed from 372 ms to 358 ms while warm p95 remained 368 ms because the candidate still had occasional approximately 360 ms outliers. Candidate immediate-feedback p95 was 26 ms cold and 28 ms warm, below the 100 ms acceptance threshold even for those outliers. These figures describe the recorded local environment, not a universal production guarantee.
