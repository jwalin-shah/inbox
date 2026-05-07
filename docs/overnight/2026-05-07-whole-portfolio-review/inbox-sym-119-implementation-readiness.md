# inbox-sym-119 Implementation Readiness Review

Date: 2026-05-07
Branch: `codex/goal-inbox-sym-119-implementation-readiness`
Queue item: `inbox-sym-119-implementation-readiness`
Scope: read-only review and queue prep; no product code edits.

## Summary

`inbox-sym-119` is ready for several tightly scoped implementation slices around indexed inbox views, MCP tool coverage, scheduler safety, and validation hygiene. The repo has strong local evidence for the indexed read model and Google account policy direction, but implementation work should avoid live-provider validation by default because the project touches personal data, macOS local stores, OAuth tokens, and write-capable services.

No previous overnight `runs/*/result.json`, `runs/*/handoff.md`, `items/*/ISSUE.md`, or `docs/overnight/*` artifacts were present in this worktree. The review therefore uses repo-local docs, tests, scripts, package metadata, and current git state only.

## Concrete File Observations

1. `PLAN.md` defines the current product target as an indexed local inbox with `items`, `threads`, and `sync_state`, and explicitly says bootstrap/incremental sync hardening must come before expanding the TUI surface.
2. `README.md` says Python 3.10+ in Quick Start, while `pyproject.toml` requires `>=3.12,<3.15`; onboarding docs are stale relative to package metadata.
3. `pyproject.toml` defines the default pytest run as `--cov=. --cov-report=term-missing` and registers `safe`, `integration`, `local_data`, `slow`, and `live_write` markers.
4. `docs/TESTING_FOR_AGENTS.md` establishes the safe validation loop as `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, and `uv run pyright`.
5. `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py` are the only files currently marked with `pytestmark = pytest.mark.safe`; most deterministic unit coverage is not included in the documented safe loop.
6. `.pre-commit-config.yaml` runs Ruff with `--fix`, Ruff format, basic pre-commit hooks, and Bandit, but there is no `.github/**` workflow file in this worktree.
7. `message_index_store.py` owns the SQLite operational index schema, including `sync_state`, `items`, `threads`, and `sender_stats`, plus filtered `list_threads()` support for actionable, waiting-on, recent, needs-reply, and sender-scoped views.
8. `message_sync.py` has resumable Gmail bootstrap state, Gmail history-cursor incremental sync, timestamp fallback, iMessage rowid checkpoints, and scoped thread rebuilds after changed-source syncs.
9. `tests/test_message_sync.py` covers resumable Gmail bootstrap, history cursor persistence, timestamp fallback, iMessage skipped-row checkpoint advancement, and scoped rebuild behavior.
10. `tests/test_message_index_store.py` covers idempotent upserts/rebuilds, high-volume thread rebuilds, sender-frequency classification, waiting-on/recent filters, and latest-sender filtering.
11. `inbox_server.py` exposes `/index/status`, `/index/health`, `/index/views/{view_name}`, `/index/sync/bootstrap`, and `/index/sync/incremental`; `tests/test_server.py` covers index health states and index-view routing.
12. `inbox.py` already renders `Now`, `Actionable`, and `Waiting On` tabs from compact index views, but it refreshes `recent`, `actionable`, and `waiting-on` without also using `index_health()` for stale-index warnings.
13. `google_account_resolution.py` centralizes default Google account selection through `INBOX_DEFAULT_GOOGLE_ACCOUNT` and powers `/preflight/google-write`; this means roadmap account-policy work has partially landed.
14. `CONNECTOR_ROADMAP.md` still lists preflight and source-of-truth routing as future milestones even though `google_account_resolution.py` and `inbox_server.py` now implement part of that surface; future work should audit the remaining gaps, not rebuild the whole layer.
15. `tools_registry.py` centrally registers MCP tools and confirms all mutating tools require `confirm=True`, but it does not expose read-only indexed inbox views such as `/index/views/actionable`, `/index/views/recent`, or `/index/health`.
16. `scheduler.py` persists scheduled messages, follow-up reminders, and task-message links, while `inbox_server.py` exposes `/scheduled`, `/followups`, `/tasks/links`, and `/tasks/from-message`; `rg` found no scheduler-specific tests under `tests/`.
17. `mcp_gateway.py` has public bearer-token middleware and health payloads, and `tests/test_mcp_gateway.py` covers token rejection, health access, memory DB configuration, and backend health error reporting.
18. `scripts/setup_inbox_mcp.sh`, `config/inbox.env.example`, and `deploy/inbox-mcp.service.example` provide local service bootstrap surfaces, but they are manual local/deploy scaffolds rather than CI validation.

## Validation Commands

Required queue validation:

```bash
git status --short
```

Agent-safe baseline from repo docs:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe
uv run ruff check .
uv run pyright
```

Useful focused validation for the ready implementation areas:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_message_sync.py tests/test_message_index_store.py -q
INBOX_TEST_MODE=1 uv run pytest tests/test_server.py -q -k "IndexEndpoints or preflight or needs_action"
INBOX_TEST_MODE=1 uv run pytest tests/test_client.py tests/test_tools_registry.py tests/test_mcp_gateway.py -q
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py -q
```

Do not run live provider, local-data, or live-write tests unless explicitly requested:

```bash
INBOX_TEST_MODE=1 uv run pytest -m "not local_data and not live_write"
```

## Risks And Blockers

- No CI workflow was present in this worktree, so there is no repo-local evidence that the safe suite, lint, type check, or pre-commit hooks run automatically on PRs.
- The documented `pytest -m safe` loop currently covers only a small slice of deterministic tests; many implementation-ready paths are tested but not safely discoverable by agents.
- The repo intentionally integrates with Gmail, Calendar, Drive, Docs, Sheets, Tasks, iMessage, Notes, Reminders, GitHub, microphone input, notifications, and local SQLite stores; live validation requires human approval and credentials.
- `README.md` and `DOCS_INDEX.md` contain stale claims relative to current package metadata and test layout, including Python version mismatch and a fixed "736 tests pass" claim.
- Scheduler behavior is write-capable and background-loop driven, but its persistence and server endpoints do not have dedicated local tests visible under `tests/`.
- MCP registry coverage is strong for confirmation gating, but read-only high-signal index views are absent from the tool registry, so agents may keep using raw provider reads where compact index reads already exist.
- Prior overnight runner artifacts were not available locally, so this pass cannot reconcile against earlier generated claims for this queue item.

## Implementation-Ready Follow-Up Tasks

### 1. Expand the agent-safe test lane for deterministic index coverage

Owned files:
- `tests/test_index_views_safe.py` or `tests/test_server.py`
- `tests/test_client.py`
- `docs/TESTING_FOR_AGENTS.md`

Acceptance criteria:
- Add safe-marked tests for `/index/health`, `/index/views/recent`, `/index/views/actionable`, `/index/views/waiting-on`, and `InboxClient.index_view()`.
- The safe lane proves compact indexed read paths without touching live Gmail, iMessage, local personal DBs, or external writes.
- `docs/TESTING_FOR_AGENTS.md` names the expanded safe coverage.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe -q
```

### 2. Add scheduler persistence and endpoint tests before more background-loop work

Owned files:
- `tests/test_scheduler.py`
- `tests/test_server.py`
- `scheduler.py` only if tests expose a correctness bug

Acceptance criteria:
- Cover scheduling, cancellation, due-message lookup, follow-up creation/cancellation, due-followup lookup, task-message link creation, message lookup, task lookup, and unlink behavior using a temp SQLite DB.
- Cover `/scheduled`, `/followups`, `/tasks/links`, and `/tasks/from-message` routing with fake server state and no live provider writes.
- Preserve current confirmation-gated MCP exposure for scheduled/follow-up write tools.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_scheduler.py tests/test_server.py -q -k "scheduled or followup or task_link or from_message"
```

### 3. Expose compact indexed inbox views through the MCP tool registry

Owned files:
- `tools_registry.py`
- `mcp_backend.py`
- `tests/test_tools_registry.py`
- `tests/test_mcp_gateway.py`

Acceptance criteria:
- Add read-only MCP tools for index health and index views, such as `get_index_health` and `list_index_view`.
- Ensure `readonly_only=True` registration includes these tools.
- Ensure generated handler path/query encoding still passes existing registry tests.
- Do not add any write-capable index sync tools to the public read-only MCP surface unless separately confirmed.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_tools_registry.py tests/test_mcp_gateway.py -q
```

### 4. Make Gmail follow-up reply detection account-aware

Owned files:
- `scheduler.py`
- `inbox_server.py`
- `tests/test_scheduler.py`
- `tests/test_server.py`

Acceptance criteria:
- Store or otherwise resolve the owning Gmail account for follow-up reminders.
- `_process_followup_reminders()` must check the Gmail thread using the follow-up's owning account instead of `next(iter(state.gmail_services))`.
- Existing imessage follow-up behavior remains unchanged.
- Add a regression test with two fake Gmail accounts where only the owning account has the reply.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_scheduler.py tests/test_server.py -q -k "followup"
```

### 5. Surface index freshness in the TUI refresh path

Owned files:
- `inbox.py`
- `inbox_client.py` only if a helper adjustment is needed
- `tests/test_inbox_app.py`
- `tests/test_client.py`

Acceptance criteria:
- During TUI auxiliary refresh, call `index_health()` alongside index views.
- If index health is unhealthy or stale, show a compact sidebar/status warning without falling back to raw provider thread fetches.
- Existing Now, Actionable, and Waiting On rendering remains index-backed.
- Tests cover healthy, stale, and error index-health payloads with mocked client responses.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_app.py tests/test_client.py -q -k "index"
```

## Suggested Execution Order

1. Expand safe deterministic validation for index paths.
2. Add scheduler tests, because scheduler work is write-capable and undercovered.
3. Add read-only MCP index tools so agents consume compact indexed views.
4. Fix account-aware follow-up detection after tests pin the scheduler behavior.
5. Surface index freshness in the TUI once the safe index lane is trustworthy.

## Review Evidence Commands Run

```bash
llm-tldr tree .
git status --short --branch
git log --oneline -5
rg --files -g .github/** -g Makefile -g tox.ini -g pytest.ini -g .pre-commit-config.yaml -g requirements*.txt -g Dockerfile* -g compose*.yml -g *.yml -g *.yaml -g *.toml .
fd -H 'result.json|handoff.md|overnight|ISSUE.md' .
rg -n "pytest.mark|@pytest.mark" tests
rg -n "SchedulerStore|scheduled_messages|create_followup|list_followups|schedule_message" tests
```
