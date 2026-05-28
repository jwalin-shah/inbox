#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${INBOX_WORKFLOWS_ENV:-$HOME/.config/raycast/inbox-workflows.env}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  . "$ENV_FILE"
  set +a
fi

INBOX_SERVER_URL="${INBOX_SERVER_URL:-http://127.0.0.1:9849}"
INBOX_SERVER_TOKEN="${INBOX_SERVER_TOKEN:-}"
export INBOX_START_SCHEDULER="${INBOX_START_SCHEDULER:-0}"
export INBOX_DISABLE_AMBIENT="${INBOX_DISABLE_AMBIENT:-1}"
export INBOX_DISABLE_IMESSAGE_SYNC="${INBOX_DISABLE_IMESSAGE_SYNC:-0}"

if ! curl -fsS --max-time 2 "$INBOX_SERVER_URL/health" >/dev/null; then
  launchctl kickstart -k "gui/$(id -u)/com.jwalin.inbox.backend" 2>/dev/null || true
  deadline=$((SECONDS + 45))
  until curl -fsS --max-time 2 "$INBOX_SERVER_URL/health" >/dev/null; do
    if (( SECONDS >= deadline )); then
      echo "Inbox backend did not become healthy at $INBOX_SERVER_URL" >&2
      exit 1
    fi
    sleep 1
  done
fi

auth_args=()
if [[ -n "$INBOX_SERVER_TOKEN" ]]; then
  auth_args=(-H "Authorization: Bearer $INBOX_SERVER_TOKEN")
fi

curl -fsS \
  --max-time "${INBOX_INDEX_SYNC_TIMEOUT:-120}" \
  -X POST \
  "${auth_args[@]}" \
  "$INBOX_SERVER_URL/index/sync/incremental"

printf '\n'
