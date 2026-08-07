---
title: ローカルAIハブという選択
type: article
description: ローカルファーストは小さなクラウドではなく、所有・遅延・協働に対する別の答えです。
readingTime: 7分
updated: 2026-07-21
tags: [local-first, forgejo, docker, ownership]
related:
  - title: プラットフォーム地図
    link: /ja/wiki/platform-map
    note: サービスと公開経路を一覧する。
  - title: アーキテクチャガイド
    link: /ja/guide/architecture
    note: 配置と信頼境界を確認する。
---

# ローカルAIハブという選択

AIハブの簡単な姿はカードのギャラリーです。難しい姿は、どのカードもチームが所有できる実体――リポジトリ、revision、動くアプリ、議論、履歴――につながっている場所です。

NyankoFaceは後者から設計されています。

## すでにある堅牢な実体を使う

Gitはファイル、履歴、branch、tag、作者、レビューを保存できます。DockerはWebアプリと実行環境を梱包できます。NyankoFaceは両者を隠しません。Forgejoを永続的な協働層にして、その周りへ発見とローカル実行の体験を加えます。

Modelのカードは別DBに置かれた飾りではありません。Spaceは無関係なデモを指すiframeではありません。Promptの古い版も新しい版で上書きされません。見えるカタログが、clone・review・runできるリポジトリの事実につながっています。

## ローカルファーストは運用境界である

「ローカル」は単に`localhost`を意味しません。障害と責任を誰が制御するかを示します。

- Repositoryデータは自分が管理するForgejo volumeに残る。
- CPU Spaceは選んだDocker hostでbuild・runされる。
- TLSは共有gatewayで終端する。
- Pagesはrepositoryのbranchまたはdirectoryから生成される。
- Agentはscopeされたaccountで動き、IssueとPRに可視の履歴を残す。

非公開ネットワークで共有することもできます。外部アクセスは所有権の移動ではなく、自分のシステムへ明示的に開いた経路です。

## Portalは第二の正解ではなく、見方である

Next.js frontendはForgejo repositoryをModels、Datasets、Spaces、Skills、MCPs、Promptsとして見やすくします。表示のためにcacheや整形をしても、source、permission、history、collaborationの正解はForgejoです。

この関係が、美しい一覧と実際にclone・実行できるものがずれる問題を防ぎます。

## 所有する代わりに引き受けるもの

運用者はDocker resource、backup、repository permission、第三者Dockerfileのbuildに伴うriskを理解する必要があります。そのために[運用ガイド](../guide/operations.md)、[Visual QA](../guide/visual-qa.md)、独立した[agent review gate](./independent-review.md)があります。ローカル基盤は警告がないからではなく、証拠を残すから信頼できます。
