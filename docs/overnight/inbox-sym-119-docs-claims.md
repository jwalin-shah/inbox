# Deep Docs-Claims Audit: inbox-sym-119

Date: 2026-05-07
Queue item: `inbox-sym-119-docs-claims`
Focus area: `docs-claims`
Repo path: `/Users/jwalinshah/projects/agent-stack/.agent-stack-worktrees/2026-05-07-overnight-marathon/inbox-sym-119-docs-claims`

## Scope And Decisions

This audit only inspected local files and wrote this report. It did not run the app, start local services, touch product code, use credentials, call external APIs, create a PR, or update any tracker state.

I treated docs claims as supported only when there was local code, tests, configuration, or command output behind them. Claims that require live Gmail, Google, Apple, GitHub, microphone, OAuth, or deployed MCP behavior are marked as not locally proven unless tests or static evidence cover the contract.

## Repo Purpose And State

The repo is a local-first personal inbox and productivity control plane. `README.md` describes a privacy-first Textual TUI that consolidates iMessage, Gmail, Google Calendar, Google Sheets, Apple Notes, Apple Reminders, GitHub notifications, and Google Drive behind a local FastAPI server. `PLAN.md` narrows the current product phase to Gmail, iMessage/SMS, calendar context, a local FastAPI server, a local SQLite operational index, and the TUI.

Branch and dirty state:
- `git branch --show-current` returned `codex/goal-inbox-sym-119-docs-claims`.
- `git rev-parse HEAD` returned `2805b8400519da188ca7d3f6e39b19a8ca42b05a`.
- Initial `git status --short` returned no output, so the worktree was clean before this report.
- After this report is written, the expected dirty state is one untracked report file under `docs/overnight/`.

## Commands Run

- `llm-tldr tree .` - mapped the repo structure.
- `git status --short` - confirmed initial clean state.
- `git branch --show-current` - confirmed the queue branch.
- `git rev-parse HEAD` - captured the handoff commit SHA.
- `rtk read README.md DOCS_INDEX.md CLAUDE.md docs/TESTING_FOR_AGENTS.md` - reviewed top-level docs and test guidance.
- `rtk read SHEETS.md SHEETS_QUICKSTART.md SHEETS_CHANGELOG.md MCP_SETUP.md MCP_V1_PLAN.md CONNECTOR_ROADMAP.md` - reviewed feature, setup, and roadmap claims.
- `rg --count-matches "^[[:space:]]*def test_" tests test_autocomplete_dev.py` - counted checked-in test functions by file; summed total is 864, not the documented 736.
- `rg -n "@app\.(get|post|put|delete|patch).*" inbox_server.py` - checked documented endpoint surface against FastAPI route declarations.
- `rg -n "_assert_live_write_allowed|sheets_rename_sheet|sheets_format|docs_insert_text" services.py tests docs/TESTING_FOR_AGENTS.md` - checked the live-write blocking claim.
- `rg --files -g '*.md'` - checked documentation inventory against `DOCS_INDEX.md`.
- `rg --files -g '.claude/**' -g '.mcp.json' -g '.cursor/**'` - checked local MCP/skill files; only `.mcp.json` was present.

## Supported Claims

The client-server architecture claim is well supported. `inbox_server.py` declares the FastAPI app and a broad route surface, `inbox_client.py` is the sync HTTP client, `mcp_backend.py` calls the HTTP API, and `inbox.py` is the Textual TUI.

The Google Sheets API claim is substantially supported at the server and service layer. `inbox_server.py` exposes `/sheets` CRUD, value, tab, copy, and format endpoints. `services.py` implements `sheets_list`, `sheets_get`, `sheets_create`, values read/write/batch/append/clear, tab add/delete/rename/copy, and formatting.

The Google Docs API claim is supported by code, though it is less visible in user-facing docs than Sheets. `inbox_server.py` exposes `/docs`, `/docs/{id}`, `/docs/{id}/text`, `/docs/{id}/export`, and `/docs/workflow-doc`. `services.py` implements `docs_list`, `docs_get`, `docs_create`, `docs_delete`, `docs_export`, `docs_insert_text`, and `docs_get_text`.

The MCP split is supported. `MCP_SETUP.md` describes private backend, full MCP gateway, readonly HTTP gateway, stdio entrypoints, and readonly stdio. The local files exist: `mcp_server.py`, `inbox_mcp_readonly.py`, `inbox_mcp_stdio.py`, `inbox_mcp_readonly_stdio.py`, `mcp_gateway.py`, `.mcp.json`, and scripts under `scripts/`.

The token-auth claim is supported. `inbox_server.py` reads `INBOX_SERVER_TOKEN` and accepts Bearer or `X-API-Key`; `mcp_gateway.py` reads `INBOX_MCP_TOKEN`; `config/inbox.env.example` distinguishes server and MCP tokens; `MCP_SETUP.md` tells users not to reuse them.

The secrets-are-gitignored claim is supported. `.gitignore` excludes `credentials.json`, `token.json`, `tokens/`, `github_token.txt`, `google_maps_key.txt`, `gemini_api_key.txt`, `config/inbox.env`, local SQLite state, coverage, server logs, and batch output state.

The worktree dev routing guidance is supported. `CLAUDE.md` documents primary port 9849 and dev port 9850, and `dev.sh` actually defaults `INBOX_SERVER_PORT=9850` and derives `INBOX_SERVER_URL` from it.

The safer agent-test-mode direction is partially supported. `docs/TESTING_FOR_AGENTS.md` defines `INBOX_TEST_MODE=1` and safe markers. `inbox_test_mode.py` implements `assert_live_writes_allowed`. Many mutating functions in `services.py` call `_assert_live_write_allowed`, and `tests/test_services.py` covers representative write guards.

The TUI key map is test-backed for newer tabs. `inbox.py` binds `ctrl+6` to Reminders, `ctrl+7` to GitHub, `ctrl+8` to Drive, and `ctrl+shift+6` to Ambient. `tests/test_inbox_app.py` has explicit tests for `ctrl+6`, `ctrl+7`, and `ctrl+8`.

## Unsupported Or Stale Claims

`README.md` says Python 3.10+ is required, but `pyproject.toml` requires `>=3.12,<3.15`. The docs should advertise Python 3.12+ unless the package metadata changes.

`DOCS_INDEX.md` and `SHEETS_CHANGELOG.md` claim "All 736 tests pass" and "production-ready." The checked-in test function count from `rg --count-matches "^[[:space:]]*def test_" tests test_autocomplete_dev.py` sums to 864. That is not the same as pytest collection count, but it is enough to show the hard-coded 736 claim is stale. I did not run the full suite.

`DOCS_INDEX.md` says total documentation is 6 files. `rg --files -g '*.md'` returned 18 markdown files, including `PLAN.md`, `MCP_SETUP.md`, `MCP_V1_PLAN.md`, `CONNECTOR_ROADMAP.md`, `docs/TESTING_FOR_AGENTS.md`, mode prompts, and config profile docs. The index is no longer complete.

`README.md` claims `Ctrl+6` toggles ambient listening. `inbox.py` binds `ctrl+6` to Reminders and `ctrl+shift+6` to Ambient. `tests/test_inbox_app.py` verifies `ctrl+6` switches to Reminders. `README.md` is stale here.

`CLAUDE.md` says slash commands are routed by `.claude/skills/inbox/SKILL.md`, but `rg --files -g '.claude/**'` found no `.claude` skill tree because `.claude/` is gitignored. The mode prompt files exist under `modes/`, and `batch/batch-runner.sh` exists, but the slash-command router claim is not supported by tracked files in this worktree.

The privacy claim in `README.md` is too broad. The local ML claim is supported by MLX dependencies and local model code, but "All data processing happens on-device" and "no cloud syncing" are misleading for a repo whose source adapters call Google Gmail, Calendar, Drive, Sheets, Docs, Tasks, GitHub, optional Google Maps, and optional Gemini. `services.py` imports Google API clients, `httpx`, and has Gemini functions using `gemini_api_key.txt`.

The test-mode docs overclaim write blocking. `services.py` guards many writes, but `sheets_rename_sheet`, `sheets_format`, `sheets_copy_to`, and `docs_insert_text` do not call `_assert_live_write_allowed`. Their HTTP endpoints in `inbox_server.py` are direct mutations. `tests/test_services.py` covers some representative writes, not all mutating surfaces.

The "full API coverage" Sheets language is stronger than the implementation evidence. The code covers many practical spreadsheet operations, including raw `batchUpdate` formatting, but it does not expose every Google Sheets API concept as first-class endpoints. The docs should say "broad Sheets CRUD, values, tab, copy, and raw formatting support."

`PLAN.md` says the phase is intentionally narrow and excludes a general-purpose personal agent platform, while `README.md`, `CLAUDE.md`, `MCP_SETUP.md`, and `CONNECTOR_ROADMAP.md` describe a much broader connector platform with Drive, Sheets, Docs, Tasks, GitHub, MCP, memory, and workflow tools. That may reflect real evolution, but the docs do not clearly mark which document is current.

## Risks And Stale Assumptions

1. Safety documentation does not match the mutation surface. Agent-safe test mode can still miss direct HTTP mutations for sheet rename/copy/format and doc text insertion. This is a concrete risk for local agents because the repo handles personal data and external write APIs.

2. Onboarding instructions can fail on Python version. A user following `README.md` with Python 3.10 will not satisfy `pyproject.toml`. This is a low-effort docs fix but high-friction if left stale.

3. Production-readiness claims are unverifiable from current docs. The hard-coded 736 count is stale, the full suite was not run in this audit, and only two files are globally marked `safe`.

4. Privacy wording may cause wrong operator expectations. The repo is local-first, but it intentionally reads and mutates cloud providers. The README should distinguish local UI/ML processing from provider API calls and remote writes.

5. Slash-command documentation references a gitignored, absent tracked router path. A future agent may waste time looking for `.claude/skills/inbox/SKILL.md` instead of using tracked `modes/` files and MCP/tool registry surfaces.

6. Multiple "source of truth" docs disagree. `PLAN.md` describes a narrow phase, `CONNECTOR_ROADMAP.md` describes the next connector platform, and `README.md` presents the broadest feature set as current. Morning review should choose a docs hierarchy.

## Non-Claims And Unknowns

This audit does not prove that live Gmail, Calendar, Drive, Sheets, Docs, Tasks, GitHub, Apple Notes, iMessage, Reminders, microphone, or MCP gateway flows work on this machine. I did not start `inbox_server.py`, authenticate accounts, use OAuth tokens, or call providers.

This audit does not prove current pytest pass/fail status. I counted test functions and inspected targeted tests, but did not run the full suite or safe suite.

This audit does not verify UI rendering in Textual, browser behavior, voice/dictation hardware behavior, or local ML model load behavior.

This audit does not compare sibling repos because this repo is not small and the docs-claims surface was already broad enough for the slice.

## Next Safe Work

1. Reconcile docs version and test-count claims.
   Acceptance criteria: `README.md` matches `pyproject.toml` on Python support; `DOCS_INDEX.md` removes hard-coded "736 pass" and "6 files" claims or replaces them with generated/current statements; no docs claim "production-ready" unless backed by a fresh validation artifact.
   Validation: `uv run pytest --collect-only -q` expected to pass and provide the current collection count; `git diff -- README.md DOCS_INDEX.md SHEETS_CHANGELOG.md` expected to show docs-only changes.

2. Close agent-safe write-guard gaps.
   Acceptance criteria: `sheets_rename_sheet`, `sheets_format`, `sheets_copy_to`, and `docs_insert_text` call `_assert_live_write_allowed`; tests prove `INBOX_TEST_MODE=1` blocks each direct service mutation before mocked API calls execute.
   Validation: `INBOX_TEST_MODE=1 uv run pytest tests/test_services.py -q -k "test_mode_blocks"` expected to pass after the fix; new focused tests should fail before the guard additions.

3. Update TUI key-binding docs from code.
   Acceptance criteria: `README.md` and `CLAUDE.md` list `Ctrl+6` as Reminders, `Ctrl+7` as GitHub, `Ctrl+8` as Drive, and `Ctrl+Shift+6` as Ambient; no stale Ambient-on-`Ctrl+6` claim remains.
   Validation: `INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_app.py -q -k "ctrl6 or ctrl7 or ctrl8"` expected to pass.

4. Clarify privacy and cloud-provider boundaries.
   Acceptance criteria: README privacy section distinguishes local storage/ML from OAuth-backed Google/GitHub/Maps/Gemini provider calls; docs explicitly identify which operations are local-only, provider reads, provider writes, and optional cloud AI.
   Validation: `rg -n "All data processing happens on-device|no cloud syncing|Gemini|Google Maps|Google API" README.md CLAUDE.md services.py` expected to show narrower language.

5. Replace absent slash-router claim with tracked entrypoints.
   Acceptance criteria: `CLAUDE.md` either tracks an actual `.claude/skills/inbox/SKILL.md` in repo or describes the tracked `modes/`, `batch/batch-runner.sh`, `tools_registry.py`, and MCP entrypoints as the source of slash-command behavior.
   Validation: `rg --files -g '.claude/**' -g 'modes/**' -g 'tools_registry.py' -g 'batch/batch-runner.sh'` expected to match the documented paths.

## Validation Candidates

Required queue validation:
- `git status --short`
- Expected status: command exits 0. After this report, expected output should show only `?? docs/overnight/inbox-sym-119-docs-claims.md` unless the runner has staged or otherwise moved the report.

Useful follow-up validation:
- `INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py tests/test_mcp_gateway.py -q`
- Expected status: pass, proving the currently marked global safe test files still work.

- `INBOX_TEST_MODE=1 uv run pytest tests/test_services.py -q -k "test_mode_blocks"`
- Expected status today: pass, but incomplete because it does not cover every mutating function listed above.

- `uv run pytest --collect-only -q`
- Expected status: pass if dependencies are available; expected collection count should be regenerated from pytest rather than hard-coded in docs.

- `uv run ruff check .`
- Expected status after docs-only changes: pass or unchanged from baseline.

## Handoff Notes

Changed files: this report only.

No product code was edited. No validation beyond the required queue command was run in this slice. No PR was created because PR creation is out of scope for the overnight audit queue.
