# Issue #151 — MCP admin runbook and visual QA evidence

This evidence closes the documentation and runtime-QA slice of the MCP administration work. It is intentionally scoped to the already merged backend and frontend changes; it does not reimplement either service.

## Review anchors

| Item | Value |
| --- | --- |
| Reviewed main | `926ece00a2763a2dad706ef049094734831f9c7e` |
| Backend PR | [#150](https://github.com/Sunwood-ai-labs/NyankoFace/pull/150), merged as `dbf9154af18ed781a0d7f9929737ee20b464c14c` |
| Frontend/BFF PR | [#152](https://github.com/Sunwood-ai-labs/NyankoFace/pull/152), merged as `926ece00a2763a2dad706ef049094734831f9c7e` |
| Runtime | Local Docker Compose at `https://localhost:8443` |
| Evidence issue | [#151](https://github.com/Sunwood-ai-labs/NyankoFace/issues/151) |

The reviewed SHA is the exact `main` head from which this evidence work was started. The screenshots are local-runtime evidence, not a claim about a production deployment.

## Acceptance checklist

| Requirement | Result | Evidence |
| --- | --- | --- |
| English administration runbook | PASS | [`docs/guide/mcp-administration.md`](../../../guide/mcp-administration.md) |
| Japanese administration runbook | PASS | [`docs/ja/guide/mcp-administration.md`](../../../ja/guide/mcp-administration.md) |
| Three safe client snippets | PASS | Codex CLI, Claude Desktop, and VS Code snippets in both runbooks |
| Re-authentication and fail-closed boundary | PASS | Re-auth screenshots and manual interaction review below |
| One-time token handling | PASS | Sanitized desktop/mobile screenshots below |
| Policy, audit, recovery, and secret boundary guidance | PASS | Both runbooks and the manual findings below |
| Visual QA on real runtime | PASS | 3 themes × 2 viewports, six baseline cases |
| Sanitized machine-readable result manifest | PASS | [`visual-qa-results.json`](./visual-qa-results.json) |
| Screenshot generation in CI | NOT ADDED | Visual capture remains a manual check |

## CLI and runtime checks

The runtime was rebuilt from the reviewed worktree with the MCP profile enabled. Secret contents were never included in commands, output, or this document.

```text
docker compose --profile mcp up -d --build nyankoface-mcp mcp-admin       PASS
docker compose --profile mcp build frontend gateway                     PASS
docker compose --profile mcp up -d --no-deps frontend gateway           PASS
docker compose --profile mcp ps                                         all required services healthy
GET http://mcp-admin:8001/health                                        {"status":"ok"}
focused Playwright baseline capture                                    6/6 PASS
```

The focused Playwright run exercised the real browser route through the gateway. Every baseline case reported `status=200`, `overflow=0`, and zero post-reauth page/console or HTTP errors. An authenticated administrator without a valid re-authentication proof receives the expected pre-reauth `428 fresh_reauthentication_required`; this was recorded as the authentication boundary, not as a test failure. One-time-secret flows completed on desktop and mobile, and the temporary QA data was cleaned up afterward.

The case-by-case sanitized result and cleanup counts are recorded in [`visual-qa-results.json`](./visual-qa-results.json). It contains no token, digest, account credential, or other secret value.

## Visual matrix

The baseline matrix checks the re-authentication surface and the authenticated administration console. Each image was opened for manual inspection after capture.

| Theme | Viewport | Re-authentication | Console | Result |
| --- | --- | --- | --- | --- |
| Standard/base | Desktop 1440×1000 | [reauth](./screenshots/standard-desktop-admin-reauth.png) | [console](./screenshots/standard-desktop-admin-console.png) | PASS |
| Standard/base | Mobile 390×844 | [reauth](./screenshots/standard-mobile-admin-reauth.png) | [console](./screenshots/standard-mobile-admin-console.png) | PASS |
| Solarpunk/light | Desktop 1440×1000 | [reauth](./screenshots/solarpunk-desktop-admin-reauth.png) | [console](./screenshots/solarpunk-desktop-admin-console.png) | PASS |
| Solarpunk/light | Mobile 390×844 | [reauth](./screenshots/solarpunk-mobile-admin-reauth.png) | [console](./screenshots/solarpunk-mobile-admin-console.png) | PASS |
| Cyberpunk/dark | Desktop 1440×1000 | [reauth](./screenshots/cyberpunk-desktop-admin-reauth.png) | [console](./screenshots/cyberpunk-desktop-admin-console.png) | PASS |
| Cyberpunk/dark | Mobile 390×844 | [reauth](./screenshots/cyberpunk-mobile-admin-reauth.png) | [console](./screenshots/cyberpunk-mobile-admin-console.png) | PASS |

### One-time secret evidence

These two screenshots show the one-time dialog after a local QA token was issued. The token and temporary QA identifiers were redacted before the files were saved. The screenshots prove the warning, the copy/connection/discard controls, and the responsive layout; they deliberately do not expose a credential.

| Viewport | Sanitized dialog |
| --- | --- |
| Desktop 1440×1000 | [one-time secret dialog](./screenshots/standard-desktop-admin-secret.png) |
| Mobile 390×844 | [one-time secret dialog](./screenshots/standard-mobile-admin-secret.png) |

## Manual findings

- The re-authentication boundary is visible before the console is used; the authenticated page is not shown to anonymous users.
- Desktop and mobile layouts keep the headline, tabs, forms, token controls, one-time dialog, and footer inside the viewport. No horizontal overflow, clipped label, or overlapping control was observed.
- Standard/base, solarpunk/light, and cyberpunk/dark themes retain readable contrast and recognizable selected-tab/control states.
- The one-time dialog clearly warns that the value cannot be shown again. Copy, connection-test, and discard actions remain reachable on both tested widths.
- The saved secret images contain only `[redacted for evidence]` in the token slot and `[redacted QA data]` in temporary account/token fields. No live credential is part of the evidence set.

## Cleanup and limitations

The local QA run created temporary subjects and tokens only in the local Compose state. Cleanup verification reported four subjects disabled, zero active tokens, and all ten temporary tokens revoked or expired. Registry digests and audit records remain operational data; no token plaintext was retained in the repository or evidence images.

This is manual visual evidence against a local Compose runtime. It does not replace the backend/frontend unit and contract tests already run by PR #150 and PR #152, and visual capture is intentionally not a CI job. Re-run this matrix after a material admin UI change or before a production release.
