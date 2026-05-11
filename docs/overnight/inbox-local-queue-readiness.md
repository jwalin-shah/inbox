# inbox-local-queue-readiness

Date: 2026-05-10
Branch: `codex/goal-inbox-local-queue-readiness`
HEAD reviewed: `af0e20c26ea7d5000db3cf3c2cf629b7e9c96050`

## Scope

This queue item was a local-only readiness inspection for the Inbox repo. I did
not edit product code, run live services, touch credentials, push branches, open
PRs, or update external trackers. The only intended repo change from this item
is this handoff file.

The Goal Pack issue body was supplied in the worker prompt. The referenced
`items/inbox-local-queue-readiness/ISSUE.md` path is not present inside this
repo, which is expected for this local Inbox worktree.

## Current State

- The worktree started clean on `codex/goal-inbox-local-queue-readiness`.
- The repo now includes prior overnight reports under `docs/overnight/`.
- The current HEAD includes `e069d70 [codex] inbox agent safe validation wrapper`.
- `docs/TESTING_FOR_AGENTS.md` now points agents at `scripts/validate_agent_safe.sh`.
- `scripts/validate_agent_safe.sh` sets `INBOX_TEST_MODE=1`, uses a writable temp
  `UV_CACHE_DIR`, runs offline dependency preflight, `ruff`, `bandit`, and the
  `pytest -m safe` lane.
- `inbox_client.py` already has `index_health()`, `index_status()`, and named
  indexed view helpers.
- `inbox_server.py` already exposes and tests `/index/health`, including
  `no_sync_state`, `missing_checkpoint`, `stale_checkpoint`, and `sync_error`.
- `inbox.py` fetches indexed `recent`, `actionable`, and `waiting-on` views, but
  does not appear to consume `client.index_health()` in the TUI refresh/poll path.

## Next Safe Goal Pack Task

Recommended queue item:

```json
{
  "branch": "codex/goal-inbox-surface-index-health-tui",
  "enabled": true,
  "id": "inbox-surface-index-health-tui",
  "issue_file": "items/inbox-surface-index-health-tui/ISSUE.md",
  "max_minutes": 60,
  "repo": "inbox",
  "title": "Surface index health in the Inbox TUI so empty indexed views are explainable.",
  "validation": "UV_CACHE_DIR=/private/tmp/uv-cache-inbox INBOX_TEST_MODE=1 uv run pytest tests/test_client.py tests/test_inbox_app.py tests/test_server.py::TestIndexEndpoints -q"
}
```

Suggested issue body:

```markdown
# inbox-surface-index-health-tui

## Goal

Surface `/index/health` in the Inbox TUI refresh workflow so empty indexed views
show whether the index is healthy, stale, missing checkpoints, or in error.

## Repo

`inbox`

## Acceptance Criteria

- The change is scoped to TUI/client index health display and focused tests.
- The TUI refresh and poll paths fetch `InboxClient.index_health()` alongside
  indexed `recent`, `actionable`, and `waiting-on` views.
- `Now`, `Actionable`, and `Waiting On` status text distinguishes a healthy empty
  index from `no_sync_state`, `missing_checkpoint`, `stale_checkpoint`, and
  `sync_error`.
- Existing indexed view behavior remains index-only and does not fall back to
  live Gmail/iMessage provider reads.
- Tests cover healthy, stale, error, and no-sync health payloads using mocks or
  server test fixtures only.
- No live provider, local personal-data, OAuth, server-start, TUI-start, or
  live-write validation is required.

## Suggested Files

- `inbox.py`
- `inbox_client.py` only if a small helper is useful; the core client method
  already exists.
- `tests/test_inbox_app.py`
- `tests/test_client.py` only if the client shape changes.
- `tests/test_server.py` only to reuse/extend existing index endpoint tests.

## Validation

```bash
UV_CACHE_DIR=/private/tmp/uv-cache-inbox INBOX_TEST_MODE=1 uv run pytest tests/test_client.py tests/test_inbox_app.py tests/test_server.py::TestIndexEndpoints -q
```

## Stop Conditions

- The implementation would require live Gmail, iMessage, Calendar, Apple data,
  OAuth, microphone, notifications, or write-capable provider access.
- The expected status copy or UX requires human product judgment beyond concise
  health/error wording.
- The work spills into MCP registry, batch archive behavior, account routing, or
  classifier heuristics.
- The validation command cannot run locally because dependencies are missing
  from the offline uv cache; record the blocker instead of widening scope.
```

## Why This Is The Safest Next Slice

The index-health API, server tests, and client method already exist, so the next
worker can avoid data-source and provider work. The current gap is a small wiring
slice in the TUI: indexed views can be empty because there is nothing to do, or
because the index has never synced, is stale, or has a sync error. Showing that
distinction makes the index-first product safer to dogfood and gives later MCP or
classification work a clearer operational signal.

## Not Chosen For The Next Slot

- MCP index tools are still valuable, but they expand the agent-facing tool
  surface and should come after the human TUI can explain index freshness.
- Batch archive hardening is important, but it changes a mutating workflow and
  has more shell/state edge cases than this TUI health slice.
- Safe marker expansion is useful, but the validation wrapper already landed in
  this branch, and this next slice has a focused validation command without
  relying on broad marker policy.

## Handoff

- Files changed by this queue item: `docs/overnight/inbox-local-queue-readiness.md`
- Product code changed: no
- Required validation: `git status --short` exited 0 and showed
  `?? docs/overnight/inbox-local-queue-readiness.md`.
- Commit SHA containing this handoff: none. The current reviewed HEAD remains
  `af0e20c26ea7d5000db3cf3c2cf629b7e9c96050`.
- PR URL: none.
- Commit blocker: `git add docs/overnight/inbox-local-queue-readiness.md &&
  git commit -m "Add inbox local queue handoff"` failed with
  `fatal: Unable to create '/Users/jwalinshah/projects/inbox/.git/worktrees/inbox-local-queue-readiness/index.lock': Operation not permitted`.
  The repo content file is written, but this sandbox cannot update the linked
  Git worktree metadata.
