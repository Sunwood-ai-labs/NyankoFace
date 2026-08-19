# NyankoFace Issue conventions

Read this reference when creating, updating, labeling, or relating an Issue in
`Sunwood-ai-labs/NyankoFace`.

## Repository and support route

- Repository: `Sunwood-ai-labs/NyankoFace`
- Issue window: `https://github.com/Sunwood-ai-labs/NyankoFace/issues`
- Support guidance: `SUPPORT.md` says to search existing Issues first, use the
  bug form for reproducible defects, use the feature form for proposals, and
  use private vulnerability reporting for security-sensitive reports.
- Security link: `https://github.com/Sunwood-ai-labs/NyankoFace/security/advisories/new`

## Issue forms

- `.github/ISSUE_TEMPLATE/bug_report.yml`
  - default title prefix: `[Bug]: `
  - label: `bug`
  - captures revision, area, reproduction, expected behavior, actual behavior,
    environment, and a safety check
- `.github/ISSUE_TEMPLATE/feature_request.yml`
  - default title prefix: `[Feature]: `
  - label: `enhancement`
  - captures problem, proposal, alternatives, and primary scope
- `.github/ISSUE_TEMPLATE/config.yml` disables blank Issues and routes security
  reports privately.

Do not force a form prefix into an already user-specified title unless the user
asks for that convention. The form fields are a content checklist, not a reason
to add boilerplate that is not relevant to the report.

## Label policy

The repository's automatic label configuration currently allowlists:

- `bug`
- `enhancement`
- `documentation`
- `question`
- `good first issue`

The maintenance classifier uses deterministic hints: reproducibility and
expected/actual behavior tend toward `bug`; feature proposals and requests tend
toward `enhancement`; README/docs wording tends toward `documentation`; direct
questions tend toward `question`; and explicitly beginner-friendly work may use
`good first issue`.

The automatic system only applies labels that already exist in the target
repository, preserves manual labels, and rejects weak matches. The Issue skill
must follow the same safety boundary: inspect current labels, use existing names
only, preserve labels on updates, and leave uncertain labels untouched.

## Relationship wording

Use explicit Markdown references because the available GitHub connector may not
provide a native parent/sub-issue mutation:

- `Related to #123` — related but independent work
- `Depends on #123` — work cannot be accepted before the referenced Issue
- `Duplicate of #123` — the referenced Issue is canonical

Keep relationship references in a `## Related issues` section when there are
two or more, and preserve existing references during updates. Do not use
`Closes #N` in an Issue body to imply a parent relation or a future PR merge.

## Local delivery

When the task is a terminal result for the registered `nyankoface` project and
the GitHub write has been read back successfully, send one delivery card with:

```powershell
& "$env:USERPROFILE\.codex\scripts\Send-MattermostProjectUpdate.ps1" `
  -Project nyankoface -Status verified `
  -Task "Issue作成または更新" `
  -Summary "..." `
  -Evidence "Issue URLとread-back結果" `
  -Artifact "https://github.com/Sunwood-ai-labs/NyankoFace/issues/N" `
  -Next "..."
```

Do not include credentials, webhook URLs, private browser state, or unsanitized
local deployment details in the Issue or delivery card.
