# inbox-sym-117 validation-map audit

Queue item: `inbox-sym-117-validation-map`
Date: 2026-05-07
Focus area: validation-map

## Repo purpose and starting state

`inbox-sym-117` is a Python local-first personal inbox system: a FastAPI backend, Textual TUI, MCP gateway, and service layer for iMessage, Gmail, Google Calendar, Sheets, Docs, Drive, Apple Notes, Reminders, GitHub notifications, audio/ASR, and local/optional LLM workflows. The most validation-sensitive boundary is that many modules touch live personal data or local credentials unless `INBOX_TEST_MODE=1` and mocked services are used.

Starting branch and state:

- `git status --short --branch` returned only `## codex/goal-inbox-sym-117-validation-map`; the worktree started with no tracked modifications.
- `git log --oneline -5` showed starting HEAD `2805b84` (`Merge pull request #34 from jwalin-shah/codex/SYM-9-indexed-defaults`).
- `git ls-files | wc -l` reported 196 tracked files.
- `rg --files tests | wc -l` reported 31 test files.
- `git diff --stat` was empty before this report was written.

## Validation inventory

Declared validation surfaces:

- `pyproject.toml` declares Python `>=3.12,<3.15`, runtime dependencies including FastAPI, Google API clients, Textual, MLX, Outlines, MCP, sounddevice, and PyObjC, plus dev dependencies `pytest`, `pytest-cov`, `ruff`, `pyright`, `bandit`, `hypothesis`, and `pre-commit`.
- `pyproject.toml` configures pytest with `testpaths = ["tests"]` and `addopts = "--cov=. --cov-report=term-missing"`. Any direct `pytest` fallback needs `pytest-cov` or `-o addopts=`.
- `pyproject.toml` registers markers `safe`, `integration`, `local_data`, `slow`, and `live_write`, but marker search found only two module-level safe declarations: `tests/test_inbox_test_mode.py:8` and `tests/test_mcp_gateway.py:18`.
- `docs/TESTING_FOR_AGENTS.md` names the intended agent-safe loop: `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, and `uv run pyright`. It also explicitly forbids live-write tests unless requested.
- `.factory/services.yaml` defines a second validation contract: `uv run pytest --ignore=tests/test_audio.py --ignore=tests/test_llm.py -x -q`, `uv run pytest -x -q`, `uv run pyright`, and `uv run ruff check .`.
- `.pre-commit-config.yaml` configures Ruff, Ruff format, common pre-commit hooks, and Bandit with `bandit[toml]`. Fresh pre-commit runs may need network to fetch hook repos.
- `README.md` and `CLAUDE.md` both list `uv run ruff`, `uv run pyright`, and `uv run pytest` as development commands.
- `scripts/run_inbox_backend.sh` and MCP launch scripts set `UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"`, but `dev.sh`, `README.md`, `CLAUDE.md`, and `docs/TESTING_FOR_AGENTS.md` do not include a writable cache override.

Runtime/test safety surfaces:

- `inbox_test_mode.py` defines `INBOX_TEST_MODE`, `INBOX_TEST_DATA_DIR`, `INBOX_TEST_NOW`, and `assert_live_writes_allowed`.
- `services.py` routes `TOKEN_FILE`, `TOKENS_DIR`, `IMSG_DB`, `NOTES_DB`, and `REMINDERS_DIR` under `test_data_dir()` when `INBOX_TEST_MODE=1`.
- `services.py` imports `assert_live_writes_allowed` via `_assert_live_write_allowed`, but importing `services.py` still requires Google/logging dependencies before many test-mode assertions can run.
- `tests/conftest.py` stubs heavy ML/hardware modules (`mlx_lm`, `mlx_whisper`, `sounddevice`, `outlines`, `Quartz`) but does not stub `google_auth_oauthlib`, `loguru`, `textual`, or `trio`.
- `tests/test_mcp_gateway.py` uses `@pytest.mark.anyio`; without a project environment, AnyIO parameterizes Trio cases and fails if Trio is missing.
- `inbox_server.py` exposes `PORT = 9849` and reads `INBOX_SERVER_PORT` at process start; `dev.sh` defaults worktrees to port 9850.

## Commands run and observed status

| Command | Result | Evidence |
| --- | --- | --- |
| `llm-tldr tree .` | Pass | Mapped Python app structure, `tests/`, `docs/`, launch scripts, and config files. |
| `git status --short --branch` | Pass | Started clean on `codex/goal-inbox-sym-117-validation-map`. |
| `rg --files tests | wc -l` | Pass | 31 test files. |
| `rg -n "pytestmark = pytest.mark.safe\|@pytest.mark..." tests` | Pass | Only `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py` are marked safe. |
| `INBOX_TEST_MODE=1 uv run pytest -m safe -q` | Fail, environment | uv could not initialize `/Users/jwalinshah/.cache/uv` in this sandbox (`Operation not permitted`). |
| `UV_CACHE_DIR=/private/tmp/uv-cache-inbox-sym-117 INBOX_TEST_MODE=1 uv run pytest -m safe -q` | Fail, environment | uv created `.venv/`, then failed to download `google-ai-generativelanguage` because network/DNS is unavailable. |
| `INBOX_TEST_MODE=1 python -m pytest -m safe -q` | Fail, environment | `python` command not found; host command is `python3`. |
| `INBOX_TEST_MODE=1 python3 -m pytest -m safe -q` | Fail, environment | Host pytest lacks `pytest-cov`, so configured `--cov` addopts are unrecognized. |
| `INBOX_TEST_MODE=1 python3 -m pytest -m safe -q -o addopts=` | Fail, collection/deps | Marker selection still collected tests that import missing `google_auth_oauthlib`, `textual`, and `loguru`; 11 collection errors. |
| `INBOX_TEST_MODE=1 python3 -m pytest tests/test_inbox_test_mode.py tests/test_mcp_gateway.py -q -o addopts=` | Mixed | 9 passed, 4 failed: missing `google_auth_oauthlib` for service-import tests and missing `trio` for AnyIO Trio parametrizations. |
| `INBOX_TEST_MODE=1 python3 -m pytest tests/test_mcp_gateway.py -q -o addopts= -k 'not trio'` | Pass | 5 passed, 2 deselected in 0.17s. |
| `INBOX_TEST_MODE=1 python3 -m pytest tests/test_inbox_test_mode.py -q -o addopts= -k 'not services and not google_auth_all'` | Pass | 4 passed, 2 deselected in 0.03s. |
| `UV_CACHE_DIR=/private/tmp/uv-cache-inbox-sym-117 uv run ruff check .` | Fail, environment | uv tried to resolve full dependencies and failed to download `numba` via `mlx-whisper`. |
| `UV_CACHE_DIR=/private/tmp/uv-cache-inbox-sym-117 uv run pyright` | Fail, environment | uv tried to resolve full dependencies and failed to download `google-api-python-client`. |
| `ruff check .` | Pass | Direct host Ruff 0.15.8 returned `All checks passed!`. |
| `pyright` | Fail | Direct host Pyright 1.1.408 returned 116 errors, including missing `textual`, `loguru`, Google OAuth, PyObjC/Quartz, MLX/Outlines, `gemma4_hackathon`, and real type issues. |
| `bandit -q -r . -c pyproject.toml` | Pass with warnings | Exit 0; warnings were about `nosec` comment parsing and suppressed findings. |
| `git status --short --ignored .pytest_cache .ruff_cache .venv` | Pass observation | `.pytest_cache/`, `.ruff_cache/`, and `.venv/` are ignored artifacts from validation attempts. Removing `.venv/` was blocked by sandbox policy. |

## Current validation map

Best command when a full uv environment is already provisioned:

```bash
UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/uv-cache uv run pyright
```

Expected current status in this fresh restricted worktree: pytest/ruff/pyright via uv fail before executing validation because dependency downloads are blocked. This is an environment/bootstrap failure, not a test assertion failure.

Best host-only cheap checks observed here:

```bash
ruff check .
bandit -q -r . -c pyproject.toml
INBOX_TEST_MODE=1 python3 -m pytest tests/test_mcp_gateway.py -q -o addopts= -k 'not trio'
INBOX_TEST_MODE=1 python3 -m pytest tests/test_inbox_test_mode.py -q -o addopts= -k 'not services and not google_auth_all'
```

Expected current status: pass on this machine. These are useful smoke checks but not a substitute for the declared uv environment.

Commands expected to fail until validation debt is addressed:

```bash
INBOX_TEST_MODE=1 python3 -m pytest -m safe -q -o addopts=
pyright
pre-commit run --all-files
```

Expected current status:

- `python3 -m pytest -m safe ...` fails during collection without project dependencies, because unselected tests still import unavailable modules before marker filtering completes.
- `pyright` fails with 116 errors in the host environment.
- `pre-commit run --all-files` is expected to require network/cached hook repos unless hooks are already installed; it was not run because this audit avoided external fetches.

Commands that should remain opt-in only:

```bash
uv run pytest
uv run pytest -x -q
uv run pytest --ignore=tests/test_audio.py --ignore=tests/test_llm.py -x -q
curl -sf http://localhost:9849/health
uv run python inbox_server.py
uv run python inbox.py
```

Reason: these either require the full dependency environment, may touch the live primary inbox server, may read local personal data stores, or may start long-running/local-service processes. For this audit, I did not start the server or call live localhost endpoints.

## Risks and stale assumptions

1. Safe pytest is not actually bootstrap-safe in a dependency-cold environment. `pytest -m safe` still collects the whole `tests/` tree, and collection imports modules needing `google_auth_oauthlib`, `textual`, and `loguru`.
2. The documented safe commands do not include `UV_CACHE_DIR`, while this sandbox cannot use `~/.cache/uv`. Some scripts know to set `/tmp/uv-cache`, but the agent docs and `dev.sh` do not.
3. Safe marker coverage is shallow. Only 2 of 31 test files are marked `safe`, so the safe loop currently checks MCP gateway/test-mode scaffolding, not most deterministic server/client/service behavior.
4. `pyproject.toml` requires `pytest-cov` globally through addopts. Host Python can have pytest installed but still fail before any test runs because `--cov` is unknown.
5. AnyIO tests assume Trio availability by default. `tests/test_mcp_gateway.py` passes under asyncio but fails the Trio parametrization when Trio is not installed.
6. Documentation claims are stale or inconsistent: `README.md` says Python 3.10+, while `pyproject.toml` requires Python 3.12+; `DOCS_INDEX.md` claims 736 passing tests and production-ready status, which was not reproducible here.
7. Direct `pyright` is not green. Some errors are missing environment packages, but others are apparent code/type contract mismatches, so a provisioned venv may still reveal real type debt.
8. Hidden `.factory/services.yaml` claims older broad test commands and a server start command pinned to `/Users/jwalinshah/projects/inbox`, which is risky for isolated worktrees because it can exercise the primary checkout instead of the current worktree.

## Next safe work

1. Make the agent validation bootstrap deterministic.
   - Acceptance criteria: `docs/TESTING_FOR_AGENTS.md`, `CLAUDE.md`, and `.factory/services.yaml` agree on `UV_CACHE_DIR=/tmp/uv-cache` or another writable cache; a fresh sandbox failure records dependency/network bootstrap clearly instead of failing on `~/.cache/uv` permissions.
   - Validation: `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe -q` reaches test execution in a provisioned/cache-warm environment; in a network-cold sandbox, the failure is only a dependency download blocker.

2. Make `pytest -m safe` collect only safe/import-light tests.
   - Acceptance criteria: safe marker collection no longer imports modules that require live Google/Textual/loguru deps before deselection, or those imports are properly stubbed under tests; the command remains read-only under `INBOX_TEST_MODE=1`.
   - Validation: `INBOX_TEST_MODE=1 python3 -m pytest -m safe -q -o addopts=` runs the selected safe tests without collection errors on a host Python that has pytest and Starlette/AnyIO installed.

3. Pin AnyIO safe tests to asyncio unless Trio is intentionally supported.
   - Acceptance criteria: `tests/test_mcp_gateway.py` defines an `anyio_backend` fixture or otherwise avoids implicit Trio parametrization; all MCP gateway safe tests pass without installing Trio.
   - Validation: `INBOX_TEST_MODE=1 python3 -m pytest tests/test_mcp_gateway.py -q -o addopts=` returns all tests passing, not just `-k 'not trio'`.

4. Reconcile validation claims in docs.
   - Acceptance criteria: `README.md` Python requirement matches `pyproject.toml`; `DOCS_INDEX.md` removes or dates the "736 tests pass" and "production-ready" claims unless a fresh command proves them.
   - Validation: `rg -n "Python 3.10|736 pass|production-ready" README.md DOCS_INDEX.md CLAUDE.md` has no unsupported current validation claims.

5. Split typecheck health into environment vs code debt.
   - Acceptance criteria: missing optional/platform imports are either resolved by the uv environment or intentionally configured, and remaining Pyright errors are tracked as concrete code issues.
   - Validation: `UV_CACHE_DIR=/tmp/uv-cache uv run pyright` runs in a provisioned environment and produces either 0 errors or a stable, triaged error list with owner tasks.

## Non-goals

- No product code was changed.
- No live personal data stores, OAuth tokens, Gmail/Calendar/Drive/Docs/Sheets/Tasks APIs, iMessage, Notes, Reminders, GitHub APIs, microphone/audio paths, or notification mutations were exercised.
- No server was started, no localhost health check was run against the primary inbox, and no external services were contacted intentionally.
- No tracked generated data, credentials, deployment config, pushes, PRs, or external tracker state were created or modified. Ignored validation artifacts are listed in the command observations.
- No attempt was made to fix the validation failures in this audit slice.

## Unknowns

- Whether the primary checkout or a CI runner has a warm uv cache that makes the declared uv commands pass.
- Whether `uv run pyright` still reports the non-import type errors after all project dependencies are installed.
- Whether the historical `.factory/validation/*` pass records correspond to this exact branch state.
- Whether all deterministic tests can be safely marked `safe`, or whether some unmarked tests read local personal stores without writes.
- Whether the runner expects ignored `.venv/`, `.pytest_cache/`, and `.ruff_cache/` artifacts to be cleaned; normal git status ignores them, and the sandbox blocked removing `.venv/`.

## Handoff blocker

The report is intentionally the only tracked file change, but this sandbox cannot stage or commit it: `git add docs/overnight/inbox-sym-117-validation-map.md` failed because Git tried to create `/Users/jwalinshah/projects/inbox/.git/worktrees/inbox-sym-117-validation-map/index.lock`, which is outside the writable roots.
