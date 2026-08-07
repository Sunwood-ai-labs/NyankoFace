---
title: Runtime
type: wiki
description: Docker Spaces、Pages、Actionsのlifecycleとrouting契約。
readingTime: 7分 reference
updated: 2026-07-21
tags: [spaces, pages, actions, docker]
related:
  - title: Spaceはアプリで、リポジトリでもある
    link: /ja/articles/docker-spaces
    note: Dockerfile-firstの理由を読む。
  - title: Spacesガイド
    link: /ja/guide/spaces
    note: Appをbuildして公開する。
---

# Runtime

## Space lifecycle

```text
repository → validate → clone/fetch → Docker build → container start
     ↑                                                   ↓
 catalog ← status/metrics ← health and capacity ← path proxy
```

CPU Spaceはon-demandでstartできます。Runnerは同時実行capacityを制限し、paused、building、running、failed、stoppedを返します。Catalog labelは固定fixtureではなく実際のruntimeを反映します。

### Space契約

- Dockerfileがある。
- Appが所定のinternal portとnon-loopback interfaceでlistenする。
- Proxied pathとforwarded headersを扱える。
- 設定されたlimit内でhealth/startupが完了する。
- Secretはruntimeから渡し、commitしない。

## Pages lifecycle

Pagesは`gh-pages`があればそのstatic outputを、なければ設定された`main`の`docs/` sourceを配信します。Forgejo ActionsでVitePressなどをbuildしてから公開できます。Pagesはstaticであり、Space containerの権限を持ちません。

## Actions isolation

Forgejo runnerは専用Docker-in-Docker daemonを使います。Repository workflowへoperatorのhost Docker socketを渡さないためです。Isolationがあるから任意workflowが安全になるわけではなく、repository permissionとrunner policyは必要です。

## Route behavior

Spaceは`/run/{owner}/{repo}/`、Pagesは`/pages/{owner}/{repo}/`です。同じgatewayとTLS endpointの背後にあるため、公開hostの`/`を所有すると仮定しない実装が必要です。
