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
export WACLI_STORE_DIR="${WACLI_STORE_DIR:-$HOME/.wacli}"

if ! command -v wacli >/dev/null 2>&1; then
  echo "wacli is not installed. Run: brew install openclaw/tap/wacli" >&2
  exit 127
fi

if ! wacli doctor 2>/dev/null | grep -q "AUTHENTICATED[[:space:]]*true"; then
  echo "wacli is not authenticated. Run: wacli auth" >&2
  exit 2
fi

wacli sync --once --idle-exit "${WACLI_IDLE_EXIT:-30s}" --refresh-contacts --refresh-groups
uv run python scripts/import_wacli_to_openhuman.py --sync-index
