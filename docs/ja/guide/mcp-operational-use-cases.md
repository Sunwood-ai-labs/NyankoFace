---
title: MCP実運用ユースケース・テストマトリクス
description: Forgejo token一本化でNyankoFaceを使うAgentの実運用シナリオ。
---

# MCP実運用ユースケース・テストマトリクス

AgentがNyankoFaceへ接続した後に実際に行う作業を、E2Eシナリオとして定義
します。Forgejo APIとMCP Bearerには同じForgejo tokenを使います。live
runnerではmutationを実行せず、write動作は分離fixtureで検証します。

## テストケース

| Case | Agentの流れ | 受入条件 |
|---|---|---|
| UC-01 | 接続してcapabilityを確認 | 未認証initializeは401。認証済みinitialize、initialized notification、tools/list、resources/listが成功し、OpenAPI resourceを広告する |
| UC-02 | 公開Knowledgeを探して内容を確認 | search_catalog(doc)で公開repositoryを取得し、get_repository、root get_tree、`articles` directoryのtree、実際の`articles/*.md` file、get_knowledgeがすべてエラーなしで成功する |
| UC-03 | repositoryのIssueをtriage | list_repositoriesとlist_issuesがboundedなlistを返し、対象repositoryにopen Issueがあればget_issueまで実行する。Forgejoのnot-found/unauthorized統合応答は、read:issue不足と断定せずambiguousとして記録し、成功扱いにしない |
| UC-04 | 変更を安全に計画 | create_issueのpreview=trueがconfirmationを返し、liveシナリオはmutationを実行しない。confirmationとidempotencyの実行経路は分離fixtureで検証する |
| UC-05 | 権限境界を維持 | 不正credentialを拒否し、明示deny/read-only、未認可repository、lifecycle service-accountのdefault denyをcontract testで維持する |

## liveシナリオの実行

保護されたtoken fileがあるcheckoutから実行します。tokenをcommand line
へ置かず、credentialを含むJSON出力を保存しないでください。

    python nyankoface-mcp/scripts/run_operational_use_cases.py --url https://nyankoface.example/mcp --token-file C:\restricted\forgejo.token --client codex --client-version 1.0

runnerは公開doc catalogをboundedにページングし、empty／malformed／未公開の
候補をskipしながら、実在する`articles/*.md`と読めるKnowledge記事を持つ
repositoryを動的に選択します。live datasetにopen Issueがない場合、UC-03の
get_issueはskipped_no_open_issueとして記録します。Forgejoの
not-found/unauthorized統合応答が返った場合は、tokenのread:issue不足と断定せず
skipped_upstream_ambiguousとして上流エラーとともに記録し、成功扱いにしません。
fixture testではlistからdetailまでの完全なflowと、
先頭候補が不正な場合のpagingを実行します。管理されたIssue fixtureがある
場合はissue-owner、issue-repo、issue-numberとrequire-issue-detailを指定します。

## 証跡の条件

- status、件数、repository identity、server revisionだけを記録する。
- token値、token file、raw client log、confirmation値を表示・commitしない。
- live writeはpreviewだけにする。実行、confirmation binding、idempotencyは
  fake upstreamを使う分離testで検証する。
- initializeやtools/listの成功だけを根拠にせず、各caseの代表tools/callまで
  到達したことを確認する。
