# inbox-sym-120 risk and validation review

Queue item: `inbox-sym-120-risk-and-validation-review`
Branch: `codex/goal-inbox-sym-120-risk-and-validation-review`
Review date: 2026-05-07
Review base: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`

## Scope

This pass reviewed the repo-local docs, tests, scripts, config, generated validation output, recent git state, and validation surface for `inbox-sym-120`. It did not modify product code, call external services, push branches, create PRs, or update trackers.

No prior report existed under `docs/overnight/2026-05-07-whole-portfolio-review/` at the start of this pass. The only existing `overnight` search hits were notification quiet-hours code/tests, not overnight review artifacts.

## Current git state

- Current branch: `codex/goal-inbox-sym-120-risk-and-validation-review`
- Starting HEAD: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`
- Recent history shows the branch starts from merged index-default work: `2805b84 Merge pull request #34 from jwalin-shah/codex/SYM-9-indexed-defaults`.
- `git status --short` was clean before this report was written.

## Validation commands

Required validation:

```bash
git status --short
```

Additional local validation attempted during review:

```bash
INBOX_TEST_MODE=1 uv run pytest --collect-only -q
```

Result: blocked before collection because `uv` attempted to initialize `/Users/jwalinshah/.cache/uv`, which is outside this worker sandbox.

```bash
UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest --collect-only -q
```

Result: blocked by restricted network while trying to download `googleapis-common-protos==1.74.0`. This created an ignored `.venv/` in the worktree but did not change tracked files.

Repo-documented validation commands that should be used in an environment with dependencies available:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe
uv run ruff check .
uv run pyright
uv run pytest -x -q
```

## File-path observations

1. `pyproject.toml` declares `requires-python = ">=3.12,<3.15"`, while `README.md` still says the requirement is Python 3.10+. That is a stale setup claim that can send agents to the wrong interpreter.

2. `docs/TESTING_FOR_AGENTS.md` defines the safe agent loop as `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, and `uv run pyright`, but only `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py` currently set `pytestmark = pytest.mark.safe`.

3. `pyproject.toml` registers `safe`, `integration`, `local_data`, `slow`, and `live_write` markers, but the marker assignment coverage is much thinner than the total test tree under `tests/`, so `pytest -m safe` does not yet represent the repo's deterministic validation surface.

4. `.factory/services.yaml` defines `test: uv run pytest --ignore=tests/test_audio.py --ignore=tests/test_llm.py -x -q`, while `test_all` is `uv run pytest -x -q`. Multiple generated validation summaries record full-suite passes, so the default factory command may now hide audio/LLM regressions.

5. `.factory/validation/fix-broken-state/scrutiny/synthesis.json` records a pass but explicitly rejects, as already-documented, the observation that the default `.factory/services.yaml` test command skips `tests/test_audio.py` and `tests/test_llm.py`.

6. `.factory/validation/architecture-hardening/scrutiny/synthesis.json` records a systemic setup issue: direct execution of `.factory/init.sh` failed with `Permission denied` in multiple reviews and required `bash .factory/init.sh`.

7. `.factory/init.sh` and `.factory/services.yaml` hard-code `/Users/jwalinshah/projects/inbox`, which is risky for this whole-portfolio worktree pattern because validation can accidentally target the primary checkout instead of the isolated worktree.

8. `deploy/com.inbox.backend.plist.example`, `deploy/com.inbox.mcp.plist.example`, `deploy/com.inbox.mcp-readonly.plist.example`, and the systemd examples also hard-code `/Users/jwalinshah/projects/inbox`. That is acceptable for personal deployment examples but risky if copied into worktree validation without editing.

9. There is no `.github/` directory in this worktree, so CI/workflow validation is not repo-local. The only automated commit-time guard visible in the repo is `.pre-commit-config.yaml`.

10. `.pre-commit-config.yaml` runs Ruff, Ruff format, generic hygiene hooks, private-key detection, and Bandit, but it does not run `pyright` or pytest. Type and test validation depend on manual commands or external automation not present in this repo.

11. `services.py` has broad live-write guards through `_assert_live_write_allowed`, including Gmail, Calendar, Reminders, Google Tasks, Drive, Sheets, Docs, notifications, and GitHub notification mutations. `tests/test_inbox_test_mode.py` validates the helper and path redirection, but most broader write-surface tests are not marked `safe`.

12. `inbox_server.py` makes API auth optional: if `INBOX_SERVER_TOKEN` is unset, `_is_authorized` returns true for all requests. This matches `README.md` and `CLAUDE.md`, but it means local security depends entirely on environment setup.

13. `mcp_gateway.py` allows `/health` without `INBOX_MCP_TOKEN`, and if `INBOX_MCP_TOKEN` is unset, the public MCP middleware allows all paths. `MCP_SETUP.md` and `config/inbox.env.example` document the token, but a missing service env is a high-impact deployment misconfiguration.

14. `tools_registry.py` centralizes MCP tool exposure and confirmation gates. `tests/test_tools_registry.py` checks that all mutating tools require `confirm=True` and that read-only registration excludes write tools. This is one of the strongest safety checks in the repo.

15. `.factory/validation/reminders-tab/scrutiny/synthesis.json` still records a blocking risk for same-title duplicate Reminders: AppleScript selects the first reminder matching title and list. Current `services.py` confirms this path through `_applescript_find_reminder`, which uses `first reminder whose name is ...`.

16. `inbox_server.py` exposes `/index/health` and flags `no_sync_state`, `missing_checkpoint`, `stale_checkpoint`, and `sync_error`, but `inbox.py` fetches indexed `recent`, `actionable`, and `waiting-on` views without querying or surfacing index health. A stale or empty index can therefore look like a quiet inbox in the TUI.

17. Recent commit `a821b5a Make indexed inbox views the default` added indexed view behavior and tests in `inbox_server.py`, `inbox_client.py`, `message_index_store.py`, `tests/test_api_contract.py`, `tests/test_client.py`, `tests/test_message_index_store.py`, and `tests/test_server.py`. `README.md`, `CLAUDE.md`, and `DOCS_INDEX.md` do not document `/index/*` endpoints or index freshness operations.

18. `message_index_store.py` now uses a temporary keep table during `rebuild_threads`, and `tests/test_message_index_store.py` covers 1100 threads to prevent expression-depth regressions. This addresses a recent scalability bug with a focused regression test.

19. `google_account_resolution.py` implements `INBOX_DEFAULT_GOOGLE_ACCOUNT`, message-owner Gmail routing, and preflight payloads. Some endpoints still bypass the shared helpers: `inbox_server.py` falls back to the first Gmail service in `get_messages` when the cache misses, and `list_gmail_labels` also picks the first service directly.

20. `CONNECTOR_ROADMAP.md` says Google objects should expose `owning_account`; `services.py` has `ThreadSummary.owning_account`, but several user-facing API shapes still expose `gmail_account` or per-type account fields rather than a single normalized ownership field.

## Risk and blocker summary

- Highest validation blocker: pytest collection cannot run in this sandbox unless dependencies are already cached. The first attempt failed on `~/.cache/uv` permissions; the second, with `UV_CACHE_DIR=/tmp/uv-cache`, failed on restricted network dependency download.
- Highest runtime correctness risk: indexed TUI views can be stale or empty without surfacing `/index/health`.
- Highest data-mutation risk: Reminders mutation semantics are not ID-stable for duplicate titles within the same list.
- Highest account-routing risk: most Google write helpers use shared account resolution, but some Gmail read/label paths still use first-service fallback.
- Highest process risk: no repo-local GitHub Actions config is present, and pre-commit does not cover pytest or pyright.
- Highest documentation risk: setup/test claims have drifted from `pyproject.toml`, current test counts, and the newer index API surface.

## Implementation-ready follow-up tasks

### 1. Make agent validation runnable and explicit in isolated worktrees

Owned files:
- `docs/TESTING_FOR_AGENTS.md`
- `.factory/services.yaml`
- `.factory/init.sh`
- Optional new helper: `scripts/validate_agent_safe.sh`

Acceptance criteria:
- Agent-safe validation commands set `INBOX_TEST_MODE=1` and `UV_CACHE_DIR=/tmp/uv-cache`.
- `.factory/init.sh` can be run through `bash .factory/init.sh` from any worktree without hard-coding the primary checkout.
- The docs distinguish dependency-cache/network failures from test failures.
- `.factory/services.yaml` no longer makes the skipped audio/LLM subset look like the authoritative default if full-suite validation is expected.

Smallest useful validation:

```bash
bash .factory/init.sh
UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest --collect-only -q
```

### 2. Expand the deterministic `safe` pytest marker set

Owned files:
- `tests/test_api_contract.py`
- `tests/test_client.py`
- `tests/test_tools_registry.py`
- `tests/test_message_index_store.py`
- `tests/test_message_sync.py`
- `docs/TESTING_FOR_AGENTS.md`

Acceptance criteria:
- Pure unit/API-contract tests that do not touch live data are marked `safe`.
- Tests requiring local personal stores, live providers, microphone/audio hardware, or visible writes remain unmarked or receive explicit opt-in markers.
- `INBOX_TEST_MODE=1 uv run pytest -m safe --collect-only -q` collects a meaningful cross-section of API contracts, MCP tool safety, index store behavior, and test-mode guards.

Smallest useful validation:

```bash
UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe --collect-only -q
UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py tests/test_mcp_gateway.py tests/test_tools_registry.py -q
```

### 3. Surface index freshness in the TUI and docs

Owned files:
- `inbox.py`
- `inbox_client.py`
- `tests/test_client.py`
- `tests/test_server.py`
- `README.md`
- `CLAUDE.md`

Acceptance criteria:
- TUI refresh calls `index_health()` before or alongside indexed views.
- `no_sync_state`, `missing_checkpoint`, `stale_checkpoint`, and `sync_error` produce a visible status instead of silently showing empty indexed tabs.
- Docs explain the `/index/status`, `/index/health`, `/index/views/{view}`, `/index/sync/bootstrap`, and `/index/sync/incremental` endpoints.
- Existing indexed-view tests still pass, and at least one new test covers stale index status surfacing.

Smallest useful validation:

```bash
UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_client.py tests/test_server.py tests/test_api_contract.py -q
```

### 4. Finish shared Google account-resolution coverage

Owned files:
- `inbox_server.py`
- `google_account_resolution.py`
- `tests/test_gmail_actions.py`
- `tests/test_server.py`

Acceptance criteria:
- `GET /messages/gmail/{msg_id}` resolves by explicit account, cache owner, message/thread existence, then `INBOX_DEFAULT_GOOGLE_ACCOUNT`; it does not silently use first service on cache miss.
- `GET /gmail/labels` uses `get_gmail_service_for_account` and respects `INBOX_DEFAULT_GOOGLE_ACCOUNT`.
- Tests cover default-account env behavior and cache-miss message lookup.
- Response shapes consistently expose either `owning_account` or a documented compatibility field.

Smallest useful validation:

```bash
UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_gmail_actions.py tests/test_server.py -q
```

### 5. Remove or explicitly fence the duplicate-title Reminders mutation hazard

Owned files:
- `services.py`
- `inbox_server.py`
- `inbox_client.py`
- `tests/test_reminders.py`
- `tests/test_server.py`

Acceptance criteria:
- Completing, editing, uncompleting, or deleting a reminder cannot mutate an arbitrary same-title reminder in the same list.
- If stable ID targeting is impossible through AppleScript, the API detects ambiguous title/list matches and returns a conflict requiring user disambiguation.
- Tests cover duplicate incomplete reminders with the same title and list.
- Existing list-name disambiguation across different lists remains supported.

Smallest useful validation:

```bash
UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_reminders.py tests/test_server.py -q
```

## Handoff

Changed file:
- `docs/overnight/2026-05-07-whole-portfolio-review/inbox-sym-120-risk-and-validation-review.md`

Local commit blocker:
- `git add docs/overnight/2026-05-07-whole-portfolio-review/inbox-sym-120-risk-and-validation-review.md && git diff --cached --check && git commit -m "Add inbox risk validation review"` failed because git could not create `/Users/jwalinshah/projects/inbox/.git/worktrees/inbox-sym-120-risk-and-validation-review/index.lock` from this sandbox.

No PR was created. External services, deploys, pushes, tracker updates, and product-code edits were intentionally out of scope.
