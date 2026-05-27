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

INBOX_SERVER_URL="${INBOX_SERVER_URL:-http://127.0.0.1:9849}"
INBOX_SERVER_TOKEN="${INBOX_SERVER_TOKEN:-}"
AUTH_ARGS=()
if [[ -n "$INBOX_SERVER_TOKEN" ]]; then
  AUTH_ARGS=(-H "Authorization: Bearer $INBOX_SERVER_TOKEN")
fi

section() {
  printf '\n== %s ==\n' "$1"
}

section "LaunchAgents"
launchctl list | rg 'com\.jwalin\.inbox' || true

section "Backend Health"
curl -fsS --max-time 5 "$INBOX_SERVER_URL/health" || true
printf '\n'

section "Index Health"
curl -fsS --max-time 10 "${AUTH_ARGS[@]}" "$INBOX_SERVER_URL/index/health" || true
printf '\n'

section "Index Status"
curl -fsS --max-time 10 "${AUTH_ARGS[@]}" "$INBOX_SERVER_URL/index/status" || true
printf '\n'

section "Local Index Counts"
sqlite3 -header -column "$ROOT_DIR/.inbox_index.sqlite3" \
  "select source, count(*) as items, max(created_at) as latest from items group by source order by items desc;" \
  2>/dev/null || true

section "Sync State"
sqlite3 -header -column "$ROOT_DIR/.inbox_index.sqlite3" \
  "select source, account, status, last_success_at, substr(last_error,1,120) as last_error from sync_state order by source, account;" \
  2>/dev/null || true

section "WhatsApp Store"
WA_DB="${INBOX_OPENHUMAN_WHATSAPP_DB:-$HOME/.openhuman/users/local/workspace/whatsapp_data/whatsapp_data.db}"
sqlite3 -header -column "$WA_DB" \
  "select 'chats' as metric, count(*) as value from wa_chats union all select 'messages', count(*) from wa_messages union all select 'nonempty_bodies', count(*) from wa_messages where length(coalesce(body,'')) > 0;" \
  2>/dev/null || true

section "LinkedIn Store"
LI_DB="${INBOX_OPENHUMAN_LINKEDIN_DB:-$HOME/.openhuman/users/local/workspace/linkedin_data/linkedin_data.db}"
sqlite3 -header -column "$LI_DB" \
  "select 'threads' as metric, count(*) as value from li_threads union all select 'messages', count(*) from li_messages;" \
  2>/dev/null || true

section "Recent Refresh Errors"
tail -n 40 "$HOME/Library/Logs/inbox/index-sync.err.log" 2>/dev/null || true
tail -n 40 "$HOME/Library/Logs/inbox/whatsapp-scan.err.log" 2>/dev/null || true
