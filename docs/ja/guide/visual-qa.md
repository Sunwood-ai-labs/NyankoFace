---
title: 開発エージェント向けVisual QA
type: guide
description: レイアウト、テーマ、操作、レスポンシブ状態をスクリーンショット証跡で検証します。
readingTime: 12分
tags: [visual-qa, playwright, テーマ]
related:
  - title: エージェント運用
    link: /ja/wiki/agent-operations
  - title: トラブルシューティング
    link: /ja/guide/troubleshooting
---

# 開発エージェント向けVisual QA

NyankoFaceでは、スクリーンショットを自動判定ではなく手動確認の証跡として扱います。Visual QAは、実際のDocker Compose環境またはデプロイ先に対してローカルで実行します。画像を生成するだけでは見た目の正しさを証明できず、pushごとに網羅的なmatrixをbuild・保存するコストも大きいため、GitHub Actionsからは除外しています。

CIはbuild、lint、unit／integration test、設定、ドキュメントなどの再現可能な検証を担当します。UI変更は、対象を絞ったブラウザ監査を実行し、生成画像を人が開いて確認して初めて完了です。

## ローカル確認パケットの内容

スクリプトは `visual-tests/artifacts/` に次を出力します。

| パス | 用途 |
|---|---|
| `AGENT_REVIEW.md` | 画面ごとの確認観点を含む、人間／エージェント向け画像一覧 |
| `manifest.json` | URL、遷移先、viewport、HTTP状態、title、見出し、横はみ出し、ブラウザエラー、失敗request、自動検出結果 |
| `screenshots/*.png` | デスクトップ／モバイルの全ページ画像 |
| `diagnostics/` | 失敗時を含むCompose状態とログ |

生成artifactはGitに含めません。撮影対象の定義は `visual-tests/routes.mjs` でバージョン管理します。

## エージェントの確認手順

1. 対象commitと環境を起動します。
2. 対象を絞ったVisual QAをローカル実行します。
3. `AGENT_REVIEW.md` を読み、対象範囲の画像をすべて開きます。
4. 指定された観点に沿って、切れ、ぼやけ、重なり、asset欠損、誤遷移、古いruntime状態、誤解を招くlabel、spacing不整合、mobile崩れを確認します。
5. `manifest.json` で、画像上の問題とHTTP失敗、console error、request失敗、横はみ出し量を対応付けます。
6. 問題ごとに画像ファイル名、目視できる根拠、期待結果、影響componentを記載します。

HTTP 200やmanifestのPASSだけでUIタスクを完了にしてはいけません。必ずPNGを目視します。

## ローカル実行

NyankoFaceを起動してから実行します。

```bash
npm ci --prefix visual-tests
npm exec --prefix visual-tests -- playwright install chromium
npm run capture --prefix visual-tests
npm run capture:themes --prefix visual-tests
npm run capture:scroll --prefix visual-tests
```

`capture:themes` は30ルートを3テーマ・PC／モバイルで描画し、180枚の全ページ画像を作ります。`capture:scroll` は同じルートの上・中・下に加え、遅れて描画される Dataset Viewer、Inference Providers、両組織の Team members へ直接スクロールし、564枚のviewport画像と66枚のcontact sheetを作ります。

出力先は `visual-tests/artifacts/` です。部分実行もできます。

```powershell
$env:VISUAL_QA_ROUTES = 'spaces,space-app'
$env:VISUAL_QA_VIEWPORTS = 'desktop'
npm run capture --prefix visual-tests
```

## 対象画面を増やす

新しいuser-facing route、または見た目が大きく異なる状態を追加したら、`visual-tests/routes.mjs` に登録します。詳細画面には安定したシードrepositoryを使い、次のエージェントが画像の目的を判断できる具体的な `focus` を書いてください。

スクリプトは、遷移失敗、HTTP error、repository not found、未処理page error、横はみ出し、埋め込みapp停止、Space runtime表示の矛盾、Cyberpunk内に残った大きな明色surfaceをFAILにします。これらは計測可能な回帰を検出しますが、画像の目視確認を代替しません。console errorと失敗requestは、単独でFAILにしない場合も確認情報として保存します。
