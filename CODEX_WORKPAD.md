# MAX-38 Workpad

## Issue

- Linear: MAX-38
- Title: Fix inbox search-result navigation tab-state crash
- Repo: `/Users/jwalinshah/projects/inbox`
- Worktree: `/Users/jwalinshah/projects/inbox-max-38`
- Branch: `codex/MAX-38-inbox-search-tab-state`
- Base: `origin/main` at `42a32a22f45b4641d5f06bbd5c5941c6bc5ec70f`

## Plan

- Add a focused regression for tab activation before the content widgets are mounted.
- Guard early tab activation so it updates the active filter but skips state/render work until widgets exist.
- Validate the focused search/render lane and the agent-safe wrapper.

## Validation

Red test before fix:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_app.py::test_tab_activation_before_content_mount_does_not_crash -q --no-cov
```

Result: failed with `ScreenStackError: No screens on stack`.

After fix:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_app.py::test_tab_activation_before_content_mount_does_not_crash -q --no-cov
```

Result: passed.

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_app.py -k "search or render" -q --no-cov
```

Result: passed, 8 passed and 150 deselected.

```bash
scripts/validate_agent_safe.sh
```

Result: passed. Ruff passed, Bandit completed with existing warnings only, and safe pytest passed with 11 passed and 872 deselected.

```bash
git diff --check
```

Result: passed.

Review rerun:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_app.py::test_tab_activation_before_content_mount_does_not_crash -q --no-cov
```

Result: passed, 1 test.

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_app.py -k "search or render" -q --no-cov
```

Result: passed, 8 passed and 150 deselected.

```bash
scripts/validate_agent_safe.sh
```

Result: passed. Ruff passed, Bandit completed with existing warnings only, and safe pytest passed with 11 passed and 872 deselected.

```bash
git diff --check
```

Result: passed.

Factory review rerun, 2026-05-11:

```bash
UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_app.py::test_tab_activation_before_content_mount_does_not_crash -q --no-cov
```

Result: passed, 1 test.

```bash
UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_app.py -k "search or render" -q --no-cov
```

Result: passed, 8 passed and 150 deselected.

```bash
UV_CACHE_DIR=/tmp/uv-cache scripts/validate_agent_safe.sh
```

Result: passed. Ruff passed, Bandit completed with existing warnings only, and safe pytest passed with 11 passed and 872 deselected.

```bash
UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_app.py -q --no-cov
```

Result: passed, 158 tests.

## Handoff

- PR URL: https://github.com/jwalin-shah/inbox/pull/45
- Implementation commit SHA: `5ac5e46fa7a5bc2bd3953c1c6389e8597f87dfc1`
- Review evidence commit SHA: pending push.
- Blockers: none.
