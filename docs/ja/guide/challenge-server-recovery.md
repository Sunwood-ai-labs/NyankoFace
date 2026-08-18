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
`HEALTH_BODY_CONTRACTS`を設定してください。

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

pid_probe_status=1
probe_pid "$old_pid" || pid_probe_status=$?
if [[ "$pid_probe_status" -eq 2 ]]; then
  echo "旧PIDのownerを証明できません: $old_pid" >&2
  exit 1
fi
if [[ "$pid_probe_status" -eq 0 ]]; then
  assert_pid_owner "$old_pid"
  kill -TERM "$old_pid"
  sleep 1
fi

pid_probe_status=1
probe_pid "$old_pid" || pid_probe_status=$?
if [[ "$pid_probe_status" -eq 2 ]]; then
  echo "TERM後の旧PIDをprobeできません: $old_pid" >&2
  exit 1
fi
if [[ "$pid_probe_status" -eq 0 ]]; then
  assert_pid_owner "$old_pid"
  kill -KILL "$old_pid"
  sleep 1
fi

pid_probe_status=1
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

~~~bash
content_type_matches() {
  local actual="${1,,}"
  local expected="${2,,}"
  actual="${actual%%;*}"
  expected="${expected%%;*}"
  actual="$(printf '%s' "$actual" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')"
  expected="$(printf '%s' "$expected" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')"
  [[ "$actual" == "$expected" ]]
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

body_contract_valid() {
  [[ "$1" == valid:* && -n "${1#valid:}" ]]
}

body_contract_value() {
  if [[ "$1" == valid:* ]]; then
    printf '%s' "${1#valid:}"
  else
    printf '%s' "$1"
  fi
}

read_health_body_contract() {
  local body_file="$1"
  local content_type="${2,,}"
  if ! content_type_in_list "$content_type" "$HEALTH_CONTENT_TYPES"; then
    printf 'invalid:content-type\n'
    return
  fi
  if content_type_in_list "$content_type" "$HEALTH_JSON_CONTENT_TYPES"; then
    "$VENV/bin/python" - "$body_file" "$HEALTH_JSON_STATUS_FIELD" "$HEALTH_BODY_CONTRACTS" <<'PY'
import json
import pathlib
import sys

try:
    value = json.loads(pathlib.Path(sys.argv[1]).read_bytes())
except (OSError, UnicodeError, ValueError):
    print('invalid-json')
else:
    status = value.get(sys.argv[2]) if isinstance(value, dict) else None
    expected = {item.strip() for item in sys.argv[3].split(',') if item.strip()}
    print(f'valid:{status}' if isinstance(status, str) and status in expected else 'invalid:body')
PY
    return
  fi
  if content_type_in_list "$content_type" "$HEALTH_TEXT_CONTENT_TYPES"; then
    local expected_body
    local -a expected_bodies
    IFS=',' read -r -a expected_bodies <<< "$HEALTH_BODY_CONTRACTS"
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

challengeの3段階を順番に実行し、各exit codeとstable-name responseを記録します。具体的なcommand名はchallenge側に依存しますが、証明の形は同じです。

~~~bash
record_stable_response() {
  local name="$1"
  local body_file metadata content_type body_contract http_status
  body_file="$(mktemp)"
  metadata="$(curl --silent --show-error --max-time 3 \
    --header "Accept: $HEALTH_CONTENT_TYPES" \
    --output "$body_file" \
    --write-out $'%{http_code}\n%{content_type}' "$HEALTH_URL")" || { rm -f "$body_file"; return 1; }
  http_status="${metadata%%$'\n'*}"
  content_type="${metadata#*$'\n'}"
  body_contract="$(read_health_body_contract "$body_file" "$content_type")"
  contract_value="$(body_contract_value "$body_contract")"
  rm -f "$body_file"
  printf 'stage=%s stable-name http_status=%s content_type=%s body_contract=%s\n' \
    "$name" "$http_status" "$content_type" "$contract_value"
  [[ "$http_status" == "$HEALTH_STATUS" ]] && body_contract_valid "$body_contract"
}

run_stage() {
  local name="$1"
  local stage_status=0
  shift
  echo "== $name =="
  set +e
  "$@"
  stage_status=$?
  set -e
  printf 'stage=%s exit=%s\n' "$name" "$stage_status"
  if ! record_stable_response "$name"; then
    return 1
  fi
  return "$stage_status"
}

matrix_status=0
if ! run_stage stage-1 "$VENV/bin/python" scripts/stage1.py; then matrix_status=1; fi
if ! run_stage stage-2 "$VENV/bin/python" scripts/stage2.py; then matrix_status=1; fi
if ! run_stage stage-3 "$VENV/bin/python" scripts/stage3.py; then matrix_status=1; fi
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
