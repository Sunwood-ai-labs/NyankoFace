# Theme verification evidence

実行環境: `https://localhost:8443/`（Docker Compose の gateway 経由）

> 最新の網羅監査は [2026-07-19 全テーマ・全ページ コントラスト監査](../visual-qa/2026-07-19-theme-contrast-audit.md) を参照してください。3テーマ × OS light/dark × desktop/mobile × 32ルートの384枚すべてが合格し、20,196個の可視テキストを計算、48枚の contact sheet を目視確認しています。

## スクロール途中のCyberpunk回帰確認

全登録ページを上・中・下で撮影し、遅れて表示される Dataset Viewer、Inference Providers、Team members には直接スクロールする監査を追加しました。以下は修正後のモバイル原寸証跡です。

| Dataset Viewer | Inference Providers | Organization team | Authentication form |
|---|---|---|---|
| ![Cyberpunk Dataset Viewer](cyberpunk-dataset-viewer-mobile.png) | ![Cyberpunk Inference Providers](cyberpunk-inference-providers-mobile.png) | ![Generated NyankoFace organization identity and team](cyberpunk-organization-team-mobile.png) | ![Cyberpunk login form](cyberpunk-login-mobile.png) |

## 操作確認

ヘッダー右上の `NyankoFace theme` セレクタを実際に操作して、各状態で次の値が一致することを確認しました。

| 選択 | `data-nyankoface-theme` | `localStorage.nyankoface-theme` | セレクタ値 |
|---|---|---|---|
| Standard | 属性なし（`standard`） | `standard` | `standard` |
| Solarpunk | `solarpunk` | `solarpunk` | `solarpunk` |
| Cyberpunk | `cyberpunk` | `cyberpunk` | `cyberpunk` |

その後、同じブラウザプロファイルでページを再読込しても選択したテーマが表示されることを確認しました。テーマ値を読むインラインスクリプトをレイアウトの先頭に置いているため、初期描画で標準テーマが一瞬表示されることを避けています。

## 実画面

| Standard | Solarpunk | Cyberpunk |
|---|---|---|
| ![Standard theme](standard-home.png) | ![Solarpunk theme](solarpunk-home.png) | ![Cyberpunk theme](cyberpunk-home.png) |

Solarpunk は温かい紙面、植物の緑、日光の黄を使います。Cyberpunk は濃いインク面、シアンのグリッド、マゼンタの光を使い、一覧カードも暗色パネルへ揃えて可読性を保ちます。

## ルート横断の画面監査

1440×1000 の実ブラウザ画面で、Standard / Solarpunk / Cyberpunk の各テーマを選択し、以下の全ルートを個別にレンダリングして確認しました。背景、見出し、カード、境界線、補助テキスト、フィルター、ボタン、フォーム、詳細サイドバー、Spaceランナー外枠を確認対象にしています。

| 画面 | ルート | 結果 |
|---|---|---|
| ホーム | `/` | 3テーマで確認済み |
| モデル一覧 | `/models` | 3テーマで確認済み |
| データセット一覧 | `/datasets` | 3テーマで確認済み |
| Spaces一覧 | `/spaces` | 3テーマで確認済み |
| Skills一覧 | `/skills` | 3テーマで確認済み |
| MCPs一覧 | `/mcps` | 3テーマで確認済み |
| Prompts一覧 | `/prompts` | 3テーマで確認済み |
| 新規リポジトリ作成 | `/new` | 3テーマで確認済み（Cyberpunkフォームを修正） |
| Space詳細 / ランナー | `/seraphim-labs/qr-code-generator` | 3テーマで確認済み |
| データセット詳細 | `/nyankoface/table-question-answering` | 3テーマで確認済み |

監査中に見つかった唯一の破綻は、Cyberpunkの新規作成画面でネイティブ入力欄が白い背景のまま残る点でした。`input` / `textarea` / `select` の面、プレースホルダ、ラジオ・チェックボックスをテーマ化し、修正後に再撮影して確認しました。

![修正後のCyberpunk新規作成画面](cyberpunk-create-space.png)
