#!/usr/bin/env bash
set -euo pipefail

# Restricted local-agent transport. The worker profile exposes only the
# read-only evidence packet and system audit; it does not expose provider
# writes, arbitrary Inbox tools, secrets, or terminal control.
export LIFEOPS_MCP_PROFILE=worker
# Required for data minimization. Set this to a comma-separated list of exact
# account identities before starting a worker client; an empty value is
# rejected instead of expanding to all observed accounts.
if [[ -z "${LIFEOPS_WORKER_ACCOUNT_ALLOWLIST:-}" ]]; then
  echo "Set LIFEOPS_WORKER_ACCOUNT_ALLOWLIST before starting the restricted LifeOps worker." >&2
  exit 1
fi
exec "$(cd "$(dirname "$0")" && pwd)/run_lifeops_mcp_v0_stdio.sh"
