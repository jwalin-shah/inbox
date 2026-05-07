# inbox-sym-118 Implementation Readiness Review

Date: 2026-05-07
Branch: `codex/goal-inbox-sym-118-implementation-readiness`
Repo: `inbox-sym-118`
HEAD at review start: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`

## Scope

This pass reviewed the repo for executable follow-up work. It did not modify product code, call external services, push branches, create PRs, or update trackers.

The queue item referenced `items/inbox-sym-118-implementation-readiness/ISSUE.md`, but that file is not present in this worktree. The full issue body was provided in the worker prompt, so the review continued from that contract.

No prior `docs/overnight/2026-05-07-whole-portfolio-review/` reports or `runs/*` outputs were present in this repo at the time of review. The repo does contain older `.factory/validation/*` outputs, which were used only as local evidence.

## Concrete Observations

1. `PLAN.md` defines the current product direction as an index-first inbox: stabilize sync/index, improve thread intelligence, make indexed reads the default, then build the `Now`, `Actionable`, and `Waiting On` TUI surfaces. This gives implementation agents a clear priority order.

2. `message_index_store.py` already has the core operational index tables: `sync_state`, `items`, `threads`, and `sender_stats`. It also supports status metadata, scoped thread rebuilds, recent/actionable/waiting filters, sender stats, and idempotent item upserts.

3. `message_sync.py` implements resumable Gmail bootstrap, Gmail history-cursor incremental sync, timestamp fallback, iMessage bootstrap/incremental sync, and scoped thread rebuilds. The highest-readiness slice is hardening these behaviors rather than inventing new architecture.

4. `tests/test_message_sync.py` covers concrete sync guarantees: saved Gmail page-token resume, history cursor recording, no double-count on resume, Gmail history incremental updates, timestamp fallback, skipped iMessage row checkpointing, and scoped rebuilds for changed Gmail/iMessage scopes.

5. `tests/test_message_index_store.py` covers index-store behavior: replacement upserts, OTP/noise classification, frequent-human sender stats, high-volume automated sender suppression, sync-state metadata, waiting/recent list filters, idempotency, and large rebuilds without SQLite expression-depth failure.

6. `inbox_server.py` exposes index endpoints that match the plan: `/index/status`, `/index/health`, `/index/views/{view_name}`, `/index/sync/bootstrap`, `/index/sync/incremental`, and `/inbox/needs-action`. The server also intentionally marks indexed outputs as `read_model=index` and `raw_provider_fetch=false`.

7. `tests/test_server.py` verifies the index endpoints route to `state.index_store.list_threads` with explicit filters for `actionable`, `waiting-on`, `waiting-on-me`, and `waiting-on-others`, and verifies `/inbox/needs-action` does not fall back to live Gmail when the index is empty.

8. `inbox_client.py` has helpers for `indexed_recent_threads`, `indexed_actionable_threads`, `indexed_waiting_on_me_threads`, and `indexed_waiting_on_others_threads`, but `inbox.py` currently fetches only `recent`, `actionable`, and `waiting-on` for the first-screen TUI. The API is ahead of the TUI controls for separating "waiting on me" from "waiting on others".

9. `CONNECTOR_ROADMAP.md` calls out source-of-truth account routing and write preflight as the next connector milestones. `google_account_resolution.py` already centralizes default Google account selection via `INBOX_DEFAULT_GOOGLE_ACCOUNT` and includes a `preflight_google_write_payload` helper for Docs, Sheets, Drive folders, Tasks, and Calendar events.

10. `tests/test_server.py` has preflight coverage for no-service failures, default account resolution, folder verification, task-list verification, calendar defaulting, and unknown write kinds. The backend preflight is implementation-ready enough to expose through client/MCP surfaces.

11. `tools_registry.py` centralizes MCP tool exposure and `tests/test_tools_registry.py` verifies every mutating MCP tool is confirmation-gated, readonly registration excludes write tools, path parameters are URL encoded, and registered tool routes exist in FastAPI via `tests/test_api_contract.py`.

12. `tools_registry.py` does not currently expose a `preflight_google_write` MCP tool, even though `inbox_server.py` exposes `/preflight/google-write`. This is a small, low-risk connector-readiness task with clear tests.

13. `docs/TESTING_FOR_AGENTS.md` documents the safe default loop as `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, and `uv run pyright`. In practice, only `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py` are marked `pytest.mark.safe`, so many deterministic server/index tests are excluded from the documented agent-safe lane.

14. Running `INBOX_TEST_MODE=1 uv run pytest -m safe -q` failed before dependency resolution because uv tried to initialize cache under `/Users/jwalinshah/.cache/uv`, which is outside this sandbox. Retrying with `UV_CACHE_DIR=/tmp/uv-cache` got past cache creation but failed on DNS while trying to download `networkx==3.6.1`. Agent validation needs either pre-seeded dependencies or commands that set `UV_CACHE_DIR`.

15. `.factory/services.yaml` sets `test` to `uv run pytest --ignore=tests/test_audio.py --ignore=tests/test_llm.py -x -q`, while `test_all` runs the full suite. Older `.factory/validation/fix-broken-state/scrutiny/synthesis.json` also notes that audio/LLM exclusions are already documented. This is a real lane split, but it should be made explicit in agent-facing validation docs.

16. `.pre-commit-config.yaml` includes Ruff, Ruff format, pre-commit hygiene hooks, and Bandit with `pyproject.toml`. `pyproject.toml` also defines pytest markers and Pyright basic type checking, but no `.github/` CI workflow was present in this worktree.

17. `.mcp.json` points both `inbox` and `inbox-readonly` MCP servers at `http://127.0.0.1:9849`, while `CLAUDE.md` warns that dev worktrees should use alternate ports. There is clear local guidance, but a dev-specific MCP example would reduce primary-vs-dev routing mistakes.

18. `.gitignore` protects credential and runtime files (`credentials.json`, `tokens/`, `github_token.txt`, `gemini_api_key.txt`, `.inbox_index.sqlite3`, `.inbox_memory.sqlite3`, `.inbox_scheduler.sqlite3`, generated batch state), so the report can safely recommend validation without risking secret commits.

## Risks And Blockers

- Missing local queue issue file: `items/inbox-sym-118-implementation-readiness/ISSUE.md` is absent. The prompt contained the issue body, so this did not block the review, but future workers should have a local `ISSUE.md` or workpad artifact.
- Dependency bootstrap blocked in this sandbox: `uv run` created `.venv` only after `UV_CACHE_DIR=/tmp/uv-cache`, then failed because network access is restricted and dependencies were not already available.
- Local commit creation is blocked in this sandbox: `git add docs/overnight/2026-05-07-whole-portfolio-review/inbox-sym-118-implementation-readiness.md` failed because git tried to create `.git/worktrees/inbox-sym-118-implementation-readiness/index.lock` under `/Users/jwalinshah/projects/inbox`, which is outside the writable roots.
- The documented safe pytest lane is too narrow: only two test files are marked `safe`, excluding deterministic server/index/client tests that are highly relevant for agent implementation.
- No `.github/` CI config was present. The repo relies on local commands and `.factory` validation metadata, which is workable locally but weak for PR-level enforcement.
- MCP/dev routing remains easy to misconfigure: default repo MCP config points at port `9849`, the primary daily-driver server, while worktree dev should use `9850+`.

## Validation Commands

Commands run during this review:

```bash
git status --short
```

Result before report creation: passed with clean output.

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe -q
```

Result: blocked by uv cache permission at `/Users/jwalinshah/.cache/uv`.

```bash
UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe -q
```

Result: blocked by restricted network while downloading `networkx==3.6.1`, pulled through `mlx-whisper -> torch -> networkx`.

Queue validation after writing this report:

```bash
git status --short
```

Result: passed with output `?? docs/overnight/`, expected because the required report could not be staged or committed under the current sandbox permissions.

Commit attempt:

```bash
git add docs/overnight/2026-05-07-whole-portfolio-review/inbox-sym-118-implementation-readiness.md
```

Result: blocked by sandbox write permissions on the external git worktree metadata path.

## Implementation-Ready Follow-Up Tasks

### 1. Broaden The Agent-Safe Test Lane

Owned files:
- `tests/test_message_sync.py`
- `tests/test_message_index_store.py`
- `tests/test_server.py`
- `tests/test_client.py`
- `tests/test_api_contract.py`
- `docs/TESTING_FOR_AGENTS.md`

Acceptance criteria:
- Deterministic index/sync/server/client/API-contract tests that avoid live data and external writes are marked with `pytestmark = pytest.mark.safe` or targeted `@pytest.mark.safe`.
- Tests that require local user data, live writes, heavy ML/audio, or external credentials remain outside `safe` and use the existing marker vocabulary.
- `docs/TESTING_FOR_AGENTS.md` lists the updated safe command with `UV_CACHE_DIR=/tmp/uv-cache` for sandboxed agents.

Smallest useful validation:

```bash
UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe -q
```

### 2. Expose Google Write Preflight Through Client And MCP

Owned files:
- `inbox_client.py`
- `tools_registry.py`
- `tests/test_client.py`
- `tests/test_tools_registry.py`
- `tests/test_api_contract.py`

Acceptance criteria:
- `InboxClient` exposes a `preflight_google_write(...)` helper for `/preflight/google-write`.
- `tools_registry.py` exposes a readonly MCP tool for Google write preflight.
- API-contract tests confirm the MCP tool path routes to FastAPI.
- Registry tests confirm the tool is readonly and does not require `confirm`.

Smallest useful validation:

```bash
UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_client.py tests/test_tools_registry.py tests/test_api_contract.py -q
```

### 3. Split Waiting-On TUI Into "Me" And "Others" Views

Owned files:
- `inbox.py`
- `inbox_client.py`
- `tests/test_inbox_app.py`
- `tests/test_client.py`

Acceptance criteria:
- The TUI can show `waiting-on-me` and `waiting-on-others` indexed views separately, using the existing client helpers.
- Existing `waiting-on` behavior remains available or is replaced with an explicit combined view.
- Status text and sidebar data make the selected waiting view unambiguous.
- Tests cover data collection and sidebar rendering for both views without live server access.

Smallest useful validation:

```bash
UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_client.py tests/test_inbox_app.py -q
```

### 4. Add A Sandbox-Friendly Validation Script

Owned files:
- `scripts/validate_agent_safe.sh`
- `docs/TESTING_FOR_AGENTS.md`
- `.factory/services.yaml`

Acceptance criteria:
- A single script sets `UV_CACHE_DIR=/tmp/uv-cache` by default and runs the safe pytest lane, Ruff, and Pyright.
- The script does not run live-write, local-data, slow, audio, or LLM-heavy tests unless explicitly asked.
- Agent docs and `.factory/services.yaml` point to the same safe command to avoid command drift.

Smallest useful validation:

```bash
bash scripts/validate_agent_safe.sh
```

### 5. Add Dev MCP Routing Example For Worktrees

Owned files:
- `.mcp.dev.example.json`
- `CLAUDE.md`
- `MCP_SETUP.md`
- `tests/test_mcp_gateway.py`

Acceptance criteria:
- The repo includes a dev MCP example that points at `http://127.0.0.1:9850` and still passes `INBOX_SERVER_TOKEN`.
- Docs clearly distinguish primary daily-driver MCP routing from dev worktree routing.
- A lightweight test or static assertion verifies the example keeps the token env placeholder and does not point dev at `9849`.

Smallest useful validation:

```bash
UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_mcp_gateway.py -q
```

## Readiness Summary

The safest next implementation work is not broad feature expansion. It is tightening the agent-safe validation lane, exposing already-built preflight/account-routing primitives through client/MCP surfaces, and finishing the index-first TUI split that the API already supports.

The index/sync work is the most implementation-ready area because the desired behavior is documented in `PLAN.md`, represented in `message_sync.py` and `message_index_store.py`, and already covered by focused deterministic tests. The connector-policy work is also ready, but should be kept to small endpoint/client/MCP slices so it does not accidentally widen write behavior.
