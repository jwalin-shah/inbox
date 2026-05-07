# inbox-sym-120 implementation-readiness review

Queue item: `inbox-sym-120-implementation-readiness`
Branch: `codex/goal-inbox-sym-120-implementation-readiness`
Reviewed HEAD: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`
Date: 2026-05-07

## Scope

This is a repo-local implementation-readiness pass. I did not touch product code,
call external services, inspect live personal data stores, push branches, open
PRs, or update trackers.

Previous overnight artifacts were not present in this worktree. `rg --files -g
'.github/**' -g 'docs/**' -g 'runs/**' -g '*handoff*' -g 'items/**'` returned
only `docs/TESTING_FOR_AGENTS.md` from those requested artifact classes, so this
report is based on the current repo docs, code, tests, scripts, config, and git
state.

## Repo observations

1. `PLAN.md:71` says `message_index_store.py` and `message_sync.py` already
   exist, and `PLAN.md:75` names the remaining Phase 1 risk: bootstrap sync is
   not hardened enough and incremental sync needs stronger checkpoints.

2. `PLAN.md:102` through `PLAN.md:122` define Milestone 1 around resumable
   bootstrap, incremental checkpoints, deterministic `items` / `threads` /
   `sync_state` upserts, and an API sync-health surface. This is already a good
   source for issue acceptance criteria.

3. `message_index_store.py:86` through `message_index_store.py:167` creates the
   local operational index tables: `sync_state`, `items`, `threads`, and
   `sender_stats`. The schema is explicit enough for focused data-model tests.

4. `message_index_store.py:239` through `message_index_store.py:356` implements
   sync-state writes, running/error status, metadata, and state listing. This
   makes index freshness work implementation-ready without adding a new store.

5. `message_index_store.py:407` through `message_index_store.py:563` rebuilds
   thread summaries and classifications from indexed items. It also deletes
   stale thread rows within the requested source/account scope, so future sync
   work should preserve these scope guarantees.

6. `message_index_store.py:565` through `message_index_store.py:612` supports
   `actionable_only`, `needs_reply`, `has_open_loop`, `latest_sender`, and
   `sort_mode`. The current `newest_only` filter is hard-coded to seven days,
   which is simple but should be tested as product behavior before more views
   depend on it.

7. `message_sync.py:181` through `message_sync.py:268` implements Gmail
   bootstrap with saved page tokens, timestamp checkpoints, and optional Gmail
   history cursor recording. The resume behavior is already covered by
   `tests/test_message_sync.py:143` through `tests/test_message_sync.py:201`.

8. `message_sync.py:272` through `message_sync.py:449` implements Gmail
   incremental sync through Gmail history when possible and timestamp fallback
   otherwise. `tests/test_message_sync.py:312` through
   `tests/test_message_sync.py:416` cover changed-message history sync and
   missing-history fallback.

9. `message_sync.py:498` through `message_sync.py:582` implements iMessage
   bootstrap and incremental sync with rowid checkpoints. `tests/test_message_sync.py:418`
   through `tests/test_message_sync.py:497` cover checkpoint advancement when
   rows are skipped because they have no useful body.

10. `message_sync.py:602` through `message_sync.py:627` rebuilds only changed
    source/account scopes after bootstrap or incremental sync. The focused
    regression tests at `tests/test_message_sync.py:499` through
    `tests/test_message_sync.py:649` make this safe to extend.

11. `thread_classifier.py:58` through `thread_classifier.py:130` is a compact
    heuristic classifier for human score, noise class, topic, urgency, and
    actionability. Existing tests in `tests/test_message_index_store.py:66`
    through `tests/test_message_index_store.py:230` cover human replies, OTP,
    frequent senders, and automated senders, but the fixture set is still thin
    for appointment, health-admin, receipt, security, and newsletter cases.

12. `inbox_server.py:565` through `inbox_server.py:624` defines response models
    that explicitly mark indexed read models as `read_model="index"` and
    `raw_provider_fetch=False`. This gives downstream clients a contract to
    assert against.

13. `inbox_server.py:2771` through `inbox_server.py:2807` routes named index
    views for `actionable`, `recent`, `waiting-on-me`, `waiting-on-others`, and
    `waiting-on`. `tests/test_server.py:276` through `tests/test_server.py:368`
    verify these routes call the index store with the intended filters.

14. `inbox_server.py:3739` through `inbox_server.py:3802` makes
    `/inbox/needs-action` prefer indexed threads and avoid Gmail provider
    fallback, but it still fetches live tasks and calendar events and silently
    drops task/calendar exceptions at `inbox_server.py:3773` and
    `inbox_server.py:3792`.

15. `tests/test_server.py:1816` through `tests/test_server.py:1936` verify that
    `/inbox/needs-action` returns index metadata and does not call live Gmail
    search even when the index is empty. This is a strong starting point for
    safe issue work around the Now view.

16. `inbox_client.py:86` through `inbox_client.py:131` already has client
    helpers for index threads, status, health, and indexed views. `inbox.py:2333`
    through `inbox.py:2349` fetches the `recent`, `actionable`, and `waiting-on`
    views for the TUI, but the TUI does not appear to surface `index_health()`
    yet.

17. `tui_tabs.py:19` through `tui_tabs.py:49` defines first-class `Now`,
    `Actionable`, and `Waiting On` tabs. `inbox.py:1702` through `inbox.py:1723`
    renders these tabs from indexed thread lists rather than raw provider
    conversations.

18. `tools_registry.py:126` through `tools_registry.py:173` starts the MCP tool
    registry with raw Gmail list/search and reply tools. There are no index
    status or index-view tools in the registry yet, so assistant-facing MCP usage
    can still default to raw provider reads even though the TUI and REST client
    have index-first surfaces.

19. `tests/test_api_contract.py:75` through `tests/test_api_contract.py:88`
    asserts that every MCP tool registry path exists on FastAPI, and
    `tests/test_api_contract.py:91` through `tests/test_api_contract.py:122`
    assert client/server shape for index status and health. This makes adding
    MCP index tools straightforward and testable.

20. `docs/TESTING_FOR_AGENTS.md:8` through `docs/TESTING_FOR_AGENTS.md:19`
    define the intended safe loop: `INBOX_TEST_MODE=1 uv run pytest -m safe`,
    `uv run ruff check .`, and `uv run pyright`. However, `rg` found
    `pytestmark = pytest.mark.safe` only in `tests/test_inbox_test_mode.py` and
    `tests/test_mcp_gateway.py`, so the documented safe suite is probably much
    narrower than the deterministic tests currently available.

21. `tests/conftest.py:15` through `tests/conftest.py:35` stubs ML and hardware
    modules such as `mlx_lm`, `mlx_whisper`, `sounddevice`, `outlines`, and
    `Quartz`, which should let many more tests run safely under
    `INBOX_TEST_MODE=1`.

22. `inbox_test_mode.py:18` through `inbox_test_mode.py:31` blocks live writes
    and redirects test data paths, while `services.py` calls `_assert_live_write_allowed`
    across Gmail, Calendar, Reminders, Tasks, Drive, Sheets, Docs, GitHub,
    notifications, and WhatsApp write paths. The safety hooks are broad enough
    to support a larger safe validation lane.

23. `pyproject.toml:54` through `pyproject.toml:62` configures pytest coverage
    and markers, but `.pre-commit-config.yaml:1` through `.pre-commit-config.yaml:23`
    only runs Ruff formatting/linting and Bandit. There is no `.github/`
    workflow in this worktree, so CI readiness cannot be verified from repo
    config.

24. `README.md:30` states Python 3.10+ as a requirement, while
    `pyproject.toml:4` requires `>=3.12,<3.15`. `DOCS_INDEX.md:142` also claims
    "All 736 tests pass" without tying that claim to a current validation run.

25. `.gitignore:12` through `.gitignore:23` ignores credentials and token files,
    and `.gitignore:34` through `.gitignore:58` ignores logs, local MCP memory,
    scheduler DB, batch state, and `.inbox_index.sqlite3`. That is aligned with
    the personal-data constraints in `docs/TESTING_FOR_AGENTS.md`.

26. `dev.sh:1` through `dev.sh:11` runs worktree development on port 9850 by
    default, and `scripts/run_inbox_backend.sh:1` through
    `scripts/run_inbox_backend.sh:9` runs the backend with `UV_CACHE_DIR` in
    `/tmp`. These scripts are useful validation surfaces for future agents but
    were not executed during this read-only pass.

## Risks and blockers

- No previous `runs/*/result.json`, `runs/*/handoff.md`, or overnight report was
  available in this worktree, so this pass could not reconcile runner outputs or
  prior handoffs.

- No `.github/` workflow was present. Local validation commands are documented,
  but CI behavior is not repo-evident.

- The documented safe pytest lane appears under-labeled. If agents run only
  `INBOX_TEST_MODE=1 uv run pytest -m safe`, they may miss most deterministic
  server, sync, index, and TUI regressions.

- `/inbox/needs-action` reports index provenance for threads, but task/calendar
  failures are swallowed silently. That can make the Now view look empty or
  healthier than it is.

- The MCP registry does not yet expose index-first read tools, so model-facing
  usage can still pull raw Gmail/provider surfaces by default.

- Thread intelligence is implementation-ready but still heuristic-heavy. Before
  broader TUI or MCP workflows depend on it, the representative fixture set
  should be expanded.

- Docs contain stale or inconsistent claims: Python 3.10+ in `README.md` versus
  Python 3.12+ in `pyproject.toml`, plus an unverified "736 tests pass" claim in
  `DOCS_INDEX.md`.

- Live-provider, local-data, external-write, and UI-browser validation were out
  of scope for this queue item.

## Validation commands

Required queue validation:

```bash
git status --short
```

Agent-safe validation commands documented by the repo:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe
uv run ruff check .
uv run pyright
```

Focused commands that should be used by follow-up implementation issues:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_message_sync.py tests/test_message_index_store.py -q
INBOX_TEST_MODE=1 uv run pytest tests/test_server.py tests/test_api_contract.py -q
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_app.py tests/test_tui_tabs.py -q
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py tests/test_mcp_gateway.py -q
```

## Implementation-ready follow-up tasks

### 1. Make the safe pytest lane representative

Owned files:
- `tests/test_api_contract.py`
- `tests/test_server.py`
- `tests/test_message_sync.py`
- `tests/test_message_index_store.py`
- `tests/test_inbox_app.py`
- `tests/test_tui_tabs.py`
- `docs/TESTING_FOR_AGENTS.md`

Acceptance criteria:
- Deterministic index, sync, server contract, and TUI unit tests are included in
  `pytest -m safe`.
- Tests that require live personal data, external writes, local macOS data, or
  slow provider behavior remain excluded from `safe`.
- The docs state what the safe suite covers and what remains opt-in.
- `INBOX_TEST_MODE=1 uv run pytest -m safe --collect-only -q` shows the intended
  expanded safe set.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe --collect-only -q
INBOX_TEST_MODE=1 uv run pytest -m safe -q
```

### 2. Add repo-local CI for non-live validation

Owned files:
- `.github/workflows/ci.yml`
- `pyproject.toml`
- `docs/TESTING_FOR_AGENTS.md`

Acceptance criteria:
- CI runs on pull requests and pushes without credentials or live personal data.
- CI runs `uv run ruff check .`, `uv run pyright`, and
  `INBOX_TEST_MODE=1 uv run pytest -m safe`.
- CI sets `INBOX_TEST_MODE=1` and does not require macOS data stores, OAuth
  tokens, microphones, or provider credentials.
- The testing doc points agents at the same commands used by CI.

Smallest useful validation:

```bash
uv run ruff check .
uv run pyright
INBOX_TEST_MODE=1 uv run pytest -m safe -q
```

### 3. Expose index-first read tools through MCP

Owned files:
- `tools_registry.py`
- `tests/test_api_contract.py`
- `tests/test_mcp_gateway.py`
- `mcp_backend.py` if legacy backend methods are kept in sync

Acceptance criteria:
- Add readonly MCP tools for index status, index health, and named index views.
- Tool responses preserve the REST contract: `read_model == "index"` and
  `raw_provider_fetch is False`.
- Indexed thread tools return compact summaries and do not expose `body_text`.
- Existing raw Gmail tools remain available for drill-down, not the default
  index-first path.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_api_contract.py tests/test_mcp_gateway.py -q
```

### 4. Surface index health in the TUI Now/Actionable/Waiting views

Owned files:
- `inbox.py`
- `inbox_client.py`
- `tests/test_inbox_app.py`
- `tests/test_api_contract.py`

Acceptance criteria:
- The TUI calls `index_health()` during refresh or auxiliary-data collection.
- If index health reports `no_sync_state`, `sync_error`, stale state, or missing
  checkpoints, the status area surfaces that condition instead of showing a
  silently empty indexed view.
- Existing `Now`, `Actionable`, and `Waiting On` tab rendering continues to use
  indexed views and does not fall back to live Gmail provider reads.
- Tests cover healthy, stale, and no-sync-state health responses.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_app.py tests/test_api_contract.py -q
```

### 5. Expand thread-classification fixtures before adding more indexed workflows

Owned files:
- `thread_classifier.py`
- `message_index_store.py`
- `tests/test_message_index_store.py`
- optional `tests/fixtures/thread_classifier_cases.py`

Acceptance criteria:
- Add representative deterministic cases for recruiter/opportunity,
  appointment/health-admin, newsletter, receipt, OTP, security alert, human SMS,
  and "latest sender is Me" waiting-on-others scenarios.
- `reply`, `review`, and `track` threads appear in actionable views; `archive`
  and `ignore` threads do not.
- Frequent-sender promotion does not override automated/newsletter/receipt
  noise classes.
- Any classifier changes keep summaries compact enough for index-first TUI and
  MCP usage.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_message_index_store.py -q
```

## Handoff

Report written:
- `docs/overnight/2026-05-07-whole-portfolio-review/inbox-sym-120-implementation-readiness.md`

Product code changed:
- None.

External actions:
- None. No deploys, pushes, PRs, tracker updates, live provider calls, or
  destructive cleanup.

Blockers:
- No previous overnight run artifacts or CI config were available in this
  worktree.
- Broader tests were not run because the queue validation command is
  `git status --short`.
- Local staging/commit was blocked by the sandbox: `git add
  docs/overnight/2026-05-07-whole-portfolio-review/inbox-sym-120-implementation-readiness.md`
  failed because git could not create
  `/Users/jwalinshah/projects/inbox/.git/worktrees/inbox-sym-120-implementation-readiness/index.lock`.
