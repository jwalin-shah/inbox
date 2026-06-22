#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

required=(
  git
  uv
  rg
  llm-tldr
  rtk
)

optional=(
  agent-doctor
  memjuice
  curl
)

missing=0

for tool in "${required[@]}"; do
  if command -v "$tool" >/dev/null 2>&1; then
    printf "ok: %s -> %s\n" "$tool" "$(command -v "$tool")"
  else
    printf "missing: %s\n" "$tool"
    missing=1
  fi
done

if [ -d .git ]; then
  printf "ok: git repo initialized\n"
else
  printf "warn: not inside a git repo\n"
fi

for tool in "${optional[@]}"; do
  if command -v "$tool" >/dev/null 2>&1; then
    printf "ok: %s (optional) -> %s\n" "$tool" "$(command -v "$tool")"
  else
    printf "skip: %s (optional, not installed)\n" "$tool"
  fi
done

if command -v agent-doctor >/dev/null 2>&1; then
  if agent-doctor >/dev/null 2>&1; then
    printf "ok: agent-doctor\n"
  else
    printf "warn: agent-doctor reported issues\n"
  fi
fi

if [ -f SESSION_BRIEF.txt ] && [ -f .orch-context.json ]; then
  printf "ok: orchestrator project files present\n"
else
  printf "warn: missing SESSION_BRIEF.txt or .orch-context.json\n"
  missing=1
fi

if [ -f scripts/validate_agent_safe.sh ]; then
  printf "ok: validate_agent_safe.sh present\n"
else
  printf "warn: missing scripts/validate_agent_safe.sh\n"
  missing=1
fi

if [ -f GEMINI.md ] && [ -f CLAUDE.md ] && [ -f AGENTS.md ]; then
  printf "ok: agent contracts present (GEMINI.md, AGENTS.md, CLAUDE.md)\n"
else
  printf "warn: missing GEMINI.md, AGENTS.md, or CLAUDE.md\n"
  missing=1
fi

if command -v curl >/dev/null 2>&1; then
  port="${INBOX_SERVER_PORT:-9849}"
  if curl -sf "http://127.0.0.1:${port}/health" >/dev/null 2>&1; then
    printf "ok: inbox server health (port %s)\n" "$port"
  else
    printf "skip: inbox server not reachable on port %s (optional)\n" "$port"
  fi
fi

exit "$missing"
