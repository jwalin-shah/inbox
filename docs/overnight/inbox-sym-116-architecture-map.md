# inbox-sym-116 architecture-map audit

Date: 2026-05-07
Queue item: inbox-sym-116-architecture-map
Focus area: architecture-map
Repo path: `/Users/jwalinshah/projects/agent-stack/.agent-stack-worktrees/2026-05-07-overnight-marathon/inbox-sym-116-architecture-map`

## Scope and state

This was a read-only architecture audit. I did not touch product code, generated data, secrets, external services, deploys, pushes, or PRs. The only intended repository mutation is this report at `docs/overnight/inbox-sym-116-architecture-map.md`.

Observed repository state:

- Branch: `codex/goal-inbox-sym-116-architecture-map`.
- Starting HEAD: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`.
- Starting dirty state: `git status --short --branch` returned only `## codex/goal-inbox-sym-116-architecture-map`, so the worktree was clean before this report.
- `llm-tldr tree .` showed a flat Python application with top-level service, UI, MCP, indexing, scheduler, and test modules rather than a package directory hierarchy.
- `fd -t f . docs` showed only `docs/TESTING_FOR_AGENTS.md` before this report, so `docs/overnight/` is new for this queue item.

## Repo purpose

`inbox-sym-116` is a local-first personal communication and productivity control plane. The intended user-facing shape is a Textual TUI and local FastAPI server that consolidate iMessage, Gmail, Calendar, Docs, Sheets, Drive, Notes, Reminders, GitHub notifications, audio/LLM helpers, and MCP access for agents.

The intended architecture is documented as a client-server split:

- `README.md:128-144` says `services.py` is the data layer, `inbox_server.py` is the FastAPI wrapper, `inbox_client.py` is the HTTP client, and `inbox.py` is the Textual TUI.
- `CLAUDE.md:74-88` expands that map with MCP, scheduler, contacts, ambient notes, local memory, token files, and local credential files.
- `CONNECTOR_ROADMAP.md:15-24` states the target layering more explicitly: source adapters, normalization layer, policy layer, and intent tools.

The implemented architecture is close to that intent at the outer boundaries, but internally it is still dominated by two large hubs:

- `services.py` is 6,467 lines and explicitly says "All data fetching, auth, mutation, audio, and LLM logic lives here" at `services.py:1-4`.
- `inbox.py` is 4,279 lines and owns most UI models, screens, key bindings, background workers, and assistant-control-plane calls.
- `inbox_server.py` is 3,940 lines and imports a very broad service surface directly from `services.py` at `inbox_server.py:61-141`.

## Commands run

Architecture and state commands:

- `llm-tldr tree .`
- `git status --short --branch`
- `git log --oneline -5`
- `git branch --show-current`
- `git rev-parse HEAD`
- `wc -l *.py tests/*.py`
- `rg -n "^(class|def|async def) " *.py`
- `llm-tldr search "if __name__|FastAPI|uvicorn|MCP|FastMCP|class .*App|Textual|@app|@mcp" .`
- `rg --files | rg '^agents/'`
- `rg -n "from agents|import agents|agents/" .`

Docs, config, and validation commands:

- `rtk read pyproject.toml`
- `rtk read README.md`
- `rtk read CLAUDE.md`
- `rtk read CONNECTOR_ROADMAP.md`
- `rtk read MCP_V1_PLAN.md`
- `rtk read DOCS_INDEX.md`
- `rtk read docs/TESTING_FOR_AGENTS.md`
- `rg -n "Python 3\\.10|requires-python|736|production-ready|All .*tests pass|TUI tab|Complete|local-first|no cloud|Qwen|Gemini|default 9849|port 9849" README.md DOCS_INDEX.md CLAUDE.md pyproject.toml CONNECTOR_ROADMAP.md`
- `rg -n "addopts|markers|safe|pytest|ruff|pyright|bandit" pyproject.toml docs/TESTING_FOR_AGENTS.md tests/conftest.py`
- `rg --files -uu | rg '(^|/)(\\.gitignore|credentials\\.json|token\\.json|tokens|github_token\\.txt|google_maps_key\\.txt|gemini_api_key\\.txt|\\.env|\\.inbox_.*\\.sqlite3|server\\.log)$'`
- `nl -ba .gitignore | sed -n '1,160p'`

Focused code reads:

- `nl -ba inbox_server.py | sed -n '1,140p'`
- `nl -ba inbox_server.py | sed -n '750,860p'`
- `nl -ba inbox_server.py | sed -n '1198,1368p'`
- `nl -ba inbox_server.py | sed -n '1363,1605p'`
- `nl -ba inbox_server.py | sed -n '2900,3035p'`
- `nl -ba inbox_server.py | sed -n '3670,3905p'`
- `nl -ba services.py | sed -n '1,140p'`
- `nl -ba services.py | sed -n '315,433p'`
- `nl -ba services.py | sed -n '3800,3990p'`
- `nl -ba services.py | sed -n '4020,4368p'`
- `nl -ba services.py | sed -n '4390,4510p'`
- `nl -ba google_account_resolution.py | sed -n '1,330p'`
- `nl -ba inbox_client.py | sed -n '1,520p'`
- `nl -ba inbox.py | sed -n '1138,1218p'`
- `nl -ba inbox.py | sed -n '4030,4288p'`
- `nl -ba mcp_backend.py | sed -n '1,220p'`
- `nl -ba mcp_server.py | sed -n '1,190p'`
- `nl -ba tools_registry.py | sed -n '1,120p'`
- `nl -ba mcp_gateway.py | sed -n '1,115p'`
- `nl -ba message_index_store.py | sed -n '1,520p'`
- `nl -ba message_sync.py | sed -n '1,120p'`
- `nl -ba message_sync.py | sed -n '181,240p'`
- `nl -ba message_sync.py | sed -n '498,668p'`
- `nl -ba thread_classifier.py | sed -n '1,180p'`
- `nl -ba gmail_triage.py | sed -n '1,130p'`
- `nl -ba gmail_triage.py | sed -n '203,330p'`
- `nl -ba scheduler.py | sed -n '1,300p'`
- `nl -ba memory_store.py | sed -n '1,140p'`
- `nl -ba ambient_notes.py | sed -n '1,120p'`
- `nl -ba tests/test_server.py | sed -n '1,160p'`
- `nl -ba tests/test_api_contract.py | sed -n '1,180p'`
- `nl -ba tests/test_mcp_gateway.py | sed -n '1,130p'`

## Architecture map

### Outer entrypoints

- `inbox.py:4277-4279` is the TUI entrypoint. It instantiates `InboxApp` and runs Textual.
- `inbox_server.py:1288-1310` builds the FastAPI app through `create_app()` and binds module-level `app`.
- `mcp_server.py:148-155` starts an HTTP MCP gateway on `127.0.0.1:8000`.
- `inbox_mcp_readonly.py:83-91` starts a read-only HTTP MCP gateway, defaulting to port 8001.
- `inbox_mcp_stdio.py:13-21` and `inbox_mcp_readonly_stdio.py:7-15` wrap those MCP surfaces for stdio clients.
- `message_sync.py:638-659` provides a CLI for `bootstrap`, `incremental`, `rebuild`, and `summary` index operations.
- `main.py:1-6` is a placeholder that prints "Hello from inbox!" and is not aligned with the documented entrypoints.
- `dev.sh:1-11` is the worktree launcher and defaults dev copies to port 9850.
- `scripts/run_inbox_backend.sh:1-9` and `scripts/run_inbox_mcp_http.sh:1-9` launch backend and MCP with `UV_CACHE_DIR` defaulted to `/tmp/uv-cache`.

There is no `[project.scripts]` section in `pyproject.toml`; `rg -n "\\[project\\.scripts\\]|scripts|entry-points|console_scripts" pyproject.toml` returned no matches. Operational entrypoints are therefore file/script based, not installed console commands.

### UI and client boundary

`inbox.py` is intended to be a thin client, but it carries substantial local behavior:

- `inbox.py:1147-1218` defines `InboxApp`, CSS, key bindings, polling constants, and UI state.
- `inbox.py:4030-4067` directly imports `save_favorites` from `services.py`, so the UI is not purely HTTP-backed.
- `inbox.py:4070-4163` owns assistant modal flow and calls `from agents.runner import Supervisor` at `inbox.py:4131`.
- `rg --files | rg '^agents/'` returned no tracked `agents/` package, while `rg -n "from agents|import agents|agents/" .` found only memory-context references in `AGENTS.md` and the runtime import in `inbox.py:4131`. That makes the assistant-control-plane path ambiguous in this checkout.
- `inbox_client.py:21-77` wraps `httpx.Client`, injects `INBOX_SERVER_TOKEN` when present, can auto-start `inbox_server.py`, and writes `server.log`.
- `inbox_client.py:81-520` exposes a broad sync API mirroring many server endpoints.

The practical boundary is "mostly HTTP client", not "strict HTTP client". A future worker should not assume UI changes are isolated from backend modules.

### FastAPI backend boundary

`inbox_server.py` is the orchestration layer and API surface:

- It imports models, services, and helpers directly from many modules, with the broadest import fan-in from `services.py` at `inbox_server.py:61-141`.
- `ServerState` centralizes live service handles, caches, background services, scheduler, index store, and adapters at `inbox_server.py:802-818`.
- Module-level global state is created at `inbox_server.py:821-822`.
- `InboxServerRuntime` at `inbox_server.py:825-834` is an important test seam. Tests can inject fake state, fake auth, disabled scheduler, and disabled ambient autostart.
- `make_lifespan()` performs startup work: contact load, Google auth, optional conversation prewarm, optional ambient autostart, and scheduler launch at `inbox_server.py:1198-1272`.
- Auth is optional: `_is_authorized()` returns true when `INBOX_SERVER_TOKEN` is empty at `inbox_server.py:1317-1320`.

This layer successfully gives tests a controlled runtime seam, but it still owns enough runtime state and route logic that it is a second hub rather than only a thin transport wrapper.

### Source adapters and data layer

`services.py` is the current all-source integration layer:

- `services.py:54-99` defines credential paths, local macOS DB paths, token paths, and broad Google OAuth scopes.
- `services.py:109-120` provides contact initialization and the `INBOX_TEST_MODE` live-write guard hook.
- `services.py:330-416` loads all Google accounts and builds Gmail, Calendar, Drive, Sheets, Docs, and Tasks services.
- The file also contains iMessage, Gmail, Calendar, Notes, WhatsApp, Reminders, Tasks, Gemini, Maps, GitHub, Drive, Sheets, Docs, audio, LLM, search, notifications, favorites, contacts, and calendar availability logic.

`service_models.py` is a cleaner boundary:

- `service_models.py:11-153` defines dataclass models for Contact, Msg, CalendarEvent, Note, Reminder, GoogleTask, GitHubNotification, DriveFile, Spreadsheet, Document, and ThreadSummary.

`google_account_resolution.py` is a partial policy extraction:

- `google_account_resolution.py:24-33` centralizes default Google account selection using `INBOX_DEFAULT_GOOGLE_ACCOUNT` when available.
- `google_account_resolution.py:85-107` resolves Gmail message/thread ownership by explicit account, cache, provider probe, then default account.
- `google_account_resolution.py:160-304` implements preflight payloads for doc, sheet, Drive folder, task, and calendar writes.

The data-layer direction is good, but extraction is incomplete. Some server paths still bypass the helper:

- `inbox_server.py:1419-1424` falls back to `next(iter(state.gmail_services.values()))` for Gmail message reads.
- `inbox_server.py:1555-1558` lists labels by using `next(iter(state.gmail_services))` rather than `_get_gmail_service_for_account`.

### MCP and agent boundary

MCP is split into backend client, gateway auth/app, full server, read-only server, stdio wrappers, and a registry:

- `mcp_backend.py:18-56` routes MCP tool calls to the private HTTP server and forwards `INBOX_SERVER_TOKEN`.
- `mcp_gateway.py:32-45` checks `INBOX_MCP_TOKEN`, but permits requests when the token is unset.
- `mcp_gateway.py:87-94` mounts `/health` and `/mcp` with the public-auth middleware.
- `mcp_server.py:41-45` defines confirmation errors for hand-written write tools.
- `mcp_server.py:142-145` registers the shared registry and creates the app.
- `inbox_mcp_readonly.py:77-80` registers the same registry with `readonly_only=True`.
- `tools_registry.py:1-12` documents the important design decision: one table drives full and read-only MCP servers to reduce drift.
- `tools_registry.py:52-107` dynamically builds tool handlers, including `confirm=True` enforcement at `tools_registry.py:73-78`.

Command observation: `rg -c "Tool\\(" tools_registry.py` returned 60 tools, `rg -c "readonly=True" tools_registry.py` returned 29 read-only tools, and `rg -c "confirm=True" tools_registry.py` returned 34 confirmation-gated tools.

This is one of the healthier boundaries in the repo. The main risk is deployment/auth posture: docs describe the MCP server as public assistant-facing, but code makes token auth optional.

### Index, ranking, and workflow boundary

The newest architecture direction is the local index and workflow read model:

- `message_index_store.py:12-14` defaults to `.inbox_index.sqlite3`.
- `message_index_store.py:80-170` initializes `sync_state`, `items`, `threads`, and `sender_stats`.
- `message_index_store.py:407-520` rebuilds thread rows from indexed items and classifies them.
- `message_sync.py:181-240` bootstraps Gmail by calling `google_auth_all()` and paginating Gmail messages.
- `message_sync.py:498-582` bootstraps and incrementally syncs local iMessage by rowid.
- `message_sync.py:602-627` combines Gmail and iMessage sync, then rebuilds changed thread scopes.
- `thread_classifier.py:18-47` scores/classifies indexed threads with deterministic heuristics.
- `gmail_triage.py:17-31` defines normalized `GmailThreadSummaryOut`.
- `gmail_triage.py:203-225` ranks threads using recency, reply need, action items, workflow, and message count.
- `inbox_server.py:3805-3853` exposes index threads, status, health, views, and sync endpoints.

This boundary is promising because it moves the model-facing read path away from raw provider payloads. It is still limited to Gmail and iMessage, while `inbox/needs-action` only combines indexed threads with Tasks and Calendar at `inbox_server.py:3739-3802`.

### Persistence and background work

Local stores and background behavior are spread across several modules:

- `scheduler.py:15-17` stores scheduler state in `.inbox_scheduler.sqlite3`.
- `scheduler.py:59-114` creates scheduled message, follow-up, and task-message-link tables.
- `memory_store.py:9-10` stores local MCP memory in `.inbox_memory.sqlite3`.
- `memory_store.py:46-70` creates the memory table and lookup index.
- `ambient_notes.py:14-17` writes daily and ambient notes under `~/vault`.
- `ambient_notes.py:28-38` appends to today's daily note.

These modules are clearer than `services.py`, but they write local user state outside the repo or to ignored local SQLite files. That is correct for the product, but future validation must stay in test mode or use temp paths.

### Config, secrets, and generated state

The repo has a reasonable ignore posture:

- `.gitignore:12-25` ignores credentials, Google tokens, GitHub/Maps/Gemini key files, env files, and key/secret patterns.
- `.gitignore:34-35` ignores logs.
- `.gitignore:40-43` ignores `.claude/`, `.inbox_memory.sqlite3`, and `.inbox_scheduler.sqlite3`.
- `.gitignore:45-49` keeps batch inputs but ignores generated batch outputs/logs/state.
- `.gitignore:58` ignores `.inbox_index.sqlite3`.
- `rg --files -uu` for likely secret/state paths only returned `.gitignore`, so no obvious credential or local DB file was visible in this worktree.

## Working boundaries

1. Test runtime injection exists and is useful. `InboxServerRuntime` lets tests bypass real contacts, Google auth, scheduler, and ambient startup. Tests use it in `tests/test_server.py:29-56` and `tests/test_api_contract.py:46-72`.

2. MCP registry is centralized. `tools_registry.py` drives both full and read-only MCP surfaces, and `tests/test_api_contract.py:75-88` verifies every registered tool path maps to a FastAPI route.

3. Account policy is no longer prompt-only. `google_account_resolution.py` has real helpers for default account, message ownership, per-service account lookup, and preflight payloads.

4. The index read model is its own subsystem. `message_index_store.py`, `message_sync.py`, `thread_classifier.py`, and `gmail_triage.py` form a separable path for compact, classified inbox reads.

5. Agent-safe testing is documented. `docs/TESTING_FOR_AGENTS.md:8-18` gives safe commands, and `inbox_test_mode.py:18-31` implements test-mode detection and temp test data root.

## Risks and stale assumptions

### Risk 1: `services.py` is a high-blast-radius integration hub

Evidence:

- `services.py:1-4` explicitly puts data fetching, auth, mutation, audio, and LLM logic in one file.
- `wc -l *.py tests/*.py` reported `services.py` at 6,467 lines.
- `inbox_server.py:61-141` imports a very large set of functions/classes directly from `services.py`.

Why it matters:

Small changes to one provider can import or initialize unrelated provider dependencies. This increases test setup cost, makes ownership unclear, and encourages bypassing emerging boundaries like `google_account_resolution.py` or the index read model.

Next safe direction:

Extract one source at a time behind existing function names or adapter protocols, starting with Drive/Docs/Sheets because they share Google account policy and have clear endpoint clusters.

### Risk 2: Write safety is inconsistently enforced at the service layer

Evidence:

- `services.py:114-120` defines `_assert_live_write_allowed`.
- Many write functions call it, as shown by `rg -n "_assert_live_write_allowed" services.py`.
- But mutating functions are present without visible guard calls in their function bodies: `drive_upload` at `services.py:3864`, `sheets_rename_sheet` at `services.py:4315`, `sheets_format` at `services.py:4341`, `sheets_copy_to` at `services.py:4358`, and `docs_insert_text` at `services.py:4476`.
- These are exposed through server endpoints including `upload_to_drive` at `inbox_server.py:2549`, `rename_sheet_tab` at `inbox_server.py:2733`, `copy_sheet_tab` at `inbox_server.py:2741`, `format_spreadsheet` at `inbox_server.py:2755`, and `insert_doc_text` at `inbox_server.py:2979`.

Why it matters:

`INBOX_TEST_MODE=1` is the repo's safety contract for deterministic agent runs. If some write paths bypass the service-layer guard, future tests or tools may mutate live Google/Drive/Docs/Sheets state unexpectedly.

Next safe direction:

Add service-level guards to every mutating provider function and add focused tests that assert `LiveWriteBlocked` for each exposed write cluster.

### Risk 3: Auth defaults are open unless environment variables are set

Evidence:

- `inbox_server.py:1317-1320` authorizes all private server requests when `INBOX_SERVER_TOKEN` is unset.
- `mcp_gateway.py:36-45` authorizes public MCP requests when `INBOX_MCP_TOKEN` is unset.
- `MCP_V1_PLAN.md:14-21` describes a security model where the public MCP auth uses `INBOX_MCP_TOKEN`.
- `mcp_server.py:148-151` binds to `127.0.0.1`, but `MCP_V1_PLAN.md:39-50` documents exposing the gateway through ngrok.

Why it matters:

The default is convenient for local development but dangerous if a launch script or tunnel exposes MCP without `INBOX_MCP_TOKEN`. The docs state the security model, but the runtime does not fail closed.

Next safe direction:

Add a startup health warning or strict mode for public MCP when `INBOX_MCP_TOKEN` is missing, and make deploy scripts opt into dev-open behavior explicitly.

### Risk 4: Account-routing extraction is incomplete

Evidence:

- `google_account_resolution.py:24-33` centralizes default account selection.
- `google_account_resolution.py:85-107` handles Gmail ownership resolution.
- `inbox_server.py:1419-1424` still uses a direct fallback to the first Gmail service for message reads.
- `inbox_server.py:1555-1558` still uses direct first-account selection for label reads.
- `CONNECTOR_ROADMAP.md:30-40` says Google writes should default to `jshah1331@gmail.com` through `INBOX_DEFAULT_GOOGLE_ACCOUNT`, and object ownership should be explicit.

Why it matters:

The repo has already had account-routing issues historically, and partial extraction makes future regressions likely. Any route that bypasses the helper can disagree with preflight, MCP, or workflow tools.

Next safe direction:

Create an account-routing audit test that enumerates all Google endpoints and fails on direct `next(iter(state.*_services))` fallback outside the policy helper.

### Risk 5: Startup has side effects that complicate validation

Evidence:

- `inbox_server.py:1213-1230` loads contacts and authenticates every Google service during lifespan startup.
- `inbox_server.py:1249-1267` may autostart ambient listening depending on voice config and availability.
- `inbox_server.py:1269-1272` starts the scheduler loop unless runtime disables it.
- `tests/test_server.py:29-56` shows tests need explicit fake runtime setup to avoid these side effects.

Why it matters:

Running `uv run python inbox_server.py` in a worktree is not a neutral validation command. It can touch local contacts, OAuth tokens, audio, and scheduler state. Architecture workers should use tests with injected runtime or `INBOX_TEST_MODE=1`, not live server boot.

Next safe direction:

Document and enforce a "no live startup in agent validation" rule near server entrypoints, or add a `--test-runtime`/`INBOX_SAFE_SERVER=1` mode for local server smoke checks.

### Risk 6: Documentation has stale or unsupported operational claims

Evidence:

- `pyproject.toml:5` requires Python `>=3.12,<3.15`, while `README.md:32` says Python 3.10+.
- `DOCS_INDEX.md:44` and `DOCS_INDEX.md:140` claim 736 tests pass and production readiness, but this audit did not run the full suite and current tests are not counted there.
- `DOCS_INDEX.md:137` says "TUI tab for Sheets - coming later", while the TUI key bindings and client/server surface have moved beyond the original Sheets-only documentation.
- `README.md:25` says local-first ML has no cloud dependencies, while `CLAUDE.md:294` and `services.py` include optional Gemini API behavior.

Why it matters:

Future agents will use docs as a task contract. Stale runtime/version/test claims can send workers to the wrong validation lane or make them trust unverified behavior.

Next safe direction:

Split "current verified state" from roadmap claims and update version/test claims with command outputs.

### Risk 7: Assistant control plane appears referenced but not tracked

Evidence:

- `inbox.py:4131` imports `Supervisor` from `agents.runner`.
- `rg --files | rg '^agents/'` returned no tracked `agents/` package.
- `AGENTS.md` memory context references prior `agents/` scaffolding work, but the files are not present in this worktree.

Why it matters:

The TUI assistant modal may be dead code in a clean checkout, or it may rely on ignored/local-only files. Either case is an ownership risk because future workers cannot reason about or test that path from tracked repo state alone.

Next safe direction:

Either restore the tracked `agents/` package, move the assistant bridge behind an optional import boundary with tests, or remove/docs-gate the feature until the dependency is available.

## Independently grabbable next tasks

### Task 1: Complete service-level live-write guard coverage

Acceptance criteria:

- Every mutating function in `services.py` starts by calling `_assert_live_write_allowed(...)`.
- At minimum, add guards for `drive_upload`, `sheets_rename_sheet`, `sheets_format`, `sheets_copy_to`, and `docs_insert_text`.
- Add tests that set `INBOX_TEST_MODE=1` and assert these functions raise `LiveWriteBlocked`.
- No live credentials, Google API calls, or local user data are touched by tests.

Validation candidates:

- `INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py tests/test_services.py -q` - expected pass after tests are updated.
- `uv run ruff check services.py tests/test_services.py` - expected pass.

### Task 2: Finish Google account-routing consolidation

Acceptance criteria:

- Replace direct first-account fallbacks in `inbox_server.py` with helpers from `google_account_resolution.py`.
- Add coverage for Gmail message reads, labels, compose/reply, Docs, Sheets, Drive, Calendar, and Tasks account selection.
- Add a regression test that fails if `next(iter(state.*_services))` appears in server endpoint code outside the policy helper.
- Returned Google objects preserve or expose account/ownership consistently.

Validation candidates:

- `INBOX_TEST_MODE=1 uv run pytest tests/test_gmail_actions.py tests/test_server.py tests/test_api_contract.py -q` - expected pass after route tests are updated.
- `uv run ruff check inbox_server.py google_account_resolution.py tests/test_gmail_actions.py tests/test_server.py tests/test_api_contract.py` - expected pass.

### Task 3: Make the MCP public-auth posture fail-safe

Acceptance criteria:

- Public MCP startup or health clearly distinguishes dev-open mode from token-protected mode.
- Exposing the MCP gateway without `INBOX_MCP_TOKEN` requires an explicit env var such as `INBOX_MCP_ALLOW_NO_AUTH=1`.
- Read-only and full MCP servers share the same auth behavior.
- Docs and launch scripts are updated to mention the token requirement before ngrok/public exposure.

Validation candidates:

- `INBOX_TEST_MODE=1 uv run pytest tests/test_mcp_gateway.py -q` - expected pass with new auth cases.
- `uv run ruff check mcp_gateway.py mcp_server.py inbox_mcp_readonly.py tests/test_mcp_gateway.py` - expected pass.

### Task 4: Decide the tracked assistant-control-plane boundary

Acceptance criteria:

- The `agents.runner` import in `inbox.py` is either backed by tracked code, moved behind an optional integration adapter, or removed from active UI paths.
- TUI behavior when the dependency is absent is tested and documented.
- No local-only `.claude/` or ignored package is required to import and run the TUI.

Validation candidates:

- `INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_app.py -q` - expected pass after optional dependency behavior is covered.
- `uv run pyright` - expected pass or known existing type blockers documented.

### Task 5: Create a module ownership map before splitting `services.py`

Acceptance criteria:

- Add a docs-only ownership map that groups `services.py` functions by provider and side-effect class.
- Identify extraction order, adapter protocol shape, and tests for the first provider slice.
- Do not move code in this planning task.

Validation candidates:

- `git status --short` - expected docs-only change.
- `INBOX_TEST_MODE=1 uv run pytest -m safe` - expected pass, but note current `safe` marker coverage is narrow.

## Validation command candidates

Required queue validation:

- `git status --short` - expected to exit 0. Actual run after writing this report exited 0 and returned `?? docs/overnight/`, which is the untracked report directory containing this file.

Safe architecture-proof commands for future code changes:

- `INBOX_TEST_MODE=1 uv run pytest -m safe` - expected pass for currently marked safe tests. Important caveat: `rg -n "pytestmark = pytest.mark.safe|@pytest.mark.safe" tests` found only `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py` marked safe, so this is a cheap smoke proof, not broad coverage.
- `INBOX_TEST_MODE=1 uv run pytest tests/test_api_contract.py tests/test_tools_registry.py tests/test_mcp_gateway.py -q` - expected pass after MCP/API-route changes.
- `INBOX_TEST_MODE=1 uv run pytest tests/test_server.py tests/test_gmail_actions.py -q` - expected pass after server/account-routing changes.
- `INBOX_TEST_MODE=1 uv run pytest tests/test_message_index_store.py tests/test_message_sync.py -q` - expected pass after index/read-model changes.
- `uv run ruff check .` - expected pass for code style, but it was not required or run for this docs-only audit.
- `uv run pyright` - expected candidate for type-sensitive refactors, but existing type state was not verified in this audit.

Commands to avoid as routine agent validation:

- `uv run python inbox_server.py` - not a neutral smoke test because server lifespan loads contacts, authenticates Google accounts, may autostart ambient listening, and may start scheduler background work.
- Live provider tests or routes without `INBOX_TEST_MODE=1` - not safe for overnight read-only audit work.

## Non-goals

- No product-code edits.
- No refactors.
- No live server startup.
- No OAuth, token, credential, or local personal-data reads.
- No Google, GitHub, MCP, ngrok, or other external-service calls.
- No generated data cleanup.
- No PR creation, pushes, merges, or external tracker updates.

## Unknowns

- I did not run full pytest, ruff, pyright, or bandit. This audit only identifies candidate commands and architecture risks.
- I did not verify live server health, Google account availability, local macOS data stores, Obsidian vault contents, audio stack, or MCP client connectivity.
- I could not determine whether the missing `agents/` package is intentionally ignored/local-only, accidentally omitted, or obsolete.
- I did not inspect sibling repos from `repos.json` because this repo is large enough for a full standalone architecture audit and the queue item is scoped to this repo only.
- I did not verify the exact current test count behind the docs' "736 tests pass" claim.

## Decision notes

- Treat `inbox_server.py` as the current API orchestration boundary, not as a thin wrapper.
- Treat `services.py` as a legacy integration hub that needs staged extraction, not a stable long-term source-adapter layer.
- Treat `google_account_resolution.py`, `tools_registry.py`, and the message index modules as the most promising existing seams for safer future work.
- Treat live server startup as out of scope for agents unless a task explicitly opts into local personal-data integration testing.
