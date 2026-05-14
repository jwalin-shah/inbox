#!/usr/bin/env bash
set -euo pipefail

PORT="${1:-9223}"
PROFILE_MODE="${2:-default}"

ARGS=(
  --remote-debugging-port="$PORT"
  --no-first-run
  "https://web.whatsapp.com/"
)

if [[ "$PROFILE_MODE" == "isolated" ]]; then
  PROFILE_DIR="${INBOX_WHATSAPP_BROWSER_PROFILE:-$HOME/.local/state/inbox/brave-whatsapp-scanner-profile}"
  mkdir -p "$PROFILE_DIR"
  ARGS=(--remote-debugging-port="$PORT" --user-data-dir="$PROFILE_DIR" --no-first-run "https://web.whatsapp.com/")
elif [[ "$PROFILE_MODE" == "default" ]]; then
  PROFILE_DIR="default Brave profile"
else
  echo "Unknown profile mode: $PROFILE_MODE" >&2
  echo "Use default or isolated" >&2
  exit 2
fi

open -na "Brave Browser" --args "${ARGS[@]}"

cat <<EOF
Started Brave for WhatsApp scanning.

DevTools endpoint:
  http://127.0.0.1:$PORT/json/version

Profile mode:
  $PROFILE_MODE ($PROFILE_DIR)

Run:
  uv run python scripts/whatsapp_web_scanner.py --cdp-url http://127.0.0.1:$PORT --click-visible 10 --sync-index

If WhatsApp shows a QR code, either pair it once or rerun this helper with the default profile:
  scripts/open_whatsapp_scanner_browser.sh $PORT default
EOF
