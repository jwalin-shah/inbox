# inbox-sym-116 dependency-surface audit

Queue item: `inbox-sym-116-dependency-surface`
Repo: `inbox-sym-116`
Focus area: dependency surface
Audit date: 2026-05-07

## Scope and decision

This is a read-only dependency-surface audit. I did not touch product code,
credentials, generated runtime data, external services, deploys, pushes, or
external trackers. The only intended change is this report.

Decision: do not run `uv run ...` validation during the audit. The repository
is dependency-heavy, `uv run` may create `.venv` or cache state, and this queue
item's required validation command is `git status --short`. I treated tests,
lint, typecheck, and lock checks as validation candidates instead of executing
them.

## Repo purpose and state

The repo is a local-first personal inbox TUI and private API. `README.md` says
it consolidates iMessage, Gmail, Calendar, Sheets, Apple Notes, Apple Reminders,
GitHub notifications, Google Drive, ambient listening, dictation, and AI
autocomplete into a keyboard-driven Textual app. The architecture is a FastAPI
backend (`inbox_server.py`), a sync client (`inbox_client.py`), a Textual TUI
(`inbox.py`), MCP adapters (`mcp_server.py`, `inbox_mcp_readonly.py`), and a
large service module (`services.py`) that owns most external data access.

Observed git state before writing this report:

```text
git branch --show-current
codex/goal-inbox-sym-116-dependency-surface

git rev-parse HEAD
2805b8400519da188ca7d3f6e39b19a8ca42b05a

git status --short
<empty>
```

The final validation is expected to show this new report as the only dirty
worktree state.

## Evidence inventory

| Evidence | Observation |
| --- | --- |
| `llm-tldr tree .` | Repo is a flat Python app with `services.py`, `inbox_server.py`, `inbox.py`, MCP entrypoints, `tests/`, `config/`, `deploy/`, `.factory/`, and `uv.lock`. |
| `git status --short --branch` | Started on `codex/goal-inbox-sym-116-dependency-surface` with no dirty file output. |
| `pyproject.toml:5-26` | Runtime requires Python `>=3.12,<3.15` and declares 19 runtime dependencies, including FastAPI, Google APIs, MCP, MLX, Outlines, pyobjc, Textual, Uvicorn, and sounddevice. |
| `pyproject.toml:28-66` | Dev dependencies and tooling are ruff, pyright, pytest, pytest-cov, bandit, hypothesis, pre-commit, and python-dotenv; pytest always adds coverage via `--cov=. --cov-report=term-missing`. |
| `uv.lock` command observation | `rg '^name = ' uv.lock | wc -l` returned `149`, so the lockfile brings in a large transitive closure. |
| `uv.lock:860-935` | The locked `inbox` package mirrors `pyproject.toml`; direct package metadata does not include `requests`, CoreLocation, or UserNotifications. |
| `uv.lock:1171-1248` and `uv.lock:2658-2745` | ML/audio dependencies pull platform-specific MLX wheels and `torch`; the lockfile also contains Linux CUDA/NVIDIA packages behind markers. |
| `README.md:31-33` vs `pyproject.toml:5` | README claims Python 3.10+, but package metadata requires Python 3.12 through below 3.15. |
| `README.md:144-150` and `services.py:65-86` | Runtime reads local macOS SQLite databases, local OAuth token files, and local API key files from user and repo paths. |
| `services.py:88-98` | Google OAuth scopes include Gmail readonly/modify/send/settings, Calendar, Drive, Sheets, Docs, and Tasks. |
| `services.py:330-390` | `google_auth_all()` creates `tokens/`, migrates `token.json`, may launch an OAuth local server, and builds Gmail, Calendar, Drive, Sheets, Docs, and Tasks services. |
| `services.py:576-623` and `services.py:2819-2845` | iMessage and Reminders writes shell out to `osascript`, guarded by `INBOX_TEST_MODE` checks. |
| `services.py:3488-3504` and `services.py:3510-3522` | Location and Maps behavior depend on optional `CoreLocation`, `INBOX_HOME_ADDRESS`, `GOOGLE_CLOUD_API_KEY`, `GOOGLE_MAPS_API_KEY`, or `google_maps_key.txt`. |
| `services.py:5429-5584` and `services.py:6088-6118` | User preferences write to `~/.config/inbox/notifications.json`, `favorites.json`, and `voice.json`, with test-mode path redirection available. |
| `inbox_client.py:16-25` | Clients default to `INBOX_SERVER_PORT`/`INBOX_SERVER_URL` and attach `INBOX_SERVER_TOKEN` only when present. |
| `inbox_server.py:1313-1325` | Backend auth is optional; if `INBOX_SERVER_TOKEN` is empty, all requests are authorized. |
| `mcp_gateway.py:18-44` | Public MCP auth is also optional through `INBOX_MCP_TOKEN`; empty token allows access. |
| `.mcp.json` and `.cursor/mcp.json` | Both checked-in MCP configs point to `http://127.0.0.1:9849` and inherit `${INBOX_SERVER_TOKEN}`. |
| `config/inbox.env.example` and `.env.mcp.example` | Example env files define `INBOX_SERVER_URL`, `INBOX_SERVER_TOKEN`, `INBOX_MCP_TOKEN`, and optional `INBOX_MEMORY_DB`. |
| `scripts/run_inbox_*.sh` | Service launchers set `UV_CACHE_DIR=${UV_CACHE_DIR:-/tmp/uv-cache}` and run `uv run python ...`, so service startup can write cache state outside the repo. |
| `deploy/*.service.example` and `deploy/*.plist.example` | Deployment examples hard-code `/Users/jwalinshah/projects/inbox`, source `config/inbox.env`, and write logs under `/tmp`. |
| `.gitignore` | Secrets, `.venv`, coverage, logs, `.tldr/`, `.claude/`, `.inbox_memory.sqlite3`, `.inbox_scheduler.sqlite3`, `.inbox_index.sqlite3`, and batch generated outputs are ignored. |
| `.factory/services.yaml` | Factory metadata defines `uv sync`, pytest, pyright, ruff, and a port-9849 service; its test command differs from agent testing docs. |
| `docs/TESTING_FOR_AGENTS.md:9-18` | Agent-safe validation should use `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, `uv run pyright`, or a focused test mode test. |
| `tests/conftest.py:15-35` | Tests stub heavy ML/hardware modules (`mlx_lm`, `mlx_whisper`, `sounddevice`, `outlines`, `Quartz`), which is good for CI but can hide runtime dependency drift. |
| `inbox_mcp_readonly.py:44-50` | `read_daily_note()` references `ambient_notes.VAULT_DIR`, but `ambient_notes.py` defines `VAULT_PATH`, `DAILY_DIR`, and `AMBIENT_DIR`; this looks like a stale symbol. |
| Command observation | `git ls-files | wc -l` returned `196`; `git ls-files .factory | wc -l` returned `85`; `du -sh .factory uv.lock tests .` returned `424K`, `432K`, `568K`, `2.4M`. |

## Dependency surface map

### Python and package management

- Package manager: `uv`; lockfile: `uv.lock`; local Python pin file:
  `.python-version` contains `3.12`.
- Runtime dependencies are centralized in `pyproject.toml`, but runtime imports
  also include transitive or optional packages not directly declared:
  `requests` (`services.py:1052`), `CoreLocation` (`services.py:3488`),
  `UserNotifications` through dynamic import (`services.py:5524-5528`), and
  `objc` through dynamic import (`services.py:5524`).
- `requests` is present in `uv.lock` as a transitive package (`uv.lock:2200`),
  but relying on it transitively is fragile if Google dependency versions move.
- The lockfile contains expensive ML packages (`mlx`, `mlx-lm`, `mlx-whisper`,
  `torch`, CUDA/NVIDIA packages behind Linux markers). These are runtime deps
  even though tests stub many of them.
- The README and package metadata disagree on Python support:
  `README.md:31-33` says Python 3.10+, while `pyproject.toml:5` says
  `>=3.12,<3.15`.
- `.factory/library/environment.md:12` claims Python 3.12+ and says
  "currently 3.14.3 installed", which is another environment claim that may be
  local and stale.

### Runtime entrypoints and scripts

- `README.md:36-45` documents `uv run python inbox.py` and
  `uv run python inbox_server.py`.
- `dev.sh` defaults worktrees to `INBOX_SERVER_PORT=9850` and derives
  `INBOX_SERVER_URL` from it, then execs `uv run python`.
- `scripts/run_inbox_backend.sh`, `scripts/run_inbox_mcp_http.sh`,
  `scripts/run_inbox_mcp_http_readonly.sh`,
  `scripts/run_inbox_mcp_stdio.sh`, and
  `scripts/run_inbox_mcp_stdio_readonly.sh` all set `UV_CACHE_DIR` to
  `/tmp/uv-cache` by default and launch the corresponding Python entrypoint.
- `scripts/setup_inbox_mcp.sh` copies `config/inbox.env.example` to
  `config/inbox.env`, chmods it to 600, and installs launchd agents on macOS.
  That is useful but mutates user-level service state and should not be run by
  unattended audit workers.
- `batch/batch-runner.sh` maintains `batch/archive-state.tsv` and `batch/logs/`
  and performs Gmail archive operations via curl. Its generated outputs are
  ignored, while `batch/archive-input.tsv` is tracked and currently only has a
  header.
- `organize-inbox-helper.sh` can start the backend in the background and then
  invoke `uv run python organize_inbox.py`; this is a live Gmail label workflow,
  not an agent-safe validation command.

### Environment variables and secret files

Known env vars from code and config:

- `INBOX_SERVER_PORT`: backend port defaulting to 9849.
- `INBOX_SERVER_URL`: client/MCP backend target defaulting to
  `http://127.0.0.1:9849`.
- `INBOX_SERVER_TOKEN`: optional private REST API bearer token.
- `INBOX_MCP_TOKEN`: optional public MCP bearer token.
- `INBOX_MCP_READONLY_PORT`: read-only HTTP MCP port defaulting to 8001.
- `INBOX_MEMORY_DB`: optional MCP memory sqlite path.
- `INBOX_DEFAULT_GOOGLE_ACCOUNT`: write-routing override for Google services.
- `INBOX_TEST_MODE`, `INBOX_TEST_DATA_DIR`, `INBOX_TEST_NOW`: test safety and
  deterministic data controls.
- `INBOX_PRE_WARM_CONVERSATIONS`: startup pre-warm switch.
- `INBOX_DISABLE_AMBIENT`: disables ambient autostart.
- `INBOX_HOME_ADDRESS`: fallback origin for maps/departure features.
- `GOOGLE_CLOUD_API_KEY`, `GOOGLE_MAPS_API_KEY`, `GEMINI_API_KEY`: optional
  API-backed feature keys.
- `MLX_LARGE_MODEL`: alternate MLX model setting.
- `INBOX_POLL_INTERVAL`: TUI polling interval.

Secret/local files:

- `credentials.json`: Google OAuth client secret.
- `token.json`: legacy Google token.
- `tokens/*.json`: per-account Google tokens.
- `github_token.txt`: GitHub PAT.
- `google_maps_key.txt`: Google Maps key fallback.
- `gemini_api_key.txt`: Gemini key fallback.
- `config/inbox.env`: local private env file.
- `.env`, `.env.local`, `.envrc`, `*.key`, and `*.secret`: ignored.

### Local data, generated artifacts, and caches

Local personal data paths:

- `~/Library/Messages/chat.db`
- `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite`
- `~/Library/Group Containers/group.com.apple.reminders/Container_v1/Stores/Data-*.sqlite`
- `~/Library/Application Support/AddressBook/Sources/*/AddressBook-v22.abcddb`
- `~/vault/daily/` and `~/vault/ambient/`
- `~/Downloads/` for Drive downloads
- `~/.config/inbox/notifications.json`
- `~/.config/inbox/favorites.json`
- `~/.config/inbox/voice.json`

Repo-local generated or persistent state:

- `.inbox_memory.sqlite3`
- `.inbox_scheduler.sqlite3`
- `.inbox_index.sqlite3`
- `server.log`
- `.coverage`, `htmlcov/`
- `batch/archive-state.tsv`, `batch/logs/`, `batch/.batch-state.lock`
- `.venv`, `.tldr/`, `.claude/`

Tracked generated-looking state:

- `.factory/` contains 85 tracked files and about 424K of library and validation
  outputs. It is part of the current handoff surface even though much of it
  looks derived. `.factory/services.yaml` also contains commands that differ
  from `docs/TESTING_FOR_AGENTS.md`, so future agents may choose different
  proof commands depending on which file they read first.

### MCP and service exposure

- Private backend binds to `127.0.0.1` in `inbox_server.py:3939-3940`.
- Full MCP HTTP server uses `mcp_server.py`; read-only HTTP server uses
  `inbox_mcp_readonly.py`.
- `mcp_gateway.py` has optional bearer auth. If `INBOX_MCP_TOKEN` is absent, the
  public MCP layer authorizes requests.
- `.mcp.json` and `.cursor/mcp.json` are checked in and point at port 9849.
  That is convenient for primary local use but easy to misuse in a worktree if
  `INBOX_SERVER_URL` is not overridden.
- `deploy/Caddyfile.example` exposes only `/health` and `/mcp` for full and
  read-only hostnames; deployment examples source `config/inbox.env`.

## Risks and stale assumptions

1. Python version claims conflict.
   README says Python 3.10+ (`README.md:31-33`), `.python-version` says 3.12,
   `.factory/library/environment.md:12` says Python 3.12+ with a local 3.14.3
   note, and `pyproject.toml:5` requires `>=3.12,<3.15`. A new agent or user
   following README on Python 3.10/3.11 will hit resolver or syntax failures.

2. Heavy runtime dependencies are not separated from core server/TUI paths.
   `mlx-lm`, `mlx-whisper`, `sounddevice`, `outlines`, `torch`, and platform
   wheels are part of the base runtime lock. Tests stub several of them, so CI
   may pass while a fresh runtime install fails or becomes much larger than
   expected. This matters for simple backend/MCP use cases that do not need
   ambient audio or local LLM features.

3. Some imports are transitive or optional but not explicitly declared.
   `services.py` imports `requests` directly, but `pyproject.toml` does not
   declare it. CoreLocation and UserNotifications are also used without direct
   pyobjc framework declarations. Because `pyproject.toml:51` enables
   `reportMissingImports`, this is likely to surface in typecheck or fresh
   installs.

4. Auth defaults are permissive when tokens are unset.
   `inbox_server.py:1317-1325` and `mcp_gateway.py:36-45` both allow all
   requests if their token env vars are empty. That is acceptable for a loopback
   private service, but dangerous if deployment or Caddy exposure happens before
   `INBOX_SERVER_TOKEN` and `INBOX_MCP_TOKEN` are set.

5. Worktree routing can silently talk to the primary inbox.
   `dev.sh` supports alternate ports, but checked-in MCP configs point at
   `127.0.0.1:9849`. The docs warn about this, but there is no validation guard
   proving an MCP client's `cwd` and `INBOX_SERVER_URL` match the target
   worktree. This is especially risky because the app operates on personal data.

6. Validation instructions disagree and may be stale.
   `docs/TESTING_FOR_AGENTS.md` recommends `INBOX_TEST_MODE=1 uv run pytest -m
   safe`, while `.factory/services.yaml` recommends pytest with audio/LLM tests
   ignored, and `DOCS_INDEX.md:42-44` claims `uv run pytest` had 736 passing
   tests. The repo currently has 31 test files, and this audit did not verify
   that 736-pass claim.

7. Read-only MCP has a stale ambient note path symbol.
   `inbox_mcp_readonly.py:47` references `ambient_notes.VAULT_DIR`, but
   `ambient_notes.py:14-16` defines `VAULT_PATH`, `DAILY_DIR`, and
   `AMBIENT_DIR`. This is a narrow runtime break in the supposedly safer
   read-only surface.

8. Local state creation is broad and partly hidden behind "read" paths.
   `google_auth_all()` creates `tokens/`, memory/index/scheduler constructors
   create sqlite files, notification/voice config loaders create config files,
   and service wrappers create `/tmp` logs/caches. That is manageable but should
   be explicit in any automated validation or deploy runner.

## Validation command candidates

Required validation for this queue item:

```bash
git status --short
```

Observed status after this report was written: exit 0 with only
`docs/overnight/` shown as untracked, because the report itself is the sole
worktree change.

```text
?? docs/overnight/
```

Useful follow-up validation candidates:

| Command | Expected status | Notes |
| --- | --- | --- |
| `git status --short --untracked-files=all` | Pass | Should identify `docs/overnight/inbox-sym-116-dependency-surface.md` exactly. |
| `uv lock --check` | Probably pass | Confirms `pyproject.toml` and `uv.lock` agree without changing the lock. Run before dependency edits. |
| `INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py -q` | Should pass | Focused safety test for env redirection and live-write blocking. May create local uv/venv cache if deps are missing. |
| `INBOX_TEST_MODE=1 uv run pytest -m safe` | Should pass if safe markers are complete | Agent-safe suite per docs, but coverage addopts and dependency install cost may be nontrivial. |
| `uv run ruff check .` | Unknown, intended pass | Lint command from docs and factory metadata. |
| `uv run pyright` | Risk of failure | Potential missing direct deps/imports: `requests`, CoreLocation, UserNotifications, and dynamic optional modules. |
| `uv run pytest --ignore=tests/test_audio.py --ignore=tests/test_llm.py -x -q` | Unknown | Factory's faster test command, but differs from agent-safe docs and may still touch broad service code. |
| `INBOX_TEST_MODE=1 INBOX_TEST_DATA_DIR=$(mktemp -d) uv run pytest tests/test_inbox_test_mode.py tests/test_mcp_gateway.py -q` | Should pass | Good proof that test-mode state stays out of personal paths and MCP auth behavior remains covered. |

## Next safe work

1. Normalize Python/runtime dependency declarations.
   Acceptance criteria: README, `.python-version`, `.factory/library/environment.md`,
   and `pyproject.toml` agree on Python support; direct imports have direct
   dependencies or explicit optional import guards; lockfile remains consistent.
   Suggested validation: `uv lock --check`, `uv run pyright`, and
   `INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py -q`.

2. Split heavy ML/audio dependencies into optional extras or a documented
   profile.
   Acceptance criteria: backend/MCP/text TUI install path does not require
   audio/LLM wheels; ambient/dictation/autocomplete paths fail with clear
   feature-unavailable messages when optional deps are absent; tests still stub
   hardware dependencies deliberately.
   Suggested validation: a fresh sync for core deps, `uv run pyright`, and
   focused tests in `tests/test_audio.py`, `tests/test_llm.py`, and
   `tests/test_voice_pipeline.py` under `INBOX_TEST_MODE=1`.

3. Add a dependency/state manifest for agent-safe runs.
   Acceptance criteria: one docs page lists env vars, secret files, local data
   paths, generated repo files, user-home writes, external APIs, and commands
   that can mutate personal data; `docs/TESTING_FOR_AGENTS.md` links to it.
   Suggested validation: `uv run ruff check .` if docs-only lint is configured,
   plus `git status --short --untracked-files=all`.

4. Make MCP routing self-checking for worktrees.
   Acceptance criteria: a cheap health or diagnostic command reports backend
   URL, repo cwd, port, and auth-enabled state; docs/config examples guide
   primary vs dev routing without hardcoded stale paths.
   Suggested validation: unit test around MCP config/health payload and
   `INBOX_TEST_MODE=1 uv run pytest tests/test_mcp_gateway.py -q`.

5. Fix and test read-only MCP ambient note path.
   Acceptance criteria: `read_daily_note()` uses a defined ambient notes path,
   returns missing-note responses without exceptions, and remains read-only.
   Suggested validation: add or extend a focused read-only MCP test, then run
   `INBOX_TEST_MODE=1 uv run pytest tests/test_mcp_gateway.py tests/test_ambient_notes.py -q`.

6. Reconcile validation docs.
   Acceptance criteria: README, DOCS_INDEX, `.factory/services.yaml`, and
   `docs/TESTING_FOR_AGENTS.md` distinguish required full validation from
   agent-safe validation; stale "736 pass" style claims are either refreshed
   with dates/commands or removed.
   Suggested validation: `INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py -q`
   and a docs review diff.

## Non-goals

- No product code edits.
- No dependency upgrades or lockfile changes.
- No `uv sync`, `uv run`, pytest, pyright, ruff, or pre-commit execution.
- No server startup, MCP startup, launchd/systemd setup, Caddy setup, or curl
  calls to localhost services.
- No OAuth flow, token inspection, personal data access, microphone access,
  AppleScript writes, Gmail/Calendar/Drive/Sheets/Docs/Tasks writes, GitHub API
  calls, or external network calls.
- No commits, pushes, PRs, or external tracker updates.

## Unknowns

- Whether a fresh `uv sync` currently succeeds on Python 3.12, 3.13, and 3.14
  across macOS and non-macOS platforms.
- Whether all current tests pass; this audit did not run test/lint/typecheck
  commands beyond the required git-status validation.
- Whether the checked-in `.factory` validation artifacts are current or stale.
- Whether local secret files exist in the primary checkout or this worktree; I
  did not inspect ignored files or user-home credential paths.
- Whether the read-only MCP HTTP surface is deployed anywhere, and if so whether
  `INBOX_MCP_TOKEN` is always set.
- Whether heavy ML model downloads already exist in `~/.cache/huggingface/`; no
  user cache paths were inspected.

## Commands run

```bash
llm-tldr tree .
git status --short --branch
rtk read pyproject.toml
rtk read README.md
rtk read AGENTS.md
git status --ignored --short
rtk grep "os\\.environ|getenv|load_dotenv|INBOX_|GOOGLE|GITHUB|TOKEN|CREDENTIAL|Path.home|~/|subprocess|Popen|uv run|pytest|ruff|pyright" .
git ls-files | sort
rg --files -uu -g '!/.git/**' | sort
rg '^name = ' uv.lock | wc -l
rtk read CLAUDE.md
rtk read docs/TESTING_FOR_AGENTS.md
rtk read .gitignore
rtk read .pre-commit-config.yaml
rtk read .python-version
rtk read config/inbox.env.example
rtk read .env.mcp.example
rtk read .mcp.json
rtk read .cursor/mcp.json
rtk read config/codex.inbox.example.toml
rtk read config/gemini-settings.inbox.example.json
rtk read dev.sh
rtk read scripts/setup_inbox_mcp.sh
rtk read batch/batch-runner.sh
rtk read organize-inbox-helper.sh
rtk read deploy/*.example
rg -n "os\\.environ|getenv|os\\.getenv" -g '*.py'
rg -n "TOKEN_FILE|TOKENS_DIR|credentials\\.json|github_token|google_maps_key|gemini_api_key|\\.sqlite|\\.json|\\.lock|Downloads|vault|Obsidian" -g '*.py' -g '*.md'
rg -n "subprocess\\.run|subprocess\\.Popen|osascript|curl|launchctl|open\\(|webbrowser|requests|httpx" -g '*.py' -g '*.sh'
rg -n "pytest|ruff|pyright|bandit|pre-commit|uv run|safe|live_write|local_data" -g '*.md' -g '*.toml' -g '*.yaml' -g '*.py'
rg -o --no-filename '^(from|import) [A-Za-z0-9_\\.]+' -g '*.py' | sed -E 's/^(from|import) ([A-Za-z0-9_\\.]+).*/\\2/' | cut -d. -f1 | sort -u
rg -n "import (requests|CoreLocation|AppKit|Foundation|Quartz|ApplicationServices|mlx|mlx_lm|mlx_whisper|outlines|sounddevice|textual|rich|fastapi|uvicorn|mcp|google|httpx|pydantic|loguru|numpy)" -g '*.py'
nl -ba pyproject.toml | sed -n '1,80p'
sed -n '1,80p' uv.lock
rg -n '^name = "(inbox|requests|CoreLocation|pyobjc-framework-corelocation|pyobjc-framework-quartz|pyobjc-framework-applicationservices|mlx|mlx-metal|mlx-lm|mlx-whisper|nvidia|cuda|torch|outlines|sounddevice|fastapi|mcp|uvicorn|textual|rich)"' uv.lock
nl -ba services.py | sed -n '50,130p'
nl -ba services.py | sed -n '330,390p'
nl -ba services.py | sed -n '540,660p'
nl -ba services.py | sed -n '2810,2875p'
nl -ba services.py | sed -n '3490,3565p'
nl -ba tests/conftest.py | sed -n '1,120p'
nl -ba inbox_test_mode.py | sed -n '1,90p'
nl -ba tests/test_inbox_test_mode.py | sed -n '1,90p'
nl -ba memory_store.py | sed -n '1,80p'
nl -ba message_index_store.py | sed -n '1,70p'
nl -ba scheduler.py | sed -n '1,80p'
nl -ba ambient_notes.py | sed -n '1,90p'
nl -ba services.py | sed -n '5418,5585p'
nl -ba services.py | sed -n '6088,6135p'
nl -ba inbox_server.py | sed -n '212,245p'
nl -ba inbox_server.py | sed -n '1224,1325p'
nl -ba inbox_server.py | sed -n '3928,3948p'
nl -ba inbox_client.py | sed -n '14,65p'
nl -ba mcp_backend.py | sed -n '1,70p'
nl -ba mcp_gateway.py | sed -n '1,90p'
nl -ba mcp_server.py | sed -n '1,80p'
nl -ba inbox_mcp_readonly.py | sed -n '1,95p'
nl -ba tools_registry.py | sed -n '1,180p'
git ls-files | wc -l
git ls-files .factory | wc -l
du -sh .factory uv.lock tests . 2>/dev/null
rtk read .factory/services.yaml
rtk read .factory/library/environment.md
rtk read batch/archive-input.tsv
rtk read .tldrignore
rtk read DOCS_INDEX.md
rtk read MCP_SETUP.md
git rev-parse HEAD
git branch --show-current
git status --short
mkdir -p docs/overnight
```
