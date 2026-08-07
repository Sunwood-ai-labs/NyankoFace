---
title: リポジトリのファイルから配信control planeへ
type: article
description: NyankoFace v0.2.0がPages、Pipelines、保護された設定、review証跡をどう接続したか。
readingTime: 7分
tags: [release, pipelines, pages, automation]
---

![NyankoFace v0.2.0 リリースヘッダー](/releases/release-header-v0.2.0.svg)

# リポジトリのファイルから配信control planeへ

NyankoFace v0.1.0では、Git repositoryを永続的なsource of truthにしました。v0.2.0では、そのrepositoryを証跡を隠さず公開siteや実行applicationへ届ける方法を整えます。

## 推測せずPagesを公開する

Pages inspectorはbranch名だけで公開済みと判断しません。`gh-pages/index.html`、次にdefault branchの`docs/index.html`を実際に確認し、published、missing、private、upstream errorを区別します。deployment wizardは書き込み前にbranchとfileを表示し、完了後にcommit、log、public URLを返します。

## RepositoryからPipelineを運用する

Pipelines tabは、別のworkflow databaseを作らずForgejo Actions runを表示します。jobとstepを追跡し、上限付きlogを読み、artifactを確認し、failed jobのretry、runのcancel、protected deploymentのapprove、immutable revisionを指定したproduction rollbackを行えます。

重要なのはbuttonの見た目ではなく順序とidentityです。古いhistoryが新しいstagingを上書きせず、tagはproductionとして扱われ、同時runが互いを壊さず、artifactがcheckout revisionと一致する必要があります。

## 設定を秘密に保ち、Automationを持ち運ぶ

Space Variable／Secretにはcookie非依存の認証APIを追加しました。APIはmetadataとaudit historyだけを返し、保存済みSecret値は返しません。runtimeとbuild scopeを分離し、build設定はForgejo Actionsへ同期しながら、無関係なruntime応答へ漏らしません。

Portable Automationsは実行に対して逆の方針を取ります。catalogとdownloadは可能ですが、必ず`enabled = false`へ正規化します。immutableなpublic revisionを検証し、secretらしい値、private endpoint、unsafe path、破壊的command、未知schema fieldを拒否します。

## Review証跡を配信の一部にする

v0.2.0の配信作業では、古いreview証跡の危険性も明らかになりました。merge guardはPull Requestのexact head、repository自身の`CI / validate` GitHub Actions check、未解決threadが0件であること、現在headのCodex Reviewを要求します。head、check、review、threadを2回一致するまで収集し、merge commandも検証済みSHAを固定します。

Visual captureを自動CIの合否へ入れない理由も同じです。構造checkはCIで行い、見た目は実browser、対象deployment、人による比較で確認します。

[v0.2.0 release note](../guide/releases/v0.2.0.md)、[Repository Pipelines](../guide/pipelines.md)、[変更配信](../guide/change-delivery.md)へ進んでください。
