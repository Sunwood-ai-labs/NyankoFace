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
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:?set the challenge port}"
HEALTH_URL="${HEALTH_URL:?set the stable-name health URL}"
FAILURE_URL="${FAILURE_URL:?set the stable-name failure URL}"
PID_FILE="$CHALLENGE_DIR/run/$SERVICE_NAME.pid"
VENV="$CHALLENGE_DIR/.venv"
LOG_FILE="$CHALLENGE_DIR/run/$SERVICE_NAME.log"
mkdir -p "$(dirname "$PID_FILE")"
~~~

Use a stable name that is unique to this challenge. Do not identify a process
by an arbitrary “latest Python” PID, a shared process-manager parent, or a
substring that could match another challenge.

## Kill and verify the old process

Read the PID file, validate that it contains only digits, and signal only that
PID. A second bounded check is enough to distinguish a clean stop from a
stuck process.

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

If the PID is reused or the process does not exit, stop here and investigate
the exact process tree. Never kill a shared shell, runner, Docker daemon, or
unrelated challenge to force this step to pass.

## Prove the stable name is stopped

The stable-name route must return the challenge's documented failure marker,
not an HTML error page or a successful response from a different server. Keep
the response body in memory and compare the exact marker.

~~~bash
failure_body="$(curl --silent --show-error --max-time 3 \
  --header 'Accept: text/plain' "$FAILURE_URL")"
if ! grep -Fxq '000FAIL' <<<"$failure_body"; then
  echo "stable name did not return the expected 000FAIL marker" >&2
  exit 1
fi
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

nohup "$VENV/bin/python" -m flask --app "$APP_MODULE" run \
  --host "$HOST" --port "$PORT" >"$LOG_FILE" 2>&1 &
new_pid=$!
printf '%s\n' "$new_pid" >"$PID_FILE"
~~~

Keep the launch command and PID file in the same recovery record. If the app
needs a project-specific launcher, use that launcher with the same stable
name and preserve the bounded output log.

## Prove health with a fixed budget

Check the health URL at most ten times. The process must be alive and the
response must be the expected JSON or text contract; an HTTP 200 alone is not
proof of the right service.

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

## Rerun the proof matrix

Run the challenge's three stages in order and capture each exit code and
stable-name response. The exact command names belong to the challenge; the
shape of the proof does not.

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
