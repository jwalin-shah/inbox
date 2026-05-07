# inbox-sym-214 risk and validation review

Queue item: `inbox-sym-214-risk-and-validation-review`
Branch: `codex/goal-inbox-sym-214-risk-and-validation-review`
Review date: 2026-05-07
Repo HEAD at review start: `2805b84`

## Scope

This is a read-only risk-and-validation review for the local `inbox-sym-214`
worktree. Product code was not changed. The only intended repo change is this
report.

The queue item referenced `items/inbox-sym-214-risk-and-validation-review/ISSUE.md`,
but that file is not present in this worktree. I used the issue body from the
goal prompt as the task contract and recorded the missing local issue artifact as
a blocker below.

## Evidence observations

1. `README.md` describes the app as a privacy-first TUI combining iMessage,
   Gmail, Google Calendar, Sheets, Apple Notes, Apple Reminders, GitHub, and
   Drive, with server endpoints on `localhost:9849`. This is a broad
   personal-data surface, so validation needs to separate deterministic tests
   from live-provider checks.

2. `README.md:31-34` says the runtime requirement is Python 3.10+, while
   `pyproject.toml:5` requires `>=3.12,<3.15`. This is a stale setup claim that
   can send agents or humans down the wrong dependency path.

3. `pyproject.toml:53-62` defines pytest markers for `safe`, `integration`,
   `local_data`, `slow`, and `live_write`, and `docs/TESTING_FOR_AGENTS.md:9-18`
   tells agents to use `INBOX_TEST_MODE=1 uv run pytest -m safe` or the focused
   `tests/test_inbox_test_mode.py` command. That is the right safety model for a
   personal-data repo.

4. Only `tests/test_inbox_test_mode.py:8` and `tests/test_mcp_gateway.py:18`
   declare `pytestmark = pytest.mark.safe`. Static search found 31 files under
   `tests/`, but only two files marked safe; the safe gate currently covers the
   test-mode helper and MCP gateway auth, not most server, service, registry, or
   account-routing regressions.

5. `tests/conftest.py` stubs hardware and ML dependencies such as `mlx_lm`,
   `mlx_whisper`, `sounddevice`, `outlines`, and `Quartz`, which is good for CI
   portability. However, there is no `.github/**` workflow file in the current
   checkout, so the repo has no visible GitHub Actions validation contract.

6. `DOCS_INDEX.md:42-44` lists `uv run ruff check --fix .`, `uv run pyright`,
   and `uv run pytest` as dev commands, and `DOCS_INDEX.md:140` claims "All 736
   tests pass." This review could not verify that claim locally because `uv run`
   needed a network download for `tokenizers`; the pinned test-count claim should
   be treated as stale until a fresh validation artifact exists.

7. `inbox_test_mode.py:22-24` blocks live writes when `INBOX_TEST_MODE` is set,
   and `services.py:114-119` routes write guards through that helper. Static
   search shows many service-level mutators call `_assert_live_write_allowed`,
   including Gmail, Calendar, Reminders, Google Tasks, Drive, Sheets, Docs,
   GitHub notification mutation, desktop notifications, and WhatsApp.

8. `services.py:56-80` redirects Google token files and macOS data-store paths
   into `INBOX_TEST_DATA_DIR` during test mode, and
   `tests/test_inbox_test_mode.py:29-42` verifies several of those redirects.
   `scheduler.py:15-17` and `memory_store.py:9-10`, however, default to
   repo-local `.inbox_scheduler.sqlite3` and `.inbox_memory.sqlite3`; these are
   ignored by `.gitignore`, but not covered by the same test-data redirection.

9. `inbox_server.py:1180-1187` starts a background scheduler loop by default,
   and `inbox_server.py:982-1030` can send due Gmail/iMessage scheduled
   messages while `inbox_server.py:1048-1114` can create Google Tasks or Apple
   Reminders for followups. Tests can disable the scheduler through
   `InboxServerRuntime(start_scheduler=False)`, but runtime default behavior is
   still a high-risk write surface.

10. `inbox_server.py:2066-2104` creates scheduled messages and followup records
    by writing through `SchedulerStore` without a local test-mode guard at the
    endpoint boundary. The actual send/create paths hit service-level live-write
    guards later, but queued work can persist and fire in a different runtime
    context.

11. `tools_registry.py:41-77` models MCP tools with `readonly` and `confirm`
    flags, and `tests/test_tools_registry.py:41-43` asserts every non-readonly
    registry tool is confirmation-gated. That is a strong guard for agent-facing
    mutation, but these tests are not part of the current `safe` marker set.

12. `inbox_server.py:1313-1340` allows all HTTP endpoints when
    `INBOX_SERVER_TOKEN` is unset, and `mcp_gateway.py:28-45` similarly allows
    MCP access when `INBOX_MCP_TOKEN` is unset except for a public `/health`
    route. `config/inbox.env.example:1-6` provides token placeholders, but auth
    remains optional by code path.

13. `google_account_resolution.py:24-31` implements
    `INBOX_DEFAULT_GOOGLE_ACCOUNT` preference when the env value exists in the
    service map. `tests/test_server.py:612-657` and `tests/test_server.py:1494-1621`
    cover default calendar/preflight routing, but `config/inbox.env.example`
    does not include `INBOX_DEFAULT_GOOGLE_ACCOUNT`, so the source-of-truth
    account policy is easy to omit in deployed config.

14. `CONNECTOR_ROADMAP.md:38-44` says Google writes should default to
    `jshah1331@gmail.com` and returned Google objects should include
    `owning_account`. `service_models.py:143-153` has `owning_account` on
    `ThreadSummary`, but other Google-facing dataclasses such as
    `GoogleTask`, `DriveFile`, `Spreadsheet`, and `Document` still use either
    no account field or `account`, so normalized ownership is not consistent.

15. `inbox_server.py:3009-3020` exposes `/preflight/google-write`, and
    `google_account_resolution.py:160-272` implements payloads for docs, sheets,
    drive folders, tasks, and calendar events. The roadmap still names a broader
    `preflight_google_write(kind, account?, destination?, sharing?, naming?)`;
    current preflight checks destination existence for some paths, but does not
    yet encode sharing or naming policy.

16. `rg --files -g 'runs/**' -g 'docs/overnight/**' -g '.github/**' -g 'items/**'`
    returned no files before this report was created. There were no prior
    overnight outputs, runner handoffs, local queue `items/` files, or CI config
    files available for this pass.

## Validation commands

Required queue validation:

```bash
git status --short
```

Agent-safe validation documented by the repo:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe
uv run ruff check .
uv run pyright
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py -q
```

Additional review command attempted:

```bash
UV_CACHE_DIR=/private/tmp/inbox-sym-214-uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe --collect-only -q
```

Result: blocked by restricted network while downloading `tokenizers==0.22.2`,
pulled through `mlx-lm -> transformers -> tokenizers`. The first attempt without
`UV_CACHE_DIR` also failed because `uv` tried to open `/Users/jwalinshah/.cache/uv`,
which is outside this sandbox's writable roots.

## Risks and blockers

- Missing local queue issue file:
  `items/inbox-sym-214-risk-and-validation-review/ISSUE.md` is absent.
- No visible CI workflow: no `.github/**` files were present.
- Safe test marker coverage is narrow: only two test files are marked `safe`.
- `uv run` validation could not complete offline because dependency resolution
  attempted to download `tokenizers`.
- Runtime docs are stale or ambiguous: README says Python 3.10+, while
  `pyproject.toml` requires Python 3.12+; docs also contain an unverified
  "736 tests pass" claim.
- Auth is optional by environment; unset `INBOX_SERVER_TOKEN` or
  `INBOX_MCP_TOKEN` leaves local HTTP/MCP endpoints open.
- Background scheduler defaults can perform live sends/tasks/reminders and can
  persist scheduled work in a repo-local ignored SQLite DB.
- Source-of-truth Google account policy exists in code and tests, but is not
  represented in `config/inbox.env.example`.
- Normalized ownership is incomplete: `owning_account` is implemented for
  thread summaries, but not consistently across tasks, files, docs, and sheets.

## Implementation-ready follow-up tasks

### 1. Add a repo CI workflow for the agent-safe validation loop

Owned files:
- `.github/workflows/ci.yml`
- `docs/TESTING_FOR_AGENTS.md`
- `DOCS_INDEX.md`

Acceptance criteria:
- CI runs on pull requests and push to main.
- CI installs dependencies with `uv` and runs the documented safe loop:
  `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, and
  `uv run pyright`.
- CI sets `INBOX_TEST_MODE=1` and a temp `INBOX_TEST_DATA_DIR`.
- Docs link the CI workflow as the source of truth for agent-safe validation.

Smallest useful validation:

```bash
uv run ruff check .
uv run pyright
INBOX_TEST_MODE=1 uv run pytest -m safe
```

### 2. Expand the `safe` marker to cover deterministic guard and contract tests

Owned files:
- `tests/test_services.py`
- `tests/test_tools_registry.py`
- `tests/test_server.py`
- `tests/test_api_contract.py`
- `docs/TESTING_FOR_AGENTS.md`

Acceptance criteria:
- Deterministic tests for live-write blocking, MCP confirmation gating, auth
  behavior, API/tool path contracts, and account/preflight routing are included
  in `pytest -m safe`.
- Tests that touch live provider data, local macOS stores, microphone input, or
  external writes remain unmarked or explicitly marked `local_data`/`live_write`.
- `docs/TESTING_FOR_AGENTS.md` explains which test classes belong in the safe
  marker.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe --collect-only -q
INBOX_TEST_MODE=1 uv run pytest -m safe
```

### 3. Make test-mode storage isolation cover scheduler and memory databases

Owned files:
- `scheduler.py`
- `memory_store.py`
- `inbox_test_mode.py`
- `tests/test_inbox_test_mode.py`
- `tests/test_server.py`

Acceptance criteria:
- In `INBOX_TEST_MODE=1`, default scheduler and memory DB paths live under
  `INBOX_TEST_DATA_DIR` or another temp test-data root.
- Creating scheduled messages, followups, task links, or memory entries during
  tests cannot write `.inbox_scheduler.sqlite3` or `.inbox_memory.sqlite3` in the
  repo root.
- Tests prove the default path redirection and preserve explicit constructor DB
  path overrides.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py tests/test_mcp_gateway.py -q
INBOX_TEST_MODE=1 uv run pytest tests/test_server.py -k "scheduler or memory or test_mode" -q
```

### 4. Encode Google account policy in config and normalize ownership fields

Owned files:
- `config/inbox.env.example`
- `google_account_resolution.py`
- `service_models.py`
- `services.py`
- `inbox_server.py`
- `tests/test_server.py`

Acceptance criteria:
- `config/inbox.env.example` documents `INBOX_DEFAULT_GOOGLE_ACCOUNT`.
- Google write endpoints and preflight return the same resolved account when
  account is omitted.
- Google-facing response models consistently expose `owning_account` or a
  documented compatibility alias from `account`.
- Tests cover Docs, Sheets, Drive, Tasks, Calendar, and Gmail reply routing under
  a configured default account and under an explicit override.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_server.py -k "default_account or preflight or owning_account or reply_auto_routes" -q
```

### 5. Replace stale validation/setup claims with generated or test-backed docs

Owned files:
- `README.md`
- `DOCS_INDEX.md`
- `CLAUDE.md`
- `docs/TESTING_FOR_AGENTS.md`
- `tests/test_inbox_test_mode.py`

Acceptance criteria:
- Python version docs match `pyproject.toml`.
- Documentation avoids hard-coded "all tests pass" counts unless generated from
  a current validation artifact.
- Docs distinguish quick local smoke tests from full live-provider or local-data
  checks.
- Existing doc tests are updated so stale Python/test-count claims fail fast.

Smallest useful validation:

```bash
rg -n "Python 3.10|736 tests|736 pass" README.md DOCS_INDEX.md CLAUDE.md docs
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py -q
```

## Handoff

Files changed:
- `docs/overnight/2026-05-07-whole-portfolio-review/inbox-sym-214-risk-and-validation-review.md`

Commit SHA:
- Current HEAD during review: `2805b84`
- No commit was created; PR creation and pushes are out of scope for this queue
  item.

PR URL:
- None. External pushes and PR creation are out of scope.

Required validation:
- `git status --short` exited 0 after writing this report and returned:

```text
?? docs/overnight/
```

Blockers:
- Local queue issue file was missing.
- Dependency-backed pytest collection could not run in this sandbox because
  `uv` needed network access to download `tokenizers`.
- The `uv` retry created an ignored `.venv` before failing; `git status --short`
  does not show ignored files, and cleanup with `rm -rf .venv` was blocked by
  local execution policy.
