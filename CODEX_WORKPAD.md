# MAX-48 Inbox needs-action rollup

## Work order

- Linear: MAX-48
- Pull request: https://github.com/jwalin-shah/inbox/pull/46
- Repo: `/Users/jwalinshah/projects/inbox`
- Worktree: `/Users/jwalinshah/projects/inbox-MAX-48-inbox-needs-action-rollup`
- Branch: `codex/MAX-48-inbox-needs-action-rollup`
- Base: `origin/main` at `42a32a2`
- Implementation commit: `26f021f`

## Acceptance

- `/inbox/needs-action?account=<email-or-id>` scopes calendar rollups to the requested account when it exists.
- Unknown account filters do not leak calendar items from other accounts.
- Undated Google Tasks with status `needsAction` or `needs_action` are included.
- Do not pull unrelated PR #38 changes.
- Open a PR against `main`.

## Plan

1. Add focused endpoint regression tests in `tests/test_server.py`.
2. Patch `/inbox/needs-action` account scoping and task status handling in `inbox_server.py`.
3. Run focused validation, then the safe repo validation if practical.
4. Commit, push, open PR, and record evidence on Linear.

## Validation

- Passed: `INBOX_TEST_MODE=1 uv run pytest tests/test_server.py -q -k 'needs_action' --no-cov` (7 passed, 119 deselected)
- Passed: `scripts/validate_agent_safe.sh` (ruff, bandit, safe pytest lane: 11 passed, 874 deselected)
