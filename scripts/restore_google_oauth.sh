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

The Google OAuth client secret is sensitive. Restore credentials.json from a
trusted local secret source such as Keeper, Google Cloud Console, or a direct
encrypted transfer. Do not paste it into chat.

After browser OAuth completes, re-run:
  scripts/restore_google_oauth.sh
EOF
}

print_missing_credentials_help() {
  cat >&2 <<EOF
Missing $ROOT/credentials.json. Restore the Google OAuth client secret first.

Expected file:
  $ROOT/credentials.json

Current token directory:
  $ROOT/tokens

Safe restore options:
  - Keeper or another password manager attachment/note
  - Google Cloud Console OAuth client JSON download
  - Direct encrypted transfer from the old Mac

After restoring credentials.json:
  $0 --start

Do not paste credentials.json into chat.
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
  print_missing_credentials_help
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
