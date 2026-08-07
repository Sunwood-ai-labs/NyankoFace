# NyankoFace visual QA

This directory creates a screenshot packet that a human or development agent can review after a UI change. It captures every major page type at desktop and mobile sizes, then records navigation status, headings, horizontal overflow, console errors, failed requests, HTTP resource errors, and full-page screenshots.

```bash
npm ci --prefix visual-tests
npm exec --prefix visual-tests -- playwright install chromium
npm run capture --prefix visual-tests
```

Open `visual-tests/artifacts/AGENT_REVIEW.md` and inspect every linked image. The adjacent `manifest.json` is the machine-readable source for automated agent feedback.

Environment variables:

- `VISUAL_QA_BASE_URL`: deployment URL; defaults to `https://localhost:8443`.
- `VISUAL_QA_OUTPUT_DIR`: artifact directory; defaults to `visual-tests/artifacts`.
- `VISUAL_QA_VIEWPORTS`: comma-separated viewport IDs such as `desktop` or `mobile`.
- `VISUAL_QA_ROUTES`: comma-separated route IDs from `routes.mjs` for focused checks.

Add a route to `routes.mjs` whenever a new user-facing page type is introduced. Screenshots are evidence for a human or development agent to inspect locally or against the deployed environment; CI does not treat pixels as a visual verdict.

## Navigation and brand drift audit

Run the source, SSR, and hydrated-DOM audit for the first-party portal and
Forgejo shells. It compares rendered navigation with
`frontend/public/nyankoface-navigation.json`, checks canonical brand asset
references, records anonymous/authenticated/admin cases when storage states are
provided, and writes JSON/Markdown only (no screenshots):

```bash
NAVIGATION_BRAND_BASE_URL=http://localhost:8090 \
NAVIGATION_BRAND_DOCS_BASE_URL=http://localhost:4173/NyankoFace \
npm run audit:navigation-brand --prefix visual-tests
```

Use `NAVIGATION_BRAND_AUTHENTICATED_STATE` and
`NAVIGATION_BRAND_ADMIN_STATE` for Playwright storage-state files. For a
source-only check when no runtime is available, set
`NAVIGATION_BRAND_SOURCE_ONLY=1`. The route inventory is the
`navigationBrandAuditRoutes` export in `routes.mjs`; user-created Pages and
Space iframe routes are deliberately excluded.

## Focused Space checks

Audit a public CPU Space as an anonymous desktop and mobile visitor. The script waits for the real embedded application, checks horizontal overflow, and records runtime/request/iframe timings alongside the screenshots.

```bash
VISUAL_QA_BASE_URL=http://localhost:8090 \
PUBLIC_SPACE_REPO=sample-vue \
npm run audit:public-space --prefix visual-tests
```

Use `PUBLIC_SPACE_OWNER` to override the default `seraphim-labs` owner and
`PUBLIC_SPACE_QA_OUTPUT_DIR` to keep the focused screenshots outside the
default `visual-tests/artifacts/public-space` directory.

Compare navigation between two frontend revisions and enforce immediate feedback p95 at or below 100 ms:

```bash
BASELINE_URL=http://localhost:3102 \
CANDIDATE_URL=http://localhost:3103 \
SPACE_NAV_TARGET=/seraphim-labs/sample-vue \
SPACE_NAV_SAMPLES=10 \
SPACE_NAV_REPORT=artifacts/space-navigation.json \
npm run benchmark:space-navigation --prefix visual-tests
```

The benchmark runs cold and warm browser samples for each origin. Treat its measurements as environment-specific evidence and publish the raw report with any performance claim.
