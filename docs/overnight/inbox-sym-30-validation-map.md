# inbox-sym-30 validation-map audit

Date: 2026-05-07
Queue item: `inbox-sym-30-validation-map`
Repo path: `/Users/jwalinshah/projects/agent-stack/.agent-stack-worktrees/2026-05-07-overnight-marathon/inbox-sym-30-validation-map`
Branch: `codex/goal-inbox-sym-30-validation-map`
HEAD at audit start: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`

## Scope

This audit maps the validation surface for the local `inbox-sym-30` worktree. It is read-only with respect to product code. The only intended tracked change is this report.

Non-goals:
- No product code changes.
- No live inbox server startup.
- No Gmail, Calendar, Drive, Sheets, Docs, GitHub, iMessage, Notes, Reminders, microphone, notification, OAuth, deploy, or MCP live-service exercise.
- No live-write tests or `local_data` tests.
- No external pushes, PR creation, tracker updates, or repo cleanup.

## Repo Purpose And State

Purpose: `README.md` and `CLAUDE.md` describe a local-first Python inbox/TUI that uses a FastAPI backend for iMessage, Gmail, Google Calendar, Google Sheets, Apple Notes, Apple Reminders, GitHub notifications, Google Drive, ambient audio, dictation, and MCP access. The repository is validation-sensitive because its normal runtime reads local personal data stores and can perform external writes through OAuth-backed services.

Observed state:
- `git status --short --branch` returned only `## codex/goal-inbox-sym-30-validation-map` before report creation.
- Required validation command `git status --short` returned no output before report creation and exited 0.
- Required validation command `git status --short` after report creation exited 0 and returned `?? docs/overnight/`.
- `git status --short --ignored` after validation probes showed ignored local artifacts: `.pytest_cache/`, `.ruff_cache/`, and `.venv/`.
- The `.venv/` directory was created by the attempted `uv run` validation after the default uv cache path was blocked by sandbox permissions.
- Expected final tracked dirty state is this report at `docs/overnight/inbox-sym-30-validation-map.md`.

## Validation Surface

Documented developer commands:
- `README.md` documents `uv run ruff check --fix .`, `uv run pyright`, and `uv run pytest`.
- `CLAUDE.md` repeats the same dev commands and explains the worktree development workflow.
- `DOCS_INDEX.md` claims `uv run pytest` has "736 pass" and later says "All 736 tests pass".

Documented agent-safe commands:
- `docs/TESTING_FOR_AGENTS.md` defines the default safe loop as `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, and `uv run pyright`.
- The same file says `INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py -q` is the focused safe test.
- It explicitly says not to run `live_write`, `local_data`, or live provider-specific tests unless requested by name.

Configured tools:
- `pyproject.toml` requires Python `>=3.12,<3.15`, which conflicts with the `README.md` quick-start claim of Python 3.10+.
- `pyproject.toml` configures `ruff` with `E`, `F`, `I`, `UP`, `B`, and `SIM`, ignores `E501`, and targets Python 3.12.
- `pyproject.toml` configures `pyright` in basic mode with `reportMissingImports = true`.
- `pyproject.toml` configures pytest to use `testpaths = ["tests"]` and global `addopts = "--cov=. --cov-report=term-missing"`.
- `pyproject.toml` registers markers: `safe`, `integration`, `local_data`, `slow`, and `live_write`.
- `.pre-commit-config.yaml` includes ruff with `--fix`, `ruff-format`, standard pre-commit hygiene hooks, and Bandit. It does not run pytest or pyright.
- `scripts/run_inbox_backend.sh`, `scripts/run_inbox_mcp_http.sh`, and `scripts/run_inbox_mcp_http_readonly.sh` set `UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"`, but `dev.sh`, `README.md`, `CLAUDE.md`, and `docs/TESTING_FOR_AGENTS.md` do not set a sandbox-safe uv cache path.

Test inventory:
- `llm-tldr tree .` found 29 files under `tests/`, plus a top-level `test_autocomplete_dev.py` development script.
- `rg -l "^def test_|^class Test" tests | wc -l` returned `29`.
- `rg -n "^def test_|^class Test" tests | wc -l` returned `393` test/class declarations. This is not the same measurement as pytest-collected test cases, but it shows the current docs claim of "736 tests" needs revalidation.
- `rg -n "pytestmark = pytest.mark.safe|@pytest.mark.safe|..." tests` found only `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py` marked safe at module scope.
- `tests/conftest.py` stubs heavy/hardware modules (`mlx_lm`, `mlx_whisper`, `sounddevice`, `outlines`, `Quartz`) but does not stub normal package dependencies like `google_auth_oauthlib`, `loguru`, or `textual`.
- `tests/test_inbox_test_mode.py` verifies `INBOX_TEST_MODE`, marker registration, and testing docs. Two tests import `services.py`.
- `tests/test_mcp_gateway.py` uses `pytest.mark.anyio`; without `trio` installed, default AnyIO parametrization produces trio-backend failures.

## Commands Run

Repo discovery and state:
- `llm-tldr tree .` passed and showed a flat Python app with `services.py`, `inbox_server.py`, `inbox.py`, MCP modules, scripts, deploy examples, docs, and 29 test files.
- `git rev-parse HEAD` returned `2805b8400519da188ca7d3f6e39b19a8ca42b05a`.
- `git status --short --branch` passed and reported branch `codex/goal-inbox-sym-30-validation-map`.
- `git status --short` passed with empty output before report creation.
- `git status --short` passed after report creation and showed `?? docs/overnight/`.

Tool availability:
- `uv --version` passed: `uv 0.11.5`.
- `pytest --version` passed: `pytest 9.0.2`.
- `ruff --version` passed: `ruff 0.15.8`.
- `pyright --version` passed: `pyright 1.1.408`.
- `bandit --version` passed: `bandit 1.9.4`.
- `pre-commit --version` passed: `pre-commit 4.5.1`.

Validation probes:
- `UV_CACHE_DIR=/private/tmp/uv-cache-inbox-sym-30-validation-map INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py -q` failed before tests ran because `uv` needed to download `pyobjc-core==12.1` and network/DNS was unavailable. This created ignored `.venv/` state.
- `python -m pytest tests/test_inbox_test_mode.py -q` failed because `python` is not on PATH.
- `python3 -m pytest tests/test_inbox_test_mode.py -q` failed because global pytest loaded `pyproject.toml` addopts but global `pytest-cov` was unavailable: unrecognized `--cov=. --cov-report=term-missing`.
- `python3 -m pytest tests/test_inbox_test_mode.py -q -o addopts=''` ran and produced `4 passed, 2 failed`; failures were `ModuleNotFoundError: No module named 'google_auth_oauthlib'` when importing `services.py`.
- `python3 -m pytest tests/test_mcp_gateway.py tests/test_inbox_test_mode.py -q -o addopts=''` ran and produced `9 passed, 4 failed`; failures were missing `trio` for AnyIO's trio backend and missing `google_auth_oauthlib` for `services.py` imports.
- `python3 -m pytest tests/test_mcp_gateway.py -q -o addopts='' -k 'not trio'` passed: `5 passed, 2 deselected`.
- `python3 -m pytest tests/test_inbox_test_mode.py::test_test_mode_blocks_live_writes tests/test_inbox_test_mode.py::test_test_mode_uses_configured_test_data_dir tests/test_inbox_test_mode.py::test_agent_safe_pytest_markers_are_registered tests/test_inbox_test_mode.py::test_agent_testing_docs_define_safe_commands_and_opt_in_warnings -q -o addopts=''` passed: `4 passed`.
- `ruff check .` passed: `All checks passed!`.
- `pyright` failed with 116 errors. Major buckets were missing imports (`textual`, `loguru`, `google_auth_oauthlib`, `ApplicationServices`, `Quartz`, `mlx_lm`, `mlx_whisper`, `outlines`, and `gemma4_hackathon.silos.*`) plus real type issues in `inbox_server.py`, `services.py`, `memory_store.py`, `organize_inbox.py`, tests, and unsubscribe scripts.
- `pre-commit validate-config` passed.
- `bandit -c pyproject.toml -r .` passed with no issues identified after scanning 18,343 lines of code; 10 potential issues were skipped due to configured skips or `#nosec` handling.

## Validation Command Candidates

Use these as candidate proof commands, with current expected status in this worktree:

| Command | Expected status | Notes |
|---|---:|---|
| `git status --short` | Pass | Required queue validation; before report it was empty. After report it should show only this report as tracked dirty state. |
| `ruff check .` | Pass | Passed from PATH with ruff 0.15.8. Pyproject dev dependency asks for ruff >=0.15.10, so canonical `uv run ruff check .` still needs a provisioned uv env. |
| `bandit -c pyproject.toml -r .` | Pass | Passed from PATH with Bandit 1.9.4. Mirrors pre-commit Bandit intent without hook environment setup. |
| `pre-commit validate-config` | Pass | Config syntax is valid. Does not prove hook execution. |
| `python3 -m pytest tests/test_mcp_gateway.py -q -o addopts='' -k 'not trio'` | Pass | Cheap local proof for non-trio MCP gateway safe tests when uv env is unavailable. |
| Selected four `tests/test_inbox_test_mode.py` tests with `-o addopts=''` | Pass | Proves test-mode helper and docs/marker checks that do not import `services.py`. |
| `python3 -m pytest tests/test_inbox_test_mode.py -q -o addopts=''` | Fail | Fails on missing `google_auth_oauthlib` when importing `services.py`. |
| `python3 -m pytest tests/test_mcp_gateway.py tests/test_inbox_test_mode.py -q -o addopts=''` | Fail | Fails on missing `trio` and `google_auth_oauthlib`. |
| `INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py -q` | Blocked/fail locally | With `UV_CACHE_DIR` moved to `/private/tmp`, uv still needed network to fetch `pyobjc-core==12.1`. Without moved cache, uv cannot access `~/.cache/uv` under sandbox. |
| `INBOX_TEST_MODE=1 uv run pytest -m safe` | Expected blocked/fail locally | Same uv provisioning blocker; additionally safe coverage is currently only two files. |
| `uv run pytest` | Not run; expected blocked/fail locally | Out of scope for this audit because it is broader than the agent-safe loop and uv provisioning is already blocked. |
| `pyright` | Fail | 116 errors from PATH. `uv run pyright` may remove some missing imports after env provisioning, but current type gate is red. |
| `pre-commit run --all-files` | Not run | Hook setup may need network/cache and ruff hook is configured with `--fix`, so it is not a non-mutating validation command. |

## Risks And Stale Assumptions

1. Python version docs are stale. `README.md` says Python 3.10+, while `pyproject.toml` requires Python `>=3.12,<3.15`.

2. Test-count claims are stale or at least unsupported. `DOCS_INDEX.md` claims "736 pass"; local static inventory found 393 test/class declarations across 29 test files, and the current worktree could not run pytest under the canonical uv environment.

3. Canonical agent-safe validation is not actually offline/sandbox safe. `docs/TESTING_FOR_AGENTS.md` tells agents to use `uv run`, but the default uv cache is outside this sandbox and moving the cache to `/private/tmp` still requires network for `pyobjc-core`.

4. Pytest's global addopts make fallback testing brittle. Without the uv dev environment, global pytest fails immediately because `pytest-cov` is not installed but `--cov=. --cov-report=term-missing` is forced by `pyproject.toml`.

5. Safe marker coverage is too narrow. Only `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py` are marked `safe`, so `pytest -m safe` is more of a smoke test than a representative deterministic suite.

6. AnyIO async tests assume optional backend dependencies. `tests/test_mcp_gateway.py` uses `pytest.mark.anyio`, and global pytest tries a trio backend even though `trio` is not available in the observed environment.

7. `pyright` is documented as a normal validation command but currently fails hard. Some errors are missing import/environment problems, but others are local type-contract issues that should be triaged separately.

8. Pre-commit is not an adequate non-mutating validation gate. It omits pytest and pyright, and its ruff hook uses `--fix`, so `pre-commit run --all-files` can mutate files while validating.

9. Runtime scripts and validation docs disagree on uv cache handling. Service wrapper scripts set `UV_CACHE_DIR=/tmp/uv-cache`; `dev.sh` and testing docs do not.

10. Personal-data safety relies on convention rather than a single enforced test harness. `INBOX_TEST_MODE=1` blocks live writes through `assert_live_writes_allowed`, but default README/CLAUDE pytest commands omit it.

## Next Safe Work

1. Add an agent-safe validation wrapper.
   - Work: create a small script such as `scripts/validate_agent_safe.sh` that exports `INBOX_TEST_MODE=1`, uses a workspace or `/tmp` uv cache, runs non-mutating lint, runs a deterministic safe pytest subset, and prints clear guidance if dependencies are not locally provisioned.
   - Acceptance criteria: the script never touches live providers, never uses `--fix`, and exits with a clear message when uv cannot run offline.
   - Validation command: `scripts/validate_agent_safe.sh`.

2. Normalize pytest markers and safe suite coverage.
   - Work: classify deterministic tests across `tests/` as `safe` or explicitly mark them otherwise; add a collection check that fails when a test file lacks an intentional validation category.
   - Acceptance criteria: `INBOX_TEST_MODE=1 uv run pytest -m safe --collect-only -q` collects more than the current two safe files, and intentionally unsafe tests are marked `local_data`, `live_write`, `slow`, or `integration`.
   - Validation commands: `INBOX_TEST_MODE=1 uv run pytest -m safe --collect-only -q`; `rg -n "pytestmark = pytest.mark.safe|@pytest.mark.safe" tests`.

3. Fix the current agent-safe pytest blockers.
   - Work: either make `trio` an explicit dev dependency or constrain AnyIO tests to asyncio; ensure the uv/dev environment contains `google-auth-oauthlib` and `pytest-cov`, or make the focused safe tests not require full service imports.
   - Acceptance criteria: `INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py tests/test_mcp_gateway.py -q` passes in a clean worktree with no live credentials.
   - Validation command: `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py tests/test_mcp_gateway.py -q`.

4. Make Pyright actionable instead of aspirational.
   - Work: separate missing-dependency noise from real type errors, add local stubs or excludes for optional platform modules, and either fix or baseline the remaining real errors.
   - Acceptance criteria: `uv run pyright` has an agreed target, ideally zero errors or a checked-in baseline with owner and date.
   - Validation command: `uv run pyright`.

5. Update validation docs to match reality.
   - Work: update `README.md`, `CLAUDE.md`, `DOCS_INDEX.md`, and `docs/TESTING_FOR_AGENTS.md` so Python version, test-count claims, safe commands, cache expectations, and pass/fail status are current.
   - Acceptance criteria: no doc claims "736 pass" unless freshly verified; docs consistently prefer `INBOX_TEST_MODE=1`; docs warn that full pytest requires a provisioned uv environment.
   - Validation command: `rg -n "Python 3.10|736 pass|uv run pytest" README.md CLAUDE.md DOCS_INDEX.md docs/TESTING_FOR_AGENTS.md`.

6. Split mutating format/fix commands from validation commands.
   - Work: make docs distinguish `ruff check .` from `ruff check --fix .`, and consider adding a non-mutating pre-commit/manual validation path.
   - Acceptance criteria: an agent can run a no-write validation command without surprise formatting edits.
   - Validation commands: `ruff check .`; `pre-commit validate-config`.

## Unknowns

- Whether the primary non-sandbox developer machine has all uv dependencies cached and can run `uv run pytest` successfully.
- Whether the historical "736 pass" claim was based on pytest-collected cases rather than static test declarations.
- Whether a CI workflow exists outside this worktree; no `.github/workflows/*` file was found by `rg --files`.
- Whether `pyright` failures are accepted debt or should block future work.
- Whether the intended agent-safe suite should include server/client/service unit tests that mock all provider surfaces, or remain a narrow safety harness.
- Whether generated `.venv/`, `.pytest_cache/`, and `.ruff_cache/` should be left for later workers or cleaned by the runner; they are ignored by `.gitignore`.
