---
title: はじめに
type: guide
description: 再現可能なNyankoFace環境を起動し、主要サービスを確認します。
readingTime: 10分
tags: [インストール, compose, 初回起動]
related:
  - title: プラットフォーム地図
    link: /ja/wiki/platform-map
  - title: トラブルシューティング
    link: /ja/guide/troubleshooting
---

# はじめに

## 必要要件

- Docker EngineまたはDocker Desktop
- Docker Compose v2（`docker compose`）
- clone・開発用のGit
- ForgejoデータとSpaceイメージを保存できるディスク容量

通常のCompose起動では、ホスト側にNode.jsやPythonは不要です。

## 新しい環境で起動する

```bash
git clone https://github.com/Sunwood-ai-labs/NyankoFace.git
cd NyankoFace
cp .env.example .env
docker compose up -d --build
```

Windows PowerShellではコピー行を次に置き換えます。

```powershell
Copy-Item .env.example .env
```

共有する前に `.env` の `NYANKOFACE_ADMIN_PASSWORD` を変更してください。`https://localhost:8443` を開きます。初回は自己署名の開発用証明書が生成されるため、ブラウザに警告が表示されます。

## 起動確認

```bash
docker compose ps
docker compose logs seed
```

`seed` は正常終了し、常駐サービスはhealthyまたはrunningになります。

## 停止と再ビルド

```bash
docker compose down
docker compose up -d --build
```

通常の `down` はnamed volumeを保持します。`--volumes` はForgejoのリポジトリ・ユーザー・token・agent metricsを意図的に削除するときだけ追加してください。

## 次に読むページ

- [アーキテクチャ](./architecture.md)
- [Docker Spaceの公開](./spaces.md)
- [NyankoFace Pages](./pages.md)
- [運用とセキュリティ](./operations.md)
