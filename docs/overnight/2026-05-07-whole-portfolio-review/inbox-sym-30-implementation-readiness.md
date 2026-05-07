# inbox-sym-30 implementation-readiness review

Queue item: `inbox-sym-30-implementation-readiness`
Branch: `codex/goal-inbox-sym-30-implementation-readiness`
Base HEAD inspected: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`

## Scope and validation

This is a read-only implementation-readiness pass. I did not edit product code, run external services, push, open a PR, or update trackers.

Queue validation command:

```bash
git status --short
```

Agent-safe validation commands documented by the repo:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe
uv run ruff check .
uv run pyright
```

Factory validation commands used by previous generated reviews:

```bash
uv run pytest -x -q
uv run pyright
uv run ruff check .
```

Repo-local overnight outputs: none found under `docs/overnight/` or `runs/`. Generated `.factory/validation/*/synthesis.json` files were used as the available prior validation evidence.

## Concrete file observations

1. `PLAN.md` defines Phase 1 as index-first inbox work and explicitly says bootstrap sync, incremental sync, classification, indexed TUI views, waiting-on views, and calendar context are incomplete or next up.
2. `message_sync.py` has concrete bootstrap and incremental entrypoints for Gmail and iMessage, with Gmail page-token resume metadata, Gmail history cursor support, iMessage rowid checkpoints, and scoped thread rebuilds.
3. `message_index_store.py` owns the local `.inbox_index.sqlite3` schema with `sync_state`, `items`, `threads`, and `sender_stats`; `list_threads()` already supports `actionable_only`, `newest_only`, `actions`, `needs_reply`, `has_open_loop`, `latest_sender`, and priority/recent sorting.
4. `inbox_server.py` exposes `/index/threads`, `/index/status`, `/index/health`, `/index/views/{view_name}`, `/index/sync/bootstrap`, and `/index/sync/incremental`; the sync endpoints execute live provider syncs through `asyncio.to_thread`.
5. `inbox_server.py` maps `waiting-on-me` to `needs_reply=True`, `waiting-on-others` to `latest_sender="Me"`, and aggregate `waiting-on` to `actions=("track",), has_open_loop=True`; those are executable but semantically different views.
6. `inbox_client.py` has helpers for `index_health()`, `index_view()`, `indexed_recent_threads()`, `indexed_actionable_threads()`, `indexed_waiting_on_me_threads()`, and `indexed_waiting_on_others_threads()`.
7. `inbox.py` already fetches indexed `recent`, `actionable`, and aggregate `waiting-on` views for the TUI, but there is no use of `index_health()` and no distinct TUI surface for `waiting-on-me` versus `waiting-on-others`.
8. `tui_tabs.py` already renames the first tab to `Now` and includes `Actionable` and `Waiting On`, which makes the index-first information architecture partially implemented.
9. `tests/test_message_sync.py` covers Gmail bootstrap resume, history cursor recording, timestamp fallback, iMessage skipped-row checkpoint advancement, and scoped thread rebuilds.
10. `tests/test_message_index_store.py` covers idempotent upserts/rebuilds, sender stats, high-volume automated senders, waiting/recent filters, latest-sender filtering, and large rebuild scope behavior.
11. `tests/test_server.py` covers index endpoints, index health reasons, `/inbox/needs-action` using the index without live Gmail fallback, Google account defaults, Gmail reply routing, and Google write preflight behavior.
12. `docs/TESTING_FOR_AGENTS.md` defines the default safe loop as `INBOX_TEST_MODE=1 uv run pytest -m safe`, but `rg` found only two safe-marked test modules: `tests/test_mcp_gateway.py` and `tests/test_inbox_test_mode.py`.
13. `pyproject.toml` registers `safe`, `integration`, `local_data`, `slow`, and `live_write` markers and sets default pytest coverage, but most deterministic index/account tests are not marked `safe`.
14. `google_account_resolution.py` already implements `INBOX_DEFAULT_GOOGLE_ACCOUNT`, message/thread-owner Gmail resolution, and `preflight_google_write_payload()`, so the account-policy foundation exists.
15. `tools_registry.py` centralizes the MCP tool surface, confirm-gates every mutating registered tool, and supports readonly-only registration, but it does not yet expose the existing `/preflight/google-write` endpoint as an MCP tool.
16. `mcp_server.py`, `inbox_mcp_readonly.py`, `MCP_SETUP.md`, `config/inbox.env.example`, and `deploy/Caddyfile.example` document separate private backend, full MCP, and readonly MCP surfaces with separate tokens.
17. `.factory/services.yaml` uses `uv run pytest --ignore=tests/test_audio.py --ignore=tests/test_llm.py -x -q` for the default factory test command, while `test_all` is `uv run pytest -x -q`; prior `.factory/validation/*/synthesis.json` files show lint/typecheck/test passes but also record the audio/LLM exclusion as already documented.
18. `.pre-commit-config.yaml` has ruff, ruff-format, basic file hygiene hooks, and Bandit configured with `pyproject.toml`; no `.github` workflow files were found by `fd -H`.
19. `modes/morning-brief.md`, `modes/triage.md`, and `modes/followup-sweep.md` still instruct agents to start from raw `/conversations` reads, even though `PLAN.md` says raw provider dumps should not be the default and `/index/views/*` exists.
20. `batch/batch-runner.sh` has a dry-run mode but defaults to `DRY_RUN=false` and calls Gmail mutation endpoints directly, so it is not yet an ideal safe default for delegated overnight execution.

## Risks and blockers

- The code is close to executable index-first work, but the safe test marker coverage is too narrow for overnight agents. The default documented `-m safe` command currently misses most index, sync, server, account-routing, and TUI tests.
- Index freshness can be diagnosed through `/index/health`, but the TUI does not surface stale, missing, or errored sync state. An empty index could look like an empty inbox.
- The slash-command mode docs still bias agents toward raw conversation fetches, which conflicts with the current Phase 1 product direction and can reintroduce high-token raw provider workflows.
- The aggregate `waiting-on` view is not the same as either `waiting-on-me` or `waiting-on-others`; implementation agents need a product decision before changing labels or tab behavior beyond the concrete split proposed below.
- Full bootstrap/incremental sync validation needs live Gmail/iMessage access and local personal data. That should stay out of automated overnight validation unless explicitly requested.
- There is no repo-local GitHub Actions workflow evidence in this worktree, so CI readiness is inferred from `pyproject.toml`, `.pre-commit-config.yaml`, `.factory/services.yaml`, and prior `.factory/validation` outputs.
- `batch/batch-runner.sh` can perform Gmail archive mutations if invoked without `--dry-run`; any future automation around it needs explicit confirmation or test-mode protection first.

## Implementation-ready follow-up tasks

### 1. Expand the agent-safe test lane for index-first work

Owned files:

- `tests/test_message_sync.py`
- `tests/test_message_index_store.py`
- `tests/test_server.py`
- `tests/test_client.py`
- `tests/test_gmail_actions.py`
- `docs/TESTING_FOR_AGENTS.md`

Acceptance criteria:

- Deterministic index, sync-store, index endpoint, preflight, account-routing, and client-helper tests are marked `pytest.mark.safe` at module/class/function granularity.
- No `local_data`, `live_write`, or live provider tests are included in the safe lane.
- `docs/TESTING_FOR_AGENTS.md` names the expanded safe coverage and keeps live-write opt-in guidance intact.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe tests/test_message_sync.py tests/test_message_index_store.py tests/test_server.py tests/test_client.py tests/test_gmail_actions.py -q
```

### 2. Expose Google write preflight through the client and MCP registry

Owned files:

- `inbox_client.py`
- `tools_registry.py`
- `tests/test_client.py`
- `tests/test_tools_registry.py`
- `tests/test_mcp_gateway.py`

Acceptance criteria:

- `InboxClient` has a `preflight_google_write(...)` helper for `/preflight/google-write`.
- `tools_registry.TOOLS` includes a readonly `preflight_google_write` tool that is registered in both full and readonly MCP surfaces.
- Tool parameters cover `kind`, `account`, `folder_id`, `list_id`, `calendar_id`, and `title`.
- Registry tests prove the tool is readonly, not confirm-gated, and present in readonly registration.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_client.py tests/test_tools_registry.py tests/test_server.py::TestPreflight -q
```

### 3. Surface index health in the TUI status flow

Owned files:

- `inbox.py`
- `inbox_client.py`
- `tests/test_inbox_app.py`
- `tests/test_client.py`

Acceptance criteria:

- The TUI polls `client.index_health()` during refresh/poll flows without crashing if the health request fails.
- Stale, missing-checkpoint, no-sync-state, and sync-error states produce a clear status warning.
- Healthy index state keeps the existing indexed-thread status behavior.
- Existing sustained-outage behavior remains unchanged.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_app.py tests/test_client.py::TestClientIndexedInbox -q
```

### 4. Make slash-command modes index-first

Owned files:

- `modes/morning-brief.md`
- `modes/triage.md`
- `modes/followup-sweep.md`
- `modes/_shared.md`
- `README.md` or `CLAUDE.md` if command docs need a brief update

Acceptance criteria:

- Morning brief starts from `/inbox/needs-action` plus `/index/views/recent` instead of raw Gmail conversations.
- Triage starts from `/index/views/actionable`, `/index/views/waiting-on-me`, `/index/views/waiting-on-others`, and only drills into raw messages for confirmation.
- Followup sweep uses indexed waiting/reply views before falling back to TSV or raw threads.
- The mode docs preserve explicit caps and avoid raw provider dumps as the default context.

Smallest useful validation:

```bash
rg -n "/index/views|/inbox/needs-action|/conversations\\?source" modes README.md CLAUDE.md
```

### 5. Split waiting-on-me and waiting-on-others in the TUI

Owned files:

- `tui_tabs.py`
- `inbox.py`
- `inbox_client.py`
- `tests/test_inbox_app.py`
- `tests/test_tui_tabs.py`
- `tests/test_server.py`

Acceptance criteria:

- The UI exposes separate user-visible filters or commands for `waiting-on-me` and `waiting-on-others`, or the aggregate `Waiting On` tab clearly combines both with stable section ordering.
- TUI refresh fetches the same server views as the labels imply.
- Tests cover the server route parameters, client helper calls, tab metadata, and TUI rendering/status counts.
- No raw provider fetch is added for these views.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_server.py::TestIndexEndpoints tests/test_client.py::TestClientIndexedInbox tests/test_tui_tabs.py tests/test_inbox_app.py -q
```

## Handoff

Recommended next issue: start with task 1. It widens the safe validation lane before workers change index or TUI behavior.

Commit/PR blocker: a local commit could not be created from this sandbox because `git add`/`git commit` needs to write `/Users/jwalinshah/projects/inbox/.git/worktrees/inbox-sym-30-implementation-readiness/index.lock`, which is outside the writable roots.

Do not mark external trackers done from this review. No PR was created.
