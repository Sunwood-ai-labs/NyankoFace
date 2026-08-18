---
title: Challenge server recovery
type: guide
description: A bounded kill, recovery, and proof procedure for challenge Flask servers.
readingTime: 6 min
tags: [operations, recovery, testing]
related:
  - title: Operations
    link: /guide/operations
  - title: Troubleshooting
    link: /guide/troubleshooting
---

# Challenge server recovery

This runbook is for a challenge server that is started from a local checkout or
an isolated runner. It describes the recovery boundary without assuming a
particular challenge repository, host, port, or credential. Replace the
uppercase placeholders locally; never commit them or paste their values into a
public issue.

The recovery contract is deliberately ordered:

1. identify one exact process by its stable service name and PID file;
2. kill it and prove that the old PID is gone;
3. prove the stable name returns the expected `000FAIL` marker while stopped;
4. rebuild the virtual environment and relaunch the same service name;
5. prove health, the three-stage challenge flow, and negative cases.

## Set the bounded inputs

Run from the challenge checkout. The commands below use a fixed retry budget;
do not turn them into an unbounded watcher.

~~~bash
set -euo pipefail

CHALLENGE_DIR="${CHALLENGE_DIR:?set this to the challenge checkout}"
SERVICE_NAME="${SERVICE_NAME:?set the stable challenge service name}"
APP_MODULE="${APP_MODULE:?set the Flask app module}"
SERVICE_MARKER="${SERVICE_MARKER:-nyankoface:$SERVICE_NAME}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:?set the challenge port}"
HEALTH_URL="${HEALTH_URL:?set the stable-name health URL}"
HEALTH_STATUS="${HEALTH_STATUS:?set the expected health HTTP status}"
HEALTH_CONTENT_TYPES="${HEALTH_CONTENT_TYPES:-application/json,text/plain}"
HEALTH_JSON_CONTENT_TYPES="${HEALTH_JSON_CONTENT_TYPES:-application/json}"
HEALTH_TEXT_CONTENT_TYPES="${HEALTH_TEXT_CONTENT_TYPES:-text/plain}"
HEALTH_JSON_STATUS_FIELD="${HEALTH_JSON_STATUS_FIELD:-status}"
HEALTH_BODY_CONTRACTS="${HEALTH_BODY_CONTRACTS:-ok,healthy,OK}"
HEALTH_TEXT_BODY_CONTRACTS="${HEALTH_TEXT_BODY_CONTRACTS:-OK}"
STAGE_1_PROBE_URL="${STAGE_1_PROBE_URL:?set the idempotent stage-1 probe URL}"
STAGE_1_PROBE_IDEMPOTENT="${STAGE_1_PROBE_IDEMPOTENT:?set stage-1 probe idempotence to true}"
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
STAGE_2_PROBE_URL="${STAGE_2_PROBE_URL:?set the idempotent stage-2 probe URL}"
STAGE_2_PROBE_IDEMPOTENT="${STAGE_2_PROBE_IDEMPOTENT:?set stage-2 probe idempotence to true}"
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
STAGE_3_PROBE_URL="${STAGE_3_PROBE_URL:?set the idempotent stage-3 probe URL}"
STAGE_3_PROBE_IDEMPOTENT="${STAGE_3_PROBE_IDEMPOTENT:?set stage-3 probe idempotence to true}"
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
FAILURE_URL="${FAILURE_URL:?set the stable-name failure URL}"
FAILURE_STATUS="${FAILURE_STATUS:?set the expected stopped-state HTTP status}"
FAILURE_CONTENT_TYPE="${FAILURE_CONTENT_TYPE:?set the expected stopped-state content type}"
PID_FILE="$CHALLENGE_DIR/run/$SERVICE_NAME.pid"
VENV="$CHALLENGE_DIR/.venv"
LOG_FILE="$CHALLENGE_DIR/run/$SERVICE_NAME.log"
mkdir -p "$(dirname "$PID_FILE")"
~~~

The default health contract accepts JSON `status` values `ok`, `healthy`, or
`OK`, and an exact plain-text `OK` body. For another challenge, configure
`HEALTH_CONTENT_TYPES`, `HEALTH_JSON_CONTENT_TYPES`,
`HEALTH_TEXT_CONTENT_TYPES`, `HEALTH_JSON_STATUS_FIELD`, and the comma-separated
`HEALTH_BODY_CONTRACTS` values. Set `HEALTH_TEXT_BODY_CONTRACTS` separately for
exact text responses. For each stage, set an idempotent `STAGE_n_PROBE_URL`,
set `STAGE_n_PROBE_IDEMPOTENT=true` only after independently confirming that
the probe cannot consume a nonce or mutate challenge state, and configure its
method, optional `STAGE_n_PROBE_HEADERS_FILE` (one complete header per line),
and optional `STAGE_n_PROBE_BODY_FILE`. An empty header-file value uses the
configured content types as the `Accept` header. Set the probe-specific status,
content-type, JSON field, and body-contract variables when a probe differs from
the health contract. The stage command runs once; the proof then calls only the
separate idempotent probe. It never replays a mutating stage request. If the
stage response itself must be verified, have the stage command capture and
validate that response as a challenge-specific artifact instead of using this
probe.

Use a stable name that is unique to this challenge. Do not identify a process
by an arbitrary “latest Python” PID, a shared process-manager parent, or a
substring that could match another challenge.

## Kill and verify the old process

Read the PID file, validate that it contains only digits, and prove the
process identity before every signal. The proof checks the challenge checkout,
the rebuilt interpreter, and the app/service marker. A second bounded check is
enough to distinguish a clean stop from a stuck process.

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
  echo "cannot prove ownership of old PID: $old_pid" >&2
  exit 1
fi
if [[ "$pid_probe_status" -eq 0 ]]; then
  if ! signal_owned_pid "$old_pid" TERM; then
    echo "could not stop the owned old PID after a bounded race check: $old_pid" >&2
    exit 1
  fi
fi

pid_probe_status=0
probe_pid "$old_pid" || pid_probe_status=$?
if [[ "$pid_probe_status" -eq 2 ]]; then
  echo "cannot probe old PID after TERM: $old_pid" >&2
  exit 1
fi
if [[ "$pid_probe_status" -eq 0 ]]; then
  if ! signal_owned_pid "$old_pid" KILL; then
    echo "could not force-stop the owned old PID after a bounded race check: $old_pid" >&2
    exit 1
  fi
fi

pid_probe_status=0
probe_pid "$old_pid" || pid_probe_status=$?
if [[ "$pid_probe_status" -eq 2 ]]; then
  echo "cannot prove old PID stopped: $old_pid" >&2
  exit 1
fi
if [[ "$pid_probe_status" -eq 0 ]]; then
  echo "old PID is still alive: $old_pid" >&2
  exit 1
fi
~~~

If the PID is reused or the process does not exit, stop here and investigate
the exact process tree. Never kill a shared shell, runner, Docker daemon, or
unrelated challenge to force this step to pass.

## Prove the stable name is stopped

The stable-name route must return the challenge's documented failure marker,
not an HTML error page or a successful response from a different server. Capture
the body in a file so the exact byte sequence is compared without Bash
command-substitution loss.

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
  local -a parameters
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
      normalized+=";${parameter_name,,}=${parameter_value}"
    else
      normalized+=";${parameter,,}"
    fi
  done
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
    expected = {item.strip() for item in sys.argv[3].split(',') if item.strip()}
    print(f'valid:{status}' if isinstance(status, str) and status in expected else 'invalid:body')
PY
    return
  fi
  if content_type_in_list "$content_type" "$expected_text_content_types"; then
    local expected_body
    local -a expected_bodies
    IFS=',' read -r -a expected_bodies <<< "$expected_text_body_contracts"
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
  echo "stable name did not return the expected stopped-state contract" >&2
  exit 1
fi
rm -f "$failure_body_file"
~~~

Record the URL path, HTTP status, content type, and marker result, but redact
internal hostnames, tokens, and challenge answers from shared evidence.

## Rebuild and relaunch

Recreate the environment from the checked-in dependency lock. Do not reuse a
partially built environment after a failed recovery.

~~~bash
cd "$CHALLENGE_DIR"
python3 -m venv --clear "$VENV"
"$VENV/bin/python" -m pip install --requirement requirements.txt

nohup env "NYANKOFACE_SERVICE_MARKER=$SERVICE_MARKER" "$VENV/bin/python" -m flask --app "$APP_MODULE" run \
  --host "$HOST" --port "$PORT" >"$LOG_FILE" 2>&1 &
new_pid=$!
printf '%s\n' "$new_pid" >"$PID_FILE"
~~~

Keep the launch command and PID file in the same recovery record. If the app
needs a project-specific launcher, use that launcher with the same stable
name, propagate `NYANKOFACE_SERVICE_MARKER=$SERVICE_MARKER`, and preserve the
bounded output log.

## Prove health with a fixed budget

Check the health URL at most ten times. The process must be alive and the
response must be the expected JSON or text contract; an HTTP 200 alone is not
proof of the right service.

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

## Rerun the proof matrix

Run the challenge's three stages in order and record each exit code plus the
response from its separately configured idempotent probe. The exact command
names belong to the challenge; the shape of the proof does not. The probe is
not the stage request and must not advance challenge state.

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
    echo "$name probe is not explicitly marked idempotent" >&2
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

Then run negative cases that must fail closed:

- an unknown or expired token;
- the wrong HTTP method or an unknown route;
- malformed, incomplete, or oversized input;
- a request sent to a non-stable alias or an unexpected content type.

The negative result must match the challenge contract and must not be replaced
by a generic proxy success. If any stage or negative test fails, mark recovery
unverified and keep the logs for private diagnosis.

## Evidence checklist

The recovery is verified only when the record contains the old PID stop proof,
the exact `000FAIL` stopped-state proof, the new PID, the bounded health proof,
all three stage results, and every negative-test result. A local simulation or
a static log excerpt is not a live recovery proof.
