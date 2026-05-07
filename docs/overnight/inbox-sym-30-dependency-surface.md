# inbox-sym-30 dependency surface audit

Queue item: `inbox-sym-30-dependency-surface`
Focus area: dependency-surface
Audited: 2026-05-07
Repo path: `/Users/jwalinshah/projects/agent-stack/.agent-stack-worktrees/2026-05-07-overnight-marathon/inbox-sym-30-dependency-surface`

## Summary

`inbox-sym-30` is a local-first Python inbox application: a Textual TUI and agent-facing MCP tools talk to a local FastAPI server that reads and mutates iMessage, Gmail, Google Calendar, Drive, Sheets, Docs, Tasks, Apple Notes, Apple Reminders, GitHub notifications, local ML/audio services, and local SQLite-backed state. The dependency surface is intentionally broad and very Mac-specific.

The repo has a locked `uv` environment, but running `uv` under this worker exposed a handoff risk: plain `uv tree --locked --depth 2` tried to initialize `/Users/jwalinshah/.cache/uv` and failed with `Operation not permitted`. The project launch scripts already work around this with `UV_CACHE_DIR=/tmp/uv-cache`; agent-facing validation docs do not consistently mention that override.

No product code was changed. This report is the only intended tracked output.

## Branch and dirty state

- Current branch: `codex/goal-inbox-sym-30-dependency-surface`.
- Starting HEAD: `2805b8400519da188ca7d3f6e39b19a8ca42b05a` (`2805b84 Merge pull request #34 from jwalin-shah/codex/SYM-9-indexed-defaults`).
- Starting dirty state: `git status --short --branch` printed only `## codex/goal-inbox-sym-30-dependency-surface`.
- Ignored local state observed: `git status --ignored --short` produced no output, so this worktree did not currently contain ignored token files, sqlite stores, logs, caches, or batch state.
- Runtime tool observation: `python` was not on PATH, while `python3 --version` returned `Python 3.12.8` and `UV_CACHE_DIR=/tmp/uv-cache uv tree --locked --depth 2` selected `CPython 3.12.12`.

## Repo purpose and entrypoints

Local evidence:

- `README.md` describes the app as a "privacy-first terminal UI" for iMessage, Gmail, Calendar, Sheets, Notes, Reminders, GitHub, and Drive.
- `CLAUDE.md` documents the core split: `services.py` for data access, `inbox_server.py` for FastAPI, `inbox_client.py` for the sync HTTP client, `mcp_backend.py`/`mcp_server.py` for MCP, and `inbox.py` for the Textual TUI.
- `inbox_server.py:1288-1310` constructs the FastAPI app with docs under `/api-docs`, `/api-redoc`, and `/api-openapi.json`.
- `inbox_server.py:3937-3940` runs `uvicorn` on `127.0.0.1` using `INBOX_SERVER_PORT` or default `9849`.
- `inbox_client.py:16-25` derives `INBOX_SERVER_URL` from `INBOX_SERVER_PORT` and attaches `Authorization: Bearer $INBOX_SERVER_TOKEN` if present.
- `inbox_client.py:48-75` can auto-start `inbox_server.py` as a subprocess and writes `server.log` in the repo root.
- `mcp_backend.py:18-27` wraps the private HTTP API for MCP clients and reads `INBOX_SERVER_URL` plus `INBOX_SERVER_TOKEN`.
- `mcp_gateway.py:18-45` adds public MCP auth through `INBOX_MCP_TOKEN`; an empty token disables auth.
- `mcp_gateway.py:87-94` exposes Starlette routes `/health` and `/mcp`.
- `scripts/run_inbox_backend.sh`, `scripts/run_inbox_mcp_http.sh`, `scripts/run_inbox_mcp_stdio.sh`, and their read-only variants all set `UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"` before `uv run`.
- `dev.sh` starts worktree development on `INBOX_SERVER_PORT=9850` by default, deriving `INBOX_SERVER_URL` from the chosen port.
- `batch/batch-runner.sh` is a live Gmail label mutation helper, with generated state in `batch/archive-state.tsv` and logs under `batch/logs/`.

## Declared Python dependency surface

Local evidence:

- `pyproject.toml` declares project name `inbox`, version `0.1.0`, and Python `>=3.12,<3.15`; `.python-version` says `3.12`.
- `pyproject.toml` runtime dependencies include FastAPI/Uvicorn, Google API clients, `httpx`, `loguru`, `mcp[cli]`, `mlx-lm`, `mlx-whisper`, `numpy`, `outlines`, `pydantic`, PyObjC frameworks, `python-multipart`, `rich`, `sounddevice`, and `textual`.
- `pyproject.toml` dev dependencies include `bandit`, `hypothesis`, `pre-commit`, `pyright`, `pytest`, `pytest-cov`, `python-dotenv`, and `ruff`.
- `uv.lock` contains 149 locked packages (`rg -c "^\[\[package\]\]" uv.lock` returned `149`).
- `UV_CACHE_DIR=/tmp/uv-cache uv tree --locked --depth 2` resolved successfully and showed `fastapi 0.135.3`, `mcp 1.27.0`, `mlx-lm 0.31.2`, `mlx-whisper 0.4.3`, `numpy 2.4.4`, `outlines 1.2.12`, `textual 8.2.3`, `uvicorn 0.44.0`, and dev tools including `ruff 0.15.10`, `pyright 1.1.408`, and `pytest 9.0.3`.
- Plain `uv tree --locked --depth 2` failed before dependency inspection because the sandbox could not open `/Users/jwalinshah/.cache/uv/sdists-v9/.git`.
- `.pre-commit-config.yaml` separately pins `ruff-pre-commit v0.15.10`, `pre-commit-hooks v5.0.0`, and `bandit 1.9.4`.

Dependency notes:

- Direct Starlette imports appear in `mcp_gateway.py`, `inbox_server.py`, `tests/test_api_contract.py`, and `tests/test_mcp_gateway.py`, but `starlette` is not declared as a direct dependency. It currently arrives transitively through FastAPI/MCP.
- `python-multipart` is declared and used by the FastAPI upload routes through `File`/`UploadFile`.
- `python-dotenv` is declared in the dev dependency group and also comes from `mcp[cli]`, but the application does not call `load_dotenv`; launchd/systemd examples source or load `config/inbox.env` externally.
- ML/audio dependencies are partly Python package dependencies (`mlx-lm`, `mlx-whisper`, `sounddevice`, `pyobjc`) and partly external binaries/models (`/opt/homebrew/bin/whisper-stream` and a Homebrew Cellar `whisper-cpp` model path).

## System and platform dependency surface

Local evidence:

- `README.md` and `CLAUDE.md` both state that macOS is required for iMessage, Notes, Reminders, Dictation, and platform APIs.
- `services.py:67-80` defaults iMessage to `~/Library/Messages/chat.db`, Notes to `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite`, and Reminders to `~/Library/Group Containers/group.com.apple.reminders/Container_v1/Stores`.
- `contacts.py` reads macOS AddressBook SQLite stores, documented in `README.md` and `CLAUDE.md`.
- `services.py:215-309` manages read-only SQLite connections with `file:{db_path}?mode=ro`, lock retry handling, and per-thread connection caching.
- `services.py:622`, `services.py:1937`, `services.py:2822`, and `services.py:5548` use `osascript` for iMessage, Notes, Reminders, and notification fallback paths.
- `services.py:2311`, `services.py:2326`, and `services.py:4704` import `Quartz` for keyboard and desktop integrations.
- `services.py:4525-4548` hard-codes MLX Whisper model `mlx-community/whisper-base.en-mlx`, `WHISPER_STREAM_BIN=/opt/homebrew/bin/whisper-stream`, and `WHISPER_STREAM_MODEL=/opt/homebrew/Cellar/whisper-cpp/1.8.4/share/whisper-cpp/ggml-base.en-q8_0.bin`.
- `ambient_daemon.py` documents launchd usage through `launchctl load ~/Library/LaunchAgents/com.jwalin.ambient.plist`.
- `scripts/setup_inbox_mcp.sh` installs launchd agents, writes `config/inbox.env` from the template, and loads three services with `launchctl`.
- `deploy/*.service.example` assume Linux/systemd paths under `/Users/jwalinshah/projects/inbox`, which is useful as a template but not portable as-is.
- `deploy/Caddyfile.example` exposes MCP HTTP and read-only MCP HTTP on ports `8000` and `8001`.

## Environment variables and secrets

Observed env vars from code, configs, and docs:

- `INBOX_SERVER_PORT`: private FastAPI server port, default `9849`.
- `INBOX_SERVER_URL`: client/MCP target URL, default `http://127.0.0.1:9849`.
- `INBOX_SERVER_TOKEN`: optional bearer token for the private server.
- `INBOX_MCP_TOKEN`: optional bearer token for the public MCP gateway; empty means unauthenticated.
- `INBOX_MEMORY_DB`: optional override for `MemoryStore`.
- `INBOX_TEST_MODE`, `INBOX_TEST_DATA_DIR`, `INBOX_TEST_NOW`: test-mode and deterministic test-data controls.
- `INBOX_DEFAULT_GOOGLE_ACCOUNT`: write-routing override in `google_account_resolution.py`, mentioned in `CONNECTOR_ROADMAP.md` but absent from `config/inbox.env.example`.
- `INBOX_POLL_INTERVAL`: TUI poll interval in `inbox.py`, absent from `config/inbox.env.example`.
- `INBOX_PRE_WARM_CONVERSATIONS`: optional startup conversation prewarm in `inbox_server.py`, absent from `config/inbox.env.example`.
- `INBOX_DISABLE_AMBIENT`: disables ambient autostart in `inbox_server.py`, absent from `config/inbox.env.example`.
- `INBOX_HOME_ADDRESS`: fallback origin for travel-time/departure calculations, absent from `config/inbox.env.example`.
- `INBOX_LLM_LARGE`: override for the larger MLX model, absent from `config/inbox.env.example`.
- `GEMINI_API_KEY`: env override for Gemini; fallback file is `gemini_api_key.txt`.
- `GOOGLE_CLOUD_API_KEY` and `GOOGLE_MAPS_API_KEY`: env overrides for map/travel features; fallback file is `google_maps_key.txt`.
- `UV_CACHE_DIR`: used in service launch scripts but not in agent validation docs.

Credential and local-secret files:

- `services.py:57-66` defines `credentials.json`, legacy `token.json`, and per-account `tokens/`.
- `services.py:84-86` defines `github_token.txt`, `google_maps_key.txt`, and `gemini_api_key.txt`.
- `services.py:88-98` requests broad Google scopes: Gmail read/modify/send/settings, Calendar, Drive, Sheets, Docs, and Tasks.
- `services.py:330-430` creates `tokens/`, migrates legacy `token.json`, renames token files by account email, refreshes credentials, and can run a local OAuth browser flow.
- `.gitignore` ignores `credentials.json`, `token.json`, `token.json.lock`, `tokens/`, `github_token.txt`, `google_maps_key.txt`, `gemini_api_key.txt`, `config/inbox.env`, `.env*`, `*.key`, and `*.secret`.
- `.mcp.json`, `.env.mcp.example`, `config/codex.inbox.example.toml`, and `config/gemini-settings.inbox.example.json` all model MCP client env wiring, but the Gemini example uses literal placeholder token strings rather than `${INBOX_SERVER_TOKEN}`.

## Persistent and generated local state

Local evidence:

- `memory_store.py:9-39` defaults MCP memory to `.inbox_memory.sqlite3` in the repo root unless `INBOX_MEMORY_DB` is provided.
- `message_index_store.py:12-84` defaults the message index to `.inbox_index.sqlite3` in the repo root and enables SQLite WAL.
- `scheduler.py:15-67` defaults scheduler persistence to `.inbox_scheduler.sqlite3` in the repo root.
- `ambient_notes.py:14-25` writes daily and ambient notes under `~/vault/daily` and `~/vault/ambient`.
- `services.py:5429-5480` writes notification config under `~/.config/inbox/notifications.json` unless test mode redirects it.
- `services.py:5560-5584` writes favorites under `~/.config/inbox/favorites.json` unless test mode redirects it.
- `services.py:6090-6118` writes voice config under `~/.config/inbox/voice.json` and defaults `vault_dir` to `~/vault`.
- `inbox_client.py:51-52` writes `server.log` in the repo root when auto-starting the server.
- `batch/batch-runner.sh` creates `batch/archive-state.tsv` and `batch/logs/*.log`.
- `.gitignore` ignores `.coverage`, `htmlcov/`, `*.log`, `.tldr/`, `.inbox_memory.sqlite3`, `.inbox_scheduler.sqlite3`, `.inbox_index.sqlite3`, `batch/triage-output.tsv`, `batch/archive-state.tsv`, `batch/logs/`, and `batch/.batch-state.lock`.
- `.tldrignore` also excludes common Python caches, `.pytest_cache`, `.ruff_cache`, binary artifacts, env files, and credentials.
- `.factory/` is tracked and contains service commands, skills, library notes, and validation JSON. It is not generated in this worktree; `git ls-files .factory ...` shows it is part of the repo history.

## Validation surface

Authoritative validation for this queue item:

- Required command: `git status --short`.
- Expected status after writing this report but before any commit: one untracked/added report path under `docs/overnight/`.
- Expected status if a local handoff commit is made: clean worktree.

Repo-declared validation candidates:

- `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe`
  - Expected: pass for the small safe subset. Risk: only `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py` are marked `safe`, so this does not prove most server/TUI behavior.
- `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py -q`
  - Expected: pass and prove test-mode path redirection plus live-write blocking helper behavior.
- `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .`
  - Expected: pass according to `docs/TESTING_FOR_AGENTS.md` and `.factory/services.yaml`; not run during this read-only audit.
- `UV_CACHE_DIR=/tmp/uv-cache uv run pyright`
  - Expected: pass according to `docs/TESTING_FOR_AGENTS.md` and `.factory/services.yaml`; not run during this read-only audit.
- `UV_CACHE_DIR=/tmp/uv-cache uv tree --locked --depth 2`
  - Observed: pass; useful cheap proof for lockfile and dependency resolution.
- `uv tree --locked --depth 2`
  - Observed: fail in this worker due sandbox denial on `/Users/jwalinshah/.cache/uv`; use only after setting `UV_CACHE_DIR` or granting cache access.

Testing details:

- `docs/TESTING_FOR_AGENTS.md` says default agent runs must be deterministic, local, and safe, and recommends `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, and `uv run pyright`.
- `pyproject.toml` registers markers `safe`, `integration`, `local_data`, `slow`, and `live_write`.
- `rg` found only two files with module-level `pytestmark = pytest.mark.safe`: `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py`.
- `tests/conftest.py` stubs heavy deps (`mlx_lm`, `mlx_whisper`, `sounddevice`, `outlines`, `Quartz`) when not importable, so unit tests can run without the full ML/hardware stack.
- `services.py` has `_assert_live_write_allowed`; `rg` found guard calls for representative writes including Google auth, iMessage, Gmail, Calendar, Reminders, Tasks, GitHub notifications, Drive, Sheets, Docs, desktop notifications, WhatsApp, and calendar attendees.

## Risks and stale assumptions

1. `uv` cache handling is inconsistent. Service scripts set `UV_CACHE_DIR=/tmp/uv-cache`, but docs and `.factory/services.yaml` commands omit it. This worker proved plain `uv tree --locked --depth 2` can fail before reading the lockfile.
2. `python` is absent on PATH in this worker; `python3` exists. The repo mainly uses `uv run python`, which is fine, but shell snippets or agents that call bare `python` outside `uv` may fail.
3. Several runtime env vars are implemented but not represented in `config/inbox.env.example`: `INBOX_DEFAULT_GOOGLE_ACCOUNT`, `INBOX_POLL_INTERVAL`, `INBOX_PRE_WARM_CONVERSATIONS`, `INBOX_DISABLE_AMBIENT`, `INBOX_HOME_ADDRESS`, `INBOX_LLM_LARGE`, `GEMINI_API_KEY`, `GOOGLE_CLOUD_API_KEY`, and `GOOGLE_MAPS_API_KEY`.
4. `INBOX_MCP_TOKEN` and `INBOX_SERVER_TOKEN` default to empty in code paths, which disables auth for the public MCP gateway and private API respectively. This is intentional for localhost, but dangerous if Caddy or launch configs are exposed before env is filled.
5. Starlette is imported directly but only guaranteed transitively. FastAPI/MCP currently pull it in, but dependency cleanup or package extras changes could break MCP gateway imports without a pyproject diff.
6. OAuth scope breadth is very large. One token directory unlocks Gmail read/modify/send/settings, Calendar, Drive, Sheets, Docs, and Tasks. Worktree docs explicitly mention copying `tokens/` from the primary checkout, which is convenient but easy to misuse.
7. Ambient autostart can touch microphone/model resources on server startup when voice config enables it. `INBOX_DISABLE_AMBIENT` exists, but it is not in the env template or agent testing doc.
8. Three SQLite stores default to the repo root: `.inbox_memory.sqlite3`, `.inbox_index.sqlite3`, and `.inbox_scheduler.sqlite3`. Only memory has an env override observed in code; scheduler and index are harder to isolate per worktree.
9. Homebrew whisper paths are hard-coded to one installed `whisper-cpp` version. A brew upgrade can silently make dictation unavailable even if Python dependencies are valid.
10. `.factory/init.sh` and `.factory/services.yaml` target `/Users/jwalinshah/projects/inbox` and port `9849`, not this isolated worktree. They are useful portfolio artifacts but unsafe as generic worker commands without path/port review.
11. `batch/batch-runner.sh` performs live Gmail label mutations and maintains a TSV state file while allowing parallel workers. It should be treated as live-write infrastructure, not a validation helper.
12. Launchd and systemd examples have absolute paths under `/Users/jwalinshah/projects/inbox`. They are local templates rather than portable deployment manifests.

## Decisions from this audit

- Treat `UV_CACHE_DIR=/tmp/uv-cache` as part of the reliable local command contract for sandboxed workers.
- Treat `git status --short` as the only validation command required by this queue item; broader pytest/lint/typecheck candidates are documented rather than executed here.
- Treat hidden tracked `.factory/` content as part of the repo dependency surface because it contains commands, validation evidence, and service assumptions.
- Treat all MCP HTTP exposure as auth-sensitive because empty `INBOX_MCP_TOKEN` means the public middleware permits requests.
- Treat local personal-data stores and OAuth files as external dependencies, not fixtures. Safe agent work should use `INBOX_TEST_MODE=1` and `INBOX_TEST_DATA_DIR`.

## Next safe work

1. Normalize agent-safe command docs around `UV_CACHE_DIR`.
   - Acceptance criteria: `docs/TESTING_FOR_AGENTS.md`, `.factory/services.yaml`, and relevant setup docs show `UV_CACHE_DIR=/tmp/uv-cache` for `uv` commands intended for sandboxed workers.
   - Validation: `UV_CACHE_DIR=/tmp/uv-cache uv tree --locked --depth 2`; `git diff -- docs/TESTING_FOR_AGENTS.md .factory/services.yaml`.

2. Build a complete env-var inventory and update templates.
   - Acceptance criteria: `config/inbox.env.example` documents every runtime env var observed in code, with safe defaults and notes for live-write/external-service vars; docs distinguish localhost-only empty tokens from exposed MCP/server deployments.
   - Validation: `rg -n "INBOX_|GEMINI_API_KEY|GOOGLE_.*API_KEY|UV_CACHE_DIR" .`; `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py -q`.

3. Make direct dependency imports explicit.
   - Acceptance criteria: either add `starlette` as a declared direct dependency or remove direct Starlette imports from first-party modules/tests; `uv.lock` remains in sync.
   - Validation: `UV_CACHE_DIR=/tmp/uv-cache uv tree --locked --depth 2`; `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_mcp_gateway.py -q`.

4. Add path overrides for local stores that currently default to repo root or home.
   - Acceptance criteria: index, scheduler, server log, and vault paths have explicit env/config overrides comparable to `INBOX_MEMORY_DB`; tests prove test-mode or env redirection avoids primary data stores.
   - Validation: `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py tests/test_message_index_store.py tests/test_memory_store.py -q`.

5. Add a live-write safety pass for batch and setup scripts.
   - Acceptance criteria: `batch/batch-runner.sh` clearly requires an explicit live-write flag or defaults to dry run, and `scripts/setup_inbox_mcp.sh` documents/guards launchd writes; parallel state updates use a lock or are single-writer.
   - Validation: `bash -n batch/batch-runner.sh scripts/setup_inbox_mcp.sh`; dry-run invocation against a temp copy of `batch/archive-input.tsv` does not call the live server.

## Non-goals

- No product code changes.
- No credential reads, token validation, OAuth flows, or external service calls.
- No server startup, MCP exposure, Caddy launch, launchd/systemd install, or deploy.
- No live Gmail, Calendar, Drive, Docs, Sheets, Tasks, GitHub, Reminders, Notes, iMessage, WhatsApp, notification, audio, or keyboard-injection writes.
- No PR creation or external tracker updates.
- No attempt to prove README feature claims beyond local dependency-surface evidence.

## Unknowns

- Whether the primary checkout at `/Users/jwalinshah/projects/inbox` currently has live tokens, service state, or a running server.
- Whether `credentials.json`, `tokens/`, `github_token.txt`, `google_maps_key.txt`, or `gemini_api_key.txt` exist in the primary checkout; they were not present in this clean worktree and were intentionally not inspected elsewhere.
- Whether Homebrew currently has the exact `whisper-cpp` model path referenced by `services.py`.
- Whether MLX model caches are already populated; first use may download or compile/cache outside the repo.
- Whether full `uv run pytest`, `uv run pyright`, and `uv run ruff check .` are green on this branch; this queue item only required `git status --short`.
- Whether `.factory/validation/*` reports are current relative to HEAD `2805b84`; they are tracked artifacts but not independently revalidated here.
