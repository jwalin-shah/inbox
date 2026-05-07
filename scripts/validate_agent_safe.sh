#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_ROOT="${TMPDIR:-/tmp}"

export INBOX_TEST_MODE=1
export INBOX_TEST_DATA_DIR="${INBOX_TEST_DATA_DIR:-${TMP_ROOT%/}/inbox-agent-test-data}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-${TMP_ROOT%/}/uv-cache}"

mkdir -p "$INBOX_TEST_DATA_DIR" "$UV_CACHE_DIR"
cd "$ROOT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "Dependency/cache blocker: uv is required for agent-safe validation but was not found on PATH." >&2
  exit 127
fi

UV_RUN=(uv run --offline --frozen --no-progress)

is_dependency_blocker() {
  grep -Eiq \
    "Network connectivity is disabled|wasn't found in the cache|not found in the cache|Failed to download|No cache entry|dependency/cache blocker" \
    <<<"$1"
}

run_uv() {
  local label="$1"
  shift

  echo "==> ${label}"

  local output
  local status
  set +e
  output="$("${UV_RUN[@]}" "$@" 2>&1)"
  status=$?
  set -e

  if [[ -n "$output" ]]; then
    printf '%s\n' "$output"
  fi

  if [[ "$status" -ne 0 ]]; then
    if is_dependency_blocker "$output"; then
      cat >&2 <<EOF

Dependency/cache blocker: uv could not hydrate or run the validation environment offline.
This wrapper does not use network access.
UV_CACHE_DIR=${UV_CACHE_DIR}

Run 'uv sync' once in a network-enabled environment, or provide a warm writable uv cache, then retry.
EOF
    fi
    exit "$status"
  fi
}

run_uv "offline dependency cache preflight" python - <<'PY'
from __future__ import annotations

import importlib.util
import shutil
import sys

missing = [
    name
    for name in ("pytest", "bandit")
    if importlib.util.find_spec(name) is None
]
if shutil.which("ruff") is None:
    missing.append("ruff")

if missing:
    print(
        "Dependency/cache blocker: missing offline validation dependencies: "
        + ", ".join(sorted(missing)),
        file=sys.stderr,
    )
    sys.exit(86)
PY

run_uv "ruff check" ruff check --no-cache .
run_uv "bandit scan" bandit -c pyproject.toml -r . -x .venv,tests,.factory,.claude -q
run_uv "safe pytest lane" pytest -m safe -q --no-cov -p no:cacheprovider
