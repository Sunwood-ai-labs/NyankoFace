---
name: nyankoface-navigator
description: Choose, scaffold, validate, publish, and live-check NyankoFace repositories for Models, Datasets, Docker or external-link Spaces, Knowledge, Skills, MCP servers, versioned Prompts, portable Automations, Characters, Benchmarks, and static Pages. Also use when configuring an NyankoFace deployment, maintenance automation, or LAN GPU worker; diagnosing missing catalog cards, wrong topics, frontmatter, tags, files, branches, URLs, ports, or environment variables; or preparing the smallest repository that NyankoFace can actually discover and render.
---

# NyankoFace Navigator

Treat Forgejo repositories and their Git history as the source of truth. Choose
the smallest valid NyankoFace surface, create only its required files, validate
the repository, and verify the rendered result through the public gateway.

## Workflow

1. Restate the intended outcome in one sentence.
2. Read [references/publishing-map.md](references/publishing-map.md).
3. Select one primary catalog type. Add Pages only when the same public
   repository should also serve a static site. When Pages is selected, read
   [references/pages.md](references/pages.md) before choosing a source.
4. Preserve user-authored files. Copy the closest file from `assets/`, or create
   an equally small equivalent when no asset matches.
5. Run:

   ```bash
   python scripts/validate_repo.py PATH --goal TYPE --topics TOPIC...
   ```

6. Fix every `ERROR`. Explain every remaining `WARN`, then rerun until the result
   is `OK`. Use `--json` when another agent or CI consumes the result.
7. Push the required topic, files, branch, and Git tags to Forgejo.
8. Open the exact public URL from the publishing map and inspect one meaningful
   interaction or nested resource. Do not infer success from a build alone.
9. Report the chosen type, changed files, topics, public URL, and verification
   evidence.

Ask one question only when the intended outcome cannot be inferred:
“読者に見せるページ、実行するアプリ、再利用するデータ／指示のどれですか？”

## Routing rules

- Weights, tokenizer, or inference configuration → **Model**
- Training, evaluation, tabular, image, audio, or text records → **Dataset**
- Docker web application → **Space**
- Existing HTTP/HTTPS application without embedding → **external-link Space**
- Markdown publications in one personal or team repository → **Knowledge**
- Reusable agent procedure rooted at `SKILL.md` → **Skill**
- Callable tool server using Model Context Protocol → **MCP**
- Reusable instruction text with immutable revisions → **Prompt**
- Scheduled or manually triggered portable Codex configuration → **Automation**
- PuruPuru, Codex Pet, or character-sheet package → **Character**
- Reproducible evaluation suite, task set, runner, and results → **Benchmark**
- Static HTML or generated documentation → **Pages**

Repository topics select catalog types. README frontmatter tags/topics add
multi-valued classification and never replace the type topic. Pages is different:
it is detected from a public repository's `gh-pages` branch or
`docs/index.html`; it has no required `pages` topic.

## Configuration

For Compose deployment, public URLs, Space capacity, maintenance automation,
automatic labels, or a LAN GPU worker, read
[references/deployment-environment.md](references/deployment-environment.md)
before changing `.env`, a secret file, or Compose. Never commit credentials,
enrollment tokens, generated secrets, or a populated `.env`.

For API-driven repository, Issue, Space, Secret, Pipeline, metrics, or reaction
management, read [references/api-authentication.md](references/api-authentication.md).
Prefer the unified NyankoFace API when the required v1 route exists; keep Git
clone/push and LFS on Forgejo's native data plane.

For an agent connection to the official NyankoFace platform MCP endpoint, read
[references/mcp-server.md](references/mcp-server.md). This is distinct from
publishing an `mcp` topic repository into the catalog.

## Live verification

- Catalog type: open its directory, find the card, then open `/OWNER/REPO`.
- Knowledge: open `/docs/OWNER/SLUG` and confirm title, topics, Markdown, and a
  nested or relative asset when present.
- Docker Space: confirm `running`, open `/run/OWNER/REPO/`, and exercise one
  application control.
- External-link Space: confirm the card badge and final absolute destination.
- Pages: follow [references/pages.md](references/pages.md); verify the card,
  copied URL, root page, one asset, and one nested page at desktop and mobile
  widths. Use `scripts/verify_pages.py` for the HTTP checks.
- Prompt: select a real Git tag and confirm `?revision=TAG` renders that revision.
- Character: confirm NyankoFace detects at least one real runtime format and opens
  its manifest, settings, spritesheet, or catalog evidence.
- Benchmark: confirm the suite card, reproducibility instructions, and one
  runner/result artifact.
- Automation: confirm the immutable revision, preflight findings, permissions,
  connectors, schedule, delivery, and disabled download. Opening the page must
  not register or execute the Automation.

When topic inspection is unavailable, obtain the actual Forgejo topic list and
pass it with `--topics`. Never claim topic validation, live rendering, or browser
verification succeeded without direct evidence.
