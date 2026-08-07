![NyankoFace v0.3.0 release header](https://sunwood-ai-labs.github.io/NyankoFace/releases/release-header-v0.3.0.svg)

[![English release notes](https://img.shields.io/badge/docs-release_notes-2563eb)](https://sunwood-ai-labs.github.io/NyankoFace/guide/releases/v0.3.0) [![日本語リリースノート](https://img.shields.io/badge/docs-日本語-d946ef)](https://sunwood-ai-labs.github.io/NyankoFace/ja/guide/releases/v0.3.0) [![Walkthrough](https://img.shields.io/badge/docs-walkthrough-059669)](https://sunwood-ai-labs.github.io/NyankoFace/articles/nyankoface-v0-3-0) [![日本語解説](https://img.shields.io/badge/docs-日本語解説-f472b6)](https://sunwood-ai-labs.github.io/NyankoFace/ja/articles/nyankoface-v0-3-0)

NyankoFace v0.3.0 makes the path from finding a repository to seeing a running app easier to follow. The release covers changes since v0.2.0: metric-backed discovery, immediate navigation feedback, staged Space readiness, shared navigation, theme-aware code, and one canonical platform identity.

## Highlights

- **Metric-backed discovery:** sort 11 catalog surfaces by created, updated, likes, or views in either direction, across the complete matching set before pagination.
- **Responsive navigation:** immediate progress, pressed states, route skeletons, bounded timeout/retry, privacy-safe p50/p95 telemetry, and a public-only knowledge metadata cache.
- **Legible Space startup:** render the repository shell first, share one runtime-state source, probe readiness before mounting the iframe, and keep public CPU launch available without authentication.
- **Shared navigation:** serve one versioned portal/Forgejo navigation contract with a native fallback.
- **Canonical brand:** use the cat mark across browser, PWA, maskable, monochrome, authentication, error, and documentation surfaces.
- **Theme-aware code:** render highlighted code server-side with safe unknown-language fallback in Standard, Solarpunk, and Cyberpunk.

## Measured Space detail result

In ten-run local cold and warm comparisons, candidate p50 improved from about 358–359 ms to 67 ms (about 81%, or 5.3×). Occasional roughly 360 ms outliers kept p95 close to baseline, and navigation feedback appeared within 28 ms at p95. These are local Pull Request #106 measurements, not a universal network or hardware guarantee.

## Upgrade notes

No repository or database migration is required. `KNOWLEDGE_CACHE_TTL_SECONDS` defaults to 60 seconds for public knowledge metadata only. Enable `NYANKOFACE_PERFORMANCE_LOG=1` only during diagnostics. Space readiness now has a 20-second budget and an explicit retry path.

## Validation

The release candidate is validated through frontend type, automation, and production builds; bilingual documentation checks and VitePress build; repository Python tests; Docker Compose validation; SVG source and rendered visual review; required GitHub Actions; live documentation checks; and the release QA inventory.

**Full changelog:** https://github.com/Sunwood-ai-labs/NyankoFace/compare/v0.2.0...v0.3.0
