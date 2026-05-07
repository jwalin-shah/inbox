# inbox-sym-30 Risk and Validation Review

Queue item: `inbox-sym-30-risk-and-validation-review`
Branch: `codex/goal-inbox-sym-30-risk-and-validation-review`
Review date: 2026-05-07

## Scope and Method

This pass reviewed repo-local evidence only: docs, tests, scripts, config, generated `.factory` validation outputs, package metadata, and current git state. Product code was not edited.

The queue referenced `items/inbox-sym-30-risk-and-validation-review/ISSUE.md`, but that file is not present in this worktree. The issue body supplied in the Goal Pack prompt was used as the task contract.

## Current State

- `git branch --show-current` returned `codex/goal-inbox-sym-30-risk-and-validation-review`.
- `git status --short` was clean before this report was written.
- `git rev-parse HEAD` returned `2805b8400519da188ca7d3f6e39b19a8ca42b05a`.
- No `.github/` directory is present, so no repo-local GitHub Actions workflow was available to inspect.
- No prior `docs/overnight/` report exists in this worktree. Prior generated review evidence is under `.factory/validation/`.

## Concrete File-Path Observations

1. `README.md` and `CLAUDE.md` describe a privacy-first localhost FastAPI server plus Textual TUI with live iMessage, Gmail, Calendar, Drive, Notes, Reminders, GitHub, audio, and local ML integrations. This is a high-risk personal-data app, so default validation must avoid live stores and external writes.

2. `inbox_server.py` has an auth middleware that allows every request when `INBOX_SERVER_TOKEN` is unset. `README.md`, `CLAUDE.md`, `config/inbox.env.example`, `.mcp.json`, and `.cursor/mcp.json` all document token-based auth, but the default remains optional.

3. `inbox_client.py` auto-starts `inbox_server.py` and writes `server.log` when the server is not running. `CLAUDE.md` and `dev.sh` correctly steer worktrees to alternate ports, but `.factory/services.yaml` still starts the daily-driver checkout at `/Users/jwalinshah/projects/inbox` on port `9849`.

4. `tools_registry.py` centralizes MCP tool registration and marks write tools with `confirm=True`; `inbox_mcp_readonly.py` registers only `readonly=True` registry tools plus local read-only daily-note and memory tools. This is a good safety boundary, but it depends on accurate `readonly` flags in one large registry.

5. `docs/TESTING_FOR_AGENTS.md` defines the agent-safe loop as `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, and `uv run pyright`. `pyproject.toml` registers `safe`, `integration`, `local_data`, `slow`, and `live_write` markers.

6. `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py` are the only files found with `pytest.mark.safe`. Many deterministic tests in `tests/` are unmarked, so the documented safe gate currently exercises only a narrow slice of the test suite.

7. `inbox_test_mode.py` provides `assert_live_writes_allowed`, `test_data_dir`, and `test_now`. `services.py` redirects local personal-data paths under `INBOX_TEST_DATA_DIR` when `INBOX_TEST_MODE=1`.

8. `services.py` calls `_assert_live_write_allowed(...)` across many mutation functions, including Gmail, Calendar, Reminders, Tasks, GitHub notifications, Drive, Sheets, Docs, WhatsApp, and desktop notifications. `tests/test_services.py` has representative and extended live-write blocking tests, but not every server endpoint is covered at the HTTP layer.

9. `tests/conftest.py` stubs heavy or platform-specific dependencies such as `mlx_lm`, `mlx_whisper`, `sounddevice`, `Quartz`, and `outlines`, which supports deterministic CI-style tests without real hardware or ML installs.

10. `.factory/services.yaml` defines `test: uv run pytest --ignore=tests/test_audio.py --ignore=tests/test_llm.py -x -q`, while later `.factory/validation/fix-broken-state/*` and `.factory/validation/architecture-hardening/*` outputs repeatedly note that excluding audio and LLM tests can hide regressions.

11. `.pre-commit-config.yaml` configures Ruff, Ruff format, generic pre-commit hooks, and Bandit. Without a `.github/` workflow or another repo-local CI config, these checks appear locally configured but not enforced by a visible remote gate.

12. `message_sync.py` and `message_index_store.py` implement the recent indexed inbox sync path, including Gmail history cursors, timestamp fallback, iMessage rowid checkpoints, resumable bootstrap, and scoped thread rebuilds. `tests/test_message_sync.py` and `tests/test_message_index_store.py` cover these paths well with fake services and temp SQLite DBs.

13. `.gitignore` excludes local credentials, token stores, logs, coverage, `.inbox_index.sqlite3`, `.inbox_memory.sqlite3`, `.inbox_scheduler.sqlite3`, and `.venv`, reducing accidental commits of sensitive or generated state.

14. `.factory/init.sh` is not executable and hard-codes `cd /Users/jwalinshah/projects/inbox`, `uv sync`, and killing port `9849`. `.factory/validation/architecture-hardening/scrutiny/synthesis.json` already records repeated `Permission denied` setup issues for direct execution of this script.

15. `.factory/library/architecture.md` is stale in several places: it says `google_auth_all()` returns three service dicts and lists only older Google scopes, while current code and `CLAUDE.md` include Drive, Sheets, Docs, and Tasks service maps and scopes.

## Risks and Blockers

- Validation is not hermetic in this worker. `uv run` could not use the default cache due sandbox permissions, and with `UV_CACHE_DIR` redirected it attempted to download `textual==8.2.3` but network/DNS is unavailable.
- The documented safe test gate is too narrow because most tests are not marked `safe`.
- The factory default test command excludes audio and LLM tests even though later validation records say those tests were restored and should be part of full-suite validation.
- There is no repo-local CI workflow to prove `pytest`, `ruff`, `pyright`, or Bandit run before merge.
- Optional server auth is convenient for local development but risky for MCP and agent surfaces if the server is exposed beyond loopback or launched with permissive defaults.
- `.factory/init.sh` is unsafe for isolated workers because it targets the main checkout and daily-driver port rather than the current worktree and configured port.
- Some generated `.factory/library` docs are stale relative to current code, which can mislead implementation agents that start from those docs.
- Live personal-data integrations cannot be fully validated without explicit opt-in and credentials, so default validation must remain mocked, temp-dir-backed, or read-only.

## Validation Commands

Commands run during this review:

```bash
git status --short
```

Result before report: exit code 0, clean output.

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe -q
```

Result: blocked before tests by sandbox denial opening `/Users/jwalinshah/.cache/uv/sdists-v9/.git`.

```bash
UV_CACHE_DIR=/private/tmp/uv-cache-inbox-sym-30 INBOX_TEST_MODE=1 uv run pytest -m safe -q
```

Result: blocked before tests because there was no local `.venv`; `uv` attempted to create one and download `textual==8.2.3`, but network/DNS is unavailable.

Useful validation commands once dependencies are available:

```bash
UV_CACHE_DIR=/private/tmp/uv-cache-inbox-sym-30 INBOX_TEST_MODE=1 uv run pytest -m safe -q
uv run pytest -x -q
uv run ruff check .
uv run pyright
uv run bandit -c pyproject.toml -r .
```

## Implementation-Ready Follow-Up Tasks

### 1. Align the repo validation contract

Owned files: `.factory/services.yaml`, `docs/TESTING_FOR_AGENTS.md`, `README.md`, `CLAUDE.md`

Acceptance criteria:
- The documented agent-safe, default, and full validation commands agree across docs and `.factory/services.yaml`.
- The default test command no longer silently excludes `tests/test_audio.py` and `tests/test_llm.py` unless the exclusion is renamed to an explicit fast or partial lane.
- Docs distinguish safe mocked tests from live/local-data tests.

Smallest useful validation:

```bash
rg -n "pytest|test_audio|test_llm|pytest -m safe|pyright|ruff" .factory/services.yaml docs/TESTING_FOR_AGENTS.md README.md CLAUDE.md
```

### 2. Expand and audit `safe` pytest marker coverage

Owned files: `tests/`, `pyproject.toml`, `docs/TESTING_FOR_AGENTS.md`

Acceptance criteria:
- Deterministic tests that use mocks, temp paths, and `INBOX_TEST_MODE=1` are marked `safe`.
- Tests that require local personal data, live provider calls, or live writes are marked `local_data`, `integration`, or `live_write`.
- A small audit test prevents new unmarked live-write tests from slipping into the safe lane.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe -q
```

### 3. Make factory startup worktree-safe

Owned files: `.factory/init.sh`, `.factory/services.yaml`, `.factory/library/environment.md`

Acceptance criteria:
- `.factory/init.sh` runs from the current repo root rather than hard-coded `/Users/jwalinshah/projects/inbox`.
- Startup and stop commands respect `INBOX_SERVER_PORT` and do not kill port `9849` by default from an isolated worktree.
- The script can be run consistently via executable bit or documented `bash .factory/init.sh`.

Smallest useful validation:

```bash
bash -n .factory/init.sh
rg -n "/Users/jwalinshah/projects/inbox|lsof -ti :9849|INBOX_SERVER_PORT" .factory/init.sh .factory/services.yaml .factory/library/environment.md
```

### 4. Add HTTP-layer live-write safety tests

Owned files: `inbox_server.py`, `tests/test_server_endpoints.py`, `tests/test_inbox_test_mode.py`

Acceptance criteria:
- `INBOX_TEST_MODE=1` blocks representative HTTP mutation endpoints before mocked live services are touched.
- Coverage includes Gmail send/read/archive, Calendar create/update/delete, Reminders create/complete/delete, Tasks create/update/delete, Drive/Sheets/Docs writes, GitHub mark-read, and notifications.
- Existing read-only endpoints still work under test mode with temp or mocked data.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_server_endpoints.py tests/test_inbox_test_mode.py -q
```

### 5. Refresh stale architecture and validation library docs

Owned files: `.factory/library/architecture.md`, `.factory/library/environment.md`, `.factory/library/architecture-hardening.md`, `DOCS_INDEX.md`

Acceptance criteria:
- Google service maps, OAuth scopes, shipped tabs, indexed inbox behavior, and MCP surfaces match current code.
- Planned additions no longer list features already present in `README.md`, `CLAUDE.md`, or implemented modules.
- The docs point future workers to `docs/TESTING_FOR_AGENTS.md` for safe validation rules.

Smallest useful validation:

```bash
rg -n "returns three|3 new TUI tabs|gmail.readonly \\+ gmail.send \\+ calendar \\+ drive|test_audio.py|test_llm.py" .factory/library DOCS_INDEX.md
```
