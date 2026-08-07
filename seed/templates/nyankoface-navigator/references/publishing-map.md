# NyankoFace publishing map

## Contract table

| Goal | Catalog topic | Minimum repository contract | Public destination |
|---|---|---|---|
| `model` | `model` | `README.md`; describe weights/configuration and usage | `/models` → `/OWNER/REPO` |
| `dataset` | `dataset` | `README.md`; include real data, splits, or retrieval instructions | `/datasets` → `/OWNER/REPO` |
| `space` | `space` | Root `Dockerfile` listening on `0.0.0.0:7860`, or README `external_url` using HTTP/HTTPS | `/spaces` → `/OWNER/REPO` |
| `knowledge` | `doc` | Markdown under `articles/`; frontmatter `title` and composable `topics` or `tags` | `/docs` → `/docs/OWNER/SLUG` |
| `skill` | `skill` | Root `SKILL.md` with `name` and `description` frontmatter | `/skills` → `/OWNER/REPO` |
| `mcp` | `mcp` | `README.md`, dependency manifest, and runnable server entrypoint | `/mcps` → `/OWNER/REPO` |
| `prompt` | `prompt` | Root `PROMPT.md`; matching `version-v*` topic and immutable `v*` Git tag | `/prompts` → `/OWNER/REPO?revision=TAG` |
| `character` | `character` | One detected PuruPuru, Codex Pet, or character-sheet contract | `/characters` → `/OWNER/REPO` |
| `benchmark` | `benchmark` | `README.md` plus a reproducible runner/configuration; keep result evidence | `/benchmarks` → `/OWNER/REPO` |
| `automation` | `automation` | `README.md`, `automation.toml`, `automation.example.toml`, `LICENSE`, and immutable `v*` tag | `/automations` → `/OWNER/REPO` |
| `pages` | none | Public repository with root `index.html` on `gh-pages`, or `docs/index.html` on the default branch | `/pages/OWNER/REPO/` |

## Classification rules

- A Forgejo repository topic selects the catalog. README tags do not.
- Tags/topics in README or Knowledge frontmatter are multi-valued labels such as
  `audio`, `gradio`, `news`, `how-to`, `reference`, `svg`, or `cad`.
- Pages is an additional publishing surface, not a catalog topic. Any public
  repository can expose Pages when it has a supported source.
- When several type topics exist, avoid relying on frontend precedence. Keep one
  primary type topic unless the platform documentation explicitly requires more.
- A repository can contain multiple Knowledge articles, all under `articles/`.

## Type-specific guidance

### Model and Dataset

Write the card and usage contract in `README.md`. Store large weights and datasets
with Git LFS. Include licenses and provenance. A README-only repository is valid
for catalog discovery but should warn until its real assets or retrieval steps are
present.

### Space

Use README frontmatter for presentation metadata:

```yaml
---
title: Local audio utility
emoji: "🎧"
sdk: docker
tags: [audio, utility]
---
```

For a container Space, bind `0.0.0.0:7860`. Any CPU-capable framework is allowed
when its Dockerfile satisfies that contract. GPU execution additionally requires
the `gpu` topic and an enrolled worker; read the deployment environment reference.

For a link-type Space, omit the container requirement and declare:

```yaml
---
title: Product documentation
emoji: "🧭"
external_url: https://docs.example.com/
---
```

Only absolute HTTP and HTTPS URLs are valid.

### Knowledge

All publications are articles. Use composable topics instead of separate
`procedures/` or `wiki/` directories:

```yaml
---
title: 記事タイトル
description: 一覧に表示する短い説明
emoji: "🧭"
topics: [how-to, forgejo]
published: true
updated: 2026-07-29
---
```

The current reader uses `topics` and `tags`; it does not require `formats`.

### Skill, MCP, and Prompt

Keep a Skill's complete instructions in root `SKILL.md`. Use optional `skill.json`
only for evidence-backed required or recommended Skill relationships.

An MCP repository needs implementation and dependency files, not only a label.
Document its transport, start command, configuration, and exposed tools.

Keep Prompt repository names revision-neutral. For every revision, pair a topic
such as `version-v4.2` with the immutable Git tag `v4.2`.

### Character

NyankoFace recognizes any of these real file contracts:

- PuruPuru: `avatar/default-settings.json` plus expression PNGs in `avatar/`;
- Codex Pet: paired `pet.json` and `spritesheet.webp`, at the root or below
  `assets/pets/`;
- character sheets: `metadata/characters.csv` plus exported character assets.

Use additional topics such as `purupuru`, `codex-pet`, `character-sheet`, or
`head-motion` for filtering, but keep `character` as the type topic.

### Benchmark

Document the task, input/output format, metric, baseline, environment, license,
and exact execution command. Include a runner or dependency configuration and
retain result evidence. Use extra topics such as `svg`, `cad`, `vision`, or
`llm-evaluation` to classify the suite.

### Automation

Use one repository per Automation. Keep the public contract at the repository
root and publish only a disabled configuration:

```toml
schema_version = 1
name = "Weekly repository report"
description = "Summarize repository activity without changing files."
platform = "codex"
format = "automation"
version = "1.0.0"
schedule_type = "weekly"
timezone = "Asia/Tokyo"
trigger = "Every Monday at 09:00"
required_permissions = ["repository:read"]
required_connectors = ["github"]
workspace_required = false
delivery_type = "none"
tested_on = ["Codex Desktop"]
tags = ["report", "repository"]
license = "MIT"
enabled = false
required_secrets = ["GITHUB_TOKEN"]
```

Pair version `1.0.0` with immutable Git tag `v1.0.0`. Store only secret names,
workspace placeholders, and parameter placeholders—not tokens, email addresses,
private URLs, machine paths, thread IDs, or hostnames. Browsing never executes
or registers an Automation. NyankoFace resolves the selected ref to a commit SHA,
shows permissions, connectors, schedule, workspace, delivery, compatibility,
and findings, then offers a normalized download that remains `enabled = false`.

### Pages

The repository must be public. NyankoFace prefers the root of `gh-pages`; only when
that branch is absent does it serve `docs/` from the default branch. Preserve
relative assets and declare `<title>`, Open Graph, and Twitter metadata for
predictable link previews. Follow the complete scaffold, build, publish, and
live-verification workflow in [pages.md](pages.md).
