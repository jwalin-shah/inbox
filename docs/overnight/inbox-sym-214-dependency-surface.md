# inbox-sym-214 dependency-surface audit

Queue item: `inbox-sym-214-dependency-surface`
Focus area: `dependency-surface`
Repo path: `/Users/jwalinshah/projects/agent-stack/.agent-stack-worktrees/2026-05-07-overnight-marathon/inbox-sym-214-dependency-surface`
Audit date: 2026-05-07

## Summary

`inbox-sym-214` is a Python/uv personal inbox service and Textual TUI that bridges local macOS data stores, Google APIs, GitHub, local ML/audio, and MCP agent access. The dependency surface is broad for a personal local tool: FastAPI/uvicorn/httpx for the backend, Textual/Rich for the TUI, Google OAuth/API clients, MCP server tooling, pyobjc/macOS SQLite readers, sounddevice/whisper/MLX local ML, and optional Gemini/Google Maps/GitHub token files.

The declared dependency source of truth is `pyproject.toml` plus `uv.lock`, not the README. `uv tree` with a sandbox-safe cache resolves 149 packages. The highest-leverage follow-up is to separate always-needed server/TUI dependencies from optional macOS/audio/ML/Gemini surfaces and to make cache, env, and worktree path assumptions explicit.

## Repo State

- Branch: `codex/goal-inbox-sym-214-dependency-surface`.
- HEAD at start of audit: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`.
- Initial dirty state: `git status --short --branch` printed only `## codex/goal-inbox-sym-214-dependency-surface`, so the worktree started clean.
- Required output written: `docs/overnight/inbox-sym-214-dependency-surface.md`.
- External services, credentials, live data, deploys, pushes, and PR creation were not touched.

## Commands Run

- `llm-tldr tree .` - mapped tracked top-level repo shape and confirmed the project is a flat Python app with `tests/`, `scripts/`, `deploy/`, `config/`, `modes/`, `batch/`, and hidden `.factory/` artifacts.
- `git status --short --branch` - observed starting branch and clean state.
- `git rev-parse --show-toplevel` - confirmed the worktree root is the queue-item repo path.
- `git rev-parse HEAD` - captured `2805b8400519da188ca7d3f6e39b19a8ca42b05a`.
- `rtk read pyproject.toml` - inspected declared Python, runtime deps, dev deps, pytest markers, ruff, pyright, and bandit config.
- `rtk read README.md` and `rtk read docs/TESTING_FOR_AGENTS.md` - compared docs claims and safe validation guidance against dependency declarations.
- `rg --files --hidden -g '!.git'` - found hidden tracked surfaces including `.mcp.json`, `.env.mcp.example`, `.factory/services.yaml`, `.factory/validation/**`, `.cursor/mcp.json`, `.pre-commit-config.yaml`, `.python-version`, and `.gitignore`.
- `git ls-files --others --ignored --exclude-standard` - produced no output; no ignored local secrets/caches/artifacts were present at audit time.
- `rg -n "os\\.environ|os\\.getenv|getenv\\(|load_dotenv|dotenv|INBOX_|OPENAI|ANTHROPIC|GOOGLE|GMAIL|CALENDAR|DRIVE|GITHUB|TOKEN|SECRET|CREDENTIAL|PORT|HOST|HOME|Library|sqlite|\\.db|\\.sqlite|\\.json|tokens/|credentials\\.json|github_token" ...` - located env, token, local SQLite, and local config surfaces across code/docs/scripts.
- `uv tree --locked --depth 1` - failed in this sandbox because `uv` tried to initialize `/Users/jwalinshah/.cache/uv` and hit `Operation not permitted`.
- `UV_CACHE_DIR=/private/tmp/uv-cache-inbox-audit uv tree --locked --depth 1` - passed, used CPython 3.12.12, resolved 149 packages, and listed direct runtime/dev packages.
- `rg -n -A80 '^name = "inbox"' uv.lock` - confirmed the lockfile package metadata matches direct runtime/dev deps.
- `rg '^name = ' uv.lock --count` - counted 149 locked packages.
- `rg -n 'name = "(torch|mlx|mlx-lm|mlx-whisper|transformers|sounddevice|pyobjc-framework-(applicationservices|quartz)|mcp|fastapi|uvicorn|google-api-python-client|google-generativeai|outlines|textual|numpy)"|cuda|nvidia|triton' uv.lock` - identified heavy platform-specific transitive dependency families.
- `nl -ba ... | sed -n ...` slices - captured line-level evidence from `services.py`, `inbox_server.py`, `mcp_gateway.py`, `mcp_backend.py`, `dev.sh`, `.gitignore`, `docs/TESTING_FOR_AGENTS.md`, `pyproject.toml`, `.mcp.json`, and related config files.

## Evidence Map

### Dependency declarations and lockfile

- `pyproject.toml:5` requires `>=3.12,<3.15`, while `.python-version` pins `3.12`. This conflicts with README's "Python 3.10+" quick-start claim in `README.md`.
- `pyproject.toml:6-26` declares runtime deps: `fastapi`, Google clients, `httpx`, `loguru`, `mcp[cli]`, `mlx-lm`, `mlx-whisper`, `numpy`, `outlines`, `pydantic`, pyobjc ApplicationServices/Quartz, `python-multipart`, `rich`, `sounddevice`, `textual`, and `uvicorn`.
- `pyproject.toml:28-38` declares dev deps: `bandit`, `hypothesis`, `pre-commit`, `pyright`, `pytest`, `pytest-cov`, `python-dotenv`, and `ruff`.
- `pyproject.toml:53-66` configures pytest with coverage by default, safe/integration/local/live markers, ruff, pyright basic mode, and bandit skips. Running normal pytest will create coverage artifacts unless the caller overrides coverage.
- `uv.lock:860-930` mirrors the `inbox` direct deps and dev deps, and `rg '^name = ' uv.lock --count` counted 149 package entries.
- `UV_CACHE_DIR=/private/tmp/uv-cache-inbox-audit uv tree --locked --depth 1` resolved direct packages to current locked versions including `fastapi v0.135.3`, `mcp[cli] v1.27.0`, `mlx-lm v0.31.2`, `mlx-whisper v0.4.3`, `numpy v2.4.4`, `textual v8.2.3`, `uvicorn v0.44.0`, and dev tools such as `pytest v9.0.3` and `ruff v0.15.10`.
- `uv.lock` includes platform-heavy ML transitive packages: `torch`, `transformers`, `triton`, `cuda-*`, and `nvidia-*` packages are present behind markers from `mlx-whisper`/ML tooling, even though this repo is documented as macOS/local-first.

### Runtime entrypoints and scripts

- `README.md` documents `uv run python inbox.py` as the default TUI/server launcher and `uv run python inbox_server.py` for server-only use.
- `dev.sh:1-11` is the worktree launcher and sets `INBOX_SERVER_PORT=9850` plus `INBOX_SERVER_URL=http://127.0.0.1:${INBOX_SERVER_PORT}` before `uv run python "${1:-inbox.py}"`.
- `inbox_server.py:212-213` defaults the backend to port `9849` and uses `INBOX_SERVER_TOKEN` for optional auth.
- `inbox_server.py:3936-3940` reads `INBOX_SERVER_PORT` only in the `__main__` uvicorn path, binding to `127.0.0.1`.
- `mcp_backend.py:9-21` reads `INBOX_SERVER_URL` and `INBOX_SERVER_TOKEN`, defaulting to `http://127.0.0.1:9849`.
- `scripts/run_inbox_backend.sh:1-9`, `scripts/run_inbox_mcp_http.sh`, `scripts/run_inbox_mcp_http_readonly.sh`, `scripts/run_inbox_mcp_stdio.sh`, and `scripts/run_inbox_mcp_stdio_readonly.sh` all set `UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"` before `uv run`.
- `.factory/services.yaml:1-14` duplicates operational commands and hardcodes `/Users/jwalinshah/projects/inbox` plus port `9849`.

### Env vars, secrets, and local-only state

- `config/inbox.env.example:1-9` defines `INBOX_SERVER_URL`, `INBOX_SERVER_TOKEN`, `INBOX_MCP_TOKEN`, and optional `INBOX_MEMORY_DB`.
- `.env.mcp.example:1-10` defines a similar MCP-specific env surface but leaves `INBOX_SERVER_TOKEN` empty and warns to set `INBOX_MCP_TOKEN` before exposing publicly.
- `.mcp.json:1-25` and `.cursor/mcp.json` provide repo-local MCP stdio servers for full and read-only tools, both using `${INBOX_SERVER_TOKEN}` and `127.0.0.1:9849`.
- `config/codex.inbox.example.toml:1-29` hardcodes `cwd = "/Users/jwalinshah/projects/inbox"` for the main config and only shows worktree `cwd` as a commented example.
- `services.py:56-86` defines credential and token files in repo root: `credentials.json`, `token.json`, `tokens/`, `github_token.txt`, `google_maps_key.txt`, and `gemini_api_key.txt`.
- `services.py:88-98` requests broad Google scopes: Gmail readonly/modify/send/settings, Calendar, Drive, Spreadsheets, Documents, and Tasks.
- `inbox_test_mode.py:9-31` defines `INBOX_TEST_MODE`, `INBOX_TEST_DATA_DIR`, and `INBOX_TEST_NOW`, with test data defaulting to `/tmp/inbox-test-data`.
- `mcp_gateway.py:18-39` reads `INBOX_MCP_TOKEN` and `INBOX_MEMORY_DB`. If `INBOX_MCP_TOKEN` is unset, `_is_publicly_authorized` returns true because there is no token to compare.
- `services.py:3249-3264` loads Gemini via `GEMINI_API_KEY` or `gemini_api_key.txt`, despite the README's local-first positioning.
- `services.py:3485-3504` supports `INBOX_HOME_ADDRESS` for commute/location fallback.
- `services.py:4829-4835` sets the local MLX autocomplete model and `INBOX_LLM_LARGE` override.
- `inbox_server.py:1230-1258` reads `INBOX_PRE_WARM_CONVERSATIONS` and `INBOX_DISABLE_AMBIENT`.
- `inbox_server.py:3939` reads `INBOX_SERVER_PORT`.
- `inbox.py:44-48` reads `INBOX_POLL_INTERVAL`.

### Local data stores and generated artifacts

- `services.py:67-80` reads iMessage, Notes, and Reminders SQLite paths from the real macOS home directory unless `INBOX_TEST_MODE` redirects them into test data.
- `contacts.py:39-78` reads AddressBook SQLite from `~/Library/Application Support/AddressBook/...` in read-only SQLite mode.
- `message_sync.py:452-456` reads iMessage messages via `sqlite3.connect(...mode=ro...)`.
- `message_index_store.py:12-13` defaults the local index DB to `.inbox_index.sqlite3` in the repo root.
- `memory_store.py:9-10` defaults the MCP memory DB to `.inbox_memory.sqlite3` in the repo root.
- `scheduler.py:15-16` defaults scheduler state to `.inbox_scheduler.sqlite3` in the repo root.
- `services.py:5429-5433`, `services.py:5560-5564`, and `services.py:6090-6100` default notification, favorite, and voice config to `~/.config/inbox/*.json` plus `~/vault`.
- `.gitignore:12-25` ignores credentials, tokens, env files, and key/secret patterns.
- `.gitignore:27-58` ignores coverage, logs, `.tldr/`, `.claude/`, `.inbox_memory.sqlite3`, `.inbox_scheduler.sqlite3`, `.inbox_index.sqlite3`, and batch outputs.
- `rg --files --hidden -g '!.git'` shows many tracked `.factory/validation/**` JSON artifacts. They are hidden generated-looking evidence files but are committed, not ignored.
- `git ls-files --others --ignored --exclude-standard` returned no ignored files, so no local secrets, `.venv`, SQLite DBs, coverage, logs, or caches were visible in this worktree during the audit.

### Deployment and external exposure surfaces

- `deploy/inbox-backend.service.example`, `deploy/inbox-mcp.service.example`, and `deploy/inbox-mcp-readonly.service.example` hardcode `WorkingDirectory=/Users/jwalinshah/projects/inbox`, `EnvironmentFile=/Users/jwalinshah/projects/inbox/config/inbox.env`, and scripts under that same path.
- `deploy/com.inbox.backend.plist.example`, `deploy/com.inbox.mcp.plist.example`, and `deploy/com.inbox.mcp-readonly.plist.example` hardcode `cd /Users/jwalinshah/projects/inbox && source config/inbox.env && ...` and write logs to `/tmp/inbox-*.log`.
- `deploy/Caddyfile.example` exposes `/health` and `/mcp*` for full MCP on `127.0.0.1:8000` and read-only MCP on `127.0.0.1:8001`.
- `scripts/setup_inbox_mcp.sh` copies `config/inbox.env.example` to `config/inbox.env` with `chmod 600`, installs launch agents, and prints guidance to keep `INBOX_SERVER_TOKEN` out of Codex config.
- `batch/batch-runner.sh` is an external-write surface: it reads `INBOX_SERVER_URL`/`INBOX_SERVER_TOKEN`, calls `/gmail/batch-modify`, writes `batch/archive-state.tsv`, and writes per-thread logs under `batch/logs/`.

## Risks And Stale Assumptions

1. Python version docs are stale. `pyproject.toml` requires Python `>=3.12,<3.15` and `.python-version` is `3.12`, while `README.md` still says Python `3.10+`. A new agent or human following README may build the wrong environment before hitting type syntax or locked dependency issues.

2. The "local-first ML/no cloud dependencies" story is not cleanly separated from optional cloud LLMs. Runtime deps include `google-generativeai`; `services.py` reads `GEMINI_API_KEY`/`gemini_api_key.txt`; `inbox_server.py` exposes Gemini endpoints. This may be intentional, but it is not visible as an optional extra or feature flag in the dependency model.

3. MCP public auth can fail open if the token is unset. `mcp_gateway.py:36-39` authorizes all requests when `INBOX_MCP_TOKEN` is empty, while `deploy/Caddyfile.example` documents an externally exposed `/mcp*` route. The docs do warn to require `INBOX_MCP_TOKEN`, but the code-level default remains permissive.

4. Worktree safety depends on remembering several path overrides. `dev.sh` handles a dev port, but `.mcp.json`, `.cursor/mcp.json`, `config/codex.inbox.example.toml`, `config/gemini-settings.inbox.example.json`, `.factory/services.yaml`, and deploy templates default to `/Users/jwalinshah/projects/inbox` or `9849`. Agents can accidentally test the primary checkout/server while editing a worktree.

5. The dependency lock is heavy and platform-sensitive. `mlx-lm`, `mlx-whisper`, `sounddevice`, pyobjc, `torch`, `transformers`, `triton`, and CUDA/NVIDIA packages make the install surface much larger than a backend/TUI baseline. This creates higher sync time, storage, native library, and non-macOS failure risk.

6. Local generated state lives beside source unless test mode or env overrides redirect it. `.inbox_index.sqlite3`, `.inbox_memory.sqlite3`, `.inbox_scheduler.sqlite3`, `tokens/`, `token.json`, and key files are gitignored, but a worktree can still accumulate personal state. This is especially risky for isolated worker runs and morning dirty-worktree review.

7. `uv` cache behavior is inconsistent by entrypoint. The service wrapper scripts set `UV_CACHE_DIR=/tmp/uv-cache`; `dev.sh` and raw validation commands do not. In the Codex sandbox, raw `uv tree --locked --depth 1` failed on `/Users/jwalinshah/.cache/uv`, while the same command passed with a temp `UV_CACHE_DIR`.

8. Batch tooling is an externally visible mutation path under a local-looking folder. `batch/batch-runner.sh` writes state/logs and performs Gmail batch modify calls. The generated outputs are ignored, but the input TSV is tracked and the script can mutate Gmail if pointed at a live server.

## Decisions Made During Audit

- Treat `pyproject.toml` and `uv.lock` as the dependency source of truth over README claims.
- Treat env vars, local SQLite paths, ignored artifacts, deploy templates, and MCP config as part of the dependency surface because they determine whether dependency commands touch live data or the intended worktree.
- Do not run live tests, servers, MCP tools, OAuth flows, launchctl, Caddy, batch archive, or any command that could touch personal data or external services.
- Use `UV_CACHE_DIR=/private/tmp/uv-cache-inbox-audit` only for dependency inspection, outside the repo, to avoid mutating project caches.
- Leave code and operational templates unchanged; this audit is a report-only artifact.

## Validation Candidates

| Command | Expected status | Evidence / notes |
| --- | --- | --- |
| `git status --short` | Pass. After this report is written, expected output is the new report path only. | Required queue validation. |
| `UV_CACHE_DIR=/private/tmp/uv-cache-inbox-audit uv tree --locked --depth 1` | Pass. | Ran successfully; CPython 3.12.12; resolved 149 packages. |
| `uv tree --locked --depth 1` | Fail in current sandbox unless cache is redirected. | Ran and failed with `failed to open file /Users/jwalinshah/.cache/uv/sdists-v9/.git: Operation not permitted`. |
| `INBOX_TEST_MODE=1 UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_inbox_test_mode.py -q --no-cov` | Expected pass; safe focused smoke candidate. | Not run in this audit because the issue validation is `git status --short`. `--no-cov` avoids default coverage artifact churn from `pyproject.toml`. |
| `INBOX_TEST_MODE=1 UV_CACHE_DIR=/tmp/uv-cache uv run pytest -m safe --no-cov` | Expected pass if safe markers remain coherent; safest broader test candidate. | Not run in this audit. `docs/TESTING_FOR_AGENTS.md` names `INBOX_TEST_MODE=1 uv run pytest -m safe` as the default safe loop. |
| `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .` | Expected pass candidate, but not proven here. | Listed in `docs/TESTING_FOR_AGENTS.md` and `.factory/services.yaml`; not run because report-only validation was requested. |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pyright` | Expected pass candidate, but not proven here. | Listed in `docs/TESTING_FOR_AGENTS.md` and `.factory/services.yaml`; not run because report-only validation was requested. |

## Next Safe Work

1. Align Python/runtime docs with the locked dependency contract.
   - Scope: `README.md`, `CLAUDE.md`, `docs/TESTING_FOR_AGENTS.md`, maybe `DOCS_INDEX.md`.
   - Acceptance criteria: README says Python 3.12+ and points to `.python-version`; docs mention `UV_CACHE_DIR=/tmp/uv-cache` for sandboxed agents; validation commands avoid accidental coverage artifacts when appropriate.
   - Validation: `git diff --check`; `UV_CACHE_DIR=/tmp/uv-cache uv tree --locked --depth 1`; `git status --short`.

2. Split optional dependency groups/extras for ML, audio, macOS private data, and cloud Gemini.
   - Scope: `pyproject.toml`, `uv.lock`, import guards in modules that use optional deps, and docs.
   - Acceptance criteria: a backend-only or test-only sync does not require MLX/audio/torch/CUDA/Gemini packages; full local app still installs all existing functionality; missing optional deps produce actionable messages instead of import-time crashes.
   - Validation: `UV_CACHE_DIR=/tmp/uv-cache uv sync --locked`; `INBOX_TEST_MODE=1 UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_inbox_test_mode.py -q --no-cov`; `UV_CACHE_DIR=/tmp/uv-cache uv run pyright`.

3. Build a documented env-var inventory and drift check.
   - Scope: new docs section or generated markdown plus a small script/test that compares `INBOX_*`, `GEMINI_API_KEY`, and local key-file references in code against examples/docs.
   - Acceptance criteria: every runtime env var has owner, default, secret/non-secret classification, live-data risk, and worktree guidance; examples do not disagree on required tokens.
   - Validation: `rg -n 'INBOX_|GEMINI_API_KEY|github_token|credentials.json|tokens/' .`; new focused unit test or script; `git diff --check`.

4. Make MCP and deploy templates worktree-safe and fail-closed.
   - Scope: `.mcp.json`, `.cursor/mcp.json`, `config/codex.inbox.example.toml`, `config/gemini-settings.inbox.example.json`, `deploy/*.example`, `scripts/setup_inbox_mcp.sh`, `MCP_SETUP.md`.
   - Acceptance criteria: examples clearly distinguish primary checkout from worktree checkout; HTTP MCP examples require `INBOX_MCP_TOKEN`; docs warn that unset `INBOX_MCP_TOKEN` is open; no template accidentally points a worktree worker at `/Users/jwalinshah/projects/inbox` without an explicit note.
   - Validation: `rg -n '/Users/jwalinshah/projects/inbox|INBOX_MCP_TOKEN|INBOX_SERVER_URL' .mcp.json .cursor/mcp.json config deploy MCP_SETUP.md`; `git diff --check`.

5. Move or parameterize repo-root SQLite state.
   - Scope: `message_index_store.py`, `memory_store.py`, `scheduler.py`, docs, and tests.
   - Acceptance criteria: default runtime state follows an XDG-ish per-user state directory or documented env override; test mode remains isolated; repo-root `.inbox_*.sqlite3` compatibility is preserved or migrated intentionally.
   - Validation: `INBOX_TEST_MODE=1 UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_memory_store.py tests/test_message_index_store.py tests/test_inbox_test_mode.py -q --no-cov`.

6. Audit batch mutation tooling before any automated worker uses it.
   - Scope: `batch/batch-runner.sh`, `batch/archive-input.tsv`, docs for dry-run/live-run boundaries.
   - Acceptance criteria: dry-run is the default for agent usage; live Gmail mutation requires explicit confirmation; state/log writes are robust under parallelism; token/header handling is shell-safe.
   - Validation: `bash -n batch/batch-runner.sh`; `batch/batch-runner.sh --mode archive --dry-run` only against non-live fixtures or mocked server.

## Non-Goals

- No product code changes.
- No dependency upgrades, lockfile rewrite, or install changes.
- No OAuth, Gmail, Calendar, Drive, Sheets, Docs, Tasks, GitHub, iMessage, Notes, Reminders, microphone, Caddy, launchd, systemd, or MCP live calls.
- No reading ignored secrets or local credential files.
- No server startup, deploy, push, PR creation, or tracker state mutation.
- No sibling repo comparison; this repo is large enough that the dependency-surface audit did not need to borrow scope from related repos.

## Unknowns

- Whether `google-generativeai` is intended as a first-class runtime dependency or should become an optional extra.
- Whether non-macOS installation is supported at all, given `pyobjc`, MLX, Homebrew whisper paths, and local macOS SQLite data sources.
- Whether full MCP HTTP is ever intentionally exposed outside localhost; current docs imply remote exposure is possible through Caddy.
- Whether repo-root `.inbox_*.sqlite3` defaults are intentional for portability or historical leftovers.
- Whether tracked `.factory/validation/**` JSON files are durable project evidence or generated artifacts that should age out.
- Whether `uv run pytest -m safe` currently covers enough of the dependency surface, since only a subset of test files visibly carry `pytest.mark.safe`.

## Handoff

- Changed files: `docs/overnight/inbox-sym-214-dependency-surface.md`.
- Current HEAD SHA: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`.
- Required validation: `git status --short` exited 0 and printed `?? docs/overnight/`.
- PR URL: none; PR creation is out of scope for this Goal Pack item.
- Blockers: none for the report. Raw `uv` commands need `UV_CACHE_DIR` redirected in this sandbox.
