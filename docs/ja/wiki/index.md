---
title: Knowledge Atlas
type: wiki
description: NyankoFaceの概念、部品、経路、運用契約をつないだ索引。
readingTime: reference index
tags: [map, concepts, reference]
related:
  - title: 読みもの
    link: /ja/articles/
    note: システムの背景と判断を読む。
  - title: はじめに
    link: /ja/guide/getting-started
    note: 地図を実際に動かす。
---

# Knowledge Atlas

このセクションはWikiとして使います。質問に近い概念から入り、関連nodeをたどるか、上部のlocal searchですべてのページを横断してください。

| Node | 知りたいこと | つながる先 |
|---|---|---|
| [プラットフォーム地図](./platform-map.md) | どのserviceが何とrouteを所有するか | architecture、state、trust boundary |
| [カタログの構造](./catalog.md) | Models、Datasets、Skills、MCPs、Promptsとrepositoryの関係 | metadata、tags、revisions |
| [Runtime](./runtime.md) | Spaces、Pages、Actionsがどう実行・公開されるか | Docker、proxy、lifecycle |
| [エージェント運用](./agent-operations.md) | 保守がどう委任・レビュー・却下・mergeされるか | identities、evidence、states |
| [用語集](./glossary.md) | 名前、route、setting、statusの正確な意味 | 定義と関連source |

## 3つの読み方

1. [読みもの](../articles/index.md)で背景とtrade-offを理解する。
2. 上のnodeをたどって概念を接続する。
3. 変更するときは[実践ガイド](../guide/getting-started.md)を使う。
