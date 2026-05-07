# inbox-sym-118 architecture-map audit

Date: 2026-05-07

Queue item: `inbox-sym-118-architecture-map`

Scope: read-only architecture audit for the local `inbox-sym-118` worktree. The only intended repository change is this report.

## Summary

Inbox is a local-first personal communication control plane with three major runtime surfaces:

- a Textual TUI in `inbox.py`,
- a local FastAPI backend in `inbox_server.py`,
- an MCP/agent surface built from `mcp_backend.py`, `mcp_server.py`, `inbox_mcp_readonly.py`, and `tools_registry.py`.

The product direction is clear: raw providers feed a local operational index, the server owns auth/routing/policy, and UI/agent clients consume compact views. The codebase is partway through that transition. The strongest newer boundaries are `service_models.py`, `google_account_resolution.py`, `message_index_store.py`, `message_sync.py`, and `tools_registry.py`. The highest architectural risk is that `services.py` and `inbox_server.py` still hold too much cross-domain behavior, so small connector changes can touch data access, routing policy, API models, background jobs, and UI refresh assumptions at once.

## Repo State

- Branch observed with `git status --short --branch`: `codex/goal-inbox-sym-118-architecture-map`.
- Initial dirty state observed with `git status --short`: clean, no output.
- Starting HEAD from `git rev-parse HEAD`: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`.
- Recent history from `git log --oneline -5` shows the branch starts at merge `2805b84 Merge pull request #34 from jwalin-shah/codex/SYM-9-indexed-defaults`, which matches recent indexed-defaults architecture work.
- `llm-tldr tree .` shows a flat Python application with top-level runtime modules, `tests/`, `config/`, `deploy/`, `scripts/`, `modes/`, and only one pre-existing file under `docs/`.
- `fd . docs -t f` initially returned only `docs/TESTING_FOR_AGENTS.md`; `docs/overnight/` did not exist before this report.
- `rg --files -g '*.py' | xargs wc -l` reported 36,403 Python lines. Largest modules: `services.py` 6,467 lines, `inbox.py` 4,279 lines, `inbox_server.py` 3,940 lines, `tests/test_inbox_app.py` 3,636 lines, `tests/test_server.py` 2,289 lines.
- `rg -c '^@app\\.' inbox_server.py` reported 160 FastAPI route decorators.
- `rg -c 'Tool\\(' tools_registry.py` reported 60 MCP registry entries.
- `rg -c '^    def |^    async def ' inbox_client.py mcp_backend.py` reported 103 synchronous client methods in `inbox_client.py` and 46 async backend methods in `mcp_backend.py`.

## Purpose And Product Shape

The README positions Inbox as a privacy-first TUI that consolidates iMessage, Gmail, Calendar, Sheets, Notes, Reminders, GitHub, and Drive (`README.md:1-15`). It also says the architecture is client-server, with FastAPI owning data access while the TUI and agents are thin HTTP clients (`README.md:23-27`).

The product plan is narrower and more architectural than the README feature list. `PLAN.md` defines the current phase around Gmail, iMessage/SMS, calendar context, FastAPI, a local SQLite operational index, and Textual TUI, while explicitly deferring a general memory platform and other ingestions. It describes four layers: raw sources, operational index, inbox views, and interfaces (`PLAN.md:1-78`). This plan better matches the recent code than the README architecture block.

The connector roadmap describes the intended long-term boundary: source adapters, normalization, policy, and intent tools (`CONNECTOR_ROADMAP.md:15-31`). It also calls out that account routing and write defaults should be code policy, not prompt convention (`CONNECTOR_ROADMAP.md:33-60`).

## Architecture Map

### Runtime Entrypoints

1. `inbox.py` is the TUI entrypoint. `InboxApp` constructs an `InboxClient`, starts or connects to the backend, refreshes data, and then polls (`inbox.py:1147-1224`, `inbox.py:2082-2114`). It is not just presentation code; it owns boot recovery, status behavior, notifications, indexed-view refreshes, and many user workflows (`inbox.py:2140-2360`).

2. `inbox_server.py` is the backend entrypoint. `make_lifespan()` initializes contacts, Google services, ambient audio, scheduler, and SQLite cleanup (`inbox_server.py:1198-1285`). `create_app()` creates the FastAPI app and copies existing routes into new runtime instances for tests (`inbox_server.py:1288-1310`). Authentication is optional unless `INBOX_SERVER_TOKEN` is set (`inbox_server.py:1313-1340`).

3. `inbox_client.py` is the synchronous HTTP client used by the TUI. It derives `SERVER_URL` from `INBOX_SERVER_URL` or `INBOX_SERVER_PORT` (`inbox_client.py:16-18`), injects the bearer token if present (`inbox_client.py:21-25`), and can spawn `inbox_server.py` as a subprocess with logs in `server.log` (`inbox_client.py:48-77`).

4. `mcp_backend.py` is the async HTTP client used by MCP tools. It defaults to `http://127.0.0.1:9849`, reads `INBOX_SERVER_URL` and `INBOX_SERVER_TOKEN`, and exposes `_request()` for registry-generated tools (`mcp_backend.py:9-56`).

5. `mcp_server.py` and `inbox_mcp_readonly.py` expose FastMCP servers. Both delegate most HTTP-backed tool generation to `tools_registry.register_all()` (`tools_registry.py:1-12`, `tools_registry.py:110-119`).

6. `message_sync.py` is the operational index sync entrypoint. Bootstrap sync reads Gmail and iMessage, records progress, and rebuilds changed thread rows (`message_sync.py:181-269`, `message_sync.py:602-626`).

### Module Ownership Boundaries

`services.py` owns provider access and local OS integration. It defines token paths, local data paths, Google scopes, SQLite helpers, OAuth, iMessage reads/writes, Gmail reads/writes, Calendar, Notes, WhatsApp Accessibility, Reminders, Tasks, Gemini, Maps, GitHub, Drive, Sheets, Docs, audio, LLM, global search, notifications, favorites, contacts, and AI helpers (`services.py:65-120`, `services.py:330-416`, `services.py:444-604`, `services.py:786-1464`, `services.py:1475-1820`, `services.py:1872-2024`, `services.py:2077-2580`, `services.py:2620-3239`, `services.py:3249-4519`, `services.py:4546-6425`). This is the primary monolith.

`service_models.py` is a cleaner shared model boundary. It defines stable dataclasses such as `Contact`, `Msg`, `CalendarEvent`, `DriveFile`, `Spreadsheet`, `Document`, and `ThreadSummary` (`service_models.py:1-153`). This file is a good extraction target and should stay pure.

`inbox_server.py` owns HTTP models, route orchestration, background server state, and conversion from service dataclasses to API response models. `ServerState` holds all Google service dictionaries, conversation cache, ambient service, dictation service, scheduler, index store, and source adapters (`inbox_server.py:802-817`). This centralizes state but also creates hidden coupling among routes.

`google_account_resolution.py` is the main account-routing policy boundary. It defines a protocol for multi-account state, honors `INBOX_DEFAULT_GOOGLE_ACCOUNT`, routes Gmail by cached conversation or message/thread lookup, and resolves services for Gmail, Sheets, Drive, Tasks, Docs, and Calendar (`google_account_resolution.py:14-33`, `google_account_resolution.py:36-157`). It also owns preflight payload construction for Google writes (`google_account_resolution.py:160-220`).

`message_index_store.py` owns the local operational read model. Its schema has `sync_state`, `items`, `threads`, and `sender_stats` tables (`message_index_store.py:69-170`). It rebuilds thread rows from normalized items and stores derived fields such as `human_score`, `noise_class`, `topic`, `urgency`, `actionability`, `needs_reply`, `summary`, and `open_loop` (`message_index_store.py:407-563`). It also owns query filtering for actionable/recent/waiting-style views (`message_index_store.py:565-612`).

`message_sync.py` owns source-to-index ingestion. Gmail bootstrap stores page progress and later switches to Gmail history cursor when available (`message_sync.py:181-269`). Top-level `bootstrap()` and `incremental()` sync Gmail and iMessage, then rebuild changed thread scopes (`message_sync.py:602-626`).

`thread_classifier.py` and `gmail_triage.py` own derived thread/workflow intelligence. `message_index_store.py` calls `classify_thread()` during rebuild (`message_index_store.py:448-500`), while `inbox_server.py` imports Gmail triage helpers for summaries, workflow display, thread briefs, and needs-action routing (`inbox_server.py:23-54`).

`scheduler.py` owns local durable workflow state for scheduled messages, follow-up reminders, and task-message links in `.inbox_scheduler.sqlite3` (`scheduler.py:1-16`, `scheduler.py:59-114`). `inbox_server.py` starts the scheduler loop at server lifespan time and exposes scheduler endpoints (`inbox_server.py:979-1192`, `inbox_server.py:2061-2183`).

`memory_store.py` owns local durable memory entries in `.inbox_memory.sqlite3`; `mcp_server.py`, `inbox_mcp_readonly.py`, and `/memory/extract` expose memory reads/writes. This is adjacent to the main inbox plan but not part of the narrow Phase 1 core.

`tools_registry.py` is the strongest agent-surface boundary. It defines `Tool` metadata, parameter placement, generated function signatures, readonly filtering, and confirm-gating (`tools_registry.py:26-119`). The registry keeps full and readonly MCP servers from drifting, but it is still a second API map separate from `inbox_client.py`.

### Data Flow

1. Local/macOS and cloud providers enter through `services.py`.
2. The FastAPI lifespan initializes provider services and stores them in global `state` (`inbox_server.py:1198-1229`).
3. Raw source endpoints either fetch live data through `services.py` or use `state.conv_cache` to recover conversation metadata (`inbox_server.py:1396-1450`).
4. Index sync writes normalized source items into `message_index_store.py` through `message_sync.py`.
5. Indexed read endpoints serve compact thread views through `/index/*` and `/inbox/needs-action` (`inbox_server.py:3739-3853`).
6. The TUI fetches both raw provider tabs and indexed views. `_collect_auxiliary_data()` fetches calendar, notes, reminders, GitHub, and indexed recent/actionable/waiting views on each refresh/poll (`inbox.py:2295-2360`).
7. MCP tools call `mcp_backend.InboxBackend._request()` directly, using registry metadata from `tools_registry.py`.

## Stale Assumptions And Risks

1. README runtime requirement is stale. `README.md:31-34` says Python 3.10+, but `pyproject.toml:1-5` requires `>=3.12,<3.15`.

2. The README architecture list is incomplete. It lists `services.py`, `inbox_server.py`, `inbox_client.py`, `inbox.py`, `contacts.py`, `ambient_notes.py`, and `ambient_daemon.py` (`README.md:132-142`), but omits current architecture-critical modules: `message_index_store.py`, `message_sync.py`, `thread_classifier.py`, `gmail_triage.py`, `google_account_resolution.py`, `scheduler.py`, `memory_store.py`, `mcp_backend.py`, and `tools_registry.py`.

3. "Thin HTTP clients" is only partly true. `inbox_client.py` and `mcp_backend.py` are transport clients, but `inbox.py` is a 4,279-line UI/control-plane module with server boot, error recovery, polling, notifications, indexed-view state, compose flows, Gmail actions, Drive actions, account auth actions, and AI actions (`inbox.py:2082-2360`, `inbox.py:2771-4277`).

4. `services.py` has too many ownership domains. Provider IO, OAuth, OS scripting, local DB reads, cloud writes, ML loading, Gemini, maps, search, notifications, and favorites all live in one 6,467-line module. Any extraction should avoid a rewrite and start from pure helpers or one provider at a time.

5. `inbox_server.py` has route sprawl and hidden global state coupling. It has 160 route decorators and a mutable global `state`. `create_app()` copies already-registered routes into a new app for tests (`inbox_server.py:1288-1310`), which is pragmatic but makes import order and app construction semantics important.

6. Several routes depend on `state.conv_cache` for correctness. `/messages/{source}/{conv_id}` picks the Gmail service from cached conversation metadata and falls back to the first/default Gmail service when missing (`inbox_server.py:1413-1427`). `/messages/send` refuses to send unless `/conversations` populated the cache first (`inbox_server.py:1434-1450`). That is an architectural coupling between read navigation and write routing.

7. Account ownership vocabulary is inconsistent. `Contact` has `gmail_account` (`service_models.py:11-25`), Google Drive/Sheets/Docs dataclasses have `account` (`service_models.py:102-139`), and `ThreadSummary` has `owning_account` (`service_models.py:142-153`). `CONNECTOR_ROADMAP.md` wants `owning_account` everywhere. Future agents should normalize with compatibility shims rather than renaming fields in one sweep.

8. REST writes rely on server auth and test-mode guards, while MCP writes add confirm gates. `tools_registry.py` confirm-gates mutating MCP tools (`tools_registry.py:52-78`), and `services.py` has `_assert_live_write_allowed()` for test mode (`services.py:114-120`), but REST endpoints such as `/messages/send`, `/calendar/events`, `/drive/upload`, `/sheets`, and `/docs` execute writes once authorized. This is acceptable for a local app but risky if deployment files expose it beyond localhost.

9. Optional token auth means "safe by default" depends on deployment context. If `INBOX_SERVER_TOKEN` is unset, `_is_authorized()` returns true (`inbox_server.py:1317-1329`). The server binds to `127.0.0.1` in `__main__`, but deploy examples and Caddy/system service files should be reviewed before any remote exposure.

10. Validation claims are likely stale. `DOCS_INDEX.md` claims "Tests (736 pass)" and "All 736 tests pass", but the current test suite has many more test/class definitions by `rg -c 'def test_|class Test' tests/*.py`, and I did not run the full suite during this read-only queue item.

11. Cross-silo query support introduces an undeclared optional dependency. `/query` imports `gemma4_hackathon` dynamically and returns 503 if not installed (`inbox_server.py:3896-3932`), but this is not present in `pyproject.toml`. This endpoint is an architecture exception and should stay explicitly optional.

12. Local generated state is intentionally gitignored, but it is architecturally important. `.gitignore:12-20` ignores credentials and tokens; `.gitignore:34-43` ignores logs, `.claude/`, `.inbox_memory.sqlite3`, and `.inbox_scheduler.sqlite3`; `.gitignore:56-58` ignores `.inbox_index.sqlite3`. Agents must not assume a fresh worktree has accounts, index state, scheduler state, or memory state.

## Decisions For Future Work

- Treat `PLAN.md` and `CONNECTOR_ROADMAP.md` as the current architecture direction. Treat `README.md` as user-facing overview that needs refresh.
- Do not start by "cleaning up" `services.py` globally. Extract one source adapter or one pure policy boundary at a time, with route-contract tests.
- Keep `service_models.py`, `google_account_resolution.py`, `message_index_store.py`, and `tools_registry.py` small and explicit. These are the current leverage points for making the repo more navigable.
- Preserve old response fields while adding normalized fields. The product has both human TUI and agent/MCP clients, so field renames need compatibility periods.
- Prefer indexed views for "what needs attention"; use raw provider reads only for drill-down and explicit refresh.

## Validation Map

Required validation for this queue item:

- `git status --short`
- Actual result after writing this report: command exited 0 and printed `?? docs/overnight/`.
- Local docs-only commit was attempted after validation, but `git add docs/overnight/inbox-sym-118-architecture-map.md` failed because the sandbox could not create the linked worktree Git index lock under `/Users/jwalinshah/projects/inbox/.git/worktrees/inbox-sym-118-architecture-map/index.lock`.
- Expected status if a human or runner stages/commits from an unrestricted shell: pass with no output.

Agent-safe validation candidates from local docs:

- `INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py -q`
  - Expected: pass.
  - Evidence: documented as the smallest focused safe test in `docs/TESTING_FOR_AGENTS.md:15-19`.
  - Not run during this audit because the queue validation command is `git status --short`.

- `INBOX_TEST_MODE=1 uv run pytest -m safe`
  - Expected: pass if current branch health matches docs.
  - Evidence: default safe loop in `docs/TESTING_FOR_AGENTS.md:5-13`; safe marker registered in `pyproject.toml:53-62`.
  - Not run during this audit.

- `uv run ruff check .`
  - Expected: pass on a healthy branch.
  - Evidence: documented in `docs/TESTING_FOR_AGENTS.md:9-13`; ruff config in `pyproject.toml:40-46`.
  - Not run during this audit.

- `uv run pyright`
  - Expected: pass on a healthy branch, but sensitive to local environment and installed dependencies.
  - Evidence: documented in `docs/TESTING_FOR_AGENTS.md:9-13`; pyright config in `pyproject.toml:48-51`.
  - Not run during this audit.

Architecture-change validation candidates:

- For route extraction: `INBOX_TEST_MODE=1 uv run pytest tests/test_api_contract.py tests/test_server.py::TestHealth -q`
  - Expected: pass if route path/method contracts and app construction are preserved.

- For MCP registry changes: `INBOX_TEST_MODE=1 uv run pytest tests/test_tools_registry.py tests/test_mcp_gateway.py -q`
  - Expected: pass if registry signatures, readonly filtering, confirm gates, and gateway auth still match.

- For account-routing changes: `INBOX_TEST_MODE=1 uv run pytest tests/test_gmail_actions.py tests/test_api_contract.py -q`
  - Expected: pass if Gmail reply ownership and API contracts are preserved.

- For index changes: `INBOX_TEST_MODE=1 uv run pytest tests/test_message_index_store.py tests/test_message_sync.py tests/test_thread_classifier.py -q`
  - Expected: pass if schema, sync checkpoints, thread rebuild, and classification behavior stay compatible.

## Next Safe Work

### Task 1: Refresh Architecture Docs To Match Current Runtime

Acceptance criteria:

- Update `README.md` architecture block to include the operational index, account routing, scheduler, MCP registry, and current Python requirement.
- Add a short "Current Architecture" section that distinguishes raw sources, operational index, API, TUI, and MCP.
- Do not claim full test counts unless generated during the change.

Suggested validation:

- `git diff -- README.md DOCS_INDEX.md`
- `uv run ruff check .` if only Markdown links are unchanged, this may be optional.

Files likely owned:

- `README.md`
- `DOCS_INDEX.md`

### Task 2: Route Surface Inventory And Router Extraction Plan

Acceptance criteria:

- Produce a route inventory grouped by source area: health/auth, conversations, Gmail, calendar, reminders/tasks, scheduler, Drive/Sheets/Docs, index, AI/audio, contacts, MCP-adjacent.
- Identify one first router extraction that preserves all path/method pairs.
- If code is changed, route-contract tests must prove `create_app()` exposes the same paths before and after extraction.

Suggested validation:

- `INBOX_TEST_MODE=1 uv run pytest tests/test_api_contract.py tests/test_server.py::TestHealth -q`
- `python - <<'PY'` route inventory script, if a future worker adds one as a checked-in helper or one-off local command.

Files likely owned:

- `inbox_server.py`
- possibly a new `api/` package if implementation follows the plan
- `tests/test_api_contract.py`

### Task 3: Cache-Free Gmail Routing Work Pack

Acceptance criteria:

- Document or implement a path where Gmail message fetch/reply routing does not require a previous `/conversations` call.
- Preserve current cached fast path but use `google_account_resolution.get_gmail_service_for_message()` for cache misses.
- Add tests for message/thread lookup across two fake Gmail accounts.

Suggested validation:

- `INBOX_TEST_MODE=1 uv run pytest tests/test_gmail_actions.py tests/test_server.py::TestMessages -q`

Files likely owned:

- `inbox_server.py`
- `google_account_resolution.py`
- `tests/test_gmail_actions.py`
- `tests/test_server.py`

### Task 4: Normalize Account Ownership Fields With Compatibility

Acceptance criteria:

- Define a repository-wide rule for `account` vs `gmail_account` vs `owning_account`.
- Add `owning_account` to Google response models where missing while retaining existing fields for compatibility.
- Update tests to assert both old and normalized fields during the transition.

Suggested validation:

- `INBOX_TEST_MODE=1 uv run pytest tests/test_api_contract.py tests/test_drive.py tests/test_gmail_actions.py -q`

Files likely owned:

- `service_models.py`
- `inbox_server.py`
- `gmail_triage.py`
- focused tests around API output shapes

### Task 5: Provider Boundary Extraction For One Low-Risk Source

Acceptance criteria:

- Choose one small provider boundary, likely GitHub or Drive metadata, and move only cohesive functions out of `services.py`.
- Keep public function names re-exported or update imports in one narrow pass.
- Prove no endpoint behavior changes with focused tests.

Suggested validation:

- For GitHub: `INBOX_TEST_MODE=1 uv run pytest tests/test_github.py tests/test_server.py::TestGitHub -q`
- For Drive: `INBOX_TEST_MODE=1 uv run pytest tests/test_drive.py tests/test_server_endpoints.py::TestDriveEndpoints -q`

Files likely owned:

- `services.py`
- new provider module if introduced
- matching focused tests

## Non-Goals

- No product code edits in this queue item.
- No credential, token, local data, deploy, external service, or generated data mutation.
- No live Gmail, Calendar, Drive, Docs, Sheets, Tasks, Reminders, iMessage, WhatsApp, GitHub, Gemini, Maps, microphone, or notification calls.
- No Linear/GitHub tracker updates.
- No PR creation or push.
- No attempt to run broad live integration tests.

## Unknowns

- Which Google account is actually intended for default writes in this worktree depends on local `INBOX_DEFAULT_GOOGLE_ACCOUNT` and available token files; neither was inspected beyond code/docs.
- Whether the primary daily-driver server on port 9849 is running was not tested, because this audit did not need live personal data access.
- Current full-suite health is unknown; only command candidates were mapped.
- The `.factory/` validation history appears to contain useful historical review evidence, but this audit did not verify whether those generated validation artifacts are authoritative for the current branch.
- Whether external `gemma4_hackathon` is installed locally is unknown and not needed for this queue item.
