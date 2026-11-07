#!/bin/bash
# Install macOS LaunchAgent for EasyPaper gloss-worker (user session, restarts on crash / login).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
RUN_SCRIPT="${SCRIPT_DIR}/gloss-worker-run.sh"
CONFIG_DIR="${HOME}/.config/easypaper"
LOG_DIR="${HOME}/Library/Logs/EasyPaper"
PLIST_DEST="${HOME}/Library/LaunchAgents/com.easypaper.gloss-worker.plist"
LABEL="com.easypaper.gloss-worker"

mkdir -p "${CONFIG_DIR}" "${LOG_DIR}" "${HOME}/Library/LaunchAgents"
chmod +x "${RUN_SCRIPT}"

ENV_FILE="${CONFIG_DIR}/gloss-worker.env"
TOKEN_FILE="${CONFIG_DIR}/gloss-worker.token"

if [[ ! -f "${ENV_FILE}" ]]; then
  sed "s|/path/to/EasyPaper|${REPO_ROOT}|g" "${SCRIPT_DIR}/gloss-worker.env.example" > "${ENV_FILE}"
  chmod 600 "${ENV_FILE}"
  echo "Wrote ${ENV_FILE}"
fi

if [[ ! -f "${TOKEN_FILE}" ]]; then
  if [[ -f /tmp/easypaper-worker-token.txt ]]; then
    cp /tmp/easypaper-worker-token.txt "${TOKEN_FILE}"
  elif [[ -n "${GLOSS_WORKER_TOKEN:-}" ]]; then
    printf '%s' "${GLOSS_WORKER_TOKEN}" > "${TOKEN_FILE}"
  else
    echo "Paste GLOSS_WORKER_TOKEN from the server .env (same as gloss_worker.token), then rerun:"
    echo "  printf '%s' 'YOUR_TOKEN' > ${TOKEN_FILE} && chmod 600 ${TOKEN_FILE} && $0"
    exit 1
  fi
  chmod 600 "${TOKEN_FILE}"
  echo "Wrote ${TOKEN_FILE}"
fi

# Patch repo path if checkout moved.
if grep -q '/path/to/EasyPaper' "${ENV_FILE}" 2>/dev/null; then
  sed -i '' "s|/path/to/EasyPaper|${REPO_ROOT}|g" "${ENV_FILE}"
fi

sed \
  -e "s|__RUN_SCRIPT__|${RUN_SCRIPT}|g" \
  -e "s|__LOG_DIR__|${LOG_DIR}|g" \
  -e "s|__HOME__|${HOME}|g" \
  "${SCRIPT_DIR}/com.easypaper.gloss-worker.plist.template" > "${PLIST_DEST}"

launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
pkill -f 'python -m app.cli gloss-worker' 2>/dev/null || true
sleep 1

launchctl bootstrap "gui/$(id -u)" "${PLIST_DEST}"
launchctl enable "gui/$(id -u)/${LABEL}"
launchctl kickstart -k "gui/$(id -u)/${LABEL}"

echo "Installed LaunchAgent ${LABEL}"
echo "  plist: ${PLIST_DEST}"
echo "  logs:  ${LOG_DIR}/gloss-worker.{out,err}.log"
echo "  status: launchctl print gui/$(id -u)/${LABEL}"
