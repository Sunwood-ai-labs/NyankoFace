---
title: MCP実クライアントQA
description: Codex、Claude Desktop、VS CodeでNyankoFace MCPを安全に再現確認する。
---

# MCP実クライアントQA

この手順では、**実クライアントの手動QA**とCIで自動化できるprotocol testを
分離します。token、PAT、literal credentialを含む設定や生logはcommitしません。

## 正式な接続経路

| Client | 今回使うtransport | Credentialの渡し方 |
|---|---|---|
| Codex CLI | remote Streamable HTTP | 継承した環境変数からbearerを参照 |
| Claude Desktop | local stdio adapter | `nyankoface-mcp-stdio`が制限付きtoken fileを読む |
| VS Code | remote Streamable HTTP | 公式`mcp.json`のpassword input |

Codexではtoken値をcommand lineに置かず登録します。

```powershell
$env:NYANKOFACE_MCP_TOKEN = (Get-Content $env:NYANKOFACE_MCP_TOKEN_FILE -Raw).Trim()
codex mcp add nyankoface --url https://nyankoface.example/mcp `
  --bearer-token-env-var NYANKOFACE_MCP_TOKEN
```

Claude Desktopのremote custom connectorはauthlessまたはOAuth用で、static
Bearer欄はありません。local stdio commandを使う前にverified host packageを
installします（このcheckoutなら `python -m pip install --upgrade ./nyankoface-mcp`、
またはverified wheel）。非secret設定を検証した上で、
`%APPDATA%\Claude\claude_desktop_config.json`にlocal stdio adapterを登録します。

```json
{
  "mcpServers": {
    "nyankoface": {
      "command": "nyankoface-mcp-stdio",
      "env": {
        "NYANKOFACE_MCP_REMOTE_URL": "https://nyankoface.example/mcp",
        "NYANKOFACE_MCP_CLIENT_TOKEN_FILE": "C:\\restricted\\nyankoface.token"
      }
    }
  }
}
```

変更後はClaude Desktopを完全終了して再起動します。Windowsのpackaged版では、
unpackaged版のpathを決め打ちせず、app packageの`LocalCache`配下にある実効
Roaming pathを確認してください。

VS Codeでは[`nyankoface-mcp/examples/vscode-mcp.json`](https://github.com/Sunwood-ai-labs/NyankoFace/blob/main/nyankoface-mcp/examples/vscode-mcp.json)
を`.vscode/mcp.json`またはuser profileへコピーし、`<NYANKOFACE_HOST>` のhost
placeholderだけを自分のdeploymentへ置き換えます。templateの`/mcp` pathは残し、
password inputは残し、
literal tokenへ置換してはいけません。

設定schemaは[Codex MCP guide](https://developers.openai.com/codex/mcp/)、
[VS Code MCP reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration)、
[Claude Desktop local server guide](https://modelcontextprotocol.io/docs/develop/connect-local-servers)、
[Claude remote connector guide](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)
と照合しています。

## 手動チェック

1. clientごとに別の短期service credentialを発行します。
2. token値やtoken file内容を残さず、client／OS／server revision／実行日時を記録します。
3. initialize、Tools、Resources、限定されたreadを1件確認します。AIへpromptを送るより、
   client nativeのresource browserを優先します。
4. valid、scope不足、expired、revoked、invalidをprotocol levelで再確認します。
   lifecycle不正はinitialize前の`401`が期待値です。scope不足ではgovernance上
   許可済みの`search_catalog`をrepository-only credentialで呼び、
   `catalog:read`不足という特定のdenialを確認します。
5. 非公開配備に複数instanceがある場合のisolation checkは、その非公開環境内で実施します。
   instance名、image identifier、address、runtime identifierは公開しません。
6. commit前にsanitized summaryへcredentialが混入していないかscanします。
7. Git外の制限付きdirectoryへnative raw logを保存し、全QA credentialとの
   exact match scan後、byte count、SHA-256、sanitized stateだけをcommitします。

```bash
bash nyankoface-mcp/scripts/provision_live_client_qa.sh
python nyankoface-mcp/scripts/run_live_client_protocol.py --help
```

provisionerはGit外のroot-only fileへcredentialを保存し、secret-freeな件数だけを
出力します。protocol runnerはtoken fileを読み、期待する認証失敗も検証し、summary
にcredentialが現れた場合は失敗します。CIはこのprotocol behaviorを検証できますが、
desktop UIやscreenshotの確認済みとは扱いません。

## Issue #130の公開範囲

このpublic snapshotにはprotocol QAの手順とclient safety contractだけを残します。
配備固有のresult、instance数、image digest、runtime identifier、raw log、screenshotは
非公開のworking recordで管理し、ここでは公開しません。

Raw artifactはGit外に保存します。reviewに必要な最小限のsanitized resultだけを記録し、
temporary credentialをrevokeし、client設定を復元したうえで、tokenや非公開配備のidentifierが
含まれていないことを確認してからreportを共有してください。
