---
title: 自動マージの前に、別の目を置く
type: article
description: 専門Agent、明示的な司令塔、独立証跡を安全な自動マージへつなぐ方法。
readingTime: 9分
updated: 2026-07-21
tags: [agents, review, auto-merge, evidence]
related:
  - title: エージェント運用
    link: /ja/wiki/agent-operations
    note: accountと状態遷移を参照する。
  - title: 自動メンテナンスガイド
    link: /ja/guide/automated-maintenance
    note: 実際の設定と操作を確認する。
---

# 自動マージの前に、別の目を置く

「実装完了」と「承認」が同じイベントになると、自動化は危険になります。NyankoFaceはこの2つを意図的に分離します。

## 責任の順序を会話に残す

利用者は`@glm-maintainer`をメンションします。Maintainerは依頼を分類し、Designer、Coding、Docsのうち1つの専門accountへ可視のコメントで委任します。担当者はClaude Code `/goal`を実行し、変更、検証、PR、証跡を公開します。

そこで、処理はいったん止まります。

Maintainerが`@review-agent`を明示的にメンションします。ReviewerはPR URLと現在のhead SHAを受け取りますが、契約はread-onlyです。Issue要件、diff、test、regression、securityを調べ、UI変更ならmobileとdesktopで実アプリを起動して独自に撮影します。

## SHAが必要な理由

対象が固定されていない承認は、過去への感想にすぎません。Reviewerは`reviewed_sha`を記録し、merge直前にwrapperがForgejoから現在のheadを再取得します。異なればmergeを拒否します。

Merge APIにもForgejoの`head_commit_id`を渡し、server側でも古い判断を拒否できるようにします。

## 失敗は閉じ、見える場所へ返す

要件・checkの失敗、残ったfinding、reviewer画像不足、tracked file変更、矛盾したreport、SHA変化のどれかがあればPRはmergeされません。Reviewerがfindingを公開し、Maintainerが専門担当を再メンションして修正条件を返します。

## 実際の証拠

[Issue #25](https://example.invalid/git/nyankoface/pages-starter/issues/25)では、担当者が「トップへ戻る」操作を検証しました。Maintainerは別accountのReviewerへ委任し、Reviewerはアプリを独自実行して10要件・9checkを合格、8枚を添付し、SHA `b55a7369…`をfindingなしで承認しました。その後にだけ[PR #26](https://example.invalid/git/nyankoface/pages-starter/pulls/26)がmergeされています。

重要なのはAgentがmergeしたことではありません。誰が、何を、どの状態で、なぜ許可したかを会話から説明できることです。
