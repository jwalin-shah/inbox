# Overnight Docs Claims Audit: inbox-sym-120

Queue item: `inbox-sym-120-docs-claims`
Focus area: `docs-claims`
Repo path: `/Users/jwalinshah/projects/agent-stack/.agent-stack-worktrees/2026-05-07-overnight-marathon/inbox-sym-120-docs-claims`
Branch: `codex/goal-inbox-sym-120-docs-claims`
Base HEAD before report: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`

## Purpose And Current State

This repo is a local-first personal inbox system: a Textual TUI and FastAPI
backend that unify Gmail, iMessage, Calendar, local Apple data stores, GitHub,
Drive, Sheets, Docs, Tasks, audio/LLM helpers, MCP surfaces, and an indexed
operational inbox. The product direction in `PLAN.md` is narrower than several
top-level feature claims: Phase 1 is explicitly inbox-only and index-driven, not
a general personal memory or broad connector platform.

The worktree started on the expected goal branch. Initial `git status --short
--branch` showed only:

```text
## codex/goal-inbox-sym-120-docs-claims
```

During audit, local validation probes created ignored artifacts only:
`.venv/`, `.coverage`, and `.pytest_cache/`. A local commit was attempted, but
git metadata for this worktree points outside the writable root, so the report
must remain as an uncommitted docs-only file in this sandbox.

## Commands Run

- `llm-tldr tree .` - mapped repo structure and confirmed docs/code/test layout.
- `git status --short --branch` - confirmed branch and initial clean tracked state.
- `git rev-parse --show-toplevel && git rev-parse --abbrev-ref HEAD && git rev-parse HEAD` - captured repo root, branch, and base SHA.
- `rg --files -g '*.md'` - found 18 markdown files, not the six claimed by `DOCS_INDEX.md`.
- `rtk read README.md`, `rtk read DOCS_INDEX.md`, `rtk read CLAUDE.md`, `rtk read SHEETS*.md`, `rtk read MCP_SETUP.md`, `rtk read docs/TESTING_FOR_AGENTS.md` - reviewed user-facing docs.
- `rg -n "^@app\.(get|post|put|delete|patch)" inbox_server.py | wc -l` - found 159 FastAPI route decorators.
- `rg -n "^(GET|POST|PUT|DELETE|PATCH) +/" README.md CLAUDE.md SHEETS.md SHEETS_QUICKSTART.md modes/_shared.md MCP_V1_PLAN.md | wc -l` - counted 119 documented endpoint lines across docs.
- `UV_CACHE_DIR=/private/tmp/inbox-sym-120-uv-cache INBOX_TEST_MODE=1 uv run pytest --collect-only -q` - collected 866 tests after first run failed on the default uv cache permission.
- `UV_CACHE_DIR=/private/tmp/inbox-sym-120-uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe -q` - passed 11 safe tests, 855 deselected.
- `uv run python -V` - created the ignored `.venv/` and reported Python 3.12.12.
- `git status --short --ignored=matching` - showed only ignored `.coverage`, `.pytest_cache/`, and `.venv/` artifacts before report write.
- `git add docs/overnight/inbox-sym-120-docs-claims.md && git commit -m "Add inbox docs claims audit"` - failed because the sandbox cannot create `/Users/jwalinshah/projects/inbox/.git/worktrees/inbox-sym-120-docs-claims/index.lock`.

## Supported Claims

The client-server architecture claim is supported. `README.md` describes a
FastAPI backend plus thin clients, and `inbox_server.py` defines the FastAPI app
and routes while `inbox_client.py` reads `INBOX_SERVER_URL` and
`INBOX_SERVER_TOKEN`.

The macOS local data-source claims are substantially supported. `services.py`
points iMessage, Notes, Reminders, AddressBook, credential, token, GitHub token,
Gemini key, and Google Maps key paths at local files or user-library locations.
Apple Reminders scan multiple `Data-*.sqlite` databases and list data via SQLite.

The broad Google integration claim is supported at the code level. `services.py`
defines OAuth scopes for Gmail readonly/modify/send/settings, Calendar, Drive,
Sheets, Docs, and Tasks, and `google_auth_all()` builds six service maps:
Gmail, Calendar, Drive, Sheets, Docs, and Tasks.

The Sheets API exists locally. `services.py` implements list/get/create/delete,
value get/update/append/clear, batch get/update, tab add/delete/rename/copy, and
formatting helpers, while `inbox_server.py` exposes corresponding `/sheets`
routes.

The MCP setup guide is mostly aligned with current code. `MCP_SETUP.md`
correctly separates private REST backend, full HTTP MCP, read-only HTTP MCP,
full stdio entrypoint, and read-only stdio entrypoint. `mcp_server.py` is an
HTTP gateway and `inbox_mcp_stdio.py` is the stdio wrapper.

Secret-file claims are supported. `.gitignore` excludes `credentials.json`,
`token.json`, `tokens/`, `github_token.txt`, `google_maps_key.txt`,
`gemini_api_key.txt`, `config/inbox.env`, `.env*`, `.inbox_memory.sqlite3`,
`.inbox_scheduler.sqlite3`, and `.inbox_index.sqlite3`.

The test-mode documentation has a real implementation. `inbox_test_mode.py`
raises `LiveWriteBlocked` when `INBOX_TEST_MODE` is enabled, and
`docs/TESTING_FOR_AGENTS.md` documents the safe loop and live-write opt-in rule.
The safe test slice passed locally.

The newer index-driven product direction is supported by local code. `PLAN.md`
describes a local SQLite operational index, and `inbox_server.py` exposes
`/index/status`, `/index/health`, `/index/views/{view_name}`, and sync endpoints.

## Unsupported Or Stale Claims

1. `README.md` says Python 3.10+ is sufficient, but `pyproject.toml` requires
   `>=3.12,<3.15` and configures Ruff/Pyright for Python 3.12. The local
   interpreter used by uv is Python 3.12.12. Update docs to Python 3.12+.

2. `DOCS_INDEX.md` says "Total documentation: 6 files" and repeatedly frames
   Sheets docs as the only new docs. `rg --files -g '*.md'` found 18 markdown
   files, including MCP setup, connector roadmap, testing, modes, and plan docs.

3. `DOCS_INDEX.md` and `SHEETS_CHANGELOG.md` claim "All 736 tests pass." Local
   collection found 866 tests, and this audit did not run the full suite. The
   only executed test command was the safe slice: 11 passed, 855 deselected.

4. `README.md` keybindings are stale. It says `Ctrl+6` toggles ambient
   listening, but `inbox.py` binds `Ctrl+6` to Reminders and `Ctrl+Shift+6` to
   ambient. It omits `Ctrl+8` Drive, `Ctrl+9` Actionable, `Ctrl+0` Waiting On,
   `Ctrl+P` command palette, `Ctrl+\` search, `Ctrl+Shift+A` re-auth,
   `Ctrl+D` delete event, `Ctrl+G` date jump, and `Ctrl+B` briefing.

5. The README API reference is a quick reference, but it says "All endpoints
   available" above a partial list. Code currently has 159 route decorators.
   Missing or under-documented surfaces include Tasks, Docs, WhatsApp, scheduled
   messages, followups, task links, contacts, memory extraction, indexed views,
   workflow object creation, free/busy, conflicts, and several Gmail actions.

6. `CLAUDE.md` claims a complete endpoint list, but its endpoint block is also
   stale. It documents `POST /preflight/write`, while code exposes
   `GET /preflight/google-write`. It does not include many current `/tasks`,
   `/whatsapp`, `/index`, `/memory`, and workflow endpoints.

7. `CLAUDE.md` says `mcp_server.py` is stdio-based. Current code has
   `mcp_server.py` as the HTTP gateway (`stateless_http=True`) and
   `inbox_mcp_stdio.py` as the stdio transport wrapper.

8. `CLAUDE.md` says MCP exposes all inbox functionality. The registry exposes a
   curated subset, not all 159 REST routes. For example, Sheets MCP tools include
   list/read/create/append, but not every REST Sheets operation.

9. The privacy/ML wording is too broad. README says no cloud dependencies and
   no API calls for ASR or LLM, but `pyproject.toml` includes
   `google-generativeai`, `services.py` has a Gemini API key file/env path, and
   `inbox_server.py` exposes Gemini-backed AI endpoints. The local ML path is
   real, but the docs should call Gemini an optional cloud backend instead of
   claiming no cloud dependency unqualified.

10. Sheets docs overclaim "any operation available in Sheets API" and
    "production-ready." The local API covers many high-value operations and raw
    formatting passthrough, but it is not a complete Google Sheets API wrapper.
    `SHEETS_CHANGELOG.md` also says Sheets functionality is not directly tested
    in the suite.

11. The test-mode docs say live writes are blocked through
    `assert_live_writes_allowed`, but coverage is partial. Representative tests
    cover one Sheets value update, while `sheets_rename_sheet`,
    `sheets_format`, and `sheets_copy_to` do not call `_assert_live_write_allowed`
    before using the Google Sheets API.

12. "All mutations return operation stats" is not accurate for Sheets. Some
    mutation helpers return booleans or objects instead of stats: delete/clear
    return `ok`, tab add/copy return `SheetTab`, and create returns metadata.

## Risks And Stale Assumptions

1. Agent safety risk: docs imply `INBOX_TEST_MODE=1` blocks live writes, but
   several Sheets mutation helpers bypass that guard. A safe test run could miss
   live mutation paths if a future test or agent hits rename, formatting, or tab
   copy with a real service.

2. User setup risk: README's Python 3.10+ claim can send users into an
   unsupported interpreter. The package metadata and tooling require Python
   3.12+, so install failures or type/runtime differences are likely on 3.10.

3. Operational risk: endpoint docs do not match the actual server surface.
   Agents following README or CLAUDE may miss safer indexed endpoints, use the
   wrong preflight route, or attempt stale keybindings/workflows.

4. Security communication risk: the privacy section does not distinguish local
   ML from optional Gemini-backed cloud AI. That can mislead a reviewer about
   when text leaves the machine.

5. MCP handoff risk: CLAUDE's transport description contradicts MCP_SETUP and
   code. A worker may configure `mcp_server.py` as a local stdio process instead
   of using `inbox_mcp_stdio.py`.

6. Test-claims risk: docs advertise a specific passing test count. The repo has
   since changed to 866 collected tests, and only the safe slice was executed in
   this audit.

## Validation Map And Expected Status

- `git status --short` - required queue validation. Expected exit code 0 with
  `?? docs/overnight/` in this sandbox because committing is blocked by git
  metadata permissions. Ignored `.venv/`, `.coverage`, and `.pytest_cache/` are
  not shown by this command.
- `UV_CACHE_DIR=/private/tmp/inbox-sym-120-uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe -q` - passed locally: 11 passed, 855 deselected. Use this as the safe agent proof command.
- `UV_CACHE_DIR=/private/tmp/inbox-sym-120-uv-cache INBOX_TEST_MODE=1 uv run pytest --collect-only -q` - passed locally after overriding uv cache: 866 tests collected. Expected to pass, but note pytest coverage output is noisy because `pyproject.toml` adds coverage globally.
- `INBOX_TEST_MODE=1 uv run pytest -m safe` - documented command. Expected to pass, but may fail in this sandbox unless `UV_CACHE_DIR` is redirected away from `/Users/jwalinshah/.cache/uv`.
- `uv run pytest` - documented full-suite command. Not run in this audit. Expected status unknown; docs should not claim a pass count without a fresh run.
- `uv run ruff check .` - documented lint command. Not run; expected status unknown.
- `uv run pyright` - documented type command. Not run; expected status unknown and likely more expensive/noisy.

## Next Safe Work

1. Fix setup and validation claims.
   Acceptance criteria: README says Python 3.12+, DOCS_INDEX removes the stale
   six-file and 736-test claims, and validation docs separate "safe slice
   passed" from "full suite not run." Validation: `git diff --check` and
   `UV_CACHE_DIR=/private/tmp/inbox-sym-120-uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe -q`.

2. Generate a server-route documentation snapshot.
   Acceptance criteria: README labels its API section as a quick reference,
   CLAUDE either links to generated route output or includes all current major
   surfaces, and `/preflight/google-write` replaces stale `/preflight/write`.
   Validation: `rg -n "^@app\\.(get|post|put|delete|patch)" inbox_server.py`
   and a focused docs review comparing listed route families.

3. Align TUI and MCP docs with code.
   Acceptance criteria: README and CLAUDE keybindings match `InboxApp.BINDINGS`;
   CLAUDE says `mcp_server.py` is HTTP and `inbox_mcp_stdio.py` is stdio; MCP
   docs clearly call the tool surface curated rather than complete. Validation:
   `rg -n "Binding\\(" inbox.py` and `rg -n "Tool\\(" tools_registry.py`.

4. Harden live-write guard coverage for Sheets.
   Acceptance criteria: `sheets_rename_sheet`, `sheets_format`, and
   `sheets_copy_to` call `_assert_live_write_allowed`; tests prove each raises
   `LiveWriteBlocked` under `INBOX_TEST_MODE=1` before touching a fake live
   service. Validation:
   `UV_CACHE_DIR=/private/tmp/inbox-sym-120-uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_services.py -q`.

5. Add a docs-claims CI/check script.
   Acceptance criteria: a local script or test checks Python version docs,
   markdown file count claims, keybinding docs, and route family drift without
   calling external services. Validation:
   `UV_CACHE_DIR=/private/tmp/inbox-sym-120-uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_docs_claims.py -q`.

## Non-Goals

- No product code was changed for this audit.
- No credentials, tokens, personal data stores, external APIs, cloud services,
  deploys, pushes, PRs, or external trackers were used.
- No live Inbox server was started.
- No full pytest, lint, typecheck, or live integration suite was run.
- No attempt was made to verify real Gmail, Calendar, Drive, Docs, Sheets,
  Tasks, GitHub, iMessage, Notes, Reminders, WhatsApp, microphone, or desktop
  notification behavior.

## Unknowns

- Whether the full test suite currently passes.
- Whether `uv run ruff check .` and `uv run pyright` are currently clean.
- Whether the daily-driver primary checkout has tokens or server state that
  differ from this isolated worktree.
- Whether docs should optimize for morning human review, external users, or
  agent handoff first; the current docs try to serve all three.
- Whether optional Gemini endpoints should remain user-facing or move behind a
  clearer "cloud optional" section.

## Handoff

Changed file: `docs/overnight/inbox-sym-120-docs-claims.md`
PR URL: none; PR creation is out of scope for this queue item.
External tracker status: not changed.
Commit status: not committed. `git commit` failed with `fatal: Unable to create
'/Users/jwalinshah/projects/inbox/.git/worktrees/inbox-sym-120-docs-claims/index.lock':
Operation not permitted`.
Blockers: commit creation is blocked by sandbox permissions on the shared git
metadata outside this worktree. Product fixes above require a separate
implementation queue item.
