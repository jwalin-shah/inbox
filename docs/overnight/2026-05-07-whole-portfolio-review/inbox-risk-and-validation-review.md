# Inbox Risk And Validation Review

Queue item: `inbox-risk-and-validation-review`
Branch: `codex/goal-inbox-risk-and-validation-review`
Review date: 2026-05-07
Pass: risk-and-validation-review

## Scope

This review covered the local `inbox` worktree only. It used repo-local evidence from docs, package metadata, scripts, deployment examples, tests, recent git history, and current git state. Product code was not edited.

No prior overnight outputs were present in this worktree: `fd -a 'overnight|handoff|result.json|runs' .` returned no paths before this report was added.

## Validation Commands Run

| Command | Result |
| --- | --- |
| `git status --short --branch` | Passed before report creation; branch was `codex/goal-inbox-risk-and-validation-review` with no tracked changes. |
| `llm-tldr tree .` | Passed; used to inventory repo structure. |
| `rg --files docs .github scripts deploy config tests \| sort` | Returned expected docs/scripts/tests and reported `.github` missing. |
| `INBOX_TEST_MODE=1 uv run pytest -m safe -q` | Blocked before collection: sandbox denied `uv` cache access under `~/.cache/uv`. |
| `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe -q` | Blocked by restricted network while `uv` tried to download `numba==0.65.0`, pulled by `mlx-whisper`. |
| `git status --short` | Required queue validation; it reported only the new `docs/overnight/` report path. Staging/commit was blocked by git metadata permissions and is recorded in the worker handoff. |

## Concrete Observations

1. `README.md` says the requirement is Python 3.10+, while `pyproject.toml` requires `>=3.12,<3.15` and `.python-version` pins `3.12`. This is a stale setup claim that can send new agents down the wrong environment path.
2. `docs/TESTING_FOR_AGENTS.md` defines the intended safe loop as `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, and `uv run pyright`, with explicit warnings not to run `local_data` or `live_write` tests without opt-in.
3. `pyproject.toml` has pytest coverage enabled by default with `--cov=. --cov-report=term-missing` and declares markers for `safe`, `integration`, `local_data`, `slow`, and `live_write`.
4. `tests/conftest.py` stubs heavy or hardware-bound modules such as `mlx_lm`, `mlx_whisper`, `sounddevice`, `outlines`, and `Quartz`, but dependency installation still tries to fetch `mlx-whisper` transitive dependencies before tests can collect.
5. `pyproject.toml` depends directly on `mlx-lm`, `mlx-whisper`, `pyobjc-framework-applicationservices`, `pyobjc-framework-Quartz`, and `sounddevice`; `uv.lock` pins `numba==0.65.0` through `mlx-whisper`, which caused the offline validation failure.
6. Only `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py` are marked `pytest.mark.safe`. Representative write-blocking regressions in `tests/test_services.py` are not included in the documented `-m safe` loop.
7. `inbox_test_mode.py` provides `assert_live_writes_allowed`, and `services.py` calls `_assert_live_write_allowed` across many mutating operations: Gmail sends/archive/delete/labels, calendar CRUD, Apple Reminders, Google Tasks, Drive, Sheets, Docs, GitHub notification mutation, WhatsApp send, desktop notifications, and attendee modification.
8. `tests/test_services.py` verifies representative and extended live-write blockers, including Gmail reply, calendar event creation, Apple Reminder completion, Google Task creation, Drive folder creation, Sheet update, Doc creation, GitHub notification mutation, desktop notification, and WhatsApp send.
9. `tools_registry.py` centralizes MCP tool registration and marks mutating tools as `confirm=True`; `tests/test_tools_registry.py` asserts all non-read-only tools are confirmation-gated and that read-only registration excludes write tools.
10. `mcp_gateway.py` allows `/health` without `INBOX_MCP_TOKEN` but protects other MCP routes when the token is set. `inbox_server.py` also makes `INBOX_SERVER_TOKEN` optional, returning open local access when the token is unset.
11. `MCP_SETUP.md` and `deploy/Caddyfile.example` correctly recommend exposing only `/health` and `/mcp`, keeping the private backend on `127.0.0.1:9849`, and exposing the read-only MCP endpoint first.
12. `scripts/run_inbox_backend.sh`, `scripts/run_inbox_mcp_http.sh`, and `scripts/run_inbox_mcp_http_readonly.sh` set `UV_CACHE_DIR=/tmp/uv-cache`, but `README.md`, `CLAUDE.md`, and `docs/TESTING_FOR_AGENTS.md` do not mention this for validation commands.
13. `.pre-commit-config.yaml` configures ruff, ruff-format, generic pre-commit hooks, and bandit, but there is no `.github/workflows` directory in the local worktree, so CI parity cannot be verified from repo evidence.
14. `message_index_store.py` stores `sync_state`, `items`, `threads`, and `sender_stats` with WAL enabled and idempotent item/thread upserts, giving the index a clear local validation surface.
15. `message_index_store.py` updates `last_success_at` inside `set_sync_state` for all statuses, including `mark_sync_started` and `update_sync_progress`. `inbox_server.py` index health treats `last_success_at` as freshness evidence, so a running or interrupted sync could look fresher than the last completed success unless tests pin that behavior.
16. `message_sync.py` has tests for resumable Gmail bootstrap, Gmail history-cursor incremental sync, timestamp fallback, skipped iMessage row checkpoint advancement, and scoped thread rebuilds in `tests/test_message_sync.py`.
17. `thread_classifier.py` is intentionally heuristic and simple. `tests/test_thread_classifier.py` directly covers only OTP ignore behavior, while richer classifier behavior is covered indirectly through `tests/test_message_index_store.py`.
18. `inbox_server.py` exposes index-first views and `/inbox/needs-action`; `tests/test_server.py` asserts `raw_provider_fetch` is false for indexed views and that `/inbox/needs-action` does not fall back to live Gmail when the index is empty.

## Risks And Blockers

1. Safe validation is not self-contained in the current sandbox. Even with `UV_CACHE_DIR=/tmp/uv-cache`, `uv run pytest -m safe -q` attempted to download `numba==0.65.0`; this blocks offline or restricted-network agents before tests collect.
2. The documented safe marker does not include several high-value live-write guard tests. A future agent following `docs/TESTING_FOR_AGENTS.md` can pass `-m safe` while missing regressions in `tests/test_services.py`.
3. Setup docs disagree on Python version. The repo will run agents on 3.12 through `.python-version` and `pyproject.toml`, but `README.md` still advertises 3.10+.
4. CI status cannot be established from local evidence because `.github/workflows` is absent. Pre-commit exists, but there is no repo-local workflow proving ruff, pyright, and safe tests run automatically.
5. Index health may overstate freshness because `last_success_at` is written during sync start/progress, not only after completed success.
6. Classifier coverage is thin for the exact categories that drive product risk: newsletters, receipts, appointments, health-admin, security, housing, opportunity review, and frequent-human-sender promotion.
7. HTTP write endpoints depend on optional local token auth plus service-layer test-mode guards. MCP writes are confirmation-gated, but direct REST access is not confirmation-gated by the server when the backend is reachable with a valid or absent `INBOX_SERVER_TOKEN`.
8. Validation docs omit the `UV_CACHE_DIR=/tmp/uv-cache` workaround already used by runtime scripts, so agents in restricted environments hit avoidable cache permission failures.

## Implementation-Ready Follow-Up Tasks

### 1. Make Agent-Safe Tests Collect Without Network

Owned files:
- `pyproject.toml`
- `uv.lock`
- `docs/TESTING_FOR_AGENTS.md`
- `tests/conftest.py`

Work:
- Split hardware/ML/audio dependencies into an optional dependency group or extra that is not required for the safe test loop.
- Keep stubs in `tests/conftest.py`, but make dependency sync for `-m safe` avoid downloading `mlx-whisper` transitive packages.
- Document the exact restricted-environment command with `UV_CACHE_DIR=/tmp/uv-cache`.

Acceptance criteria:
- A clean checkout can run the safe test command without contacting PyPI after the base Python/dev environment is available.
- Runtime scripts still install/run full app dependencies when requested.
- Docs distinguish safe validation from full local app dependency sync.

Smallest useful validation:
```bash
UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe -q
```

### 2. Put Live-Write Guard Regressions In The Safe Test Lane

Owned files:
- `tests/test_services.py`
- `tests/test_inbox_test_mode.py`
- `docs/TESTING_FOR_AGENTS.md`

Work:
- Mark the representative `INBOX_TEST_MODE` live-write blocker tests as `safe`.
- If needed, split live-write guard tests into a dedicated safe file so they are run by the documented command.
- Add a doc sentence that safe tests include guard tests but still do not touch providers.

Acceptance criteria:
- `pytest -m safe` includes service-level write blocker regressions for Gmail, Calendar, Reminders, Tasks, Drive, Sheets, Docs, GitHub, notifications, and WhatsApp.
- No test marked `safe` reaches a real provider, local personal DB, microphone, or notification mutation path.

Smallest useful validation:
```bash
UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe tests/test_inbox_test_mode.py tests/test_services.py -q
```

### 3. Tighten Index Freshness Semantics

Owned files:
- `message_index_store.py`
- `inbox_server.py`
- `tests/test_message_index_store.py`
- `tests/test_server.py`

Work:
- Preserve `last_success_at` for the last completed idle sync only.
- Track running progress through `status`, `last_run_started_at`, `checkpoint_value`, and metadata without making health look successful.
- Add health reasons for long-running or interrupted syncs if needed.

Acceptance criteria:
- Starting or progressing a sync does not make `/index/health` healthy unless a completed sync exists.
- An error after progress keeps the last successful timestamp separate from current failure state.
- Existing status and metadata tests still pass.

Smallest useful validation:
```bash
UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_message_index_store.py tests/test_server.py -k "sync_state or index_health" -q
```

### 4. Expand Classifier Fixtures For Actionable Views

Owned files:
- `thread_classifier.py`
- `tests/test_thread_classifier.py`
- `tests/test_message_index_store.py`

Work:
- Add table-driven fixtures for newsletter, receipt, appointment, health-admin, security alert, opportunity, housing, frequent human sender, and no-reply cases.
- Pin `topic`, `noise_class`, `urgency`, `actionability`, `needs_reply`, and `open_loop`.
- Only adjust classifier logic where tests expose a wrong or unstable classification.

Acceptance criteria:
- The categories used by indexed actionability views are directly tested.
- Low-value automated mail remains `archive` or `ignore`.
- Human/opportunity/security/health-admin examples produce stable `reply`, `review`, or `track` outputs.

Smallest useful validation:
```bash
UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_thread_classifier.py tests/test_message_index_store.py -q
```

### 5. Add Repo-Local CI Parity For Validation

Owned files:
- `.github/workflows/ci.yml`
- `docs/TESTING_FOR_AGENTS.md`
- `README.md`

Work:
- Add a GitHub Actions workflow that runs the same safe validation surface documented for agents.
- Include `ruff check .`, `pyright`, and `INBOX_TEST_MODE=1 pytest -m safe`.
- Update setup docs to align Python version and validation commands.

Acceptance criteria:
- Local docs and CI agree on Python 3.12.
- Pull requests get automated feedback for lint, type check, and safe tests.
- The workflow does not require personal tokens, local macOS databases, microphone access, or live providers.

Smallest useful validation:
```bash
git ls-files .github/workflows/ci.yml && UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe -q
```

## Suggested Morning Review Focus

- Check whether other queue items also hit `uv` network/dependency blockers; if yes, split heavy optional dependencies once instead of patching each report.
- Inspect any runner-created PRs for CI evidence, because this local worktree has no `.github/workflows` evidence.
- Prioritize follow-up task 1 before broad implementation, because it unblocks every future safe validation pass.
- Prioritize follow-up task 3 before relying on `/index/health` as a go/no-go signal for indexed-default work.
