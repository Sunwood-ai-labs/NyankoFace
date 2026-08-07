---
title: 用語集
type: reference
description: NyankoFaceのroute、asset、state、設定用語を簡潔に定義します。
readingTime: quick reference
updated: 2026-07-21
tags: [definitions, configuration, routes]
related:
  - title: プラットフォーム地図
    link: /ja/wiki/platform-map
    note: 用語をsystem contextへ置く。
  - title: トラブルシューティング
    link: /ja/guide/troubleshooting
    note: 具体的なfailureを診断する。
---

# 用語集

**Asset type**  
RepositoryをModel、Dataset、Space、Skill、MCP、Promptとして提示するときのrole。

**Docker Space**  
Space runnerがbuild・proxyできるDockerfile-backed Web appのForgejo repository。

**Forgejo**  
NyankoFaceのGit、identity、permission、Issue、PR、Actionsにおけるauthoritative service。

**Knowledge Atlas**  
概念中心のWiki layer。関係を説明し、実践guideとnarrative articleへ接続する。

**NyankoFace Pages**<br>
`/pages/{owner}/{repo}/`で行うstatic repository publishing。Pages branchまたはdirectoryから配信し、Forgejo Actionsでbuildできる。

**Prompt revision**  
`v4.2`のようにURLとrepository historyへ保持される、選択可能でimmutableなPrompt version。

**Reviewed SHA**  
`review-agent`が独立評価したPR head commit。現在headが異なればapprovalは無効。

**Runner control token**  
Trusted service間でlifecycle APIを呼ぶinternal shared secret。User session tokenではない。

**Topic / tag**  
Topicはrepository-level Forgejo metadata。TagはNyankoFaceの表示とfilterに使うmulti-value asset descriptor。

**Visual QA**  
Page、theme、viewport、scroll position、interaction、contrastを横断する自動・手動検査。
