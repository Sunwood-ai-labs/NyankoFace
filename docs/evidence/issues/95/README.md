# Issue #95 — shared navigation visual QA

Runtime: isolated Issue worktree containers behind `http://127.0.0.1:3195`.
Screenshots are captured manually from the real runtime and are not part of CI.

## QA inventory

| Claim / state | Functional check | Visual evidence |
| --- | --- | --- |
| One canonical menu and brand | Compare portal and `/git/`; confirm `nyankoface-navigation.json` v1 is consumed | desktop portal + Forgejo |
| Stable active state | Visit home, directory, details, settings/admin; inspect `aria-current` | light/dark route screenshots |
| Anonymous/authenticated/admin | Inspect login actions, avatar/account, and admin-only action | anonymous + signed-in screenshots |
| Desktop/mobile information architecture | Compare primary and More/hamburger destinations | 1440px + 390px screenshots |
| Mobile interaction safety | Open by tap, Tab cycle, Escape close, backdrop close, scroll lock | menu-open screenshot + DOM assertions |
| No duplicated shell | Count global headers and inspect Space/full-screen opt-out | DOM assertions on portal, Forgejo, Space route |
| #25/#42/#75 regressions | Check visible authenticated controls, no transparent target, no desktop mobile layout | screenshots + viewport metrics |
| Theme consistency | Check standard light and cyberpunk dark | paired screenshots |

Exploratory checks: a long translated/admin label at 390px; direct `/git/` load while the canonical JSON endpoint is unavailable (native single-navbar fallback).

## Result

Passed on the isolated runtime.

- Portal and Forgejo render one 64px global shell with the same NyankoFace mark,
  primary order, and overflow destinations.
- Repository routes expose `Repositories` as the current destination through
  `aria-current="page"`; portal route matching is covered by unit tests.
- Anonymous actions, the authenticated account menu, and the admin-only
  `Administration` destination were exercised against a real Forgejo session.
- At 390px, both menus lock document scroll, move focus into the menu, wrap
  `Shift+Tab` from the first to the final item, close on `Escape`, and restore
  focus to the toggle.
- Intercepting `nyankoface-navigation.json` with HTTP 503 leaves one usable
  native Forgejo navbar and does not create a duplicate shell.
- Desktop and mobile pages reported no horizontal document overflow.
- An authenticated admin sees the shared `config.publish` destinations in both
  the desktop More menu and the mobile `Create & publish` section.
- Resizing an open menu through 1440px -> 390px -> 1440px -> 390px clears the
  body scroll lock, closes the desktop sheet, and leaves no stale inline layout
  styles before the mobile menu is opened again.

## Screenshot matrix

| Surface | Theme / audience | Evidence |
| --- | --- | --- |
| Portal home | Standard, anonymous, desktop | [portal-home-light-desktop.png](./portal-home-light-desktop.png) |
| Portal menu | Standard, anonymous, mobile | [portal-home-light-mobile-menu.png](./portal-home-light-mobile-menu.png) |
| Portal home | Cyberpunk, anonymous, desktop | [portal-home-dark-desktop.png](./portal-home-dark-desktop.png) |
| Portal menu | Cyberpunk, anonymous, mobile | [portal-home-dark-mobile-menu.png](./portal-home-dark-mobile-menu.png) |
| Forgejo login | Standard, anonymous, desktop | [forgejo-login-light-desktop.png](./forgejo-login-light-desktop.png) |
| Forgejo menu | Standard, anonymous, mobile | [forgejo-login-light-mobile-menu.png](./forgejo-login-light-mobile-menu.png) |
| Forgejo repository | Standard, authenticated, desktop | [forgejo-repo-light-desktop-authenticated.png](./forgejo-repo-light-desktop-authenticated.png) |
| Forgejo repository | Cyberpunk, authenticated admin, desktop | [forgejo-repo-dark-desktop-authenticated.png](./forgejo-repo-dark-desktop-authenticated.png) |
| Forgejo menu | Cyberpunk, authenticated admin, mobile | [forgejo-repo-dark-mobile-menu-admin.png](./forgejo-repo-dark-mobile-menu-admin.png) |
| Forgejo More menu | Standard, authenticated admin, desktop | [forgejo-review-publish-desktop.png](./forgejo-review-publish-desktop.png) |
| Forgejo resized menu | Standard, authenticated admin, mobile | [forgejo-review-resize-mobile.png](./forgejo-review-resize-mobile.png) |

## Automated checks

- `npm run lint`
- `npm run test:automation`
- `npm run build`
- Portal and Forgejo production Docker image builds
- `git diff --check`
