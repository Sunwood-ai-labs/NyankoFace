---
title: Upgradeとデータ保持
type: guide
description: NyankoFaceを安全に更新・ロールバックするための公開手順です。
readingTime: 4分
tags: [upgrade, recovery, safety]
related:
  - title: 運用
    link: /ja/guide/operations
  - title: Release v0.6.0
    link: /ja/guide/releases/v0.6.0
---

# Upgradeとデータ保持

この公開runbookではrelease確認だけを扱います。環境固有のmigration commandや
非公開インフラの詳細は意図的に除外しています。

## Upgrade checklist

1. release noteを読み、導入するrevisionを記録します。
2. 非公開の配備手順でアプリデータをexportまたはsnapshotします。
3. secret値を露出させずに設定を検証します。
4. 非公開環境で対象serviceをrebuildまたはrestartします。
5. 認証、repository閲覧、代表的なSpace、docs buildを確認します。

## Rollback

新versionの確認が終わるまで、直前に検証したimageまたはrevisionを保持します。
rollbackが必要な場合は、そのartifactを復元し、healthとaccessの確認が終わってから
保持データを削除します。

## 保持境界

backup、database dump、証明書、識別子を含むlog、secret fileはGitの外で管理します。
公開リポジトリには再現可能なsource、sanitized example、非公開ホストやendpointを
特定しないドキュメントだけを置きます。
