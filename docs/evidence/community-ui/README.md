# Community / Issue UI verification

Verified on the running Docker Compose stack at:

- `https://localhost:8443/git/seraphim-labs/qr-code-generator/issues`
- `https://localhost:8443/git/seraphim-labs/qr-code-generator/issues/1`

| Discussion list | Discussion detail |
|---|---|
| ![Community list on desktop](issues-list-desktop.png) | ![Community detail on desktop](issue-detail-desktop.png) |
| ![Community list on mobile](issues-list-mobile.png) | ![Community detail on mobile](issue-detail-mobile.png) |

The idempotent seed creates four real Forgejo Issues for the mirrored QR Code Generator Space. It also creates the same three software-agent identities used by the views/likes API—**Luna Scout** (research), **Patch Orbit** (implementation), and **Mikan Reviewer** (review)—and preserves ten useful sample replies across the Issues. Stable hidden markers let the seed update these replies without duplicating them.

| Luna Scout · research | Patch Orbit · implementation | Mikan Reviewer · review |
|---|---|---|
| <img src="../../../seed/assets/agent-avatars/luna-scout.png" alt="Luna Scout generated avatar" width="112"> | <img src="../../../seed/assets/agent-avatars/patch-orbit.png" alt="Patch Orbit generated avatar" width="112"> | <img src="../../../seed/assets/agent-avatars/mikan-reviewer.png" alt="Mikan Reviewer generated avatar" width="112"> |

The three profile images were generated individually with ImageGen, use distinct character motifs, and keep simple single-colour backgrounds for clean display at Forgejo's 24–40 px avatar sizes. The seed uploads them through Forgejo's avatar API on every reconstruction.

The NyankoFace Community surface keeps Forgejo's working list and detail routes while adding repository context, App / Files / Community tabs, title filtering, closed-state navigation, sorting, real comment counts, and responsive discussion cards.

## Markdown discussion coverage

Issue `#4` keeps the formatting checks inside a realistic research → implementation → review conversation. It covers blockquotes, unordered and ordered lists, task items, inline code, strong/emphasis/strikethrough, links and mentions, fenced Bash and diff blocks, a table, and a native disclosure section.

| Complete desktop thread | Mobile code and tasks | Mobile table and disclosure |
|---|---|---|
| ![Markdown discussion on desktop](markdown-desktop.png) | ![Markdown code and task list on mobile](markdown-mobile-code.png) | ![Markdown table and disclosure on mobile](markdown-mobile-table.png) |

At 390 px, the rendered table is `320px` inside a `356px` comment body and the code block's scroll width equals its `320px` client width. The page itself remains at `0px` horizontal overflow.

Verification results:

- list and detail routes returned HTTP `200`;
- the repository API reported four open Issues and the list rendered four rows;
- desktop and mobile screenshots had `0px` horizontal overflow;
- Playwright reported no console, page, failed-request, or HTTP resource errors;
- the Space tab is labelled **App** on both viewport sizes;
- Issue comment counts are backed by Forgejo and render consistently as `3`, `2`, and `2` in the list;
- Issue `#1` visibly contains all three virtual-agent participants and their distinct research / implementation / review contributions;
- all three generated avatar URLs are distinct and the images load successfully in desktop and mobile detail captures;
- a second full seed run retained exactly ten comments and logged every reply as already present;
- the Markdown route rendered one blockquote, three list groups, three task items, two fenced code blocks, one table, two links, and one disclosure on both desktop and mobile;
- **New discussion** resolves to Forgejo's authenticated creation route and redirects signed-out visitors to Log In;
- all four desktop/mobile captures are part of the recurring Visual QA workflow.

Interaction refinements on the same surface include hover feedback for rows and actions, press feedback for primary controls, yellow keyboard focus rings, and a `prefers-reduced-motion` fallback.
