---
title: Challenge serverの復旧
type: guide
description: Challenge用Flask serverをkill、復旧、検証するbounded手順です。
readingTime: 6分
tags: [operations, recovery, testing]
related:
  - title: 運用
    link: /ja/guide/operations
  - title: トラブルシューティング
    link: /ja/guide/troubleshooting
---

# Challenge serverの復旧

このrunbookは、local checkoutまたは隔離runnerから起動したchallenge
serverを対象にします。特定のchallenge repository、host、port、credentialには依存しません。
大文字のplaceholderは各自のlocal環境で置き換え、値をcommitしたり公開Issueへ貼ったりしないでください。

復旧の順序は固定します。

1. stable service nameとPID fileで対象processを1つに特定する。
2. killして旧PIDが消えたことを確認する。
3. 停止中のstable nameが期待する`000FAIL` markerを返すことを確認する。
4. virtual environmentを再構築し、同じservice nameで再起動する。
5. health、3段階のchallenge flow、negative caseを検証する。

## boundedな入力を設定する

challenge checkoutから実行します。以下のcommandはretry回数を固定しています。
unbounded watcherへ変更しないでください。

~~~bash
set -euo pipefail

CHALLENGE_DIR="${CHALLENGE_DIR:?challenge checkoutを指定}"
SERVICE_NAME="${SERVICE_NAME:?stableなchallenge service名を指定}"
APP_MODULE="${APP_MODULE:?Flask app moduleを指定}"
SERVICE_MARKER="${SERVICE_MARKER:-nyankoface:$SERVICE_NAME}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:?challenge portを指定}"
HEALTH_URL="${HEALTH_URL:?stable nameのhealth URLを指定}"
HEALTH_STATUS="${HEALTH_STATUS:?healthで期待するHTTP statusを指定}"
HEALTH_CONTENT_TYPES="${HEALTH_CONTENT_TYPES:-application/json,text/plain}"
HEALTH_JSON_CONTENT_TYPES="${HEALTH_JSON_CONTENT_TYPES:-application/json}"
HEALTH_TEXT_CONTENT_TYPES="${HEALTH_TEXT_CONTENT_TYPES:-text/plain}"
HEALTH_JSON_STATUS_FIELD="${HEALTH_JSON_STATUS_FIELD:-status}"
HEALTH_BODY_CONTRACTS="${HEALTH_BODY_CONTRACTS:-ok,healthy,OK}"
HEALTH_TEXT_BODY_CONTRACTS="${HEALTH_TEXT_BODY_CONTRACTS:-OK}"
STAGE_1_PROBE_URL="${STAGE_1_PROBE_URL:?idempotentなstage-1 probe URLを指定}"
STAGE_1_PROBE_IDEMPOTENT="${STAGE_1_PROBE_IDEMPOTENT:?stage-1 probeのidempotenceをtrueに設定}"
STAGE_1_PROBE_METHOD="${STAGE_1_PROBE_METHOD:-GET}"
STAGE_1_PROBE_HEADERS_FILE="${STAGE_1_PROBE_HEADERS_FILE:-}"
STAGE_1_PROBE_BODY_FILE="${STAGE_1_PROBE_BODY_FILE:-}"
STAGE_1_PROBE_STATUS="${STAGE_1_PROBE_STATUS:-$HEALTH_STATUS}"
STAGE_1_PROBE_CONTENT_TYPES="${STAGE_1_PROBE_CONTENT_TYPES:-$HEALTH_CONTENT_TYPES}"
STAGE_1_PROBE_JSON_CONTENT_TYPES="${STAGE_1_PROBE_JSON_CONTENT_TYPES:-$HEALTH_JSON_CONTENT_TYPES}"
STAGE_1_PROBE_TEXT_CONTENT_TYPES="${STAGE_1_PROBE_TEXT_CONTENT_TYPES:-$HEALTH_TEXT_CONTENT_TYPES}"
STAGE_1_PROBE_JSON_STATUS_FIELD="${STAGE_1_PROBE_JSON_STATUS_FIELD:-$HEALTH_JSON_STATUS_FIELD}"
STAGE_1_PROBE_BODY_CONTRACTS="${STAGE_1_PROBE_BODY_CONTRACTS:-$HEALTH_BODY_CONTRACTS}"
STAGE_1_PROBE_TEXT_BODY_CONTRACTS="${STAGE_1_PROBE_TEXT_BODY_CONTRACTS:-$HEALTH_TEXT_BODY_CONTRACTS}"
STAGE_2_PROBE_URL="${STAGE_2_PROBE_URL:?idempotentなstage-2 probe URLを指定}"
STAGE_2_PROBE_IDEMPOTENT="${STAGE_2_PROBE_IDEMPOTENT:?stage-2 probeのidempotenceをtrueに設定}"
STAGE_2_PROBE_METHOD="${STAGE_2_PROBE_METHOD:-GET}"
STAGE_2_PROBE_HEADERS_FILE="${STAGE_2_PROBE_HEADERS_FILE:-}"
STAGE_2_PROBE_BODY_FILE="${STAGE_2_PROBE_BODY_FILE:-}"
STAGE_2_PROBE_STATUS="${STAGE_2_PROBE_STATUS:-$HEALTH_STATUS}"
STAGE_2_PROBE_CONTENT_TYPES="${STAGE_2_PROBE_CONTENT_TYPES:-$HEALTH_CONTENT_TYPES}"
STAGE_2_PROBE_JSON_CONTENT_TYPES="${STAGE_2_PROBE_JSON_CONTENT_TYPES:-$HEALTH_JSON_CONTENT_TYPES}"
STAGE_2_PROBE_TEXT_CONTENT_TYPES="${STAGE_2_PROBE_TEXT_CONTENT_TYPES:-$HEALTH_TEXT_CONTENT_TYPES}"
STAGE_2_PROBE_JSON_STATUS_FIELD="${STAGE_2_PROBE_JSON_STATUS_FIELD:-$HEALTH_JSON_STATUS_FIELD}"
STAGE_2_PROBE_BODY_CONTRACTS="${STAGE_2_PROBE_BODY_CONTRACTS:-$HEALTH_BODY_CONTRACTS}"
STAGE_2_PROBE_TEXT_BODY_CONTRACTS="${STAGE_2_PROBE_TEXT_BODY_CONTRACTS:-$HEALTH_TEXT_BODY_CONTRACTS}"
STAGE_3_PROBE_URL="${STAGE_3_PROBE_URL:?idempotentなstage-3 probe URLを指定}"
STAGE_3_PROBE_IDEMPOTENT="${STAGE_3_PROBE_IDEMPOTENT:?stage-3 probeのidempotenceをtrueに設定}"
STAGE_3_PROBE_METHOD="${STAGE_3_PROBE_METHOD:-GET}"
STAGE_3_PROBE_HEADERS_FILE="${STAGE_3_PROBE_HEADERS_FILE:-}"
STAGE_3_PROBE_BODY_FILE="${STAGE_3_PROBE_BODY_FILE:-}"
STAGE_3_PROBE_STATUS="${STAGE_3_PROBE_STATUS:-$HEALTH_STATUS}"
STAGE_3_PROBE_CONTENT_TYPES="${STAGE_3_PROBE_CONTENT_TYPES:-$HEALTH_CONTENT_TYPES}"
STAGE_3_PROBE_JSON_CONTENT_TYPES="${STAGE_3_PROBE_JSON_CONTENT_TYPES:-$HEALTH_JSON_CONTENT_TYPES}"
STAGE_3_PROBE_TEXT_CONTENT_TYPES="${STAGE_3_PROBE_TEXT_CONTENT_TYPES:-$HEALTH_TEXT_CONTENT_TYPES}"
STAGE_3_PROBE_JSON_STATUS_FIELD="${STAGE_3_PROBE_JSON_STATUS_FIELD:-$HEALTH_JSON_STATUS_FIELD}"
STAGE_3_PROBE_BODY_CONTRACTS="${STAGE_3_PROBE_BODY_CONTRACTS:-$HEALTH_BODY_CONTRACTS}"
STAGE_3_PROBE_TEXT_BODY_CONTRACTS="${STAGE_3_PROBE_TEXT_BODY_CONTRACTS:-$HEALTH_TEXT_BODY_CONTRACTS}"
FAILURE_URL="${FAILURE_URL:?stable nameのfailure URLを指定}"
FAILURE_STATUS="${FAILURE_STATUS:?停止状態で期待するHTTP statusを指定}"
FAILURE_CONTENT_TYPE="${FAILURE_CONTENT_TYPE:?停止状態で期待するcontent typeを指定}"
PID_FILE="$CHALLENGE_DIR/run/$SERVICE_NAME.pid"
VENV="$CHALLENGE_DIR/.venv"
LOG_FILE="$CHALLENGE_DIR/run/$SERVICE_NAME.log"
mkdir -p "$(dirname "$PID_FILE")"
~~~

既定のhealth contractは、JSONの`status`が`ok`、`healthy`、`OK`のいずれかで、
text/plainのbodyが正確な`OK`であることを受け入れます。別のchallengeでは、
proofを実行する前に`HEALTH_CONTENT_TYPES`、`HEALTH_JSON_CONTENT_TYPES`、
`HEALTH_TEXT_CONTENT_TYPES`、`HEALTH_JSON_STATUS_FIELD`、カンマ区切りの
`HEALTH_BODY_CONTRACTS`を設定してください。exact text responseは
`HEALTH_TEXT_BODY_CONTRACTS`で別に設定します。各stageについて、
idempotentな`STAGE_n_PROBE_URL`を指定し、nonceを消費したりchallenge stateを
変更したりしないことを別途確認してから`STAGE_n_PROBE_IDEMPOTENT=true`に設定します。
method、任意の`STAGE_n_PROBE_HEADERS_FILE`（1行に1つの完全なheader）、任意の
`STAGE_n_PROBE_BODY_FILE`も設定します。header fileを空にすると、設定したcontent
typeを`Accept` headerとして使用します。probeごとにhealth contractと異なるstatus、
content type、JSON field、body contractがある場合は、probe固有の変数も設定します。
stage commandは1回だけ実行し、その後は分離したidempotent probeだけを呼びます。
mutatingなstage requestは再実行しません。stage自身のresponseを検証する必要がある場合は、
challenge固有のartifactとしてstage command内でcapture・検証し、このprobeで代用しないでください。

stable nameはchallengeごとに一意にします。任意の「最新Python」のPID、
shared process-managerのparent、別challengeにも一致するsubstringでprocessを選ばないでください。

## 旧processをkillして確認する

PID fileを読み、数字だけであることを確認します。signalを送る前に、
challenge checkout、再構築したinterpreter、app/service markerを使ってprocess identityを確認します。
2回目までのbounded checkで正常停止か、停止不能かを判定します。

~~~bash
old_pid="$(
  python3 - "$PID_FILE" <<'PY'
from pathlib import Path
import sys

data = Path(sys.argv[1]).read_bytes()
if data.endswith(b'\n'):
    data = data[:-1]
if not data or b'\x00' in data or b'\n' in data or any(byte < 48 or byte > 57 for byte in data):
    raise SystemExit('invalid PID file')
sys.stdout.write(data.decode('ascii'))
PY
)"
[[ "$old_pid" =~ ^[0-9]+$ && "$old_pid" -gt 1 ]]

probe_pid() {
  local pid="$1"
  if kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  if [[ -e "/proc/$pid" ]]; then
    return 2
  fi
  return 1
}

assert_pid_owner() {
  local pid="$1"
  local expected_dir expected_python resolved_python process_dir command_line process_env
  expected_dir="$(readlink -f "$CHALLENGE_DIR")"
  expected_python="$VENV/bin/python"
  resolved_python=''
  if [[ -e "$expected_python" ]]; then
    resolved_python="$(readlink -f "$expected_python" 2>/dev/null || true)"
  fi
  [[ -r "/proc/$pid/cwd" && -r "/proc/$pid/cmdline" ]]
  process_dir="$(readlink -f "/proc/$pid/cwd")"
  command_line="$(tr '\0' ' ' < "/proc/$pid/cmdline")"
  process_env="$(tr '\0' '\n' < "/proc/$pid/environ")"
  [[ "$process_dir" == "$expected_dir" || "$process_dir" == "$expected_dir/"* ]]
  if [[ -n "$resolved_python" ]]; then
    [[ "$command_line" == *"$expected_python"* || "$command_line" == *"$resolved_python"* ]]
  else
    [[ "$command_line" == *"$expected_python"* ]]
  fi
  [[ "$command_line" == *"$APP_MODULE"* ]]
  grep -Fqx -- "NYANKOFACE_SERVICE_MARKER=$SERVICE_MARKER" <<<"$process_env"
}

signal_owned_pid() {
  local pid="$1"
  local signal="$2"
  local owner_status=0
  local probe_status=0
  assert_pid_owner "$pid" || owner_status=$?
  if (( owner_status != 0 )); then
    probe_pid "$pid" || probe_status=$?
    [[ "$probe_status" -eq 1 ]] && return 0
    return 1
  fi
  if kill "-$signal" "$pid"; then
    sleep 1
    return 0
  fi
  probe_pid "$pid" || probe_status=$?
  [[ "$probe_status" -eq 1 ]]
}

pid_probe_status=0
probe_pid "$old_pid" || pid_probe_status=$?
if [[ "$pid_probe_status" -eq 2 ]]; then
  echo "旧PIDのownerを証明できません: $old_pid" >&2
  exit 1
fi
if [[ "$pid_probe_status" -eq 0 ]]; then
  if ! signal_owned_pid "$old_pid" TERM; then
    echo "bounded race check後も旧PIDを停止できません: $old_pid" >&2
    exit 1
  fi
fi

pid_probe_status=0
probe_pid "$old_pid" || pid_probe_status=$?
if [[ "$pid_probe_status" -eq 2 ]]; then
  echo "TERM後の旧PIDをprobeできません: $old_pid" >&2
  exit 1
fi
if [[ "$pid_probe_status" -eq 0 ]]; then
  if ! signal_owned_pid "$old_pid" KILL; then
    echo "bounded race check後も旧PIDを強制停止できません: $old_pid" >&2
    exit 1
  fi
fi

pid_probe_status=0
probe_pid "$old_pid" || pid_probe_status=$?
if [[ "$pid_probe_status" -eq 2 ]]; then
  echo "旧PIDの停止を証明できません: $old_pid" >&2
  exit 1
fi
if [[ "$pid_probe_status" -eq 0 ]]; then
  echo "old PID is still alive: $old_pid" >&2
  exit 1
fi
~~~

PIDが再利用されていたりprocessが終了しない場合は停止し、対象process treeを調査します。
shared shell、runner、Docker daemon、無関係なchallengeをkillして成功扱いにしません。

## stable nameが停止状態であることを証明する

stable-name routeは、別serverの成功応答やHTML error pageではなく、challengeが定義したfailure markerを返す必要があります。
Bashのcommand substitutionでNULなどのbyteが失われないようbodyをfileへ保存し、正確なbyte列を比較します。

body contractの候補は互換性のためカンマ区切りです。値そのものにカンマを含める場合は
`\\,`、バックスラッシュ自体は`\\\\`とescapeします。例えば
`READY\\, v1,OK`は、完全一致させる2候補`READY, v1`と`OK`を表します。

~~~bash
content_type_matches() {
  local actual="$1"
  local expected="$2"
  local actual_normalized
  local expected_normalized
  if [[ "$expected" == *';'* ]]; then
    actual_normalized="$(content_type_normalize "$actual")"
    expected_normalized="$(content_type_normalize "$expected")"
  else
    actual_normalized="$(content_type_normalize "${actual%%;*}")"
    expected_normalized="$(content_type_normalize "$expected")"
  fi
  [[ "$actual_normalized" == "$expected_normalized" ]]
}

content_type_trim() {
  local value="$1"
  value="$(printf '%s' "$value" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')"
  printf '%s' "$value"
}

content_type_normalize() {
  local value="$1"
  local media_type="${value%%;*}"
  local normalized
  local parameter
  local parameter_name
  local parameter_value
  local normalized_parameter
  local -a parameters
  local -a normalized_parameters
  media_type="$(content_type_trim "$media_type")"
  normalized="${media_type,,}"
  if [[ "$value" != *';'* ]]; then
    printf '%s' "$normalized"
    return
  fi
  IFS=';' read -r -a parameters <<< "${value#*;}"
  for parameter in "${parameters[@]}"; do
    parameter="$(content_type_trim "$parameter")"
    [[ -z "$parameter" ]] && continue
    if [[ "$parameter" == *=* ]]; then
      parameter_name="$(content_type_trim "${parameter%%=*}")"
      parameter_value="$(content_type_trim "${parameter#*=}")"
      normalized_parameters+=("${parameter_name,,}=${parameter_value}")
    else
      normalized_parameters+=("${parameter,,}")
    fi
  done
  if ((${#normalized_parameters[@]} > 0)); then
    while IFS= read -r normalized_parameter; do
      normalized+=";${normalized_parameter}"
    done < <(printf '%s\n' "${normalized_parameters[@]}" | LC_ALL=C sort)
  fi
  printf '%s' "$normalized"
}

content_type_in_list() {
  local actual="$1"
  local expected_list="$2"
  local expected
  local -a expected_types
  IFS=',' read -r -a expected_types <<< "$expected_list"
  for expected in "${expected_types[@]}"; do
    if content_type_matches "$actual" "$expected"; then
      return 0
    fi
  done
  return 1
}

split_body_contracts() {
  local value="$1"
  local current=''
  local char next
  local index
  for ((index = 0; index < ${#value}; index++)); do
    char="${value:index:1}"
    if [[ "$char" == "\\" && $((index + 1)) -lt ${#value} ]]; then
      next="${value:index + 1:1}"
      if [[ "$next" == ',' || "$next" == "\\" ]]; then
        current+="$next"
        index=$((index + 1))
        continue
      fi
    fi
    if [[ "$char" == ',' ]]; then
      printf '%s\0' "$current"
      current=''
    else
      current+="$char"
    fi
  done
  printf '%s\0' "$current"
}

body_contract_valid() {
  [[ "$1" == valid:* && -n "${1#valid:}" ]]
}

read_health_body_contract() {
  local body_file="$1"
  local content_type="${2,,}"
  local expected_content_types="${3:-$HEALTH_CONTENT_TYPES}"
  local expected_json_content_types="${4:-$HEALTH_JSON_CONTENT_TYPES}"
  local expected_text_content_types="${5:-$HEALTH_TEXT_CONTENT_TYPES}"
  local expected_json_status_field="${6:-$HEALTH_JSON_STATUS_FIELD}"
  local expected_body_contracts="${7:-$HEALTH_BODY_CONTRACTS}"
  local expected_text_body_contracts="${8:-$HEALTH_TEXT_BODY_CONTRACTS}"
  if ! content_type_in_list "$content_type" "$expected_content_types"; then
    printf 'invalid:content-type\n'
    return
  fi
  if content_type_in_list "$content_type" "$expected_json_content_types"; then
    "$VENV/bin/python" - "$body_file" "$expected_json_status_field" "$expected_body_contracts" <<'PY'
import json
import pathlib
import sys

try:
    def reject_constant(value):
        raise ValueError(f'non-standard JSON constant: {value}')

    value = json.loads(pathlib.Path(sys.argv[1]).read_bytes(), parse_constant=reject_constant)
except (OSError, UnicodeError, ValueError):
    print('invalid:json')
else:
    status = value.get(sys.argv[2]) if isinstance(value, dict) else None
    def split_contracts(raw):
        items = []
        current = []
        index = 0
        while index < len(raw):
            char = raw[index]
            if char == '\\' and index + 1 < len(raw) and raw[index + 1] in ',\\':
                current.append(raw[index + 1])
                index += 2
                continue
            if char == ',':
                items.append(''.join(current))
                current = []
            else:
                current.append(char)
            index += 1
        items.append(''.join(current))
        return items

    expected = {item.strip() for item in split_contracts(sys.argv[3]) if item.strip()}
    print(f'valid:{status}' if isinstance(status, str) and status in expected else 'invalid:body')
PY
    return
  fi
  if content_type_in_list "$content_type" "$expected_text_content_types"; then
    local expected_body
    local -a expected_bodies
    while IFS= read -r -d '' expected_body; do
      expected_bodies+=("$expected_body")
    done < <(split_body_contracts "$expected_text_body_contracts")
    for expected_body in "${expected_bodies[@]}"; do
      if printf '%s' "$expected_body" | cmp -s "$body_file" -; then
        printf 'valid:%s\n' "$expected_body"
        return
      fi
    done
  fi
  printf 'invalid:body\n'
}

failure_body_file="$(mktemp)"
failure_metadata="$(curl --silent --show-error --max-time 3 \
  --header "Accept: $FAILURE_CONTENT_TYPE" \
  --output "$failure_body_file" \
  --write-out $'%{http_code}\n%{content_type}' "$FAILURE_URL")" || { rm -f "$failure_body_file"; exit 1; }
failure_status="${failure_metadata%%$'\n'*}"
failure_content_type="${failure_metadata#*$'\n'}"
failure_body_matches=1
if printf '%s' '000FAIL' | cmp -s "$failure_body_file" -; then
  failure_body_matches=0
fi
failure_content_type_matches=0
if content_type_matches "$failure_content_type" "$FAILURE_CONTENT_TYPE"; then
  failure_content_type_matches=1
fi
if [[ "$failure_status" != "$FAILURE_STATUS" \
  || "$failure_body_matches" -ne 0 \
  || "$failure_content_type_matches" -ne 1 ]]; then
  rm -f "$failure_body_file"
  echo "stable nameが期待する停止状態のcontractを返しません" >&2
  exit 1
fi
rm -f "$failure_body_file"
~~~

共有するevidenceにはURL path、HTTP status、content type、marker判定だけを記録し、
internal hostname、token、challenge answerはredactします。

## 再構築して起動する

checked-in dependency lockからenvironmentを作り直します。失敗した復旧で中途半端なenvironmentを再利用しません。

~~~bash
cd "$CHALLENGE_DIR"
python3 -m venv --clear "$VENV"
"$VENV/bin/python" -m pip install --requirement requirements.txt

nohup env "NYANKOFACE_SERVICE_MARKER=$SERVICE_MARKER" "$VENV/bin/python" -m flask --app "$APP_MODULE" run \
  --host "$HOST" --port "$PORT" >"$LOG_FILE" 2>&1 &
new_pid=$!
printf '%s\n' "$new_pid" >"$PID_FILE"
~~~

project固有のlauncherが必要なら、そのlauncherを同じstable nameで使い、
`NYANKOFACE_SERVICE_MARKER=$SERVICE_MARKER`を引き継ぎ、boundedなlogとPID fileを残します。

## 固定回数でhealthを検証する

health URLは最大10回だけ確認します。processが生きていることと、期待するJSONまたはtext contractを両方確認します。
HTTP 200だけでは正しいserviceの証明になりません。

~~~bash
check_health() {
  local body_file metadata content_type body_contract http_status
  body_file="$(mktemp)"
  metadata="$(curl --silent --show-error --max-time 3 \
    --header "Accept: $HEALTH_CONTENT_TYPES" \
    --output "$body_file" \
    --write-out $'%{http_code}\n%{content_type}' "$HEALTH_URL")" || { rm -f "$body_file"; return 1; }
  http_status="${metadata%%$'\n'*}"
  content_type="${metadata#*$'\n'}"
  body_contract="$(read_health_body_contract "$body_file" "$content_type")"
  rm -f "$body_file"
  [[ "$http_status" == "$HEALTH_STATUS" ]] && body_contract_valid "$body_contract"
}

healthy=0
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if kill -0 "$new_pid" 2>/dev/null && check_health; then
    healthy=1
    break
  fi
  sleep 1
done
[[ "$healthy" -eq 1 ]] || { echo "health proof failed" >&2; exit 1; }
~~~

## proof matrixを再実行する

challengeの3段階を順番に実行し、各exit codeと別に設定したidempotent probeのresponseを記録します。
probeはstage requestそのものではなく、challenge stateを進めてはいけません。具体的なcommand名はchallenge側に依存しますが、証明の形は同じです。

~~~bash
record_stage_probe() {
  local name="$1"
  local probe_url="$2"
  local probe_method="$3"
  local probe_headers_file="$4"
  local probe_body_file="$5"
  local expected_status="$6"
  local expected_content_types="$7"
  local expected_json_content_types="$8"
  local expected_text_content_types="$9"
  local expected_json_status_field="${10}"
  local expected_body_contracts="${11}"
  local expected_text_body_contracts="${12}"
  local body_file metadata content_type body_contract body_contract_status http_status
  local -a curl_args
  body_file="$(mktemp)"
  curl_args=(--silent --show-error --max-time 3 --request "$probe_method")
  if [[ -n "$probe_headers_file" ]]; then
    [[ -f "$probe_headers_file" ]] || { rm -f "$body_file"; return 1; }
    curl_args+=(--header "@$probe_headers_file")
  else
    curl_args+=(--header "Accept: $expected_content_types")
  fi
  if [[ -n "$probe_body_file" ]]; then
    [[ -f "$probe_body_file" ]] || { rm -f "$body_file"; return 1; }
    curl_args+=(--data-binary "@$probe_body_file")
  fi
  metadata="$(curl "${curl_args[@]}" \
    --output "$body_file" \
    --write-out $'%{http_code}\n%{content_type}' "$probe_url")" || { rm -f "$body_file"; return 1; }
  http_status="${metadata%%$'\n'*}"
  content_type="${metadata#*$'\n'}"
  body_contract="$(read_health_body_contract "$body_file" "$content_type" \
    "$expected_content_types" "$expected_json_content_types" "$expected_text_content_types" \
    "$expected_json_status_field" "$expected_body_contracts" "$expected_text_body_contracts")"
  body_contract_status='invalid'
  if body_contract_valid "$body_contract"; then
    body_contract_status='matched'
  fi
  rm -f "$body_file"
  printf 'stage=%s idempotent_probe http_status=%s content_type=%s body_contract=%s\n' \
    "$name" "$http_status" "$content_type" "$body_contract_status"
  [[ "$http_status" == "$expected_status" ]] && body_contract_valid "$body_contract"
}

run_stage() {
  local name="$1"
  local probe_url="$2"
  local probe_idempotent="$3"
  local probe_method="$4"
  local probe_headers_file="$5"
  local probe_body_file="$6"
  local expected_status="$7"
  local expected_content_types="$8"
  local expected_json_content_types="$9"
  local expected_text_content_types="${10}"
  local expected_json_status_field="${11}"
  local expected_body_contracts="${12}"
  local expected_text_body_contracts="${13}"
  local stage_status=0
  shift 13
  if [[ "$probe_idempotent" != 'true' ]]; then
    echo "$name probeが明示的にidempotentと指定されていません" >&2
    return 1
  fi
  echo "== $name =="
  set +e
  "$@"
  stage_status=$?
  set -e
  printf 'stage=%s exit=%s\n' "$name" "$stage_status"
  if ! record_stage_probe "$name" "$probe_url" "$probe_method" "$probe_headers_file" \
    "$probe_body_file" "$expected_status" "$expected_content_types" \
    "$expected_json_content_types" "$expected_text_content_types" \
    "$expected_json_status_field" "$expected_body_contracts" "$expected_text_body_contracts"; then
    return 1
  fi
  return "$stage_status"
}

matrix_status=0
if ! run_stage stage-1 "$STAGE_1_PROBE_URL" "$STAGE_1_PROBE_IDEMPOTENT" "$STAGE_1_PROBE_METHOD" \
  "$STAGE_1_PROBE_HEADERS_FILE" "$STAGE_1_PROBE_BODY_FILE" "$STAGE_1_PROBE_STATUS" \
  "$STAGE_1_PROBE_CONTENT_TYPES" "$STAGE_1_PROBE_JSON_CONTENT_TYPES" "$STAGE_1_PROBE_TEXT_CONTENT_TYPES" \
  "$STAGE_1_PROBE_JSON_STATUS_FIELD" "$STAGE_1_PROBE_BODY_CONTRACTS" "$STAGE_1_PROBE_TEXT_BODY_CONTRACTS" \
  "$VENV/bin/python" scripts/stage1.py; then matrix_status=1; fi
if ! run_stage stage-2 "$STAGE_2_PROBE_URL" "$STAGE_2_PROBE_IDEMPOTENT" "$STAGE_2_PROBE_METHOD" \
  "$STAGE_2_PROBE_HEADERS_FILE" "$STAGE_2_PROBE_BODY_FILE" "$STAGE_2_PROBE_STATUS" \
  "$STAGE_2_PROBE_CONTENT_TYPES" "$STAGE_2_PROBE_JSON_CONTENT_TYPES" "$STAGE_2_PROBE_TEXT_CONTENT_TYPES" \
  "$STAGE_2_PROBE_JSON_STATUS_FIELD" "$STAGE_2_PROBE_BODY_CONTRACTS" "$STAGE_2_PROBE_TEXT_BODY_CONTRACTS" \
  "$VENV/bin/python" scripts/stage2.py; then matrix_status=1; fi
if ! run_stage stage-3 "$STAGE_3_PROBE_URL" "$STAGE_3_PROBE_IDEMPOTENT" "$STAGE_3_PROBE_METHOD" \
  "$STAGE_3_PROBE_HEADERS_FILE" "$STAGE_3_PROBE_BODY_FILE" "$STAGE_3_PROBE_STATUS" \
  "$STAGE_3_PROBE_CONTENT_TYPES" "$STAGE_3_PROBE_JSON_CONTENT_TYPES" "$STAGE_3_PROBE_TEXT_CONTENT_TYPES" \
  "$STAGE_3_PROBE_JSON_STATUS_FIELD" "$STAGE_3_PROBE_BODY_CONTRACTS" "$STAGE_3_PROBE_TEXT_BODY_CONTRACTS" \
  "$VENV/bin/python" scripts/stage3.py; then matrix_status=1; fi
if (( matrix_status != 0 )); then exit 1; fi
~~~

続けて、fail closedであるべきnegative caseを実行します。

- unknownまたはexpired token
- HTTP method違い、またはunknown route
- malformed、incomplete、oversized input
- stableでないaliasへのrequest、または想定外content type

negative resultはchallenge contractと一致し、generic proxy successに置き換わってはいけません。
stageまたはnegative testのどれかが失敗したら、復旧はunverifiedと記録し、private diagnosis用にlogを保持します。

## evidence checklist

旧PIDの停止証明、停止中の正確な`000FAIL`証明、新PID、boundedなhealth証明、
3 stageの結果、全negative-testの結果が記録されて初めてverifiedとします。
local simulationやstatic log excerptだけではlive recoveryの証明になりません。
