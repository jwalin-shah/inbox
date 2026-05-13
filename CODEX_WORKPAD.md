# MAX-250 Workpad

## Issue

- Linear: `MAX-250`
- Title: Inbox: require explicit API auth for personal-data and write endpoints
- Repo: `/Users/jwalinshah/projects/inbox`
- Worktree: `/Users/jwalinshah/projects/inbox-MAX-250`
- Branch: `codex/MAX-250-inbox-api-auth-fail-closed`
- Base: `origin/main` at `1327e97`

## Plan

- Make `/health` the only unauthenticated endpoint by default.
- Require `INBOX_SERVER_TOKEN` for all non-health endpoints unless an explicit dev/test bypass is enabled.
- Add `INBOX_SERVER_ALLOW_UNAUTHENTICATED=1` as the named bypass for isolated development and tests.
- Update auth tests to prove fail-closed, token success, X-API-Key success, and explicit dev bypass behavior.
- Update README/CLAUDE/config docs for the new default.

## Validation

```bash
uv run pytest tests/test_server.py::TestAuth -q --no-cov
```

Result: passed, 7 passed.

```bash
uv run pytest tests/test_server.py tests/test_server_endpoints.py tests/test_api_contract.py -q --no-cov
```

Result: passed, 186 passed.

```bash
uv run ruff check inbox_server.py tests/conftest.py tests/test_server.py
```

Result: passed.

```bash
git diff --check
```

Result: passed.

```bash
scripts/validate_agent_safe.sh
```

Result: passed. Ruff passed, Bandit completed with existing warnings only, and safe pytest passed with 11 passed and 874 deselected.

Review rerun after PR #43 landed:

```bash
uv lock --check
```

Result: passed.

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_server.py -q --no-cov
```

Result: passed, 126 passed.

```bash
scripts/validate_agent_safe.sh
```

Result: passed. Ruff passed, Bandit completed with existing warnings only, and safe pytest passed with 11 passed and 874 deselected.

```bash
git diff --check
```

Result: passed.

## Handoff

Pending PR.
