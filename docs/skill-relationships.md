# Skill relationship metadata

NyankoFace reads Skill-to-Skill relationships from `skill.json` in the
root of each repository tagged with the `skill` topic. The file stays in the
same Git history as `SKILL.md`, so repository members can review, branch, edit,
and revert relationship changes through the normal Forgejo workflow.

## Schema

```json
{
  "schemaVersion": 2,
  "dependencies": [
    {
      "repo": "frontend-design-skill",
      "type": "recommended",
      "reason": "Refine product-facing documentation and Pages surfaces.",
      "evidence": "repository-polish SKILL.md: QA Workflow §3; frontend-design SKILL.md: Design Thinking"
    },
    {
      "repo": "nyankoface/security-review-skill",
      "type": "required",
      "reason": "Complete the security gate before publishing."
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `schemaVersion` | Metadata contract version. Use `2` for evidence-backed links (`1` remains readable). |
| `dependencies[].repo` | Repository slug in the same organization, or a full `owner/repo` reference. |
| `dependencies[].type` | `required` for a hard workflow requirement; `recommended` for an optional pairing. |
| `dependencies[].reason` | Short explanation shown on the relationship card. |
| `dependencies[].evidence` | Exact `SKILL.md` section(s) that justify the relationship. |

`required` means the source Skill cannot complete its documented workflow
without the target Skill. `recommended` is a curated workflow connection, not
a package dependency. Do not create either type from repository descriptions
alone: inspect both `SKILL.md` files and record the supporting sections in
`evidence`.

NyankoFace automatically derives **Referenced by** links from every public Skill
in the catalog. No reverse list needs to be maintained manually. Missing or
invalid metadata degrades to a visible **Standalone** state instead of breaking
the Skill directory.

## Editing

1. Open the Skill repository in Forgejo.
2. Create or edit `skill.json` on the default branch.
3. Commit the change through a normal branch or pull-request workflow.
4. Reload the Skill page. NyankoFace caches relationship files briefly, then
   rebuilds both dependency and reverse-reference views automatically.

The current ten-Skill content audit is recorded in
[Skill content relationship audit](./research/skill-relationship-audit.md).
