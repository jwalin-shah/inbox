# Ticket 004 — Triage stale Codex remote branches

Label: `wayfinder:ticket`
Status: open
Blocked by: 003
Blocks: 005

## What

Audit the 22 stale Codex remote branches on origin. For each: determine if
it contains unlanded work worth keeping, then either open a PR to land it or
delete the branch. Document findings.

## Why

22 stale branches clutter the remote namespace and make it hard to see what's
actually in-flight. Some may contain useful work (MCP path encoding, Gmail
history incremental sync, TUI refresh snapshot, calendar date range). Others
are dead experiments. Without a triage pass, useful work rots and dead
branches accumulate.

## Acceptance

- Each of the 22 branches classified as: LAND (open PR), DELETE (no useful
  work), or DEFER (useful but blocked — document why)
- LAND branches: PR opened with description of what the branch does
- DELETE branches: deleted from origin
- Full test suite passes on any code changes from LAND branches
- Findings documented in this ticket or a `branch-triage.md` in `docs/`

## Branches to triage

```
codex/SYM-115-mcp-path-encoding
codex/SYM-116-api-mcp-contract-tests
codex/SYM-117-gmail-history-incremental
codex/SYM-118-scoped-thread-rebuilds
codex/SYM-119-sender-stats-actionability
codex/SYM-120-tui-refresh-snapshot
codex/SYM-214-calendar-date-range
codex/WP-014-local-validation-gate
codex/WP-042-core-regression-test
codex/WP-070-shallow-module-deepening
codex/WP-098-duplicate-logic-consolidation
codex/WP-126-cli-smoke-contract
codex/WP-154-fixture-runtime-separation
codex/WP-182-error-boundary-hardening
codex/harden-inbox-pr39
codex/inbox-safe-daily-brief-slice
codex/reconcile-inbox-local-main-2026-05-20
feat/tools-registry
fm/inbox-wip-ship-9p
hygiene/20260608
stash/calendar-docs-2026-04-19
```

(Also check the second `origin/main` ref — likely a stale tracking ref.)

## Approach notes

For each branch: `git log origin/<branch> --oneline --not main` to see what
commits it adds. If the diff is small and focused, it's likely landable. If
it's a large refactor that conflicts with the gnhf series, it's likely dead.
