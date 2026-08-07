---
title: エージェント運用
type: wiki
description: Identity、委任、証跡、review state、guarded auto-mergeの参照ページ。
readingTime: 8分 reference
updated: 2026-07-21
tags: [agents, maintainer, reviewer, merge]
related:
  - title: 独立レビューの読みもの
    link: /ja/articles/independent-review
    note: このgateの理由を読む。
  - title: 自動メンテナンスガイド
    link: /ja/guide/automated-maintenance
    note: Tokenとwebhookを設定する。
---

# エージェント運用

## Identity

| Account | 責任 | 実装 | 承認 |
|---|---|---:|---:|
| `glm-maintainer` | classify、delegate、publish、gate、merge | wrapperのみ | no |
| `designer-agent` | UI/UX、responsive、theme、a11y evidence | yes | no |
| `coding-agent` | application code、refactor、test、build | yes | no |
| `docs-agent` | README、VitePress、example、reconstruction docs | yes | no |
| `security-agent` | threat analysis、auth、secret、dependency、validation、supply chain | yes | no |
| `review-agent` | read-onlyのrequirement/diff/test/security/regression review | no | yes |

## State transition

```text
Issueがmaintainerをmention
  → maintainerが1体のspecialistをmention
  → specialistがPRとevidenceを公開
  → maintainerがreview-agentをmention
  → reviewerが現在のhead SHAを評価
      ├─ rejected → PRはopen → maintainerがspecialistを再mention
      └─ approved → wrapperがSHA再確認 → server-side guarded merge

Release branchがpush
  → maintainerがsecurity/docs監査Issueを作る
  → security-agentとdocs-agentが分離cloneで同時実行
  → release branch向けPRを各自公開
  → review-agentが各head SHAを評価
  → 現在SHAへの独立reviewが指摘なしで承認した場合だけglm-maintainerがmerge
```

## UI evidence

ImplementerとReviewerは別々に証跡を作ります。それぞれmobile（幅480以下）とdesktop（幅1024以上）の実PNG、具体的なinteraction check、error/overflow結果が必要です。WrapperはJSONのlabelを信用せず、PNG signatureと実寸を検証します。

## Approval invariant

全requirementとcheckがpass、findingが空、Reviewerがtracked fileを変更していない、recorded SHAが現在のPR headと一致し、Forgejoが同じSHAの`head_commit_id`を受理した場合だけapprovalは有効です。

## Observable API

- `/api/agents`はpersonaとrole contractを返す。
- `/api/jobs`はassignmentとjob stateを返す。
- Forgejo Issue/PRはhuman、maintainer、specialist、reviewerの会話を保存する。
