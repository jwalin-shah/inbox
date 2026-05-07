# Overnight Architecture Map: inbox-sym-30

Queue item: `inbox-sym-30-architecture-map`
Branch: `codex/goal-inbox-sym-30-architecture-map`
Repo/worktree: `/Users/jwalinshah/projects/agent-stack/.agent-stack-worktrees/2026-05-07-overnight-marathon/inbox-sym-30-architecture-map`
HEAD at audit start: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`

## Scope Decision

This audit stayed docs-only. I did not edit product code, run live services, call external APIs, start the TUI, expose MCP, mutate personal data stores, or create a PR.

The only intended artifact is this report.

## Commands Run

Discovery and state:

```bash
pwd
git status --short
git branch --show-current
git rev-parse HEAD
git ls-files | wc -l
du -sh . 2>/dev/null
llm-tldr tree .
llm-tldr structure .
llm-tldr arch .
wc -l *.py tests/*.py docs/*.md *.md pyproject.toml
```

Project instructions and docs:

```bash
rtk read AGENTS.md
rtk read CLAUDE.md
rtk read README.md
rtk read pyproject.toml
rtk read DOCS_INDEX.md
rtk read MCP_V1_PLAN.md
rtk read MCP_SETUP.md
rtk read PLAN.md
rtk read docs/TESTING_FOR_AGENTS.md
rtk read .gitignore
rtk read .env.mcp.example
rtk read config/inbox.env.example
rtk read config/codex.inbox.example.toml
rtk read deploy/Caddyfile.example
```

Architecture tracing:

```bash
llm-tldr search "FastAPI|APIRouter|@app|uvicorn|if __name__|Textual|class .*App|MCP|FastMCP" .
llm-tldr context create_app --project . --depth 2
llm-tldr context InboxApp --project . --depth 1
llm-tldr context InboxBackend --project . --depth 2
rg "^(class|def|async def) " -n --glob "*.py"
rg "^(import|from) " -n --glob "*.py"
rg "^@app\.(get|post|put|delete|patch)" -n inbox_server.py
rg "self\._client\.(get|post|put|delete|patch)\(" -n inbox_client.py
rg "from services import|import services|agents\.runner|from agents" -n . --glob "*.py"
rg "_assert_live_write_allowed" -n services.py tests
rg "create_app\(|InboxServerRuntime|TestClient\(|lifespan" -n tests inbox_server.py
rg "class SourceAdapters|source_adapters|def _source_adapter|ProductionSource" -n inbox_server.py tests/test_server.py
rg "pytest\.mark\.safe|@pytest.mark.safe|mark\.safe" -n tests
rg "pytestmark|mark\.local_data|mark\.live_write|mark\.slow|mark\.integration" -n tests
rg --files | rg "^agents/"
```

Representative file slices were read with `nl -ba ... | sed -n ...` for:

- `inbox_server.py`
- `services.py`
- `inbox.py`
- `inbox_client.py`
- `mcp_backend.py`
- `mcp_gateway.py`
- `mcp_server.py`
- `inbox_mcp_readonly.py`
- `inbox_mcp_stdio.py`
- `inbox_mcp_readonly_stdio.py`
- `tools_registry.py`
- `message_index_store.py`
- `message_sync.py`
- `scheduler.py`
- `google_account_resolution.py`
- `memory_store.py`
- `service_models.py`
- `tui_tabs.py`
- `tests/conftest.py`
- `tests/test_api_contract.py`

## Observed Dirty State

Before writing this report, `git status --short` returned no output.

After writing this report, the expected dirty state is this docs-only artifact:

```text
?? docs/overnight/
```

## Current Architecture

The repo is a flat Python application rather than a package tree. `llm-tldr tree .` found 196 tracked files in a small worktree, with core app modules at repo root and tests under `tests/`.

The large modules are the real architectural owners:

- `services.py`: 6,467 lines
- `inbox.py`: 4,279 lines
- `inbox_server.py`: 3,940 lines
- `inbox_client.py`: 947 lines
- `tools_registry.py`: 851 lines
- `message_sync.py`: 659 lines
- `message_index_store.py`: 616 lines
- `mcp_backend.py`: 541 lines
- `scheduler.py`: 437 lines

The intended product stack is visible in `PLAN.md`: raw sources, a local SQLite operational index, indexed inbox views, and interfaces through Textual, FastAPI, and a curated MCP surface. The current code partially matches that direction.

### Layer 1: Shared Models

`service_models.py` is the cleanest shared contract. It defines dataclasses for source-agnostic records like `Contact`, `Msg`, `CalendarEvent`, `Reminder`, `GoogleTask`, `DriveFile`, `Spreadsheet`, `Document`, and `ThreadSummary` (`service_models.py:11`, `service_models.py:28`, `service_models.py:39`, `service_models.py:65`, `service_models.py:78`, `service_models.py:90`, `service_models.py:102`, `service_models.py:124`, `service_models.py:133`, `service_models.py:142`).

This file is small, pure, and stable compared with the rest of the system.

### Layer 2: Source and Capability Implementations

`services.py` declares itself as the data access layer where all fetching, auth, mutation, audio, and LLM logic lives (`services.py:1`). That is accurate. It owns:

- local paths and credential files (`services.py:54`)
- Google OAuth scopes (`services.py:88`)
- iMessage read/send (`services.py:441`)
- Gmail read/write/search (`services.py:626`, `services.py:995`)
- Calendar operations (`services.py:1472`)
- Apple Notes (`services.py:1869`)
- WhatsApp macOS Accessibility integration (`services.py:2021`)
- Apple Reminders (`services.py:2617`)
- Google Tasks (`services.py:3098`)
- Gemini AI (`services.py:3243`)
- Google Maps/departure times (`services.py:3507`)
- GitHub notifications (`services.py:3659`)
- Drive, Sheets, Docs (`services.py:3805`, `services.py:4023`, `services.py:4391`)
- audio, ambient, dictation, local LLM, autocomplete, global search, notifications, favorites, contacts, and voice commands (`services.py:4523`, `services.py:4580`, `services.py:4699`, `services.py:4827`, `services.py:5028`, `services.py:5427`, `services.py:5558`, `services.py:6088`)

This gives the repo a simple ownership model, but it also means most domain coupling accumulates in one file. The module has many unrelated reasons to change: OAuth scope changes, SQLite parsing, Gmail batching, AppleScript mutation, WhatsApp UI automation, ML loading, Drive/Sheets/Docs APIs, and desktop notification behavior.

### Layer 3: Account Resolution and Source Adapters

`google_account_resolution.py` extracts multi-account routing out of the server. It defines a state protocol over service dictionaries and `conv_cache` (`google_account_resolution.py:14`) and centralizes Gmail, Sheets, Drive, Tasks, Docs, and Calendar default-account resolution (`google_account_resolution.py:36`, `google_account_resolution.py:109`, `google_account_resolution.py:119`, `google_account_resolution.py:129`, `google_account_resolution.py:139`, `google_account_resolution.py:149`).

`inbox_server.py` has a narrower `SourceAdapters` mechanism, but only Gmail search and calendar event reads use it (`inbox_server.py:750`, `inbox_server.py:776`, `inbox_server.py:795`). Tests verify that fake adapters can be installed and production adapters delegate to service functions (`tests/test_server.py:1021`, `tests/test_server.py:1071`, `tests/test_server.py:1089`).

The account-resolution extraction is more complete than the source-adapter extraction. Source adapters are currently a testing convenience, not the general integration boundary.

### Layer 4: FastAPI Runtime and API Surface

`inbox_server.py` is the central process boundary. It imports a broad set of functions and dataclasses from `services.py` (`inbox_server.py:61`) and exposes a large route surface. `rg "^@app\."` found routes from `/health` (`inbox_server.py:1346`) through `/query` (`inbox_server.py:3896`), including conversations/messages, Gmail, Calendar, Notes, Reminders, Tasks, Scheduler, AI, WhatsApp, GitHub, Drive, Sheets, Docs, search, ambient/dictation, contacts, notifications, workflow helpers, index sync, and cross-silo query.

Runtime state is centralized in `ServerState`, which holds service maps, caches, ambient/dictation services, `SchedulerStore`, `MessageIndexStore`, and source adapters (`inbox_server.py:802`). The module also exposes global `state` and `memory_store` (`inbox_server.py:821`).

Tests can inject a runtime via `InboxServerRuntime` (`inbox_server.py:826`) and `create_app(runtime)` (`inbox_server.py:1288`). The app factory copies routes from the global `app` into each new app (`inbox_server.py:1297`). That keeps tests practical, but it also means routes are still authored against module-global decorators and global state.

The lifecycle initializes contacts, authenticates all Google accounts, optionally prewarms conversations, optionally starts ambient listening, and optionally starts a scheduler loop (`inbox_server.py:1198`). This makes server startup a heavy ownership boundary: auth, data source setup, ML/audio, and background jobs all meet there.

### Layer 5: HTTP Client and TUI

`inbox_client.py` is a synchronous HTTP client. It derives its base URL from `INBOX_SERVER_URL` or `INBOX_SERVER_PORT` (`inbox_client.py:16`), attaches `INBOX_SERVER_TOKEN` as a bearer token (`inbox_client.py:21`), and can auto-start `inbox_server.py` with the current Python executable (`inbox_client.py:48`).

`inbox.py` declares itself as a thin HTTP client that auto-starts the server (`inbox.py:1`). That is mostly true: `InboxApp.boot()` loads favorites, calls `self.client.ensure_server()`, then refreshes and starts polling (`inbox.py:2082`). Refreshes collect conversations, calendar, notes, reminders, GitHub notifications, and indexed views through `InboxClient` (`inbox.py:2295`, `inbox.py:2363`, `inbox.py:2389`).

The TUI still leaks through the HTTP boundary in a few places:

- It directly imports `services.llm_is_loaded` for command palette behavior (`inbox.py:1957`).
- It directly imports `services.load_favorites` on boot (`inbox.py:2090`).
- It directly imports `services.save_favorites` when toggling favorites (`inbox.py:4060`).
- It imports `agents.runner.Supervisor` for the local assistant action (`inbox.py:4131`), but no tracked `agents/` package exists in this worktree.

Those are the main places where the "thin client" boundary is porous.

### Layer 6: Operational Index

`message_index_store.py` owns the local `.inbox_index.sqlite3` schema (`message_index_store.py:12`). It creates `sync_state`, `items`, `threads`, and `sender_stats` tables with indexes (`message_index_store.py:80`). `message_sync.py` owns Gmail and iMessage bootstrap/incremental sync into that store (`message_sync.py:181`, `message_sync.py:422`, `message_sync.py:498`, `message_sync.py:541`).

The API exposes index endpoints for threads, status, health, named views, bootstrap sync, and incremental sync (`inbox_server.py:3805`, `inbox_server.py:3820`, `inbox_server.py:3829`, `inbox_server.py:3834`, `inbox_server.py:3844`, `inbox_server.py:3850`).

This layer matches the roadmap in `PLAN.md`, and tests cover many of the intended guarantees. `tests/test_api_contract.py` verifies client/server shape for index status and health (`tests/test_api_contract.py:91`, `tests/test_api_contract.py:109`).

### Layer 7: MCP Surfaces

The MCP architecture has three layers:

- `mcp_backend.py` is an async HTTP adapter to the private FastAPI server. It reads `INBOX_SERVER_URL`, `INBOX_SERVER_TOKEN`, and defaults to `http://127.0.0.1:9849` (`mcp_backend.py:9`). All calls flow through `_request()` (`mcp_backend.py:29`).
- `mcp_gateway.py` builds the Starlette public app, health endpoint, memory store, and bearer-token middleware for `INBOX_MCP_TOKEN` (`mcp_gateway.py:18`, `mcp_gateway.py:48`, `mcp_gateway.py:87`).
- `mcp_server.py`, `inbox_mcp_readonly.py`, `inbox_mcp_stdio.py`, and `inbox_mcp_readonly_stdio.py` choose full vs read-only and HTTP vs stdio transport (`mcp_server.py:34`, `mcp_server.py:142`, `mcp_server.py:145`, `inbox_mcp_readonly.py:30`, `inbox_mcp_readonly.py:77`, `inbox_mcp_stdio.py:16`, `inbox_mcp_readonly_stdio.py:10`).

`tools_registry.py` is the strongest anti-drift mechanism in the MCP layer. It says one table drives full and read-only servers (`tools_registry.py:1`) and dynamically creates FastMCP handlers from `Tool` definitions (`tools_registry.py:52`, `tools_registry.py:110`). Mutating tools can require a `confirm` parameter (`tools_registry.py:55`, `tools_registry.py:73`).

There is explicit contract coverage: `tests/test_api_contract.py` checks that every MCP registry path maps to a FastAPI route (`tests/test_api_contract.py:75`), and `tests/test_tools_registry.py` checks confirmation gating and readonly registration behavior.

## Entrypoints

Main local entrypoints:

- `uv run python inbox.py`: Textual TUI; calls `InboxClient.ensure_server()` (`inbox.py:4277`, `inbox.py:2082`, `inbox_client.py:60`).
- `uv run python inbox_server.py`: FastAPI backend on `127.0.0.1`, port from `INBOX_SERVER_PORT` or 9849 (`inbox_server.py:3936`).
- `uv run python mcp_server.py`: full HTTP MCP gateway on `127.0.0.1:8000` (`mcp_server.py:148`).
- `uv run python inbox_mcp_readonly.py`: read-only HTTP MCP gateway on `127.0.0.1:8001` by default (`inbox_mcp_readonly.py:83`).
- `uv run python inbox_mcp_stdio.py`: full local stdio MCP (`inbox_mcp_stdio.py:16`).
- `uv run python inbox_mcp_readonly_stdio.py`: read-only local stdio MCP (`inbox_mcp_readonly_stdio.py:10`).
- `uv run python message_sync.py`: index bootstrap/incremental CLI (`message_sync.py:638`).
- `uv run python ambient_daemon.py`: ambient audio daemon (`ambient_daemon.py:91`).
- `./dev.sh`: worktree launcher that defaults to port 9850 (`dev.sh:1`).
- `scripts/run_inbox_backend.sh` and MCP runner scripts: service-friendly wrappers that set `UV_CACHE_DIR` and run the relevant Python entrypoint.

## Ownership Map

Current practical owners by file:

| Area | Files | Notes |
| --- | --- | --- |
| Provider APIs and local integrations | `services.py`, `contacts.py`, `ambient_notes.py` | `services.py` owns almost every provider-specific implementation. |
| API runtime | `inbox_server.py`, `google_account_resolution.py` | API owns global state, lifecycle, auth middleware, route models, and route handlers. |
| Human UI | `inbox.py`, `tui_tabs.py`, `command_palette.py` | UI is mostly HTTP-backed but has direct service imports for favorites/LLM status and a missing assistant import. |
| HTTP client | `inbox_client.py` | Synchronous client for TUI and scripts. |
| MCP | `mcp_backend.py`, `mcp_gateway.py`, `mcp_server.py`, `inbox_mcp_readonly.py`, stdio wrappers, `tools_registry.py` | Best defined external boundary, with confirmation-gated writes. |
| Operational index | `message_index_store.py`, `message_sync.py`, `thread_classifier.py`, `gmail_triage.py` | Close to the roadmap; still top-level rather than packaged. |
| Local persistence | `memory_store.py`, `scheduler.py`, `.inbox_*.sqlite3` | SQLite stores live at repo root by default and are gitignored. |
| Deployment/config | `scripts/`, `deploy/`, `config/`, `.env.mcp.example` | Config examples are present; real tokens are ignored. |
| Validation | `tests/`, `docs/TESTING_FOR_AGENTS.md`, `pyproject.toml` | Broad suite exists, but safe marker coverage is small. |

## Boundary Risks and Stale Assumptions

1. `services.py` is the main architecture bottleneck.

Evidence: it is 6,467 lines and owns unrelated domains from Gmail to WhatsApp, ML, Drive, Docs, Sheets, local SQLite, AppleScript, and notifications. Adding a new provider or changing a policy can touch the same file as unrelated audio or LLM code.

Safe next direction: extract by stable domain seams only when making real changes. Start with the already coherent clusters: Google Workspace, Apple local stores, audio/LLM, and search/triage. Avoid a broad mechanical split without behavior tests.

2. `inbox_server.py` is both router and application composition root.

Evidence: route decorators are global (`inbox_server.py:1310` onward), `create_app()` copies existing global routes into a new app (`inbox_server.py:1297`), and `ServerState` initializes every major runtime service (`inbox_server.py:802`). This is workable but makes it hard to reason about route ownership and startup side effects.

Safe next direction: for new API groups, prefer routers or small registration functions before adding more global route blocks. Existing routes do not need to move all at once.

3. The TUI is not fully thin.

Evidence: `inbox.py` calls the HTTP client for most work, but imports `services.llm_is_loaded`, `services.load_favorites`, and `services.save_favorites` directly (`inbox.py:1957`, `inbox.py:2090`, `inbox.py:4060`). It also imports `agents.runner.Supervisor` at runtime (`inbox.py:4131`) while `rg --files | rg "^agents/"` returned no tracked `agents/` files.

Safe next direction: either route favorites and LLM status through existing API endpoints consistently, or document these as intentional local-only UI affordances. The assistant action should be guarded by an importability test or moved behind an optional plugin boundary.

4. Source adapters are partial.

Evidence: `SourceAdapters` covers Gmail search and Calendar event reads only (`inbox_server.py:795`). Most other provider calls still go straight from route handlers to `services.py`.

Safe next direction: do not rename this to a general adapter layer until it actually covers more integrations. If the next work targets testability of a provider, extend `SourceAdapters` one provider at a time.

5. Roadmap and implementation have diverged around memory and agent platform scope.

Evidence: `PLAN.md` says this phase does not solve full personal memory or a general-purpose personal agent platform. The repo now has `memory_store.py`, MCP memory tools in `mcp_server.py`, a `/memory/extract` endpoint in `inbox_server.py:3621`, and a TUI assistant action that expects `agents.runner.Supervisor`.

Safe next direction: update `PLAN.md` or split "inbox operational index" from "personal assistant memory" explicitly so future agents do not treat these as accidental scope creep or as mandatory Phase 1 surface.

6. Runtime docs have at least one stale environment claim.

Evidence: `README.md` says Python 3.10+ is required, while `pyproject.toml` requires `>=3.12,<3.15` (`pyproject.toml:5`).

Safe next direction: correct the README requirement to match packaging before any onboarding or CI work.

7. MCP V1 plan is behind the current tool surface.

Evidence: `MCP_V1_PLAN.md` lists a narrow v1 and says Calendar stays on the built-in ChatGPT connector for now. `tools_registry.py` now includes tools beyond that v1, including Sheets, Tasks, Maps/departure, scheduled messages, followups, Drive, Docs, GitHub, and memory extraction paths.

Safe next direction: mark `MCP_V1_PLAN.md` historical or replace it with the current source-of-truth rule: `tools_registry.py` plus `tests/test_api_contract.py`.

8. Safe validation policy exists, but marker coverage is not yet broad.

Evidence: `docs/TESTING_FOR_AGENTS.md` says default agent verification should be `INBOX_TEST_MODE=1 uv run pytest -m safe`, `ruff`, and `pyright`. Only `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py` currently set `pytestmark = pytest.mark.safe`.

Safe next direction: classify more deterministic tests with `safe`, or change the recommended safe command to focused tests that actually cover the touched area.

9. Optional external project dependency is embedded in the main server surface.

Evidence: `/query` imports `gemma4_hackathon` from an external editable path and returns 503 when unavailable (`inbox_server.py:3896`). This is gracefully handled, but the endpoint lives in the main API module and adds another reason for server route churn.

Safe next direction: keep optional hackathon/cross-silo routes isolated behind their own route registration or explicit experimental section.

## Existing Guardrails

The repo already has useful guardrails:

- `.gitignore` excludes credentials, token files, env files, server logs, `.inbox_memory.sqlite3`, `.inbox_scheduler.sqlite3`, and `.inbox_index.sqlite3`.
- `inbox_test_mode.py` blocks live writes when `INBOX_TEST_MODE` is enabled (`inbox_test_mode.py:22`), and `services.py` calls `_assert_live_write_allowed()` across many write operations (`services.py:114`).
- `tests/conftest.py` stubs heavy ML/hardware modules (`tests/conftest.py:15`).
- `tests/test_api_contract.py` catches MCP registry route drift (`tests/test_api_contract.py:75`).
- `tests/test_tools_registry.py` catches MCP confirmation-gating drift.
- `InboxServerRuntime` lets tests skip scheduler and ambient startup (`inbox_server.py:826`).
- `MCP_SETUP.md` clearly separates private backend token auth from public MCP token auth.

## Missing Validation

I did not run the full test suite, linter, type checker, server, TUI, or MCP gateways because this queue item only asked for an architecture-map report and the required validation command is `git status --short`.

Additional validation worth running before code changes in this repo:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe
uv run ruff check .
uv run pyright
```

For route/MCP boundary changes, the cheapest focused tests are:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_api_contract.py tests/test_tools_registry.py tests/test_mcp_gateway.py -q
```

For index changes:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_message_index_store.py tests/test_message_sync.py tests/test_server.py -q
```

## Next Safe Work

1. Make the thin-client boundary explicit.

Acceptance criteria:

- Decide whether favorites and LLM status are allowed direct TUI service calls.
- If not, add API/client methods and move the TUI to `InboxClient`.
- Add a focused regression test around the changed TUI path.

Validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_app.py tests/test_client.py tests/test_server.py -q
uv run ruff check .
```

2. Stabilize the optional local assistant action.

Acceptance criteria:

- Either add the missing `agents.runner` package, remove the TUI action, or feature-gate it with a clear unavailable state.
- Document where the assistant control-plane code lives.
- Add a test that the command palette action fails gracefully when the optional dependency is missing.

Validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_command_palette.py tests/test_inbox_app.py -q
uv run ruff check .
```

3. Reconcile docs with current runtime boundaries.

Acceptance criteria:

- README Python version matches `pyproject.toml`.
- `MCP_V1_PLAN.md` is marked historical or updated to point to `tools_registry.py`.
- `PLAN.md` explains how `memory_store.py`, `/memory/extract`, and MCP memory tools relate to Phase 1.
- `docs/TESTING_FOR_AGENTS.md` safe command matches actual marker coverage or marker coverage is broadened.

Validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py tests/test_api_contract.py tests/test_tools_registry.py -q
uv run ruff check .
```

4. Prepare a future services split only around tested seams.

Acceptance criteria:

- Choose one domain cluster, such as Google Workspace or Apple local stores.
- Move only that cluster behind a small module while preserving public imports or updating callers deliberately.
- Add/keep focused tests for the moved cluster.

Validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_services.py tests/test_gmail_actions.py tests/test_drive.py tests/test_calendar.py -q
uv run ruff check .
uv run pyright
```

## Final Validation

Required command:

```bash
git status --short
```

Result: command completed successfully and reported only this required docs-only artifact:

```text
?? docs/overnight/
```
