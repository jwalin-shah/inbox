# inbox-sym-116 validation-map audit

Queue item: `inbox-sym-116-validation-map`
Repo: `inbox-sym-116`
Worktree: `/Users/jwalinshah/projects/agent-stack/.agent-stack-worktrees/2026-05-07-overnight-marathon/inbox-sym-116-validation-map`
Branch observed: `codex/goal-inbox-sym-116-validation-map`
Base HEAD observed before report: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`
Focus area: validation-map

## Scope decision

This was a read-only validation audit. I did not change product code, generated data,
secrets, deployment configuration, external services, trackers, remotes, or PR state.
The only intended repo change is this report file.

Because `docs/TESTING_FOR_AGENTS.md` says agent runs must be deterministic, local,
and safe, I treated the documented agent-safe commands as the validation contract.
I did not run the full unmarked test suite because the repo explicitly warns agents
not to run local-data, live-write, or provider-specific integration tests without
explicit opt-in.

## Repo purpose

`inbox-sym-116` is a local-first personal inbox/control-plane application. The core
runtime is a Python FastAPI backend plus a Textual TUI that integrates iMessage,
Gmail, Google Calendar, Google Sheets, Google Drive, Apple Notes, Apple Reminders,
GitHub notifications, local ML/audio, and MCP-facing agent tools. The validation
surface has to protect personal-data integrations while still giving agents a cheap
proof loop.

Local evidence:

- `README.md` describes the product as a unified communication/productivity TUI and
  lists `uv run ruff check --fix .`, `uv run pyright`, and `uv run pytest` as dev
  commands.
- `CLAUDE.md` documents worktree development on alternate ports and repeats the
  same lint/type/test commands.
- `docs/TESTING_FOR_AGENTS.md` is the only file found with explicit agent-safe
  validation rules.
- `pyproject.toml` declares Python `>=3.12,<3.15`, runtime dependencies including
  FastAPI, Google APIs, MLX, Textual, PyObjC, Rich, MCP, and dev dependencies
  including pytest, pytest-cov, ruff, pyright, bandit, and pre-commit.
- `tests/conftest.py` stubs heavy ML/hardware modules (`mlx_lm`, `mlx_whisper`,
  `sounddevice`, `Quartz`, `outlines`) but does not stub general runtime
  dependencies such as `google_auth_oauthlib`, `textual`, `loguru`, or `trio`.
- `inbox_test_mode.py` defines `INBOX_TEST_MODE`, `INBOX_TEST_DATA_DIR`,
  `INBOX_TEST_NOW`, and `assert_live_writes_allowed`.
- `services.py` calls `_assert_live_write_allowed(...)` across many mutation
  surfaces, including Google auth, iMessage, Gmail, Calendar, WhatsApp, Reminders,
  Drive, Sheets, Docs, and notifications.
- `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py` are the only test
  files currently marked `safe`.
- `scripts/run_inbox_backend.sh`, `scripts/run_inbox_mcp_http.sh`, and
  `scripts/run_inbox_mcp_http_readonly.sh` set `UV_CACHE_DIR` to `/tmp/uv-cache`
  before invoking `uv run`, which is relevant for sandboxed agents.
- `dev.sh` starts worktree copies on `INBOX_SERVER_PORT=9850` by default, avoiding
  the primary daily-driver server on port 9849.

## Validation surfaces found

### Package and tool config

`pyproject.toml` is the central validation config:

- Ruff: `[tool.ruff]`, target `py312`, line length 100.
- Ruff lint select: `E`, `F`, `I`, `UP`, `B`, `SIM`; ignores `E501`.
- Pyright: Python 3.12, `typeCheckingMode = "basic"`, missing imports reported.
- Pytest: `testpaths = ["tests"]`.
- Pytest default addopts: `--cov=. --cov-report=term-missing`.
- Pytest markers: `safe`, `integration`, `local_data`, `slow`, `live_write`.
- Bandit configured with `exclude_dirs = [".venv", "tests"]` and skips for several
  common subprocess/assert/import warnings.

### Documented commands

Agent-safe commands in `docs/TESTING_FOR_AGENTS.md`:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe
uv run ruff check .
uv run pyright
```

Focused safe command in `docs/TESTING_FOR_AGENTS.md`:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py -q
```

General developer commands in `README.md`, `CLAUDE.md`, and `DOCS_INDEX.md`:

```bash
uv run ruff check --fix .
uv run pyright
uv run pytest
```

Additional historical command in `SHEETS_CHANGELOG.md`:

```bash
uv run pytest tests/ -q
```

### Test inventory

Command observations:

- `rg --files tests | wc -l` returned `31`.
- `rg "^def test_|^class Test" tests | wc -l` returned `393`.
- `rtk grep "@pytest.mark|pytestmark|mark.safe|mark.integration|mark.local_data|mark.live_write|mark.slow" tests`
  returned only 4 marker matches across 2 files:
  - `tests/test_inbox_test_mode.py`: `pytestmark = pytest.mark.safe`
  - `tests/test_mcp_gateway.py`: `pytestmark = pytest.mark.safe`
  - two `@pytest.mark.anyio` entries in `tests/test_mcp_gateway.py`

This means `pytest -m safe` is currently a small marker set, not a broad suite
classification. Most test files are unmarked.

## Commands run and observed results

Environment and repo state:

```bash
git branch --show-current
# codex/goal-inbox-sym-116-validation-map

git rev-parse HEAD
# 2805b8400519da188ca7d3f6e39b19a8ca42b05a

git status --short
# clean before writing this report

uv --version
# uv 0.11.5 (Homebrew 2026-04-08 aarch64-apple-darwin)

python3 --version
# Python 3.12.8

fd -H '^\.venv$' .
# no .venv existed before the first uv attempt
```

Structure and config discovery:

```bash
llm-tldr tree .
# observed flat Python app modules, docs, scripts, tests, pyproject.toml, uv.lock

rtk read pyproject.toml
# observed dependencies, pytest markers, pytest-cov addopts, ruff, pyright, bandit

rtk read docs/TESTING_FOR_AGENTS.md
# observed documented agent-safe validation commands and explicit opt-in warnings

rtk grep "pytest|ruff|mypy|uv run|python -m|tox|coverage|lint|test" .
# observed validation docs spread across README, CLAUDE, DOCS_INDEX, pyproject,
# scripts, and tests
```

Safe validation attempts:

```bash
INBOX_TEST_MODE=1 uv run --frozen pytest -m safe -q
```

Result: BLOCKED before pytest. `uv` tried to initialize cache at
`/Users/jwalinshah/.cache/uv` and failed with "Operation not permitted".

```bash
UV_CACHE_DIR=/private/tmp/inbox-sym-116-validation-map-uv-cache \
  INBOX_TEST_MODE=1 uv run --frozen pytest -m safe -q
```

Result: BLOCKED by offline dependency hydration. `uv` created `.venv`, then failed
to download `pyobjc-core==12.1`, included via `pyobjc-framework-quartz==12.1`,
because DNS/network access was unavailable. `.venv` is gitignored.

```bash
INBOX_TEST_MODE=1 python3 -m pytest tests/test_inbox_test_mode.py -q
```

Result: BLOCKED by missing plugin under system Python. Pytest read
`pyproject.toml` and rejected `--cov=. --cov-report=term-missing` because
`pytest-cov` is not installed in the system environment.

```bash
INBOX_TEST_MODE=1 python3 -m pytest -o addopts='' -m safe -q
```

Result: FAIL during collection before marker filtering completed. The system
environment lacks project dependencies such as `google_auth_oauthlib`, `textual`,
and `loguru`, so unmarked test modules fail import even though only `safe` tests
were requested.

```bash
INBOX_TEST_MODE=1 python3 -m pytest -o addopts='' \
  tests/test_inbox_test_mode.py tests/test_mcp_gateway.py -q
```

Result: PARTIAL FAIL, 9 passed and 4 failed. Failures were environment/dependency
failures:

- `tests/test_inbox_test_mode.py::test_services_resolve_local_data_paths_under_test_dir`
  failed importing `services.py` because `google_auth_oauthlib` is missing.
- `tests/test_inbox_test_mode.py::test_google_auth_all_creates_missing_test_data_parent`
  failed importing `services.py` because `google_auth_oauthlib` is missing.
- `tests/test_mcp_gateway.py::test_health_handler_includes_backend_and_extra_payload[trio]`
  failed because `trio` is missing.
- `tests/test_mcp_gateway.py::test_health_handler_handles_backend_error[trio]`
  failed because `trio` is missing.

Narrow local proofs that do run under system Python:

```bash
INBOX_TEST_MODE=1 python3 -m pytest -o addopts='' \
  tests/test_inbox_test_mode.py::test_test_mode_blocks_live_writes \
  tests/test_inbox_test_mode.py::test_test_mode_uses_configured_test_data_dir \
  tests/test_inbox_test_mode.py::test_agent_safe_pytest_markers_are_registered \
  tests/test_inbox_test_mode.py::test_agent_testing_docs_define_safe_commands_and_opt_in_warnings \
  -q
# 4 passed in 0.03s
```

```bash
python3 -m pytest -o addopts='' tests/test_mcp_gateway.py -k 'not trio' -q
# 5 passed, 2 deselected in 0.17s
```

Syntax proof:

```bash
python3 -m compileall -q *.py tests
# passed with exit code 0
```

Lint/type command observations under system Python:

```bash
python3 -m ruff check .
# /usr/local/bin/python3: No module named ruff

python3 -m pyright
# /usr/local/bin/python3: No module named pyright
```

These do not prove lint/type failures in the repo; they prove the local
non-`uv` tool environment is incomplete.

## Current validation map

| Command | Scope | Expected status in a hydrated dev env | Observed status here | Notes |
|---|---|---:|---:|---|
| `git status --short` | queue validation | PASS | PASS before report; expected to show only this report after write | Required by queue item. |
| `INBOX_TEST_MODE=1 uv run pytest -m safe` | documented agent-safe tests | SHOULD PASS | BLOCKED | Needs uv cache path writable and dependencies available/cached. |
| `INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py -q` | focused test-mode safety | SHOULD PASS | BLOCKED through uv; partially runnable via system Python | Depends on project deps for `services.py` import cases. |
| `uv run ruff check .` | lint | SHOULD PASS before merge | BLOCKED | Cannot hydrate uv env offline; system Python has no ruff. |
| `uv run pyright` | type check | SHOULD PASS before merge | BLOCKED | Cannot hydrate uv env offline; system Python has no pyright. |
| `uv run pytest` | full suite with coverage | UNKNOWN | NOT RUN | Not agent-safe by default; most tests are unmarked and repo warns against local/live/provider tests without opt-in. |
| `uv run pytest tests/ -q` | historical full tests command | UNKNOWN | NOT RUN | Same opt-in concern; docs claim 736 pass but current grep saw 393 test defs/classes. |
| `python3 -m compileall -q *.py tests` | syntax-only local proof | PASS | PASS | Useful fallback when dependency hydration is blocked. |
| `python3 -m pytest -o addopts='' tests/test_mcp_gateway.py -k 'not trio' -q` | system-Python partial MCP safe proof | PASS | PASS | Avoids missing `trio` backend. |
| selected `tests/test_inbox_test_mode.py` no-service tests | system-Python partial test-mode proof | PASS | PASS | Avoids missing Google runtime dependencies. |

## Risks and stale assumptions

1. Agent-safe validation depends on full dependency hydration.
   `docs/TESTING_FOR_AGENTS.md` recommends `uv run pytest -m safe`, but in a
   sandboxed/offline agent worktree this fails before pytest if the default uv
   cache is outside the writable sandbox or dependencies are not already cached.
   The scripts under `scripts/` already use `UV_CACHE_DIR=/tmp/uv-cache`, but the
   testing docs do not mention this workaround.

2. `pytest -m safe` is not guaranteed to avoid collection-time imports from
   unmarked files. Under system Python with incomplete deps, the command still
   hit collection errors in unmarked tests before producing a useful safe-only
   result. This is a validation ergonomics risk for agents trying to respect the
   safety policy.

3. The safe marker set is very small. Only `tests/test_inbox_test_mode.py` and
   `tests/test_mcp_gateway.py` are marked `safe`, while the repo has 31 test files
   and roughly 393 test/class definitions. The documented safe command may give a
   false sense of coverage for changes outside test-mode and MCP gateway code.

4. Docs contain stale or unverified test-count claims. `DOCS_INDEX.md` and
   `SHEETS_CHANGELOG.md` claim "All 736 tests pass"; this checkout's local grep
   saw 393 test/class definitions and validation could not reproduce the claim.
   The number may be historical, but morning reviewers should not treat it as
   current evidence.

5. `pyproject.toml` always injects coverage options through pytest addopts. That
   is reasonable in the managed `uv` env, but it makes system-Python fallback
   pytest unusable unless `-o addopts=''` is added. This matters during sandboxed
   audits where `uv` cannot hydrate.

6. `tests/conftest.py` stubs ML/hardware dependencies but not baseline app
   dependencies. Tests that are conceptually safe can still fail to import
   `services.py`, `inbox.py`, or async backends when the full dependency set is
   not present.

7. The validation story mixes agent-safe commands and general developer commands.
   `README.md` and `CLAUDE.md` advertise `uv run pytest`; `docs/TESTING_FOR_AGENTS.md`
   narrows agents to `INBOX_TEST_MODE=1 uv run pytest -m safe`. This split is good,
   but it should be the first thing a worker sees when asked to validate changes.

## Next safe work

### 1. Make sandboxed agent validation boot reliably

Acceptance criteria:

- `docs/TESTING_FOR_AGENTS.md` includes a sandbox-friendly variant using
  `UV_CACHE_DIR=/tmp/uv-cache` or another writable temp path.
- The same doc explains that the default `~/.cache/uv` path can be blocked in
  restricted worktrees.
- No product code changes.

Validation command:

```bash
UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run --frozen pytest -m safe -q
```

Expected status: PASS in a hydrated/cached environment; BLOCKED offline until
`pyobjc-core` and the rest of the lockfile are available locally.

### 2. Add a dependency-light safe smoke lane

Acceptance criteria:

- Add or document a command that runs only tests which do not import `services.py`,
  `inbox.py`, Google clients, Textual, or optional anyio trio backend.
- The command should be useful when `uv` dependency hydration is blocked.
- The command should include `-o addopts=''` or otherwise avoid requiring
  `pytest-cov` under system Python.

Candidate validation command:

```bash
INBOX_TEST_MODE=1 python3 -m pytest -o addopts='' \
  tests/test_inbox_test_mode.py::test_test_mode_blocks_live_writes \
  tests/test_inbox_test_mode.py::test_test_mode_uses_configured_test_data_dir \
  tests/test_inbox_test_mode.py::test_agent_safe_pytest_markers_are_registered \
  tests/test_inbox_test_mode.py::test_agent_testing_docs_define_safe_commands_and_opt_in_warnings \
  -q
```

Expected status: PASS; observed `4 passed in 0.03s`.

### 3. Fix safe marker coverage and collection behavior

Acceptance criteria:

- Review all tests and mark deterministic, local, non-mutating tests as `safe`.
- Add `integration`, `local_data`, `slow`, or `live_write` markers where tests
  should not run by default.
- Ensure `INBOX_TEST_MODE=1 uv run pytest -m safe -q` collects cleanly and gives
  meaningful coverage of safe surfaces.

Validation commands:

```bash
rtk grep "@pytest.mark|pytestmark" tests
INBOX_TEST_MODE=1 uv run pytest -m safe -q
```

Expected status: first command shows broad marker coverage; second command PASS
in a hydrated environment.

### 4. Replace stale test-count claims with reproducible evidence

Acceptance criteria:

- `DOCS_INDEX.md` and `SHEETS_CHANGELOG.md` no longer state unqualified
  "All 736 tests pass" unless a current command and commit are cited.
- Docs distinguish historical release notes from current validation state.

Validation command:

```bash
rtk grep "736 tests|All .* tests pass|uv run pytest" DOCS_INDEX.md SHEETS_CHANGELOG.md README.md CLAUDE.md
```

Expected status: PASS when stale claims are removed or clearly dated.

### 5. Add a no-dependency syntax proof to the agent guide

Acceptance criteria:

- `docs/TESTING_FOR_AGENTS.md` lists `python3 -m compileall -q *.py tests` as a
  fallback syntax-only proof when `uv` cannot hydrate.
- The doc labels it as insufficient for merge readiness.

Validation command:

```bash
python3 -m compileall -q *.py tests
```

Expected status: PASS; observed PASS in this worktree.

## Non-goals

- Do not broaden or refactor product code as part of this audit.
- Do not run live-write, local-data, or provider integration tests without
  explicit human opt-in.
- Do not start the inbox server, MCP services, launchd jobs, Caddy, OAuth flows,
  notification tests, audio capture, or UI automation.
- Do not edit credentials, tokens, local personal-data stores, or generated state.
- Do not push branches, open PRs, merge PRs, or mark external trackers done.
- Do not treat the partial system-Python proofs as a substitute for hydrated
  `uv` validation before merge.

## Unknowns

- Whether `uv run pytest -m safe`, `uv run ruff check .`, and `uv run pyright`
  pass in the primary checkout or any already-hydrated developer environment.
- Whether the historical "736 tests pass" claim corresponds to another branch,
  an older suite layout, generated parametrization, or stale documentation.
- Whether the full unmarked suite is entirely deterministic under
  `INBOX_TEST_MODE=1`; this audit did not run it because the repo docs warn
  against unapproved local/live/provider tests.
- Whether CI exists for this repo and which validation subset it runs; no CI
  metadata was inspected beyond local files.
- Whether any ignored `.venv` created by `uv` during this audit is complete; the
  observed `uv` attempt failed during dependency download.

## Handoff notes

Files changed:

- `docs/overnight/inbox-sym-116-validation-map.md`

Validation result for this audit:

- Required queue validation command: `git status --short`
- Status before report write: PASS, clean output.
- Status after report write: PASS, output `?? docs/overnight/`.
- `fd . docs/overnight` confirmed the directory contains exactly
  `docs/overnight/inbox-sym-116-validation-map.md`.

PR URL:

- None. PR creation was explicitly out of scope for this Goal Pack.

Blockers:

- Hydrated `uv` validation could not run inside this sandbox because the default
  uv cache path was not writable and the temp-cache retry needed network access
  for `pyobjc-core==12.1`.
