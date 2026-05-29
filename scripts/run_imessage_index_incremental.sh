#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"

ENV_FILE="${INBOX_ENV_FILE:-${INBOX_WORKFLOWS_ENV:-$ROOT_DIR/config/inbox.env}}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  . "$ENV_FILE"
  set +a
fi

export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"
export INBOX_DISABLE_IMESSAGE_SYNC="${INBOX_DISABLE_IMESSAGE_SYNC:-0}"

exec uv run python message_sync.py imessage-incremental
