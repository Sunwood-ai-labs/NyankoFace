# ページ遷移のパフォーマンス

NyankoFace は内部リンクを押した直後にフィードバックを表示し、ページ種別に合ったスケルトンを描画します。計測にはURLやユーザーデータを保存せず、正規化した遷移種別だけを使います。

## 実行時の動作

- 内部リンクは全画面リロードではなく Next.js のクライアント遷移を使います。
- 進捗ラインと押下状態を即時表示し、遷移完了まで重複操作を抑止します。
- 15秒を超えた場合は再試行を表示します。戻る／進むと reduced-motion にも対応します。
- 公開ナレッジのメタデータだけを `KNOWLEDGE_CACHE_TTL_SECONDS`（既定60秒）でプロセス内キャッシュし、同時取得をまとめます。非公開または認証付きのリポジトリ内容はキャッシュしません。

## 計測

`GET /api/performance/navigation` は遷移種別ごとの件数と p50／p95 を返します。`POST` は遷移種別、所要時間、フィードバック遅延、結果、画面幅区分、キャッシュ状態だけを受け付け、パスや任意メタデータを拒否します。取り込みにはブラウザの same-origin fetch metadata も必要で、gateway のクライアントアドレスごとに1分30件へ制限し、直接クライアントが有限の観測枠を自由に置き換えないようにしています。メモリ上のレート制限は有効なクライアント記録を最大4,096件だけ保持し、新規クライアントを拒否する前に期限切れの記録を削除します。

`NYANKOFACE_PERFORMANCE_LOG=1` で API、DB、Forgejo、Markdown のサーバー処理時間を構造化ログに出力できます。調査時以外は無効のままにしてください。

見た目は実ブラウザで手動確認します。CIは型、計測値の検証、プロダクションビルドを担当し、描画結果を確認できたとは扱いません。

## Spaceの遷移とruntime準備状態

Space詳細ページはruntime APIの完了を待たず、リポジトリ名や操作領域を先に描画します。runtimeバッジとアプリ領域は同じクライアント側providerを共有するため、詳細表示だけでstatus pollが重複しません。Spaceリポジトリでは、モデル／データセット向けのPagesソース調査も省略します。

runtime状態は `checking`、`queued`、`leased`、`building`、`starting`、`warming`、`running`、`stopping`、`stopped`、`offline`、`unavailable`、`failed`、`error` に正規化して表示します。遷移中は2秒、runningは10秒、stoppedは15秒間隔でpollし、それ以外の終端状態は次の確認まで20秒待ちます。status requestは8秒でtimeoutし、別ページへ移動した場合は未完了requestを中断します。

埋め込みアプリはruntimeが `running` になった後、ページ本体とは独立して読み込みます。iframeを配置する前に `/run/` を750ミリ秒間隔でprobeし、`space is not running` などの一時的なgateway応答を無視します。既存の20秒の準備上限はprobeとiframe読込の両方に適用され、時間切れでは古いJSONエラー画面や無限loadingを残さず再試行操作を表示します。Start／Stop中は現在の操作を表示して競合するcontrolを無効化し、runnerの応答後に共有statusをすぐ更新します。

手動QAと診断では、アプリ領域の `data-runtime-phase`、`data-runtime-request-ms`、`data-iframe-phase`、`data-iframe-duration-ms` で状態と所要時間を確認できます。`NYANKOFACE_PERFORMANCE_LOG=1` の場合は詳細routeのserver phase timingも記録します。CPU／GPU／external Spaceは実際の配備環境で確認し、ブラウザcaptureは引き続き手動のrelease checkとして扱います。

実配備に対する匿名desktop／mobileの集中監査は次で実行します。

```bash
VISUAL_QA_BASE_URL=http://localhost:8090 \
PUBLIC_SPACE_REPO=sample-vue \
npm run audit:public-space --prefix visual-tests
```

遷移速度を変更前後で再現可能に比較する場合は、2つのfrontend revisionを別originで起動して次を実行します。

```bash
BASELINE_URL=http://localhost:3102 \
CANDIDATE_URL=http://localhost:3103 \
SPACE_NAV_TARGET=/seraphim-labs/sample-vue \
SPACE_NAV_SAMPLES=10 \
npm run benchmark:space-navigation --prefix visual-tests
```

#103のlocal検証ではrevisionごとにcold／warmを各10回計測しました。変更前から変更後へのp50はcoldで358 msから67 ms、warmで359 msから67 msになりました。cold p95は372 msから358 msになり、変更後にも約360 msのoutlierが時折残ったためwarm p95は368 msのままでした。そのoutlierを含めても変更後の即時feedback p95はcold 26 ms、warm 28 msで、100 msの受け入れ基準を満たしました。この数値は記録したlocal環境の結果であり、すべてのproduction環境に対する保証ではありません。
