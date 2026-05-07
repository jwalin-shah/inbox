# inbox-sym-115 dependency-surface audit

Date: 2026-05-07
Queue item: `inbox-sym-115-dependency-surface`
Repo: `inbox-sym-115`
Branch observed: `codex/goal-inbox-sym-115-dependency-surface`
Starting HEAD observed: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`

## Scope and non-goals

This is a read-only dependency-surface audit except for this report file. I did
not touch product code, generated data, secrets, local service files, deploy
targets, external services, GitHub PRs, or external trackers. I did not run
setup scripts, start servers, load launch agents, expose MCP endpoints, execute
live inbox operations, or run tests that would touch personal data.

The required validation for this queue item is `git status --short`. Other
commands below are evidence-gathering commands or candidate validation commands.

## Repo purpose

Inbox is a local-first Python personal inbox/control-plane app. The main shape
is a Textual/Rich TUI backed by a local FastAPI server; agents can also reach
the same backend through MCP stdio or HTTP gateways. The app integrates local
macOS data stores, Google APIs, GitHub, local ML/audio, scheduling, memory, and
batch inbox operations.

Evidence:

- [README.md](../../README.md) describes the unified TUI, FastAPI backend,
  local ML, macOS data sources, OAuth token files, and dev commands.
- [CLAUDE.md](../../CLAUDE.md) gives the strongest current architecture map:
  `services.py` as data layer, `inbox_server.py` as FastAPI wrapper,
  `inbox_client.py` as HTTP client, MCP entrypoints, scheduler, and local state.
- [docs/TESTING_FOR_AGENTS.md](../TESTING_FOR_AGENTS.md) explicitly treats the
  repo as personal-data-sensitive and requires `INBOX_TEST_MODE=1` for
  agent-safe tests.

## Current branch and dirty state

Observed before writing this report:

- `git branch --show-current` -> `codex/goal-inbox-sym-115-dependency-surface`
- `git rev-parse HEAD` -> `2805b8400519da188ca7d3f6e39b19a8ca42b05a`
- `git status --short` -> clean output
- `git status --ignored --short` -> clean output
- `git remote -v` -> `origin https://github.com/jwalin-shah/inbox.git`
- `git ls-files docs/overnight` -> no existing overnight reports tracked before
  this file

Expected dirty state after this audit: only
`docs/overnight/inbox-sym-115-dependency-surface.md`.

## Dependency and runtime surface

### Python and uv

- [pyproject.toml](../../pyproject.toml) declares package `inbox`, version
  `0.1.0`, Python `>=3.12,<3.15`, runtime deps, dev deps, Ruff, Pyright, Pytest,
  and Bandit settings.
- [.python-version](../../.python-version) is `3.12`.
- [README.md](../../README.md) still says "Python 3.10+" while the manifest
  requires Python 3.12+. That is a stale setup claim.
- [uv.lock](../../uv.lock) is present and is about 432K.
- `UV_CACHE_DIR=/tmp/uv-cache uv tree --locked` succeeded, used CPython
  3.12.12, and resolved 149 packages.
- `uv tree --locked` without `UV_CACHE_DIR` failed in this sandbox because uv
  tried to initialize `/Users/jwalinshah/.cache/uv` and hit an operation-not-
  permitted error. Local worker validation should set `UV_CACHE_DIR=/tmp/uv-cache`
  in this environment.

### Runtime deps from manifest and lock

Main declared runtime dependencies in [pyproject.toml](../../pyproject.toml):

- Web/API: `fastapi`, `uvicorn`, `httpx`, `python-multipart`, `pydantic`
- Google: `google-api-python-client`, `google-auth-oauthlib`,
  `google-generativeai`
- MCP: `mcp[cli]`
- TUI: `textual`, `rich`
- ML/audio: `mlx-lm`, `mlx-whisper`, `numpy`, `outlines`, `sounddevice`
- macOS input/accessibility: `pyobjc-framework-applicationservices`,
  `pyobjc-framework-Quartz`
- Logging: `loguru`

`UV_CACHE_DIR=/tmp/uv-cache uv tree --locked` showed notable resolved versions:

- `fastapi==0.135.3`, `starlette==1.0.0`, `uvicorn==0.44.0`
- `mcp==1.27.0`
- `textual==8.2.3`, `rich==14.3.3`
- `google-api-python-client==2.194.0`, `google-auth==2.49.1`,
  `google-generativeai==0.8.6`
- `mlx-lm==0.31.2`, `mlx-whisper==0.4.3`, `mlx==0.31.1`, `torch==2.11.0`,
  `numpy==2.4.4`
- `pyobjc-framework-applicationservices==12.1`,
  `pyobjc-framework-quartz==12.1`
- Dev group: `pytest==9.0.3`, `pytest-cov==7.1.0`, `ruff==0.15.10`,
  `pyright==1.1.408`, `bandit==1.9.4`, `pre-commit==4.5.1`

### Direct imports that rely on transitive deps

These are small but real packaging risks:

- [services.py](../../services.py) imports `requests` inside
  `gmail_unsubscribe`, but `requests` is not a direct dependency in
  [pyproject.toml](../../pyproject.toml). It is currently available transitively
  through Google packages in [uv.lock](../../uv.lock).
- [mcp_gateway.py](../../mcp_gateway.py) imports Starlette objects directly
  (`Starlette`, middleware, requests, responses, routing), and tests import
  Starlette directly too. `starlette` is currently transitive through FastAPI
  and MCP, not direct.
- [inbox_server.py](../../inbox_server.py) also imports `starlette.responses`
  in one route path.

If a future dependency update removes those transitives, runtime import failures
will be surprising because the source imports them directly.

## Entrypoints, scripts, and service wrappers

Primary Python entrypoints observed:

- [inbox.py](../../inbox.py): Textual TUI. Reads `INBOX_POLL_INTERVAL`, launches
  server through [inbox_client.py](../../inbox_client.py), opens downloads under
  `~/Downloads`, and uses subprocesses for some UI actions.
- [inbox_server.py](../../inbox_server.py): FastAPI app. Uses
  `INBOX_SERVER_TOKEN`, `INBOX_SERVER_PORT`, `INBOX_PRE_WARM_CONVERSATIONS`, and
  `INBOX_DISABLE_AMBIENT`. It instantiates `SchedulerStore()` and
  `MessageIndexStore()` at runtime.
- [mcp_server.py](../../mcp_server.py): full MCP HTTP/stdout-facing tool surface
  plus memory and daily-note tools. Defaults HTTP port 8000.
- [inbox_mcp_readonly.py](../../inbox_mcp_readonly.py): read-only MCP surface,
  default HTTP port 8001, override via `INBOX_MCP_READONLY_PORT`.
- [inbox_mcp_stdio.py](../../inbox_mcp_stdio.py) and
  [inbox_mcp_readonly_stdio.py](../../inbox_mcp_readonly_stdio.py): local stdio
  wrappers around the full/read-only MCP apps.
- [message_sync.py](../../message_sync.py): materializes Gmail and iMessage into
  [message_index_store.py](../../message_index_store.py); modes are
  `bootstrap`, `incremental`, `rebuild`, and `summary`.

Shell/service surfaces:

- [dev.sh](../../dev.sh) runs `uv run python "${1:-inbox.py}"`, defaults the
  worktree to `INBOX_SERVER_PORT=9850`, and derives `INBOX_SERVER_URL`.
- [scripts/run_inbox_backend.sh](../../scripts/run_inbox_backend.sh),
  [scripts/run_inbox_mcp_http.sh](../../scripts/run_inbox_mcp_http.sh),
  [scripts/run_inbox_mcp_http_readonly.sh](../../scripts/run_inbox_mcp_http_readonly.sh),
  [scripts/run_inbox_mcp_stdio.sh](../../scripts/run_inbox_mcp_stdio.sh), and
  [scripts/run_inbox_mcp_stdio_readonly.sh](../../scripts/run_inbox_mcp_stdio_readonly.sh)
  all set `UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"` before `uv run`.
- [scripts/setup_inbox_mcp.sh](../../scripts/setup_inbox_mcp.sh) is not a safe
  audit command: it copies `config/inbox.env`, writes under
  `~/Library/LaunchAgents`, and runs `launchctl load`.
- [batch/batch-runner.sh](../../batch/batch-runner.sh) writes
  `batch/archive-state.tsv` and `batch/logs/`, then uses curl against
  `INBOX_SERVER_URL`. Its only implemented archive path is Gmail
  `POST /gmail/batch-modify`.

Deploy examples:

- [deploy/inbox-backend.service.example](../../deploy/inbox-backend.service.example),
  [deploy/inbox-mcp.service.example](../../deploy/inbox-mcp.service.example), and
  [deploy/inbox-mcp-readonly.service.example](../../deploy/inbox-mcp-readonly.service.example)
  hard-code `/Users/jwalinshah/projects/inbox`, not the current worktree.
- [deploy/com.inbox.backend.plist.example](../../deploy/com.inbox.backend.plist.example),
  [deploy/com.inbox.mcp.plist.example](../../deploy/com.inbox.mcp.plist.example), and
  [deploy/com.inbox.mcp-readonly.plist.example](../../deploy/com.inbox.mcp-readonly.plist.example)
  also hard-code `/Users/jwalinshah/projects/inbox` and log to `/tmp`.
- [deploy/Caddyfile.example](../../deploy/Caddyfile.example) exposes only
  `/health` and `/mcp` for full and read-only MCP hostnames.

## Environment variables

Observed env vars with local evidence:

- `INBOX_SERVER_URL`: [config/inbox.env.example](../../config/inbox.env.example),
  [.mcp.json](../../.mcp.json), [.cursor/mcp.json](../../.cursor/mcp.json),
  [mcp_backend.py](../../mcp_backend.py), [inbox_client.py](../../inbox_client.py),
  [MCP_SETUP.md](../../MCP_SETUP.md)
- `INBOX_SERVER_TOKEN`: [config/inbox.env.example](../../config/inbox.env.example),
  [inbox_server.py](../../inbox_server.py), [mcp_backend.py](../../mcp_backend.py),
  [.gitignore](../../.gitignore), [MCP_SETUP.md](../../MCP_SETUP.md)
- `INBOX_MCP_TOKEN`: [config/inbox.env.example](../../config/inbox.env.example),
  [mcp_gateway.py](../../mcp_gateway.py), [MCP_SETUP.md](../../MCP_SETUP.md)
- `INBOX_SERVER_PORT`: [dev.sh](../../dev.sh), [inbox_client.py](../../inbox_client.py),
  [inbox_server.py](../../inbox_server.py), [CLAUDE.md](../../CLAUDE.md)
- `INBOX_MCP_READONLY_PORT`: [inbox_mcp_readonly.py](../../inbox_mcp_readonly.py)
- `INBOX_MEMORY_DB`: [config/inbox.env.example](../../config/inbox.env.example),
  [mcp_gateway.py](../../mcp_gateway.py), [mcp_server.py](../../mcp_server.py)
- `INBOX_TEST_MODE`, `INBOX_TEST_DATA_DIR`, `INBOX_TEST_NOW`:
  [inbox_test_mode.py](../../inbox_test_mode.py) and
  [docs/TESTING_FOR_AGENTS.md](../TESTING_FOR_AGENTS.md)
- `INBOX_DEFAULT_GOOGLE_ACCOUNT`:
  [google_account_resolution.py](../../google_account_resolution.py) and
  [CONNECTOR_ROADMAP.md](../../CONNECTOR_ROADMAP.md)
- `INBOX_PRE_WARM_CONVERSATIONS`, `INBOX_DISABLE_AMBIENT`:
  [inbox_server.py](../../inbox_server.py)
- `INBOX_HOME_ADDRESS`, `GOOGLE_CLOUD_API_KEY`, `GOOGLE_MAPS_API_KEY`:
  [services.py](../../services.py)
- `GEMINI_API_KEY`: [services.py](../../services.py)
- `INBOX_POLL_INTERVAL`: [inbox.py](../../inbox.py)
- `UV_CACHE_DIR`: all `scripts/run_inbox_*` wrappers and necessary in this
  sandbox for uv commands.

Risk note: [mcp_gateway.py](../../mcp_gateway.py) treats an empty
`INBOX_MCP_TOKEN` as auth disabled for all non-health HTTP MCP requests. That
is acceptable for local stdio, but unsafe if the HTTP MCP gateway is exposed.
[MCP_SETUP.md](../../MCP_SETUP.md) says remote use should require
`INBOX_MCP_TOKEN`.

## Secrets, credentials, local state, and generated artifacts

Gitignored local credential/state paths are clear in [.gitignore](../../.gitignore):

- `credentials.json`, `token.json`, `token.json.lock`, `tokens/`
- `github_token.txt`, `google_maps_key.txt`, `gemini_api_key.txt`
- `config/inbox.env`, `.env`, `.env.local`, `.envrc`, `*.key`, `*.secret`
- `.inbox_memory.sqlite3`, `.inbox_scheduler.sqlite3`, `.inbox_index.sqlite3`
- `.coverage`, `htmlcov/`, `.tldr/`, `.venv`, `*.log`
- `batch/triage-output.tsv`, `batch/archive-state.tsv`, `batch/logs/`,
  `batch/.batch-state.lock`

Runtime-created local stores:

- [memory_store.py](../../memory_store.py) defaults to `.inbox_memory.sqlite3`
  unless `INBOX_MEMORY_DB` overrides it.
- [scheduler.py](../../scheduler.py) defaults to `.inbox_scheduler.sqlite3` and
  persists scheduled messages, follow-up reminders, and task-message links.
- [message_index_store.py](../../message_index_store.py) defaults to
  `.inbox_index.sqlite3`, creates WAL-mode tables for sync state, indexed items,
  threads, and sender stats.
- [services.py](../../services.py) stores Google OAuth tokens under `tokens/`,
  migrates legacy `token.json`, and writes token files under a lock.
- [services.py](../../services.py) writes voice config under
  `~/.config/inbox/voice.json` outside the repo unless test mode redirects it.
- [ambient_notes.py](../../ambient_notes.py) defaults to an Obsidian-style vault
  under `~/vault`.

Tracked generated or runner-owned artifacts:

- `git ls-files .factory` found 85 tracked `.factory` files.
- `du -sh .factory` -> `424K`.
- [.factory/services.yaml](../../.factory/services.yaml) defines install/test/
  typecheck/lint commands and a service target that hard-codes
  `/Users/jwalinshah/projects/inbox`.
- [.factory/init.sh](../../.factory/init.sh) runs `uv sync`, creates
  `~/.config/inbox`, and kills port 9849. It is not safe as a read-only audit
  command.
- [.factory/validation/**](../../.factory/validation) contains prior scrutiny
  and user-testing JSON artifacts; this is useful historical evidence but also
  a surface that can go stale relative to current code.

## External-service and platform dependencies

The app is tightly bound to local macOS and several external providers:

- macOS SQLite stores:
  - iMessage: `~/Library/Messages/chat.db`
  - AddressBook:
    `~/Library/Application Support/AddressBook/Sources/*/AddressBook-v22.abcddb`
  - Notes:
    `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite`
  - Reminders:
    `~/Library/Group Containers/group.com.apple.reminders/Container_v1/Stores/Data-*.sqlite`
- macOS write paths use AppleScript via `osascript` for iMessage, Notes,
  Reminders, WhatsApp, and notifications in [services.py](../../services.py).
- Dictation has hard-coded native binary/model assumptions in
  [services.py](../../services.py):
  `/opt/homebrew/bin/whisper-stream` and
  `/opt/homebrew/Cellar/whisper-cpp/1.8.4/share/whisper-cpp/ggml-base.en-q8_0.bin`.
- ML model names in [services.py](../../services.py) include
  `mlx-community/whisper-base.en-mlx`,
  `mlx-community/Qwen3.5-0.8B-MLX-4bit`, and
  `mlx-community/Qwen2.5-3B-Instruct-4bit`.
- Google API scopes in [services.py](../../services.py) include Gmail read,
  Gmail modify, Gmail send, Gmail settings, Calendar, Drive, Sheets, Docs, and
  Tasks.
- GitHub token resolution in [services.py](../../services.py) tries
  `gh auth token` first, then `github_token.txt`.
- Google Maps features read `GOOGLE_CLOUD_API_KEY`, `GOOGLE_MAPS_API_KEY`, or
  `google_maps_key.txt`.
- Gemini features read `GEMINI_API_KEY` or `gemini_api_key.txt`.

The test layer reduces some of this risk:

- [tests/conftest.py](../../tests/conftest.py) stubs `mlx_lm`, `mlx_whisper`,
  `sounddevice`, `outlines`, and `Quartz`.
- [inbox_test_mode.py](../../inbox_test_mode.py) blocks live writes under
  `INBOX_TEST_MODE=1`.
- [tests/test_inbox_test_mode.py](../../tests/test_inbox_test_mode.py) and
  [tests/test_services.py](../../tests/test_services.py) assert representative
  live writes are blocked.

## MCP dependency surface

MCP is a separate product surface with its own risks:

- [mcp_server.py](../../mcp_server.py) exposes full tools plus memory and daily
  note mutation tools. It requires explicit `confirm=True` for its handwritten
  write tools.
- [inbox_mcp_readonly.py](../../inbox_mcp_readonly.py) registers only readonly
  registry tools plus read-only memory/daily-note reads.
- [tools_registry.py](../../tools_registry.py) centralizes HTTP-backed tool
  definitions and flags each tool as `readonly` and/or `confirm`.
- [mcp_gateway.py](../../mcp_gateway.py) adds public HTTP auth middleware, but
  auth is disabled when `INBOX_MCP_TOKEN` is empty.
- [.mcp.json](../../.mcp.json) and [.cursor/mcp.json](../../.cursor/mcp.json)
  run `uv run python inbox_mcp_stdio.py` and
  `uv run python inbox_mcp_readonly_stdio.py` with
  `INBOX_SERVER_URL=http://127.0.0.1:9849`. They do not specify `cwd`, so client
  working-directory behavior matters.
- [config/codex.inbox.example.toml](../../config/codex.inbox.example.toml) and
  [config/gemini-settings.inbox.example.json](../../config/gemini-settings.inbox.example.json)
  hard-code the primary checkout by default and include comments/examples for
  dev worktrees.

Handoff risk: a dev worktree can run on 9850 via [dev.sh](../../dev.sh), but MCP
configs default to 9849. [MCP_SETUP.md](../../MCP_SETUP.md) calls this out as a
common failure mode where requests succeed but hit primary data.

## Validation surface

Observed commands:

- `llm-tldr tree .` succeeded and showed a flat Python repo with `config/`,
  `deploy/`, `docs/`, `modes/`, `scripts/`, `tests/`, root modules, and
  `uv.lock`.
- `rg --files -uu` showed hidden config and tracked factory files including
  `.mcp.json`, `.cursor/mcp.json`, `.env.mcp.example`, `.pre-commit-config.yaml`,
  `.factory/**`, and `.python-version`.
- `UV_CACHE_DIR=/tmp/uv-cache uv tree --locked` passed and resolved 149 packages.
- `uv tree --locked` failed because the sandbox could not use
  `/Users/jwalinshah/.cache/uv`.
- `rg -n "pytest.mark.safe|@pytest.mark.safe|pytestmark" tests` showed only
  [tests/test_inbox_test_mode.py](../../tests/test_inbox_test_mode.py) and
  [tests/test_mcp_gateway.py](../../tests/test_mcp_gateway.py) are marked
  `safe`.
- `du -sh .factory` -> `424K`; `du -sh tests` -> `568K`; `du -sh uv.lock` ->
  `432K`.

Exact validation command candidates:

- Required queue validation: `git status --short`
  - Expected after report: one added/modified report file before commit; clean
    after commit.
- Dependency graph smoke: `UV_CACHE_DIR=/tmp/uv-cache uv tree --locked`
  - Observed pass in this sandbox.
- Unsafe default in this sandbox: `uv tree --locked`
  - Observed fail due uv cache permission under `/Users/jwalinshah/.cache/uv`.
- Agent-safe tests: `INBOX_TEST_MODE=1 UV_CACHE_DIR=/tmp/uv-cache uv run pytest -m safe`
  - Expected to run only currently marked safe tests. Not run in this audit
    because the queue validation command is `git status --short` and `uv run`
    may create a local virtualenv/cache surface.
- Lint: `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .`
  - Expected to use configured Ruff rules. Not run in this audit.
- Typecheck: `UV_CACHE_DIR=/tmp/uv-cache uv run pyright`
  - Expected to use basic Pyright mode. Not run in this audit.
- Full tests: `INBOX_TEST_MODE=1 UV_CACHE_DIR=/tmp/uv-cache uv run pytest`
  - Expected to run with coverage because `pyproject.toml` has
    `--cov=. --cov-report=term-missing`; may create `.coverage`.
  - Should not run without `INBOX_TEST_MODE=1`.
- Factory test command:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pytest --ignore=tests/test_audio.py --ignore=tests/test_llm.py -x -q`
  - From [.factory/services.yaml](../../.factory/services.yaml). Expected to
    skip heavy audio/LLM tests, but still broader than the queue validation.

## Risks and stale assumptions

1. README Python version is stale.
   [README.md](../../README.md) says Python 3.10+, while
   [pyproject.toml](../../pyproject.toml) and [.python-version](../../.python-version)
   require/use Python 3.12. New workers can waste time debugging an unsupported
   interpreter.

2. Direct imports rely on transitive packages.
   [services.py](../../services.py) uses `requests` directly and
   [mcp_gateway.py](../../mcp_gateway.py) uses Starlette directly, but neither
   is directly declared in [pyproject.toml](../../pyproject.toml). Current lock
   resolves them transitively, but future dependency changes can break imports.

3. HTTP MCP auth is opt-in by env var.
   [mcp_gateway.py](../../mcp_gateway.py) allows all non-health HTTP MCP traffic
   when `INBOX_MCP_TOKEN` is empty. This is easy to misconfigure if a local
   gateway is later reverse-proxied.

4. Primary-vs-dev routing is fragile.
   [dev.sh](../../dev.sh) defaults worktrees to port 9850, while
   [.mcp.json](../../.mcp.json), [.cursor/mcp.json](../../.cursor/mcp.json), and
   service examples default to primary port 9849. A worker can believe it is
   testing a worktree while mutating or reading primary state.

5. Deploy/factory files hard-code the primary checkout.
   `deploy/*.example`, [.factory/services.yaml](../../.factory/services.yaml),
   and [.factory/init.sh](../../.factory/init.sh) reference
   `/Users/jwalinshah/projects/inbox`. They are useful for the primary machine
   but unsafe to run blindly in isolated worktrees.

6. Local state is broad and partly outside the repo.
   SQLite stores, OAuth tokens, GitHub token files, Google Maps/Gemini key files,
   Obsidian vault writes, voice config, macOS SQLite data stores, and Homebrew
   whisper binaries all sit outside normal package dependency boundaries.

7. The `safe` marker is sparse.
   Only two test modules are marked `safe`. [docs/TESTING_FOR_AGENTS.md](../TESTING_FOR_AGENTS.md)
   recommends `INBOX_TEST_MODE=1 uv run pytest -m safe`, but that command may
   prove less coverage than expected unless more tests are marked.

8. Batch runner is stateful and mutation-oriented.
   [batch/batch-runner.sh](../../batch/batch-runner.sh) creates state/log files
   and performs Gmail archive operations. It should not be treated as a generic
   read-only validation helper.

9. ML/audio deps are large and platform-specific.
   `mlx-lm`, `mlx-whisper`, `torch`, `sounddevice`, PyObjC, and hard-coded
   whisper-stream paths make dependency resolution and local validation machine-
   dependent. Tests stub some deps, but runtime setup remains fragile.

10. The lock is current, but manifest constraints are broad lower bounds.
    [pyproject.toml](../../pyproject.toml) uses `>=` lower bounds for runtime
    and dev dependencies. The lock protects `uv` workflows, but non-locked
    installs may pick newer packages with changed APIs.

## Independently grabbable next tasks

### Task 1: Declare direct transitive imports explicitly

Acceptance criteria:

- Add direct dependencies for any runtime imports that are used directly but
  currently only present transitively, at minimum `requests` and `starlette`.
- Keep [uv.lock](../../uv.lock) updated.
- Do not widen dependency versions beyond existing lock-compatible versions.

Validation:

- `UV_CACHE_DIR=/tmp/uv-cache uv sync --locked`
- `UV_CACHE_DIR=/tmp/uv-cache uv tree --locked`
- `INBOX_TEST_MODE=1 UV_CACHE_DIR=/tmp/uv-cache uv run pytest -m safe`

### Task 2: Align setup docs with actual Python and uv requirements

Acceptance criteria:

- Update [README.md](../../README.md), [CLAUDE.md](../../CLAUDE.md), and
  [MCP_SETUP.md](../../MCP_SETUP.md) where needed so Python version, uv cache
  expectations, worktree ports, and primary-vs-dev MCP routing are consistent.
- Explicitly document `UV_CACHE_DIR=/tmp/uv-cache` for sandboxed agent commands.
- Keep changes docs-only.

Validation:

- `rg -n "Python 3.10|Python 3.12|UV_CACHE_DIR|9850|9849" README.md CLAUDE.md MCP_SETUP.md docs config`
- `git diff -- README.md CLAUDE.md MCP_SETUP.md docs config`

### Task 3: Expand agent-safe validation coverage

Acceptance criteria:

- Review unmarked tests and mark deterministic, mocked tests as `safe`.
- Do not mark tests safe if they touch local user data, live providers, audio
  hardware, notification mutation, or live writes.
- Update [docs/TESTING_FOR_AGENTS.md](../TESTING_FOR_AGENTS.md) with any refined
  safe-test policy.

Validation:

- `rg -n "pytest.mark.safe|pytestmark = pytest.mark.safe" tests`
- `INBOX_TEST_MODE=1 UV_CACHE_DIR=/tmp/uv-cache uv run pytest -m safe -q`

### Task 4: Add a config drift check for MCP/dev routing

Acceptance criteria:

- Add a script or test that checks MCP config examples for primary vs dev port
  consistency and catches missing `cwd` where a client requires it.
- The check should not start servers or touch tokens.
- It should fail with clear messages when a config points at primary 9849 while
  describing a dev worktree.

Validation:

- `INBOX_TEST_MODE=1 UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_mcp_gateway.py -q`
- New focused test/script command chosen by implementer.

### Task 5: Quarantine destructive local setup commands from worker workflows

Acceptance criteria:

- Document that [scripts/setup_inbox_mcp.sh](../../scripts/setup_inbox_mcp.sh)
  and [.factory/init.sh](../../.factory/init.sh) are not agent-default commands.
- If appropriate, add a dry-run or confirmation guard to setup scripts before
  they copy launch agents, run `launchctl`, or kill port 9849.
- Keep default runtime scripts unchanged unless the task explicitly scopes it.

Validation:

- `bash -n scripts/setup_inbox_mcp.sh .factory/init.sh`
- Review of script output in dry-run mode if added.

## Unknowns

- I did not inspect real local token files or secret files; they are gitignored
  and intentionally out of scope.
- I did not inspect whether primary `~/projects/inbox` is running on port 9849.
- I did not run live backend health checks, MCP calls, Google API calls, GitHub
  API calls, AppleScript operations, or audio/ML runtime loading.
- I did not verify whether the hard-coded Homebrew whisper paths exist on this
  machine.
- I did not compare against sibling repos from `repos.json`; this queue item is
  scoped to the current repo/worktree and the local repo was substantial enough
  for a standalone audit.
- I did not run full tests/lint/typecheck because the queue validation is
  `git status --short` and broader validation can create local caches or require
  deeper product judgment about safe coverage.

## Morning handoff

Changed file expected from this queue item:

- [docs/overnight/inbox-sym-115-dependency-surface.md](inbox-sym-115-dependency-surface.md)

No PR was opened. No external tracker was marked Done. No product code was
modified.
