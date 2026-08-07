# Navigation and brand audit

- Generated: 2026-08-05T18:15:10.732Z
- Result: **PASS**
- Portal/Forgejo base: `https://localhost:8443`
- Docs base: `not configured`
- Auth states: anonymous

## Source checks

- PASS — navigation manifest has one versioned source of truth
- PASS — portal consumes every navigation group and canonical brand mark
- PASS — portal layout exposes the versioned metadata and navigation shell
- PASS — Forgejo consumes the shared navigation manifest with progressive fallback
- PASS — Forgejo image wiring points to generated canonical assets
- PASS — VitePress uses the shared brand asset family
- PASS — legacy platform brand references are absent from active source
- PASS — legacy assets are inventory-only and not silently used

## Runtime checks

- SKIP — docs-home
- SKIP — docs-guide
- SKIP — docs-not-found
- PASS — anonymous/desktop/portal-home
- PASS — anonymous/desktop/portal-directory
- PASS — anonymous/desktop/portal-not-found
- PASS — anonymous/desktop/forgejo-home
- PASS — anonymous/desktop/forgejo-repository
- PASS — anonymous/desktop/forgejo-files
- PASS — anonymous/desktop/forgejo-community
- PASS — anonymous/desktop/forgejo-login
- PASS — anonymous/desktop/forgejo-not-found
- PASS — anonymous/mobile/portal-home
- PASS — anonymous/mobile/portal-directory
- PASS — anonymous/mobile/portal-not-found
- PASS — anonymous/mobile/forgejo-home
- PASS — anonymous/mobile/forgejo-repository
- PASS — anonymous/mobile/forgejo-files
- PASS — anonymous/mobile/forgejo-community
- PASS — anonymous/mobile/forgejo-login
- PASS — anonymous/mobile/forgejo-not-found

The JSON file contains route, shell, auth state, viewport, navigation, brand, overflow, and browser-error details. This audit intentionally writes no screenshots.

