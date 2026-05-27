#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${INBOX_WORKFLOWS_ENV:-$HOME/.config/raycast/inbox-workflows.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  . "$ENV_FILE"
  set +a
fi

export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"
export INBOX_SERVER_ALLOW_UNAUTHENTICATED="${INBOX_SERVER_ALLOW_UNAUTHENTICATED:-0}"
export INBOX_START_SCHEDULER="${INBOX_START_SCHEDULER:-0}"
export INBOX_DISABLE_AMBIENT="${INBOX_DISABLE_AMBIENT:-1}"
export INBOX_DISABLE_IMESSAGE_SYNC="${INBOX_DISABLE_IMESSAGE_SYNC:-1}"

exec uv run python inbox_server.py
