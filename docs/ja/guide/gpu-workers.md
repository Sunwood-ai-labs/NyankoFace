---
title: GPU worker
type: guide
description: 任意のGPU-backed Space実行に関する公開契約です。
readingTime: 5分
tags: [gpu, spaces, runtime, security]
related:
  - title: Docker Spaces
    link: /ja/guide/spaces
  - title: SpaceのVariables／Secrets
    link: /ja/guide/space-environment
---

# GPU worker

NyankoFaceは、任意のGPU worker上でDockerfileベースのSpaceを実行できます。
workerは認証済みleaseをpollし、指定revisionをbuildして、短期runtime URLを返します。
CPU実行がデフォルトです。

## 公開版の安全なデフォルト

example workerは通常のcontainer境界でjobを起動し、trusted repository listを持ちません。
追跡対象の[`runtime-profile.example.json`](../../gpu-worker/runtime-profile.example.json)だけでは
host integrationを有効にできません。

compose exampleはplaceholderとloopback bindだけを使います。接続設定は非公開のdeployment
overlayまたはsecret storeで置き換え、organizationのhostname、address、credential、hardware
inventoryはcommitしないでください。

## 非公開runtime profileの任意設定

運用者は、`WORKER_RUNTIME_PROFILE_FILE`で指定した場所へ、別管理のJSON profileをmountできます。

```json
{
  "repositories": ["owner/diagnostics-space"],
  "share_namespaces": true,
  "metadata_mount": {
    "source": "/private/metadata",
    "target": "/runtime/metadata",
    "read_only": true
  }
}
```

workerが追加のDocker optionを有効にするには、次の条件をすべて満たす必要があります。

- repository slugが明示的にlistされていること
- namespace sharingが明示的に有効であること
- metadata mountのpathがabsoluteで、`read_only: true`であること

欠落、形式不正、未登録、書き込み可能な設定は、通常のcontainer実行へfail closedします。
実際のprofileは公開repositoryの外で管理してください。上記source pathはexample placeholderであり、
deployment valueではありません。

## 運用境界

host-integrated diagnosticsはprivilegedな配備機能です。review済みrepositoryだけをallowlistに入れ、
read-only mountを使い、worker enrollment credentialはGit外で管理してください。公開repositoryには
policy contractとtestだけを置き、private topologyやlive runtime evidenceは置きません。
