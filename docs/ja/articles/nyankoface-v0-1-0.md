---
title: リポジトリからローカルAIコミュニティへ
type: article
description: NyankoFace v0.1.0が何を接続し、その境界をなぜ大切にしたかをたどる案内。
readingTime: 8分
tags: [release, architecture, operations]
---

![NyankoFace v0.1.0 リリースヘッダー](/releases/release-header-v0.1.0.svg)

# リポジトリからローカルAIコミュニティへ

NyankoFace v0.1.0は、AIコミュニティの永続的な情報を、普通のGit repositoryと普通のapplicationとして保つところから始まります。

## 正本を退屈なままにする

Files、commit、tag、Issue、Pull Request、user、organization、team、star、forkはForgejoが管理します。NyankoFaceは第二のrepository databaseを作らず、発見と実行の層を追加します。topicによってModels、Datasets、Spaces、Characters、Benchmarks、Skills、MCPs、Prompts、Knowledgeを分類します。

この境界により、catalogを移動できます。cloneはそのままcloneであり、tagは不変であり、portalを再構築してもproject historyは書き換わりません。

## Spaceをapplicationとして扱う

共通契約はrepository rootのDockerfileです。Gradio、静的HTML、React、Vue、Next.js、Streamlit、FastAPI、Node.jsの各sampleはport `7860`でlistenし、runnerがbuild、lifecycle、proxyを担当します。

公開applicationはForgejo sessionなしで起動できます。破壊的操作や設定変更はOwnerだけに制限します。既存serviceは`external_url`、静的documentはNyankoFace Pagesを選べます。

## 配備の詳細は非公開に保つ

公開snapshotではapplicationの境界と安全なruntime contractを扱い、配備固有のhostname、address、hardware topology、credential、運用者向け接続経路は省略しています。これらは非公開の運用repositoryで管理してください。

## 自動化にも証跡を残す

maintenance flowは見えないcron jobではありません。coordinatorが分類し、専門identityへ委任し、Claude Code `/goal`を実行し、Pull Requestを作成し、固定commit SHAに対する独立reviewを依頼します。evidence、label、reviewが不足する場合、auto-mergeはfail-closedになります。

## 利用者が触る画面を検証する

Visual QAはStandard／Solarpunk／CyberpunkのPC／mobile routeを撮影します。長いpageをscrollし、menuとcontrolを操作し、MarkdownとMermaidを検証し、実装証跡と一緒にscreenshotを保存します。

NyankoFaceは単なるcatalogでもrunnerでもありません。data、application、automation、verificationのすべてを調べられるローカル協働環境です。

[v0.1.0 release note](../guide/releases/v0.1.0.md)を読むか、[最初のdeployment](../guide/getting-started.md)へ進んでください。
