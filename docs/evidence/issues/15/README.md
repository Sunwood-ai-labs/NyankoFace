# Issue #15 — configurable application name

The portal and Forgejo were recreated twice from the same images:

1. with `APP_NAME=Aurora Hub`;
2. with `APP_NAME` unset, exercising the `NyankoFace` default.

`visual-tests/app-name-audit.mjs` checks the rendered navbar brand, browser
title, search accessibility label, Forgejo `AppDisplayName` metadata, HTTP
status, and horizontal overflow at desktop and mobile widths.

| Configuration | Cases | Result |
|---|---:|---|
| `APP_NAME=Aurora Hub` | 4 | PASS |
| unset (`NyankoFace`) | 4 | PASS |

## Custom-name screenshots

| Portal | Forgejo login |
|---|---|
| [Desktop](custom/screenshots/portal-home--desktop.png) | [Desktop](custom/screenshots/forgejo-login--desktop.png) |
| [Mobile](custom/screenshots/portal-home--mobile.png) | [Mobile](custom/screenshots/forgejo-login--mobile.png) |

## Default-name screenshots

| Portal | Forgejo login |
|---|---|
| [Desktop](default/screenshots/portal-home--desktop.png) | [Desktop](default/screenshots/forgejo-login--desktop.png) |
| [Mobile](default/screenshots/portal-home--mobile.png) | [Mobile](default/screenshots/forgejo-login--mobile.png) |

Machine-readable reports:

- [custom name](custom/report.json)
- [default name](default/report.json)
