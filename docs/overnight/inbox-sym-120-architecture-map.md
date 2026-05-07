# Overnight Architecture Map: inbox-sym-120

Queue item: `inbox-sym-120-architecture-map`
Repo: `inbox-sym-120`
Worktree: `/Users/jwalinshah/projects/agent-stack/.agent-stack-worktrees/2026-05-07-overnight-marathon/inbox-sym-120-architecture-map`
Branch observed: `codex/goal-inbox-sym-120-architecture-map`
Initial HEAD observed: `2805b84` (`Merge pull request #34 from jwalin-shah/codex/SYM-9-indexed-defaults`)
Initial dirty state observed: clean, from `git status --short` producing no output.

## Scope And Method

This is a read-only architecture-map audit. Product code, secrets, generated data, pushes, deploys, external services, tracker updates, and PR creation are out of scope. The only intended repository mutation is this report.

Commands and observations used as evidence:

- `llm-tldr tree .` showed a flat Python repo with top-level modules, `tests/`, `scripts/`, `deploy/`, `config/`, `modes/`, `batch/`, and a single existing docs file before this report: `docs/TESTING_FOR_AGENTS.md`.
- `git status --short --branch` showed `## codex/goal-inbox-sym-120-architecture-map` and no dirty files at audit start.
- `git rev-parse --short HEAD` returned `2805b84`.
- `git log --oneline -5` showed recent work around indexed inbox defaults and sync freshness health.
- `wc -l *.py tests/*.py` showed `services.py` at 6,467 lines, `inbox.py` at 4,279 lines, `inbox_server.py` at 3,940 lines, and 36,403 Python lines total.
- `rg -c "^@app\\." inbox_server.py` returned `160`, so the FastAPI surface is broad and route-heavy.
- `rg -c "^(def|class) " services.py` returned `205`, so the data-access module has a very wide interface.
- `rg -c "^    Tool\\(" tools_registry.py` returned `60`; `rg -c "readonly=True" tools_registry.py` returned `29`.
- `fd -H -d 2 -t f . .` showed hidden local configs including `.mcp.json`, `.cursor/mcp.json`, `.factory/services.yaml`, `.env.mcp.example`, and `.gitignore`.
- `rtk read docs/TESTING_FOR_AGENTS.md` documented the agent-safe command set: `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, and `uv run pyright`.

## Repo Purpose

Inbox is a local-first personal communication and productivity control plane. It combines iMessage, Gmail, Google Calendar, Google Drive, Google Sheets, Google Docs, Google Tasks, Apple Notes, Apple Reminders, GitHub notifications, ambient audio notes, dictation, local LLM features, and MCP access into one local backend plus terminal UI.

The primary production shape is:

```text
Textual TUI or agent client
  -> local HTTP client
  -> FastAPI backend on 127.0.0.1:9849
  -> provider adapters and local stores
  -> macOS SQLite stores, Google APIs, GitHub API, local ML, AppleScript
```

The MCP shape is:

```text
MCP client
  -> mcp_server.py or inbox_mcp_readonly.py
  -> mcp_gateway.py / mcp_backend.py
  -> private inbox_server.py
  -> services.py and persistence modules
```

The repo is not a library-first package. It is a runnable application with several executable surfaces and many provider-specific integrations in the repository root.

## Primary Entrypoints

- `inbox.py` is the Textual TUI entrypoint. Its `InboxApp` class owns UI state, polling, tab switching, command handling, optimistic sends, notifications, and client calls.
- `inbox_server.py` is the private FastAPI backend entrypoint. It defines Pydantic request/response models, global runtime state, lifecycle setup, schedulers, route handlers, and account routing wrappers.
- `inbox_client.py` is the synchronous HTTP client used by the TUI and some agent workflows. It also starts `inbox_server.py` as a subprocess if the TUI cannot reach it.
- `mcp_server.py` is the full MCP HTTP gateway. It has a few hand-written memory and daily-note tools, then registers the shared tool registry with `readonly_only=False`.
- `inbox_mcp_readonly.py` is the read-only MCP HTTP gateway. It registers only registry tools marked `readonly=True`, plus read-only memory and daily-note tools.
- `inbox_mcp_stdio.py` and `inbox_mcp_readonly_stdio.py` are small local subprocess wrappers around the HTTP MCP app surfaces.
- `scripts/run_inbox_backend.sh`, `scripts/run_inbox_mcp_http.sh`, `scripts/run_inbox_mcp_http_readonly.sh`, `scripts/run_inbox_mcp_stdio.sh`, and `scripts/run_inbox_mcp_stdio_readonly.sh` are operational entrypoints.
- `ambient_daemon.py`, `organize_inbox.py`, `unsubscribe_interactive.py`, `unsubscribe_bulk.py`, and `unsubscribe_all_newsletters.py` are utility entrypoints layered on top of the same backend or service functions.
- `main.py` is a placeholder that prints `Hello from inbox!`; it is not the real application entrypoint despite being present in a `uv` project.

## Module Map

### Data And Provider Module

`services.py` is the central data and provider module. Its file header explicitly says that all data fetching, auth, mutation, audio, and LLM logic lives there. It imports Google OAuth clients, `httpx`, SQLite, subprocess, threading, contacts, and shared service dataclasses. It defines local paths for `credentials.json`, `tokens/`, `github_token.txt`, `google_maps_key.txt`, `gemini_api_key.txt`, iMessage, Notes, and Reminders.

The module owns these interfaces and implementations:

- Google auth and account token loading via `google_auth_all`, `add_google_account`, and `reauth_google_account`.
- iMessage listing, thread loading, and AppleScript sending via `imsg_contacts`, `imsg_thread`, and `imsg_send`.
- Gmail listing, body cleanup, thread loading, reply/send, archive, delete, labels, filters, and search.
- Calendar events, conflicts, reminders, RSVP, attendees, free/busy, free slots, and recurring instances.
- Apple Notes, Apple Reminders, WhatsApp Accessibility access, Google Tasks, Gemini helpers, Google Maps, GitHub, Drive, Sheets, Docs, ambient audio, dictation, local LLM, autocomplete, cross-source search, notifications, favorites, contacts, briefing, triage, summarization, and voice-command routing.

Architectural reading: `services.py` is a deep implementation module, but its interface is now too broad. Callers must know provider object ownership, account routing, write safety, local file side effects, optional ML availability, and macOS permission behavior. The module has leverage, but poor locality for a maintainer changing one provider.

### Shared Data Models

`service_models.py` is the pure dataclass model module. It defines `Contact`, `Msg`, `CalendarEvent`, `Note`, `Reminder`, `GoogleTask`, `GitHubNotification`, `DriveFile`, `SheetTab`, `Spreadsheet`, `Document`, and `ThreadSummary`.

This is one of the cleaner modules. It is a small interface with stable data shapes shared by the backend and service functions. The main caveat is that the server separately defines many Pydantic DTOs in `inbox_server.py`, so there are two model layers to keep aligned.

### FastAPI Server Module

`inbox_server.py` is the server and orchestration module. Evidence:

- It imports a large list of functions and classes from `services.py`.
- It defines many Pydantic request/response models at the top of the file.
- It defines `ServerState` with Google service dictionaries, conversation cache, event cache, `AmbientService`, `DictationService`, `SchedulerStore`, `MessageIndexStore`, and `SourceAdapters`.
- It defines `InboxServerRuntime`, which lets tests inject fake state, fake auth, disabled scheduler, disabled ambient autostart, and a SQLite cleanup hook.
- `create_app(runtime)` builds a new FastAPI app, but then copies routes and middleware from a global existing `app` if present.
- The route surface is large: 160 route decorators were observed.

The server owns policy-adjacent orchestration, but not consistently. Some account selection is centralized in `google_account_resolution.py`, while route handlers still directly choose services, read global state, and call provider functions.

### TUI Module

`inbox.py` is the Textual app. It contains many UI item classes and a single large `InboxApp` class. The class owns:

- Server boot and auto-start through `InboxClient.ensure_server`.
- Refresh and poll flows through `_collect_refresh_data`, `_collect_poll_data`, `_collect_auxiliary_data`, `_populate`, and background workers.
- TUI tab state, sidebar rendering, selection routing, detail rendering, and compose-mode multiplexing.
- User actions for messages, calendar, reminders, Gmail, GitHub, Drive, search, command palette, briefings, favorites, and AI summaries.

This makes the TUI module a large interface for UI state transitions. It is test-covered, but the core class combines view state, interaction state, API orchestration, and per-provider action behavior.

### HTTP Client Module

`inbox_client.py` is a synchronous `httpx` wrapper. It reads `INBOX_SERVER_PORT`, `INBOX_SERVER_URL`, and `INBOX_SERVER_TOKEN`, constructs an authenticated client, exposes endpoint methods, and can start `inbox_server.py` as a subprocess with `server.log`.

This is a useful seam for the TUI. It is less clearly the agent-facing seam now that MCP has its own `mcp_backend.py` and registry-driven handlers. There is overlap between `InboxClient` methods and `InboxBackend` methods.

### MCP Modules

`tools_registry.py` is a strong newer seam. A `Tool` describes MCP name, HTTP method, path, params, readonly flag, and confirm flag. `register_all` attaches handlers to FastMCP. `tests/test_tools_registry.py` verifies that mutating registry tools require confirmation, read-only registration excludes write tools, path params are URL-encoded, and body params are not URL-encoded.

`mcp_backend.py` is an async HTTP backend for MCP. It also still carries many hand-written methods that mirror routes. `tools_registry.py` handlers bypass those methods and call `_request` directly, which means old backend convenience methods and registry entries can drift unless tests intentionally cover both.

`mcp_gateway.py` provides Starlette app assembly, bearer auth for public MCP, health, backend creation, and memory-store creation.

`mcp_server.py` and `inbox_mcp_readonly.py` are thin gateway compositions with different write exposure. This is a good separation, but the docs have older and newer claims that do not fully agree with the current registry.

### Persistence And Index Modules

`memory_store.py` is a local SQLite memory store with a separate `INBOX_MEMORY_DB` override in `mcp_gateway.py`.

`scheduler.py` owns `.inbox_scheduler.sqlite3` and models scheduled messages, followup reminders, and task-message links. `inbox_server.py` owns the runtime scheduler loop that calls this store and provider functions every 30 seconds.

`message_index_store.py` owns `.inbox_index.sqlite3`, sync state, indexed items, threads, and sender stats. It sets WAL mode and migrates schema in place.

`message_sync.py` fills the index from Gmail and iMessage. It imports `IMSG_DB`, `_clean_body`, `_decode_body`, `_parse_email_address`, and `google_auth_all` from `services.py`, so indexing is coupled to the broad service module rather than to a narrow source adapter interface.

`gmail_triage.py` owns workflow classification, action extraction, ranking, summaries, and Pydantic thread summary output. It imports `Contact` and `ThreadSummary` from `services.py`, where those names are re-exported from `service_models.py`.

### Config, Deployment, And Local State

- `README.md`, `CLAUDE.md`, `MCP_SETUP.md`, `CONNECTOR_ROADMAP.md`, `DOCS_INDEX.md`, and Sheets docs are the main architecture docs.
- `.mcp.json` and `.cursor/mcp.json` point both full and read-only local MCP stdio servers at `http://127.0.0.1:9849`.
- `dev.sh` defaults development worktrees to port `9850` and derives `INBOX_SERVER_URL`.
- `.factory/services.yaml` starts the service from `/Users/jwalinshah/projects/inbox`, not from the current worktree. This is consistent for a primary checkout, but risky in worktree testing.
- `.gitignore` correctly ignores credentials, token files, logs, `.inbox_memory.sqlite3`, `.inbox_scheduler.sqlite3`, and `.inbox_index.sqlite3`.
- `deploy/Caddyfile.example` exposes only `/health` and `/mcp` for full and read-only MCP gateways.

## Key Seams

1. TUI-to-server seam: `InboxClient` hides HTTP details from `InboxApp`, including auth headers and server boot.
2. Server-to-provider seam: currently mostly direct calls from `inbox_server.py` into `services.py`.
3. Google account-routing seam: `google_account_resolution.py` is a narrower policy module shared by server and tests.
4. MCP tool-definition seam: `tools_registry.py` centralizes tool exposure and read/write gating.
5. MCP transport seam: `mcp_gateway.py` creates Starlette apps and public auth independent of tool definitions.
6. Persistence seams: `SchedulerStore`, `MemoryStore`, and `MessageIndexStore` isolate local SQLite schemas.
7. Test-mode seam: `inbox_test_mode.py` redirects local data paths and blocks live writes when `INBOX_TEST_MODE=1`.
8. Runtime injection seam: `InboxServerRuntime` allows server tests to bypass real auth, real contacts, scheduler, and ambient autostart.

## Risks And Stale Assumptions

### Risk 1: `services.py` Is Too Broad For Safe Change Locality

The module has 205 top-level definitions and owns most provider behavior. The deletion test says this module is not shallow because deleting it would scatter real complexity. The problem is that its public interface is nearly as broad as the implementation: the server must know specific provider functions, account service objects, local file assumptions, and mutation semantics.

Why it matters: changes to one provider can accidentally affect import-time behavior, test stubs, write safety, or unrelated providers. New agents will tend to patch in place rather than identify the right source adapter.

### Risk 2: Server Global State And App Factory Are Coupled

`inbox_server.py` creates a global `state = ServerState()` and `app = create_app()`. `make_lifespan` swaps global state when a runtime is injected. `create_app(runtime)` copies routes from an existing global `app` into the new app.

Why it matters: this makes test isolation possible, but the interface is subtle. Future route registration, middleware changes, or multiple app instances can behave differently depending on import order and prior global state.

### Risk 3: MCP Documentation Is Partly Behind The Tool Surface

`MCP_V1_PLAN.md` says Calendar stays on a built-in ChatGPT connector and destructive mail actions/deletes stay out of scope in v1. Current `tools_registry.py` exposes calendar and many mutation tools behind confirmation, including delete-style actions for tasks, Drive files, Docs, Sheets, and GitHub notifications.

Why it matters: morning reviewers or external agents reading the plan may underestimate the live write surface. `MCP_SETUP.md` appears newer and more accurate than `MCP_V1_PLAN.md`.

### Risk 4: Worktree Routing Can Silently Hit The Primary Backend

Docs repeatedly warn that dev worktrees must set both `cwd` and `INBOX_SERVER_URL`. `.mcp.json`, `.cursor/mcp.json`, and `.factory/services.yaml` all point at primary `9849` or `/Users/jwalinshah/projects/inbox`.

Why it matters: an agent in a worktree can believe it is testing local changes while the MCP or factory service is still talking to the daily-driver checkout.

### Risk 5: Test Documentation Overstates The Safe Test Surface

`docs/TESTING_FOR_AGENTS.md` says to run `INBOX_TEST_MODE=1 uv run pytest -m safe`, but `rg` only found module-level `pytestmark = pytest.mark.safe` in `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py`. Many deterministic unit tests appear unmarked. `DOCS_INDEX.md` also claims `uv run pytest` has 736 passing tests; this audit did not run that suite, and the claim is date-sensitive.

Why it matters: agents following the safe command may get a narrow safety check while believing they proved the full deterministic surface.

### Risk 6: Optional Experimental Surface Is Hidden In The Server

`inbox_server.py` exposes `/query`, which imports `gemma4_hackathon` dynamically and returns 503 if missing. This dependency is not listed in `pyproject.toml`.

Why it matters: it is fine as an optional experiment, but it is not visible in the main architecture docs or dependency surface. It adds another source of route ownership and runtime behavior.

### Risk 7: Two HTTP Client Abstractions Can Drift

`InboxClient` is the TUI/client wrapper. `InboxBackend` is the MCP wrapper. `tools_registry.py` now builds handlers that call `InboxBackend._request` directly, while `InboxBackend` also contains older named methods. This is manageable, but it is a drift risk.

Why it matters: a backend method can be fixed without fixing the registry path, or a new endpoint can be added to the registry without a corresponding ergonomic client method.

## Existing Strengths

- The HTTP API seam is real. The TUI does not directly read Gmail, iMessage, or local databases.
- `service_models.py` is small and stable.
- `google_account_resolution.py` is a good example of extracting policy from route handlers.
- `tools_registry.py` is a good example of turning a broad MCP surface into data, with tests proving confirmation and readonly behavior.
- `InboxServerRuntime` gives tests a practical way to run the server without live auth and background loops.
- `inbox_test_mode.py` and `docs/TESTING_FOR_AGENTS.md` show an explicit safety model for agents.
- `.gitignore` covers the highest-risk local secrets and generated SQLite files.
- `MCP_SETUP.md` documents a safer remote topology: expose MCP, keep the private backend loopback-only, prefer read-only MCP for cloud agents.

## Next Safe Work

### Task 1: Split The Provider Ownership Map Out Of `services.py`

Acceptance criteria:

- Add a docs-only ownership map listing each provider area in `services.py`, the current public functions, mutation functions, local side effects, and tests covering it.
- Do not move code in this task.
- Identify the first two low-risk provider modules that could later be extracted behind source adapters.

Validation candidates:

- `git status --short` should show only the new docs file while drafting or be clean after commit.
- `uv run ruff check .` expected to pass because no Python changes are needed.

### Task 2: Reconcile MCP Docs Against `tools_registry.py`

Acceptance criteria:

- Update or supersede `MCP_V1_PLAN.md` so it no longer claims calendar and destructive actions are out of scope if the current registry intentionally exposes them behind confirmation.
- Add a generated or manually checked table of registry tool counts: total, readonly, mutating, confirmation-gated.
- State which doc is authoritative: `MCP_SETUP.md`, the registry, or a new ADR.

Validation candidates:

- `uv run pytest tests/test_tools_registry.py -q` expected to pass.
- `uv run ruff check tools_registry.py mcp_server.py inbox_mcp_readonly.py` expected to pass.

### Task 3: Make App Factory State Less Surprising

Acceptance criteria:

- Document and then simplify the `create_app(runtime)` route-copying pattern, or add tests that prove multiple app instances do not duplicate routes or share unexpected mutable state.
- Keep `InboxServerRuntime` as the test injection interface.
- Preserve existing TestClient fixtures.

Validation candidates:

- `INBOX_TEST_MODE=1 uv run pytest tests/test_server.py tests/test_conversations_latency.py -q` expected to pass.
- `uv run pyright` may expose existing type debt; if so, record the current baseline rather than expanding the task.

### Task 4: Mark The Deterministic Safe Test Surface Deliberately

Acceptance criteria:

- Audit tests that do not touch live personal data or external writes and add `safe` markers or a repo-level marker strategy.
- Keep local-data, live-write, slow, and ML/hardware tests opt-in.
- Update `docs/TESTING_FOR_AGENTS.md` so `pytest -m safe` has clear coverage expectations.

Validation candidates:

- `INBOX_TEST_MODE=1 uv run pytest -m safe -q` expected to pass and collect a meaningful subset.
- `INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py tests/test_mcp_gateway.py -q` expected to pass as the current known safe subset.

### Task 5: Add A Worktree Routing Self-Check

Acceptance criteria:

- Add a read-only endpoint or script that reports current repo path, branch, backend URL, and whether MCP is pointed at the same worktree.
- Do not expose secrets.
- Make the check easy for agents to run before exercising a dev backend.

Validation candidates:

- `uv run pytest tests/test_mcp_gateway.py tests/test_client.py -q` expected to pass if the check stays outside product routes.
- If adding a server endpoint, also run `INBOX_TEST_MODE=1 uv run pytest tests/test_server.py -q`.

## Validation Candidates For This Repo

Observed authoritative docs list these commands:

- Required queue validation: `git status --short`. Expected status for this report after commit: exit 0 and no output. If left uncommitted, expected output is only `?? docs/overnight/inbox-sym-120-architecture-map.md`.
- Agent-safe default: `INBOX_TEST_MODE=1 uv run pytest -m safe`. Expected to pass for the currently marked safe tests, but likely narrower than the repo's deterministic test surface.
- Lint: `uv run ruff check .`. Expected to pass based on repo docs, not executed during this audit.
- Type check: `uv run pyright`. Expected status unknown because pyright was not executed during this audit.
- Full tests: `uv run pytest`. Expected status unknown and potentially expensive because it spans provider-heavy modules, though tests stub many heavy dependencies.
- Factory command: `.factory/services.yaml` defines `uv run pytest --ignore=tests/test_audio.py --ignore=tests/test_llm.py -x -q`. Expected status unknown and path-sensitive because the service config is hardcoded to the primary checkout.

## Non-Goals

- No product-code refactor.
- No test, lint, or type-fix implementation.
- No live server start.
- No OAuth, Gmail, Calendar, Drive, Docs, Sheets, Tasks, GitHub, iMessage, Notes, Reminders, microphone, dictation, desktop notification, or AppleScript operation.
- No external tracker update.
- No push, deploy, or PR creation.
- No sibling-repo comparison. The repo is large enough for the architecture-map scope; sibling comparison would be a separate queue item.

## Unknowns

- Whether the full test suite currently passes. This audit did not run it because the queue validation command is `git status --short` and the goal scope is read-only architecture mapping.
- Whether the daily-driver backend on port 9849 was running or healthy. This audit intentionally did not call it.
- Whether local credentials and token files exist in the primary checkout. They are intentionally ignored and were not inspected.
- Whether `gemma4_hackathon` is installed in any local developer environment.
- Whether the docs claim of 736 passing tests is still accurate on May 7, 2026.
- Whether the current MCP write surface is intentional v1 scope or accumulated implementation drift.

## Handoff Notes

The best next architectural move is not a broad extraction. The safer first move is to document provider ownership in `services.py`, then extract one or two policy modules like `google_account_resolution.py` where tests already show value. The highest-leverage documentation cleanup is reconciling `MCP_V1_PLAN.md` against the live registry so future agents do not reason from a stale write-surface model.
