# inbox-sym-119 Architecture Map Audit

Queue item: `inbox-sym-119-architecture-map`

Focus area: `architecture-map`

Repo: `inbox-sym-119`

Report path: `docs/overnight/inbox-sym-119-architecture-map.md`

## 1. Scope

This is a read-only architecture audit. The only repository mutation made for
this queue item is this report file.

In scope:

- Module boundaries, entrypoints, ownership, and runtime state.
- Stale architecture assumptions in local docs.
- Local evidence from files and command observations.
- Validation command candidates and next safe Work Pack or Linear-ready tasks.

Out of scope:

- Product code changes.
- Generated data changes.
- Credential reads beyond path/name inventory.
- External services, deploys, pushes, PR creation, or tracker state changes.
- Running live personal inbox flows, OAuth flows, AppleScript sends, or provider
  write endpoints.

## 2. Repo State

- Current working directory observed with `pwd`:
  `/Users/jwalinshah/projects/agent-stack/.agent-stack-worktrees/2026-05-07-overnight-marathon/inbox-sym-119-architecture-map`
- Branch observed with `git status --short --branch`:
  `codex/goal-inbox-sym-119-architecture-map`
- Initial HEAD observed with `git rev-parse HEAD`:
  `2805b8400519da188ca7d3f6e39b19a8ca42b05a`
- Initial dirty state observed with `git status --short`: clean, no output.
- `CONTEXT.md` and `docs/adr/` were not present in this worktree. The durable
  architecture context is spread across `README.md`, `CLAUDE.md`, `PLAN.md`,
  `CONNECTOR_ROADMAP.md`, `DOCS_INDEX.md`, `.factory/library/*.md`, source, and
  tests.

## 3. Commands Run And Local Observations

Representative commands used during the audit:

- `llm-tldr tree .`
  - Observed a flat Python application with top-level modules including
    `services.py`, `inbox_server.py`, `inbox_client.py`, `inbox.py`,
    `message_index_store.py`, `message_sync.py`, `gmail_triage.py`,
    `thread_classifier.py`, `mcp_backend.py`, `mcp_server.py`,
    `tools_registry.py`, `scheduler.py`, and `memory_store.py`.
- `git status --short --branch`
  - Observed branch `codex/goal-inbox-sym-119-architecture-map`.
- `git rev-parse HEAD`
  - Observed initial SHA `2805b8400519da188ca7d3f6e39b19a8ca42b05a`.
- `fd -a '^(CONTEXT.md|AGENTS.md|CLAUDE.md|README.md|DOCS_INDEX.md|PLAN.md|CONNECTOR_ROADMAP.md)$' .`
  - Observed local docs and instruction files; no `CONTEXT.md`.
- `fd -a 'adr|decision|architecture' .`
  - Observed `.factory/library/architecture.md` and
    `.factory/library/architecture-hardening.md`; no `docs/adr/`.
- `wc -l *.py tests/*.py`
  - Observed large owner modules: `services.py` 6467 lines, `inbox.py` 4279
    lines, `inbox_server.py` 3940 lines, `inbox_client.py` 947 lines,
    `tools_registry.py` 851 lines, `message_sync.py` 659 lines, and
    `message_index_store.py` 616 lines.
- `rg -c '^@app\.' inbox_server.py`
  - Observed 160 FastAPI route decorators in `inbox_server.py`.
- `rg -c '^    Tool\(' tools_registry.py`
  - Observed 60 registry-defined MCP tools.
- `rg -c '^(def|class) ' services.py`
  - Observed 205 top-level functions/classes in `services.py`.
- `rg -c '^    def ' inbox_client.py`
  - Observed 103 `InboxClient` methods.
- `llm-tldr context create_app --project .`
  - Observed that app construction is coupled to lifespan setup, global route
    copying, scheduler startup, ambient services, and runtime state injection.
- `llm-tldr context _preflight_google_write --project .`
  - Observed that Google write preflight reaches from server routing into
    `google_account_resolution.py`, which then imports helpers from
    `services.py`.
- `llm-tldr context get_needs_action --project .`
  - Observed a cross-source endpoint mixing indexed threads, live Google Tasks,
    and live Calendar into one response with local exception swallowing.
- `llm-tldr imports inbox_server.py`
  - Observed broad imports from `services.py`, plus optional external
    `gemma4_hackathon` imports near the query endpoint.
- `llm-tldr imports services.py`
  - Observed provider SDK, macOS, SQLite, audio, ML, auth, and OS automation
    imports in one module.
- `llm-tldr arch .`
  - Observed no static circular dependencies, but the analyzer only found a
    root/tests directory layer because the repo is intentionally flat. It
    reported a large root graph, not meaningful bounded packages.
- `llm-tldr dead . --entry inbox_server.py inbox.py mcp_server.py inbox_mcp_readonly.py message_sync.py`
  - Observed 92 static "dead" candidates. Many are dynamic registry or test
    false positives, so this is evidence that dynamic dispatch limits static
    analysis, not proof of dead behavior.
- `rg -n 'credentials|token|secret|api_key|INBOX_|GEMINI|OPENAI|GOOGLE|GITHUB' .gitignore config pyproject.toml README.md CLAUDE.md services.py inbox_server.py mcp_server.py tools_registry.py`
  - Observed local credential/config paths and ignored token/key files.

## 4. Repo Purpose

`inbox-sym-119` is a local-first personal inbox and control-plane application.
It combines:

- A Textual TUI in `inbox.py`.
- A local FastAPI server in `inbox_server.py`.
- A Python HTTP client in `inbox_client.py`.
- MCP servers and tool registry surfaces in `mcp_server.py`,
  `inbox_mcp_readonly.py`, `inbox_mcp_stdio.py`, `tools_registry.py`, and
  `mcp_backend.py`.
- Provider and local OS integration logic in `services.py`.
- A local normalized message index in `message_index_store.py` and
  `message_sync.py`.
- Supporting local state in `memory_store.py`, `scheduler.py`,
  `ambient_notes.py`, and related modules.

The product direction in `PLAN.md` is not just "show raw inbox data." Lines
24-33 say the inbox should not default to raw provider dumps. Lines 35-62
describe a four-layer target architecture: raw sources, an operational index,
inbox views, and interfaces. That direction is partly implemented through the
message index, but raw source APIs still remain prominent across REST, TUI, and
MCP surfaces.

## 5. Entrypoints

Primary human and agent entrypoints:

- `inbox.py`
  - TUI entrypoint. The bottom of the file instantiates `InboxApp` and calls
    `app.run()`.
  - `InboxApp` begins at `inbox.py:1147`; it owns CSS, bindings, tab state,
    refresh loops, compose/reply flows, and view rendering.
  - Boot logic at `inbox.py:2082-2114` starts or connects to the local server
    through `InboxClient`.
- `dev.sh`
  - Development wrapper. Lines 1-11 set `INBOX_SERVER_PORT` default `9850` and
    execute `uv run python "${1:-inbox.py}"`.
- `scripts/run_inbox_backend.sh`
  - Backend wrapper. Lines 1-9 set `UV_CACHE_DIR` and execute
    `uv run python inbox_server.py`.
- `inbox_server.py`
  - REST server. Lines 3936-3940 run uvicorn on `INBOX_SERVER_PORT`.
  - `create_app()` at `inbox_server.py:1288-1307` constructs the FastAPI app
    and copies routes from the global app when routes already exist.
- `mcp_server.py`
  - Full MCP HTTP server. Lines 1-15 document environment defaults. Lines
    142-151 register registry tools and run uvicorn on port 8000 by default.
- `inbox_mcp_readonly.py`
  - Read-only MCP HTTP server. Lines 1-6 identify the read-only surface. Lines
    77 and 83-87 register read-only tools and run the server.
- `inbox_mcp_stdio.py`
  - Stdio MCP entrypoint. Lines 1-9 describe the local stdio transport, and
    lines 13-17 import the full MCP server object and run stdio mode.
- `message_sync.py`
  - CLI/sync entrypoint. Lines 638-659 parse `bootstrap` or `incremental` and
    run the corresponding sync flow.
- `main.py`
  - Stale placeholder. Lines 1-6 only print `Hello from inbox!`; it is not a
    meaningful product entrypoint.

## 6. Actual Architecture Map

The current architecture is a flat-module local app with these practical
ownership zones.

### UI zone

- `inbox.py` owns the TUI shell, visual state, tab state, polling, compose
  dialogs, and rendering.
- `tui_tabs.py` is a small shared tab-definition module. Lines 19-120 define
  `TABS`, including Now, Actionable, Waiting On, iMessage, Gmail, Calendar,
  Notes, Reminders, GitHub, and Drive.
- `inbox_client.py` is the UI/agent HTTP client. Lines 16-18 resolve
  `SERVER_URL` from `INBOX_SERVER_URL` or `INBOX_SERVER_PORT`. Lines 49-77
  start and health-check the local server.

Architectural note: the TUI is mostly a thin client, but not perfectly. At
`inbox.py:2082-2114`, boot logic imports `services.load_favorites` directly.
That is a boundary exception to the documented "TUI as HTTP client" model.

### REST/runtime zone

- `inbox_server.py` owns route registration, auth middleware, global runtime
  state, application lifespan, and API composition.
- Lines 212-220 define process constants such as `PORT`, `AUTH_TOKEN_ENV`, and
  `GOOGLE_SERVICE_SET`.
- Lines 794-819 define `SourceAdapters` and `ServerState`. `ServerState` holds
  Google service dictionaries, a conversation cache, event cache,
  `AmbientService`, `DictationService`, `SchedulerStore`, and
  `MessageIndexStore`.
- Lines 821-823 create global `state` and `memory_store`.
- Lines 826-834 define `InboxServerRuntime`, which is the strongest test seam
  for injecting fake state and disabling startup side effects.
- Lines 1198-1285 define `make_lifespan()`, which initializes contacts,
  authenticates Google services, optionally prewarms conversations, starts
  ambient services, starts scheduler polling, and cleans up on shutdown.
- Lines 1313-1340 define optional bearer/x-api-key auth middleware.

Architectural note: this zone is doing two different jobs. It is both the local
REST facade and the runtime container for provider services, scheduler,
ambient, memory, and index state. That makes `inbox_server.py` the highest
traffic module after `services.py`.

### Provider/service zone

- `services.py` owns most provider, local OS, auth, data-fetching, mutation,
  audio, and local ML logic. Its docstring at lines 1-4 explicitly says all
  data fetching, auth, mutation, audio, and LLM logic lives there.
- Lines 56-87 define key local paths: `credentials.json`, token files,
  iMessage database, Notes database, Reminders database directory,
  `github_token.txt`, `google_maps_key.txt`, and `gemini_api_key.txt`.
- Lines 88-98 define broad Google OAuth scopes, including Gmail read/modify/send
  and settings, Calendar, Drive, Sheets, Docs, and Tasks.
- Lines 114-120 delegate live-write protection to `inbox_test_mode`.
- Lines 194-212 implement token locking and atomic token writes.
- Lines 215-253 implement `SQLiteConnectionManager` for read-only SQLite
  connection reuse.
- Lines 276-309 implement `_run_sqlite_read()` with retries and an empty-list
  fallback on read failure.
- Lines 330-416 implement `google_auth_all()` and build six service
  dictionaries: Gmail, Calendar, Drive, Sheets, Docs, and Tasks.
- Lines 444-623 implement iMessage contacts, thread reads, and sends.
- Lines 786-1244 implement Gmail contact/thread/read/send/reply and mutations.
- Lines 2620-3095 implement Reminders read and write behavior, including
  AppleScript mutation flows.
- Lines 3101-3225 implement Google Tasks behavior.
- Lines 3246-3475 implement optional Gemini-backed summary, smart reply,
  categorization, digest, and action extraction.
- Lines 4546-4824 implement ambient/dictation availability and OS-level
  dictation behavior.
- Lines 4829 onward implement local ML model loading and extraction helpers.

Architectural note: `services.py` is a compatibility shell and a feature bucket.
It has useful stable behavior, but it is too broad to be a coherent ownership
unit. Any implementation task in this module risks accidental coupling between
provider auth, local SQLite, AppleScript, audio, ML, and API behavior.

### Data model zone

- `service_models.py` is a good stable boundary. Lines 1-2 state that it
  contains stable pure data models shared by service providers and callers.
- `Contact` at `service_models.py:11-26` includes provider routing fields such
  as `reply_to`, `thread_id`, `message_id_header`, and `gmail_account`.
- `Msg` at `service_models.py:28-37` is the normalized message shape.
- `CalendarEvent` at `service_models.py:39-53` is the normalized calendar
  shape.
- `DriveFile` at `service_models.py:102-113` includes `account`, which matters
  for multi-account routing.
- `ThreadSummary` at `service_models.py:143-153` includes `owning_account`,
  participants, labels, body snippets, and account-sensitive fields.

Architectural note: this is the clearest low-risk extraction point already in
the repo. Future service splitting should keep imports flowing through these
models rather than reintroducing provider-specific shapes at boundaries.

### Account policy zone

- `google_account_resolution.py` centralizes multi-account selection and
  write-preflight policy.
- Lines 14-21 define `GoogleMultiAccountState`, a protocol over service
  dictionaries and conversation cache.
- Lines 24-33 implement `default_google_account()`, honoring
  `INBOX_DEFAULT_GOOGLE_ACCOUNT` when configured and available.
- Lines 36-58 choose Gmail services from cache or explicit account.
- Lines 85-106 choose a Gmail service for a message or thread by explicit
  account, cached conversation metadata, existence probing, or fallback.
- Lines 109-157 choose Sheets, Drive, Tasks, Docs, and Calendar services.
- Lines 160 onward implement `preflight_google_write_payload()`.

Architectural note: this is a real policy module, but it still imports
`Contact`, `drive_get`, and `tasks_lists` from `services.py`. The policy layer
therefore depends on the broad service module instead of a narrow read-only
capability interface.

### Operational index zone

- `message_index_store.py` owns the local normalized SQLite message index.
- Lines 12-13 define the default `.inbox_index.sqlite3` path.
- Lines 69-168 initialize the schema: `sync_state`, `items`, `threads`, and
  `sender_stats`.
- Lines 185-237 upsert indexed items.
- Lines 239-356 manage sync-state progress, errors, and counts.
- Lines 407-563 rebuild thread rows by grouping items and calling
  `thread_classifier.classify_thread()`.
- Lines 565-612 list threads by actionability, source, sender, needs-reply,
  open-loop, and sort mode.
- `message_sync.py` owns index ingestion. Lines 51-82 normalize Gmail messages
  into `IndexedItem`; lines 181-269 implement Gmail bootstrap; lines 272-449
  implement Gmail incremental; lines 452-582 implement iMessage bootstrap and
  incremental; lines 602-627 orchestrate both sources and rebuild changed
  threads.

Architectural note: this is closest to the `PLAN.md` operational index target.
The main gap is that raw live endpoints and raw TUI views still sit beside the
index-backed views instead of being clearly subordinate drill-downs.

### Thread intelligence zone

- `thread_classifier.py` owns index-time heuristic classification.
- Lines 6-16 define `ThreadClassification`.
- Lines 18-47 implement `classify_thread()`.
- Lines 58-130 implement heuristic scoring and classification.
- Lines 133-150 implement open-loop detection and summary construction.
- `gmail_triage.py` owns Gmail/thread workflow triage output.
- Lines 17-31 define `GmailThreadSummaryOut`.
- Lines 44-125 define workflow keyword maps and display metadata.
- Lines 172-177 classify workflow kind.
- Lines 203-225 rank raw thread summaries.
- Lines 228-305 convert both `Contact` and indexed rows into
  `GmailThreadSummaryOut`.

Architectural note: classification currently has two centers:
`thread_classifier.py` for index rows and `gmail_triage.py` for Gmail workflow
output. They are related but not a single source of truth. Drift here affects
Now, Actionable, Waiting, Gmail triage, and MCP agent views.

### MCP/tooling zone

- `tools_registry.py` centralizes many tool definitions.
- Lines 1-12 explain that the registry drives both full and read-only MCP
  servers.
- Lines 26-45 define `Param` and `Tool`.
- Lines 52-107 build handlers and enforce confirmation for confirm-gated
  tools.
- Lines 110-119 register tools into an MCP server.
- Lines 126-851 define 60 tools. They include read tools, write tools, raw
  Sheets/Drive/Docs operations, Gmail mutations, iMessage send, Reminders,
  Tasks, scheduling, memory, and GitHub tools.
- `mcp_backend.py` is the HTTP adapter for MCP tools. Lines 9-11 define local
  URL defaults; lines 29-56 implement the shared request wrapper; lines 61-540
  expose per-endpoint methods.
- `mcp_server.py` adds non-HTTP note/memory tools and registers the full tool
  registry.
- `inbox_mcp_readonly.py` adds read-only note/memory tools and registers only
  read-only registry entries.

Architectural note: the registry is a strong shared surface, but the exposed
contract is still mostly endpoint-shaped. The roadmap asks for intent-level
tools, while the registry still has raw provider syntax such as Sheets ranges,
Drive paths, Docs document IDs, and Gmail label/filter primitives.

### Local state zone

- `scheduler.py` and `memory_store.py` own local persistent state for scheduled
  actions and memory. They are injected into server state and MCP behavior.
- `.gitignore` lines 41-43 ignore `.claude`, `.inbox_memory.sqlite3`, and
  `.inbox_scheduler.sqlite3`; line 58 ignores `.inbox_index.sqlite3`.
- `services.py` lines 56-87 define many local data and credential paths,
  including personal database paths and token/key files.

Architectural note: local state is intentionally private and local-first, but
the paths are spread across modules. New workers need a clear boundary between
tracked repo state, ignored local state, and external/personal data.

## 7. Data Flow Sketches

### TUI refresh flow

1. `inbox.py` starts or connects to the server through `InboxClient`.
2. `InboxClient` resolves `SERVER_URL` from environment defaults in
   `inbox_client.py:16-18`.
3. `InboxApp._collect_auxiliary_data()` at `inbox.py:2295-2361` fetches
   calendar, notes, reminders, GitHub, and index-backed views.
4. `InboxApp._refresh_data()` at `inbox.py:2363-2387` also fetches raw
   conversations.
5. `InboxApp._poll_data()` at `inbox.py:2389-2458` compares raw conversation
   IDs and index thread IDs.
6. Rendering mixes raw sidebars and index-backed Now/Actionable/Waiting views
   in `inbox.py:1577-1724`.

Risk: the TUI still depends on raw `/conversations` refresh even though the
product direction wants index-first views.

### Raw conversation flow

1. `/conversations` at `inbox_server.py:1396-1407` calls `_fetch_conversations()`.
2. `_fetch_conversations()` at `inbox_server.py:1363-1393` concurrently reads
   iMessage contacts and each Gmail service.
3. The endpoint clears and rebuilds `state.conv_cache`.
4. `/messages/{source}/{conv_id}` at `inbox_server.py:1413-1431` uses cache for
   Gmail account selection and falls back to the first Gmail service when cache
   is absent.
5. `/messages/send` at `inbox_server.py:1434-1450` requires the contact to
   exist in `state.conv_cache`.

Risk: conversation cache is a hidden routing contract. Sending and Gmail thread
loading depend on previous read behavior.

### Index flow

1. `message_sync.py` authenticates Gmail through `google_auth_all()` and reads
   iMessage SQLite directly.
2. It upserts normalized `IndexedItem` rows into `MessageIndexStore`.
3. `MessageIndexStore.rebuild_threads()` groups items and calls
   `thread_classifier.classify_thread()`.
4. `inbox_server.py` exposes `/index/status`, `/index/health`,
   `/index/views/{view_name}`, `/index/sync/bootstrap`, and
   `/index/sync/incremental` at lines 3805-3853.
5. `_index_view_rows()` at `inbox_server.py:2771-2807` maps Now, Actionable,
   Waiting, and recent views to store filters.
6. `inbox.py` renders index rows as synthetic messages at `inbox.py:2720-2748`.

Risk: the index exists and is useful, but it is not yet the only read contract
for high-level inbox work.

### Google write flow

1. `google_account_resolution.py` chooses default or explicit account.
2. `_preflight_google_write()` in `inbox_server.py:2906-2919` wraps policy.
3. `/preflight/google-write` at `inbox_server.py:3009-3020` exposes policy
   checks.
4. Raw write routes for Drive, Sheets, Docs, Tasks, Gmail, and Calendar are
   still exposed elsewhere in `inbox_server.py` and `tools_registry.py`.

Risk: preflight exists as a tool, but the architecture does not make it a
universal gate for all Google writes.

## 8. Stale Or Unsupported Architecture Claims

1. `README.md` says Python 3.10+ at line 32, while `pyproject.toml:5` requires
   `>=3.12,<3.15`.
2. `DOCS_INDEX.md` lines 40-45 and 136-140 mention a test claim of "736 tests"
   passing. That was not validated in this audit, and the current test tree is
   large enough that the exact count is likely stale.
3. `.factory/library/architecture.md` describes `services.py` as owning data
   models, but the current pure model boundary is `service_models.py`.
4. `.factory/library/architecture.md` describes several features as planned
   additions that now exist in code, including Reminders, GitHub, Drive, and
   multi-tab surfaces.
5. `CLAUDE.md` and `README.md` document a thin client-server shape. That is
   directionally true, but `inbox.py:2082-2114` still imports
   `services.load_favorites` directly.
6. `CONNECTOR_ROADMAP.md` lines 60-76 prefer intent-level tools, but
   `tools_registry.py:126-851` still exposes a large raw provider/API surface.
7. `PLAN.md` wants the operational index to mediate inbox views, but
   `/gmail/threads/needing-reply` at `inbox_server.py:3672-3695` still runs raw
   Gmail search and local heuristics.
8. `main.py` is a placeholder entrypoint that can mislead automation or new
   agents expecting `python main.py` to launch the app.

## 9. Risks And Shallow Boundaries

### Risk 1: `services.py` is the dominant shared dependency

Evidence:

- `services.py:1-4` explicitly places data fetching, auth, mutation, audio, and
  LLM logic in one file.
- `services.py` is 6467 lines and has 205 top-level functions/classes by local
  command observation.
- `inbox_server.py:61-200` imports a very wide function set from `services.py`.
- `message_sync.py:10-11` imports both constants/helpers and `google_auth_all()`
  from `services.py`.
- `google_account_resolution.py` imports service helpers for policy checks.

Why this matters:

- Any provider-specific change risks unrelated behavior.
- It is hard to assign ownership to one worker without hot-file conflicts.
- The module mixes pure transforms, provider calls, OS automation, auth, ML, and
  credential path ownership.

### Risk 2: REST server is both API facade and runtime container

Evidence:

- `inbox_server.py` is 3940 lines with 160 route decorators.
- `ServerState` at `inbox_server.py:794-819` holds provider services,
  conversation cache, event cache, ambient service, dictation service,
  scheduler store, and index store.
- `make_lifespan()` at `inbox_server.py:1198-1285` initializes auth, contacts,
  ambient, scheduler, and cleanup.
- `create_app()` at `inbox_server.py:1288-1307` copies routes from a global app
  into a fresh app, which is unusual and test-sensitive.

Why this matters:

- Route-only changes can accidentally affect startup, personal services, or
  tests.
- Runtime state is global by default and injected only through careful test
  setup.
- Adding another connector directly to the server will deepen the monolith.

### Risk 3: Conversation cache is an implicit write/routing contract

Evidence:

- `/conversations` clears and rebuilds `state.conv_cache` at
  `inbox_server.py:1396-1407`.
- `/messages/{source}/{conv_id}` at `inbox_server.py:1413-1431` uses the cache
  for Gmail account selection, otherwise falls back to the first Gmail service.
- `/messages/send` at `inbox_server.py:1434-1450` requires the contact to be in
  `state.conv_cache`.
- `google_account_resolution.py:85-106` also consults cached metadata when
  resolving Gmail services.

Why this matters:

- Write correctness can depend on a prior read call.
- Agents using MCP or REST directly may not know they must warm the cache.
- Multi-account routing failures can look like missing messages rather than
  policy errors.

### Risk 4: Index and triage intelligence can drift

Evidence:

- `message_index_store.py:407-563` rebuilds thread rows using
  `thread_classifier.classify_thread()`.
- `gmail_triage.py:44-125` contains separate workflow keyword and display
  metadata.
- `gmail_triage.py:228-305` converts contacts and indexed rows into
  `GmailThreadSummaryOut`.
- `inbox_server.py:3672-3695` still has a raw Gmail "needing reply" route.

Why this matters:

- Now/Actionable/Waiting can disagree with Gmail triage and agent tools.
- New classification rules may be added in one place and not the other.
- Morning review cannot reason about one authoritative thread-intelligence
  contract yet.

### Risk 5: Write policy is documented but not structurally mandatory

Evidence:

- `CONNECTOR_ROADMAP.md:32-44` defines source-of-truth policy for Google
  account ownership and default account behavior.
- `google_account_resolution.py` implements policy helpers.
- `/preflight/google-write` exists at `inbox_server.py:3009-3020`.
- Raw write endpoints and MCP tools remain exposed in `inbox_server.py` and
  `tools_registry.py`.
- `tools_registry.py:52-107` enforces confirmation, but confirmation is not the
  same as account/source preflight.

Why this matters:

- A caller can do a confirmed but badly routed write.
- Intent-level safety is optional unless every write path calls the policy.
- The repo relies on discipline rather than a hard boundary.

### Risk 6: External/local-only assumptions are easy to trip

Evidence:

- `services.py:56-87` names local credential and personal database paths.
- `.gitignore` ignores credentials, tokens, API keys, logs, and local SQLite
  state.
- `inbox_server.py:3896-3934` has an optional `/query` endpoint coupled to
  `~/projects/gemma4-hackathon`.
- `services.py:576-623` and `services.py:2804-3095` include AppleScript
  mutation flows.
- `services.py:4546-4824` includes optional audio, ambient, and OS-level
  dictation integrations.

Why this matters:

- Automation can accidentally invoke local personal state or OS automation.
- Some routes only work on the author's machine or with private adjacent repos.
- New workers need safe test-mode commands and explicit non-goals.

## 10. Strong Existing Boundaries Worth Preserving

1. `service_models.py` is the cleanest stable data model boundary.
2. `InboxServerRuntime` at `inbox_server.py:826-834` allows tests to inject
   fake state and avoid live startup behavior.
3. `MessageIndexStore` is a cohesive local persistence boundary for indexed
   message views.
4. `tools_registry.py` gives full and read-only MCP servers one shared
   definition list.
5. `google_account_resolution.py` has the right policy shape, even though it
   should depend on narrower provider interfaces.
6. `tests/conftest.py:15-35` stubs heavy ML/hardware modules, which protects
   local tests from optional runtime dependencies.
7. `tests/test_server.py:29-56` builds a fake runtime fixture, which is the
   pattern to use for route-level tests.
8. `tests/test_api_contract.py:75-88` checks that every MCP tool path maps to a
   FastAPI route, which is valuable contract protection for the registry.

## 11. Validation Map For Architecture Work

Required queue validation:

| Command | Expected status | Notes |
| --- | --- | --- |
| `git status --short` | Pass | Required by queue item. Before report writing it produced no output. After committing the report it should again be clean. |

Cheap architecture/doc validation candidates:

| Command | Expected status | Notes |
| --- | --- | --- |
| `INBOX_TEST_MODE=1 uv run pytest -m safe` | Expected pass in a synced dev env | Documented as the safe default in `docs/TESTING_FOR_AGENTS.md:10`. Avoids live/personal integration tests. |
| `INBOX_TEST_MODE=1 uv run pytest tests/test_api_contract.py -q` | Expected pass | Best small proof for MCP/REST route contract changes. |
| `INBOX_TEST_MODE=1 uv run pytest tests/test_server.py -q` | Expected pass | Best small proof for server route/runtime behavior. Uses fake runtime fixtures at `tests/test_server.py:29-56`. |
| `INBOX_TEST_MODE=1 uv run pytest tests/test_message_index_store.py tests/test_message_sync.py -q` | Expected pass for index-only refactors | Best small proof for operational index behavior. |
| `INBOX_TEST_MODE=1 uv run pytest tests/test_thread_classifier.py tests/test_message_index_store.py -q` | Expected pass for thread-intelligence work | Best small proof for classification and indexed view changes. |
| `uv run ruff check .` | Expected pass | Listed in `.factory/services.yaml` as lint command. Should be run after code changes. |
| `uv run pyright` | Unknown until dependencies are installed | Listed in `.factory/services.yaml`. Pyright is configured with `reportMissingImports = true` in `pyproject.toml:48-51`; missing optional SDKs may affect local result. |
| `uv run pytest -q` | Unknown and potentially broad | The repo contains tests for live/personal integrations. Prefer safe marker or focused tests for worker tasks. |

Validation commands intentionally not run during this audit:

- Live app startup through `uv run python inbox.py`.
- Live backend startup against personal services.
- OAuth, AppleScript, send, archive, delete, or external provider write flows.

## 12. Independently Grabbable Next Tasks

### Task 1: Extract a narrow provider adapter boundary from `services.py`

Suggested issue title:
`Extract source/provider adapter interfaces without changing behavior`

Problem:

`services.py` is the broadest shared dependency. `inbox_server.py`,
`message_sync.py`, and `google_account_resolution.py` all depend on it directly
for mixed concerns.

Suggested scope:

- Add narrow adapter/protocol modules for Gmail, iMessage, and Google account
  service lookup.
- Keep existing `services.py` function names as compatibility wrappers.
- Move no business behavior in the first slice; only create interfaces and
  wire one or two low-risk call sites.
- Do not touch AppleScript, OAuth scopes, or local ML behavior in the same
  slice.

Acceptance criteria:

- `inbox_server.py` imports adapter or protocol objects for at least Gmail
  read/thread operations instead of importing all functions directly from
  `services.py` at those call sites.
- `services.py` still exports the old functions used by existing tests.
- No route response shape changes.
- No new external service calls in tests.

Validation:

- `INBOX_TEST_MODE=1 uv run pytest tests/test_server.py tests/test_api_contract.py -q`
- `uv run ruff check .`

### Task 2: Make thread intelligence one explicit contract

Suggested issue title:
`Consolidate indexed thread classification and Gmail triage summary rules`

Problem:

`thread_classifier.py` and `gmail_triage.py` both encode thread intelligence.
They are currently adjacent but not one authoritative contract.

Suggested scope:

- Define one shared classifier or classification DTO used by both indexed
  rows and Gmail triage output.
- Keep `GmailThreadSummaryOut` as an API output type if needed.
- Move duplicated workflow keyword or priority logic behind one helper.
- Add fixtures for newsletter/noise, OTP/security, human opportunity, medical
  admin, waiting-on-me, and waiting-on-others cases.

Acceptance criteria:

- Indexed views and Gmail triage use the same classification source.
- Existing route output fields remain compatible.
- Tests prove representative cases produce consistent actionability and
  workflow classification.

Validation:

- `INBOX_TEST_MODE=1 uv run pytest tests/test_thread_classifier.py tests/test_message_index_store.py tests/test_message_sync.py -q`
- `INBOX_TEST_MODE=1 uv run pytest tests/test_server.py -q`

### Task 3: Make index-first views the explicit read contract

Suggested issue title:
`Harden Now/Actionable/Waiting as index-first views with stale-index reporting`

Problem:

The plan wants inbox views to sit over an operational index, but TUI refresh and
REST endpoints still mix index-backed and raw provider flows.

Suggested scope:

- Document and enforce that Now, Actionable, and Waiting views read from
  `MessageIndexStore`.
- Keep raw Gmail/iMessage/Calendar/Drive tabs as drill-down/source views.
- Surface index stale/error state in API and TUI without falling back silently
  to raw provider scans.
- Avoid changing sync algorithms in the same slice.

Acceptance criteria:

- Now/Actionable/Waiting rendering does not require `/conversations` to be
  called first.
- TUI displays a clear stale-index or sync-error state when index health is bad.
- Tests prove index view endpoints do not call raw provider fetches.

Validation:

- `INBOX_TEST_MODE=1 uv run pytest tests/test_api_contract.py tests/test_client.py tests/test_inbox_app.py -q`
- `INBOX_TEST_MODE=1 uv run pytest tests/test_message_index_store.py -q`

### Task 4: Enforce Google write preflight across write routes

Suggested issue title:
`Make Google write account preflight mandatory for raw and intent write APIs`

Problem:

Preflight exists but is not yet a universal structural gate for all write
surfaces.

Suggested scope:

- Inventory Google write routes in `inbox_server.py` and write tools in
  `tools_registry.py`.
- Route each write through a shared policy helper or require explicit policy
  evidence.
- Keep test mode write blocking intact through `inbox_test_mode`.
- Add tests for default account, explicit account, missing account, and
  destination mismatch.

Acceptance criteria:

- Every Google write route either calls the shared preflight helper or has a
  documented, tested reason it does not.
- MCP write tool descriptions point callers to preflight or account fields.
- Existing route shapes remain backward compatible where possible.

Validation:

- `INBOX_TEST_MODE=1 uv run pytest tests/test_server.py tests/test_gmail_actions.py tests/test_drive.py -q`
- `INBOX_TEST_MODE=1 uv run pytest tests/test_api_contract.py -q`

### Task 5: Refresh stale architecture docs without product behavior changes

Suggested issue title:
`Update architecture docs to match current entrypoints, Python version, and index architecture`

Problem:

Several local docs contradict current code or make unvalidated claims.

Suggested scope:

- Update `README.md` Python version claim to match `pyproject.toml`.
- Update `DOCS_INDEX.md` test-count claims or replace exact count with the
  validation command that produced it.
- Update `.factory/library/architecture.md` to point data models at
  `service_models.py` and mark existing features as present rather than
  planned.
- Add a short architecture map to `CLAUDE.md` or a dedicated docs file only if
  this repo wants a maintained map.

Acceptance criteria:

- Docs no longer claim Python 3.10+ when `pyproject.toml` requires 3.12+.
- Docs do not claim exact passing test counts without a command and date.
- Docs identify the current entrypoints: `inbox.py`, `inbox_server.py`,
  MCP servers, and `message_sync.py`; `main.py` is identified as placeholder or
  removed in a separate implementation task.

Validation:

- `rg -n '3\.10|736 tests|planned|service_models|main.py|inbox_server.py' README.md DOCS_INDEX.md CLAUDE.md .factory/library/architecture.md`
- `git diff --check`

## 13. Unknowns And Blockers

- No `CONTEXT.md` or `docs/adr/` exists, so architecture intent must be inferred
  from `PLAN.md`, `CONNECTOR_ROADMAP.md`, `CLAUDE.md`, and source.
- Exact current full test status is unknown. This audit intentionally did not
  run broad/live validation.
- Current production/local data shape is unknown because personal data stores
  and tokens are ignored local state.
- The optional `gemma4-hackathon` dependency behind `/query` is outside this
  repo, so this audit did not inspect it.
- The static dead-code report is noisy because registry, MCP, and Textual flows
  use dynamic dispatch; dead-code candidates need manual confirmation before
  cleanup.
- The intended fate of `main.py` is unknown. It may be harmless placeholder
  scaffolding or a stale artifact that should be removed.

## 14. Handoff Notes

Files changed by this queue item:

- `docs/overnight/inbox-sym-119-architecture-map.md`

Validation command required by queue item:

- `git status --short`

Commit and PR status:

- No PR created by this worker.
- Commit was attempted with
  `git add docs/overnight/inbox-sym-119-architecture-map.md && git commit -m "Add inbox architecture map overnight audit"`.
- Commit is blocked in this sandbox because Git cannot create the worktree
  index lock outside the writable root:
  `fatal: Unable to create '/Users/jwalinshah/projects/inbox/.git/worktrees/inbox-sym-119-architecture-map/index.lock': Operation not permitted`.

Expected final state after a human or runner with git metadata write access
commits this report:

- No product code changed.
- No generated data changed.
- No external service touched.
- `git status --short` should be clean after the report commit.
