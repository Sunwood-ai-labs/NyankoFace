---
title: 読みもの
type: article
description: NyankoFaceの背景、設計判断、検証の物語を読むための記事集。
readingTime: curated reading
tags: [思想, 実装, 運用]
related:
  - title: Knowledge Atlas
    link: /ja/wiki/
    note: 記事に登場する概念を引く。
  - title: 実践ガイド
    link: /ja/guide/getting-started
    note: 理解した内容を実行へ移す。
---

# 読みもの

NyankoFaceは、部品が存在する理由を理解すると運用しやすくなります。ここでは課題から入り、設計判断と検証をたどり、最後にWikiと実践ガイドへ接続します。

## 発想から読む

### [NyankoFace v0.6.0：実測するsurfaceと証跡を守る](./nyankoface-v0-6-0.md)

1つのPostgreSQL event ledgerで閲覧、完了したdownload、activeなlikeを実測し、
静かなnavigation、tablet-safeなSpace、MCP setup、保存したlogo探索を
review可能なsurfaceへまとめる過程を紹介します。

### [NyankoFace v0.5.0：状態を安全に運用できる境界へ移す](./nyankoface-v0-5-0.md)

PostgreSQL-backedなpipeline state、明示的なlegacy migration、fail-closedなupgrade、
読みやすいrepository preview、並列validationが、upgradeをoperatorが管理できる変更へ
変える過程を紹介します。

### [NyankoFace v0.4.0：安全につなぎ、監査可能に運用する](./nyankoface-v0-4-0.md)

statelessなMCP境界、preview／confirmation付き操作、package adapter、高可用性、管理consoleを組み合わせ、agent accessを監査可能なplatform surfaceへ変える方法を紹介します。

### [NyankoFace v0.3.0：すべての遷移を分かる速さにする](./nyankoface-v0-3-0.md)

指標で探す、すぐ反応する、Spaceの準備状況を伝える、コードを読みやすくする、同じ顔で案内する。その積み重ねで、根拠を隠さず体感速度を上げた過程を紹介します。

### [NyankoFace v0.2.0：リポジトリのファイルから配信control planeへ](./nyankoface-v0-2-0.md)

Pages、Pipelines、保護された環境設定、Portable Automations、exact-head review証跡をつなぎ、監査可能な配信workflowへ進化した内容を紹介します。

### [NyankoFace v0.1.0：リポジトリからローカルAIコミュニティへ](./nyankoface-v0-1-0.md)

初回公開リリースのrepository catalog、Docker Spaces、GPU worker、監査可能な自動化、screenshot-driven QAを案内します。

### [ローカルAIハブという選択](./local-first-hub.md)

クラウドの縮小コピーではなく、手元のGitとDockerをコミュニティへ変える理由。

### [自動マージの前に、別の目を置く](./independent-review.md)

司令塔、専門アカウント、SHA固定レビュー、fail-closedな自動マージを一つの会話にする方法。

### [Spaceはアプリで、リポジトリでもある](./docker-spaces.md)

Dockerfile-firstがGradio、Next.js、Streamlitなどを無理なく統合できる理由。

> 物語より先に事実を引きたい場合は、[Knowledge Atlas](../wiki/index.md)かナビゲーションのローカル検索を使ってください。
