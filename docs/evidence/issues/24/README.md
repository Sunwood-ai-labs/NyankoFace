# Issue #24 — truthful repository statistics

Verified on a private deployment at `https://example.invalid` on 2026-07-28.

## What changed

- Forgejo stars and forks use the values returned by the repository API.
- The fork count uses the fork icon; it is no longer presented as a download count.
- Space and Knowledge views/likes come from the persisted metrics API.
- A successful zero remains `0`; a missing or failed metric is shown as `—`.
- Metric elements expose `data-metric-state="available|loading|error|unavailable"` and localized accessible labels.
- The Spaces route has an explicit loading skeleton while repositories and statistics are being fetched.

## API-to-screen comparison

The first five Space cards were compared with
`GET /runner-api/metrics/repos/nyankoface/{repo}`:

| Repository | API views | Screen views | API likes | Screen likes |
|---|---:|---:|---:|---:|
| `humanless-autopilot` | 9 | 9 | 0 | 0 |
| `patent-image-converter` | 12 | 12 | 3 | 3 |
| `verb-tense-converter` | 14 | 14 | 2 | 2 |
| `panorama-metadata-injector` | 10 | 10 | 2 | 2 |
| `qr-code-generator` | 482 | 482 | 2 | 2 |

## Screenshot evidence

| Desktop — recorded values | Mobile — recorded values |
|---|---|
| ![Desktop Spaces cards showing API-backed views and likes](statistics-desktop.png) | ![Mobile Spaces cards showing API-backed views and likes](statistics-mobile.png) |

The metrics service was then stopped briefly. All visible metrics changed to
`data-metric-state="unavailable"`, displayed `—`, and exposed the Japanese
tooltips `いいね数を取得できません` / `閲覧数を取得できません` rather than
fabricating zero values.

![Mobile unavailable-state cards showing em dashes rather than zero](statistics-unavailable-mobile.png)

After the service restarted, the same page reported 60 available metric nodes
and zero unavailable nodes.

## Mechanical verification

- `npm run lint --prefix frontend`
- `npm run build --prefix frontend`
- `git diff --check`
- metrics API response compared with rendered DOM values
- desktop viewport: 1440 × 1000
- mobile viewport: 390 × 844

