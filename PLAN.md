# NyankoFace — セルフホスト版 HuggingFace プラットフォーム設計書

計画: Claude Fable 5 / 実装: Claude Sonnet 5

## コンセプト

Forgejo を Git+LFS ストレージ基盤とし、公式カスタマイズ機構（テンプレート/アセット上書き）を焼き込んだ**改造版 Forgejo イメージ**と、HuggingFace 風の **Next.js フロントエンド**を組み合わせる。`docker compose up -d` 一発で起動。

## サービス構成 (docker-compose)

| サービス | 役割 | イメージ | 内部ポート |
|---|---|---|---|
| `gateway` | nginx リバースプロキシ（唯一の公開口 `:8090`） | nginx:alpine | 80 |
| `frontend` | HF風ポータル (Next.js + Tailwind) | ./frontend | 3000 |
| `forgejo` | 改造版 Forgejo (Git + LFS + API + 認証) | ./forgejo (FROM codeberg.org/forgejo/forgejo:9) | 3000 (http), 22 (ssh→host 2222) |
| `spaces-runner` | Gradio アプリの起動・プロキシ (FastAPI + docker sdk) | ./spaces-runner | 8000 |
| `seed` | 初回起動時に admin/サンプルrepo作成 (one-shot) | ./seed | - |

### ルーティング (gateway :8090)

- `/` , `/models`, `/datasets`, `/spaces`, `/:owner/:repo/*` → `frontend:3000`
- `/git/` → `forgejo:3000` （clone URL: `http://localhost:8090/git/<owner>/<repo>.git`、Forgejo UI/管理画面もここ）
- `/run/` → `spaces-runner:8000` （起動中 Space への WebSocket 対応プロキシ）
- `/runner-api/` → `spaces-runner:8000/api/`

## データモデル

- リポジトリ種別は Forgejo の **topics** で分類: `model` / `dataset` / `space`
- モデルカード / データセットカード = リポジトリ直下 `README.md`（HF互換の YAML frontmatter: `license`, `tags`, `pipeline_tag`, `language` 等）。frontend が frontmatter をパースしてバッジ表示、本文を Markdown レンダリング
- 大容量ファイルは Git LFS（Forgejo 組み込み LFS サーバー、`LFS_START_SERVER=true`）
- Space リポジトリ規約: `app.py` + `requirements.txt`（Gradio）。`Dockerfile` があればそれを優先ビルド

## 改造版 Forgejo (forgejo/)

フォークではなく公式 custom ディレクトリ機構を Dockerfile で焼き込む:

- `custom/templates/custom/header.tmpl` ほか — NyankoFace ブランディング注入、frontend への導線
- `custom/public/assets/img/logo.svg` 等 — ロゴ差し替え
- `custom/public/assets/css/nyankoface.css` — HF風配色（黄色アクセント #FFD21E 系）
- `app.ini` は環境変数 (`FORGEJO__section__KEY`) で compose から設定: LFS有効、`ROOT_URL=http://localhost:8090/git/`、登録開放は `.env` で制御

## frontend (Next.js 14+ App Router + Tailwind)

サーバーサイドから `http://forgejo:3000/api/v1` を叩く（token は seed が生成し共有ボリューム or env 経由で注入）。

ページ:

- `/` — ヒーロー + 新着モデル/データセット/Spaces カードグリッド
- `/models`, `/datasets`, `/spaces` — 一覧（topic検索 `q=&topic=`）、検索ボックス、タグフィルタ、ソート（更新順/スター順）
- `/[owner]/[repo]` — 詳細: カード（README + frontmatter バッジ）/ Files タブ（ツリー閲覧・LFSポインタ検出してDLリンク）/ clone コマンド表示。Space の場合は「▶ Run」ボタン + 埋め込み iframe (`/run/{owner}/{repo}/`)
- `/new` — リポジトリ作成ガイド（Forgejo の作成画面 `/git/repo/create` へ誘導 + topic 設定手順）

UIUX: HF 風 — 白基調、黄色アクセント、カード型グリッド、絵文字アイコン、`pipeline_tag` バッジ色分け。ダークモード対応。

## spaces-runner (FastAPI)

- `POST /api/spaces/{owner}/{repo}/start` — repo を clone → イメージビルド（gradio ベース）→ コンテナ起動（`docker.sock` マウント経由、compose ネットワークに接続、ラベルで管理）
- `GET /api/spaces/{owner}/{repo}/status`, `POST .../stop`
- `/{owner}/{repo}/{path}` — 起動中コンテナ (port 7860) へ httpx/websocket リバースプロキシ
- アイドルタイムアウトで自動停止（既定30分）

## seed (one-shot)

1. Forgejo の healthcheck 待ち
2. admin ユーザー作成（`.env` の `NYANKOFACE_ADMIN_*`）、API token 発行 → 共有ボリューム `/shared/token` へ
3. サンプル作成: `nyankoface/sample-model`（topic: model, README frontmatter付き）、`nyankoface/sample-dataset`（CSV付き）、`nyankoface/hello-space`（gradio app.py）

## リポジトリ構成

```
NyankoFace/
├── docker-compose.yml
├── .env.example
├── README.md            # セットアップ・使い方（日本語）
├── PLAN.md              # 本書
├── gateway/nginx.conf
├── forgejo/             # Dockerfile + custom/ (templates, assets)
├── frontend/            # Next.js アプリ
├── spaces-runner/       # FastAPI + Dockerfile
└── seed/                # seed.sh + Dockerfile
```

## 実装フェーズ（Sonnet 5 サブエージェント）

1. **infra**: compose / gateway / forgejo / seed — 契約（ポート・パス・env名）は本書に固定
2. **frontend**: 上記ページ一式（infra 完了後、並行可）
3. **spaces-runner + README**: ランナーと利用ドキュメント（並行可）
4. **検証**: `docker compose config`、frontend ビルド、契約整合チェック

## 固定契約（全エージェント遵守）

- env: `NYANKOFACE_ADMIN_USER/PASSWORD`, `FORGEJO_TOKEN_FILE=/shared/token`, `FORGEJO_API=http://forgejo:3000/api/v1`, `PUBLIC_BASE_URL=http://localhost:8090`
- topics: `model` / `dataset` / `space`（これで種別判定）
- 共有ボリューム名: `shared-token`, `forgejo-data`
- ネットワーク名: `nyankoface`
