# Issue #16 visual evidence

Forgejo keeps the active stopwatch trigger in the authenticated navbar DOM, but
NyankoFace must not reveal it when no time tracker is active. The focused audit
logs in, verifies the computed visibility of both the trigger and its yellow
dot, and captures desktop and mobile screenshots.

- `desktop--navbar-without-stopwatch-dot.png`
- `mobile--navbar-without-stopwatch-dot.png`
- `report.json`

Run:

```bash
npm run audit:stopwatch-indicator --prefix visual-tests
```
