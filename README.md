<p align="center">
  <img src="docs/public/nyankoface.svg" width="104" alt="NyankoFace logo">
</p>

<h1 align="center">NyankoFace</h1>

<p align="center"><strong>The AI community building locally.</strong></p>

<p align="center">
  A local-first, Forgejo-backed hub for Models, Datasets, Docker Spaces, Characters, Benchmarks, Skills, MCPs, versioned Prompts, portable Automations, Knowledge, and static Pages.
</p>

<p align="center">
  <a href="README.md"><strong>English</strong></a> · <a href="README.ja.md">日本語</a> · <a href="https://sunwood-ai-labs.github.io/NyankoFace/">Documentation</a>
</p>

<p align="center">
  <a href="https://github.com/Sunwood-ai-labs/NyankoFace/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/Sunwood-ai-labs/NyankoFace/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://github.com/Sunwood-ai-labs/NyankoFace/actions/workflows/docs.yml"><img alt="Docs" src="https://github.com/Sunwood-ai-labs/NyankoFace/actions/workflows/docs.yml/badge.svg"></a>
  <a href="https://github.com/Sunwood-ai-labs/NyankoFace/releases/latest"><img alt="Release" src="https://img.shields.io/github/v/release/Sunwood-ai-labs/NyankoFace?display_name=tag"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-yellow.svg"></a>
  <img alt="Docker Compose" src="https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white">
  <img alt="Forgejo" src="https://img.shields.io/badge/Git-Forgejo-fb923c">
</p>

![NyankoFace home showing models, datasets, Spaces, Skills, MCPs, and Prompts](docs/images/nyankoface-home.png)

NyankoFace turns one Docker host into a self-contained AI collaboration platform. Forgejo stores real Git repositories, histories, tags, issues, permissions, and LFS objects. A Next.js portal presents those repositories in a Hugging Face-style catalog, while a FastAPI runner builds and embeds CPU-capable Docker applications. nginx exposes the portal, Git UI, apps, APIs, and Pages through one HTTPS gateway.

The latest release is documented in the [v0.6.0 release notes](docs/guide/releases/v0.6.0.md) and the companion article, [Measure the surface, preserve the evidence](docs/articles/nyankoface-v0-6-0.md). Existing operators should also read the [upgrade and data retention runbook](docs/guide/upgrading.md). The [v0.5.0 notes](docs/guide/releases/v0.5.0.md) and earlier release notes remain available for historical upgrades.

## ✨ Highlights

- **Real repositories:** models, datasets, Skills, MCPs, and Prompts keep their files, commits, tags, clone URLs, and repository permissions.
- **Format-aware Characters:** import PuruPuru PNGTubers, direction-control patches, character sheets, and Codex Pet packages; NyankoFace inspects their real settings, state images, manifests, and spritesheets.
- **Reproducible Benchmarks:** catalog evaluation suites for CAD, SVG, vision, and LLM tasks with runners, task assets, and result evidence kept in Git.
- **Dockerfile-first Spaces:** run Gradio, static HTML, React, Vue, Next.js, Streamlit, FastAPI, Node.js, or another CPU web application on port `7860`.
- **External-link Spaces:** set `external_url` in README frontmatter to open an existing HTTP/HTTPS site directly without an iframe or container build.
- **Always-on CPU mode:** `IDLE_TIMEOUT_MINUTES=0` keeps CPU Spaces running; a least-recently-used cap prevents unbounded growth.
- **NyankoFace Pages:** serve `gh-pages` or default-branch `docs/`, with a seeded VitePress workflow on an isolated Forgejo Actions runner.
- **NyankoFace MCP operations:** connect Codex, Claude, or VS Code to a stateless Streamable HTTP server with scoped catalog reads, preview-confirmed writes, durable audit records, and an optional local stdio adapter.
- **Repository Pipelines:** install and operate Forgejo Actions from each repository page, including trigger history, live jobs and logs, artifacts, approvals, cancellation, failed-job retry, rollback, API control, and audit records.
- **Agent operations API:** browser views, likes, and agent actions use a persisted metrics service with hashed agent credentials.
- **Claude Code goal maintenance:** mention `@glm-maintainer` on an Issue or agent-created PR; it delegates to a specialist, runs Claude Code's built-in `/goal` with Z.AI-hosted `glm-5.2`, verifies evidence, and auto-merges the Pull Request.
- **Auditable auto-labeling:** signed Issue and Pull Request webhooks add only existing allowlisted labels, preserve manual labels, support dry-run, and record every reason in PostgreSQL.
- **Release branch audit agents:** pushing `release`, `release-*`, or `release/*` starts independent security and documentation audits in parallel and opens human-reviewed PRs back to that release branch.
- **Versioned Prompts:** stable repository slugs point to immutable Git tags that can be switched directly in the Prompt view.
- **Portable Automations:** publish a disabled, versioned TOML manifest; NyankoFace pins it to an immutable commit, audits its schedule, permissions, connectors, workspace, delivery, compatibility, and safety findings, then offers a normalized disabled download without registering or running it.
- **Living Knowledge library:** publish every Markdown entry as a Git-backed article, then compose `news`, `how-to`, `reference`, `benchmark`, and other topics for discovery.
- **Three visual themes:** Standard, Solarpunk, and Cyberpunk persist across visits.
- **Editable organizations:** Forgejo Owners can update organization metadata, avatars, membership, teams, and repositories from the real organization settings UI.
- **Bilingual public docs:** English and Japanese VitePress guides build and deploy through GitHub Actions.

## 🧩 Implemented feature map

| Area | What is available now | Where to configure or verify it |
|---|---|---|
| Catalog | Models, Datasets, Spaces, Characters, Benchmarks, Skills, MCPs, Prompts, Automations, and Knowledge are discovered from real Forgejo repositories. | Add the matching repository topic; see **Repository types, topics, and tags** below. |
| Applications | Dockerfile-based Spaces, external-link Spaces, static Pages, and on-demand lifecycle control. | README frontmatter, root `Dockerfile`, `.env`, and the [Spaces guide](https://sunwood-ai-labs.github.io/NyankoFace/guide/spaces). |
| Collaboration | Repository files, history, Issues, Pull Requests, comments, reactions, organizations, teams, API-backed likes, and view counters with explicit loading/error states. | Forgejo permissions, [Community verification](docs/evidence/community-ui/README.md), and the [statistics audit](docs/evidence/issues/24/README.md). |
| Truthful statistics | Stars and forks come from Forgejo; Space and Knowledge views/likes come from the persisted metrics API. Successful zeroes stay `0`, while unavailable data is shown as `—` instead of a fabricated value. | [Issue #24 API-to-screen audit](docs/evidence/issues/24/README.md). |
| Authenticated navbar | The portal reflects the active Forgejo session, preserves the account state across reloads and route changes, and returns to login/sign-up immediately after logout. | [Issue #25 desktop/mobile session audit](docs/evidence/issues/25/README.md). |
| Space configuration | Repository owners can manage runtime/build/both Variables and encrypted Secrets. Runtime values go only to the container; build values synchronize to native Forgejo Actions storage without being returned by list APIs. | [Variables and Secrets guide](docs/guide/space-environment.md) and [Repository pipelines](docs/guide/pipelines.md). |
| Unified API design | The proposed `/api/v1` facade defines NyankoFace tokens, least-privilege scopes, per-request Forgejo authorization, write-only Secrets, audit/rate/idempotency contracts, migration, and the native Git boundary. | [Unified API and authentication ADR](docs/guide/unified-api.md) and the [machine-readable security contract](docs/contracts/nyankoface-api-v1-security.json). |
| MCP operations | A stateless MCP endpoint exposes scoped catalog, repository, Issue, Space, Pages, and Pipeline tools/resources; write paths require caller authorization, preview/confirmation, idempotency, and audit. | [NyankoFace MCP Server](docs/guide/mcp-server.md), [MCP administration runbook](docs/guide/mcp-administration.md), and [live MCP client QA](docs/guide/mcp-live-clients.md). |
| Portable Automation catalog | Versioned, disabled TOML manifests with immutable-revision preflight, safety findings, and normalized download. | Add the `automation` topic and follow **Publishing a portable Automation** below. |
| Platform automation | Repository Pipelines, Forgejo Actions, VitePress publishing, Claude Code `/goal` maintenance, specialist-agent delegation, release audits, and guarded auto-merge. | `.forgejo/workflows/`, `maintenance-agent/`, the [pipeline guide](docs/guide/pipelines.md), [Issue #70 runtime/UI evidence](docs/evidence/issues/70/README.md), and the [maintenance guide](docs/guide/automated-maintenance.md). |
| Presentation | Three persistent themes, Japanese/English UI, responsive desktop/mobile layouts, Markdown and Mermaid rendering, configurable `APP_NAME`, and a shared portal/Forgejo identity. | `.env`, browser controls, and [`docs/evidence/`](docs/evidence/). |
| Desktop utility pages | Authenticated Settings, Notifications, and Site Administration preserve their full desktop rails at 1280px and 1440px. | [Issue #14 screenshot audit](docs/evidence/issues/14/README.md). |
| Navbar state | The inactive Forgejo stopwatch element remains available in the DOM but no longer renders as an unexplained status dot. | [Issue #16 screenshot audit](docs/evidence/issues/16/README.md). |

Application naming is controlled by one `APP_NAME` value and is verified on both the Next.js portal and Forgejo surfaces in desktop and mobile layouts. See the [default/custom branding audit](docs/evidence/issues/15/README.md).

### Recently verified additions

| Issue | Addition | Evidence |
|---|---|---|
| [#24](https://github.com/Sunwood-ai-labs/NyankoFace/issues/24) | Real repository and persisted interaction statistics, correct fork iconography, loading states, and an explicit unavailable state. | [API values, failure simulation, and screenshots](docs/evidence/issues/24/README.md) |
| [#25](https://github.com/Sunwood-ai-labs/NyankoFace/issues/25) | Forgejo-aware account navbar with reload/navigation persistence and immediate logout feedback. | [Desktop/mobile login-state screenshots](docs/evidence/issues/25/README.md) |
| [#26](https://github.com/Sunwood-ai-labs/NyankoFace/issues/26) | Immediate Space operation spinners, duplicate-submit prevention, accessible success/failure feedback, and per-phase server timing. | [Busy/success/failure screenshots and timing evidence](docs/evidence/issues/26/README.md) |
| [#27](https://github.com/Sunwood-ai-labs/NyankoFace/issues/27) | Installable NyankoFace Navigator Skill for choosing, scaffolding, and validating the smallest publishing path. | [`skills/nyankoface-navigator/`](skills/nyankoface-navigator/) |
| [#28](https://github.com/Sunwood-ai-labs/NyankoFace/issues/28) | Owner-only runtime Variables and encrypted Secrets with masked reads, rotation/deletion, audit records, and fail-closed GPU handling. | [Security assertions and responsive screenshots](docs/evidence/issues/28/README.md) |
| [#37](https://github.com/Sunwood-ai-labs/NyankoFace/issues/37) | Rebuild-safe seed application guide covering both generated catalog repositories and tracked Docker Space samples. | [Source locations, lifecycle diagram, and update/removal procedures](docs/guide/seed-apps.md) |
| [#38](https://github.com/Sunwood-ai-labs/NyankoFace/issues/38) | Deterministic Issue/PR auto-labeling with an existing-label allowlist, confidence threshold, dry-run, preview API, and PostgreSQL audit trail. | [Configuration, safety rules, API, and screenshot evidence](docs/evidence/issues/37-38/README.md) |
| Sample | Production CPU Space that consumes three runtime Variables and uses an encrypted Secret to create a server-side HMAC receipt without exposing the raw value. | [Source, live URLs, assertions, and desktop/mobile screenshots](docs/evidence/environment-space-sample/README.md) |

| Seed source guide | Production Issue auto-label |
|---|---|
| ![Seed application guide with source-of-truth table](docs/evidence/issues/37-38/seed-guide-desktop.png) | ![Issue showing automatic documentation and question labels](docs/evidence/issues/37-38/issue-27-mobile.png) |

## 🚀 Quick start

### Requirements

- Docker Engine or Docker Desktop
- Docker Compose v2 (`docker compose`)
- Git for cloning or contributing

Node.js and Python are not required on the host for the normal Compose path.

```bash
git clone https://github.com/Sunwood-ai-labs/NyankoFace.git
cd NyankoFace
cp .env.example .env
docker compose up -d --build
```

On Windows PowerShell, use `Copy-Item .env.example .env` instead of `cp`.

Before sharing the deployment, change `NYANKOFACE_ADMIN_PASSWORD` in `.env`. Then open:

- HTTPS portal: [https://localhost:8443](https://localhost:8443)
- Certificate-free HTTP endpoint: [http://localhost:8090](http://localhost:8090)

For private access from phones or remote devices, configure the gateway and
trusted network in the private deployment environment. Keep the public
repository limited to placeholders; do not commit hostnames, LAN addresses,
certificates, or network-specific helper scripts.
- Forgejo SSH: `ssh://git@localhost:2222/OWNER/REPOSITORY.git`

The local gateway generates a self-signed development certificate on first start. Replace it with a trusted certificate for a shared deployment.

Verify the stack:

```bash
docker compose ps
docker compose logs seed
```

The seed job should finish successfully. Long-running services should be healthy or running.

## 🔌 MCP Server setup

NyankoFace MCP is an optional, authenticated integration for Codex, Claude Desktop,
and VS Code. Enable it only for trusted operators on a private network. Use a
trusted HTTPS certificate for shared deployments, and keep every Forgejo PAT and
MCP bearer token outside Git, `.env`, issue comments, shell history, screenshots,
and client configuration committed to the repository.

### Start the MCP profile

Create the registry and secret files before asking Compose to load the profile.
The registry is policy and service-account configuration; the Forgejo PAT belongs
in the separate Docker Secret file and must be least-privileged.

```bash
mkdir -p secrets/nyankoface-mcp
if [ ! -f secrets/nyankoface-mcp/registry.json ]; then
  cp nyankoface-mcp/registry.example.json secrets/nyankoface-mcp/registry.json
fi
# Edit registry.json with service-account mappings and minimum scopes.
# Put the mapped Forgejo PAT in secrets/nyankoface-mcp-forgejo-user-token.
# Generate the private BFF-to-admin credential locally; do not commit this file.
if [ ! -f secrets/nyankoface-mcp-admin-internal-token ]; then
  openssl rand -hex 32 > secrets/nyankoface-mcp-admin-internal-token
fi
chmod 600 secrets/nyankoface-mcp-admin-internal-token
docker compose --profile mcp config --quiet
docker compose --profile mcp up -d --build frontend gateway nyankoface-mcp mcp-admin
```

PowerShell users can use the following equivalent create-if-absent steps (the
random generator does not rotate an existing bridge credential):

```powershell
New-Item -ItemType Directory -Force secrets/nyankoface-mcp | Out-Null
if (-not (Test-Path -LiteralPath secrets/nyankoface-mcp/registry.json -PathType Leaf)) {
  Copy-Item nyankoface-mcp/registry.example.json secrets/nyankoface-mcp/registry.json
}
$forgejoTokenPath = 'secrets/nyankoface-mcp-forgejo-user-token'
if (-not (Test-Path -LiteralPath $forgejoTokenPath -PathType Leaf)) {
  throw "Create $forgejoTokenPath from your secret manager with a least-privileged Forgejo PAT before starting Compose."
}
$adminTokenPath = 'secrets/nyankoface-mcp-admin-internal-token'
if (-not (Test-Path -LiteralPath $adminTokenPath -PathType Leaf)) {
  $bytes = New-Object byte[] 32
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
  $token = -join ($bytes | ForEach-Object { $_.ToString('x2') })
  [System.IO.File]::WriteAllText($adminTokenPath, $token, [System.Text.Encoding]::ASCII)
}
```

Keep the token file readable only by the deployment account (for example with
the host's ACL tooling).
The official remote endpoint is `https://<NYANKOFACE_HOST>/mcp`. It uses stateless
MCP Streamable HTTP: the default response is SSE; set
`NYANKOFACE_MCP_JSON_RESPONSE=true` when the client requires one JSON response.
Both modes use the same authentication and authorization policy. Local stdio is
an adapter for clients that cannot use the remote transport directly; it still
connects to the same `/mcp` endpoint and must read its token from a protected
secret store or restricted token file.

### Issue and rotate credentials safely

An administrator creates and manages service-account mappings and client tokens
at `/admin/mcp`; the detailed [MCP administration runbook](docs/guide/mcp-administration.md)
also covers the offline lifecycle tool. Map a service account to one Forgejo
identity, grant only the required scopes (for example `catalog:read` and
`repos:read`), constrain repositories explicitly (for example
`nyankoface/example=read`), and choose the shortest practical token TTL. Re-authenticate
before issuing, rotating, revoking, disabling, or remapping credentials. The
one-time token result must go directly into the client's protected secret store.

### Configure clients

Use the transport that each client supports. Never replace a placeholder below
with a token in a tracked file.

- **Codex CLI — remote Streamable HTTP:** load the token into the environment
  from an OS secret store or restricted file, then register the HTTPS endpoint:

  ```powershell
  $env:NYANKOFACE_MCP_TOKEN_FILE = '<RESTRICTED_TOKEN_FILE>'
  $env:NYANKOFACE_MCP_TOKEN = (Get-Content -LiteralPath $env:NYANKOFACE_MCP_TOKEN_FILE -Raw).Trim()
  codex mcp add nyankoface --url https://<NYANKOFACE_HOST>/mcp --bearer-token-env-var NYANKOFACE_MCP_TOKEN
  ```

- **Claude Desktop — local stdio:** install the verified host-side adapter before
  using this entry (from this checkout, `python -m pip install --upgrade ./nyankoface-mcp`,
  or install the verified release wheel), then use `nyankoface-mcp-stdio` with
  `NYANKOFACE_MCP_REMOTE_URL` and `NYANKOFACE_MCP_CLIENT_TOKEN_FILE` in the local
  `claude_desktop_config.json`. The token file must be protected and must not
  be checked in. The static-bearer remote endpoint is not compatible with
  Claude Desktop's remote custom connector flow; use local stdio until the
  documented OAuth/live-client path is available.

  ```json
  {
    "mcpServers": {
      "nyankoface": {
        "command": "nyankoface-mcp-stdio",
        "env": {
          "NYANKOFACE_MCP_REMOTE_URL": "https://<NYANKOFACE_HOST>/mcp",
          "NYANKOFACE_MCP_CLIENT_TOKEN_FILE": "<RESTRICTED_TOKEN_FILE>"
        }
      }
    }
  }
  ```

- **VS Code — remote Streamable HTTP:** start from the checked-in
  [`vscode-mcp.json`](nyankoface-mcp/examples/vscode-mcp.json), replace the
  `<NYANKOFACE_HOST>` URL placeholder with your deployment host only; keep the
  `/mcp` path from the template, keep the
  `${input:nyankoface-token}` password prompt, and enter the token only when VS
  Code asks for it. Do not replace that input with a literal bearer value.

Fully quit and restart a client after changing its MCP entry. The detailed
[MCP server guide](docs/guide/mcp-server.md) and
[live client matrix](docs/guide/mcp-live-clients.md) are the source of truth
for transport, platform, and secret-store differences.

### Verify the connection and diagnose failures

`validate-config` checks only the local stdio adapter environment; it does not
read a Codex/VS Code client entry or verify the remote deployment. Set the
stdio adapter variables in the shell that will run the command, without
printing the token, then verify health and the protocol from the client or
`/admin/mcp` connection test:

```bash
# Use a protected token file or an OS secret store; do not paste a token here.
export NYANKOFACE_MCP_REMOTE_URL="https://<NYANKOFACE_HOST>/mcp"
export NYANKOFACE_MCP_CLIENT_TOKEN_FILE="<RESTRICTED_TOKEN_FILE>"
nyankoface-mcp validate-config
docker compose --profile mcp ps nyankoface-mcp mcp-admin gateway
```

The connection test should complete `initialize`, `tools/list`, and
`resources/list`, followed by one representative read. An invalid or expired
token should fail at HTTP authentication before initialization; a valid token
with insufficient scope or repository access should fail closed at authorization.
Inspect `docker compose --profile mcp logs nyankoface-mcp mcp-admin` and the
[administration recovery runbook](docs/guide/mcp-administration.md#recovery-runbook),
but never paste token values or upstream secret-bearing errors into a ticket.

### Upgrade, rollback, uninstall, and revoke

For a package upgrade, verify the wheel checksum and build provenance, install
the new version, restart the local client, and repeat `validate-config` plus the
connection test. For a rollback, retain the prior verified wheel or image
digest, reinstall that exact artifact, restart, and repeat the same checks; do
not delete the MCP state before recovery is complete. To uninstall, remove the
client entry, revoke its token, uninstall the local `nyankoface-mcp` package (if
used), and rotate the mapped Forgejo PAT when compromise is possible. Keep the
registry, write-safety state, and audit evidence backed up together. See the
[MCP server lifecycle section](docs/guide/mcp-server.md#lifecycle)
for the exact release and recovery commands.

## 🧭 What gets created

| Service | Responsibility | Exposure |
|---|---|---|
| `gateway` | nginx routing, TLS, WebSockets, single web entrypoint | local entrypoint |
| `frontend` | Next.js discovery portal and repository pages | private service |
| `forgejo` | Git, LFS, authentication, ACLs, Issues, Pull Requests, Actions | private service |
| `postgres` | Forgejo, metrics, and maintenance persistence | private service |
| `spaces-runner` | Space build/run/proxy, Pages, views, likes, agent API | private service |
| `seed` | Idempotent admin, token, organization, catalog, examples, and Prompt tags | one-shot |
| `forgejo-actions-runner` | Pages workflow jobs | internal |
| `forgejo-actions-dind` | Isolated Docker daemon for Actions | runner-only Unix socket |
| `maintenance-agent` | Signed Issue webhook, Claude Code `/goal`, branch and PR creation | internal `8010` |

The exact source-of-truth locations, registration timing, update commands, and
safe removal process for bootstrap repositories and sample Spaces are documented
in [Seed applications and catalogs](docs/guide/seed-apps.md).

```mermaid
flowchart LR
    User["Browser / Git / Agent"] --> Gateway["nginx gateway<br/>8090 / 8443"]
    Gateway --> Frontend["Next.js portal"]
    Gateway --> Forgejo["Forgejo Git + LFS"]
    Gateway --> Runner["FastAPI Space runner"]
    Frontend --> Forgejo
    Frontend --> Runner
    Forgejo --> Postgres["PostgreSQL"]
    Runner --> Postgres
    Maintenance["Maintenance agent"] --> Postgres
    Runner --> Space["CPU Docker Spaces"]
    Runner --> Pages["Static Pages"]
    Seed["Idempotent seed"] --> Forgejo
    Actions["Forgejo Actions runner"] --> Dind["Isolated Docker daemon"]
    Actions --> Forgejo
```

See the [architecture guide](https://sunwood-ai-labs.github.io/NyankoFace/guide/architecture) for routing, storage, and trust boundaries.

### Markdown and Mermaid diagrams

Repository READMEs and Knowledge articles render fenced Mermaid blocks as real
diagrams. Flowchart, sequence, state, class, and pie diagrams are verified in
all three NyankoFace themes at desktop and 390 px mobile widths. Diagrams fit the
available width by default; the **Zoom** control switches to a detailed,
horizontally scrollable view. Invalid Mermaid remains readable as source with a
localized fallback instead of breaking the page.

| Standard desktop | Cyberpunk mobile |
|---|---|
| <img src="docs/evidence/markdown-mermaid/2026-07-25/screenshots/standard--desktop--knowledge-article--diagram-2.png" alt="A Mermaid sequence diagram rendered in the Standard NyankoFace theme" height="360"> | <img src="docs/evidence/markdown-mermaid/2026-07-25/screenshots/cyberpunk--mobile--knowledge-article--diagram-2.png" alt="The same Mermaid sequence diagram fitted to the Cyberpunk mobile theme" height="360"> |

The repeatable Playwright audit covers **2 Markdown surfaces × 3 themes × 2
viewports**, plus every diagram and the malformed-source fallback: **57
screenshots, 12/12 cases passing**. See the
[full Mermaid visual evidence](docs/evidence/markdown-mermaid/README.md) or run
`cd visual-tests && npm run audit:mermaid`.

## 🎭 Characters: portable runtime assets

[`/characters`](https://localhost:8443/characters) is a format-aware catalog backed by real Forgejo repositories. The seed imports three public Sunwood AI Labs repositories with their history and assets:

- `lumi-jelly-pngtuber`: PuruPuru upper-body avatar with six frontal states.
- `lumi-jelly-head-motion-pngtuber`: head-only PuruPuru avatar with five directions, 30 states, and a direction-control patch.
- `character-design-images`: eight character sheets and eight independently selectable Codex Pet packages, each with its own manifest, spritesheet, QA evidence, and animated WebP.

NyankoFace reads repository contents rather than trusting labels alone. The directory expands the pet repository into eight distinct cards—Ayano Yukimura, Fuhyo, Hisha, Kakugyo, Kohaku, Maki, Momiji, and Onizuka. PuruPuru cards and detail pages animate the repository's real state PNGs with a two-layer alpha crossfade; detail controls can pause playback and select a direction.

<details>
<summary><strong>Open the full-page mobile Character captures</strong></summary>

| Standard mobile | Cyberpunk mobile |
|---|---|
| <a href="docs/evidence/characters/standard-mobile-directory.png"><img src="docs/evidence/characters/standard-mobile-directory.png" alt="Characters directory in Standard theme on mobile" width="320"></a> | <a href="docs/evidence/characters/cyberpunk-mobile-directory.png"><img src="docs/evidence/characters/cyberpunk-mobile-directory.png" alt="Characters directory in Cyberpunk theme on mobile" width="320"></a> |

</details>

The [Characters verification record](docs/evidence/characters/README.md) contains all representative screenshots and the 24-case format audit, 48-case WCAG theme matrix, and 48-case bilingual audit results.

## 🏛️ Editable organizations

The seed creates four real Forgejo organizations rather than static profile fixtures:

- [`nyankoface`](https://localhost:8443/git/nyankoface) uses a compact aperture mark for the main local AI community.
- [`seraphim-labs`](https://localhost:8443/git/seraphim-labs) is an angel-inspired AI safety collective with its own repositories and visual identity.
- `vault-research` is a private research organization. Its private `internal-knowledge` repository and articles are visible only to organization members.
- `local-makers` is a private community organization used to verify ordinary-user invitations and member-only articles.

NyankoFace keeps `nyankoface-admin`, `aiko-mesh`, `ren-vector`, and `mira-signal` in its Owners team. Seraphim Labs has its own fictional angel-themed team—`aurelia-vale`, `cassian-reed`, `ilyana-noor`, and `lucien-sol`—with distinct high-end anime/game-character avatars. Owners can use **Edit organization** to update the profile, avatar, members, teams, and repository settings; the public profile description is read back from the Forgejo organization API. The complete avatar prompt set is preserved in [docs/evidence/organization/seraphim-avatar-prompts.md](docs/evidence/organization/seraphim-avatar-prompts.md).

`vault-research` contains `security-agent`, `docs-agent`, and `review-agent`; `coding-agent` is intentionally kept outside the organization for negative access testing. The seed checks the organization, repository, and article API as an anonymous visitor, a member, and a non-member on every run. The [member-only Knowledge verification record](docs/evidence/member-only-knowledge/README.md) preserves the production ACL matrix and browser screenshots.

`local-makers` contains the simulated community users `haruka-sato` (write) and `nana-kurose` (read). `takumi-endo` and `rio-kanda` are explicitly removed from every organization team. The seed verifies the private organization, `member-notes` repository, and its article for all four identities plus anonymous access. See the [community-user verification record](docs/evidence/community-users/README.md).

| NyankoFace | Seraphim Labs |
|---|---|
| <a href="docs/images/nyankoface-organization-mobile.png"><img src="docs/images/nyankoface-organization-mobile.png" alt="NyankoFace organization page with the compact aperture logo" height="360"></a> | <a href="docs/images/seraphim-labs-organization-mobile.png"><img src="docs/images/seraphim-labs-organization-mobile.png" alt="Seraphim Labs organization page with the halo and wing logo" height="360"></a> |

| Team page | Generated character portraits |
|---|---|
| <a href="docs/images/seraphim-labs-team-mobile.png"><img src="docs/images/seraphim-labs-team-mobile.png" alt="Seraphim Labs team with four distinct fictional angel character avatars" height="360"></a> | <a href="docs/images/seraphim-angel-team-portraits.png"><img src="docs/images/seraphim-angel-team-portraits.png" alt="Aurelia Vale, Cassian Reed, Ilyana Noor, and Lucien Sol character portraits with halos and white wings" height="360"></a> |

<details>
<summary><strong>Open the full Owner settings capture</strong></summary>

<a href="docs/images/seraphim-labs-owner-settings-mobile.png"><img src="docs/images/seraphim-labs-owner-settings-mobile.png" alt="Editable Seraphim Labs organization settings" width="320"></a>

</details>

## 🗂️ Repository types, topics, and tags

NyankoFace chooses the catalog from a **Forgejo topic**:

| Topic | Catalog |
|---|---|
| `model` | Models |
| `dataset` | Datasets |
| `space` | Spaces |
| `skill` | Skills |
| `mcp` | MCPs |
| `prompt` | Prompts |
| `automation` | Automations |
| `doc` | Docs |
| `character` | Characters |
| `benchmark` | Benchmarks |

Topics classify the repository itself. README frontmatter `tags` add multiple content labels such as `audio`, `gradio`, or `classification`; they do not replace the type topic.

Pages does not use a type topic. A public repository gets a Pages surface when
it contains root `index.html` on `gh-pages`, or `docs/index.html` on its default
branch.

## ⏱️ Publishing a portable Automation

Use one public repository per Automation and add the `automation` topic. Keep
`README.md`, `automation.toml`, `automation.example.toml`, and `LICENSE` at the
root. `automation.toml` declares schema version, semantic version, schedule,
timezone, permissions, connectors, workspace scope, delivery, tested clients,
tags, license, and `enabled = false`. Pair each release such as `1.0.0` with an
immutable Git tag such as `v1.0.0`.

Store only secret names and placeholders—never tokens, email addresses, private
URLs, hostnames, thread IDs, or machine-specific paths. Opening
[`/automations`](https://localhost:8443/automations) or an Automation detail
page does not register or execute anything. NyankoFace resolves the selected ref
to a commit SHA, displays compatibility and safety findings, and allows copying
or downloading only a normalized manifest that remains disabled. The
[NyankoFace Navigator](skills/nyankoface-navigator/SKILL.md) includes the complete
four-file starter and validates the repository contract before publication.

## 📚 Git-backed knowledge publishing

The internal [`/docs`](https://localhost:8443/docs) category is a repository-backed publication library, separate from the VitePress operator manual. One person or team owns one repository. Add the `doc` repository topic and store every Markdown publication in `articles/`. All publications are articles; reusable `topics` such as `news`, `how-to`, `reference`, `benchmark`, and `research` provide composable classification without splitting content across directories or document types.

The seed publication contains 31 useful sample entries. Each entry supports `title`, `description`, `emoji`, `topics`, `published`, and `updated` front matter, plus automatic reading-time calculation. `emoji` becomes both the article marker and its faint card watermark; when it is omitted, NyankoFace chooses a stable topic-aware fallback. Each knowledge page records real browser views; readers can switch between latest and view-ranked trends or browse reusable tags.

Four non-admin community accounts—`haruka-sato`, `takumi-endo`, `nana-kurose`, and `rio-kanda`—each own a public `knowledge` repository and publish with their own protected token. Their articles use the `community-authored` topic rather than the maintenance agents' `agent-authored` topic. Repository ownership and latest-commit attribution are checked during every seed run.

| Community-authored directory | Example user article |
|---|---|
| <a href="docs/evidence/community-users/community-authored-list.png"><img src="docs/evidence/community-users/community-authored-list.png" alt="Four community-authored Knowledge cards owned by ordinary user accounts" width="460"></a> | <a href="docs/evidence/community-users/haruka-article.png"><img src="docs/evidence/community-users/haruka-article.png" alt="Haruka Sato personal GPU learning-log article" width="460"></a> |

<details>
<summary><strong>Open the complete Standard and Cyberpunk Knowledge directories</strong></summary>

| NyankoFace Standard | NyankoFace Cyberpunk |
|---|---|
| <a href="docs/evidence/knowledge-library/2026-07-24/screenshots/standard--light--mobile--docs.png"><img src="docs/evidence/knowledge-library/2026-07-24/screenshots/standard--light--mobile--docs.png" alt="NyankoFace tagged articles, trends, and topics in the Standard theme" width="320"></a> | <a href="docs/evidence/knowledge-library/2026-07-24/screenshots/cyberpunk--dark--mobile--docs.png"><img src="docs/evidence/knowledge-library/2026-07-24/screenshots/cyberpunk--dark--mobile--docs.png" alt="NyankoFace knowledge library in the Cyberpunk theme" width="320"></a> |

</details>

The [knowledge-library verification](docs/evidence/knowledge-library/README.md) includes article-detail captures and the complete theme matrix across all three platform themes, light/dark OS schemes, mobile/desktop viewports, horizontal-overflow checks, and computed WCAG text contrast.

```yaml
---
title: Local audio utility
emoji: "🎧"
sdk: docker
license: mit
tags:
  - audio
  - utility
---
```

The detail view reads the repository's actual `README.md`, including relative images stored in Forgejo.

## 🚀 Docker Spaces

Add the `space` topic and a root `Dockerfile`. The application container must listen on port `7860`. Seeded examples cover:

- Gradio
- static HTML
- React and Vue
- Next.js
- Streamlit
- FastAPI
- Node.js

Stopped public Spaces show **On demand** and any visitor can start and use them without signing in. Stop, environment-variable, and settings controls remain restricted to signed-in maintainers with write permission. The runner clones the repository, builds the image, starts the container, and proxies it under `/run/OWNER/REPOSITORY/`.

![NyankoFace Spaces directory with running CPU applications](docs/images/nyankoface-spaces.png)

![A React Space embedded in an NyankoFace repository page](docs/images/nyankoface-space-app.png)

Capacity controls:

- `MAX_RUNNING_SPACES=24` limits simultaneous containers.
- Starting a Space at capacity stops the least recently accessed one.
- `IDLE_TIMEOUT_MINUTES=0` disables time-based automatic stopping.
- README metadata is cached and card metrics are fetched in batches for paginated directories.

Read the full [Spaces guide](https://sunwood-ai-labs.github.io/NyankoFace/guide/spaces).

## 🌐 NyankoFace Pages

Public repositories can expose static sites at:

```text
https://HOST/pages/OWNER/REPOSITORY/
```

The source priority is:

1. the root of `gh-pages`;
2. the default branch's `docs/` directory when `gh-pages` is absent.

The initial seed includes a one-file page, an HTML/CSS/JavaScript portfolio, a multi-page `docs/` fallback, and a VitePress project published by Forgejo Actions.

| Repository Pages card | Live seeded site |
|---|---|
| ![Repository Pages card](docs/evidence/pages/repository-pages-card.png) | ![NyankoFace Pages starter](docs/evidence/pages/pages-starter-live.png) |

Follow the canonical [NyankoFace Pages publishing workflow](https://sunwood-ai-labs.github.io/NyankoFace/guide/pages) for the source decision, minimal HTML, VitePress/Forgejo Actions deployment, live verification, updates, removal, security, and troubleshooting. The [browser verification record](docs/evidence/pages/README.md) contains the tested examples.

## 💬 Community and Issues

Every repository keeps Forgejo-backed Issues and Pull Requests behind the NyankoFace **Community** tab. The initial seed adds real discussion records to the QR Code Generator Space so list, detail, filtering, and authenticated creation routes can be verified after a fresh rebuild. The sample discussion is conducted by three persistent virtual-agent accounts—Luna Scout, Patch Orbit, and Mikan Reviewer—whose research, implementation, and review replies are idempotently recreated without duplicate comments. A dedicated fourth thread verifies blockquotes, lists, task items, code fences, tables, links, mentions, and disclosures as a natural review conversation.

| Discussion list | Discussion detail |
|---|---|
| ![NyankoFace Community list](docs/evidence/community-ui/issues-list-desktop.png) | ![NyankoFace Community detail](docs/evidence/community-ui/issue-detail-desktop.png) |

Desktop and mobile evidence, route checks, and responsive results are recorded in the [Community / Issue verification](docs/evidence/community-ui/README.md).

## 🧠 Skills, MCPs, and versioned Prompts

The seed imports pinned public repositories rather than label-only fixtures. Skill entries contain `SKILL.md`; MCP entries contain an implementation and dependency definition. Source selection and verification are recorded in [docs/research/skill-mcp-sources.md](docs/research/skill-mcp-sources.md).

### Publishing and maintaining a Skill

The installable NyankoFace Navigator Skill is included at [`skills/nyankoface-navigator/`](skills/nyankoface-navigator/). It is the agent-facing source of truth for choosing, scaffolding, validating, publishing, live-checking, and troubleshooting NyankoFace repository contracts and deployment settings. Copy that directory into the Skill location used by Codex or another compatible agent, then invoke `$nyankoface-navigator`. Its validator can also be run directly:

```bash
python skills/nyankoface-navigator/scripts/validate_repo.py PATH --goal space --topics space
python skills/nyankoface-navigator/scripts/validate_repo.py PATH --goal knowledge --topics doc --json
```

#### Bundled installable Skills

| Skill | Use it when | Invocation | Important files |
|---|---|---|---|
| [NyankoFace Navigator](skills/nyankoface-navigator/SKILL.md) | Choose among every NyankoFace publishing surface, create the minimum contract, validate an existing repository, configure deployment/maintenance/GPU settings, or diagnose why content is not discovered or rendered. | `$nyankoface-navigator` | [`SKILL.md`](skills/nyankoface-navigator/SKILL.md), [publishing map](skills/nyankoface-navigator/references/publishing-map.md), [deployment environment](skills/nyankoface-navigator/references/deployment-environment.md), [validator](skills/nyankoface-navigator/scripts/validate_repo.py), [validator tests](skills/nyankoface-navigator/scripts/test_validate_repo.py), and [starter assets](skills/nyankoface-navigator/assets/) |

The repository currently bundles one installable agent Skill. The catalog can
display many seeded or user-published Skills, but those catalog entries are not
silently installed on the host. Copy only the Skill directory you intend to
trust and use.

The Navigator covers the repository-backed publishing surfaces that NyankoFace exposes:

| Goal | What the Skill prepares | NyankoFace destination |
|---|---|---|
| `model` | Model card plus weights/configuration or retrieval instructions | Models |
| `dataset` | Dataset card plus real data/splits or retrieval instructions | Datasets |
| `space` | Dockerfile-based web application | Spaces |
| `space` | README `external_url` for a direct HTTP/HTTPS destination | Spaces |
| `knowledge` | Top-level `articles/*.md` with composable topics | Knowledge |
| `skill` | Agent instructions with `SKILL.md` | Skills |
| `mcp` | MCP server implementation and dependency definition | MCPs |
| `prompt` | Stable repository slug plus version topics and Git tags | Prompts |
| `automation` | Disabled manifest, safe example, README, license, and SemVer tag | Automations |
| `character` | PuruPuru, Codex Pet, or character-sheet file contract | Characters |
| `benchmark` | Evaluation task, runner/configuration, and result evidence | Benchmarks |
| `pages` | Public `gh-pages` root or default-branch `docs/` | Pages |

The bundled directory is intentionally self-contained: [`SKILL.md`](skills/nyankoface-navigator/SKILL.md) defines the workflow, [`references/publishing-map.md`](skills/nyankoface-navigator/references/publishing-map.md) maps all eleven goals to their real discovery contracts, [`references/deployment-environment.md`](skills/nyankoface-navigator/references/deployment-environment.md) defines public-safe defaults and secret-handling boundaries, [`scripts/validate_repo.py`](skills/nyankoface-navigator/scripts/validate_repo.py) performs human- or JSON-readable checks, and [`assets/`](skills/nyankoface-navigator/assets/) contains minimal Knowledge, Pages, Docker Space, external-link Space, and four-file Automation starters. The seeded Forgejo copy uses the same files, so the Skill shown in NyankoFace and the installable copy cannot silently diverge.

1. Create a normal Forgejo repository and add the `skill` topic.
2. Put the complete instructions in the root `SKILL.md`; keep referenced scripts, templates, and assets in the same repository.
3. Add an optional root `skill.json` only when the Skill has evidence-backed `required` or `recommended` relationships.
4. Push through the normal Git/PR workflow. NyankoFace reads the repository files and history directly—there is no separate Skill database or upload format.
5. Open `/skills`, select the card, and verify the rendered `SKILL.md`, Files tab, commit history, dependencies, and reverse **Referenced by** links.

The reproducible seed catalog lives in [`seed/catalog/sunwood-ai-labs.json`](seed/catalog/sunwood-ai-labs.json). Each entry pins a public source repository and branch, so another environment can rebuild the same sample catalog without copying generated cards. To add a bundled sample, add a `kind: "skill"` entry there; user-created Skills only need the repository topic and do not need to be added to the seed catalog.

CI verifies that the installable Navigator and its seeded Forgejo copy stay
identical, validates `SKILL.md` frontmatter, runs the validator's
eleven-contract regression suite, and validates the Navigator repository itself
as a Skill.

Skill repositories can also declare typed Skill-to-Skill relationships in an editable `skill.json`. NyankoFace shows required/recommended dependencies, derives reverse **Referenced by** links, and marks Skills without declarations as **Standalone**. See the [relationship metadata schema and editing guide](docs/skill-relationships.md).

| Skills | MCPs |
|---|---|
| ![Skills directory](docs/evidence/skills-mcps/skills-directory.png) | ![MCP directory](docs/evidence/skills-mcps/mcps-directory.png) |

![Skill workflow-link counts](docs/evidence/skill-relationships/skills-desktop.png)

<details>
<summary><strong>Open the full-height evidence-backed relationship sidebar</strong></summary>

<a href="docs/evidence/skill-relationships/graph-desktop.png"><img src="docs/evidence/skill-relationships/graph-desktop.png" alt="Skill relationship sidebar" width="720"></a>

</details>

The [screenshot-backed relationship verification](docs/evidence/skill-relationships/README.md) also covers mobile layouts, link navigation, and repositories without a `README.md`.

Prompts use a stable repository slug. Versions are represented by `version-v*` topics and matching immutable Git tags. The detail page can switch among existing tags, and `?revision=v4.2` creates a directly shareable revision URL.

| Prompt v4.1 | Prompt v4.2 |
|---|---|
| ![Prompt revision v4.1](docs/evidence/prompts/prompt-revision-v4-1.png) | ![Prompt revision v4.2](docs/evidence/prompts/prompt-revision-v4-2.png) |

## 🎨 Themes and browser evidence

### 日本語／英語UI

ヘッダーのコンパクトな言語切替で、日本語と英語を選択できます。選択はページ移動・再読み込み後も保持されます。グローバルナビゲーションは両言語とも `Models / Datasets / Spaces / Knowledge / Benchmarks / Characters / Skills / MCPs / Prompts` に統一しています。主要12画面を両言語・PC／スマートフォンで撮影する監査は **48 / 48 成功**しています。実際の切替操作とスクリーンショットは[日本語／英語UI検証](docs/evidence/i18n/README.md)に記録しています。

The theme selector stores Standard, Solarpunk, or Cyberpunk in `localStorage` and restores it before the first visible render.

| Standard | Solarpunk | Cyberpunk |
|---|---|---|
| ![Standard theme](docs/evidence/themes/standard-home.png) | ![Solarpunk theme](docs/evidence/themes/solarpunk-home.png) | ![Cyberpunk theme](docs/evidence/themes/cyberpunk-home.png) |

Additional screenshot-backed QA lives under [`docs/evidence/`](docs/evidence/): community UI, enterprise access, Pages, Prompts, scalability, Skills/MCPs, sorting, and themes.

## 🤖 Agent metrics API

NyankoFace creates demo agents and stores API keys only at creation time; the database keeps hashes. Agents can record views and likes through authenticated endpoints, while browser views are recorded by the repository detail page. See [spaces-runner/AGENT_API.md](spaces-runner/AGENT_API.md) for endpoint and authentication details.

The metrics API is for NyankoFace automation. It does not grant Forgejo repository permissions or Space control.

## ⚙️ Configuration

Copy `.env.example` to `.env`. Important values include:

| Variable | Default | Purpose |
|---|---|---|
| `APP_NAME` | `NyankoFace` | Shared display name for the portal, Forgejo navbar, and browser titles |
| `PUBLIC_BASE_URL` | `https://localhost:8443` | Canonical gateway URL |
| `NYANKOFACE_PORT` | `8090` | Certificate-free HTTP gateway port |
| `NYANKOFACE_HTTPS_PORT` | `8443` | HTTPS port |
| `DISABLE_REGISTRATION` | `true` | Keep public self-registration closed |
| `MAX_RUNNING_SPACES` | `24` | Maximum simultaneous Space containers |
| `IDLE_TIMEOUT_MINUTES` | `0` | Optional inactivity stop; zero disables it |
| `README_CACHE_TTL_SECONDS` | `300` | Repository card metadata cache |

The Navigator's deployment safety reference covers public-safe defaults and
secret-handling boundaries. Private hostnames, addresses, hardware settings,
and deployment endpoints belong in an access-controlled runbook. Keep real
credentials in untracked local secret files.

Named volumes keep Forgejo data, shared control tokens, agent metrics, and Actions runner state. `docker compose down` preserves them. Add `--volumes` only when permanent deletion is intentional.

## 🔐 Security boundary

NyankoFace is designed for trusted local or private-network collaboration. It is **not** a hardened multi-tenant sandbox.

The Space runner mounts `/var/run/docker.sock`; a malicious Dockerfile can control the Docker host. Keep repository creation restricted, review every runnable Space, leave registration disabled, replace the bootstrap password, and avoid exposing a default deployment to the public internet.

Read [SECURITY.md](SECURITY.md) and the [operations guide](https://sunwood-ai-labs.github.io/NyankoFace/guide/operations) before shared deployment.

## 🧪 Development and verification

The [change-delivery guide](docs/guide/change-delivery.md) records the measured
PR #80 postmortem and the scope, review-wave, CI, and exact-head merge gates
that prevent a repeat.

Validate Compose without changing runtime state:

```bash
docker compose config
```

Build the frontend:

```bash
cd frontend
npm ci
npm run build
```

Build the documentation:

```bash
cd docs
npm ci
npm run docs:build
```

The repository CI performs these structural checks and Python syntax compilation. User-facing changes should include browser or screenshot evidence when practical.

### Agent-readable visual QA

Visual QA runs locally against the real Compose stack. It is intentionally not part of GitHub Actions: generated screenshots cannot prove that a layout looks correct unless a person opens and reviews them, while the exhaustive matrix is expensive to build and retain on every push.

CI remains responsible for deterministic build, lint, unit, integration, configuration, and documentation checks. For a user-facing change, run the focused browser audit locally or against the deployed environment, then open the generated PNGs and inspect them before reporting completion.

Run the review:

```bash
npm ci --prefix visual-tests
npm exec --prefix visual-tests -- playwright install chromium
npm run capture --prefix visual-tests
npm run capture:themes --prefix visual-tests
npm run capture:scroll --prefix visual-tests
```

`capture:themes` is the exhaustive theme matrix: **Standard, Solarpunk, and Cyberpunk × light and dark OS color schemes × desktop and mobile × 32 major screens = 384 full-page screenshots**. It calculates rendered text contrast after alpha compositing and enforces WCAG AA (4.5:1 for normal text, 3:1 for large text). The direct Skill repository Files route is included so file names and tree edges cannot hide behind the decorative page grid. `capture:scroll` adds viewport screenshots across the top, middle, and bottom of every page, plus direct checkpoints for Dataset Viewer, Inference Providers, and both organizations' Team members. Both commands accept `VISUAL_QA_THEMES`, `VISUAL_QA_COLOR_SCHEMES`, `VISUAL_QA_VIEWPORTS`, or `VISUAL_QA_ROUTES` filters (comma-separated IDs).

`npm run audit:organization --prefix visual-tests` adds focused desktop/mobile evidence for the organization profile. It fails on exposed mobile side gutters, decorative fake members, member-count mismatches, or unreadable repository focus states.

Open the generated reports and contact sheets, then inspect the images rather than relying on PASS/FAIL alone. The current matrix produces 48 full-page contact sheets; the scroll audit provides additional top, middle, bottom, and direct-section evidence.

The latest committed manual review is the [2026-07-19 exhaustive theme contrast audit](docs/evidence/visual-qa/2026-07-19-theme-contrast-audit.md): **384 / 384 screenshots passed**, **20,196 rendered text nodes** were calculated, and all **48 contact sheets** were visually reviewed across every theme, OS color scheme, viewport, and all 32 routes. The Skill Files page also passed **18 / 18** top, middle, and bottom scroll captures across all themes and both viewports.

| Cyberpunk Dataset Viewer | Cyberpunk Inference Providers | Generated organization identity and team |
|---|---|---|
| <a href="docs/evidence/themes/cyberpunk-dataset-viewer-mobile.png"><img src="docs/evidence/themes/cyberpunk-dataset-viewer-mobile.png" alt="Cyberpunk Dataset Viewer on mobile" height="360"></a> | <a href="docs/evidence/themes/cyberpunk-inference-providers-mobile.png"><img src="docs/evidence/themes/cyberpunk-inference-providers-mobile.png" alt="Cyberpunk Inference Providers on mobile" height="360"></a> | <a href="docs/evidence/themes/cyberpunk-organization-team-mobile.png"><img src="docs/evidence/themes/cyberpunk-organization-team-mobile.png" alt="NyankoFace generated organization identity and team members" height="360"></a> |

See the [visual QA guide](https://sunwood-ai-labs.github.io/NyankoFace/guide/visual-qa) for the agent feedback workflow and focused-capture options.

## Automated Claude Code `/goal` maintenance

```mermaid
flowchart LR
    Issue["Manual or opted-in Issue"] --> Route{"Maintainer classification"}
    Humanless["Scheduled humanless cycle"] --> Specialist["Specialist Claude Code /goal"]
    Release["Release branch push"] --> Parallel["Security and docs audits in parallel"]
    Route -->|Question| Answer["Read-only Japanese answer"]
    Route -->|Change| Specialist
    Specialist --> PR["Implementation PR"]
    Parallel --> PRs["Two release-audit PRs"]
    PR --> Review["Independent exact-SHA review"]
    PRs --> Review
    Review -->|Approved| Merge["glm-maintainer auto-merge"]
    Review -->|Rejected, attempts remain| Retry["Same specialist and PR"]
    Retry --> Review
    Review -->|Exhausted, stale, conflict, or missing evidence| Open["Leave PR open, fail-closed"]
```

The [detailed maintenance guide](docs/guide/automated-maintenance.md) expands
this overview into Issue sequence, parallel release-audit, retry-state, and
loop-safety diagrams. Browser-rendering proof is retained in the
[Mermaid evidence packet](docs/evidence/automated-maintenance/flow-diagrams/README.md).

Point `ZAI_AGENT_CONFIG` in the untracked `.env` file to a protected env file containing `ZAI_API_KEY`, then start `maintenance-agent`. Mention `@glm-maintainer` in a new Issue under the `nyankoface` organization to pass it to Claude Code 2.1.205 as a real `/goal` completion condition. On repositories opted in with the `humanless` or `humanless-issues` topic, `MAINTENANCE_AUTO_ISSUE_ENABLED=true` also accepts ordinary new Issues without a mention. Bugs are fixed through an independently reviewed, SHA-bound, auto-merged PR; review findings and transient execution failures return to the same agent and PR for at most `MAINTENANCE_AUTOMATIC_RETRY_MAX_ATTEMPTS` attempts. Questions and inquiries are investigated read-only and receive a Japanese answer with repository-path evidence; unknown reports default to that non-mutating path instead of speculative edits. Claude Code connects directly to Z.AI's Anthropic-compatible endpoint with `glm-5.2`. Agent prompts, completion summaries, PR bodies, and status replies are written in Japanese. Add the `agent:skip` label or `<!-- nyankoface-maintenance:skip -->` to opt out.

After the PR exists, mention the maintainer again, for example `@glm-maintainer 見出しも日本語にしてください。`. The selected specialist checks out the existing `agent/issue-N` branch, applies and verifies the additional instruction, pushes another commit to the same PR, and replies in Japanese. Ordinary comments, bare `/goal`, and direct specialist mentions do not run the agent. The trigger works on the source Issue and on its agent-created PR.

`glm-maintainer` automatically delegates implementation to `@designer-agent`, `@coding-agent`, or `@docs-agent`. The delegation is a real, visible conversation step: the maintainer first posts `@specialist 次の作業を担当してください`, and only then is that specialist's worker submitted. Users always address the maintainer; direct specialist mentions neither start a run nor override its routing. After the implementation PR and evidence are published, the maintainer visibly mentions the separate `@review-agent`. That account runs a read-only, SHA-bound `/goal` review and must independently approve the requirements, diff, tests, regressions, and security before merge. Each agent has its own Forgejo identity, avatar, least-privilege token, role contract, reactions, and comments; `/api/agents` and `/api/jobs` expose the available personas and current assignment.

### Humanless development and maintenance

Set `MAINTENANCE_HUMANLESS_ENABLED=true` and add the `humanless` topic to an opted-in repository. No human-authored Issue or mention is required after that point. The scheduler creates the initial product-development Issue from the repository description, README, and existing files, delegates implementation, requires independent SHA-bound review, and lets `glm-maintainer` merge only the approved head. Repositories with a UI can add `humanless-ui` to require real mobile and desktop browser evidence in both implementation and review.

After the bootstrap merge, PostgreSQL schedules recurring maintenance cycles. The specialist rotation covers design, security, documentation, and coding; each specialist inspects the current product and autonomously completes one highest-value improvement. A rejected review is fed back into the same PR automatically for up to `MAINTENANCE_HUMANLESS_MAX_ATTEMPTS`. Active workers renew a database lease; an interrupted service is detected from the missing heartbeat and recovered by the same specialist. If implementation was already published, recovery rediscovers the newest open `agent/humanless-*` PR from Forgejo and resumes at independent review instead of opening duplicate Issues and PRs. A rejected recovery review returns to implementation on that same branch. Failed, stale, or conflicting work still fails closed instead of being reported as complete. Add `humanless-paused` to suspend a repository without deleting its history. Current state is available from `/api/humanless/cycles`.

The production run, duplicate-cycle regression, independent review rejection,
Docker verification, and public desktop/mobile screenshots are preserved in
[`docs/evidence/automated-maintenance/humanless-autopilot`](docs/evidence/automated-maintenance/humanless-autopilot).

Pushing a branch named `release`, `release-*`, or `release/*` under the configured Forgejo organization activates two additional release gates. `security-agent` audits the complete default-branch-to-release diff for authorization, validation, secrets, dependencies, CI/container boundaries, and supply-chain risk. In parallel, `docs-agent` checks README/VitePress coverage, configuration examples, migration and reconstruction steps, links, and commands; it also derives the version from the branch and generates diff-backed `RELEASE_NOTES.md` plus the versioned release page in every existing docs locale. Release claims must point to inspected files or executed checks rather than commit subjects alone. Each agent receives an isolated clone and deterministic `agent/release-...` branch, records an audit artifact under `docs/release-audits/`, and opens its own PR with the pushed release branch as base. The tuple repository + release branch + pushed SHA + agent is deduplicated in PostgreSQL. When review rejects a result, the same agent updates the existing PR, bounded by `MAINTENANCE_AUTOMATIC_RETRY_MAX_ATTEMPTS`. When the separate `review-agent` approves the exact current head SHA with no findings, `glm-maintainer` merges that release-audit PR; exhausted, stale, conflicting, or incomplete reviews remain open. Audit state is exposed by `/api/releases/audits`.

| Security release-audit PR | Documentation release-audit PR |
|---|---|
| <a href="docs/evidence/release-audits/security-pr-mobile.png"><img src="docs/evidence/release-audits/security-pr-mobile.png" alt="Security agent release-audit PR on mobile" height="420"></a> | <a href="docs/evidence/release-audits/docs-pr-mobile.png"><img src="docs/evidence/release-audits/docs-pr-mobile.png" alt="Documentation agent release-audit PR on mobile" height="420"></a> |

| Coordinator | Design | Coding | Documentation | Security | Review |
|---|---|---|---|---|---|
| <img src="seed/assets/agent-avatars/glm-maintainer.png" alt="GLM Maintainer avatar" width="96"> | <img src="seed/assets/agent-avatars/designer-agent.png" alt="NyankoFace Designer avatar" width="96"> | <img src="seed/assets/agent-avatars/coding-agent.png" alt="NyankoFace Coding avatar" width="96"> | <img src="seed/assets/agent-avatars/docs-agent.png" alt="NyankoFace Docs avatar" width="96"> | <img src="seed/assets/agent-avatars/security-agent.png" alt="NyankoFace Security avatar" width="96"> | <img src="seed/assets/agent-avatars/review-agent.png" alt="NyankoFace Review avatar" width="96"> |
| `glm-maintainer` | `designer-agent` | `coding-agent` | `docs-agent` | `security-agent` | `review-agent` |

The retained [independent-account sample Issue #20](https://example.invalid/git/nyankoface/pages-starter/issues/20) contains a separate comment from every account. The screenshot below verifies the rendered discussion; the individual profile captures in [`docs/evidence/agents`](docs/evidence/agents) verify that Forgejo serves five distinct generated avatars without the former shared-avatar override.

The live hand-off is retained as [Issue #21](https://example.invalid/git/nyankoface/pages-starter/issues/21) → [PR #22](https://example.invalid/git/nyankoface/pages-starter/pulls/22). It proves the ordered sequence `glm-maintainer mention → docs-agent reaction/work → docs-agent completion comment`.

| Independent specialist accounts | Maintainer-to-specialist hand-off |
|---|---|
| <a href="docs/evidence/agents/specialist-agent-identities.png"><img src="docs/evidence/agents/specialist-agent-identities.png" alt="Independent specialist-agent accounts in one retained Issue" height="420"></a> | <a href="docs/evidence/agents/maintainer-delegates-specialist-complete.png"><img src="docs/evidence/agents/maintainer-delegates-specialist-complete.png" alt="GLM Maintainer mentions a specialist before the specialist starts and replies" height="420"></a> |

Issue reactions provide a compact progress signal: 👍 records human support, 👀 means `glm-maintainer` accepted and is processing the request, 🚀 means the verified PR or follow-up commit was published, and 😕 marks a stopped or failed run that needs log inspection.

The service validates the Forgejo HMAC signature and deduplicates deliveries in PostgreSQL. Claude Code runs as an unprivileged user inside the maintenance container: it has no host Docker socket and cannot read the Forgejo bot token, while retaining normal repository-level tools and test execution. The root wrapper alone commits and pushes after `git diff --check`. It never merges on the implementer's self-assessment. The independent reviewer must return a schema-valid approval for the exact current PR head SHA; failed requirements, any finding, missing reviewer evidence, a changed head, merge conflict, or rejected merge fails closed. With `MAINTENANCE_AUTO_MERGE=true`, the wrapper sends that approved SHA as Forgejo's `head_commit_id` and deletes the source branch only after merge succeeds. Set the variable to `false` to keep approved PRs for human merge. See [Automated Claude Code maintenance](https://sunwood-ai-labs.github.io/NyankoFace/guide/automated-maintenance).

UI and application changes have two evidence gates. First, the implementer must run the real app, list the interactions and browser checks it performed, and attach real mobile (≤480px) and desktop (≥1024px) PNG screenshots. Then `review-agent` independently starts the reviewed SHA, repeats the interaction and viewport checks, and attaches its own captures and requirement/test tables. The wrapper validates PNG signatures and actual dimensions for both accounts. Missing viewport coverage, failed checks, console/page errors reported as failures, or a reviewer finding prevents merge. Chromium, Japanese CJK fonts, and color emoji are included in the maintenance image so the captured Japanese UI remains readable.

[ClearNext Issue #22](https://example.invalid/git/nyankoface/clear-next/issues/22) → [PR #23](https://example.invalid/git/nyankoface/clear-next/pulls/23) is the retained end-to-end proof. A human mentioned only `@glm-maintainer`; the maintainer delegated to `@designer-agent`; the specialist added a real disclosure interaction, reported 18 UI checks, attached four screenshots, and the wrapper auto-merged commit `22430240`. The images below are browser captures of the rendered Forgejo comment and its opened mobile attachment—not copied build artifacts.

| Rendered UI-test report and auto-merge status | Opened mobile UI attachment with readable Japanese |
|---|---|
| ![Designer completion comment with UI test table](docs/evidence/automated-maintenance/issue-22-completion-comment.png) | ![ClearNext opened privacy disclosure on mobile](docs/evidence/automated-maintenance/issue-22-mobile-opened.png) |

[Pages starter Issue #25](https://example.invalid/git/nyankoface/pages-starter/issues/25) → [PR #26](https://example.invalid/git/nyankoface/pages-starter/pulls/26) is the retained proof for the independent review gate itself. The maintainer handed the implementation to a specialist, explicitly mentioned `@review-agent`, and withheld merge until that separate account approved the exact head SHA `b55a7369cdee3d49b5ffcc5c74bd6a46882018a8`. The reviewer independently reran the app, passed all 10 requirements and 9 checks, attached eight mobile/desktop screenshots, and returned no findings. Only then did `glm-maintainer` server-side merge commit `b64e42021f03f4110614c7cd2f9fd3b27a6b254a`.

| Maintainer hand-off | Independent SHA-bound approval | Auto-merged PR |
|---|---|---|
| ![Maintainer explicitly assigns review-agent and blocks merge](docs/evidence/automated-maintenance/issue-25-review-handoff.png) | ![Review-agent approval with traceability table](docs/evidence/automated-maintenance/issue-25-review-approved.png) | ![Forgejo PR merged by glm-maintainer](docs/evidence/automated-maintenance/issue-25-auto-merged.png) |

## 📖 Documentation

The public docs use one article model: every Markdown publication lives under `articles/`, while composable topics distinguish news, how-to material, reference information, benchmarks, research, and other themes. Every page exposes reading time, topics, and related knowledge in both English and Japanese.

| Editorial home | Knowledge atlas node |
|---|---|
| ![NyankoFace editorial field manual](docs/evidence/docs-atlas/home-en-desktop.png) | ![NyankoFace platform map knowledge node](docs/evidence/docs-atlas/wiki-platform-map.png) |

| Dark theme | Japanese mobile article |
|---|---|
| ![NyankoFace field manual in dark mode](docs/evidence/docs-atlas/home-en-dark.png) | <a href="docs/evidence/docs-atlas/article-ja-mobile.png"><img src="docs/evidence/docs-atlas/article-ja-mobile.png" alt="Japanese NyankoFace field note on mobile" height="360"></a> |

The [editorial knowledge atlas verification record](docs/evidence/docs-atlas/README.md) includes responsive metrics, interaction checks, and additional mobile screenshots. The complete [repository polish verification record](docs/repository-polish/index.md) also includes the post-upgrade NyankoFace home, Spaces directory, and immutable Prompt revision screenshots.

- [English documentation](https://sunwood-ai-labs.github.io/NyankoFace/)
- [日本語ドキュメント](https://sunwood-ai-labs.github.io/NyankoFace/ja/)
- [Field notes](https://sunwood-ai-labs.github.io/NyankoFace/articles/)
- [Knowledge atlas](https://sunwood-ai-labs.github.io/NyankoFace/wiki/)
- [Japanese README](README.ja.md)
- [Contributing](CONTRIBUTING.md)
- [Support](SUPPORT.md)
- [Security policy](SECURITY.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)

## 📄 License

NyankoFace-specific code and documentation are released under the [MIT License](LICENSE). Forgejo, fonts, package dependencies, base images, and seeded public repositories retain their own licenses. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
