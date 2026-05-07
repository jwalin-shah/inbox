# Inbox implementation-readiness review

Queue item: `inbox-implementation-readiness`
Branch: `codex/goal-inbox-implementation-readiness`
Review date: 2026-05-07
Scope: read-only repo review plus this report. No product code changed.

## Current state

- Starting HEAD: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`.
- Initial validation command `git status --short` returned no output before this report was written.
- No `.github/workflows` files were present (`rg --files -g '.github/**'` returned no matches).
- No previous overnight outputs were available in this worktree: `rg --files docs runs` found only `docs/TESTING_FOR_AGENTS.md` and reported `runs: No such file or directory`.
- Recent history is already moving in the right direction: latest commits include `a821b5a Make indexed inbox views the default`, `05fc249 Add index sync health endpoint`, and `44be0c8 Avoid large thread cleanup expressions`.

## Concrete observations

1. `PLAN.md` defines the immediate product as Gmail, iMessage/SMS, calendar context, local FastAPI server, local SQLite index, and Textual TUI. It explicitly says incomplete areas are resumable bootstrap sync, stronger incremental checkpoints, noisy classification, indexed default TUI views, waiting-on views, and calendar context.

2. `message_sync.py` has a real sync implementation, not just scaffolding: Gmail bootstrap persists `bootstrap_page_token`, tracks `internalDateMs`, records a Gmail `historyId` when available, has timestamp fallback, and rebuilds only changed `(source, account)` scopes after bootstrap/incremental sync.

3. `tests/test_message_sync.py` is a strong readiness signal. It covers Gmail bootstrap resume after interruption, history cursor recording, no double-counting on resume, history-based incremental sync, timestamp fallback, skipped iMessage rows advancing checkpoints, and scoped thread rebuilds.

4. `message_index_store.py` owns the operational index schema: `sync_state`, `items`, `threads`, and `sender_stats`. `list_threads()` already supports actionable, recent, action set, needs-reply, open-loop, latest-sender, and priority/recent sort filters, so more index views can be added without provider calls.

5. `thread_classifier.py` is deterministic and small enough for implementation work. The current classifier distinguishes OTP, newsletter, appointment, survey, receipt, security, opportunity, health-admin, housing, and general threads, but `tests/test_thread_classifier.py` currently has only one focused assertion for OTP ignore behavior.

6. `inbox_server.py` exposes index-first API surfaces: `/index/threads`, `/index/status`, `/index/health`, `/index/views/{view_name}`, `/index/sync/bootstrap`, `/index/sync/incremental`, and `/inbox/needs-action`. The sync POST routes call `index_bootstrap_sync` and `index_incremental_sync` directly in a thread without an obvious server-level concurrency guard.

7. `tests/test_server.py` validates the index health and read-model contract: stale checkpoints, missing checkpoints, sync errors, no sync state, index views, and `/inbox/needs-action` avoiding live Gmail fallback when the index is empty.

8. `inbox_client.py` includes compact index helpers for recent, actionable, waiting-on-me, and waiting-on-others views. The client can already consume more granular waiting views than the current TUI presents.

9. `tui_tabs.py` declares `Now`, `Actionable`, and `Waiting On` as primary tabs before raw sources, matching the product plan. `inbox.py` binds these to `ctrl+1`, `ctrl+9`, and `ctrl+0`, refreshes `recent`, `actionable`, and `waiting-on` index views, and renders indexed thread summaries without raw body fetches.

10. `inbox.py`'s `_show_index_thread()` renders summary, action items, and brief text from the index only. That keeps the default view compact, but there is not yet an obvious "open raw source thread from this indexed row" flow in the inspected slice.

11. `google_account_resolution.py` centralizes Google service resolution and honors `INBOX_DEFAULT_GOOGLE_ACCOUNT` when the preferred account exists in the service map. It also implements `preflight_google_write_payload()` for docs/sheets/Drive folders, Tasks, and Calendar events.

12. `CONNECTOR_ROADMAP.md` says write routing and preflight should be encoded in code, not prompts. The backend partially implements that, but `tools_registry.py` currently has no MCP tool entries for `preflight_google_write`, `index_health`, index views, or `/inbox/needs-action` (`rg -n "preflight|index_|needs_action|workflow" tools_registry.py ...` returned only tests around client index status/health).

13. `tools_registry.py` and `tests/test_tools_registry.py` provide a good safety base for MCP work: every mutating tool must be confirmation-gated, readonly registration is separately tested, handler signatures are checked, and path params are URL-encoded.

14. `docs/TESTING_FOR_AGENTS.md`, `inbox_test_mode.py`, and `services.py` provide an agent-safe test mode. `INBOX_TEST_MODE=1` blocks representative live writes and redirects local data paths, and `tests/test_inbox_test_mode.py` asserts the docs and marker registration. However, `rg -n "@pytest.mark|live_write|local_data|safe" tests pyproject.toml` shows only `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py` carry module-level `pytest.mark.safe`, so the documented `pytest -m safe` loop currently exercises only a small slice.

15. `config/codex.inbox.example.toml` and `config/gemini-settings.inbox.example.json` both pass `INBOX_SERVER_TOKEN` to MCP clients. `deploy/com.inbox.backend.plist.example` and `deploy/inbox-backend.service.example` source `config/inbox.env` and run `scripts/run_inbox_backend.sh`, while `dev.sh` defaults worktrees to port 9850. Runtime routing is reasonably documented and implementable.

## Risks and blockers

- There is no CI workflow in this worktree, so local validation discipline is the only visible enforcement surface.
- The documented safe pytest command appears too narrow because most deterministic tests are not marked `safe`.
- Live provider behavior still depends on local macOS data stores, OAuth tokens, Google account services, GitHub token files, microphone/accessibility permissions, and server routing. Implementation slices should stay in `INBOX_TEST_MODE=1` unless explicitly approved.
- Index sync endpoints appear callable concurrently. A double bootstrap or bootstrap plus incremental run could make status and checkpoint evidence harder to trust.
- Preflight exists as an HTTP endpoint but is not exposed through the MCP tool registry, so agents can confirm writes without first having a first-class preflight step.
- Previous overnight reports and `runs/*` artifacts were not available locally, so this pass cannot compare against prior overnight findings.

## Exact validation commands

Required queue validation:

```bash
git status --short
```

Useful local implementation validation commands for future slices:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_message_sync.py -q
INBOX_TEST_MODE=1 uv run pytest tests/test_server.py -q
INBOX_TEST_MODE=1 uv run pytest tests/test_client.py tests/test_api_contract.py -q
INBOX_TEST_MODE=1 uv run pytest tests/test_thread_classifier.py -q
INBOX_TEST_MODE=1 uv run pytest tests/test_tools_registry.py tests/test_mcp_gateway.py -q
uv run ruff check .
uv run pyright
```

## Implementation-ready follow-up tasks

### 1. Expose index and preflight tools on the MCP registry

Owned files:
- `tools_registry.py`
- `tests/test_tools_registry.py`
- `tests/test_api_contract.py`

Change:
- Add readonly MCP tools for `index_health`, `index_status`, `list_index_view`, `list_needs_action`, and `preflight_google_write`.
- Keep preflight readonly even though it describes writes.
- Ensure registry route tests prove each tool maps to an existing FastAPI endpoint.

Acceptance criteria:
- `readonly_only=True` registration includes the new index/preflight tools.
- `test_mcp_tool_paths_route_to_fastapi_endpoints` stays green.
- No new mutating tool is added without `confirm=True`.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_tools_registry.py tests/test_api_contract.py -q
```

### 2. Split Waiting On into "Waiting on me" and "Waiting on others" surfaces

Owned files:
- `tui_tabs.py`
- `inbox.py`
- `inbox_client.py`
- `tests/test_client.py`
- `tests/test_inbox_app.py`

Change:
- Use the existing client helpers for `waiting-on-me` and `waiting-on-others`.
- Add clear TUI navigation and state preservation for the two views, or add a small toggle inside the existing Waiting On tab if a new tab is too much UI surface.
- Keep both views index-only and avoid raw provider fallback.

Acceptance criteria:
- Waiting-on-me calls `/index/views/waiting-on-me`.
- Waiting-on-others calls `/index/views/waiting-on-others`.
- Sidebar status makes the selected waiting mode visible.
- Existing source tabs still preserve selection state.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_client.py tests/test_inbox_app.py -q
```

### 3. Add representative classifier fixtures before tuning actionability

Owned files:
- `thread_classifier.py`
- `tests/test_thread_classifier.py`
- optionally `message_index_store.py` if the fix needs sender-stat behavior

Change:
- Add tests for recruiter/interview, newsletter, receipt, appointment, security alert, health-admin, housing, and latest-sender-is-me cases.
- Then tune the smallest classifier rules needed to satisfy those fixtures.

Acceptance criteria:
- Automated/newsletter/receipt/OTP examples do not become reply-worthy.
- Recruiter or direct opportunity examples become `review` or `reply`.
- Health/security examples become `track` with an open loop.
- Last sender `Me` does not set `needs_reply`.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_thread_classifier.py tests/test_message_sync.py -q
```

### 4. Add an index sync concurrency guard and status evidence

Owned files:
- `inbox_server.py`
- `tests/test_server.py`
- optionally `message_index_store.py` if a persistent lock/status field is needed

Change:
- Prevent `/index/sync/bootstrap` and `/index/sync/incremental` from running concurrently in the same server process.
- Return a clear 409 or structured failure when another sync is running.
- Preserve `sync_state.status`, `last_run_started_at`, and `last_error` semantics.

Acceptance criteria:
- A second sync request while one is running does not start another sync.
- The response identifies the active mode or at least reports that sync is already running.
- Existing index health tests still pass.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_server.py -q
```

### 5. Make the agent-safe validation lane enforceable

Owned files:
- `.github/workflows/agent-safe.yml`
- `docs/TESTING_FOR_AGENTS.md`
- `pyproject.toml`
- targeted test files chosen for `safe` coverage

Change:
- Add a CI workflow or equivalent local validation script for `INBOX_TEST_MODE=1`, safe pytest, ruff, and pyright.
- Expand `safe` markers for deterministic tests that do not touch live personal data, or adjust docs to name focused safe files instead of implying broad coverage.

Acceptance criteria:
- The documented safe command runs a meaningful subset of deterministic backend/client/MCP/index tests.
- Live-write, local-data, and slow tests remain opt-in.
- CI or the local script fails on lint/type/test regressions.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe -q
uv run ruff check .
uv run pyright
```

## Handoff

- Files changed by this queue item: `docs/overnight/2026-05-07-whole-portfolio-review/inbox-implementation-readiness.md`
- Product code changed: no
- PR URL: not created; external pushes and PR creation are out of scope for this queue item.
- Blockers: no local blocker for the required report. Previous overnight artifacts and CI workflows were not present in this worktree. A local commit was attempted but blocked because Git could not create `/Users/jwalinshah/projects/inbox/.git/worktrees/inbox-implementation-readiness/index.lock` from this sandboxed worktree.
- Required validation result: `git status --short` exits 0 and reports this new `docs/overnight/` report path as the only worktree change.
