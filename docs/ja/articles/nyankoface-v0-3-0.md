---
title: すべての遷移を分かる速さにする
type: article
description: NyankoFace v0.3.0が探索、遷移feedback、Space readiness、コード表示、識別をどう改善したか。
readingTime: 6分
tags: [release, performance, spaces, discovery]
---

![NyankoFace v0.3.0リリースヘッダー](/releases/release-header-v0.3.0.svg)

# すべての遷移を分かる速さにする

performanceは最後のcomponentが完成するまでの秒数だけではありません。tapに反応したか、並び順を保てたか、アプリが起動中だと分かるか、別surfaceでも同じnavigationとidentityを認識できるか。NyankoFace v0.3.0は、その一連の流れを一つのproduct課題として扱いました。

## 開く前に、目的のrepositoryを見つける

11種類のcatalogで、作成日、更新日、いいね数、閲覧数を一致集合全体に適用してからpaginationします。安定したtie breakerで同じ問い合わせを決定的にし、URL parameterでfilter／sort結果を共有できます。metricsはcardごとのN+1ではなく、有限batchで取得します。

## 移動先より先に反応する

navigationでは、即時feedbackとcontent完成を分離しました。pressed controlとprogressが操作を受け付け、route skeletonがlayoutを保ち、15秒のtimeout後は待ち続けずretryできます。公開knowledge metadataは短いprocess内cacheとin-flight coalescingを使えますが、private／authenticated contentはcacheしません。

## 空白ではなくSpace lifecycleを見せる

containerより先にSpace repository shellを表示します。badgeとapp panelは同じruntime state sourceを使い、750 ms間隔でrunner endpointを確認してからiframeをmountします。ローカル各10回の比較でcandidate p50は約358～359 msから67 msへ短縮しました。ただし約360 msの外れ値が残りp95はbaselineに近いため、そのtailも明記しています。

## コードと操作を同じ顔で案内する

server-side syntax highlightingはclient runtimeを不要にし、tokenをStandard、Solarpunk、Cyberpunkへ割り当てます。未知languageは安全にfallbackします。portal／Forgejo navigationはversion付きcontractを共有し、faviconからdocsまでcanonicalな猫のmarkを使います。

これは、すべてのrequestが5倍速くなったという主張ではありません。操作へ素早く応答し、有限のroute classを計測し、runtime phaseを公開し、ローカル根拠の範囲を明記する仕組みです。

[v0.3.0リリースノート](../guide/releases/v0.3.0.md)、[ページ遷移のパフォーマンス](../guide/performance.md)、[カタログのメトリクス並び替え](../guide/catalog-metric-sorting.md)も参照してください。
