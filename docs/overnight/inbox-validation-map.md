# inbox-validation-map

## Scope

Queue item: deep validation-map audit for `inbox`.

This report is intentionally read-only for product code. It records the repo's validation surfaces, observed command behavior, validation gaps, and safe follow-up work. The only tracked file added by this worker is this report.

## Repo State

- Repo purpose: `inbox` is a local-first Python/TUI personal communication hub. The README describes a FastAPI backend plus Textual TUI that unifies iMessage, Gmail, Calendar, Sheets, Notes, Reminders, GitHub, Drive, ambient audio, dictation, and local ML.
- Worktree: `/Users/jwalinshah/projects/agent-stack/.agent-stack-worktrees/2026-05-07-overnight-marathon/inbox-validation-map`
- Branch: `codex/goal-inbox-validation-map`
- Starting HEAD: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`
- Starting dirty state: `git status --short --branch` showed only `## codex/goal-inbox-validation-map`.
- Local validation side effects: `uv run --no-sync python --version` created an ignored `.venv/`; pytest runs created ignored `.coverage` and `.pytest_cache/`. `git status --short --ignored .venv .pytest_cache .coverage` showed all three as ignored (`!!`).

## Validation Inventory

Primary validation files and claims:

- `pyproject.toml` defines Python `>=3.12,<3.15`, runtime dependencies, dev dependencies, `ruff`, `pyright`, `pytest`, `pytest-cov`, and `bandit`.
- `pyproject.toml` sets `pytest` `testpaths = ["tests"]` and default `addopts = "--cov=. --cov-report=term-missing"`.
- `pyproject.toml` registers five markers: `safe`, `integration`, `local_data`, `slow`, and `live_write`.
- `docs/TESTING_FOR_AGENTS.md` says default agent verification is `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, and `uv run pyright`.
- `docs/TESTING_FOR_AGENTS.md` says `INBOX_TEST_MODE=1` blocks live writes and warns not to run `local_data`, `live_write`, or live provider-specific integration tests unless explicitly requested.
- `README.md` and `CLAUDE.md` list developer commands as `uv run ruff check --fix .`, `uv run pyright`, and `uv run pytest`.
- `DOCS_INDEX.md` claims `uv run pytest` has "Tests (736 pass)" and "All 736 tests pass"; this is stale against the current collected suite and observed results.
- `.pre-commit-config.yaml` runs `ruff --fix`, `ruff-format`, basic pre-commit hooks, and `bandit -c pyproject.toml`.
- No CI or central runner was found by `fd -H -t f '(^Makefile$|tox\.ini$|noxfile\.py$|pytest\.ini$|setup\.cfg$|\.github/|github/workflows|requirements.*\.txt$)' .`.

## Commands Run

Required queue validation:

- `git status --short --branch`
  - Result: pass. Initial output was only `## codex/goal-inbox-validation-map`.

Exploration and validation-map discovery:

- `llm-tldr tree .`
  - Result: pass. Observed a flat Python app with `tests/`, `scripts/`, `deploy/`, `config/`, and docs, including `docs/TESTING_FOR_AGENTS.md`.
- `rtk read pyproject.toml`
  - Result: pass. Confirmed `pytest`, coverage addopts, `ruff`, `pyright`, `bandit`, and marker config.
- `rtk read docs/TESTING_FOR_AGENTS.md`
  - Result: pass. Confirmed agent-safe validation policy and opt-in warnings.
- `rtk grep "pytest|ruff|pyright|bandit|INBOX_TEST_MODE|safe|local_data|live_write|pre-commit|coverage|uv run" .`
  - Result: pass. Found validation claims in README, CLAUDE, DOCS_INDEX, pyproject, test files, and service write guards.
- `rg -n "pytestmark|@pytest\.mark" tests --glob '*.py'`
  - Result: pass. Found only four marker lines: safe module marks in `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py`, plus two `anyio` marks.
- `rg -n "^def test_|^async def test_" tests test_autocomplete_dev.py | wc -l`
  - Result: pass. Found 250 test function definitions before parametrization.

Executable validation commands:

- `uv run ruff check .`
  - Result: pass. Output: `All checks passed!`
- `INBOX_TEST_MODE=1 uv run pytest -m safe -q`
  - First result: fail before collection due sandboxed home cache: `Failed to initialize cache at /Users/jwalinshah/.cache/uv`.
  - Retried as `UV_CACHE_DIR=/private/tmp/inbox-validation-map-uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe -q`.
  - Retry result: pass. Output summary: `11 passed, 855 deselected in 9.95s`; total coverage in that narrow lane was 15%.
- `UV_CACHE_DIR=/private/tmp/inbox-validation-map-uv-cache INBOX_TEST_MODE=1 uv run pytest -q`
  - Result: fail. Output summary: `53 failed, 813 passed in 126.51s`.
  - Failure class: tests expecting mocked write helpers to execute now raise `inbox_test_mode.LiveWriteBlocked` because `INBOX_TEST_MODE=1` blocks service write paths.
- `uv run pyright`
  - Result: fail. Output summary: `108 errors, 0 warnings, 0 informations`.
  - Failure classes: unresolved optional/local imports, dynamic Textual widget APIs, dynamic Google/Quartz APIs, object-typed API services, test fake type mismatches, and optional subscripting in unsubscribe scripts.
- `UV_CACHE_DIR=/private/tmp/inbox-validation-map-uv-cache uv run bandit -c pyproject.toml -r . -q`
  - Result: pass with warning noise. Warnings included malformed `nosec` comments such as ignored words in comments and `nosec encountered ... but no failed test` on SQL-related files.

## Key Evidence

- `docs/TESTING_FOR_AGENTS.md` is the current best source for safe local validation. It correctly distinguishes safe agent runs from live/local-data tests.
- `inbox_test_mode.py` defines `INBOX_TEST_MODE`, `LiveWriteBlocked`, `assert_live_writes_allowed`, and `test_data_dir`.
- `services.py` centralizes live-write blocking through `_assert_live_write_allowed`, with guarded calls for Gmail, iMessage, Calendar, Reminders, Tasks, GitHub notifications, Drive, Sheets, Docs, desktop notifications, WhatsApp, and account auth.
- `tests/test_inbox_test_mode.py` proves `INBOX_TEST_MODE` blocks live writes, redirects data paths, registers pytest markers, and documents safe commands.
- `tests/test_mcp_gateway.py` is also marked safe; together with `tests/test_inbox_test_mode.py`, it accounts for the 11 selected safe tests.
- `tests/test_drive.py`, `tests/test_github.py`, `tests/test_gmail_actions.py`, `tests/test_notifications.py`, `tests/test_reminders.py`, and `tests/test_services.py` contain mocked write-behavior tests that fail when the full suite is run under `INBOX_TEST_MODE=1`.
- `.pre-commit-config.yaml` uses mutating `ruff --fix` and `ruff-format`; this is fine as a pre-commit hook but not a read-only audit command.
- `scripts/run_inbox_backend.sh` sets `UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"`, but `dev.sh` and the docs validation commands do not, which matters inside sandboxed worktrees where `~/.cache/uv` can be blocked.
- `DOCS_INDEX.md` says all 736 tests pass, while current full pytest collection observed 866 parametrized tests with 53 failures under `INBOX_TEST_MODE=1`.

## Risks And Stale Assumptions

1. The documented agent-safe lane is healthy but too small to protect most of the product. `pytest -m safe` selected 11 tests and deselected 855, so most regression coverage is outside the default safe proof.
2. Full pytest and safe test mode currently conflict. Running the full suite with `INBOX_TEST_MODE=1` blocks mocked write tests in Drive, GitHub, Gmail, Notifications, Reminders, and service AppleScript/Gmail paths.
3. `pyright` is listed as a default agent command, but it currently fails with 108 errors. That makes the documented validation contract non-green even before product behavior is considered.
4. `DOCS_INDEX.md` has stale validation claims: "736 pass" and "All 736 tests pass" do not match the current observed suite.
5. Validation commands are sensitive to the UV cache location. In this sandbox, `INBOX_TEST_MODE=1 uv run pytest -m safe -q` failed until `UV_CACHE_DIR` was moved to `/private/tmp/...`.
6. Pre-commit is not a safe read-only audit command as configured because `ruff --fix` and `ruff-format` may modify files.
7. There is no discovered CI workflow, Makefile, tox, nox, or single non-mutating validation wrapper. Agents must piece together validation from docs and pyproject.
8. Bandit passes but emits warning noise about malformed/ineffective `nosec` comments, which can hide whether security validation is meaningful.

## Validation Command Candidates

Use these as the current validation map:

| Command | Expected Status | Notes |
| --- | --- | --- |
| `git status --short` | pass | Queue-required validation. Should show only the intended report change before commit, or clean after commit. |
| `UV_CACHE_DIR=/private/tmp/inbox-validation-map-uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe -q` | pass | Observed `11 passed, 855 deselected`. Cheap and agent-safe, but narrow. |
| `uv run ruff check .` | pass | Observed `All checks passed!`; non-mutating form. |
| `uv run ruff check --fix .` | not read-only | Listed in README/CLAUDE and pre-commit, but may modify files. Avoid for audits. |
| `uv run pyright` | fail | Observed 108 errors. Do not use as a merge gate until triaged or scoped. |
| `UV_CACHE_DIR=/private/tmp/inbox-validation-map-uv-cache INBOX_TEST_MODE=1 uv run pytest -q` | fail | Observed 53 failures and 813 passes because test mode blocks mocked write tests. |
| `UV_CACHE_DIR=/private/tmp/inbox-validation-map-uv-cache uv run pytest -q` | unknown / risky | Not run. It may execute mocked write tests without `INBOX_TEST_MODE`; needs a human decision on whether mocks are sufficient guardrails. |
| `UV_CACHE_DIR=/private/tmp/inbox-validation-map-uv-cache uv run bandit -c pyproject.toml -r . -q` | pass with warning noise | Observed exit 0 plus `nosec` warning noise. |
| `uv run pre-commit run --all-files` | not read-only | Not run because configured hooks include format/fix actions. |

## Next Safe Work

1. Expand the safe test lane without weakening live-write protection.
   - Acceptance criteria: Tests that only use mocked services and temp paths are marked `safe`; tests that intentionally verify `LiveWriteBlocked` stay safe; true local-data/live-write tests are explicitly marked otherwise.
   - Suggested validation: `UV_CACHE_DIR=/private/tmp/inbox-validation-map-uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe -q` selects materially more than 11 tests and passes.

2. Split write-helper unit tests from live-write-blocking policy.
   - Acceptance criteria: Mocked Drive/GitHub/Gmail/Notification/Reminder tests can run in an agent-safe mode without hitting external services, while separate tests prove `INBOX_TEST_MODE` blocks real write entrypoints.
   - Suggested validation: `UV_CACHE_DIR=/private/tmp/inbox-validation-map-uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_drive.py tests/test_github.py tests/test_gmail_actions.py tests/test_notifications.py tests/test_reminders.py tests/test_services.py -q` no longer fails because of `LiveWriteBlocked`.

3. Make `pyright` actionable.
   - Acceptance criteria: Either `uv run pyright` passes, or `pyproject.toml` scopes/ignores known dynamic integration surfaces and docs state the expected residual errors.
   - Suggested validation: `uv run pyright`.

4. Add a non-mutating validation wrapper.
   - Acceptance criteria: A documented command or script runs the intended read-only checks with a sandbox-safe `UV_CACHE_DIR`, no `ruff --fix`, no formatter writes, and no live external writes.
   - Suggested validation: new wrapper exits 0 for `ruff` plus safe pytest, and explicitly reports `pyright` as pass/fail according to the chosen contract.

5. Update stale validation docs.
   - Acceptance criteria: `DOCS_INDEX.md`, `README.md`, `CLAUDE.md`, and `docs/TESTING_FOR_AGENTS.md` agree on the current pass/fail status and avoid claiming "736 pass" unless revalidated.
   - Suggested validation: `rg -n "736|All .* tests pass|uv run pytest|pyright|ruff" README.md CLAUDE.md DOCS_INDEX.md docs/TESTING_FOR_AGENTS.md`.

## Non-Goals

- No product code changes.
- No credential, token, OAuth, inbox data, Calendar, Gmail, Drive, GitHub, Notes, Reminders, or external-service access.
- No live server startup, no localhost browser QA, no deploys, no pushes, no PR creation, and no external tracker updates.
- No mutation of `.pre-commit-config.yaml`, test markers, pyproject config, or docs beyond this audit report.

## Unknowns

- Whether the desired release gate should be narrow safe pytest only, full pytest without `INBOX_TEST_MODE`, full pytest with a mock-write bypass, or a staged combination.
- Whether any existing external CI exists outside this worktree; none was found locally.
- Whether `pyright` was ever green or intentionally allowed to fail for dynamic integrations.
- Whether the 53 full-suite failures under `INBOX_TEST_MODE=1` should be fixed by test marker changes, a mock-write context manager, service-layer dependency injection, or adjusted docs.
- Whether bandit's `nosec` warning noise is acceptable or should be cleaned into a stricter security gate.

## Decision Notes

- I treated `docs/TESTING_FOR_AGENTS.md` as the safest validation policy because this repo handles personal data and live external write surfaces.
- I used `UV_CACHE_DIR=/private/tmp/inbox-validation-map-uv-cache` for repeatable validation after observing the default `~/.cache/uv` failure.
- I did not run pre-commit because the configured hooks can modify files.
- I did run full pytest under `INBOX_TEST_MODE=1` to map the current conflict between broad regression coverage and live-write blocking; the result is not a recommended merge gate yet.

## Handoff

- Changed tracked-intent file: `docs/overnight/inbox-validation-map.md`.
- Final required validation: `git status --short` exited 0 and showed `?? docs/overnight/`.
- Commit status: not committed. `git add docs/overnight/inbox-validation-map.md` failed because the worktree git metadata points at `/Users/jwalinshah/projects/inbox/.git/worktrees/inbox-validation-map/index.lock`, which is outside the writable sandbox.
- Commit SHA for current HEAD: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`.
- PR URL: none; PR creation and pushing were out of scope.
- Blockers: only the sandboxed git metadata write blocker prevented creating a local commit.
