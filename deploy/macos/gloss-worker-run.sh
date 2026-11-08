#!/bin/bash
# launchd entry: load secrets from ~/.config/easypaper/gloss-worker.env and run the worker.
set -euo pipefail

CONFIG_DIR="${HOME}/.config/easypaper"
ENV_FILE="${CONFIG_DIR}/gloss-worker.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "gloss-worker-run: missing ${ENV_FILE} (run deploy/macos/install-gloss-worker-launchd.sh)" >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a
source "${ENV_FILE}"
set +a

if [[ -z "${EASYPAPER_REPO:-}" || ! -d "${EASYPAPER_REPO}/backend" ]]; then
  echo "gloss-worker-run: EASYPAPER_REPO must point at the EasyPaper checkout" >&2
  exit 1
fi

BACKEND="${EASYPAPER_REPO}/backend"
VENV="${BACKEND}/.venv/bin/python"
if [[ ! -x "${VENV}" ]]; then
  echo "gloss-worker-run: backend venv missing at ${VENV}" >&2
  exit 1
fi

TOKEN="${GLOSS_WORKER_TOKEN:-}"
if [[ -z "${TOKEN}" && -n "${GLOSS_WORKER_TOKEN_FILE:-}" && -f "${GLOSS_WORKER_TOKEN_FILE}" ]]; then
  TOKEN="$(tr -d ' \n\r' < "${GLOSS_WORKER_TOKEN_FILE}")"
fi
if [[ -z "${TOKEN}" ]]; then
  echo "gloss-worker-run: set GLOSS_WORKER_TOKEN or GLOSS_WORKER_TOKEN_FILE" >&2
  exit 1
fi

export APP_CONFIG_PATH="${APP_CONFIG_PATH:-${BACKEND}/config/config.yaml}"
export EASYPAPER_SERVER_URL="${EASYPAPER_SERVER_URL:?}"
export EASYPAPER_GLOSS_CONCURRENCY="${EASYPAPER_GLOSS_CONCURRENCY:-4}"
export EASYPAPER_KNOWLEDGE_CONCURRENCY="${EASYPAPER_KNOWLEDGE_CONCURRENCY:-6}"
export KNOWLEDGE_WORKER_TOKEN="${KNOWLEDGE_WORKER_TOKEN:-${TOKEN}}"
export EASYPAPER_AI_PROVIDER="${EASYPAPER_AI_PROVIDER:-cursor}"
export EASYPAPER_CURSOR_EXECUTABLE="${EASYPAPER_CURSOR_EXECUTABLE:-${HOME}/.local/bin/cursor-j}"
export EASYPAPER_CURSOR_MODEL="${EASYPAPER_CURSOR_MODEL:-grok-4.7-high-fast}"
export EASYPAPER_CURSOR_MAX_CONCURRENT="${EASYPAPER_CURSOR_MAX_CONCURRENT:-4}"
export CURSOR_J_KEY_FILE="${CURSOR_J_KEY_FILE:-${HOME}/.config/cursor-j/api-key}"
export CURSOR_CONFIG_DIR="${CURSOR_CONFIG_DIR:-${HOME}/.config/cursor-j}"
export CURSOR_DATA_DIR="${CURSOR_DATA_DIR:-${HOME}/.local/share/cursor-j/data}"
export GLOSS_WORKER_TOKEN="${TOKEN}"

LABEL="${GLOSS_WORKER_LABEL:-mac-worker}"
POLL="${EASYPAPER_GLOSS_WORKER_POLL_SECONDS:-5}"

cd "${BACKEND}"
exec "${VENV}" -m app.cli local-worker \
  --base-url "${EASYPAPER_SERVER_URL}" \
  --gloss-token "${GLOSS_WORKER_TOKEN}" \
  --knowledge-token "${KNOWLEDGE_WORKER_TOKEN}" \
  --gloss-label "${LABEL}" \
  --knowledge-label "${LABEL}-knowledge" \
  --poll-seconds "${POLL}"
