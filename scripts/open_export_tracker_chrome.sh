#!/usr/bin/env bash
set -euo pipefail

PORT="${1:-9222}"
PROFILE_MODE="${2:-isolated}"

"$(dirname "$0")/open_export_tracker_browser.sh" chrome "$PORT" "$PROFILE_MODE"
