#!/usr/bin/env bash
set -euo pipefail

: "${INBOX_SERVER_TOKEN:?Set INBOX_SERVER_TOKEN before starting LifeOps}"

export INBOX_SERVER_URL="${INBOX_SERVER_URL:-http://127.0.0.1:9849}"
export LIFEOPS_MCP_PORT="${LIFEOPS_MCP_PORT:-9850}"
# Keep autonomous departure-task creation off during the first MCP validation.
export INBOX_ENABLE_DEPARTURE_ALERTS="${INBOX_ENABLE_DEPARTURE_ALERTS:-0}"

cleanup() {
  if [[ -n "${INBOX_PID:-}" ]] && kill -0 "$INBOX_PID" 2>/dev/null; then
    kill "$INBOX_PID" 2>/dev/null || true
    wait "$INBOX_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

uv run python inbox_server.py &
INBOX_PID=$!

for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:9849/health >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$INBOX_PID" 2>/dev/null; then
    echo "Inbox server exited during startup" >&2
    exit 1
  fi
  sleep 0.5
done

if ! curl -fsS http://127.0.0.1:9849/health >/dev/null 2>&1; then
  echo "Inbox server did not become healthy" >&2
  exit 1
fi

exec uv run python lifeops_mcp.py
