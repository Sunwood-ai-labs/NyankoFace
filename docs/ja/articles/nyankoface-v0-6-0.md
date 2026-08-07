---
title: 実測するsurfaceと証跡を守る
type: article
description: NyankoFace v0.6.0が、operatorに推測をさせずrepository activityを実測event streamへ変える方法。
readingTime: 7分
tags: [release, metrics, downloads, operations, interface]
---

![NyankoFace v0.6.0リリースヘッダー](/releases/release-header-v0.6.0.svg)

# 実測するsurfaceと証跡を守る

数字を表示していても、その意味をoperatorが説明できるとは限りません。
clickは完了downloadではなく、metrics serviceがないことは確定した0ではありません。
logo探索もproduction decisionではありません。NyankoFace v0.6.0は、その区別を
product surfaceの一部として扱います。

## 1つのledgerから正直な表示へ

このreleaseでは`nyankoface_metrics.metric_events`をcanonical event ledgerにしました。
browser／agentのsuccessful view、完了したRaw／LFS／Automation download、activeなagent likeを
同じaggregation boundaryから読み出せます。repositoryの累計cardと日次graphが別々の
historyを推測する必要はありません。

event contractは小さくしています。event type、source、repository target、粗いactor kind、
outcome、value、利用可能ならoperation key、UTC timeだけを保存します。IP address、bearer token、
Forgejo PAT、cookie、secretは保存しません。failed、denied、cancelled、bot、health-checkは
診断に残っても、実測activityには入りません。

## 境界はcompletion

downloadを見ると、この境界の意味が分かります。button clickは意図を示すだけですが、proxyは
response bodyが完了したRaw file、LFS object、Automation bundleだけを数えます。source別内訳も
残るため、model artifactとAutomation packageを飾りの数字へ平坦化しません。

同じルールでretryも安全になります。sourceがoperation keyを渡す場合、ledgerのunique indexが
再送による重複eventを防ぎます。完了直後のdownloadがgraphへ反映されるのは次のrequestになる
ことがありますが、`updated_at`と`generated_at`で遅延を表示し、推測counterに隠しません。

## emptyはunavailableではない

急いだproductで混同しやすい3つの意味をUIで分けました。実測data、eventがない実測period、
service unavailableです。NyankoFaceは`data`、`no_data`、`unavailable`として返します。時系列APIは
day／week／month bucketとIANA timezoneを受け付けますが、query windowは366日に制限します。
これはquery safety limitであり、retention policyではありません。

ledgerはrunner startupで作成されます。既存のview／like counterは安定したlegacy keyでbackfillし、
旧compatibility tableも残します。初期化は自動かつ冪等ですが、durable dataの変更であることは
変わりません。operatorは`nyankoface_metrics`をbackupし、restore evidenceを保持します。serviceが
historyを暗黙にpruneすることもありません。

## Calm surfaceがevidenceを使える形にする

同じ考え方で、小さなinterface変更も入りました。navigation menuは選択後に閉じるため、前の
contextが次のpageを覆いません。brand auditで共有の名前とidentityを読みやすくし、Space headerは
tablet／mobileでwrapした後の残り領域を測ります。Space identity、tab、metric、runtime controlを
同じ会話の中に置けます。

MCP setupも同じ境界を持ちます。remote endpointは認証済みStreamable HTTPのまま、local stdio
adapterはserver sessionを発明せず1 requestずつforwardする互換pathです。configはenvironmentか
restricted fileから読み、validationはtokenそのものではなくsourceだけを報告します。README contractを
testするため、copy-paste setupがcredential leakへ静かに変わりません。

## identityを決める前にevidenceを残す

logo決定も明示的に保ちます。10候補とvariant matrixはIssue #177 evidence surfaceに保存しました。
探索をfinal brand decisionだと偽らず、再利用できるvisual conversationにしています。別の方向が
選ばれ実装されるまでは、production logoを安定させます。

[v0.6.0リリースノート](../guide/releases/v0.6.0)、[実測メトリクスと時系列ガイド](../guide/metrics-time-series)、
[upgradeとデータ保持のrunbook](../guide/upgrading)へ進んでください。[release QA inventory](https://github.com/Sunwood-ai-labs/NyankoFace/blob/main/tmp/release-qa-v0.6.0.md)
にはclaim、validation command、docs review、publication evidenceをまとめています。
