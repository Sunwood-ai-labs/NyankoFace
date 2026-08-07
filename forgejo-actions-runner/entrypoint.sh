#!/bin/sh
set -eu

DATA_DIR=/data
TOKEN_FILE=/shared/actions-runner-token
CONFIG_FILE="${DATA_DIR}/config.yml"
RUNNER_CAPACITY="${FORGEJO_RUNNER_CAPACITY:-2}"
JOB_CPUS="${FORGEJO_JOB_CPUS:-2}"
JOB_MEMORY="${FORGEJO_JOB_MEMORY:-4g}"
JOB_PIDS_LIMIT="${FORGEJO_JOB_PIDS_LIMIT:-512}"

case "${RUNNER_CAPACITY}:${JOB_CPUS}:${JOB_MEMORY}:${JOB_PIDS_LIMIT}" in
  *[!0-9.:a-zA-Z_-]*)
    echo "[forgejo-actions-runner] Invalid runner resource limit." >&2
    exit 2
    ;;
esac

mkdir -p "${DATA_DIR}"

cat > "${CONFIG_FILE}" <<EOF
runner:
  capacity: ${RUNNER_CAPACITY}
  labels:
    - node20:docker://node:20-bookworm
container:
  # Empty means a dedicated bridge per job. "forgejo" resolves to that
  # bridge's gateway, where the DinD forwarder exposes only Forgejo port 3000.
  network: ""
  docker_host: "-"
  options: >-
    --cpus ${JOB_CPUS}
    --memory ${JOB_MEMORY}
    --pids-limit ${JOB_PIDS_LIMIT}
    --cap-drop NET_RAW
    --add-host forgejo:host-gateway
EOF

if [ ! -f "${DATA_DIR}/.runner" ]; then
  echo "[forgejo-actions-runner] Waiting for runner registration token..."
  while [ ! -s "${TOKEN_FILE}" ]; do
    sleep 2
  done

  forgejo-runner register \
    --no-interactive \
    --instance "${FORGEJO_INSTANCE_URL}" \
    --token "$(cat "${TOKEN_FILE}")" \
    --name "${FORGEJO_RUNNER_NAME}" \
    --labels "node20:docker://node:20-bookworm"
fi

exec forgejo-runner daemon --config "${CONFIG_FILE}"
