#!/usr/bin/env bash
set -euo pipefail

# Local-agent transport for Pi, DeepSeek harnesses, and OpenClaw.
# It uses the same LifeOps adapter and Inbox credential as the HTTP transport;
# it does not create a second Google credential store or bypass Inbox.

credential_file="${INBOX_SERVER_ENV_FILE:-$HOME/.config/inbox/server.env}"
if [[ ! -r "$credential_file" || ! -O "$credential_file" ]]; then
  echo "LifeOps MCP requires an owner-readable Inbox credential file." >&2
  exit 1
fi

file_mode="$(/usr/bin/stat -f '%Lp' "$credential_file")"
if (( (8#$file_mode & 077) != 0 )); then
  echo "LifeOps MCP refuses a credential file readable by group or others." >&2
  exit 1
fi

inbox_token="$(/usr/bin/awk -F= '$1 == "INBOX_SERVER_TOKEN" {sub(/^[^=]*=/, ""); print; exit}' "$credential_file")"
if [[ -z "$inbox_token" ]]; then
  echo "LifeOps MCP could not load the local Inbox credential." >&2
  exit 1
fi

export INBOX_SERVER_URL="${INBOX_SERVER_URL:-http://127.0.0.1:9849}"
export INBOX_SERVER_TOKEN="$inbox_token"
export LIFEOPS_MCP_TRANSPORT=stdio
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"

lifeops_root="${LIFEOPS_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$lifeops_root"
exec uv run python lifeops_mcp.py
