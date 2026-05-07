# inbox-sym-214 Implementation Readiness Review

Date: 2026-05-07
Queue item: `inbox-sym-214-implementation-readiness`
Branch: `codex/goal-inbox-sym-214-implementation-readiness`

## Scope

This is a read-only implementation-readiness pass for the `inbox-sym-214`
worktree. The only repo change from this pass is this report. Product code,
external trackers, deploys, pushes, and PRs are out of scope.

Evidence inspected:

- Repo structure from `llm-tldr tree .`.
- Current git state from `git status --short`, `git status -sb`, `git log --oneline -8`, and `git remote -v`.
- Project docs, test guidance, package metadata, scripts, MCP config, and relevant source/test files.
- Previous overnight artifacts were checked with `rg --files -g 'docs/**' -g 'runs/**' -g 'items/**'`; this worktree only contained `docs/TESTING_FOR_AGENTS.md` in that scan, so no prior overnight report or runner output was available locally.

## Current State

- Initial `git status --short` was clean.
- Branch is `codex/goal-inbox-sym-214-implementation-readiness`.
- Remote is `origin https://github.com/jwalin-shah/inbox.git`.
- Recent history shows index-first work already landed: `2805b84 Merge pull request #34 from jwalin-shah/codex/SYM-9-indexed-defaults`, `05fc249 Add index sync health endpoint`, and `ae5f2fe Fix calendar range parameter forwarding`.
- No `.github` workflow files were present in this worktree, so CI behavior could not be verified from repo-local config.

## Concrete File Observations

1. `PLAN.md` defines Phase 1 around a local SQLite operational index, reliable bootstrap/incremental sync, indexed endpoints, and a TUI home surface that uses compact indexed state before raw provider fetches.
2. `README.md` describes a broad privacy-first TUI and API surface, but its requirement says Python 3.10+ while `pyproject.toml` requires `>=3.12,<3.15` and `.python-version` pins `3.12`.
3. `pyproject.toml` defines the real validation stack: `ruff`, `pyright`, `pytest`, coverage addopts, `bandit`, and markers for `safe`, `integration`, `local_data`, `slow`, and `live_write`.
4. `docs/TESTING_FOR_AGENTS.md` gives the safe agent loop as `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, and `uv run pyright`, and explicitly blocks local data/live-write tests unless opted in.
5. `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py` are the only files found with module-level `pytest.mark.safe`, so the documented safe loop appears too narrow for index/sync implementation work unless more deterministic suites are marked.
6. `message_sync.py` has concrete implementation surfaces for Gmail bootstrap resume tokens, Gmail history/timestamp cursors, iMessage rowid cursors, changed-scope thread rebuilds, and a CLI with `bootstrap`, `incremental`, `rebuild`, and `summary` modes.
7. `tests/test_message_sync.py` already covers Gmail bootstrap resume, history cursor capture, timestamp fallback without a history cursor, iMessage skipped-row checkpoint advancement, and changed-scope rebuilds. This makes sync hardening safe to continue with focused fake-service tests.
8. `message_index_store.py` owns the SQLite schema for `sync_state`, `items`, `threads`, and `sender_stats`, plus `list_threads` filters for actionable, recent, waiting/open-loop, needs-reply, latest-sender, and priority/recent sorting.
9. `tests/test_message_index_store.py` covers item/thread idempotence, human sender stats, OTP ignoring, high-volume automated sender demotion, waiting/recent filters, latest-sender filters, and a 1100-thread rebuild path that avoids SQLite expression-depth failures.
10. `thread_classifier.py` is intentionally heuristic and compact; `tests/test_thread_classifier.py` currently has only a direct OTP fixture, so classifier behavior is not yet protected across the main product classes described in `PLAN.md`.
11. `inbox_server.py` exposes `/index/threads`, `/index/status`, `/index/health`, `/index/views/{view_name}`, `/index/sync/bootstrap`, `/index/sync/incremental`, and `/inbox/needs-action`.
12. `tests/test_server.py` validates index endpoint shapes, stale/missing/error health reasons, view routing for `actionable`, `waiting-on`, `waiting-on-me`, and `waiting-on-others`, and confirms `/inbox/needs-action` does not fall back to live Gmail when the index is empty.
13. `inbox_client.py` has helpers for `index_health`, generic `index_view`, `indexed_recent_threads`, `indexed_actionable_threads`, `indexed_waiting_on_me_threads`, and `indexed_waiting_on_others_threads`.
14. `inbox.py` fetches `recent`, `actionable`, and `waiting-on` indexed views for the TUI, but does not currently surface the separate `waiting-on-me` and `waiting-on-others` helpers exposed by `inbox_client.py`.
15. `tools_registry.py` centralizes the MCP tool surface and `tests/test_tools_registry.py` confirms mutating tools are confirmation-gated and readonly registration excludes writes. The registry does not currently expose `/index/health`, `/index/views/{view_name}`, or `/inbox/needs-action`, so MCP agents may still reach for raw Gmail/thread tools instead of compact indexed views.
16. `MCP_SETUP.md`, `dev.sh`, `scripts/run_inbox_backend.sh`, `.mcp.json`, and `config/inbox.env.example` document a primary-vs-dev split, default dev port `9850`, and tokenized backend/MCP routing. This is enough to assign runtime-readiness work without touching provider credentials.
17. `.pre-commit-config.yaml` includes `ruff --fix`, `ruff-format`, `trailing-whitespace`, `end-of-file-fixer`, `check-yaml`, `check-added-large-files`, `detect-private-key`, and `bandit -c pyproject.toml`, but no repo-local CI workflow was found to enforce them remotely.
18. `DOCS_INDEX.md` claims "All 736 tests pass" and "production-ready" for Sheets, but that count is a stale claim unless refreshed by a current test run; no current runner output was available in this worktree.

## Readiness Assessment

The repo is ready for small, executable implementation slices around the
indexed-inbox path. The index store, sync layer, server endpoints, client
helpers, and TUI already have enough boundaries and tests to assign narrow
follow-up work with file ownership and focused validation.

The safest next wave should avoid live providers and use fake services,
`INBOX_TEST_MODE=1`, and endpoint/client unit tests. Work that requires real
Gmail, Calendar, Drive, Reminders, iMessage, microphone, OAuth, or MCP exposure
should stay out of unattended implementation unless the issue explicitly opts
into those surfaces.

## Risks And Blockers

- No previous overnight `runs/*/result.json`, `runs/*/handoff.md`, or repo-local `docs/overnight` reports were available in this worktree, so this pass cannot compare against prior generated findings.
- No `.github` workflow files were present, so CI enforcement is unknown from repo-local evidence.
- The documented safe loop is underpowered for the current implementation queue because only two test modules are marked `safe`.
- `README.md` and `pyproject.toml` disagree on supported Python versions.
- `DOCS_INDEX.md` contains stale-looking pass-count and production-readiness claims that should not be used as acceptance evidence without rerunning tests.
- MCP tools currently expose many raw or provider-shaped operations but not the compact index/needs-action read models, which conflicts with the Phase 1 plan to reduce raw-provider reads.
- `/inbox/needs-action` returns indexed threads only, which is good, but an empty stale index can look like "no work" unless callers also inspect `/index/health`.
- Live provider validation is intentionally blocked by the queue scope and by `docs/TESTING_FOR_AGENTS.md` unless a human explicitly opts in.

## Validation Commands

Queue validation command:

```bash
git status --short
```

Recommended repo-safe validation loop for implementation tasks:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe
uv run ruff check .
uv run pyright
```

Focused validation commands for the index workstream:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_message_sync.py tests/test_message_index_store.py -q
INBOX_TEST_MODE=1 uv run pytest tests/test_server.py::TestIndexEndpoints tests/test_client.py::TestClientIndexedInbox -q
INBOX_TEST_MODE=1 uv run pytest tests/test_tools_registry.py tests/test_mcp_gateway.py -q
```

## Implementation-Ready Follow-Up Tasks

### 1. Expand The Agent-Safe Test Lane For Index Work

Owned files:

- `tests/test_message_sync.py`
- `tests/test_message_index_store.py`
- `tests/test_server.py`
- `tests/test_client.py`
- `docs/TESTING_FOR_AGENTS.md`

Acceptance criteria:

- Deterministic index, sync fake-service, index endpoint, and client index-view tests are included in the `safe` marker lane.
- Tests that touch local personal stores, live OAuth providers, microphones, or external writes remain unmarked or explicitly marked `local_data`/`live_write`.
- `docs/TESTING_FOR_AGENTS.md` names the focused safe index command so future agents do not overrun live surfaces.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe tests/test_inbox_test_mode.py tests/test_mcp_gateway.py tests/test_message_sync.py tests/test_message_index_store.py tests/test_server.py tests/test_client.py -q
```

### 2. Expose Compact Indexed Inbox Reads Through MCP

Owned files:

- `tools_registry.py`
- `tests/test_tools_registry.py`
- `MCP_SETUP.md`

Acceptance criteria:

- Add readonly MCP tools for index health, one indexed view by name, and needs-action rollup.
- New tools route to `/index/health`, `/index/views/{view_name}`, and `/inbox/needs-action` without exposing body text.
- Readonly registration includes the new read tools; full registration still requires confirmation for mutating tools.
- MCP docs tell agents to prefer indexed/needs-action tools before raw Gmail search for triage.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_tools_registry.py tests/test_mcp_gateway.py -q
```

### 3. Surface Stale Or Empty Index State In Needs-Action And TUI

Owned files:

- `inbox_server.py`
- `inbox_client.py`
- `inbox.py`
- `tests/test_server.py`
- `tests/test_client.py`
- `tests/test_inbox_app.py`

Acceptance criteria:

- `/inbox/needs-action` includes index health/freshness metadata or an explicit stale/empty reason while still avoiding live Gmail fallback.
- `InboxClient` exposes that metadata without changing existing compact thread shapes.
- The TUI shows a clear index stale/error/no-sync state when indexed views are empty because the index is unhealthy.
- Existing index endpoint behavior remains backward compatible.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_server.py::TestIndexEndpoints tests/test_client.py::TestClientIndexedInbox tests/test_inbox_app.py -q
```

### 4. Harden Gmail History-Cursor Failure Fallback

Owned files:

- `message_sync.py`
- `tests/test_message_sync.py`

Acceptance criteria:

- A Gmail history API failure caused by an invalid or expired cursor falls back to timestamp incremental sync instead of leaving the account stuck on an unusable history cursor.
- Metadata records a distinct fallback reason such as `history_cursor_invalid` or `history_cursor_expired`.
- If both history and timestamp fallback fail, `sync_state.status` becomes `error` and preserves the last useful checkpoint/error.
- Existing bootstrap resume and history-cursor tests continue to pass.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_message_sync.py -q
```

### 5. Add Representative Thread-Classifier Fixtures

Owned files:

- `thread_classifier.py`
- `tests/test_thread_classifier.py`
- `tests/test_message_index_store.py`

Acceptance criteria:

- Add deterministic fixtures for recruiter/opportunity, appointment or health admin, security alert, newsletter/job alert, receipt/order, survey, and frequent human sender cases.
- Expected `noise_class`, `topic`, `urgency`, `actionability`, `needs_reply`, and `open_loop` outcomes are asserted.
- Any classifier changes remain local to the heuristic classifier and do not require live message bodies.

Smallest useful validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_thread_classifier.py tests/test_message_index_store.py -q
```

## Handoff Notes

- Product code was not edited.
- External services, pushes, PR creation, and tracker updates were not attempted.
- The only intended changed file is this report.
- Final worker response should include the local commit SHA, final `git status --short` result, PR URL if any, and blockers.
