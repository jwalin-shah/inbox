#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_ENV="${INBOX_SERVER_ENV:-$HOME/.config/inbox/server.env}"
BASE_URL="${INBOX_SERVER_URL:-http://127.0.0.1:9849}"
START=0

usage() {
  cat <<'EOF'
Usage: scripts/restore_google_oauth.sh [--start]

Diagnose Inbox Google OAuth readiness. With --start, call /accounts/add on the
local Inbox server, which opens the browser OAuth flow and waits for completion.

Requirements:
  - Inbox server running on INBOX_SERVER_URL, default http://127.0.0.1:9849
  - INBOX_SERVER_TOKEN available in the environment or ~/.config/inbox/server.env
  - credentials.json present in the inbox repo

After browser OAuth completes, re-run:
  scripts/restore_google_oauth.sh
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --start)
      START=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "${INBOX_SERVER_TOKEN:-}" && -f "$SERVER_ENV" ]]; then
  # shellcheck disable=SC1090
  source "$SERVER_ENV"
fi

if [[ -z "${INBOX_SERVER_TOKEN:-}" ]]; then
  echo "INBOX_SERVER_TOKEN is missing. Expected it in env or $SERVER_ENV." >&2
  exit 2
fi

if [[ ! -f "$ROOT/credentials.json" ]]; then
  echo "Missing $ROOT/credentials.json. Restore the Google OAuth client secret first." >&2
  exit 2
fi

auth_header=(-H "Authorization: Bearer ${INBOX_SERVER_TOKEN}")

echo "Inbox Google OAuth Restore"
echo "repo: $ROOT"
echo "server: $BASE_URL"
echo

echo "Health:"
curl -fsS "$BASE_URL/health" | python3 -m json.tool
echo

echo "Auth status:"
curl -fsS "${auth_header[@]}" "$BASE_URL/accounts/auth-status?check_refresh=true" | python3 -m json.tool
echo

if [[ "$START" -eq 0 ]]; then
  cat <<EOF
Dry run complete.

To start browser OAuth for a Google account, run:
  $0 --start
EOF
  exit 0
fi

echo "Starting /accounts/add. Complete the browser OAuth flow when it opens..."
curl -fsS -X POST "${auth_header[@]}" "$BASE_URL/accounts/add" | python3 -m json.tool
echo
echo "OAuth call returned. Rechecking auth status:"
curl -fsS "${auth_header[@]}" "$BASE_URL/accounts/auth-status?check_refresh=true" | python3 -m json.tool
