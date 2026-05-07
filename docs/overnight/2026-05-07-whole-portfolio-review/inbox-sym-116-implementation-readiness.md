# inbox-sym-116 Implementation Readiness Review

Date: 2026-05-07
Branch: `codex/goal-inbox-sym-116-implementation-readiness`
Starting HEAD: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`
Scope: read-only review plus this report only.

## Summary

`inbox-sym-116` is implementation-ready for small vertical slices around the indexed inbox, MCP/tool surfacing, account-routing policy, and validation hygiene. The highest-leverage next work is not a broad rewrite: it is wiring already-built index and policy primitives into the surfaces agents actually use, then tightening the safe validation lane so future workers can prove changes without touching live personal data.

No repo-local `docs/overnight/` report, `runs/*/result.json`, or `runs/*/handoff.md` was present before this pass. No `.github` workflow directory was present in this worktree, so local validation commands are the only repo-local validation evidence available.

## Concrete Observations

1. [PLAN.md](../../../PLAN.md) defines the product direction as an operational indexed inbox, with raw providers relegated to drill-down, and names `message_sync.py`, `message_index_store.py`, `inbox_server.py`, and tests as Milestone 1 ownership.
2. [message_index_store.py](../../../message_index_store.py) already has persistent `sync_state`, `items`, `threads`, and `sender_stats` tables, including `status`, `last_run_started_at`, `metadata_json`, and `last_error` fields for sync observability.
3. [message_sync.py](../../../message_sync.py) already supports resumable Gmail bootstrap via `bootstrap_page_token`, records Gmail `historyId` cursors, falls back to timestamp cursors, and has scoped thread rebuild paths for changed accounts/sources.
4. [inbox_server.py](../../../inbox_server.py) exposes index-first endpoints: `/index/threads`, `/index/status`, `/index/health`, `/index/views/{view_name}`, `/index/sync/bootstrap`, and `/index/sync/incremental`.
5. [tests/test_message_sync.py](../../../tests/test_message_sync.py) covers bootstrap resume after interruption, duplicate avoidance on resume, Gmail history incremental sync, timestamp fallback, skipped iMessage checkpoint advancement, and scoped incremental thread rebuilds.
6. [tests/test_server.py](../../../tests/test_server.py) covers index endpoint response shape, health reasons (`no_sync_state`, `missing_checkpoint`, `stale_checkpoint`, `sync_error`), and the current contract that `/inbox/needs-action` does not fall back to live Gmail when the index is empty.
7. [inbox_client.py](../../../inbox_client.py) has client helpers for index status, health, and named indexed views, and [inbox.py](../../../inbox.py) already fetches `recent`, `actionable`, and `waiting-on` views for the TUI auxiliary data path.
8. [tools_registry.py](../../../tools_registry.py) drives full and read-only MCP tool registration from one table and tests enforce confirm-gating, but the registry does not currently expose the index health/status/view endpoints or `/preflight/google-write`.
9. [google_account_resolution.py](../../../google_account_resolution.py) centralizes Google account resolution and honors `INBOX_DEFAULT_GOOGLE_ACCOUNT`, but most returned API models still expose `account` rather than the roadmap's explicit `owning_account` field.
10. [CONNECTOR_ROADMAP.md](../../../CONNECTOR_ROADMAP.md) says Google writes should default to `jshah1331@gmail.com` via `INBOX_DEFAULT_GOOGLE_ACCOUNT`, replies should route to object ownership, and the model should prefer intent-level tools over raw provider payloads.
11. [docs/TESTING_FOR_AGENTS.md](../../TESTING_FOR_AGENTS.md) declares the default safe loop as `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, and `uv run pyright`; [pyproject.toml](../../../pyproject.toml) registers `safe`, `integration`, `local_data`, `slow`, and `live_write` markers.
12. Only two test modules are currently marked safe: [tests/test_inbox_test_mode.py](../../../tests/test_inbox_test_mode.py) and [tests/test_mcp_gateway.py](../../../tests/test_mcp_gateway.py), while the repo has 31 test files. The documented safe lane is therefore too narrow for implementation handoffs.
13. [DOCS_INDEX.md](../../../DOCS_INDEX.md) still claims `uv run pytest` is "Tests (736 pass)" and "All 736 tests pass"; this review did not run the full suite, so future work should treat that as stale until revalidated.
14. [README.md](../../../README.md) says Python 3.10+ is required, while [pyproject.toml](../../../pyproject.toml) requires `>=3.12,<3.15`.
15. [.mcp.json](../../../.mcp.json) and [.cursor/mcp.json](../../../.cursor/mcp.json) point assistants at `http://127.0.0.1:9849`; [MCP_SETUP.md](../../../MCP_SETUP.md) and [CLAUDE.md](../../../CLAUDE.md) correctly warn that dev worktrees must use a distinct `cwd` and `INBOX_SERVER_URL` to avoid silently exercising the primary instance.
16. [batch/batch-runner.sh](../../../batch/batch-runner.sh) removes the `INBOX` label for Gmail archive operations, while [modes/batch-archive.md](../../../modes/batch-archive.md) documents adding an `ARCHIVED` label and refers to `thread_id` as the batch modify ID. This is likely to confuse the next automation slice.

## Risks And Blockers

- Live personal data and writes are a standing risk. Any implementation work should run with `INBOX_TEST_MODE=1` and avoid `local_data` or `live_write` tests unless explicitly approved.
- CI evidence is absent in this worktree because no `.github` workflows are present. Workers should report local validation commands exactly.
- The safe marker lane is underdeveloped relative to the documented agent workflow, so `pytest -m safe` can pass while leaving index, server, and MCP registry behavior untested.
- The index-first backend exists, but agent-facing MCP tools and slash-mode docs still emphasize raw provider endpoints. That increases the chance that future agents bypass the operational index.
- Primary/dev routing remains easy to misconfigure because repo-local MCP configs default to port 9849. Worktree testing needs explicit `INBOX_SERVER_URL=http://127.0.0.1:9850` or higher.
- Some documentation is stale against package metadata and validation reality, notably the Python version and "736 pass" claims.

## Validation Commands

Queue-item validation run:

```bash
git status --short
```

Useful implementation validation commands for future slices:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe -q
INBOX_TEST_MODE=1 uv run pytest tests/test_message_sync.py tests/test_message_index_store.py -q
INBOX_TEST_MODE=1 uv run pytest tests/test_server.py tests/test_client.py tests/test_api_contract.py -q
INBOX_TEST_MODE=1 uv run pytest tests/test_tools_registry.py tests/test_mcp_gateway.py -q
uv run ruff check .
uv run pyright
bash -n batch/batch-runner.sh
```

Do not run live provider, local data, or live-write tests without explicit approval.

## Implementation-Ready Follow-Up Tasks

### 1. Expose Indexed Inbox Views Through MCP

Owned files: [tools_registry.py](../../../tools_registry.py), [mcp_backend.py](../../../mcp_backend.py), [tests/test_tools_registry.py](../../../tests/test_tools_registry.py), [tests/test_api_contract.py](../../../tests/test_api_contract.py).

Acceptance criteria:
- Read-only MCP includes tools for `index_status`, `index_health`, and named `index_view`.
- Full MCP includes the same read-only index tools.
- Route contract tests prove every new MCP tool maps to an existing FastAPI endpoint.
- Returned payloads preserve `read_model: "index"` and `raw_provider_fetch: false`.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_tools_registry.py tests/test_api_contract.py -q
```

### 2. Make The Safe Test Lane Cover Core Agent Work

Owned files: [tests/test_message_sync.py](../../../tests/test_message_sync.py), [tests/test_message_index_store.py](../../../tests/test_message_index_store.py), [tests/test_server.py](../../../tests/test_server.py), [tests/test_client.py](../../../tests/test_client.py), [tests/test_tools_registry.py](../../../tests/test_tools_registry.py), [docs/TESTING_FOR_AGENTS.md](../../TESTING_FOR_AGENTS.md).

Acceptance criteria:
- Deterministic index, server-contract, client, and MCP-registry tests are marked `safe`.
- Tests that can touch user data or live writes remain unmarked or explicitly marked `local_data` / `live_write`.
- `docs/TESTING_FOR_AGENTS.md` states what the safe lane covers and what it deliberately excludes.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe -q
```

### 3. Surface Index Health In The TUI And Client Workflow

Owned files: [inbox_client.py](../../../inbox_client.py), [inbox.py](../../../inbox.py), [tests/test_client.py](../../../tests/test_client.py), [tests/test_inbox_app.py](../../../tests/test_inbox_app.py), [tests/test_server.py](../../../tests/test_server.py).

Acceptance criteria:
- Refresh/poll paths fetch `/index/health` alongside indexed views.
- The TUI status bar distinguishes empty healthy views from stale/error/no-sync index states.
- Tests cover fresh, stale, error, and no-sync health payloads without live provider access.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_client.py tests/test_inbox_app.py tests/test_server.py -q
```

### 4. Add Account Ownership Contract Tests For Google Writes

Owned files: [google_account_resolution.py](../../../google_account_resolution.py), [inbox_server.py](../../../inbox_server.py), [service_models.py](../../../service_models.py), [tests/test_gmail_actions.py](../../../tests/test_gmail_actions.py), [tests/test_server_endpoints.py](../../../tests/test_server_endpoints.py).

Acceptance criteria:
- Tests prove `INBOX_DEFAULT_GOOGLE_ACCOUNT` is honored for Docs, Sheets, Drive folders, Tasks, Calendar events, and Gmail compose when no explicit account is supplied.
- Gmail reply tests continue proving message/thread owner routing wins over the default when ownership can be resolved.
- Returned Google objects expose an explicit ownership field, either by standardizing on `owning_account` or by documenting and testing `account` as the stable ownership field.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_gmail_actions.py tests/test_server_endpoints.py -q
```

### 5. Align Batch Archive Workflow With Actual Gmail Semantics

Owned files: [batch/batch-runner.sh](../../../batch/batch-runner.sh), [modes/batch-archive.md](../../../modes/batch-archive.md), [tests/test_tools_registry.py](../../../tests/test_tools_registry.py) if MCP/tool semantics change.

Acceptance criteria:
- The mode doc and shell runner agree on whether inputs are Gmail message IDs or thread IDs.
- The archive payload matches the real server contract and no longer documents a nonexistent `ARCHIVED` label requirement.
- Dry-run behavior remains non-mutating and reports exactly what would be archived.
- Any required ID resolution is implemented before mutating Gmail labels.

Smallest useful validation:

```bash
bash -n batch/batch-runner.sh
INBOX_TEST_MODE=1 uv run pytest tests/test_tools_registry.py -q
```

## Handoff Notes

- Product code was not edited.
- This report is the only intended file change.
- External services, pushes, PR creation, tracker updates, and live provider checks were not performed.
- Required validation command `git status --short` ran successfully; output showed `?? docs/overnight/` because this new report is uncommitted.
- Local commit was attempted but blocked by sandbox permissions: Git tried to create `/Users/jwalinshah/projects/inbox/.git/worktrees/inbox-sym-116-implementation-readiness/index.lock`, which is outside the writable roots.
- No PR was created.
