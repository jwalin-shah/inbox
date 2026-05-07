# inbox-sym-115 implementation-readiness review

Date: 2026-05-07
Branch: `codex/goal-inbox-sym-115-implementation-readiness`
Repo: `inbox-sym-115`
Review type: implementation-readiness
Starting HEAD: `2805b84`

## Scope

This pass was read-only against product code. The only intended repository change
is this report under `docs/overnight/2026-05-07-whole-portfolio-review/`.

External services, deploys, pushes, PR creation, live writes, and tracker updates
were out of scope. Live provider behavior was inferred only from repo-local docs,
tests, scripts, and code.

## Evidence Reviewed

- `llm-tldr tree .`
- `git status --short --branch`
- `git rev-parse --short HEAD`
- `git log --oneline -8`
- `rg --files -g 'docs/**' -g 'runs/**' -g 'items/**' -g '.github/**'`
- `rtk read AGENTS.md`
- `rtk read CLAUDE.md`
- `rtk read README.md`
- `rtk read pyproject.toml`
- `rtk read docs/TESTING_FOR_AGENTS.md`
- `rtk read PLAN.md`
- `rtk read CONNECTOR_ROADMAP.md`
- `rtk read MCP_V1_PLAN.md`
- Targeted `rg` and `nl -ba ... | sed -n ...` reads across index, sync, MCP,
  TUI, account routing, tests, scripts, and config.

No `runs/`, `.github/`, `items/`, or prior `docs/overnight/` artifacts were
present in this worktree. The only pre-existing file under `docs/` was
`docs/TESTING_FOR_AGENTS.md`.

## Current State

The repo is ready for tightly scoped local implementation slices. The strongest
next work is around making the index-driven inbox surface operationally reliable:
safe validation coverage, index health visibility, MCP exposure of index-first
reads, and write-account/preflight enforcement.

The repo is not ready for unattended live-write validation. Several important
surfaces intentionally depend on local credentials, macOS data stores, OAuth
tokens, microphone/accessibility permissions, and personal data providers.

## File-Path Observations

1. `pyproject.toml` defines Python `>=3.12,<3.15`, first-class dev dependencies
   for `pytest`, `ruff`, `pyright`, `bandit`, `hypothesis`, and `pre-commit`,
   and pytest markers for `safe`, `integration`, `local_data`, `slow`, and
   `live_write`. Pytest always runs coverage through
   `addopts = "--cov=. --cov-report=term-missing"`.

2. `docs/TESTING_FOR_AGENTS.md` defines the intended safe loop:
   `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, and
   `uv run pyright`. It also says not to run `local_data`, `live_write`, or
   live provider-specific tests without explicit opt-in.

3. `tests/conftest.py` stubs heavyweight or host-specific modules including
   `mlx_lm`, `mlx_whisper`, `sounddevice`, `outlines`, and `Quartz`, which makes
   deterministic unit tests practical without the full macOS/ML runtime.

4. `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py` are the only
   modules currently marked with `pytestmark = pytest.mark.safe`. That means the
   documented agent-safe command does not yet exercise most deterministic index,
   sync, server, client, or write-guard behavior.

5. `inbox_test_mode.py` centralizes `INBOX_TEST_MODE`,
   `INBOX_TEST_DATA_DIR`, and live-write blocking through
   `assert_live_writes_allowed`. `tests/test_services.py` has deterministic
   checks proving representative Gmail, Calendar, Reminders, Tasks, Drive,
   Sheets, Docs, GitHub notification, desktop notification, and WhatsApp writes
   are blocked under test mode, but that module is not in the safe marker lane.

6. `message_index_store.py` has a concrete operational index schema for
   `items`, `threads`, `sync_state`, and `sender_stats`. The `threads` table
   includes `urgency`, `actionability`, `needs_reply`, `summary`, and
   `open_loop`, and `list_threads` supports actionable, recent, reply-needed,
   open-loop, sender, and priority/recent sort modes.

7. `message_sync.py` implements resumable Gmail bootstrap with
   `bootstrap_page_token`, Gmail history cursor incremental sync, timestamp
   fallback metadata, iMessage sync, scoped thread rebuilds, and CLI modes for
   `bootstrap`, `incremental`, `rebuild`, and `summary`.

8. `tests/test_message_sync.py` already validates key implementation-readiness
   behaviors: Gmail bootstrap resumes from saved page token, history cursors are
   recorded, interrupted bootstrap does not double-count, iMessage checkpoints
   advance across skipped rows, and incremental rebuild touches only changed
   Gmail or iMessage scopes.

9. `inbox_server.py` exposes index-first endpoints:
   `/index/threads`, `/index/status`, `/index/health`,
   `/index/views/{view_name}`, `/index/sync/bootstrap`, and
   `/index/sync/incremental`. The `/inbox/needs-action` endpoint prefers
   `state.index_store.list_threads` and sets `thread_read_model = "index"` and
   `raw_thread_provider_fetch = False`.

10. `tests/test_server.py` covers `/index/status`, `/index/health`, stale and
    missing checkpoints, sync errors, index view routing, and
    `/inbox/needs-action` behavior that does not fall back to live Gmail when
    the index is empty.

11. `inbox_client.py` has compact helpers for `index_threads`,
    `index_status`, `index_health`, `index_view`,
    `indexed_recent_threads`, `indexed_actionable_threads`,
    `indexed_waiting_on_me_threads`, and `indexed_waiting_on_others_threads`.
    `tests/test_client.py` covers the index helper request shapes.

12. `tui_tabs.py` makes `Now`, `Actionable`, and `Waiting On` the first three
    TUI tabs. `inbox.py` initializes the active filter to `all`, uses
    `IndexedThreadItem`, fetches `recent`, `actionable`, and `waiting-on` index
    views during refresh, and can render indexed thread summaries without raw
    thread bodies.

13. `google_account_resolution.py` centralizes Google account resolution around
    `INBOX_DEFAULT_GOOGLE_ACCOUNT`, message/thread owner lookup, and a
    `preflight_google_write_payload` helper for Docs, Sheets, Drive folders,
    Tasks, and Calendar events. `tests/test_server.py` already validates default
    account resolution and preflight result payloads.

14. `inbox_server.py` exposes `/preflight/google-write`, but create/write
    endpoints such as `/docs`, `/calendar/events`, `/drive/folder`, Sheets
    range writes, and task creation still need an explicit pass to ensure the
    same preflight policy is enforced before mutation rather than only being
    available for manual inspection.

15. `tools_registry.py` is a strong MCP readiness foundation: one `TOOLS` table
    drives full and readonly MCP registration, path parameters are encoded, and
    confirm-gated tools require `confirm=True`. However, `rg` found no indexed
    inbox, index health, or needs-action tools in the MCP registry.

16. `tests/test_api_contract.py` protects registry-to-FastAPI route drift and
    verifies `InboxClient.index_status()` and `InboxClient.index_health()` match
    server response shape. It does not yet assert MCP exposure for index-first
    inbox reads because those tools do not exist.

17. `mcp_server.py`, `mcp_backend.py`, `mcp_gateway.py`,
    `inbox_mcp_readonly.py`, and `tests/test_mcp_gateway.py` show a clear
    public/private token split: `INBOX_MCP_TOKEN` protects the public MCP layer,
    and `INBOX_SERVER_TOKEN` protects the private local REST backend.

18. `MCP_SETUP.md`, `config/inbox.env.example`,
    `config/codex.inbox.example.toml`, and
    `config/gemini-settings.inbox.example.json` document the backend URL/token
    split and dev-vs-primary routing, including the warning not to reuse the
    public MCP token as the private server token.

19. `scripts/run_inbox_backend.sh` and
    `scripts/run_inbox_mcp_http_readonly.sh` set `UV_CACHE_DIR=/tmp/uv-cache`
    before launching backend/MCP processes. `dev.sh` defaults dev worktrees to
    port `9850`, separate from the primary `9849` instance.

20. `.gitignore` excludes credentials, OAuth tokens, local env files, logs,
    `.claude/`, `.inbox_memory.sqlite3`, `.inbox_scheduler.sqlite3`,
    `.inbox_index.sqlite3`, coverage output, batch state, and batch logs.

## Risks And Blockers

- The documented safe validation lane is too narrow. Because only two test
  modules are marked `safe`, the default command can pass while index/sync/server
  behavior is untested.

- The index can be stale, missing, or in error, but `inbox.py` does not currently
  appear to consume `InboxClient.index_health()`. A stale empty index could look
  like an empty Now/Actionable/Waiting surface instead of an operational problem.

- MCP users cannot yet ask for index-first views through the registry, even
  though the FastAPI server and client have index endpoints. That can push agents
  back toward raw provider reads.

- Write preflight exists as an endpoint and helper, but implementation work is
  still needed to make preflight policy part of the write path for each Google
  mutation family.

- Live provider validation needs credentials and explicit approval. This review
  did not run live Gmail, Calendar, Drive, Docs, Sheets, Tasks, iMessage,
  Reminders, Notes, GitHub, audio, dictation, notification, or MCP public
  exposure flows.

- No repo-local `.github/` workflow files were present, so CI behavior could not
  be inspected from this worktree.

- No prior `runs/*/result.json` or `runs/*/handoff.md` artifacts were present in
  this repo checkout, so this pass could not reconcile earlier runner outputs.

## Validation Commands

Required queue validation:

```bash
git status --short
```

Agent-safe repo validation documented by the project:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe
uv run ruff check .
uv run pyright
```

Focused validations recommended for the follow-up slices below:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_message_sync.py tests/test_message_index_store.py tests/test_server.py tests/test_client.py tests/test_api_contract.py -q
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_app.py tests/test_tui_tabs.py tests/test_client.py -q
INBOX_TEST_MODE=1 uv run pytest tests/test_api_contract.py tests/test_mcp_gateway.py -q
INBOX_TEST_MODE=1 uv run pytest tests/test_server.py -k "preflight or create_doc or create_spreadsheet or create_drive_folder or create_event or create_task" -q
bash -n batch/batch-runner.sh
```

## Implementation-Ready Follow-Up Tasks

### 1. Promote deterministic index and write-guard tests into the safe lane

Owned files:
- `tests/test_message_sync.py`
- `tests/test_message_index_store.py`
- `tests/test_server.py`
- `tests/test_client.py`
- `tests/test_api_contract.py`
- `tests/test_services.py`
- `docs/TESTING_FOR_AGENTS.md`

Acceptance criteria:
- Deterministic tests for index status/health, index view routing, sync resume,
  scoped rebuild, client index helpers, API contract, and test-mode write guards
  are marked `safe`.
- No tests requiring real local data or provider writes are marked `safe`.
- `docs/TESTING_FOR_AGENTS.md` names a focused safe command for index/sync work.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe -q
```

### 2. Surface index health in the TUI Now, Actionable, and Waiting On views

Owned files:
- `inbox.py`
- `inbox_client.py` if a small helper or response normalization is needed
- `tests/test_inbox_app.py`
- `tests/test_client.py`

Acceptance criteria:
- Refresh fetches `/index/health` once and stores the health payload.
- Now, Actionable, and Waiting On empty or stale states distinguish "no indexed
  work" from `no_sync_state`, `missing_checkpoint`, `stale_checkpoint`, and
  `sync_error`.
- Existing indexed thread rendering still works when the health response is
  healthy.
- No raw provider thread fetch is added to these index-first views.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_app.py tests/test_client.py -q
```

### 3. Expose index-first inbox reads through the MCP tool registry

Owned files:
- `tools_registry.py`
- `tests/test_api_contract.py`
- `tests/test_mcp_gateway.py`
- `MCP_V1_PLAN.md` or `MCP_SETUP.md` if docs need the new tool names

Acceptance criteria:
- Add readonly registry tools for index status, index health, a selected index
  view, and needs-action rollup.
- Full and readonly MCP servers both register these readonly tools.
- Route-contract tests prove every new tool maps to an existing FastAPI route.
- Returned thread payloads stay compact and do not expose `body_text`.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_api_contract.py tests/test_mcp_gateway.py -q
```

### 4. Enforce Google write preflight policy on initial mutation paths

Owned files:
- `google_account_resolution.py`
- `inbox_server.py`
- `tests/test_server.py`

Acceptance criteria:
- Docs, Sheets, Drive folder, Google Task, and Calendar create paths resolve the
  same account and destination that `/preflight/google-write` would report.
- Invalid folder, task list, or missing-account preflight failures return a
  client error before calling provider write functions.
- Explicit `account` overrides continue to work when the account exists.
- Tests use mocks only and do not require live Google credentials.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_server.py -k "preflight or create_doc or create_spreadsheet or create_drive_folder or create_event or create_task" -q
```

### 5. Add deterministic safety tests for the batch archive runner

Owned files:
- `batch/batch-runner.sh`
- `tests/test_batch_runner.py`
- `batch/archive-input.tsv` only if a tiny fixture input is needed

Acceptance criteria:
- `bash -n batch/batch-runner.sh` passes.
- A new deterministic test runs `--dry-run` against a temp-copied batch
  directory and proves no curl/write call is executed.
- Thread IDs and JSON payload construction are shell-safe for ordinary Gmail
  IDs and fail closed for unsupported sources.
- The runner keeps `archive-state.tsv` and `batch/logs/` out of git, consistent
  with `.gitignore`.

Smallest useful validation:

```bash
bash -n batch/batch-runner.sh
INBOX_TEST_MODE=1 uv run pytest tests/test_batch_runner.py -q
```

## Handoff Notes

- Product code was not edited.
- No external services were called.
- No PR was created.
- No tracker state was changed.
- The required validation for this queue item is `git status --short`.
