# Issue #178 — navigation and brand runtime evidence

The strengthened navigation/brand audit was run against the local NyankoFace
runtime at `https://localhost:8443` on 2026-08-05. It exercised 18 anonymous
portal and Forgejo routes at desktop (1440px) and mobile (390px) widths.

## Results

- [Machine-readable audit](latest-audit.json)
- [Audit report](REPORT.md)
- [Desktop/mobile visual packet](captures/AGENT_REVIEW.md)
- [Capture manifest](captures/manifest.json)
- [Screenshots](captures/screenshots/desktop--home.png), [desktop Explore](captures/screenshots/desktop--global-nav-explore.png), [desktop Forgejo](captures/screenshots/desktop--forgejo-home.png), [desktop login](captures/screenshots/desktop--login.png), [mobile home](captures/screenshots/mobile--home.png), [mobile Explore](captures/screenshots/mobile--global-nav-explore.png), [mobile Forgejo](captures/screenshots/mobile--forgejo-home.png), [mobile login](captures/screenshots/mobile--login.png)

All 18 runtime cases passed. The audit also passed source checks for the
versioned navigation manifest, canonical mark wiring, favicon/PWA asset family,
absence of legacy logo references, and horizontal overflow. The docs routes
were marked skipped because no separate docs base URL was configured for this
runtime packet.

The visual packet covers the portal home, Explore menu, Forgejo home, and login
surface at both widths. Screenshots are manual review evidence, not a CI gate.
The packet was captured anonymously; authenticated/admin states should be
added when those credentials are available for a deployment-specific audit.

## Reproduction

```powershell
$env:NAVIGATION_BRAND_BASE_URL = 'https://localhost:8443'
$env:NAVIGATION_BRAND_OUTPUT_DIR = 'docs/evidence/issues/178'
npm run audit:navigation-brand --prefix visual-tests

$env:VISUAL_QA_BASE_URL = 'https://localhost:8443'
$env:VISUAL_QA_OUTPUT_DIR = 'docs/evidence/issues/178/captures'
$env:VISUAL_QA_ROUTES = 'home,global-nav-explore,forgejo-home,login'
npm run capture --prefix visual-tests
```
