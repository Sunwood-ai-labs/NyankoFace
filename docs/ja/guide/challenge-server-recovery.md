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
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:?challenge portを指定}"
HEALTH_URL="${HEALTH_URL:?stable nameのhealth URLを指定}"
FAILURE_URL="${FAILURE_URL:?stable nameのfailure URLを指定}"
PID_FILE="$CHALLENGE_DIR/run/$SERVICE_NAME.pid"
VENV="$CHALLENGE_DIR/.venv"
LOG_FILE="$CHALLENGE_DIR/run/$SERVICE_NAME.log"
mkdir -p "$(dirname "$PID_FILE")"
~~~

stable nameはchallengeごとに一意にします。任意の「最新Python」のPID、
shared process-managerのparent、別challengeにも一致するsubstringでprocessを選ばないでください。

## 旧processをkillして確認する

PID fileを読み、数字だけであることを確認して、そのPIDだけへsignalを送ります。
2回目までのbounded checkで正常停止か、停止不能かを判定します。

~~~bash
old_pid="$(tr -d '[:space:]' < "$PID_FILE")"
[[ "$old_pid" =~ ^[0-9]+$ && "$old_pid" -gt 1 ]]

if kill -0 "$old_pid" 2>/dev/null; then
  kill -TERM "$old_pid"
  sleep 1
fi

if kill -0 "$old_pid" 2>/dev/null; then
  kill -KILL "$old_pid"
  sleep 1
fi

if kill -0 "$old_pid" 2>/dev/null; then
  echo "old PID is still alive: $old_pid" >&2
  exit 1
fi
~~~

PIDが再利用されていたりprocessが終了しない場合は停止し、対象process treeを調査します。
shared shell、runner、Docker daemon、無関係なchallengeをkillして成功扱いにしません。

## stable nameが停止状態であることを証明する

stable-name routeは、別serverの成功応答やHTML error pageではなく、challengeが定義したfailure markerを返す必要があります。
bodyをmemory上で扱い、markerを完全一致させます。

~~~bash
failure_body="$(curl --silent --show-error --max-time 3 \
  --header 'Accept: text/plain' "$FAILURE_URL")"
if ! grep -Fxq '000FAIL' <<<"$failure_body"; then
  echo "stable nameが期待する000FAIL markerを返しません" >&2
  exit 1
fi
~~~

共有するevidenceにはURL path、HTTP status、content type、marker判定だけを記録し、
internal hostname、token、challenge answerはredactします。

## 再構築して起動する

checked-in dependency lockからenvironmentを作り直します。失敗した復旧で中途半端なenvironmentを再利用しません。

~~~bash
cd "$CHALLENGE_DIR"
python3 -m venv --clear "$VENV"
"$VENV/bin/python" -m pip install --requirement requirements.txt

nohup "$VENV/bin/python" -m flask --app "$APP_MODULE" run \
  --host "$HOST" --port "$PORT" >"$LOG_FILE" 2>&1 &
new_pid=$!
printf '%s\n' "$new_pid" >"$PID_FILE"
~~~

project固有のlauncherが必要なら、そのlauncherを同じstable nameで使い、boundedなlogとPID fileを残します。

## 固定回数でhealthを検証する

health URLは最大10回だけ確認します。processが生きていることと、期待するJSONまたはtext contractを両方確認します。
HTTP 200だけでは正しいserviceの証明になりません。

~~~bash
healthy=0
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if kill -0 "$new_pid" 2>/dev/null \
    && curl --silent --show-error --fail --max-time 3 "$HEALTH_URL" \
    | grep -Eq '"status"[[:space:]]*:[[:space:]]*"(ok|healthy)"|^OK$'; then
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
run_stage() {
  local name="$1"
  shift
  echo "== $name =="
  "$@"
}

run_stage stage-1 python scripts/stage1.py
run_stage stage-2 python scripts/stage2.py
run_stage stage-3 python scripts/stage3.py
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
