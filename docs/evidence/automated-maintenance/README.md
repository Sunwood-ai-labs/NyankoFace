# Automated maintenance evidence

This directory keeps browser-verified evidence for the maintainer-led Claude Code `/goal` workflow.

## Release and automatic Issue maintenance

The [release and Issue automation evidence](release-and-issue-automation/README.md)
records production tests for read-only inquiries, bug-fix PRs, parallel
security/documentation release gates, bounded retries, deduplication, and
feedback-loop prevention.

## ClearNext UI evidence gate

- Request: [Issue #22](https://example.invalid/git/nyankoface/clear-next/issues/22)
- Result: [PR #23](https://example.invalid/git/nyankoface/clear-next/pulls/23)
- Specialist: `designer-agent`, selected and mentioned by `glm-maintainer`
- Merge: server-side auto-merge, commit `22430240bf329d67da36636f7ba58a63002350ea`
- Reported UI checks: 18 passed rows covering click, Enter, Space, reversible state, mobile and desktop layouts, light/dark themes, overflow, console errors, and page errors
- Attachments: four validated PNG files (mobile/desktop, closed/opened)

`issue-22-completion-comment.png` is a browser capture of Forgejo rendering the specialist's Markdown report. `issue-22-mobile-opened.png` is a browser capture of the actual attached mobile PNG. Japanese text is readable after adding Noto CJK fonts to the maintenance image.

## Independent reviewer and auto-merge gate

- Request: [Pages starter Issue #25](https://example.invalid/git/nyankoface/pages-starter/issues/25)
- Result: [PR #26](https://example.invalid/git/nyankoface/pages-starter/pulls/26)
- Reviewed head: `b55a7369cdee3d49b5ffcc5c74bd6a46882018a8`
- Reviewer: `review-agent`, a separate Forgejo identity using a read-only `/goal` contract
- Review result: 10 requirements passed, 9 checks passed, zero findings, eight independent screenshots
- Merge: performed only after approval by `glm-maintainer`, commit `b64e42021f03f4110614c7cd2f9fd3b27a6b254a`

The three `issue-25-*.png` files are browser captures of the visible maintainer hand-off, the SHA-bound reviewer approval and traceability table, and the final merged PR header. They confirm that the implementer's self-assessment is not treated as approval.
