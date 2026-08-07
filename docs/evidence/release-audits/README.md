# Release branch agent E2E evidence

Captured on 2026-07-25 against the retained public fixture
[`nyankoface/release-agent-demo`](https://example.invalid/git/nyankoface/release-agent-demo).

## Trigger

- Release branch: `release/e2e-20260725-140913`
- Pushed commit: `33d4e503814ef8a938af648e2d944310791ab61f`
- Comparison branch: `main`
- Security job start: `2026-07-25T14:18:23.421652Z`
- Documentation job start: `2026-07-25T14:18:23.608799Z`
- Parallel start delta: about 0.19 seconds

## Retained results

| Gate | Issue | Pull request | Author | Result |
|---|---|---|---|---|
| Security | [#7](https://example.invalid/git/nyankoface/release-agent-demo/issues/7) | [#10](https://example.invalid/git/nyankoface/release-agent-demo/pulls/10) | `security-agent` | Independent review approved; open and unmerged for human review |
| Documentation | [#8](https://example.invalid/git/nyankoface/release-agent-demo/issues/8) | [#9](https://example.invalid/git/nyankoface/release-agent-demo/pulls/9) | `docs-agent` | Independent review found two medium evidence defects; open and unmerged with changes requested |

Both PRs target `release/e2e-20260725-140913`, use distinct deterministic
`agent/release-...` branches, and were created by the specialist account rather
than the shared maintainer account.

## Maintainer merge verification

A second push to the same retained release branch verified the enabled
fail-closed merge path:

- Pushed commit: `b9c9852eb78837a02e21857330c89436040274c0`
- Security Issue: [#11](https://example.invalid/git/nyankoface/release-agent-demo/issues/11)
- Specialist PR: [#13](https://example.invalid/git/nyankoface/release-agent-demo/pulls/13), authored by `security-agent`
- Review: `review-agent` approved the exact PR head
  `b329a84b956ba67bd36a6c6a39c25fcd6d20773a` with no findings
- Merge: `glm-maintainer` merged the PR as
  `a5dfaddde6a7a24817873daf0ba214ac00409a63`
- Cleanup: the specialist source branch was deleted after merge

The release branch now points at that merge commit. Forgejo returned HTTP 200
for the maintainer's merge request, and the resulting commit used the neutral
fixture identity `glm-maintainer@noreply.example.invalid`.

## QA inventory

| Claim | Functional check | Visual check |
|---|---|---|
| A release push starts both gates | PostgreSQL-backed job API recorded two jobs for the same SHA | Issue list shows separate Security and Documentation audit Issues |
| Work runs concurrently | Job timestamps differ by about 0.19 seconds and both processes were observed simultaneously | Separate Issue assignments are visible |
| Specialists publish independent PRs | Forgejo API reports `docs-agent` on #9 and `security-agent` on #10 | PR headers show each specialist, source branch, and release target |
| Maintainer owns the merge | #13 was approved for its current SHA and merged by `glm-maintainer`; the specialist branch was deleted | The retained Issue and PR show the specialist, independent reviewer, and maintainer as separate accounts |
| Independent review fails closed | #9 remains open after `changes_requested`; only a current-SHA approval can reach the maintainer merge call | Issue comments show the review account's evidence-backed rejection |
| Responsive rendering | Playwright inspected 1440×1000 and 390×844 pages | No horizontal overflow was observed in either viewport |

Exploratory checks also confirmed that a non-release push is ignored and an
agent-authored release push does not recursively create more audit jobs.

## Screenshots

Audit list: [Desktop](audit-list-desktop.png) · [Mobile](audit-list-mobile.png)

| Security PR | Documentation PR |
|---|---|
| [Desktop](security-pr-desktop.png) · [Mobile](security-pr-mobile.png) | [Desktop](docs-pr-desktop.png) · [Mobile](docs-pr-mobile.png) |

| Approved independent review | Rejected independent review |
|---|---|
| [Desktop](security-review-desktop.png) · [Mobile](security-review-mobile.png) | [Desktop](docs-review-desktop.png) · [Mobile](docs-review-mobile.png) |
