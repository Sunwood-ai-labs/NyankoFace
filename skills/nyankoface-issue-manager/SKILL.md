---
name: nyankoface-issue-manager
description: Create and maintain NyankoFace GitHub Issues by searching for duplicates, selecting safe existing labels, linking related issues, and verifying the saved Markdown.
---

# NyankoFace Issue Manager

Use this skill when the user wants to create, update, classify, label, relate, or triage an Issue for `Sunwood-ai-labs/NyankoFace`.

Read [references/project-conventions.md](references/project-conventions.md) before making an Issue mutation. It records the repository's Issue forms, label allowlist, security route, and relationship conventions.

## Required outcome

Produce one of these outcomes:

- an existing matching Issue is identified and no duplicate is created;
- a new Issue is created with a clear title, evidence-backed Markdown body, appropriate existing labels, and explicit related-Issue references; or
- an existing Issue is updated without losing its current body, labels, or relationship context.

Always report the exact repository, Issue number, URL, labels, relationship references, and read-back result. If the user asked only for a draft, stop before the GitHub write.

## Workflow

### 1. Fix the target and scope

- Resolve the repository from the current checkout's `origin` remote and GitHub metadata. Do not silently switch repositories, accounts, or visibility.
- Confirm the authenticated GitHub identity and that the target repository is `Sunwood-ai-labs/NyankoFace` unless the user explicitly names another repository.
- Read the current local instructions, `SUPPORT.md`, and the Issue forms before drafting.
- Classify the request as a reproducible bug, feature proposal, documentation request, question/support request, or security report. Route security-sensitive reports to GitHub private vulnerability reporting; do not expose secrets or open a public Issue for them.

### 2. Search before creating

Use the GitHub connector first:

1. Search the exact repository with the user's distinctive symptom, UI label, error text, route, file, and a short title phrase as separate focused searches.
2. Inspect the strongest open and recently closed candidates. Read their title, body, state, labels, and relationship context; search results alone are not enough to declare a duplicate.
3. Classify the result:
   - exact duplicate: do not create a new Issue; return the canonical Issue;
   - related but distinct: create or update only when the requested scope is materially different, and add an explicit relationship reference;
   - no relevant match: proceed to draft and create.

Do not create a placeholder Issue merely because the request is underspecified. Ask for the smallest missing fact that changes the title, target, or acceptance criteria.

### 3. Draft an evidence-backed body

Use real Markdown line breaks and blank lines. Select the repository's bug or feature form as the baseline, then add only the sections needed by the request:

- `Summary` / `概要`
- `Reproduction steps` for bugs, or `Problem` for proposals
- `Expected behavior`
- `Actual behavior` and impact
- environment, revision, route, or affected files when known
- evidence and verification status, separating observation from inference
- concrete acceptance criteria
- `Related issues` with explicit `Related to #N`, `Depends on #N`, or `Duplicate of #N` references when applicable

Do not invent reproduction results, browser state, URLs, commits, labels, or test outcomes. Mark code-only inspection, local tests, live UI checks, and unverified reports separately.

### 4. Apply labels conservatively

- Inspect labels already present in the target repository. If the connector cannot list labels, use the repository-scoped `gh label list` command as a read-only fallback.
- Use only labels that already exist in the repository. Never create a label implicitly from a guessed spelling.
- Preserve existing labels when updating an Issue. Prefer additive label operations over replacing the full label set.
- Apply the smallest justified set. Typical choices are `bug`, `enhancement`, `documentation`, `question`, and `good first issue`; use the project's documented confidence/rule hints, not intuition alone.
- A reproducible defect may receive `bug`; a README/docs behavior may also receive `documentation`; a requested capability may receive `enhancement`; use `good first issue` only when the scope is explicitly small and newcomer-friendly.
- If evidence supports two categories, keep both and explain why. If no label is clearly justified, leave the labels unchanged and report that decision.

### 5. Relate Issues without pretending a formal hierarchy exists

- Use Markdown references in the body so GitHub creates navigable links: `Related to #123`, `Depends on #456`, or `Duplicate of #789`.
- Use `Duplicate of #N` only when the existing Issue is genuinely canonical. Do not close or replace an Issue without explicit authorization.
- Use `Depends on #N` only when the dependency is real and acceptance depends on it. Do not use closing keywords to imply a merge relationship.
- If the available GitHub connector does not expose a formal parent/sub-issue relationship mutation, record the relationship explicitly in Markdown and report it as a reference, not as a native parent link.
- When updating an existing Issue, preserve prior related links and add a new relationship section only once.

### 6. Write once, then read back

For a new Issue, use `github_create_issue` with the exact target, title, body, and labels. For an existing Issue, fetch it first and use `github_update_issue` with a complete replacement body only after preserving the current content and labels.

After every write, fetch the saved Issue independently and verify:

- repository, Issue number, title, state, and URL;
- body has real newlines and blank lines, not literal `\\n` text;
- fenced code blocks are paired and links/Issue references survived;
- requested sections and acceptance criteria are present;
- labels match the intended set and no pre-existing label disappeared;
- related Issue references point to the intended repository and Issue numbers.

If read-back fails or differs, stop and report the Issue as unverified. Do not automatically retry the mutation.

## Tool routing

Prefer these GitHub connector operations when available: repository/profile lookup, Issue search, Issue fetch, Issue creation/update, and additive label updates. Use local `git`/`gh` only for checkout context or a connector gap. Keep all searches and writes bounded; do not poll or retry indefinitely.

For a registered NyankoFace project result, send exactly one evidence-backed delivery card with the local project delivery script after the GitHub read-back succeeds. Do not use the delivery card as a substitute for the final response.
