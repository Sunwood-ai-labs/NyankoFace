---
title: 安全につなぎ、監査可能に運用する
type: article
description: NyankoFace v0.4.0がagent accessをscope付き・復旧可能・可観測なplatform boundaryへ変える方法。
readingTime: 7分
tags: [release, mcp, security, operations]
---

![NyankoFace v0.4.0リリースヘッダー](/releases/release-header-v0.4.0.svg)

# 安全につなぎ、監査可能に運用する

agent interfaceは、質問に答えるだけでなく操作できると役に立ちます。同時に、その瞬間からriskも増えます。NyankoFace v0.4.0ではMCP endpointをplatform boundaryとして扱います。callerを識別し、scopeを絞り、mutationの意図を明示し、起きたことを保存し、次のrequestを前のprocessから独立させます。

## statelessなread boundaryから始める

公式MCP serverは、catalog、repository、Knowledge、Issue、Space、Pages、Pipeline、metrics、OpenAPIをscope付きTool／Resourceで提供します。各requestはcallerの現在のForgejo identityとrepository permissionで認可します。見えないprivate repositoryは、存在しないrepositoryと別のerrorで露出しません。

このboundaryは運用しやすさを優先しています。Streamable HTTPはserver-side conversationを作らず、次のrequestはどちらのreplicaにも到達できます。ResourceもToolと同じ認可・redaction経路を使うため、primitiveを変えてcheckを迂回できません。

## writeを小さなceremonyにする

Issue comment、Space variable、Secret、Pages deployment、Pipeline controlは単なるHTTP callではありません。clientはまずcanonical targetとpayloadをpreviewし、そのpayloadを短い有効期限のconfirmationとidempotency key付きで再送します。serverはconfirmationをsubject、Tool、target、payload fingerprintへbindします。

durable leaseで、まだdispatchしていない処理とupstream結果が不明な処理を分けます。dispatch後にconnectionが切れた場合、NyankoFaceはretry safeだと推測せずunknown outcomeを保持します。reconciliationはoperatorの明示操作です。audit rowにはidentity、target、outcome、request、時刻を記録しますが、Issue本文、token、PAT、Secret値は保存しません。

失敗を見えるようにしながら、重複mutationを通常の復旧手段にしない形です。

## 同じboundaryをlocal clientへpackageする

clientによってはcommandを起動し、remote HTTPではなく改行区切りJSON-RPCを話します。version付き`nyankoface-mcp` distributionには、そのためのstdio adapterが含まれます。各requestを独立したauthenticated HTTP requestとしてforwardし、bearerはenvironmentまたは保護されたtoken fileから読み、process-level proxy discoveryを無効にし、queueを有限にし、cancellation後の遅いresponseを捨てます。

Codex、Claude Desktop、VS Codeにはそれぞれdocumented setup pathがあります。live-client evidenceでは、startup、invalid credential、read-only、代表的なreadを、raw tokenやclient configをcommitせずに記録しています。remote static-Bearer endpointはClaude DesktopのOAuth向けremote connectorとは別経路で、compatibilityの基準はlocal stdio launcherです。

## replicaを独立してfailさせる

MCP Compose profileはnginxの背後でserver processを2つ動かします。policy、audit、idempotency、write-safety stateはshared coordination boundaryに置き、HTTP request処理はstatelessにします。HA checkでは各replicaを順に単独backendとし、initialize、Tool／Resource discovery、代表readが期待したinstanceへ届くことを確認します。

目的はfailureが消えることではありません。process-local conversation stateを隠れたdependencyにせず、1台を停止・再起動・交換しても次のrequestを処理できることです。

## operator向けcontrol planeを用意する

`/admin/mcp` consoleは、token lifecycle、service-account mapping、policy revision、connection diagnostics、audit evidenceをadministratorに見せます。browser flowはForgejoのfresh reauthenticationで保護します。内部bridge credentialはDocker Secret、service-account token referenceはallowlist制、client tokenは一度だけ表示します。

client boundaryと同じ設計です。accessを絞り、state transitionを明示し、credentialそのものを残さずに復旧に必要なevidenceを残します。

[v0.4.0リリースノート](../guide/releases/v0.4.0.md)、[MCP Server guide](../guide/mcp-server.md)、[MCP管理Runbook](../guide/mcp-administration.md)も参照してください。
