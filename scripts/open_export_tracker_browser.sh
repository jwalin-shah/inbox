#!/usr/bin/env bash
set -euo pipefail

BROWSER="${1:-brave}"
PORT="${2:-9222}"
PROFILE_MODE="${3:-isolated}"

case "$BROWSER" in
  brave|Brave)
    APP_NAME="Brave Browser"
    PROFILE_SLUG="brave"
    ;;
  chrome|Chrome)
    APP_NAME="Google Chrome"
    PROFILE_SLUG="chrome"
    ;;
  edge|Edge)
    APP_NAME="Microsoft Edge"
    PROFILE_SLUG="edge"
    ;;
  *)
    echo "Unknown browser: $BROWSER" >&2
    echo "Use one of: brave, chrome, edge" >&2
    exit 2
    ;;
esac

ARGS=(--remote-debugging-port="$PORT" --no-first-run)

if [[ "$PROFILE_MODE" == "isolated" ]]; then
  PROFILE_DIR="${INBOX_EXPORT_BROWSER_PROFILE:-$HOME/.local/state/inbox/${PROFILE_SLUG}-export-tracker-profile}"
  mkdir -p "$PROFILE_DIR"
  ARGS+=(--user-data-dir="$PROFILE_DIR")
elif [[ "$PROFILE_MODE" == "default" ]]; then
  PROFILE_DIR="default browser profile"
else
  echo "Unknown profile mode: $PROFILE_MODE" >&2
  echo "Use isolated or default" >&2
  exit 2
fi

open -na "$APP_NAME" --args "${ARGS[@]}"

cat <<EOF
Started $APP_NAME for export tracking.

DevTools endpoint:
  http://127.0.0.1:$PORT/json/version

Profile mode:
  $PROFILE_MODE ($PROFILE_DIR)

Tracker:
  scripts/track_data_export_browser.py --once

Open priority export pages:
  scripts/request_personal_data_exports.py --priority
EOF
