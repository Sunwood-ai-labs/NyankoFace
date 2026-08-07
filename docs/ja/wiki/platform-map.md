---
title: プラットフォーム地図
type: wiki
description: Service、公開route、state、trust boundaryを一枚で確認します。
readingTime: 5分 reference
updated: 2026-07-21
tags: [architecture, routes, services, state]
related:
  - title: アーキテクチャガイド
    link: /ja/guide/architecture
    note: 配置の説明を読む。
  - title: Runtime
    link: /ja/wiki/runtime
    note: Sourceからprocessまでたどる。
---

# プラットフォーム地図

## Serviceの責任

| Service | 所有するもの | 所有しないもの |
|---|---|---|
| `gateway` | TLS、公開routing、WebSocket | repository data、app build |
| `frontend` | discovery、repository presentation | Git history、Space process |
| `forgejo` | repository、auth、permission、Issue、PR、Actions metadata | host container lifecycle |
| `spaces-runner` | validation、clone、build、lifecycle、Pages serving | user identity source |
| `seed` | idempotentなsample/bootstrap | 長時間request処理 |
| `maintenance-agent` | Issue起点の`/goal`、evidence gate、guarded merge | 制限のないhost操作 |
| `forgejo-actions-runner` | 隔離DinD上のrepository workflow | host Docker socket |

## 公開route

```text
https://host/
├─ /models /datasets /spaces /skills /mcps /prompts → frontend
├─ /nyankoface/{repository}                         → frontend repository view
├─ /git/                                          → Forgejo
├─ /run/{owner}/{space}/                          → running Space proxy
├─ /runner-api/                                   → runner API
└─ /pages/{owner}/{repository}/                   → published Pages
```

## State

- **Forgejo volume:** repository、user、permission、Issue、PR、Actions metadata。
- **Runner volume:** registration、shared control token、runtime metadata。
- **Docker:** build済みimage、Space container、build cache。
- **Git checkout:** Compose、frontend、service code、sample、docs。production secretは置かない。

## Trust boundary

BrowserはForgejoで認証します。Frontendはinternal tokenでrunnerへprivilegedなlifecycle操作を依頼し、runnerはrepository permissionを確認します。Agentは別々のscope tokenを使い、Claudeはhost Docker socketやbot credentialを持たないunprivileged userとして実行されます。
