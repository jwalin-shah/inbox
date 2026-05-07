# Inbox 30 Minute Extension Action Plan

Date: 2026-05-07
Repo: inbox
Branch: codex/goal-inbox-30min-action-plan
Base HEAD: 2805b8400519da188ca7d3f6e39b19a8ca42b05a

## Scope

This was a read-only planning audit of the inbox repo. I did not edit product code. The only intended repo change from this worker is this report.

The audit focused on:

- repo docs and stated product direction
- current validation surface
- recent merged work that already covered overnight-style concerns
- index, sync, TUI, MCP, account routing, and task-link handoff gaps

## Previous Report Reconciliation

No prior overnight report was present in this worktree. `docs/` only contained `docs/TESTING_FOR_AGENTS.md` before this report, and searches for `docs/overnight`, `runs/**/result.json`, `runs/**/handoff.md`, and `handoff.md` found no repo-local artifacts to reconcile.

What recent repo work already covered:

- `a821b5a Make indexed inbox views the default` added indexed client/server behavior and tests across `inbox_client.py`, `inbox_server.py`, `message_index_store.py`, and API tests.
- `05fc249 Add index sync health endpoint` added `/index/health` and server tests.
- `44be0c8 Avoid large thread cleanup expressions` hardened `message_index_store.py` rebuild cleanup for large thread sets.
- `9825e50 Fix TUI refresh snapshots` repaired TUI refresh state around indexed views.

What is still missing:

- There is no recorded implementation queue item tying these index improvements to MCP tools, TUI stale-state behavior, or automatic freshness recovery.
- There is no repo-local overnight report preserving the validation state and blockers found below.
- Some docs still describe old health claims, especially total tests and "all tests pass" claims.

## Current Repo Health

Commands run:

- `git status --short`: passed before edits with no output.
- `UV_CACHE_DIR=/private/tmp/uv-cache-inbox uv run ruff check .`: passed with `All checks passed!`.
- `UV_CACHE_DIR=/private/tmp/uv-cache-inbox INBOX_TEST_MODE=1 uv run pytest -m safe -q`: passed, `11 passed, 855 deselected in 10.25s`.
- `UV_CACHE_DIR=/private/tmp/uv-cache-inbox INBOX_TEST_MODE=1 uv run pytest tests/test_message_sync.py tests/test_message_index_store.py tests/test_server.py::TestIndexEndpoints tests/test_api_contract.py -q`: passed, `37 passed in 7.89s`.
- `UV_CACHE_DIR=/private/tmp/uv-cache-inbox uv run pyright`: failed with 108 errors.

Validation caveat:

- Running `INBOX_TEST_MODE=1 uv run pytest -m safe -q` without `UV_CACHE_DIR` initially failed because the sandbox could not open `/Users/jwalinshah/.cache/uv/sdists-v9/.git`. Use `UV_CACHE_DIR=/private/tmp/uv-cache-inbox` in this worktree.

Known type blockers from `pyright`:

- `inbox.py:1888`, `inbox.py:1896`, `inbox.py:1907`, `inbox.py:1909`, `inbox.py:1923`, `inbox.py:1927`, `inbox.py:1931`: Textual `Widget` narrowing issues around list/table cursor actions.
- `inbox.py:4131`: unresolved `agents.runner` import.
- `inbox_mcp_readonly.py:47`: `ambient_notes.VAULT_DIR` is referenced, but the module exposes `VAULT_PATH`, `DAILY_DIR`, and `AMBIENT_DIR` in tests.
- `inbox_server.py:3905` through `inbox_server.py:3909`: unresolved `gemma4_hackathon.silos.*` imports.
- `services.py` has many dynamic Google API and macOS framework attribute errors, especially around `Quartz`, Accessibility APIs, Sheets, Docs, Drive, and Calendar service objects.

## Concrete File Observations

1. `PLAN.md` defines the active product direction as an indexed local-first inbox OS, not raw provider tabs. Phase 1 explicitly prioritizes reliable bootstrap/incremental sync, indexed endpoints, and a TUI home surface.

2. `message_index_store.py:86` to `message_index_store.py:160` defines the local operational index tables: `sync_state`, `items`, `threads`, and `sender_stats`. The schema already has status, run-start, metadata, and last-error fields needed for health reporting.

3. `message_index_store.py:239` to `message_index_store.py:356` implements `set_sync_state`, `mark_sync_started`, `update_sync_progress`, `record_sync_error`, and sync-state reads. This gives implementation agents a durable checkpoint/status surface instead of relying on logs.

4. `message_index_store.py:407` to `message_index_store.py:563` rebuilds thread rows from indexed items, refreshes sender stats, classifies each thread, and deletes stale thread rows within the rebuild scope. The recent temp-table cleanup avoids expression depth failures.

5. `message_index_store.py:565` to `message_index_store.py:612` supports the indexed views with filters for `actionable_only`, `newest_only`, explicit actions, `needs_reply`, `has_open_loop`, `latest_sender`, and priority/recent sorting.

6. `message_sync.py:181` to `message_sync.py:269` implements resumable Gmail bootstrap using saved `bootstrap_page_token`, timestamp checkpoint metadata, and an optional Gmail history cursor after full sync.

7. `message_sync.py:272` to `message_sync.py:420` implements Gmail incremental sync through history API when a cursor is present, with timestamp fallback when the cursor or history API is missing.

8. `message_sync.py:498` to `message_sync.py:580` advances iMessage rowid checkpoints even when rows are skipped because message bodies are empty or cleaned away. Tests cover this behavior.

9. `message_sync.py:602` to `message_sync.py:627` rebuilds only changed Gmail/iMessage scopes after bootstrap or incremental sync. This is the right shape for cheap recurring sync work.

10. `inbox_server.py:2771` to `inbox_server.py:2807` maps named index views to store queries. The server supports `actionable`, `recent`, `waiting-on-me`, `waiting-on-others`, and `waiting-on`.

11. `inbox_server.py:2810` to `inbox_server.py:2898` marks index health stale after 30 minutes and reports `no_sync_state`, `missing_checkpoint`, `stale_checkpoint`, and `sync_error`.

12. `inbox_server.py:3739` to `inbox_server.py:3802` makes `/inbox/needs-action` use index threads only and explicitly avoids live Gmail thread fallback when the index is empty.

13. `inbox_server.py:3820` to `inbox_server.py:3853` exposes `/index/status`, `/index/health`, `/index/views/{view_name}`, `/index/sync/bootstrap`, and `/index/sync/incremental`.

14. `inbox_client.py:90` to `inbox_client.py:131` already has client helpers for index status, health, generic index view, recent, actionable, waiting-on-me, and waiting-on-others.

15. `inbox.py:1702` to `inbox.py:1723` renders the TUI `Now`, `Actionable`, and `Waiting On` indexed lists. `inbox.py:2328` to `inbox.py:2349` refreshes `recent`, `actionable`, and `waiting-on`, but does not consume `waiting-on-me`, `waiting-on-others`, or `/index/health`.

16. `inbox.py:2720` to `inbox.py:2749` shows indexed thread summaries as a synthetic message from "Inbox Index", which keeps the first view compact but leaves raw-thread drilldown as a future UX problem.

17. `tui_tabs.py:16` to `tui_tabs.py:48` makes `Now`, `Actionable`, and `Waiting On` first-class tabs before raw source tabs. This matches the phase-1 information architecture.

18. `google_account_resolution.py:24` to `google_account_resolution.py:33` honors `INBOX_DEFAULT_GOOGLE_ACCOUNT` only if the account exists in the service map. `config/inbox.env.example` does not document this variable yet.

19. `google_account_resolution.py:85` to `google_account_resolution.py:106` resolves Gmail reply ownership from explicit account, conversation cache, or live message/thread existence before falling back to default.

20. `google_account_resolution.py:160` to `google_account_resolution.py:304` already has a preflight payload builder for Drive/Docs/Sheets, Tasks, and Calendar write destinations.

21. `tools_registry.py` centralizes MCP tool definitions and confirm gates. A search for `/index`, `index_health`, `index_status`, `index_view`, and `indexed_` across `tools_registry.py`, `mcp_backend.py`, `mcp_server.py`, and `inbox_mcp_readonly.py` found no index MCP tools yet.

22. `mcp_gateway.py` authenticates public MCP requests with `INBOX_MCP_TOKEN` while `mcp_backend.py` forwards `INBOX_SERVER_TOKEN` to the private REST server. `tests/test_mcp_gateway.py:18` marks these tests safe and `tests/test_mcp_gateway.py:44` to `tests/test_mcp_gateway.py:51` covers public token rejection/acceptance.

23. `tools_registry.py:630` to `tools_registry.py:666` exposes task-message linking tools over MCP, including `create_task_from_message`.

24. `inbox_server.py:441` to `inbox_server.py:450` defines `TaskFromMessageRequest` without a due-date field. `inbox_server.py:2152` to `inbox_server.py:2191` creates a task, then finds the newly-created task by matching title from `tasks_list`, which is brittle when duplicate task titles exist.

25. `services.py:3164` to `services.py:3183` returns only `bool` from `task_create`, discarding the Google Tasks API response that could provide a durable task id.

26. `docs/TESTING_FOR_AGENTS.md` correctly tells agents to use `INBOX_TEST_MODE=1`, safe pytest markers, ruff, and pyright. `pyproject.toml` registers `safe`, `integration`, `local_data`, `slow`, and `live_write` markers.

27. `DOCS_INDEX.md:44` and `DOCS_INDEX.md:140` still claim `uv run pytest` has 736 passing tests and that all 736 tests pass. The safe-marker run collected 866 tests total (`11 passed, 855 deselected`), and full pyright currently fails.

## Risks And Blockers

- `pyright` is not a passing validation gate today. It reports 108 errors across product code, tests, dynamic Google clients, macOS APIs, and missing optional modules.
- Index freshness exists as an endpoint but is not surfaced in the TUI. A stale or never-built index can make `Now` look empty without clearly telling the user why.
- The TUI consumes the broad `waiting-on` view but leaves server/client support for `waiting-on-me` and `waiting-on-others` unused.
- MCP clients cannot currently ask for compact indexed views or index health even though the REST and TUI layers can.
- `create_task_from_message` can link the wrong Google Task when task titles collide, because `task_create` drops the inserted task response and the server re-queries by title.
- Live provider health was not validated. This audit avoided local personal data, live Google writes, AppleScript writes, microphone access, and external services.
- No previous overnight report was available, so there was no prior report content to explicitly close out.

## Implementation Queue

### 1. Surface Index Freshness In The TUI

Owned files:

- `inbox_client.py`
- `inbox.py`
- `tests/test_client.py`
- `tests/test_inbox_app.py`
- `tests/test_server.py`

Acceptance criteria:

- `InboxClient.index_health()` is used by the TUI refresh path.
- The `Now` and indexed tab status bars show stale/no-sync/error reasons when `/index/health` is unhealthy.
- A stale index does not silently render as just an empty useful inbox.
- Tests cover healthy index, `no_sync_state`, `stale_checkpoint`, and `sync_error` status text.
- Validation: `UV_CACHE_DIR=/private/tmp/uv-cache-inbox INBOX_TEST_MODE=1 uv run pytest tests/test_client.py tests/test_inbox_app.py tests/test_server.py::TestIndexEndpoints -q`.

### 2. Split Waiting-On TUI Into Me vs Others

Owned files:

- `tui_tabs.py`
- `inbox.py`
- `inbox_client.py`
- `tests/test_tui_tabs.py`
- `tests/test_client.py`
- `tests/test_inbox_app.py`

Acceptance criteria:

- The TUI exposes separate views for `waiting-on-me` and `waiting-on-others`, or a clear toggle within Waiting On.
- `waiting-on-me` calls the existing `/index/views/waiting-on-me` path.
- `waiting-on-others` calls the existing `/index/views/waiting-on-others` path.
- The older `waiting-on` track/open-loop view remains available or is intentionally renamed.
- Tests assert the correct endpoint names and status text for each view.
- Validation: `UV_CACHE_DIR=/private/tmp/uv-cache-inbox INBOX_TEST_MODE=1 uv run pytest tests/test_tui_tabs.py tests/test_client.py tests/test_inbox_app.py -q`.

### 3. Expand Thread Classification Fixtures Before Changing Heuristics

Owned files:

- `thread_classifier.py`
- `tests/test_thread_classifier.py`
- `tests/test_message_index_store.py`
- optional helper file if fixtures become repetitive

Acceptance criteria:

- Add representative tests for recruiter outreach, direct human follow-up, newsletter/job alert, receipt/order, OTP, security alert, medical appointment, and billing/admin follow-up.
- Tests pin `noise_class`, `topic`, `urgency`, `actionability`, `needs_reply`, and `open_loop`.
- Existing OTP ignore behavior remains unchanged.
- Classifier changes, if any, are limited to improving failures in those fixtures.
- Validation: `UV_CACHE_DIR=/private/tmp/uv-cache-inbox INBOX_TEST_MODE=1 uv run pytest tests/test_thread_classifier.py tests/test_message_index_store.py -q`.

### 4. Expose Compact Index Tools Through MCP

Owned files:

- `tools_registry.py`
- `mcp_backend.py`
- `tests/test_tools_registry.py`
- `tests/test_api_contract.py`
- `tests/test_mcp_gateway.py`
- `MCP_SETUP.md`

Acceptance criteria:

- Add read-only MCP tools for index health/status and named indexed views.
- Add confirm-gated MCP tools for `/index/sync/incremental` and, if included, `/index/sync/bootstrap`.
- Read-only MCP registration includes only safe index read tools.
- Full MCP registration includes sync tools with `confirm=True`.
- API-contract tests prove every new MCP tool routes to a FastAPI endpoint.
- Docs explain that local assistants should prefer compact index tools before raw Gmail/iMessage reads.
- Validation: `UV_CACHE_DIR=/private/tmp/uv-cache-inbox INBOX_TEST_MODE=1 uv run pytest tests/test_tools_registry.py tests/test_api_contract.py tests/test_mcp_gateway.py -q`.

### 5. Make Task-From-Message Linking Use Durable Task IDs

Owned files:

- `services.py`
- `inbox_server.py`
- `inbox_client.py`
- `mcp_backend.py`
- `tools_registry.py`
- `scheduler.py`
- `tests/test_server.py`
- `tests/test_client.py`
- `tests/test_tools_registry.py`

Acceptance criteria:

- `task_create` returns the created Google Task id or task payload instead of only `bool`.
- `/tasks/from-message` links the created task by returned id, not by re-querying recent tasks by title.
- Duplicate task titles cannot cause a link to point at the wrong task.
- The endpoint response includes resolved account, list id, task source, task id, and link id.
- MCP and client helpers preserve the same response shape.
- Tests cover duplicate-title safety and existing Reminder fallback behavior.
- Validation: `UV_CACHE_DIR=/private/tmp/uv-cache-inbox INBOX_TEST_MODE=1 uv run pytest tests/test_server.py tests/test_client.py tests/test_tools_registry.py -q`.

## Suggested Order

1. Surface index freshness in TUI.
2. Expose compact index tools through MCP.
3. Split waiting-on views.
4. Expand classifier fixtures.
5. Fix task-from-message durable IDs.

This order keeps the default indexed inbox path observable first, lets agents consume the same compact state, then improves classification and task handoff safety.
