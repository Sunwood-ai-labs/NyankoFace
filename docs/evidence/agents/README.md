# Specialist agent identity evidence

The retained [Issue #20](https://example.invalid/git/nyankoface/pages-starter/issues/20) was created with the maintenance opt-out marker so it remains stable. Each comment was posted through that account's own Forgejo token.

![Five independent accounts commenting in one Issue](specialist-agent-identities.png)

| Account | Role | Forgejo profile capture |
|---|---|---|
| `glm-maintainer` | Coordinator and router | ![GLM Maintainer profile](glm-maintainer-profile.png) |
| `designer-agent` | Visual and accessibility specialist | ![NyankoFace Designer profile](designer-agent-profile.png) |
| `coding-agent` | Implementation and test specialist | ![NyankoFace Coding profile](coding-agent-profile.png) |
| `docs-agent` | Documentation specialist | ![NyankoFace Docs profile](docs-agent-profile.png) |
| `security-agent` | Release security and supply-chain specialist | Generated profile evidence is captured during the release-branch E2E verification. |
| `review-agent` | Independent reviewer | ![NyankoFace Review profile](review-agent-profile.png) |

All five screenshots were captured from the running Forgejo instance after reseeding. The profile image sources resolve to five distinct `/git/avatars/<hash>` URLs. This specifically guards against the earlier client-side fallback that replaced specialist avatars with one shared image.

## Mention-driven delegation

[Issue #21](https://example.invalid/git/nyankoface/pages-starter/issues/21) is the retained end-to-end proof for the actual orchestration order:

1. `glm-maintainer` classifies the Issue and visibly mentions `@docs-agent`.
2. Only after the mention is published, the `docs-agent` job enters `running` and adds the 👀 reaction.
3. `docs-agent` creates [PR #22](https://example.invalid/git/nyankoface/pages-starter/pulls/22), adds 🚀, and posts its own completion comment.

![Maintainer mention visible while the specialist job is running](maintainer-mentions-specialist.png)

![Maintainer mention followed by the specialist's own completion reply](maintainer-delegates-specialist-complete.png)
