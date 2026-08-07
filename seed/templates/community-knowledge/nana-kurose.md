---
title: はじめてDocker Spaceを公開した記録
description: 小さなHTMLアプリをDockerfileからSpaceとして公開するまでに迷った点
emoji: "🚀"
topics: [community-authored, spaces, docker, beginner]
published: true
updated: 2026-07-26
---

# はじめてDocker Spaceを公開した記録

静的HTMLの小さなツールを、Dockerfile付きのSpaceとして公開しました。アプリ自体よりも、外からアクセスできるポートとコンテナの待受アドレスで時間を使いました。

## うまくいった構成

- コンテナ内では`0.0.0.0`で待ち受ける
- 公開ポートをREADMEとDockerfileで一致させる
- ローカルでイメージをビルドしてから投稿する
- 起動後にPCとスマートフォンの両方で開く

トップ画面が表示されても、ボタンやページ内リンクまで動くとは限りません。公開後は実際に操作し、ブラウザーの戻る操作でも一覧へ復帰できるか確認しました。

次は同じ内容をReact版に置き換え、ビルド成果物を配信する構成との違いを比べてみます。
