# SpaceのVariables／Secrets

NyankoFaceでは、リポジトリOwnerがSpace詳細画面の **VariablesとSecrets** からruntime値とpipeline値を設定できます。

## 種類の使い分け

- **Variable**: 機密ではない設定値。対象リポジトリへの書き込み権限がある利用者には値を表示します。
- **Secret**: APIキーやtoken。保存前に暗号化し、一覧APIでは値を返さず、保存後の画面にも再表示しません。

名前は `[A-Z_][A-Z0-9_]{0,126}` に一致させます。同じ名前で保存すると値をローテーションし、削除は2回目の確認操作で確定します。

Space containerだけなら`runtime`、Forgejo Actionsだけなら`build`、両方なら
`both`を選びます。native Forgejo同期とfork境界は
[Repository Pipelines](./pipelines)を参照してください。

## セキュリティ境界

NyankoFaceは現在のForgejoブラウザsessionを確認し、対象リポジトリへの書き込み権限を要求します。値は正確な `owner/repository` の組み合わせに属し、Git cloneやforkにはコピーされません。

runnerはPostgreSQLへ暗号文を保存し、Fernet鍵を`/data/agents/space-secrets.key`へmode `0600`で保持します。監査行には設定名、種類、操作、実行者、時刻だけを記録し、平文値はログへ出しません。

runtime scopeの値を渡すのは`docker run`だけです。Docker build context、build
argument、image metadata、repository、frontend responseには含めません。build
scopeはForgejo nativeのrepository Variable／Secretへ同期し、信頼済みworkflow job
だけから参照します。runtime値の変更後はSpaceを再起動してください。

## CI／エージェント向けCookie非依存API

同じ暗号化storeを
`/runner-api/v1/spaces/{owner}/{repo}/environment` から操作できます。
各requestでForgejo PATを検証し、browser cookieには依存しません。ForgejoでPATを
失効すると、次のrequestから利用できなくなります。

一覧・監査には`read:repository`、変更には`write:repository`と対象repositoryへの
push権限が必要です。対象repositoryには`space` topicも必要です。token単位の既定rate
limitは1分60requestで、`NYANKOFACE_SPACE_API_RATE_LIMIT_PER_MINUTE`から変更できます。

```bash
export NYANKOFACE_URL="https://nyankoface.example.com"
export FORGEJO_PAT="replace-with-a-forgejo-pat"

# metadataだけを取得。Variable／Secretの値はどちらも返しません。
curl --fail-with-body \
  -H "Authorization: Bearer ${FORGEJO_PAT}" \
  "${NYANKOFACE_URL}/runner-api/v1/spaces/acme/demo/environment"

# 冪等upsertまたはSecret rotation。即時反映は `"restart": true` を追加します。
# `expected_kind` はv1互換のため任意です。型の比較guardには指定してください。
curl --fail-with-body -X PUT \
  -H "Authorization: Bearer ${FORGEJO_PAT}" \
  -H "Content-Type: application/json" \
  -d '{"kind":"secret","value":"replace-me","enabled":true,"scope":"build"}' \
  "${NYANKOFACE_URL}/runner-api/v1/spaces/acme/demo/environment/SERVICE_TOKEN"

# 削除せず無効化。次回restart後のruntimeから除外されます。
curl --fail-with-body -X PATCH \
  -H "Authorization: Bearer ${FORGEJO_PAT}" \
  -H "Content-Type: application/json" \
  -d '{"enabled":false}' \
  "${NYANKOFACE_URL}/runner-api/v1/spaces/acme/demo/environment/SERVICE_TOKEN"

# すでに存在しないkeyの削除も安全な成功no-opです。
curl --fail-with-body -X DELETE \
  -H "Authorization: Bearer ${FORGEJO_PAT}" \
  "${NYANKOFACE_URL}/runner-api/v1/spaces/acme/demo/environment/SERVICE_TOKEN"

# 有効な値をCPU runtime containerの再作成で反映します。
curl --fail-with-body -X POST \
  -H "Authorization: Bearer ${FORGEJO_PAT}" \
  -H "Content-Type: application/json" \
  -d '{"restart":true}' \
  "${NYANKOFACE_URL}/runner-api/v1/spaces/acme/demo/environment/apply"

# Secret値を含まない監査履歴です。
curl --fail-with-body \
  -H "Authorization: Bearer ${FORGEJO_PAT}" \
  "${NYANKOFACE_URL}/runner-api/v1/spaces/acme/demo/environment/audit"
```

errorは安定した`detail.code`と`detail.message`を返し、`429`には
`Retry-After: 60`を付けます。対話型API仕様は`/runner-api/docs`、OpenAPI JSONは
`/runner-api/openapi.json`です。

browser管理画面とAPIは同じrepository scopeのrowを読み書きします。Secretは両方で
write-onlyです。restartを実行しない変更responseは`restart_required: true`を返します。

## ローテーション、削除、復旧

1. **VariablesとSecrets** を開きます。
2. **ローテーション** または **編集** で同名の値を置き換えます。
3. **削除**、続けて **削除を確認** を選ぶと削除されます。

バックアップはPostgreSQL DBと`space-secrets.key`を必ず一緒に取得します。片方だけでは既存暗号文を復号できません。鍵や平文Secretをcommitしないでください。

generation migration中に新旧Runnerをwriterとして混在させるのは安全ではありません。全replicaの更新が完了するまで環境設定の書き込みを停止するか、Runner writerを1台に限定してください。

## リモートGPU worker

CPU SpaceにはLXC内で安全に注入します。リモートGPUはworker固有の暗号化配送路が未設定のため、設定値が存在する場合はfail-closedで起動を拒否します。平文転送へフォールバックせず、envelope encryptionとworker単位の認可を実装してから有効化してください。

