# inbox-sym-118 dependency-surface audit

Queue item: `inbox-sym-118-dependency-surface`
Branch: `codex/goal-inbox-sym-118-dependency-surface`
Audit date: 2026-05-07
Focus area: dependencies, scripts, environment variables, generated artifacts, caches, and local-only state.

## Summary

`inbox-sym-118` is a local-first Python inbox/TUI project with a large integration surface: FastAPI server, Textual TUI, MCP HTTP/stdio gateways, Google OAuth integrations, macOS SQLite data readers, AppleScript/Quartz write paths, local ML/audio, local SQLite stores, and deployment templates for launchd/systemd/Caddy. The dependency surface is not just `pyproject.toml`; successful operation also depends on macOS permissions, local token files, per-checkout generated SQLite databases, port routing, and several path-pinned helper scripts.

The repo was clean before writing this report. No ignored local credential/state files were present in this isolated worktree during the audit, but `.gitignore` shows many are expected in a real checkout.

## Repo State

- Purpose: README describes a privacy-first terminal UI for iMessage, Gmail, Calendar, Sheets, Notes, Reminders, GitHub, Drive, ambient audio, dictation, and local ML. Evidence: `README.md`, `CLAUDE.md`, `services.py`, `inbox_server.py`, `inbox.py`, `mcp_server.py`.
- Current branch: `codex/goal-inbox-sym-118-dependency-surface`.
- Starting HEAD: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`.
- Starting dirty state: `git status --short --branch` printed only `## codex/goal-inbox-sym-118-dependency-surface`; `git status --porcelain=v1` printed nothing.
- Remote: `origin https://github.com/jwalin-shah/inbox.git`.
- Upstream: `git rev-parse --abbrev-ref --symbolic-full-name @{u}` printed nothing, so this branch has no configured upstream.
- Recent HEAD observation: `git log --oneline --decorate -5` shows HEAD at merge commit `2805b84` from `origin/main` and many goal branches pointing at the same commit.

## Commands Run

- `llm-tldr tree .` to map visible top-level structure.
- `git status --short --branch` and `git status --porcelain=v1` for dirty state.
- `git rev-parse --show-toplevel`, `git rev-parse --abbrev-ref HEAD`, and `git rev-parse HEAD` for repo/branch/commit identity.
- `rtk read pyproject.toml`, `README.md`, `CLAUDE.md`, `docs/TESTING_FOR_AGENTS.md`, `.gitignore`, config examples, scripts, deploy examples, and selected code files.
- `llm-tldr search "os.environ|os.getenv|environ.get|getenv|dotenv|INBOX_|TOKEN|credentials.json|token.json|tokens/|github_token|gemini_api_key|google_maps_key|sqlite|.sqlite|Path.home|expanduser|Library/|vault|UV_CACHE_DIR" .` for env/local-state discovery.
- `rg -n "os\.environ|os\.getenv|environ\.get|getenv|load_dotenv|INBOX_|TOKEN|credentials\.json|token\.json|tokens/|github_token|gemini_api_key|google_maps_key|\.sqlite|Path\.home|expanduser|Library/|vault|UV_CACHE_DIR" -g '!uv.lock' -g '!docs/overnight/**' .` for exact code/doc hits.
- `rg --files -uu -g '!.git/**'` showed 197 files visible including hidden tracked `.factory`, `.cursor`, `.mcp.json`, `.env.mcp.example`, `.pre-commit-config.yaml`, `.python-version`, and `.tldrignore`.
- `git ls-files --others --ignored --exclude-standard | sed 's#/.*##' | sort | uniq -c` printed no ignored local files in this worktree.
- `wc -l uv.lock pyproject.toml` found `uv.lock` at 2847 lines and `pyproject.toml` at 66 lines.
- `rg '^name = ' uv.lock | ...` found 148 locked package names.
- `rg -o "INBOX_[A-Z0-9_]+|GOOGLE_[A-Z0-9_]+|GEMINI_[A-Z0-9_]+|UV_CACHE_DIR" ...` found the env var inventory listed below.
- `rg -n "Tool\(" tools_registry.py | wc -l` found 60 registered MCP tool definitions.
- `rg -n "pytestmark = pytest.mark.safe|@pytest.mark.safe" tests -g '*.py'` found only two safe-marked test modules.
- `du -sh . .factory uv.lock tests scripts config deploy docs` found the repo at 2.4M, `.factory` at 424K, `uv.lock` at 432K, and tests at 568K.

## Package Surface

Primary package metadata is in `pyproject.toml`:

- Python: `requires-python = ">=3.12,<3.15"` in `pyproject.toml`; `.python-version` pins `3.12`; `uv.lock` repeats `requires-python = ">=3.12, <3.15"` and has resolution markers for Python 3.12, 3.13, and 3.14.
- Runtime dependencies: FastAPI, Google API/OAuth/Gemini clients, httpx, loguru, `mcp[cli]`, MLX LLM/Whisper, numpy, outlines, pydantic, PyObjC ApplicationServices/Quartz, python-multipart, rich, sounddevice, Textual, uvicorn.
- Dev dependencies: bandit, hypothesis, pre-commit, pyright, pytest, pytest-cov, python-dotenv, ruff.
- Tool configs: Ruff targets `py312`; Pyright targets Python 3.12 with basic checking; pytest default addopts include coverage; Bandit excludes `.venv` and `tests` and skips several subprocess/assert-related checks.
- Lockfile: `uv.lock` has 148 package names, all observed package sources are PyPI registry entries, and the lock includes heavy transitive packages from ML/Outlines/Torch, including CUDA/NVIDIA/Triton packages marked for Linux and MLX/Metal packages marked for Darwin.

Stale assumption: `README.md` says requirements are Python 3.10+, but `pyproject.toml`, `.python-version`, and actual generic function syntax in `services.py` require Python 3.12.

## Runtime Dependency Clusters

- Server/API: `inbox_server.py` imports FastAPI, Pydantic, loguru, and wraps `services.py`; it binds to `127.0.0.1` and `INBOX_SERVER_PORT` with default port 9849.
- TUI/client: `inbox.py` imports Textual/Rich/httpx and uses `InboxClient`; `inbox_client.py` can auto-start `inbox_server.py` through `subprocess.Popen`.
- MCP: `mcp_server.py`, `inbox_mcp_stdio.py`, `inbox_mcp_readonly.py`, `inbox_mcp_readonly_stdio.py`, `mcp_gateway.py`, `mcp_backend.py`, and `tools_registry.py` provide HTTP and stdio MCP entrypoints.
- Google APIs: `services.py` declares broad `GOOGLE_SCOPES` for Gmail read/modify/send/settings, Calendar, Drive, Sheets, Docs, and Tasks. Tokens are per-account JSON files under `tokens/`.
- macOS local data: `services.py` and `contacts.py` read iMessage, Notes, Reminders, and AddressBook SQLite files under `~/Library/...`.
- macOS write paths: `services.py` uses AppleScript for iMessage, Notes, Reminders, and notifications; Quartz CGEvent for WhatsApp/dictation keyboard injection; `open -a WhatsApp`; and CoreLocation for location fallback.
- ML/audio: `services.py` uses MLX model ids, `mlx_lm`, `mlx_whisper`, `sounddevice`, and a hardcoded `/opt/homebrew/bin/whisper-stream` dictation binary.
- Local persistent stores: `memory_store.py`, `message_index_store.py`, and `scheduler.py` create repo-local SQLite files by default.

## Environment Variables

Observed env vars from code, docs, config examples, and scripts:

- `INBOX_SERVER_URL`: client/MCP backend URL, defaulting to localhost port 9849.
- `INBOX_SERVER_PORT`: server/client port selection, default 9849; `dev.sh` defaults this to 9850.
- `INBOX_SERVER_TOKEN`: optional private backend bearer token. If unset, server auth allows requests.
- `INBOX_MCP_TOKEN`: optional public MCP gateway bearer token. If unset, MCP gateway allows non-health requests.
- `INBOX_MCP_READONLY_PORT`: read-only MCP HTTP port, default 8001.
- `INBOX_MEMORY_DB`: optional MCP memory-store SQLite path override.
- `INBOX_TEST_MODE`: blocks representative live writes and redirects some local data paths.
- `INBOX_TEST_DATA_DIR`: test-local token, SQLite, and config root.
- `INBOX_TEST_NOW`: date/time override used by tests.
- `INBOX_DEFAULT_GOOGLE_ACCOUNT`: write-routing hint for Google account selection.
- `INBOX_PRE_WARM_CONVERSATIONS`: startup cache warmup flag.
- `INBOX_DISABLE_AMBIENT`: disables ambient autostart.
- `INBOX_HOME_ADDRESS`: fallback origin for location/departure calculations.
- `INBOX_LLM_LARGE`: large MLX model id override.
- `INBOX_POLL_INTERVAL`: TUI polling interval.
- `GOOGLE_CLOUD_API_KEY` and `GOOGLE_MAPS_API_KEY`: Maps/cloud API key fallbacks.
- `GEMINI_API_KEY`: Gemini fallback/specific-task API key.
- `UV_CACHE_DIR`: wrapper scripts default this to `/tmp/uv-cache`.

## Local Files, State, Caches, and Artifacts

Tracked examples and ignore rules show the intended local-only state:

- Secrets/tokens ignored by `.gitignore`: `credentials.json`, `token.json`, `token.json.lock`, `tokens/`, `github_token.txt`, `google_maps_key.txt`, `gemini_api_key.txt`, `config/inbox.env`, `.env`, `.env.local`, `.envrc`, `*.key`, `*.secret`.
- Repo-local SQLite ignored by `.gitignore`: `.inbox_memory.sqlite3`, `.inbox_scheduler.sqlite3`, `.inbox_index.sqlite3`.
- User config/state outside repo: `~/.config/inbox/notifications.json`, `~/.config/inbox/favorites.json`, `~/.config/inbox/voice.json`, `~/vault/daily`, and `~/vault/ambient`.
- Local personal data read surfaces: `~/Library/Messages/chat.db`, `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite`, `~/Library/Group Containers/group.com.apple.reminders/Container_v1/Stores/Data-*.sqlite`, and `~/Library/Application Support/AddressBook/...`.
- Generated/test/cache ignores: `__pycache__/`, `.coverage`, `htmlcov/`, `.tldr/`, `.claude/`, `batch/triage-output.tsv`, `batch/archive-state.tsv`, `batch/logs/`, `batch/.batch-state.lock`, `CLAUDE.md.new`.
- Tracked generated/planning artifacts: `.factory` is tracked and contains 85 files, including validation synthesis JSON files. This is repo context, not local cache.
- Current isolated worktree observation: no ignored files were present according to `git ls-files --others --ignored --exclude-standard`.

## Entrypoints and Scripts

- `README.md` and `CLAUDE.md`: `uv run python inbox.py` starts server plus TUI; `uv run python inbox_server.py` starts server only.
- `dev.sh`: sets `INBOX_SERVER_PORT=9850` and derives `INBOX_SERVER_URL` unless overridden, then runs `uv run python "${1:-inbox.py}"`.
- `scripts/run_inbox_backend.sh`: sets `UV_CACHE_DIR=/tmp/uv-cache` if unset and runs `uv run python inbox_server.py`.
- `scripts/run_inbox_mcp_http.sh`: runs `uv run python mcp_server.py`.
- `scripts/run_inbox_mcp_http_readonly.sh`: runs `uv run python inbox_mcp_readonly.py`.
- `scripts/run_inbox_mcp_stdio.sh`: runs `uv run python inbox_mcp_stdio.py`.
- `scripts/run_inbox_mcp_stdio_readonly.sh`: runs `uv run python inbox_mcp_readonly_stdio.py`.
- `scripts/setup_inbox_mcp.sh`: copies `config/inbox.env.example` to `config/inbox.env`, chmods it 600, installs launchd plists to `~/Library/LaunchAgents`, and loads backend/full/read-only services.
- `deploy/*.plist.example` and `deploy/*.service.example`: path-pin `/Users/jwalinshah/projects/inbox`, use `config/inbox.env`, and write logs to `/tmp`.
- `.factory/init.sh` and `.factory/services.yaml`: also path-pin `/Users/jwalinshah/projects/inbox`; `.factory/init.sh` can kill anything listening on port 9849.
- `batch/batch-runner.sh`: defaults to live archive mode, writes ignored state/logs, and calls `/gmail/batch-modify`.
- `unsubscribe_*.py` scripts call the live localhost server and can unsubscribe/archive Gmail after prompts or batches.
- `oci_retry.sh`: launches an OCI compute instance in a loop using hardcoded OCIDs, hardcoded SSH key path, and log path under `/Users/jwalinshah/projects/inbox/oci_retry.log`.

## Concrete Risks and Stale Assumptions

1. Python version claim is stale. `README.md` says Python 3.10+, while `pyproject.toml`, `.python-version`, `uv.lock`, and syntax in `services.py` require Python 3.12. A user following README on 3.10 will fail before app behavior is tested.

2. Some direct runtime imports rely on transitive or undeclared optional packages. `services.py` imports `requests` inside unsubscribe logic while `requests` is not a direct dependency in `pyproject.toml`; `mcp_gateway.py` imports Starlette directly while Starlette is transitive through FastAPI/MCP; `services.py` dynamically imports `CoreLocation`, `objc`, and `UserNotifications` but only ApplicationServices/Quartz PyObjC packages are directly declared. Optional fallback behavior hides this until a feature path runs.

3. Auth defaults are permissive. `inbox_server.py` permits all requests when `INBOX_SERVER_TOKEN` is unset; `mcp_gateway.py` permits all non-health MCP routes when `INBOX_MCP_TOKEN` is unset. This is fine for private localhost, but dangerous if Caddy or service templates are copied without token setup.

4. Google scope surface is very broad. `GOOGLE_SCOPES` includes Gmail modify/send/settings, full Calendar, Drive, Sheets, Docs, and Tasks. Tokens are local per-checkout files; copying tokens between primary and dev worktrees is documented, but that raises account-routing and accidental-write risk.

5. Service and factory templates path-pin the primary checkout. launchd/systemd examples and `.factory` commands use `/Users/jwalinshah/projects/inbox`, while the current work happens in an isolated worktree. Running those templates from a worktree can hit the daily-driver checkout or kill the primary port 9849 service.

6. The read-only MCP daily-note tool appears broken and untested. `inbox_mcp_readonly.py` refers to `ambient_notes.VAULT_DIR`, but `ambient_notes.py` defines `VAULT_PATH`, `DAILY_DIR`, and `AMBIENT_DIR`; `rg` found no direct test for this read-only tool path.

7. The documented safe test command has narrow coverage. `docs/TESTING_FOR_AGENTS.md` recommends `INBOX_TEST_MODE=1 uv run pytest -m safe`, but only `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py` are safe-marked. Most deterministic tests are unmarked and will be skipped by that command.

8. Local ML/audio is both large and platform-sensitive. `uv.lock` includes MLX, MLX Metal, Torch/Transformers/Outlines transitive packages, plus Linux CUDA/NVIDIA/Triton packages behind markers. Runtime also depends on microphone access, Accessibility permissions, and `/opt/homebrew/bin/whisper-stream`, none of which are proven by dependency install alone.

9. Live helper scripts are easy to run against real data. `batch/batch-runner.sh` defaults to non-dry-run archive processing once input exists; `unsubscribe_all_newsletters.py` and related tools call live server endpoints; `organize-inbox-helper.sh` can start the primary port 9849 server and then modify Gmail labels.

10. `oci_retry.sh` is a destructive/external compute surface in the repo. It is not part of inbox runtime, contains cloud resource identifiers and a personal SSH key path, writes outside the worktree, and would launch a VM if run in an authenticated environment.

## Validation Map Notes

Required queue validation:

- `git status --short`
- Expected final status if the report is committed: command exits 0 and prints nothing.
- Expected status before commit: command exits 0 and shows only the new report path.

Useful dependency-surface validation candidates:

- `uv lock --check`
  - Expected: pass if `pyproject.toml` and `uv.lock` are synchronized.
  - Risk: may depend on current `uv` behavior/version, but should not touch live personal data.

- `INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py -q`
  - Expected: pass; proves test-mode data redirection and live-write guard.
  - Risk: may create temp test data only.

- `INBOX_TEST_MODE=1 uv run pytest -m safe -q`
  - Expected: pass, but currently covers only two safe-marked modules.
  - Risk: low; coverage is narrower than docs imply.

- `uv run ruff check .`
  - Expected: should pass for a clean implementation branch.
  - Risk: purely static, but may flag existing style in generated/planning files if scope is not configured.

- `uv run pyright`
  - Expected: should pass or expose missing imports from optional/transitive packages.
  - Risk: higher signal for dependency surface, but may be noisy due dynamic APIs and mocks.

- `bash -n dev.sh scripts/*.sh batch/batch-runner.sh organize-inbox-helper.sh oci_retry.sh`
  - Expected: pass syntax checks without running live operations.
  - Risk: only shell syntax, not safety.

- `INBOX_TEST_MODE=1 uv run pytest tests/test_mcp_gateway.py -q`
  - Expected: pass; validates MCP auth defaults and memory DB override behavior.
  - Risk: low; uses local test client and temp DB.

## Next Safe Work

1. Align Python/runtime dependency claims.
   - Acceptance criteria: `README.md`, `CLAUDE.md`, `.python-version`, `pyproject.toml`, and `uv.lock` all agree on Python 3.12+; README no longer says Python 3.10+; direct feature requirements mention macOS-only surfaces.
   - Validation: `uv lock --check`; `INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py -q`.

2. Create a dependency/environment manifest.
   - Acceptance criteria: add a docs page listing required Python deps, optional feature deps, env vars, local files, macOS permissions, external CLIs/binaries, and live-write commands; link it from `DOCS_INDEX.md` or README.
   - Validation: `uv run ruff check .`; `bash -n dev.sh scripts/*.sh batch/batch-runner.sh organize-inbox-helper.sh oci_retry.sh`.

3. Make optional/direct dependencies explicit.
   - Acceptance criteria: either declare direct imports (`requests`, Starlette if intentionally direct, relevant PyObjC framework packages) or refactor to avoid relying on transitive packages; document `whisper-stream` as an external binary rather than a Python dependency.
   - Validation: `uv lock --check`; `uv run pyright`; focused tests for unsubscribe, MCP gateway, notification, and location fallback paths.

4. Harden worktree-safe service templates.
   - Acceptance criteria: deploy examples and `.factory` commands avoid hardcoded primary checkout paths or clearly mark them primary-only; worktree examples require explicit `INBOX_SERVER_PORT` and `INBOX_SERVER_URL`; no template kills port 9849 without an explicit primary-service action.
   - Validation: `bash -n scripts/*.sh dev.sh`; manual review of `deploy/*.example`, `.factory/init.sh`, `.factory/services.yaml`.

5. Expand safe test markers.
   - Acceptance criteria: deterministic tests that use mocks/temp DBs are marked `safe`; `INBOX_TEST_MODE=1 uv run pytest -m safe -q` covers more than just test-mode and MCP gateway smoke tests; docs state what remains excluded.
   - Validation: `INBOX_TEST_MODE=1 uv run pytest -m safe -q`; `rg -n "pytestmark = pytest.mark.safe|@pytest.mark.safe" tests -g '*.py'`.

6. Fix and test read-only MCP daily-note path.
   - Acceptance criteria: `inbox_mcp_readonly.py` uses existing `ambient_notes` path constants or public helpers; date-specific daily note reads work; a safe unit test covers missing and present notes.
   - Validation: `INBOX_TEST_MODE=1 uv run pytest tests/test_mcp_gateway.py tests/test_ambient_notes.py -q` plus a new focused read-only MCP test.

7. Decide whether `oci_retry.sh` belongs in this repo.
   - Acceptance criteria: either remove/move it to a private ops location, or gate it behind explicit docs and safe defaults; no hardcoded tenancy/subnet/image IDs or personal SSH key path remain in the inbox product repo.
   - Validation: `git grep -n "ocid1\\|oci compute instance launch\\|/Users/jwalinshah/.ssh"`.

## Non-Goals

- No product code was changed for this audit.
- No secrets, tokens, local SQLite databases, or user data files were opened.
- No tests, servers, MCP services, deploys, OAuth flows, external APIs, cloud jobs, or live-write helper scripts were run.
- No external tracker state was changed.
- No PR was created or merged.

## Handoff Notes

- Changed file: `docs/overnight/inbox-sym-118-dependency-surface.md`.
- Required validation run after report creation: `git status --short` exited 0 and printed `?? docs/overnight/`.
- Commit status: attempted to stage the report with `git add docs/overnight/inbox-sym-118-dependency-surface.md`, but Git could not create `/Users/jwalinshah/projects/inbox/.git/worktrees/inbox-sym-118-dependency-surface/index.lock` due sandbox write permissions. The worktree content is inside the writable root, but the linked Git metadata is outside it.
- Commit SHA: no new commit was created. Current HEAD remains `2805b8400519da188ca7d3f6e39b19a8ca42b05a`.
- PR URL: none created.

## Unknowns

- Whether the primary checkout currently has real `tokens/`, `credentials.json`, `github_token.txt`, or local SQLite stores; this worktree had none.
- Whether the installed local machine has `/opt/homebrew/bin/whisper-stream`, MLX models cached, microphone permission, Accessibility permission, Full Disk Access, and Location Services permission.
- Whether launchd/systemd/Caddy templates are actually used in production or are historical examples.
- Whether `.factory` is an active workflow contract or historical generated context.
- Whether the broad Google OAuth scope set is intentional for all accounts or should be split by feature.
