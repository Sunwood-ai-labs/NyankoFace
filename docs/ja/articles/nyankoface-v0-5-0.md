---
title: 状態を安全に運用できる境界へ移す
type: article
description: NyankoFace v0.5.0がpipeline stateをPostgreSQLへ移し、upgradeを検証可能なoperator ceremonyに変える方法。
readingTime: 8分
tags: [release, pipelines, postgres, operations]
---

![NyankoFace v0.5.0リリースヘッダー](/releases/release-header-v0.5.0.svg)

# 状態を安全に運用できる境界へ移す

delivery systemで最も重要なstateは、今動いているcontainerそのものとは限りません。
何が起きたかを説明するhistory、reconciliationが次に進むcursor、connectionやprocessが
消えた後にoperatorが使えるevidenceこそ重要です。NyankoFace v0.5.0では、そのstateを
PostgreSQLへ移し、移行を明示的にしました。

## Pipelineにはdurableな居場所が必要

v0.5.0以前は、pipeline audit historyとreconciliation stateがmetrics volume内のSQLite
fileに保存されていました。初期実装としては便利でしたが、PostgreSQL dumpだけでは
pipeline control planeが含まれないというbackup boundaryを見落としやすい構造でした。

新しいrunnerはaudit row、production state、cursor、migration markerを、`nyankoface_metrics`
databaseの`nyankoface_pipeline` schemaへ保存します。health endpointはpipeline databaseを
readinessの一部として確認します。databaseやschemaがないとき、別の場所へwriteを始めるのではなく、
見えるfailureになります。

## Migrationは推測ではなくceremony

既存環境はstartup時にsilent conversionされません。operatorはrunnerを停止し、SQLite sourceを
保持した上で、`pipeline_migration.py`に正確なfileを検証させます。commandはSQLite integrityと
想定schema、row fieldとtimestampを確認し、reconciliation stateとcursorを移し、SHA-256 source
digestを記録し、conflictを拒否します。

このceremonyには、migration失敗時にsourceが残るという利点があります。同じ検証済みsourceの
再実行は安全ですが、予期しない変更や不完全なtargetは、2つ目の曖昧なhistoryになる前にblocked
operationとして止まります。

## Upgradeはrecovery boundaryを説明する

upgrade runbookはreleaseを稼働中systemへの変更として扱います。backup前にwriteを止め、3つの
PostgreSQL databaseとnamed volumeを対象にし、optionalなMCP stateを検出し、MCP archiveとcredential
checkをfail-closedにします。restore helperはatomic transactionではなくordered restore operationです。
対応するMCP stateを置き換える前にMCP archiveを検証しますが、`.env`、TLS、その他volumeの処理は
順番に進みます。そのためoperatorはold checkoutと検証済みbackupを保持し、変更後にstable ID、
row count、run number、health resultを比較します。

だからold checkout、volume archive、database dumpを一緒に保持します。rollbackはschema migrationを
消すbuttonではなく、本番前にrehearseできる検証済みrestore pathです。

## 見えるsurfaceは静かに保つ

control planeを明示的にする一方で、portalには静かな改善も入っています。repository blob viewは
repositoryのdefault branchを追い、file directoryを基準にrelative linkとassetを解決してREADME
Markdownをrenderします。長いSpace organization nameがtabやruntime controlをheaderの外へ押し出す
こともなくなり、tabletとmobileではwrap後に残った領域からrunner sizeを決めます。

validation workflowも同じ考え方です。frontend、docs、Python、runner、maintenance、Composeの
独立checkを並列で実行しつつ、1つのaggregate `validate` jobでbranch protectionを分かりやすく保ちます。

repository activityは1つのPostgreSQL event ledgerから実測します。detail panelはsuccessfulな
browser/agent view、完了したRaw/LFS/Automation download、activeなagent likeを、累計と日別seriesで
同じevent集合から集計します。既存counterは安定したlegacy keyでbackfillされます。upgradeでは
`nyankoface_metrics` dumpとrestore evidenceを保持してください。このreleaseはhistoryを推測せず、
ledgerを自動pruneしません。public series APIのwindowは366日に制限されます。定義、retention、検証は
[実測メトリクスと時系列ガイド](../guide/metrics-time-series)を参照してください。

[v0.5.0リリースノート](../guide/releases/v0.5.0.md)、[Repository Pipelines guide](../guide/pipelines)、
[upgradeとdata retention runbook](../guide/upgrading)も参照してください。
