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
`HEALTH_BODY_CONTRACTS` values before running the proof.

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

if kill -0 "$old_pid" 2>/dev/null; then
  assert_pid_owner "$old_pid"
  kill -TERM "$old_pid"
  sleep 1
fi

if kill -0 "$old_pid" 2>/dev/null; then
  assert_pid_owner "$old_pid"
  kill -KILL "$old_pid"
  sleep 1
fi

if kill -0 "$old_pid" 2>/dev/null; then
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
  [[ "$1" != 'unexpected' && "$1" != 'invalid-json' && -n "$1" ]]
}

read_health_body_contract() {
  local body_file="$1"
  local content_type="${2,,}"
  if ! content_type_in_list "$content_type" "$HEALTH_CONTENT_TYPES"; then
    printf 'unexpected\n'
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
    print(status if isinstance(status, str) and status in expected else 'unexpected')
PY
    return
  fi
  if content_type_in_list "$content_type" "$HEALTH_TEXT_CONTENT_TYPES"; then
    local expected_body
    local -a expected_bodies
    IFS=',' read -r -a expected_bodies <<< "$HEALTH_BODY_CONTRACTS"
    for expected_body in "${expected_bodies[@]}"; do
      if printf '%s' "$expected_body" | cmp -s "$body_file" -; then
        printf '%s\n' "$expected_body"
        return
      fi
    done
  fi
  printf 'unexpected\n'
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

Run the challenge's three stages in order and capture each exit code and
stable-name response. The exact command names belong to the challenge; the
shape of the proof does not.

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
  rm -f "$body_file"
  printf 'stage=%s stable-name http_status=%s content_type=%s body_contract=%s\n' \
    "$name" "$http_status" "$content_type" "$body_contract"
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

run_stage stage-1 "$VENV/bin/python" scripts/stage1.py
run_stage stage-2 "$VENV/bin/python" scripts/stage2.py
run_stage stage-3 "$VENV/bin/python" scripts/stage3.py
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
