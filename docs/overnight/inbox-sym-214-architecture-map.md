# inbox-sym-214 architecture-map audit

Queue item: `inbox-sym-214-architecture-map`
Repo/worktree: `/Users/jwalinshah/projects/agent-stack/.agent-stack-worktrees/2026-05-07-overnight-marathon/inbox-sym-214-architecture-map`
Branch observed: `codex/goal-inbox-sym-214-architecture-map`
Initial dirty state: `git status --short --branch` returned only `## codex/goal-inbox-sym-214-architecture-map`, so the worktree was clean before this report.

This was a read-only architecture audit except for this report. I did not touch product code, generated data, credentials, deploys, external services, trackers, or PRs.

## Purpose

Inbox is a local-first personal inbox/control-plane app. The documented core is a Python Textual TUI plus a local FastAPI backend that reads and writes across iMessage, Gmail, Google Calendar, Notes, Reminders, Drive, Sheets, Docs, GitHub, audio/LLM, and MCP surfaces.

The current product direction is narrower than the current code surface. `PLAN.md` says this phase should focus on Gmail, iMessage/SMS, calendar context, a local FastAPI server, a local SQLite operational index, and the Textual TUI. The implementation has already widened into a general personal assistant platform: `services.py`, `inbox_server.py`, `inbox_client.py`, `tools_registry.py`, and the deploy configs expose many more source and workflow modules.

## Commands And Observations

- `pwd`: confirmed the worker is in the queue worktree path above.
- `git status --short --branch`: clean branch before report creation.
- `git log --oneline -5`: HEAD was `2805b84 Merge pull request #34 from jwalin-shah/codex/SYM-9-indexed-defaults`; recent merges include indexed-defaults, thread rebuild cleanup, and sync freshness health.
- `llm-tldr tree .`: repo is a flat Python app with `batch/`, `config/`, `deploy/`, `docs/`, `modes/`, `scripts/`, `tests/`, and many top-level modules.
- `rg --files`: found 30 test files and top-level modules including `services.py`, `inbox_server.py`, `inbox.py`, `inbox_client.py`, `message_index_store.py`, `message_sync.py`, `tools_registry.py`, `mcp_backend.py`, and MCP entrypoints.
- `wc -l *.py`: 21,703 Python LOC across top-level modules; largest are `services.py` 6,467 LOC, `inbox.py` 4,279 LOC, `inbox_server.py` 3,940 LOC, `inbox_client.py` 947 LOC.
- `rg -c "^@app\\." inbox_server.py`: 160 FastAPI app decorators, including middleware and HTTP routes.
- `rg -c "^    Tool\\(" tools_registry.py`: 60 MCP registry tools; `rg -c "confirm=True"` found 34 confirm-gated tools and `rg -c "readonly=True"` found 29 readonly tools.
- `rg -c "_assert_live_write_allowed\\(" services.py`: 44 service-level live-write guard call sites.
- `rg -n "pytestmark = pytest.mark.safe|@pytest.mark.safe" tests`: only `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py` are explicitly marked safe, while `rg -c "^def test_|^    def test_" tests | awk ...` counted 864 test functions.
- `fd -a -H '^CONTEXT\\.md$|^docs/adr$|^adr$|^decisions$|^docs/architecture$' .`: no domain glossary, ADR directory, or architecture-doc directory found.
- `git status --ignored --short docs/overnight`: no existing overnight report or ignored output under `docs/overnight` before this write.

## Architecture Map

Current shape:

```text
Textual TUI: inbox.py
  -> sync HTTP client: inbox_client.py
  -> local FastAPI backend: inbox_server.py
       -> source implementation module: services.py
       -> index store: message_index_store.py
       -> sync pipeline: message_sync.py
       -> scheduler store: scheduler.py
       -> memory store: memory_store.py

MCP entrypoints:
  mcp_server.py / inbox_mcp_readonly.py / stdio wrappers
  -> tools_registry.py
  -> mcp_backend.py
  -> inbox_server.py

Source/local stores:
  macOS SQLite data, Google OAuth tokens, local SQLite index, local scheduler DB,
  local memory DB, Obsidian vault, token files, launchd/systemd/Caddy examples.
```

### Entrypoints

- `inbox.py:1-5` says the TUI is a thin HTTP client that auto-starts `inbox_server.py`. The code mostly follows that through `InboxClient`, but it still imports `services` directly for LLM status and favorites (`inbox.py:1954-1965`, `inbox.py:2082-2097`, `inbox.py:4048-4065`).
- `inbox_server.py:1-3` is the local REST server entrypoint. It binds at the bottom with `uvicorn.run(app, host="127.0.0.1", port=port)` and reads `INBOX_SERVER_PORT`.
- `message_sync.py:638-659` is a CLI for `bootstrap`, `incremental`, `rebuild`, and `summary` against `MessageIndexStore`.
- `mcp_server.py:1-15` is the full assistant-facing MCP HTTP gateway. It talks to the private inbox REST server and uses `INBOX_MCP_TOKEN`, `INBOX_SERVER_URL`, and `INBOX_SERVER_TOKEN`.
- `inbox_mcp_readonly.py:1-6` is the read-only MCP surface for less-trusted clients; it registers only readonly tools from `tools_registry.py` and runs on port 8001 by default (`inbox_mcp_readonly.py:77-87`).
- `scripts/run_inbox_backend.sh`, `scripts/run_inbox_mcp_http.sh`, and the stdio script wrappers all use `uv run python ...` with `UV_CACHE_DIR=/tmp/uv-cache`.
- `dev.sh:1-11` is the worktree-safe launcher. It defaults to `INBOX_SERVER_PORT=9850` and derives `INBOX_SERVER_URL`.

### Modules And Ownership

`services.py` is the main source implementation module. Its docstring states that all fetching, auth, mutation, audio, and LLM logic lives there (`services.py:1-4`). In practice it owns:

- local paths, credentials, and OAuth scopes (`services.py:54-98`);
- a read-only SQLite connection manager for macOS data sources (`services.py:215-309`);
- Google auth for Gmail, Calendar, Drive, Sheets, Docs, and Tasks (`services.py:330-416`);
- iMessage, Gmail, calendar, Notes, WhatsApp, Reminders, Tasks, Gemini, Maps, GitHub, Drive, Sheets, Docs, audio, LLM, search, notifications, favorites, voice commands, and calendar utility implementations.

This module has depth because deleting it would scatter provider complexity everywhere. The problem is its interface: callers must know too much about provider-specific objects, global paths, token state, write guards, side effects, and private helper functions. `message_sync.py:10-12` imports `IMSG_DB`, `_clean_body`, `_decode_body`, `_parse_email_address`, and `google_auth_all` from `services.py`, so the sync module crosses a private helper seam instead of a stable source-adapter interface.

`service_models.py` is the stable shared data-model module. It holds dataclasses for contacts, messages, calendar events, notes, reminders, Google tasks, GitHub notifications, Drive files, Sheets, Docs, and `ThreadSummary` (`service_models.py:1-153`). This module is deep and relatively clean: callers can use simple dataclasses without knowing provider SDK shapes.

`inbox_server.py` is the main orchestration module. It currently owns Pydantic response/request models, global state, production adapters, app lifecycle, auth middleware, route handlers, scheduler loops, index health, AI endpoints, workflow endpoints, and provider routing. Evidence:

- imports many names from `services.py` (`inbox_server.py:61-90` and continuing through the large import block);
- defines the only concrete `SourceAdapters`, currently Gmail and Calendar only (`inbox_server.py:750-799`);
- creates global `ServerState` with all service dictionaries, caches, ambient/dictation services, scheduler, index store, and adapters (`inbox_server.py:802-818`);
- uses `InboxServerRuntime` as a test seam for server state, contacts init, Google auth, scheduler startup, ambient autostart, prewarm, and SQLite cleanup (`inbox_server.py:825-833`);
- builds lifecycle behavior in `make_lifespan`, including contacts, Google auth, optional conversation prewarm, optional ambient autostart, scheduler loop, and cleanup (`inbox_server.py:1198-1285`);
- installs optional token auth middleware with bearer or `x-api-key` support (`inbox_server.py:1313-1340`);
- implements index views and sync endpoints in the same file (`inbox_server.py:2771-2807`, `inbox_server.py:3739-3853`).

`InboxServerRuntime` is a useful real seam. It has multiple adapters in tests (`tests/test_server.py:29-56`, `tests/test_api_contract.py:46-72`) and lets TestClient avoid real contacts, Google auth, scheduler, and ambient startup. `SourceAdapters` is only a partial seam: it has Gmail and Calendar adapters only, while most providers are still direct function calls from server routes to `services.py`. One adapter in production and few provider variants makes much of the adapter shape hypothetical rather than fully real.

`inbox_client.py` is the sync HTTP client module. It reads `INBOX_SERVER_PORT`, `INBOX_SERVER_URL`, and `INBOX_SERVER_TOKEN` at import/init time (`inbox_client.py:16-25`), can spawn `inbox_server.py` as a background process and write `server.log` (`inbox_client.py:48-77`), and mirrors many server routes as thin methods. Its indexed view methods (`inbox_client.py:86-131`) are a clean interface for the TUI, but the full client is broad because it mirrors the entire backend surface.

`inbox.py` is the TUI module. It is large but has a clearer external interface: the app talks mostly through `InboxClient` and renders Textual widgets. The module owns tab metadata consumption, state, polling, rendering, keyboard actions, optimistic message display, notifications, search overlays, command palette, AI actions, and cleanup. `tui_tabs.py:19-120` provides a small shared metadata module for tabs; this is a good deepening direction because commands and TUI navigation consume one shared tab table.

The indexed inbox slice is the most coherent current module group:

- `message_index_store.py:69-168` owns a local SQLite index with `sync_state`, `items`, `threads`, and `sender_stats`.
- `message_index_store.py:407-612` owns thread rebuild/query behavior and calls `thread_classifier.classify_thread`.
- `message_sync.py:181-269` implements resumable Gmail bootstrap.
- `message_sync.py:422-449` chooses Gmail history API incremental sync or timestamp fallback.
- `message_sync.py:452-560` reads iMessage by rowid and materializes indexed items.
- `message_sync.py:585-627` rebuilds only changed source/account scopes after bootstrap or incremental sync.
- `thread_classifier.py:18-47` concentrates actionability classification in one function, with small helper functions for human score, noise class, topic, urgency, open loop, and summary.

This slice has good locality for index behavior, but it still depends on private helpers and live Google auth in `services.py`, which weakens testability and makes it harder to run sync command candidates without credentials.

The MCP slice has a strong registry seam:

- `tools_registry.py:1-12` documents the intent: one `Tool` table drives both full and readonly MCP servers.
- `tools_registry.py:52-119` builds FastMCP handlers from registry metadata, adds confirmation for mutating tools, and dispatches through `backend._request`.
- `mcp_backend.py:18-59` is a small adapter over the private REST backend.
- `mcp_server.py:48-53` says HTTP-backed tools were migrated to `tools_registry.TOOLS`, leaving hand-written tools for ambient notes and memory.

This is one of the better seams in the repo. The risk is that the registry exposes 60 tools while `MCP_V1_PLAN.md:28-61` describes a much narrower V1 surface. The plan may be stale or the implementation may have outgrown the documented risk model.

### Local State And Deployment Surface

- `.gitignore:12-23` excludes credential and token files including `credentials.json`, `tokens/`, `github_token.txt`, `google_maps_key.txt`, `gemini_api_key.txt`, and env files.
- `.gitignore:41-58` excludes local MCP memory, scheduler DB, `.inbox_index.sqlite3`, logs, coverage, `.claude/`, and batch outputs.
- `scheduler.py:1-17` persists scheduled messages, follow-up reminders, and task-message links to `.inbox_scheduler.sqlite3`.
- `memory_store.py:1-10` persists structured memory to `.inbox_memory.sqlite3`.
- `ambient_notes.py:14-25` writes daily notes and ambient captures under `~/vault`.
- `deploy/Caddyfile.example:1-33` exposes only `/health` and `/mcp` for full and readonly MCP hostnames.
- `deploy/*.service.example` and `deploy/*.plist.example` hard-code `/Users/jwalinshah/projects/inbox` as the production working directory, so worktree routing must be explicit during development.

## Risks And Stale Assumptions

1. `services.py` is too wide for the current product phase.
   - Evidence: `services.py` is 6,467 LOC, owns all provider logic, and includes WhatsApp, Drive, Sheets, Docs, Maps, GitHub, audio, LLM, notifications, and favorites despite `PLAN.md` narrowing Phase 1 to Gmail, iMessage, calendar, index, and TUI.
   - Architectural effect: the module has leverage, but the interface is shallow and implicit. Callers must know provider SDK details, private helpers, path globals, and auth side effects.
   - Safe next move: introduce source-adapter modules around Gmail and iMessage sync/read paths first, because those are core to the plan and already have tests.

2. `inbox_server.py` is a server, runtime, router, policy layer, scheduler host, index controller, and workflow module at once.
   - Evidence: 3,940 LOC, 160 `@app.*` decorators, broad `services.py` imports, global `state`, lifecycle side effects, auth middleware, and index sync endpoints.
   - Architectural effect: route changes have poor locality. A bug in account routing, runtime startup, index health, or endpoint response shape all require understanding the same file.
   - Safe next move: split router groups only after preserving `create_app(runtime)` behavior and API contract tests.

3. Startup has live side effects that are easy to trigger accidentally.
   - Evidence: `make_lifespan` always calls contacts init and `google_auth_all` unless a runtime overrides them (`inbox_server.py:1209-1222`). `google_auth_all` can migrate legacy tokens and may run a browser OAuth flow if scopes are missing and `credentials.json` exists (`services.py:341-359`).
   - Architectural effect: the app lifecycle interface includes hidden credential and browser behavior. Test fixtures avoid it, but manual server starts and some direct TestClient uses still need care.
   - Safe next move: add an explicit startup mode/policy object that separates "load existing tokens" from "interactive reauth/migration".

4. The read-only/write safety model is layered but not yet unified.
   - Evidence: service-level `INBOX_TEST_MODE` blocks 44 representative live-write paths; MCP registry has 34 confirm-gated tools; FastAPI write endpoints are still callable directly if the server token allows them.
   - Architectural effect: "safe" depends on which interface the caller used: tests use `INBOX_TEST_MODE`, MCP uses `confirm=True`, REST uses server auth plus service guards. These are related policies but not one module.
   - Safe next move: define a small write-policy module that can be called from REST, MCP registry, and service functions.

5. Validation documentation is stale or under-specified.
   - Evidence: `docs/TESTING_FOR_AGENTS.md` recommends `INBOX_TEST_MODE=1 uv run pytest -m safe`, but only two test modules are marked safe. `DOCS_INDEX.md` and `SHEETS_CHANGELOG.md` claim "736 tests pass", while the current test tree has 864 `test_` functions by static count.
   - Architectural effect: agents may run a tiny safe subset and believe they validated the repo, or trust an outdated test-count claim.
   - Safe next move: audit test markers and split "agent-safe full unit suite" from "minimal smoke suite".

6. Indexed views are now the default TUI path, but the assumptions are encoded as route logic rather than product terminology.
   - Evidence: `_index_view_rows` hard-codes actionable/recent/waiting-on filters (`inbox_server.py:2771-2807`). `MessageIndexStore.list_threads` hard-codes `newest_only` as seven days and waiting-on-others depends on `latest_sender = "Me"` (`message_index_store.py:565-612`).
   - Architectural effect: changing product language such as "Now", "Waiting On", or "Actionable" requires touching server route logic and store query predicates.
   - Safe next move: create an index-view definition table with view names, predicates, and acceptance tests.

7. MCP implementation and MCP V1 docs have drifted.
   - Evidence: `MCP_V1_PLAN.md` lists a small V1 set, but `tools_registry.py` now has 60 tools spanning Gmail, Sheets, Drive, Docs, Calendar, Tasks, search, memory, and workflows.
   - Architectural effect: security and UX review cannot rely on the plan file. The implementation may be correct, but the decision record is stale.
   - Safe next move: generate a docs-only MCP surface inventory from `tools_registry.TOOLS`, including readonly/write/confirm status.

8. No local architecture decision record exists.
   - Evidence: no `CONTEXT.md`, `docs/adr/`, `adr/`, or `docs/architecture/` found. Architecture decisions are spread across `CLAUDE.md`, `PLAN.md`, `CONNECTOR_ROADMAP.md`, and implementation files.
   - Architectural effect: future agents will keep rediscovering the same source-adapter, account-routing, index-default, and MCP-surface decisions.
   - Safe next move: add a docs-only `docs/architecture/` or ADR index before large refactors.

## Deepening Opportunities

1. Deepen the source-adapter seam for index sync.
   - Files: `services.py`, `message_sync.py`, `message_index_store.py`, `tests/test_message_sync.py`.
   - Problem: `message_sync.py` imports private helpers and `google_auth_all` from `services.py`; testing and sync behavior are coupled to live auth unless heavily monkeypatched.
   - Solution: define Gmail and iMessage source adapter interfaces owned by the sync slice, with production adapters wrapping `services.py` and fake adapters in tests.
   - Benefit: better locality for sync correctness and more leverage from tests. The interface becomes "fetch changed source items" rather than a collection of private provider helpers.

2. Deepen the server policy seam for Google account routing and write preflight.
   - Files: `google_account_resolution.py`, `inbox_server.py`, `services.py`, `tests/test_server.py`, `tests/test_gmail_actions.py`.
   - Problem: account routing is partly centralized but still spread through route wrappers, service calls, preflight, and docs. The default account policy is documented in `CONNECTOR_ROADMAP.md` but enforced only through helper behavior and env choices.
   - Solution: make an explicit policy module that resolves account, destination, write safety, and explanation before each write.
   - Benefit: higher leverage for all Google write paths and fewer account-routing regressions.

3. Deepen indexed view definitions.
   - Files: `inbox_server.py`, `inbox_client.py`, `inbox.py`, `message_index_store.py`, `tests/test_message_index_store.py`, `tests/test_client.py`.
   - Problem: "Now", "Actionable", and "Waiting On" are product concepts, but their exact filters are scattered across server route helpers and store method parameters.
   - Solution: create one view-definition module that maps product view names to store predicates, labels, and expected sorting.
   - Benefit: callers get a smaller interface and tests can assert product meaning without duplicating predicate knowledge.

4. Deepen MCP registry documentation and safety.
   - Files: `tools_registry.py`, `mcp_server.py`, `inbox_mcp_readonly.py`, `MCP_V1_PLAN.md`, `MCP_SETUP.md`, `tests/test_tools_registry.py`, `tests/test_api_contract.py`.
   - Problem: the implementation has a strong registry, but docs no longer match the tool surface.
   - Solution: generate or hand-maintain a registry inventory table that lists tool name, route, readonly/write, confirm requirement, and exposure path.
   - Benefit: security review and cloud-agent handoff become concrete and testable.

## Independently Grabbable Next Tasks

1. Test-marker audit and validation doc repair.
   - Acceptance criteria:
     - Identify which current tests are deterministic and agent-safe.
     - Add or adjust `safe` markers, or update `docs/TESTING_FOR_AGENTS.md` so it no longer implies broad coverage from `pytest -m safe`.
     - Replace stale "736 tests pass" claims with current evidence or remove exact count claims.
   - Suggested validation:
     - `INBOX_TEST_MODE=1 uv run pytest -m safe -q --no-cov`
     - `uv run ruff check docs/TESTING_FOR_AGENTS.md DOCS_INDEX.md SHEETS_CHANGELOG.md` if markdown lint is configured; otherwise `git diff --check`.
   - Owned files:
     - `docs/TESTING_FOR_AGENTS.md`, `DOCS_INDEX.md`, `SHEETS_CHANGELOG.md`, selected `tests/*.py`.

2. MCP surface inventory docs.
   - Acceptance criteria:
     - Add a docs-only table generated from or manually synchronized with `tools_registry.TOOLS`.
     - Each row includes tool name, HTTP method/path, readonly/write, confirm-gated status, and whether it appears in full MCP, readonly MCP, or both.
     - `MCP_V1_PLAN.md` either becomes historical or is updated to match the current surface.
   - Suggested validation:
     - `INBOX_TEST_MODE=1 uv run pytest tests/test_tools_registry.py tests/test_api_contract.py -q --no-cov`
     - `git diff --check`
   - Owned files:
     - `MCP_V1_PLAN.md`, `MCP_SETUP.md`, possible new `docs/mcp-surface.md`.

3. Indexed view definition module.
   - Acceptance criteria:
     - Move hard-coded view names/predicates from `_index_view_rows` into a small pure module.
     - Preserve endpoint responses for `/index/views/{view_name}`.
     - Add tests proving `recent`, `actionable`, `waiting-on`, `waiting-on-me`, and `waiting-on-others` map to expected store queries.
   - Suggested validation:
     - `INBOX_TEST_MODE=1 uv run pytest tests/test_message_index_store.py tests/test_server.py::TestIndexEndpoints tests/test_client.py::TestClientIndexedInbox -q --no-cov`
     - `uv run ruff check inbox_server.py message_index_store.py tests/test_message_index_store.py tests/test_server.py tests/test_client.py`
   - Owned files:
     - `inbox_server.py`, new small index view module, `message_index_store.py` only if its interface must change, related tests.

4. Source-adapter seam for sync.
   - Acceptance criteria:
     - Introduce explicit production/fake adapters for Gmail sync and iMessage sync.
     - `message_sync.bootstrap` and `message_sync.incremental` accept injected adapters or a runtime object in tests.
     - No behavior change to CLI defaults.
   - Suggested validation:
     - `INBOX_TEST_MODE=1 uv run pytest tests/test_message_sync.py tests/test_message_index_store.py -q --no-cov`
     - `uv run ruff check message_sync.py message_index_store.py tests/test_message_sync.py`
   - Owned files:
     - `message_sync.py`, possible new adapter module, `tests/test_message_sync.py`.

5. Server runtime/router split spike.
   - Acceptance criteria:
     - Move only one low-risk route group, preferably index routes, into a router module while preserving `create_app(runtime)`.
     - API contract tests still prove MCP paths and client response shapes.
     - No provider route behavior changes.
   - Suggested validation:
     - `INBOX_TEST_MODE=1 uv run pytest tests/test_api_contract.py tests/test_server.py::TestIndexEndpoints -q --no-cov`
     - `uv run ruff check inbox_server.py <new_router_module>.py tests/test_api_contract.py tests/test_server.py`
   - Owned files:
     - `inbox_server.py`, new route module, index endpoint tests.

## Validation Candidates

Required queue validation:

- `git status --short`
  - Final observed status in this sandbox: command runs successfully and reports the untracked docs-only report path.
  - Clean status would require staging/committing the report, but `git add docs/overnight/inbox-sym-214-architecture-map.md` is blocked by sandbox permissions because this worktree's Git metadata lives under `/Users/jwalinshah/projects/inbox/.git/worktrees/inbox-sym-214-architecture-map/index.lock`, outside the writable roots.

Cheap architecture validation candidates not run during this audit:

- `git diff --check`
  - Expected status: pass for this docs-only report.

- `INBOX_TEST_MODE=1 uv run pytest -m safe -q --no-cov`
  - Expected status: pass, but coverage is currently narrow because only two modules are explicitly marked safe.

- `INBOX_TEST_MODE=1 uv run pytest tests/test_message_index_store.py tests/test_message_sync.py -q --no-cov`
  - Expected status: pass for the index/sync slice, assuming dependencies are installed.

- `INBOX_TEST_MODE=1 uv run pytest tests/test_tools_registry.py tests/test_api_contract.py -q --no-cov`
  - Expected status: pass for MCP registry route coverage, assuming dependencies are installed.

- `uv run ruff check .`
  - Expected status: likely pass if recent merges were clean, but unverified in this queue item.

- `uv run pyright`
  - Expected status: unknown. The repo config enables basic type checking and `reportMissingImports=true`; local ML/macOS/provider imports may affect this outside the pytest stubbing path.

I did not run pytest, ruff, or pyright because the queue item validation is `git status --short`, the audit is read-only/docs-only, and pytest addopts include coverage by default unless overridden.

## Non-Goals

- No product-code refactor.
- No endpoint, MCP tool, or TUI behavior change.
- No live server start.
- No Google, Gmail, Calendar, Drive, Docs, Sheets, GitHub, iMessage, Notes, Reminders, WhatsApp, audio, or external service calls.
- No credential/token inspection beyond tracked example files and `.gitignore`.
- No deploy, public exposure, push, PR creation, or external tracker update.
- No sibling repo comparison. This repo is not small: the top-level Python modules alone are 21,703 LOC and warranted the full audit time locally.

## Unknowns

- Whether the primary daily-driver server on port 9849 is healthy today; not checked because this queue item avoids live local services.
- Whether local OAuth token state matches documented multi-account assumptions.
- Whether WhatsApp, Drive, Sheets, Docs, GitHub, memory, and voice are active product scope or historical accretion.
- Whether all 864 statically counted tests pass; no test suite was run.
- Whether the "736 tests pass" docs claim was true when written; it is stale against current static test count.
- Whether `INBOX_DEFAULT_GOOGLE_ACCOUNT` is set in production and whether account routing matches the roadmap's desired default.
- Whether the MCP full surface is intentionally public/trusted or simply ahead of `MCP_V1_PLAN.md`.

## Handoff Notes

Changed file from this queue item:

- `docs/overnight/inbox-sym-214-architecture-map.md`

No blockers encountered for writing the report. Commit evidence is blocked locally by Git metadata permissions outside the writable roots; the handoff should treat the uncommitted docs-only report as the artifact.
