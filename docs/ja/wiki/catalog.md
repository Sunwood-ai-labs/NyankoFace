---
title: カタログの構造
type: wiki
description: Repository-backedなasset type、metadata、tag、revisionの関係。
readingTime: 6分 reference
updated: 2026-07-21
tags: [models, datasets, skills, mcps, prompts]
related:
  - title: ローカルAIハブという選択
    link: /ja/articles/local-first-hub
    note: Repositoryを正解にする理由を読む。
  - title: 用語集
    link: /ja/wiki/glossary
    note: Catalog用語を確認する。
---

# カタログの構造

NyankoFaceには複数のasset typeがありますが、見えているentityが実在するForgejo repositoryまたはimmutable revisionへ対応する点は共通です。

| Type | 主な内容 | 特有の挙動 |
|---|---|---|
| Model | weights、configuration、model card | model向けbrowse、inference情報 |
| Dataset | table/media file、dataset card | split、viewer表示 |
| Space | Dockerfile、Web app source | local build、start、health、proxy、metrics |
| Skill | `SKILL.md`とsupporting files | instruction render、relationship graph |
| MCP | server code、config、docs | tool server discovery、repository files |
| Prompt | prompt source、metadata | immutableなversion切替 |

## Topicとtag

Repository topicはForgejo metadataとして広い発見に使います。Asset tagはより具体的で複数付与できます。Spaceへ`space`、`gradio`、`audio`を同時に付けてもよく、UIが排他的categoryのように扱うべきではありません。

## Revision

Filesはbranchとcommit historyを表示します。Promptはさらに`v4.1`、`v4.2`のようなversionを選択でき、古いcontentを上書きしません。共有URLは選択revisionを保持します。

## Authorityとcache

正解はForgejoです。Frontendは高速化のためbatch requestやREADME cacheを使えますが、cache keyはowner、repository、revisionを維持する必要があります。Generic cardがrepository実体の代わりになることはありません。
