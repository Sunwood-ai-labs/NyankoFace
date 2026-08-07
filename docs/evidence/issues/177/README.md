# NyankoFace brand exploration — Issue #177

Status: design exploration complete; production asset replacement is a separate
approval step. The current canonical cat asset is intentionally unchanged by
this evidence PR.

## Evidence files

- [10-direction comparison board (PNG)](brand-exploration.png) · [SVG source](brand-exploration.svg)
- [shrink and color matrix (PNG)](variant-matrix.png) · [SVG source](variant-matrix.svg)
- [10 standalone candidate SVGs](candidates/01-nyankoface-signal-wordmark.svg), [02](candidates/02-open-eye.svg), [03](candidates/03-neural-horizontal-face.svg), [04](candidates/04-of-brain-line-monogram.svg), [05](candidates/05-open-portal-wordmark.svg), [06](candidates/06-cat-signal.svg), [07](candidates/07-face-aperture.svg), [08](candidates/08-community-wave.svg), [09](candidates/09-black-wordmark-cyan-cut.svg), [10](candidates/10-mark-first-monogram-system.svg)
- [Japanese decision record](README.ja.md)
- Regenerator: `node docs/evidence/issues/177/build-brand-exploration.mjs`

The board uses deterministic SVG primitives, explicit `viewBox` coordinates,
high-contrast ink, cyan, and amber accents, and the same 256-unit mark surface
for every candidate. The matrix compares light, dark, two-color, monochrome,
inverse, and 24/32px reductions. It translates the requested reference
language (minimal icon + wordmark, strong contrast, horizontal motion) without
copying Ideogram's logo, typography, or line pattern.

## Ten candidates

| # | Direction | Strength | Risk | Intended surfaces |
|---|---|---|---|---|
| 01 | NyankoFace Signal Wordmark | Reads as open face plus signal; strong 24px silhouette; clear wordmark extension | Horizontal lines need spacing rules so they do not look like a generic menu | Navbar, wordmark, favicon, social card |
| 02 | Open Eye | Friendly, legible eye aperture and softer community tone | Less distinctive at favicon scale; can read as an eye-only product | Navbar, onboarding, community pages |
| 03 | Neural Horizontal Face | Directly combines face, signal, and local-AI layers | Stacked strokes can lose facial reading when reduced | Favicon, dashboard, loading mark |
| 04 | OF Brain-Line Monogram | Explicit OF monogram with an AI/neural interpretation | Dense right-hand strokes need a compact variant | Wordmark, developer docs, social card |
| 05 | Open Portal Wordmark | Repository and open-boundary metaphor; strong square container | Portal icon is common in developer tooling | Docs, Pages, repository shell |
| 06 | Cat Signal | Preserves continuity with the canonical cat while simplifying it | Keeps a mascot association and limits future neutrality | Navbar, community, migration period |
| 07 | Face Aperture | “Open” becomes a motion system for loading and transitions | Horizontal slits can be mistaken for a menu or equalizer | Loading, favicon, motion accent |
| 08 | Community Wave | Connects people, agents, and repositories without a node cliché | Weakest face/name association at 24px | Community, social card, event material |
| 09 | Black Wordmark + Cyan Cut | Most economical single-color mark; cyan cut preserves NyankoFace color | Abstract mark needs the wordmark beside it during migration | Favicon, monochrome, print, code hosting |
| 10 | Mark-First Monogram System | Designed as a responsive system from compact mark to wordmark | Container can feel app-like rather than community-like | PWA, app icon, responsive header |

## Evaluation and provisional selection

Scores are 1–5, based on the Issue criteria: name/meaning, 24px
recognition, system expansion, continuity, and differentiation. They are a
design review record, not user research or trademark clearance.

| # | Meaning | 24px | System | Continuity | Distinctive | Total | Result |
|---|---:|---:|---:|---:|---:|---:|---|
| 01 | 5 | 5 | 5 | 3 | 4 | 22 | Primary shortlist |
| 02 | 4 | 4 | 4 | 2 | 3 | 17 | Reject for now |
| 03 | 4 | 4 | 5 | 3 | 4 | 20 | Reject for now |
| 04 | 5 | 3 | 4 | 3 | 4 | 19 | Reject for now |
| 05 | 4 | 5 | 5 | 2 | 4 | 20 | Reject for now |
| 06 | 4 | 4 | 4 | 5 | 3 | 20 | Continuity shortlist |
| 07 | 4 | 5 | 4 | 3 | 4 | 20 | Reject for now |
| 08 | 3 | 3 | 4 | 2 | 4 | 16 | Reject for now |
| 09 | 5 | 5 | 5 | 3 | 5 | 23 | Utility shortlist |
| 10 | 4 | 4 | 5 | 3 | 4 | 20 | Reject for now |

The provisional selection is:

1. **01 — NyankoFace Signal Wordmark** as the primary candidate. It is the
   clearest combination of “Open”, “Face”, local signal, and a wordmark that
   can survive outside the portal shell.
2. **06 — Cat Signal** as the continuity candidate. It gives existing users a
   low-risk migration path if the mascot remains important after testing.
3. **09 — Black Wordmark + Cyan Cut** as the utility candidate. It is the
   safest monochrome, favicon, print, and code-hosting fallback.

Before production adoption, run a short user preference test, a trademark
search, and real runtime captures. The selection is intentionally provisional;
the design evidence does not claim legal clearance or user validation.

## Adoption handoff

After approval, implement one primary system only. The planned asset family is:

- `primary-logo.svg` and `primary-logo.png` for the full mark;
- `compact-mark.svg` for the 24/32px Navbar and favicon source;
- `wordmark.svg` for wide headers and social cards;
- monochrome and inverse variants with no thin strokes;
- regenerated 16/32/48px favicon, `apple-icon.png`, PWA 192/512px icons,
  docs logo, Forgejo logo, and social-card artwork;
- a versioned cache suffix and `/git/`-safe absolute asset paths.

The implementation PR must inspect Navbar, footer, login, 404/error, empty
states, docs, PWA manifest, and Forgejo shell at desktop (1024px+) and mobile
(480px or less), across Standard, Solarpunk, Cyberpunk, and OS light/dark. It
must not touch user-authored Page or Space logos. The existing canonical asset
remains live until that implementation PR is approved.

## Acceptance checklist

- [x] Ten SVG candidates with concept, strength, risk, and surface notes.
- [x] Light/dark, two-color, monochrome, inverse, 24px, and 32px comparison.
- [x] Three-candidate shortlist with scoring and selection rationale.
- [x] Production asset family, cache, base-path, and migration plan.
- [x] English/Japanese decision records and reproducible SVG generator.
- [ ] User preference, trademark, and post-approval runtime implementation; these
      are explicitly the next approval gate and are not represented as complete.
