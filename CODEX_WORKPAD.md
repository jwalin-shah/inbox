# MAX-7 Workpad

## Issue

- Linear: MAX-7
- Title: Fix inbox CI/runtime mismatch for mac-only dependencies
- Repo: `/Users/jwalinshah/projects/inbox`
- Worktree: `/Users/jwalinshah/projects/inbox-max-7`
- Branch: `codex/MAX-7-inbox-ci-runtime`
- Base: `origin/main` at `42a32a22f45b4641d5f06bbd5c5941c6bc5ec70f`

## Plan

- Guard MLX and PyObjC dependencies so non-mac CI does not resolve mac-only runtime packages.
- Add an explicit `mac` extra for the full macOS runtime dependency set.
- Add a safe CI workflow that hydrates the locked environment, then runs the existing agent-safe validation wrapper.
- Document local and CI validation commands in README and AGENTS.

## Validation

```bash
uv lock --check
```

Result: passed.

```bash
uv sync --frozen --all-groups --dry-run --python-platform x86_64-unknown-linux-gnu --no-progress
```

Result: passed. Linux dry run installs 98 packages and excludes MLX, PyObjC, Torch, and CUDA runtime artifacts.

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py tests/test_services.py -k "test_mode_blocks" -q --no-cov
```

Result: passed, 3 passed and 69 deselected.

```bash
scripts/validate_agent_safe.sh
```

Result: passed. Ruff passed, Bandit completed with existing warnings only, and safe pytest passed with 11 passed and 871 deselected.

```bash
git diff --check
```

Result: passed.

Review rerun:

```bash
uv lock --check
```

Result: passed, resolved 130 packages.

```bash
uv sync --frozen --all-groups --dry-run --python-platform x86_64-unknown-linux-gnu --no-progress
```

Result: passed. Linux dry run excludes MLX, PyObjC, Torch, CUDA, and related mac/ML runtime artifacts.

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py tests/test_services.py -k "test_mode_blocks" -q --no-cov
```

Result: passed, 3 passed and 69 deselected.

```bash
scripts/validate_agent_safe.sh
```

Result: passed. Ruff passed, Bandit completed with existing warnings only, and safe pytest passed with 11 passed and 871 deselected.

```bash
git diff --check
```

Result: passed.

Remote CI:

- PR #43 `Safe validation`: passed.
- Job: https://github.com/jwalin-shah/inbox/actions/runs/25645772647/job/75274274402

## Handoff

- PR URL: https://github.com/jwalin-shah/inbox/pull/43
- Latest implementation commit SHA: `f10b972f753f4a36705d088bf549cc45c7aaa92f`
- Review evidence commit SHA: recorded in Linear after push.
- Commits:
  - `6d64c7f22c1ed210d6b30e676992e3a86b2cee4b` - Fix inbox mac-only dependency CI path
  - `f10b972f753f4a36705d088bf549cc45c7aaa92f` - Fix CI workflow temp env
- Blockers: none.
