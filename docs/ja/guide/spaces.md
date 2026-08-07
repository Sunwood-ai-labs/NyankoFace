---
title: Spaces
type: guide
description: Dockerアプリの埋め込みと既存Webサイトへの直接リンクを公開します。
readingTime: 8分
tags: [spaces, docker, アプリ]
related:
  - title: ランタイムモデル
    link: /ja/wiki/runtime
  - title: DockerをSpace共通契約にする
    link: /ja/articles/docker-spaces
---

# Spaces

Spaceは、`space` topicを持つpublic Forgejoリポジトリです。Dockerアプリを
実行・埋め込みする形式と、指定したWebサイトを直接開くリンク形式を選べます。

## アプリの種類

seedにはGradio、静的HTML、React、Vue、Next.js、Streamlit、FastAPI、Node.jsの例があります。固定allowlistではなく、container化してproxyできるCPU向けWebサーバーなら利用できます。

## カード情報

README frontmatterでタイトル、絵文字、SDK、tagsを指定します。

```yaml
---
title: Local audio utility
emoji: "🎧"
sdk: docker
tags:
  - audio
  - utility
---
```

Forgejo topicの `space` はカタログ種別を決めます。READMEの `tags` はカード内の分類であり、topicの代わりにはなりません。

## リンク型Space

コンテナをbuild・埋め込みせず既存サイトを開く場合は、README
frontmatterの `external_url` に絶対HTTP/HTTPS URLを設定します。

```yaml
---
title: Product documentation
emoji: "🧭"
external_url: https://docs.example.com/
---
```

Spacesカードには **外部サイト** badgeが表示され、クリックするとそのURLへ
直接移動します。通常のリポジトリ詳細URLも同じURLへredirectします。Filesや
設定はForgejoから引き続き参照できます。不正なURLやHTTP/HTTPS以外のschemeは
無視され、通常のDocker Spaceとして扱われます。

seed catalogには動作例として `seraphim-labs/nyankoface-documentation` が含まれます。
シードのCPU Spaceは天使をテーマにした `seraphim-labs` 組織が所有し、
`nyankoface` はプラットフォーム本体の組織として分離しています。

![本番Spaces一覧のリンク型Space](../../evidence/spaces/external-link-space-desktop.png)

[Desktop／mobileのブラウザ検証記録](../../evidence/spaces/README.md)には、カード表示、
直接遷移、redirect response、横overflow確認を保存しています。

## Docker Space

Docker Spaceはroot `Dockerfile`を使います。コンテナはport `7860`でlistenし、
frameworkが対応している場合はNyankoFaceのpath prefixを受け入れます。

## 実行動作

- `IDLE_TIMEOUT_MINUTES=0` ならCPU Spaceを常時起動できます。
- 同時起動数は既定24で、`MAX_RUNNING_SPACES` で変更できます。
- 上限時は最終アクセスが最も古いSpaceを停止してから新しいSpaceを起動します。
- 停止中のpublic Spaceは **On demand** と表示し、未ログインでも起動して利用できます。
- 停止・環境変数・設定は、write権限を持つログイン済みmaintainerだけが操作できます。
- ブラウザ閲覧とagent API操作は同じ永続metrics storeに記録します。

## セキュリティ警告

runnerは `/var/run/docker.sock` をmountします。悪意あるDockerfileはDocker hostを制御できます。全Spaceを確認し、runner hostを破棄可能な隔離環境にしない限り、リポジトリ作成者を信頼できるユーザーに限定してください。
