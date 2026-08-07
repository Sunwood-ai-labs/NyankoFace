---
title: NyankoFace Pages
type: guide
description: publicなForgejoリポジトリから静的HTMLと生成済みドキュメントを公開する正式手順です。
readingTime: 12分
tags: [pages, vitepress, actions, static-site]
related:
  - title: ランタイムモデル
    link: /ja/wiki/runtime
  - title: Docker Spaces
    link: /ja/guide/spaces
  - title: トラブルシューティング
    link: /ja/guide/troubleshooting
---

# NyankoFace Pages

このページがNyankoFace Pagesのcanonicalな公開手順です。Pagesは **public**
Forgejoリポジトリにあるbuild済み静的ファイルを配信します。サーバー処理は
実行せず、`pages` repository topicも必要ありません。

## どの公開面を選ぶか

| 目的 | 選択 |
| --- | --- |
| 静的HTML/CSS/JavaScript、VitePress、Astro、static export | **Pages** |
| Gradio、Next.js SSR、Streamlit、FastAPI、Node.jsなど常駐プロセス | **Docker Space** |
| NyankoFaceのナレッジ一覧へ載せるMarkdown記事 | **Knowledge** |

PagesはModel、Dataset、Skillなどのカタログリポジトリと併用できます。
repository topicはカタログ分類に使い、Pagesは配信元のファイル契約だけで
有効になります。

## 検出仕様

NyankoFaceはリポジトリ詳細を開くたび、次の順で確認します。

1. `gh-pages` branchのルートにある `index.html`
2. default branchにある `docs/index.html`

最初に存在したファイルを採用します。`index.html`のない`gh-pages` branchは
deploy済みとみなしません。private repositoryは決して公開しません。

公開URL:

```text
https://HOST/pages/OWNER/REPOSITORY/
```

静的サイトジェネレーターのbase path:

```text
/pages/OWNER/REPOSITORY/
```

## どちらの配信元を選ぶか

| 配信元 | 適する場合 | 特徴 |
| --- | --- | --- |
| `gh-pages` | buildでHTML/CSS/JSを生成する、sourceと成果物を分離したい | VitePressやCIに推奨。branch全体をdeployで置換できる |
| default branchの`docs/` | commitするファイルがそのまま完成済み静的サイト | 最小のGit運用。sourceと公開成果物を同じbranchで管理 |

両方を置くときは、常に`gh-pages`が優先される点に注意してください。

## NyankoFace画面からデプロイする

`/pages`を開いて **新しいPagesをデプロイ** を選ぶか、未設定のpublic
repositoryで **Pagesとして公開する** を押します。このウィザードはSpaceを起動せず、
`pages` topicも要求しません。

1. publicな`OWNER/REPOSITORY`を入力または選択
2. 公開条件を確認
3. `gh-pages`、default branchの`docs/`、VitePress + Forgejo Actionsから選択
4. NyankoFaceが作成または置換するbranchとfile pathを確認
5. 変更に同意してdeploy
6. logと各commit SHAを確認
7. **サイトを見る** を開く。VitePress build中はActions logを開く

deploy APIはForgejoへログイン済みで、対象repositoryへのwrite権限を持つuserだけが
実行できます。書き込み前にpublic設定を再確認します。private repository、権限不足、
file書き込み失敗、Pages検出失敗を成功扱いにはせず、理由をerrorとして表示します。

## 最小の静的サイトを公開する

cleanなworking treeから始めます。remoteは実際のForgejo URLを使ってください。

```bash
git switch --orphan gh-pages
git rm -rf .
cat > index.html <<'HTML'
<!doctype html>
<html lang="ja">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Hello from NyankoFace Pages</title>
  </head>
  <body><h1>Hello from NyankoFace Pages</h1></body>
</html>
HTML
git add index.html
git commit -m "docs: publish NyankoFace Pages site"
git push --force-with-lease origin gh-pages
```

`docs/`方式はdefault branchのまま`docs/index.html`を追加し、通常どおりcommit・
pushします。

## VitePressなどbuildが必要なサイト

リポジトリ固有のbase pathを設定します。

```ts
// docs/.vitepress/config.mts
import { defineConfig } from 'vitepress'

export default defineConfig({
  base: process.env.VITEPRESS_BASE ?? '/',
})
```

seedされる`nyankoface/vitepress-pages-starter`には、動作確認済みのForgejo
Actions workflowがあります。要点は次のとおりです。

```yaml
name: Publish VitePress to NyankoFace Pages
on:
  push:
    branches: [main]
    paths: ['docs/**', 'package.json', 'package-lock.json']
  workflow_dispatch:

jobs:
  publish:
    runs-on: node20
    steps:
      - uses: https://data.forgejo.org/actions/checkout@v4
      - run: npm install --no-audit --no-fund
      - run: VITEPRESS_BASE="/pages/${GITHUB_REPOSITORY}/" npm run docs:build
      - name: Publish built output
        env:
          PAGES_TOKEN: ${{ github.token }}
        run: |
          git config user.name "NyankoFace Pages"
          git config user.email "pages@nyankoface.local"
          git checkout --orphan gh-pages
          git rm -rf .
          cp -R docs/.vitepress/dist/. .
          touch .nojekyll
          git add --all
          git commit -m "Publish Pages for ${GITHUB_SHA}"
          git remote set-url origin "http://oauth2:${PAGES_TOKEN}@forgejo:3000/${GITHUB_REPOSITORY}.git"
          git push --force origin gh-pages
```

`gh-pages`にはbuild後の成果物だけを置きます。VitePressのproject sourceを
そのままdeploy済みサイトとしてpushしないでください。

## 公開確認

pushのたびに次を確認します。

1. repository詳細を開く
2. sidebarの **NyankoFace Pages** cardを探す
3. **公開中** と期待した配信元が表示されることを確認
4. **サイトを見る** を開く
5. root page、CSS／JavaScript／画像のいずれか1asset、1つのnested routeを確認
6. 公開URLのcopy buttonを確認

Navigator Skillにはlive checkerも含まれます。

```bash
python skills/nyankoface-navigator/scripts/verify_pages.py \
  https://HOST/pages/OWNER/REPOSITORY/ \
  --asset assets/app.css \
  --nested guide/
```

runnerとfrontendはrepository cardの検出結果をcacheしないため、新しいpushは
次のpage loadで反映されます。

## 更新・削除・非公開化

- **更新:** 現在の配信元へ新しいbuild成果物をpushし、repository pageと公開URLをreload
- **配信元変更:** `docs/`を使う前に`gh-pages` branchを削除
- **削除:** `gh-pages` branchを削除し、`docs/index.html`も削除
- **非公開化:** Forgejo repositoryをprivateへ変更。NyankoFaceは`404`を返し、
  Pages assetを公開しない

## トラブルシューティング

| 症状 | 確認箇所 |
| --- | --- |
| Pages cardが **未設定** | `gh-pages/index.html`か`<default>/docs/index.html`を追加。cardに両方の確認結果が出る |
| 公開URLが`404` | public設定、owner/repositoryの大小文字、branch、`index.html` |
| CSS／JS／画像が崩れる | `/pages/OWNER/REPOSITORY/`をbaseにbuildし、relativeまたはbase-aware URLを使う |
| nested routeが`404` | `guide/index.html`など実ファイルを作る。server-side rewriteは動かない |
| 別の配信元が表示される | `gh-pages`が常に優先。`docs/`を使うならbranchを削除 |
| cardが **確認できません** | ForgejoまたはPages runnerのhealthを確認してreload |
| link previewが不足 | `<title>`、Open Graph、Twitter card、取得可能なpreview imageを追加 |

## 共有用メタデータ

NyankoFaceはrepositoryで指定した値を保持し、不足している`<title>`、Open
Graph、Twitter cardだけを補完します。relativeなpreview image pathは公開Pages
URLを基準にabsolute URLへ変換します。

```html
<title>人が読めるページタイトル</title>
<meta property="og:title" content="人が読めるページタイトル">
<meta property="og:description" content="短い説明">
<meta property="og:image" content="./social-card.png">
<meta name="twitter:card" content="summary_large_image">
```
