#!/usr/bin/env bash
# Launched by com.jwalinshah.inbox-server.plist. Not meant to be run by hand
# for interactive use — for that, use `uv run python inbox.py` directly so
# you get the TUI. This is server-only, for background/agent access.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_ENV="$HOME/.config/inbox/server.env"

cd "$ROOT"

if [[ -f "$SERVER_ENV" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$SERVER_ENV"
  set +a
fi

exec "$ROOT/.venv/bin/python3" inbox_server.py
