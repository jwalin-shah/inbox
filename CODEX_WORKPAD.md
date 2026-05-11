# MAX-36 Workpad

## Issue

- Linear: MAX-36
- Title: Fix inbox read-only MCP daily-note handler
- Repo: `/Users/jwalinshah/projects/inbox`
- Worktree: `/Users/jwalinshah/projects/inbox-max-36`
- Branch: `codex/MAX-36-inbox-readonly-mcp-notes`
- Base: `origin/main` at `42a32a22f45b4641d5f06bbd5c5941c6bc5ec70f`

## Plan

- Add focused safe tests around the read-only MCP hand-written daily-note tool.
- Reproduce the dated-note failure against `ambient_notes.VAULT_DIR`.
- Fix the handler to use the existing ambient notes daily directory.
- Confirm the read-only MCP tool list excludes mutating registry tools.

## Validation

Red test before fix:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_mcp_gateway.py tests/test_ambient_notes.py -q --no-cov
```

Result: failed as expected with `AttributeError: module 'ambient_notes' has no attribute 'VAULT_DIR'`.

After fix:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_mcp_gateway.py tests/test_ambient_notes.py -q --no-cov
```

Result: passed, 24 passed.

```bash
scripts/validate_agent_safe.sh
```

Result: passed. Ruff passed, Bandit completed with existing warnings only, and safe pytest passed with 15 passed and 871 deselected.

```bash
git diff --check
```

Result: passed.

Review rerun:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_mcp_gateway.py tests/test_ambient_notes.py -q --no-cov
```

Result: passed, 24 tests.

```bash
scripts/validate_agent_safe.sh
```

Result: passed. Ruff passed, Bandit completed with existing warnings only, and safe pytest passed with 15 passed and 871 deselected.

```bash
git diff --check
```

Result: passed.

## Handoff

- PR URL: https://github.com/jwalin-shah/inbox/pull/44
- Implementation commit SHA: `ea233f04d23ee2564741765ae297f493e308e6f4`
- Review evidence commit SHA: recorded in Linear after push.
- Blockers: none.
