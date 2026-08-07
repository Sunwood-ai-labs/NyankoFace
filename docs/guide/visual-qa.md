---
title: Visual QA for development agents
type: guide
description: Verify layouts, themes, interactions, and responsive states with screenshot evidence.
readingTime: 12 min
tags: [visual-qa, playwright, themes]
related:
  - title: Agent operations
    link: /wiki/agent-operations
  - title: Troubleshooting
    link: /guide/troubleshooting
---

# Visual QA for development agents

NyankoFace treats screenshots as manual review evidence, not as an automated verdict. Visual QA is run locally against the real Docker Compose application or a deployed environment. It is deliberately excluded from GitHub Actions because capture generation alone does not establish visual correctness, and an exhaustive matrix is too expensive to build and retain on every push.

CI handles deterministic build, lint, unit, integration, configuration, and documentation checks. A UI change is complete only after someone runs a focused browser audit and opens the resulting images.

## What a local review packet contains

The scripts write the following files under `visual-tests/artifacts/`:

| Path | Purpose |
|---|---|
| `AGENT_REVIEW.md` | Human- and agent-readable screenshot index with a review focus for each screen |
| `manifest.json` | Exact URL, final URL, viewport, HTTP status, title, heading, overflow, browser errors, request failures, and automated defects |
| `screenshots/*.png` | Full-page desktop and mobile captures |
| `diagnostics/` | Compose process state and logs, including failed runs |

Generated artifacts are intentionally excluded from Git. Source-controlled route coverage lives in `visual-tests/routes.mjs`.

## Agent review procedure

1. Start the exact commit and environment being reviewed.
2. Run the focused visual audit locally.
3. Read `AGENT_REVIEW.md` and open every screenshot in scope.
4. Check the stated focus and look for clipping, blur, overlap, broken assets, wrong navigation, stale runtime state, misleading labels, inconsistent spacing, and mobile regressions.
5. Use `manifest.json` to correlate visual evidence with HTTP failures, console errors, failed requests, and measured horizontal overflow.
6. Report each issue with the screenshot filename, visible evidence, expected result, and likely affected component.

An agent must not mark a UI task complete from HTTP 200 or the manifest alone. It must inspect the rendered PNGs.

## Run locally

Start NyankoFace first, then run:

```bash
npm ci --prefix visual-tests
npm exec --prefix visual-tests -- playwright install chromium
npm run capture --prefix visual-tests
npm run capture:themes --prefix visual-tests
npm run capture:scroll --prefix visual-tests
```

`capture:themes` renders 30 routes in three themes at desktop and mobile sizes (180 full-page screenshots). `capture:scroll` visits those same routes at top, middle, and bottom positions and directly scrolls to late-rendered Dataset Viewer, Inference Providers, and both organizations' Team members sections (564 viewport screenshots and 66 contact sheets).

The output is written to `visual-tests/artifacts/`. A focused run can reduce iteration time:

```bash
VISUAL_QA_ROUTES=spaces,space-app VISUAL_QA_VIEWPORTS=desktop npm run capture --prefix visual-tests
```

In PowerShell:

```powershell
$env:VISUAL_QA_ROUTES = 'spaces,space-app'
$env:VISUAL_QA_VIEWPORTS = 'desktop'
npm run capture --prefix visual-tests
```

## Keep coverage current

When adding a new user-facing route or materially different page state, add it to `visual-tests/routes.mjs`. Use a stable seeded repository for detail pages. Give the entry a concrete `focus` description so the next agent knows what the screenshot is meant to prove.

The scripts fail on navigation errors, HTTP errors, repository-not-found states, uncaught page errors, horizontal overflow, unavailable embedded applications, contradictory Space runtime state, and large light surfaces leaked into Cyberpunk. These checks catch measurable regressions, but they do not replace opening the images. Console errors and failed requests are retained as review observations even when they do not independently fail the run.
