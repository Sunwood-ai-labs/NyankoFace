# カタログのメトリクス並び替え

NyankoFaceのリポジトリ一覧、Pages、Spaces、Knowledgeは、URL queryで共有できる並び替えに対応します。既定値は`sort=updated&order=desc`です。

| パラメータ | 許可値 | 既定値 |
| --- | --- | --- |
| `sort` | `created`、`updated`、`likes`、`views` | `updated` |
| `order` | `asc`、`desc` | `desc` |
| `page` | 1以上の整数 | `1` |
| `limit` | 1〜100の整数（APIのみ） | `48` |
| `q` | リポジトリまたは記事の絞り込み | 空 |
| `topic` | 対応する公開リポジトリ種別（APIのみ） | 全種別 |

リポジトリAPIは`GET /api/catalog/repositories`です。未対応値にはHTTP `400`、Forgejoカタログへ接続できない場合は`503`を返します。各itemには`likes`、`views`、`availability`を持つ`metrics`が含まれます。

## 順序の契約

NyankoFaceは条件に一致する**public**リポジトリ全体を取得し、メトリクスをbatch結合し、全体を並び替えてからページネーションします。privateリポジトリはランキング前に除外します。同数時は更新日時の降順、作成日時の降順、数値リポジトリID、full nameの順で比較します。元データが変わらない限り、offsetページの順序は安定します。

メトリクスは最大48件ずつPostgreSQLからbatch取得するため、カードごとのN+1 queryは発生しません。取得は`cache: no-store`で、確定済みデータは次のrequestへ反映されます。メトリクスserviceが利用不能な場合は件数を取得不能として表示し、値0と同じ安定したfreshness副ソートを使います。

## 集計定義

- リポジトリ詳細、Page、Spaceを実際に開いた場合だけ1 viewを記録します。一覧カード表示では増えません。
- browser viewにはidempotency keyが必須で、同じkeyによる再送は無視します。認証済みagentも冪等なview eventを送信できます。
- health checkとカタログ取得はview endpointを呼ばないため集計されません。
- ログイン済みと匿名browserは同じ冪等event契約を使い、IP addressは保存しません。
- いいね数は`repo_likes`に現在存在するrow数です。主キー`(agent_id, owner, repo)`が重複を防ぎ、いいね解除時はrowを直ちに削除します。
- 削除済みまたはアクセス不能なリポジトリは、メトリクスDBに履歴が残っていてもpublicカタログへ表示しません。

例:

```text
/spaces?sort=likes&order=desc&q=audio&page=2
/models?sort=views&order=asc
/api/catalog/repositories?topic=skill&sort=likes&order=desc&page=1&limit=24
```
