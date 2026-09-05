#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"

OAUTH_CLIENT_JSON="${INBOX_GOOGLE_OAUTH_CLIENT_JSON:-$HOME/.config/inbox/gemini_oauth_client.json}"
if [[ -f "$OAUTH_CLIENT_JSON" ]] && command -v jq >/dev/null 2>&1; then
  export GOOGLE_OAUTH_CLIENT_ID="${GOOGLE_OAUTH_CLIENT_ID:-$(jq -r '.web.client_id' "$OAUTH_CLIENT_JSON")}"
  export GOOGLE_OAUTH_CLIENT_SECRET="${GOOGLE_OAUTH_CLIENT_SECRET:-$(jq -r '.web.client_secret' "$OAUTH_CLIENT_JSON")}"
fi
STATIC_CLIENT_JSON="${INBOX_GEMINI_MCP_CLIENT_JSON:-$HOME/.config/inbox/gemini_mcp_static_client.json}"
if [[ -f "$STATIC_CLIENT_JSON" ]] && command -v jq >/dev/null 2>&1; then
  export INBOX_GEMINI_MCP_CLIENT_ID="${INBOX_GEMINI_MCP_CLIENT_ID:-$(jq -r '.client_id' "$STATIC_CLIENT_JSON")}"
  export INBOX_GEMINI_MCP_CLIENT_SECRET="${INBOX_GEMINI_MCP_CLIENT_SECRET:-$(jq -r '.client_secret' "$STATIC_CLIENT_JSON")}"
  export INBOX_GEMINI_MCP_REDIRECT_URI="${INBOX_GEMINI_MCP_REDIRECT_URI:-$(jq -r '.redirect_uri' "$STATIC_CLIENT_JSON")}"
fi
export INBOX_PUBLIC_BASE_URL="${INBOX_PUBLIC_BASE_URL:-https://crumpled-resume-arbitrate.ngrok-free.dev}"
export INBOX_OAUTH_DB="${INBOX_OAUTH_DB:-$ROOT_DIR/.inbox_oauth.sqlite3}"
# Stable across restarts, while still requiring an explicit override in production.
export INBOX_OAUTH_SECRET="${INBOX_OAUTH_SECRET:-$GOOGLE_OAUTH_CLIENT_SECRET}"

exec uv run python mcp_server.py
