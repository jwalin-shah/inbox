# inbox-sym-117 Implementation Readiness Review

Queue item: `inbox-sym-117-implementation-readiness`
Branch: `codex/goal-inbox-sym-117-implementation-readiness`
Reviewed HEAD: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`
Date: 2026-05-07

## Scope

This is a read-only implementation-readiness pass for the `inbox-sym-117`
repo. I did not edit product code. I reviewed repo-local docs, scripts,
tests, config, recent git state, and searched for previous overnight outputs.

## Evidence Observations

1. `PLAN.md` defines the implementation direction around a local operational
   index: stabilize sync/index first, then make indexed reads default, then
   add the TUI Now, Actionable, Waiting On, and Calendar Context surfaces.
   This is already executable as vertical slices because the plan names owned
   files such as `message_sync.py`, `message_index_store.py`, `inbox_server.py`,
   `inbox_client.py`, and `inbox.py`.
2. `message_index_store.py` already has the core index schema (`sync_state`,
   `items`, `threads`, `sender_stats`) plus idempotent item upserts, thread
   rebuilds, index counts, sync state listing, and view filters for actionable,
   recent, waiting-on-me, waiting-on-others, and open-loop tracking queries.
3. `message_sync.py` has resumable Gmail bootstrap using
   `bootstrap_page_token`, Gmail history cursor support with timestamp fallback,
   iMessage rowid checkpoints, and scoped thread rebuilds through
   `rebuild_changed_threads()`. This means Phase 1 sync hardening work can be
   tested mostly with fakes instead of live provider calls.
4. `inbox_server.py` exposes index endpoints at `/index/threads`,
   `/index/status`, `/index/health`, `/index/views/{view_name}`,
   `/index/sync/bootstrap`, and `/index/sync/incremental`. The sync endpoints
   call live sync functions in background threads, so endpoint tests should
   patch those call targets and must not hit Gmail or Messages directly.
5. `inbox_server.py` also has `/inbox/needs-action` returning
   `thread_read_model="index"` and `raw_thread_provider_fetch=false`;
   `tests/test_server.py` verifies that the route does not fall back to live
   Gmail when the index is empty.
6. `inbox_client.py` includes `index_status()`, `index_health()`,
   `index_view()`, and helper methods for recent, actionable, waiting-on-me,
   and waiting-on-others indexed threads. The server/client contract for status
   and health is covered in `tests/test_api_contract.py`.
7. `inbox.py` already loads indexed recent, actionable, and waiting-on views in
   its auxiliary refresh path. The TUI metadata in `tui_tabs.py` now labels the
   first tab as `Now`, but `inbox.py` key binding text and `tui_tabs.py`
   command text still say `All` in places. This is a small naming drift that
   can confuse agents and users.
8. `tests/test_message_sync.py` covers Gmail bootstrap resume, history cursor
   capture, timestamp fallback, skipped iMessage rows, changed-scope rebuilds,
   and global rebuild repair. `tests/test_message_index_store.py` covers
   idempotence, sender stats, high-volume automated sender behavior, waiting
   filters, latest-sender filtering, and a 1100-thread rebuild case.
9. `docs/TESTING_FOR_AGENTS.md` defines the agent-safe loop:
   `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, and
   `uv run pyright`. `pyproject.toml` registers `safe`, `integration`,
   `local_data`, `slow`, and `live_write` markers.
10. The safe marker is currently narrow: only `tests/test_inbox_test_mode.py`
    and `tests/test_mcp_gateway.py` declare `pytestmark = pytest.mark.safe`.
    Deterministic index, client, server, API-contract, and tool-registry tests
    are not yet part of the documented safe agent loop.
11. `services.py` has live-write guards via `_assert_live_write_allowed()` on
    Gmail, iMessage, calendar, reminders, Google Tasks, Drive, Sheets, Docs,
    GitHub notification mutation, notifications, and attendee modification.
    `tests/test_services.py` has representative guard tests, and
    `tests/test_inbox_test_mode.py` verifies test-mode path redirection.
12. `tools_registry.py` centralizes the MCP tool surface and marks mutating
    tools as `confirm=True`; `tests/test_tools_registry.py` verifies all
    mutating tools require confirmation and readonly registration omits writes.
    The current MCP default `list_inbox_threads` still reads raw Gmail
    conversations, so indexed inbox views are not yet first-class MCP tools.
13. `.pre-commit-config.yaml` configures Ruff, Ruff format, common pre-commit
    hooks, large-file/key checks, and Bandit using `pyproject.toml`. No
    `.github/` workflow files were present in this worktree, so local evidence
    does not show CI running the documented agent-safe loop.
14. `README.md` says Python 3.10+, while `pyproject.toml` requires
    `>=3.12,<3.15`. `DOCS_INDEX.md` and `SHEETS_CHANGELOG.md` claim "736
    tests pass"; that claim is stale unless revalidated because the current
    review did not run the full suite and the test tree has changed.
15. `dev.sh` supports isolated worktree development by defaulting to port
    `9850`, while `config/codex.inbox.example.toml` shows how to point MCP
    clients at the primary `9849` instance or a dev worktree. This reduces
    implementation risk for UI/API work because agents can avoid disrupting
    the daily-driver inbox.
16. `config/inbox.env.example`, `scripts/run_inbox_backend.sh`,
    `scripts/run_inbox_mcp_http.sh`, and `deploy/inbox-backend.service.example`
    provide deployment/run surfaces, but they rely on local tokens and primary
    machine paths. Implementation agents should keep validation provider-free
    unless explicitly asked to test live integrations.
17. Search for `runs/**`, `docs/overnight/**`, `*handoff*`, and
    `*result.json` returned no prior overnight artifacts in this worktree.
18. `git status --short --branch` was clean at the start of review on
    `codex/goal-inbox-sym-117-implementation-readiness`.

## Risks And Blockers

- The documented safe validation loop is too small to prove most executable
  work. Deterministic tests exist, but most are not marked `safe`.
- Full sync and provider-backed behavior cannot be validated safely without
  local credentials and live personal data. Work on sync should use fake
  provider services and temp SQLite databases by default.
- No local `.github/` workflows were present, so there is no repo-local proof
  that every PR runs the safe test loop, lint, type checking, or Bandit.
- The index is now the default read path for several flows, but MCP still
  exposes raw Gmail inbox listing as the primary thread tool.
- Product docs contain stale runtime and test-count claims, which can mislead
  agents choosing validation commands or Python versions.

## Exact Validation Commands

Required queue validation:

```bash
git status --short
```

Agent-safe validation recommended for implementation slices:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe
uv run ruff check .
uv run pyright
```

Useful focused validations:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_message_sync.py tests/test_message_index_store.py -q
INBOX_TEST_MODE=1 uv run pytest tests/test_server.py tests/test_api_contract.py tests/test_client.py -q
INBOX_TEST_MODE=1 uv run pytest tests/test_tools_registry.py tests/test_mcp_gateway.py -q
```

## Implementation-Ready Follow-Up Tasks

### 1. Broaden the agent-safe test lane for deterministic index/API work

Owned files:

- `tests/test_message_sync.py`
- `tests/test_message_index_store.py`
- `tests/test_server.py`
- `tests/test_client.py`
- `tests/test_api_contract.py`
- `tests/test_tools_registry.py`
- `docs/TESTING_FOR_AGENTS.md`

Acceptance criteria:

- Deterministic tests for the index store, message sync fakes, index server
  endpoints, API contract, client helpers, and tool registry are included in
  `pytest -m safe`.
- Tests that require local personal data, live providers, external writes, or
  slow hardware/ML dependencies remain outside `safe`.
- `docs/TESTING_FOR_AGENTS.md` names the broadened safe lane and explains what
  is intentionally excluded.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe -q
```

### 2. Add safe endpoint tests for index sync triggers

Owned files:

- `tests/test_server.py`
- `inbox_server.py` only if the current error shape needs normalization

Acceptance criteria:

- `/index/sync/bootstrap` is tested with `index_bootstrap_sync` patched to
  return fake stats and proves the response shape is `{"ok": true,
  "mode": "bootstrap", "stats": ...}`.
- `/index/sync/incremental` is tested with `index_incremental_sync` patched to
  return fake stats and proves the response shape is `{"ok": true,
  "mode": "incremental", "stats": ...}`.
- Tests prove no live Gmail, iMessage, or token-loading path is invoked.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_server.py -k 'index_sync' -q
```

### 3. Make indexed inbox views first-class MCP readonly tools

Owned files:

- `tools_registry.py`
- `tests/test_tools_registry.py`
- `tests/test_api_contract.py`
- `MCP_V1_PLAN.md`

Acceptance criteria:

- Add readonly tools for indexed recent, actionable, waiting-on-me, and
  waiting-on-others threads, mapped to `/index/views/recent`,
  `/index/views/actionable`, `/index/views/waiting-on-me`, and
  `/index/views/waiting-on-others`.
- Existing raw Gmail tools remain available for drill-down, but docs identify
  indexed tools as the default inbox read path.
- Contract tests prove every new tool path routes to a FastAPI endpoint and
  readonly MCP registration includes the new tools.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_tools_registry.py tests/test_api_contract.py -q
```

### 4. Resolve TUI Now/Waiting naming drift and expose split waiting views

Owned files:

- `tui_tabs.py`
- `command_palette.py`
- `inbox.py`
- `tests/test_tui_tabs.py`
- `tests/test_command_palette.py`
- `tests/test_inbox_app.py`

Acceptance criteria:

- The first tab, command palette entry, and key binding text consistently use
  `Now` instead of mixing `Now` and `All`.
- The TUI either exposes separate `Waiting On Me` and `Waiting On Others`
  surfaces or clearly defines the existing `Waiting On` tab as the open-loop
  tracking view.
- Tests cover tab metadata, command registry labels, and the index view names
  requested during auxiliary refresh.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_tui_tabs.py tests/test_command_palette.py tests/test_inbox_app.py -q
```

### 5. Add a local CI workflow for the safe implementation lane

Owned files:

- `.github/workflows/ci.yml`
- `.pre-commit-config.yaml` only if workflow behavior needs alignment
- `docs/TESTING_FOR_AGENTS.md`

Acceptance criteria:

- Pull requests run `uv sync --dev`, `INBOX_TEST_MODE=1 uv run pytest -m safe`,
  `uv run ruff check .`, and `uv run pyright`.
- The workflow does not require local personal data, Google tokens, Apple
  databases, microphone input, or live external writes.
- Testing docs link the local commands to the CI workflow so agents can
  reproduce failures before handoff.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe
uv run ruff check .
uv run pyright
```

## Handoff Notes

- Report file written: `docs/overnight/2026-05-07-whole-portfolio-review/inbox-sym-117-implementation-readiness.md`
- Product code changes: none.
- Previous overnight artifacts: none found locally.
- External services, deploys, pushes, PRs, and tracker updates: not attempted.
- Required validation command run: `git status --short`.
- Validation result: command completed successfully and reported the new
  `docs/overnight/` report path as untracked.
- Commit/PR blocker: local commit creation was blocked by sandbox permissions.
  `git add docs/overnight/2026-05-07-whole-portfolio-review/inbox-sym-117-implementation-readiness.md`
  failed because Git could not create
  `/Users/jwalinshah/projects/inbox/.git/worktrees/inbox-sym-117-implementation-readiness/index.lock`
  (`Operation not permitted`).
