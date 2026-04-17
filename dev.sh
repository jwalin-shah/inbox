#!/usr/bin/env bash
# Dev launcher for inbox-dev worktree. Runs server+TUI on port 9850 so the
# primary ~/projects/inbox instance on 9849 keeps working uninterrupted.
set -euo pipefail
export INBOX_SERVER_PORT=9850
export INBOX_SERVER_URL="http://127.0.0.1:9850"
cd "$(dirname "$0")"
exec uv run python "${1:-inbox.py}"
