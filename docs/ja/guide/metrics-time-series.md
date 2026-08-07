---
title: 実測メトリクスと時系列アクティビティ
type: guide
description: NyankoFaceの閲覧・ダウンロード・いいねと、実測アクティビティグラフを支えるイベント契約。
readingTime: 8分
tags: [metrics, downloads, analytics, postgres]
related:
  - title: カタログのメトリクス並び替え
    link: /ja/guide/catalog-metric-sorting
  - title: Upgradeとdata retention
    link: /ja/guide/upgrading
---

# 実測メトリクスと時系列アクティビティ

repository detail pageの**実測アクティビティ**panelは、PostgreSQLの
`nyankoface_metrics.metric_events` ledgerを参照します。demo系列、click数、乱数、
推測値は使いません。panelはpublic repositoryのdetail、file、Space surfaceに表示し、
download契約はAutomation bundleにも適用します。

## Event contract

各eventは集計・監査に必要なfieldだけを保存します。

| Field | 値・意味 |
| --- | --- |
| `event_type` | `view`、`download`、`like` |
| `source` | `browser`、`agent`、`raw`、`lfs`、`automation` |
| target | repository owner/nameと、任意のrepository-relative artifact path |
| `actor_kind` | `anonymous`、`authenticated`、`agent`、`system` |
| `outcome` | `success`、`failed`、`cancelled`、`denied`、`bot`、`health_check` |
| `value` | successful view/downloadは`1`、like変更は`+1`または`-1`、非集計outcomeは`0` |
| deduplication | sourceが提供するoperation単位のidempotency key |
| time | UTCの`created_at` timestamp |

IP address、bearer token、Forgejo PAT、cookie value、secretは保存しません。
`actor_kind`は粗い分類であり、identityやpermission grantではありません。

## 何を数えるか

- repository detail、Page、Spaceを実際に開いた場合に、browserまたはagentの
  successful eventを1件記録します。detail pageはpage-load idempotency keyを使うため、
  Reactの再mountやretryで増えません。catalog cardとhealth checkはview endpointを呼びません。
- likeはagentのactive stateです。successfulな`+1`で増え、`-1`で減ります。`repo_likes`の
  primary keyとevent ledgerでretryを冪等にします。
- downloadは、publicなRaw file、解決済みLFS object、検査済みAutomation bundleの
  NyankoFace proxy response bodyが最後まで送信できた場合だけ数えます。buttonのclickだけでは
  記録しません。直接Forgejoの**Raw** navigation linkはpreviewであり、測定downloadではありません。
- failed、cancelled、denied、bot、health-check outcomeは診断用にledgerへ残る場合がありますが、
  `value=0`で、実測totalには入りません。public download pathはhealth checkをuser downloadに分類せず、
  proxy前にprivate repositoryを拒否します。

同じsuccessful event setを累計cardと時系列の両方で使います。`raw`、`lfs`、`automation`は
deliveryの意味が異なるため、download内訳を分けて表示します。

## API contract

public metricsはrunner gatewayの下で取得できます。

```http
GET /runner-api/metrics/repos/{owner}/{repo}
GET /runner-api/metrics/repos/{owner}/{repo}/timeseries?from=2026-08-01T00:00:00Z&to=2026-09-01T00:00:00Z&bucket=day&timezone=UTC
```

時系列windowは`[from, to)`です。boundを省略すると直近30日から現在のUTC時刻までになります。
最大windowは366日です。`bucket`は`day`、`week`、`month`、`timezone`は`UTC`や`Asia/Tokyo`の
IANA timezoneを受け付けます。bucket labelは指定timezoneで返します。

responseには次が含まれます。

- `series[]`: `bucket_start`、`views`、`downloads`、activeな`likes`、like delta、
  `downloads_by_source`;
- `totals`: period views/downloads、`to`時点のactive like、sourceごとのtotal;
- `data_state`: 実測eventがある`data`、実測eventがない`no_data`;
- 指定timezone、`updated_at`、`generated_at`、responseのdefinition。

`no_data`は、eventが存在する期間内の確定した0件とは別です。metrics serviceやrepositoryが
利用できない場合、UIは`unavailable`を表示し、0へ置き換えません。

download recorderはfrontend proxyからだけ呼び出すinternal contractです。
browserから直接呼び出さず、frontend control tokenを送信します。

```http
POST /runner-api/metrics/repos/{owner}/{repo}/downloads
Content-Type: application/json
X-NyankoFace-Control-Token: <frontend-control-token>

{
  "source": "raw",
  "artifact_path": "weights/model.bin",
  "idempotency_key": "one-browser-download-operation",
  "outcome": "success"
}
```

3つのdownload sourceと上記6つのoutcomeを受け付けます。private repositoryは他のpublic
surfaceと同じnot-found boundaryで返します。

## Storage・migration・retention

ledgerにはtarget/timeとevent-type/sourceのindex、non-null idempotency keyのpartial unique
indexがあります。runnerのPostgreSQL startup initializationで作成します。既存の
`repo_views`、`browser_views`、activeな`repo_likes`は安定した`legacy:*` keyでbackfillし、
startupを繰り返しても重複しません。新しいwriteはlegacy compatibility tableとcanonical ledgerを
同じPostgreSQL transactionで更新します。

このreleaseはhistoryを推測せず、`metric_events`を自動pruneもしません。そのためdeploymentの
`nyankoface_metrics` backupとdatabase retention policyがretention boundaryになります。operatorは
database dumpとrestore evidenceを一緒に保持します。APIの366日制限はquery safety boundであり、
削除policyではありません。将来purgeや再集計を行う場合は、active like stateを保持し、変更前後の
件数を記録するreview済みmaintenance migrationにしてください。

download eventはresponse streamが完了した時点でaggregation対象になるため、直後のgraphは
次のrequestまで遅れることがあります。`updated_at`と`generated_at`で遅延を確認できます。同じ
ledgerに同じwindow、bucket、timezoneを指定した再集計はdeterministicです。

## UIとQA

detail panelには次を表示します。

- 実測views、downloads、active likesの累計;
- Raw/LFS/Automationのdownload内訳;
- exact point tooltip付きSVG trend graph;
- period、value、unit、集計timezoneを確認できる展開table;
- loading、unavailable、no-dataを混同しないstate。

release時はpublic repositoryとtest Automation/file fixtureで次を確認します。

1. desktopとmobileでrepository detailを開き、page-load viewが一度だけ記録されることを確認する。
2. Raw、LFS、Automationを各1件最後までdownloadし、response status、`metric_events` row、
   cumulative API、時系列bucket、source内訳、UI tooltip/tableを突き合わせる。
3. 同じoperation keyで再送し、denied、failed、cancelled、bot、health-check outcomeも確認する。
   successful eventだけが実測totalに入ることを確認する。
4. anonymous session、login済みbrowser、認証済みagentで繰り返し、変わるのが粗い
   `actor_kind`だけで、private dataが保存されないことを確認する。
5. period boundary、`Asia/Tokyo`、empty period、long period、metrics service failureを試し、
   480pxでpage全体のhorizontal overflowが発生しないことを確認する。

Visual captureは`docs/evidence/issues/175/`に保存します。手動runtime evidenceはCI gateにしません。
