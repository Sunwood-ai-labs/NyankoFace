---
title: Spaceはアプリで、リポジトリでもある
type: article
description: Dockerfile-firstなら、多様なWeb stackを一つのframeworkへ押し込めず、同じ契約で扱えます。
readingTime: 6分
updated: 2026-07-21
tags: [spaces, docker, gradio, nextjs]
related:
  - title: Runtime
    link: /ja/wiki/runtime
    note: lifecycle、routing、resource境界を確認する。
  - title: Docker Spaceを公開する
    link: /ja/guide/spaces
    note: 実際の契約に沿って作る。
---

# Spaceはアプリで、リポジトリでもある

Gradio、Streamlit、React、Vue、Next.js、FastAPI、Node serverは多くの点で異なります。ただし、container内のportでWebアプリを待ち受けられる点は共通です。

NyankoFaceには、それで十分です。

## 共通契約を小さく保つ

SpaceはDockerfileを持つForgejo repositoryです。Containerは所定の内部portでWebアプリを公開し、path-awareなreverse proxyの背後で動作します。Source、assets、dependency、documentation、historyはframeworkに自然な構成のまま保持できます。

Next.jsをGradio設定へ変換したり、Vue appを静的metadataへ平坦化したりしません。Dockerfileが実行可能な説明として残ります。

## Card、repository、appは別の問いに答える

Catalog cardは「何をするか、誰が所有するか、実行中か、どのtagか、何人が見たか」に答えます。Repositoryは「どのcommitか、何をinstallするか、どうreviewするか、別環境で再構築できるか」に答えます。埋め込まれたappは「本当に動くか」に答えます。

3つを一つのSpaceとして扱うことで、見栄えのよいcatalogが古いgeneric demoへ飛ぶ問題を防ぎます。

## CPU-firstという有益な制約

Sample catalogはZeroGPUや必須GPU runtimeを避けます。通常のDocker hostで再現でき、start、resource limit、failure messageを理解しやすくするためです。GPU supportは意図して追加できますが、baselineには紛れ込みません。

Docker契約は[Spacesガイド](../guide/spaces.md)、lifecycleとroutingは[Runtime node](../wiki/runtime.md)で確認できます。
