---
title: 運用
type: guide
description: NyankoFaceを安全に運用するための公開可能な基本手順です。
readingTime: 4分
tags: [operations, safety]
related:
  - title: アーキテクチャ
    link: /ja/guide/architecture
  - title: Upgradeとデータ保持
    link: /ja/guide/upgrading
---

# 運用

この公開ガイドでは、再現可能な安全習慣だけを扱います。非公開の配備
トポロジー、ホスト名、アドレス、環境固有のrunbookは公開リポジトリから除外します。

## 起動前

1. `.env.example`をローカルの追跡対象外`.env`へコピーします。
2. bootstrap credentialを変更し、tokenはsecret storeで管理します。
3. 実行可能なSpaceを公開できるリポジトリを信頼済み範囲に限定します。
4. secret値を出力せずにCompose設定を確認します。

## 運用中

- credentialをIssueへコピーせず、アプリとrunnerのlogを確認します。
- registrationとwrite権限を信頼できるmaintainerに限定します。
- 取り込んだDockerfileとruntime依存関係は信頼できないコードとして扱います。
- logやスクリーンショットを共有する前に、ホスト名、アドレス、内部URLを削除します。

## 復旧

配備バックアップはリポジトリの外で管理し、復元テストも非公開環境で行います。
復旧後はhealth、認証、リポジトリアクセス、代表的なSpaceを確認します。backup archive、
database dump、証明書、token、ホスト固有設定はcommitしません。
