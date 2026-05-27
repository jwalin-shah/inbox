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

PORT="${INBOX_WHATSAPP_CDP_PORT:-9223}"
CDP_URL="${INBOX_WHATSAPP_CDP_URL:-http://127.0.0.1:$PORT}"
PROFILE_MODE="${INBOX_WHATSAPP_PROFILE_MODE:-isolated}"
CLICK_VISIBLE="${INBOX_WHATSAPP_CLICK_VISIBLE:-15}"
SCROLL_PAGES="${INBOX_WHATSAPP_SCROLL_PAGES:-0}"
IDB_LIMIT="${INBOX_WHATSAPP_IDB_LIMIT:-10000}"
STRICT="${INBOX_WHATSAPP_SCAN_STRICT:-0}"
UV_BIN="${INBOX_UV_BIN:-/opt/homebrew/bin/uv}"
if [[ ! -x "$UV_BIN" ]]; then
  UV_BIN="$(command -v uv || true)"
fi

if [[ -z "$UV_BIN" ]]; then
  echo "uv not found; leaving existing WhatsApp data in place." >&2
  if [[ "$STRICT" == "1" ]]; then
    exit 1
  fi
  exit 0
fi

if ! curl -fsS --max-time 2 "$CDP_URL/json/version" >/dev/null; then
  scripts/open_whatsapp_scanner_browser.sh "$PORT" "$PROFILE_MODE" >/dev/null
  sleep "${INBOX_WHATSAPP_BROWSER_START_DELAY:-10}"
fi

if ! curl -fsS --max-time 2 "$CDP_URL/json/version" >/dev/null; then
  echo "WhatsApp scanner browser is not reachable at $CDP_URL; leaving existing data in place." >&2
  if [[ "$STRICT" == "1" ]]; then
    exit 1
  fi
  exit 0
fi

set +e
"$UV_BIN" run python scripts/whatsapp_web_scanner.py \
  --cdp-url "$CDP_URL" \
  --idb \
  --idb-limit "$IDB_LIMIT" \
  --click-visible "$CLICK_VISIBLE" \
  --scroll-pages "$SCROLL_PAGES" \
  --sync-index
status=$?
set -e

if [[ "$status" -eq 0 ]]; then
  exit 0
fi

echo "WhatsApp scanner exited with $status; leaving existing data in place." >&2
if [[ "$STRICT" == "1" ]]; then
  exit "$status"
fi
exit 0
