# Contributing to NyankoFace

Thank you for helping improve NyankoFace. Small, focused changes with clear verification are the easiest to review.

## Development setup

1. Install Docker Desktop or another Docker Engine with Compose v2.
2. Copy `.env.example` to `.env` and change the bootstrap password.
3. Run `docker compose up -d --build`.
4. Open `https://localhost:8443` and accept the local development certificate warning.

The frontend can also be checked independently:

```bash
cd frontend
npm ci
npm run build
```

## Before opening a pull request

- Keep credentials, generated certificates, logs, databases, and local screenshots out of Git.
- Run `docker compose config`.
- Run `npm ci && npm run build` in `frontend/` when frontend code changes.
- Build the documentation when docs change.
- Add or update browser evidence when behavior or layout changes.
- Explain any security effect of changes to Docker socket access, repository visibility, authentication, or proxy routing.

## Commit and pull request scope

- Prefer one coherent concern per commit.
- Describe what changed, why it changed, and how it was verified.
- Link an issue when one exists.
- Do not commit generated Space repositories from `sample-spaces/`; they are published independently to the local Forgejo instance.

By contributing, you agree that your contribution is licensed under the repository's MIT license.
