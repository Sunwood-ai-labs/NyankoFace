# Skill content relationship audit

Audit date: 2026-07-19

This audit reads the complete root `SKILL.md` from each of the ten public Skill
repositories seeded by NyankoFace. Repository descriptions were not accepted as
dependency evidence. A case-insensitive cross-reference scan found no Skill
explicitly naming another catalog Skill, so the catalog currently declares
**zero hard dependencies**. Four optional workflow links remain because the
actual procedures have adjacent hand-off points; each link stores its section
basis in `skill.json`.

## Content inventory

| Skill | Workflow found in `SKILL.md` | Relationship decision |
| --- | --- | --- |
| `android-termux-ssh-bootstrap-skill` | Windows/ADB setup, GitHub Termux APK selection, OpenSSH installation, key auth, port forwarding, and validation. | Standalone; the previous generic repository-polish link was removed. |
| `cc-orchestrator-cli-skill` | Claude Code team prompting, provider selection, debug-log verification, ownership, and QA reporting. | Standalone; no catalog Skill is referenced or required. |
| `cities-skylines1-agent-skill` | Local bridge setup, state-first inspection, auditable commands, save verification, and repair gotchas. | Standalone; no catalog Skill is referenced or required. |
| `draw-io-skill` | Native XML creation, export, SVG linting, visual verification, repository docs, and diagram QA. | Standalone itself; `repository-polish-skill` can optionally hand documentation visuals to it. |
| `frontend-design-skill` | Design intent, implementation constraints, typography, theme, motion, composition, and production-grade UI execution. | Standalone itself; `repository-polish-skill` can optionally use it for changed user-facing docs surfaces. |
| `gh-release-notes-skill` | Diff/tag evidence, docs truth-sync, release QA inventory, SVG validation, publication, and live verification. | Optional link to Git Flow because its comparison range can follow release/hotfix boundaries. |
| `git-flow-skill` | Branch-model detection, feature/release/hotfix flows, tagging, back-merges, and recovery guardrails. | Standalone; reverse-linked from release notes instead of declaring a circular dependency. |
| `jupytext-skill` | Notebook/Markdown pairing, conversion, sync, format choice, and round-trip validation. | Standalone; the previous generic repository-polish link was removed. |
| `m5stack-arduino-cli-skill` | Windows serial diagnosis, ESP32 package setup, FQBN attachment, compile/upload, samples, and board references. | Standalone; no catalog Skill is referenced or required. |
| `repository-polish-skill` | README/docs/Pages/CI polish, public-facing QA, visual assets, commit/push, release structure, and finish-line verification. | Three optional hand-offs: frontend design, release notes, and draw.io diagrams. |

## Retained workflow links and evidence

| Source → target | Type | Source evidence | Target evidence |
| --- | --- | --- | --- |
| `gh-release-notes-skill` → `git-flow-skill` | Recommended | **Default Workflow §2** resolves the release comparison range. | **Standard Flows / Release and Hotfix** defines branch and tag boundaries. |
| `repository-polish-skill` → `frontend-design-skill` | Recommended | **QA Workflow §3** covers changed user-facing documentation surfaces. | **Design Thinking** covers purpose, constraints, aesthetic direction, and implementation. |
| `repository-polish-skill` → `gh-release-notes-skill` | Recommended | **Close out at the actual finish line** includes publish and release structure. | **Docs Truth-Sync** aligns release claims with README and operator docs. |
| `repository-polish-skill` → `draw-io-skill` | Recommended | **Common Scope** includes reusable visual assets and public-facing polish. | **Default Workflow** requires editable source, export, linting, and visual verification. |

## Rules applied

- No hard dependency is inferred merely because two Skills could be used in the same repository.
- Reverse links are derived by NyankoFace and are not duplicated in metadata.
- Circular recommendations are avoided when one directed hand-off explains the relationship.
- Every future relationship should name the `SKILL.md` section basis in its metadata.
