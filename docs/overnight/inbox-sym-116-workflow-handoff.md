# inbox-sym-116 workflow-handoff audit

Queue item: `inbox-sym-116-workflow-handoff`
Branch: `codex/goal-inbox-sym-116-workflow-handoff`
Audit date: 2026-05-07
Scope: read-only audit plus this report. No product code, generated data, secrets, external services, deploys, pushes, or PR creation.

## Executive summary

`inbox-sym-116` is a local-first Python inbox assistant. The repo combines a Textual TUI, FastAPI backend, MCP gateway surfaces, local SQLite indexing, Google Workspace integrations, macOS data-source readers, AppleScript mutators, background audio/LLM features, and utility workflows.

This is not a small repo: `git ls-files | wc -l` reports 196 tracked files, `rg --files | wc -l` reports 104 visible files, and `wc -l inbox.py inbox_server.py services.py message_sync.py message_index_store.py mcp_gateway.py mcp_backend.py mcp_server.py inbox_mcp_readonly.py tools_registry.py tests/test_server.py tests/test_message_sync.py tests/test_mcp_gateway.py` reports 20,736 lines across the main audited surfaces.

The strongest handoff path is to turn the next work into narrow, independently grabbable tasks around validation reliability, read-only MCP correctness, and stale workflow docs. The current architecture already has better implementation evidence than the docs imply: index-backed views and `/index/*` endpoints exist, but some docs still claim upcoming work or old test counts.

## Repo state

- Current branch: `codex/goal-inbox-sym-116-workflow-handoff` from `git branch --show-current`.
- Current HEAD: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`.
- Recent history: `git log --oneline -5` shows latest commit `2805b84 Merge pull request #34 from jwalin-shah/codex/SYM-9-indexed-defaults`, followed by `a821b5a Make indexed inbox views the default`.
- Remote: `origin https://github.com/jwalin-shah/inbox.git` from `git remote -v`.
- Initial tracked dirty state: `git status --short --branch` showed only `## codex/goal-inbox-sym-116-workflow-handoff`.
- After attempting the safe pytest command, `git status --short` remained empty, while `git status --short --ignored=matching` showed ignored `.venv/` created by `uv run`.
- This audit intentionally adds only `docs/overnight/inbox-sym-116-workflow-handoff.md`.

## Evidence map

- `CLAUDE.md` defines the product as a Python + Textual + Rich TUI backed by local FastAPI, with agents using the server API directly.
- `README.md:32` says Python 3.10+ is required, while `pyproject.toml:5` requires `>=3.12,<3.15`; this is a clear stale setup claim.
- `pyproject.toml:53-61` configures pytest to discover `tests/`, run coverage by default, and register `safe`, `integration`, `local_data`, `slow`, and `live_write` markers.
- `docs/TESTING_FOR_AGENTS.md:9-18` documents the agent-safe loop as `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, and `uv run pyright`.
- `rg --files tests | wc -l` reports 31 test files, but `rg "pytestmark = pytest.mark.safe" tests -n` finds safe marks only in `tests/test_inbox_test_mode.py:8` and `tests/test_mcp_gateway.py:18`.
- `tests/conftest.py` stubs heavy ML and hardware modules such as `mlx_lm`, `mlx_whisper`, `sounddevice`, `outlines`, and `Quartz`, so the test suite is designed to run without full local hardware dependencies once Python deps are installed.
- `inbox_test_mode.py` provides `INBOX_TEST_MODE`, `INBOX_TEST_DATA_DIR`, `INBOX_TEST_NOW`, and `assert_live_writes_allowed`, giving future workers a concrete safety shim for live-write blockers.
- `message_index_store.py` defines `.inbox_index.sqlite3`, `sync_state`, `items`, `threads`, and `sender_stats`; `list_threads()` supports actionable, recent, waiting-on, and priority sorting behavior.
- `message_sync.py` implements Gmail bootstrap and incremental sync, Gmail history/timestamp cursors, iMessage rowid sync, changed-scope thread rebuilds, and a CLI with `bootstrap`, `incremental`, `rebuild`, and `summary`.
- `inbox_server.py:565-632` defines index-oriented response models with `read_model="index"` and `raw_provider_fetch=False`; `inbox_server.py:3805-3853` exposes `/index/threads`, `/index/status`, `/index/health`, `/index/views/{view_name}`, and sync endpoints.
- `inbox_client.py:86-131` has first-class client helpers for `index_threads`, `index_status`, `index_health`, `index_view`, `indexed_recent_threads`, `indexed_actionable_threads`, `indexed_waiting_on_me_threads`, and `indexed_waiting_on_others_threads`.
- `inbox.py:1702-1723` renders the TUI `all`, `actionable`, and `waiting` filters from indexed thread lists, which conflicts with older docs saying indexed views are not yet the default TUI experience.
- `tools_registry.py` is the central MCP registry. `rg "Tool\\(" tools_registry.py -c` found 60 registry tools, `rg "readonly=True" tools_registry.py -c` found 29 read-only tools, and `rg "confirm=True" tools_registry.py -c` found 34 confirmation-gated tools.
- `tests/test_tools_registry.py` verifies all mutating registry tools require confirmation, read-only registration excludes write tools, path parameters are URL encoded, and body params are not URL encoded.
- `mcp_gateway.py` implements `INBOX_MCP_TOKEN` bearer auth for public MCP requests and leaves `/health` unauthenticated for health checks.
- `mcp_server.py` and `inbox_mcp_readonly.py` share `make_mcp_app()` and the central tool registry, but still define hand-written ambient/memory tools outside the registry.
- `inbox_mcp_readonly.py:47` references `ambient_notes.VAULT_DIR`; `ambient_notes.py` defines `VAULT_PATH`, `DAILY_DIR`, and `AMBIENT_DIR`, not `VAULT_DIR`. `rg "VAULT_DIR" -n .` finds only that broken reference.
- `.gitignore` excludes local credentials and generated state: `credentials.json`, `token.json`, `tokens/`, `github_token.txt`, `google_maps_key.txt`, `gemini_api_key.txt`, `config/inbox.env`, `.inbox_memory.sqlite3`, `.inbox_scheduler.sqlite3`, `.inbox_index.sqlite3`, batch state, and logs.
- `MCP_SETUP.md` documents a safer topology: private `inbox_server.py` on loopback, public MCP gateways protected by separate `INBOX_MCP_TOKEN`, and a read-only MCP surface for cloud or lower-trust clients.
- `deploy/Caddyfile.example` exposes only `/health` and `/mcp*` for both full and read-only MCP virtual hosts.
- `dev.sh` defaults dev worktrees to `INBOX_SERVER_PORT=9850` and derives `INBOX_SERVER_URL`; `.mcp.json` and `.cursor/mcp.json` still point both full and read-only local MCP servers at primary `127.0.0.1:9849`.
- `batch/batch-runner.sh` is a mutation workflow for Gmail archiving; it supports `--dry-run`, state files, logs, and optional parallelism, but writes state and logs under `batch/`.
- `DOCS_INDEX.md:140` claims "All 736 tests pass" and "production-ready"; local validation could not substantiate this because dependency installation is blocked by network restrictions.

## Architecture handoff

The codebase has three major workflow layers:

1. Human UI path: `inbox.py` uses `inbox_client.py`, renders source tabs plus indexed `Now`/actionable/waiting-like views, and can auto-start `inbox_server.py`.
2. Backend path: `inbox_server.py` owns app state, auth middleware, provider service routing, index endpoints, write endpoints, ambient/dictation state, scheduler hooks, and cross-source APIs. `services.py` remains the large source-adapter module.
3. Agent/MCP path: `mcp_server.py`, `inbox_mcp_readonly.py`, stdio wrappers, `mcp_gateway.py`, `mcp_backend.py`, and `tools_registry.py` expose a curated tool surface over the private HTTP backend.

The current repo direction is consistent: `PLAN.md` wants indexed operational inbox views, `CONNECTOR_ROADMAP.md` wants normalized intent-level tools and coded account policy, and current code has already moved meaningful pieces in that direction. The handoff risk is that docs, config snippets, and validation affordances lag the code.

## Risks and stale assumptions

1. Stale runtime requirement: `README.md` says Python 3.10+, but `pyproject.toml` requires Python 3.12+. New workers using the README can start from the wrong interpreter.
2. Unsupported validation claim: `DOCS_INDEX.md` and `SHEETS_CHANGELOG.md` claim 736 tests pass, but this worker could not install dependencies or run tests in the sandbox. The claim should be replaced with dated, reproducible validation evidence or removed.
3. Safe test loop is undercovered: only two of 31 test files are marked `safe`, so `pytest -m safe` is likely too narrow to prove most agent-safe backend, registry, client, and index behavior even after dependencies install.
4. Read-only MCP bug: `inbox_mcp_readonly.py` likely raises `AttributeError` for dated daily-note reads because it references nonexistent `ambient_notes.VAULT_DIR`.
5. Primary/dev routing confusion remains plausible: docs warn about it, `dev.sh` defaults to port 9850, but committed `.mcp.json` and `.cursor/mcp.json` point to primary port 9849. Worktree testing can silently hit the daily-driver backend unless clients are explicitly reconfigured.
6. MCP implementation drift risk: `tools_registry.py` now owns the HTTP-backed MCP surface, while `mcp_backend.py` still carries many older hand-written async wrapper methods. Future edits can update one path while tests only cover the other.
7. Batch archiving needs stronger input safety before broader use: `batch/batch-runner.sh` reads thread IDs from TSV, uses them in log filenames and JSON payloads, and mutates Gmail labels unless `--dry-run` is set. It is not a default safe agent workflow.
8. `main.py` still prints "Hello from inbox!", which is harmless but stale for a package named `inbox`; it can mislead tooling or new contributors looking for the app entrypoint.

## Next safe work

### Task 1: Make agent validation reproducible offline

Acceptance criteria:
- Update docs so the default agent validation command includes `UV_CACHE_DIR=/tmp/uv-cache` or another repo-approved writable cache path.
- Remove or qualify unverified "736 tests pass" claims with the date, command, environment, and source of truth.
- Add a short troubleshooting note for sandboxed workers where `uv` cannot write `~/.cache/uv` or cannot reach PyPI.
- Do not change product behavior.

Validation command candidates:
- `git status --short` should show only docs touched for this task.
- `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe -q` should pass when dependencies are already cached; in this sandbox it currently fails before tests because `sentencepiece==0.2.1` cannot be downloaded.
- `uv run ruff check docs/TESTING_FOR_AGENTS.md DOCS_INDEX.md SHEETS_CHANGELOG.md` is not a valid lint target for Markdown; use `git diff --check` instead for whitespace.

### Task 2: Fix and test read-only MCP daily note reads

Acceptance criteria:
- Replace the `ambient_notes.VAULT_DIR` reference in `inbox_mcp_readonly.py` with the existing daily-note API or `ambient_notes.DAILY_DIR`.
- Add a focused test that imports the read-only MCP module or the handler safely, monkeypatches ambient note paths to a temp dir, and proves both today's note and a dated note can be read without touching the real vault.
- Keep the change read-only; no writes to real Obsidian paths in tests.

Validation command candidates:
- `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_mcp_gateway.py -q` should pass when deps are installed.
- If a new focused test file is added, run that file directly with `INBOX_TEST_MODE=1`.
- `rg "VAULT_DIR" -n .` should return no matches after the fix.

### Task 3: Expand the safe test marker surface deliberately

Acceptance criteria:
- Audit existing tests for deterministic, local-only behavior and mark a first batch as `safe`, starting with `tests/test_tools_registry.py`, `tests/test_client.py`, `tests/test_message_index_store.py`, and pure index/sync tests that use fakes and temp SQLite only.
- Do not mark tests safe if they touch real macOS data stores, OAuth, external APIs, microphone/audio hardware, AppleScript writes, or live provider mutation.
- Update `docs/TESTING_FOR_AGENTS.md` to name what `pytest -m safe` is expected to cover and what remains opt-in.

Validation command candidates:
- `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe -q` should run a materially larger set than the current two marked files.
- `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py tests/test_tools_registry.py tests/test_client.py tests/test_message_index_store.py -q` should pass when dependencies are installed.
- `git diff --check` should pass.

### Task 4: Add a dev-routing self-check for MCP clients

Acceptance criteria:
- Add a small local-only command or docs-backed health procedure that reports `cwd`, `INBOX_SERVER_URL`, backend `/health`, MCP mode, and whether the client is pointed at primary 9849 or a dev port.
- Update `MCP_SETUP.md` and `CLAUDE.md` with the command and expected output shape.
- Do not expose secrets; redact `INBOX_SERVER_TOKEN` and `INBOX_MCP_TOKEN`.

Validation command candidates:
- `INBOX_SERVER_URL=http://127.0.0.1:9850 <new-command>` should show dev routing without printing tokens.
- `git diff --check` should pass.
- A focused unit test should prove token redaction and primary/dev classification without starting a live server.

## Validation notes from this audit

Commands run:
- `llm-tldr tree .` succeeded and mapped the repo structure.
- `git status --short --branch` succeeded and showed the branch with no tracked changes at audit start.
- `git log --oneline -5`, `git remote -v`, `git rev-parse HEAD`, and `git branch --show-current` succeeded.
- `rtk read` and `rg`/`nl`/`wc` commands succeeded for docs, scripts, entrypoints, tests, and key modules.
- `INBOX_TEST_MODE=1 uv run pytest -m safe -q` failed before test collection because `uv` could not initialize `/Users/jwalinshah/.cache/uv` in this sandbox.
- `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe -q` advanced past the cache issue, created ignored `.venv/`, then failed before test collection because network access is restricted and `sentencepiece==0.2.1` could not be downloaded.

Required queue validation:
- Command: `git status --short`
- Result: exit 0.
- Output: `?? docs/overnight/`.
- Detail command: `git status --short --untracked-files=all` shows `?? docs/overnight/inbox-sym-116-workflow-handoff.md`.

## Non-goals

- No product-code changes.
- No fixes to tests, docs outside this report, scripts, or MCP code.
- No credentials, tokens, OAuth flows, local inbox server startup, live provider reads, or live provider writes.
- No deploy, public endpoint, push, PR, merge, or tracker state update.
- No sibling repo comparison; this repo is substantial enough to justify the full audit locally.

## Unknowns

- Whether the full test suite currently passes outside this sandbox with dependencies already cached.
- Whether the daily-driver inbox server on port 9849 is currently healthy; this audit did not curl it to avoid touching live personal data paths.
- Whether committed `.mcp.json` primary routing is intentional for all local clients or should become worktree-aware.
- Whether `batch/archive-input.tsv` is intentionally tracked as an empty template or should be documented as input-only with stronger sanitization.
- Whether the "736 tests pass" claim came from a real historical run, generated text, or an old branch state.

## Handoff

Changed files:
- `docs/overnight/inbox-sym-116-workflow-handoff.md`

Commit SHA:
- Current HEAD before this report: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`

PR URL:
- None. Pushes and PR creation are out of scope for this Goal Pack item.

Blockers:
- Dependency-backed pytest validation cannot run in this sandbox without either an existing dependency cache or network access to fetch `sentencepiece`.
- Live server and provider checks were intentionally not run.
