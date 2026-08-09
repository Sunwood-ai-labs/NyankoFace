# MCP管理Runbook

`/admin/mcp` は、MCPのサービスアカウント対応付け、クライアントToken、policy、接続診断、監査証跡を扱う管理者専用control planeです。[PR #150](https://github.com/Sunwood-ai-labs/NyankoFace/pull/150) と [PR #152](https://github.com/Sunwood-ai-labs/NyankoFace/pull/152) で実装された運用境界を説明します。今回の実runtimeとVisual QAの詳細は [Issue #151の証跡index](../../evidence/issues/151/README.md) に固定しています。

## セキュリティ境界

- ブラウザは`/api/admin/mcp/*`を呼びます。frontend BFFはリクエストごとにForgejo管理者権限を確認してから、制限されたリクエストだけを内部の`mcp-admin`へ転送します。
- `/api/admin/mcp/*`のadmin BFF API requestは、未ログインなら`401`、認証済みでもForgejo管理者でなければ`403`です。`/admin/mcp` page自体は未認証ならloginへredirectし、非管理者または安全でないtransportなら`404`を返します。`mcp-admin`はhost portを公開せず、Compose networkからだけ到達できます。
- 再認証formは現在のForgejo passwordをForgejoへ直接照合します。passwordは保存、admin serviceへの転送、log出力をせず、formを消去した後も保持しません。発行される5分間のHttpOnly proofはbrowser sessionと管理者subjectに束縛されます。
- BFFからadminへの内部credentialは`mcp-admin`だけがDocker secretとして読みます。`mcp-admin`はmode `0440`でprivateな`nyankoface-mcp-admin-bridge` volumeへcopyし、frontendは`/run/mcp-admin-bridge/token`をread-onlyで読みます。raw Docker secretをfrontendへmountせず、環境変数やbrowser valueにも置きません。
- サービスアカウントのcredential参照名は`NYANKOFACE_MCP_FORGEJO_TOKEN_ALLOWLIST`にあるものだけを許可します。参照先は`NYANKOFACE_MCP_FORGEJO_TOKEN_ROOT`直下のreadableなregular fileかつnon-symlinkでなければなりません。内部admin credentialをallowlistへ追加しないでください。
- client Tokenの平文は、認証済みBFFへのissue／rotate成功responseだけで返され、一度だけ表示されます。その後のstate、list、revoke、audit、connection-test responseは平文を返しません。dialogを閉じるか破棄した後、UIは平文を保持せず、registry、log、auditにも復元可能な平文を残しません。

## Agentの認証: Forgejo credentialを一本化

Agentは、Forgejo APIで使っているものと**まったく同じForgejo token**を
MCPの`Authorization: Bearer`にも使えます。NyankoFaceは提示されたtokenを
Forgejoの`/user`で検証し、そのtokenをForgejo／Runnerへ渡すため、read／write
の権限判定はForgejoをsource of truthにします。Agentごとに別のMCP tokenや
別のpermission mappingを作成しません。

直接提示されたtokenはlifecycle registry、MCP response、log、auditへ保存・返却
しません。MCPのwrite safety（policy、preview、confirmation、idempotency、
secret redaction）はそのまま有効です。Forgejo側でtokenをrevoke／rotateすれば、
次の認証からMCPも利用できなくなります。

短いTTLやscope／repositoryのsubsetが必要なclient向けには、下記のlifecycle
service-account方式も残しています。Agentにとっては任意の互換方式です。

## MCP profileを起動する

secretとMCP stateはrepositoryの外で作成します。Composeの`./secrets/...` defaultはlocal development用で、repository外のsecret境界にはなりません。Compose起動前に次の3つのpathをabsolute pathへ設定します。Windows PowerShellの例は内部credentialだけを生成するため、Forgejo token fileはdeploymentのsecret管理手順で投入してください。

```powershell
$secretRoot = Join-Path $env:ProgramData 'NyankoFace\secrets'
$stateRoot = Join-Path $env:ProgramData 'NyankoFace\mcp-state'
New-Item -ItemType Directory -Force $secretRoot, $stateRoot | Out-Null
$hostIdentities = @([Security.Principal.WindowsIdentity]::GetCurrent().Name)
# Docker Desktopが別のhost identityを使う場合だけ、そのidentityを明示的に追加します。
# $hostIdentities += 'CONTOSO\nyankoface-docker'
$aclGrants = @($hostIdentities | ForEach-Object { '{0}:(OI)(CI)(F)' -f $_ })
foreach ($path in @($secretRoot, $stateRoot)) {
  icacls.exe $path /reset /T /C | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Failed to reset existing ACLs under $path" }
  icacls.exe $path /inheritance:r /T /C | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Failed to remove inherited ACLs from $path" }
  icacls.exe $path /grant:r $aclGrants /T /C | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Failed to protect ACLs on $path" }
}
$internalTokenPath = Join-Path $secretRoot 'nyankoface-mcp-admin-internal-token'
$forgejoTokenPath = Join-Path $secretRoot 'nyankoface-mcp-forgejo-user-token'
$bytes = New-Object byte[] 48
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
[Convert]::ToBase64String($bytes) | Set-Content -NoNewline -LiteralPath $internalTokenPath
$env:NYANKOFACE_MCP_ADMIN_INTERNAL_TOKEN_FILE = $internalTokenPath
$env:NYANKOFACE_MCP_FORGEJO_USER_TOKEN_FILE = $forgejoTokenPath
$env:NYANKOFACE_MCP_STATE_DIR = $stateRoot
```

bounded serviceを起動またはrebuildし、secretの中身を表示せずにhealthを確認します。

```bash
docker compose --profile mcp up -d --build frontend gateway nyankoface-mcp mcp-admin
docker compose --profile mcp ps
```

`8001`を公開portにせず、BFFを迂回せず、`docker-compose.yml`、`.env`、screenshot、Issue comment、Gitへcommitするclient設定にsecret値を置かないでください。

## 操作手順

1. Forgejo管理者で`/admin/mcp`を開き、再認証を完了します。proofがない、期限切れ、改変、別session、別subjectに束縛されている場合はfail closedで拒否されなければなりません。
2. lifecycle clientでは、サービスアカウント対応付けを追加または選択します。Forgejo user、allowlist済みsecret参照名、必要最小限のscope、明示したrepository権限を選びます。Forgejo tokenを直接使うAgentはこの手順を省略できます。
3. lifecycle clientでは、対応付けのscopeとrepositoryのsubsetだけを持つclient Tokenを発行します。TTLは実運用で必要な最短値にします。Agentは既存のForgejo tokenをそのまま使います。
4. 一度きりのdialogを開いたまま**接続を確認**を実行し、`initialize`、`tools/list`、`resources/list`を確認します。到達性、HTTP／認証失敗、JSON-RPC失敗、利用可能なtool／resource数を区別し、Tokenや上流error本文をechoしません。
5. Tokenは保護されたclient secret storeへコピーしたらdialogを閉じるか破棄します。平文をticket、shell history、screenshot、browser bookmark、source fileへ置かないでください。
6. 対応付けを無効化または再マッピングしたときは、以前のmapping versionに紐付くTokenが失効したことを確認します。Tokenのrotateでは前のTokenが失効します。

### 安全なclient snippet

以下はplaceholderだけを含む例です。`<NYANKOFACE_HOST>`と`<FORGEJO_TOKEN_FILE>`はローカルで置換し、実Tokenをcommitしないでください。

#### Codex CLI

```powershell
$env:NYANKOFACE_FORGEJO_TOKEN_FILE = '<FORGEJO_TOKEN_FILE>'
$env:NYANKOFACE_MCP_TOKEN = (Get-Content -LiteralPath $env:NYANKOFACE_FORGEJO_TOKEN_FILE -Raw).Trim()
codex mcp add nyankoface --url https://<NYANKOFACE_HOST>/mcp --bearer-token-env-var NYANKOFACE_MCP_TOKEN
```

#### Claude Desktop

```json
{
  "mcpServers": {
    "nyankoface": {
      "command": "nyankoface-mcp-stdio",
      "env": {
        "NYANKOFACE_MCP_REMOTE_URL": "https://<NYANKOFACE_HOST>/mcp",
        "NYANKOFACE_MCP_CLIENT_TOKEN_FILE": "<FORGEJO_TOKEN_FILE>"
      }
    }
  }
}
```

#### VS Code

```json
{
  "servers": {
    "nyankoface": {
      "type": "http",
      "url": "https://<NYANKOFACE_HOST>/mcp",
      "headers": { "Authorization": "Bearer ${input:nyankoface-token}" }
    }
  },
  "inputs": [
    {
      "id": "nyankoface-token",
      "type": "promptString",
      "description": "Forgejo token (MCP Bearerにも同じ値を使用)",
      "password": true
    }
  ]
}
```

## Policyと監査

Policy更新には画面に表示されたrevisionを含めます。同時更新があればconflictになるため、再読み込みして新しいrevisionを確認してから再送します。lifecycle／service-account requestの既定はdenyで、明示的なallowだけが適用されます。直接Forgejo Bearerを使うrequestは、認証済みForgejo identityをread／write policyの基準にし、repository writeは上流Forgejoの権限確認で制限します。明示的なdenyとread-only ruleは、直接Forgejo Bearerにも適用されます。

監査は実際のoutcome（`allowed`、`denied`、`failed`、`replayed`、`changed`）、subject、client、tool、期間、bounded cursorで絞り込めます。summaryは現在ページだけでなくfilterに一致する全recordを数えます。展開recordは承認済みfieldだけを返し、Token平文、Token digest、Forgejo PAT path、idempotency fingerprint、audit-chain hashは返しません。

## 障害対応Runbook

- **Forgejo token紛失:** Forgejoで直ちにrevoke／rotateし、clientの保護されたsecret storeにある唯一のForgejo tokenを更新します。別のMCP tokenをrotateする必要はありません。
- **lifecycle Token紛失:** 直ちに失効し、最小scopeで再発行して、clientの保護されたsecret storeを更新します。
- **サービスアカウント侵害の疑い:** 先に対応付けを無効化し、Forgejo credential secretをrotateし、再対応付けしてから新しいclient Tokenを発行します。
- **Policy conflict:** 再読み込みしてから再実行します。未確認のrevisionを上書きしません。
- **Admin backend停止:** `mcp-admin`のhealth、Docker secret mount、lifecycle／policy／audit volumeの権限を確認します。BFFを迂回する公開portは追加しません。
- **Backupとrestore:** 設定した`NYANKOFACE_MCP_STATE_DIR`のToken registryとlifecycle auditに加え、`nyankoface-mcp-state` volume全体を一貫したSQLite snapshotとしてbackupします。snapshotにはpolicy／audit database、`/data/write-safety.sqlite3`、隣接する`.hmac-key`を必ず含めます。これらはidempotencyとoperation-reconciliation historyを保持するため、一部だけrestoreすると、以前に上流で成功したか不明なwriteを再実行する可能性があります。restore後は管理者／非管理者のaccess、短命で制限されたTokenの発行、接続確認、失効、audit outcomeを確認します。

## Release QAの境界

base、solarpunk、cyberpunk themeのdesktop／mobile幅を実runtimeで手動確認します。tabのwrap、一度きりのsecret処理、contrast、control、footer位置、horizontal overflowを確認します。screenshot生成は意図的にCI gateにしません。今回のmerged mainに対するマスク済み証跡は [Issue #151](../../evidence/issues/151/README.md) にあります。
