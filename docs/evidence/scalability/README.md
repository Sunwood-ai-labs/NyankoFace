# Spaces scalability verification evidence

このディレクトリには、Spaces一覧のスケーラビリティ改善を実際のNyankoFace環境で検証した証拠を保存しています。検証用リポジトリは撮影後に削除し、最終状態は24件すべてRunningへ復元しています。

## 1. 48件ページング

| 1ページ目（48件） | 2ページ目（49–54件） |
|---|---|
| ![48 Spaces on page one](01-pagination-page-1.png) | ![Six Spaces on page two](01-pagination-page-2.png) |

- URL: `/spaces`、`/spaces?page=2`
- 実測: 1ページ目48件、2ページ目6件、合計54件
- 前へ／次へ、現在ページ、表示範囲を確認

## 2. メトリクス・Docker状態の一括取得

![Cards rendered from batched metrics and status data](02-batched-card-data.png)

- [リクエスト数の記録](02-batched-requests.txt)
- メトリクス一括API: 1回
- `/runner-api/spaces`: 1回
- カード単位のメトリクス・状態API: 0回

## 3. READMEの5分キャッシュ

![Emoji metadata remains visible with the README cache](03-readme-cache.png)

- [コールド／ウォーム取得の記録](03-readme-cache.txt)
- コールド表示: README 24件取得
- TTL内の再表示: README取得0件
- ページングにより対象は最大48件

## 4. 24コンテナ上限とOn demand起動

| 起動前 | 詳細を開いて自動起動 |
|---|---|
| ![The 25th Space is marked On demand](04-on-demand-before-start.png) | ![The on-demand Space starts automatically](04-on-demand-auto-start.png) |

![The new Space is running while the least recently used Space becomes On demand](04-lru-after-start.png)

- [同時起動数とLRU停止の記録](04-running-capacity.txt)
- 起動前: 24 Running + 1 On demand
- 25件目を開いた後: Runningは24のまま
- 最終アクセスが最古の1件だけを停止

## 5. 最終回帰確認

| 復元後の一覧 | 既存React Space |
|---|---|
| ![All original 24 Spaces are running](05-final-spaces.png) | ![Existing React Space still runs](05-react-regression.png) |

- 最終状態: 24リポジトリ、24 Running
- 既存のDocker Space埋め込み、閲覧数、ナビゲーションを確認
