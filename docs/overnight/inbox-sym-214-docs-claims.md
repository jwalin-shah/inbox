# Overnight docs-claims audit: inbox-sym-214

Queue item: `inbox-sym-214-docs-claims`
Focus area: docs claims, supported evidence, unsupported claims, non-claims, and next safe work
Worktree: `/Users/jwalinshah/projects/agent-stack/.agent-stack-worktrees/2026-05-07-overnight-marathon/inbox-sym-214-docs-claims`

## Repo purpose and state

This repo is a local-first personal inbox/control-plane application. The tracked surface is a Python FastAPI backend, a Textual TUI, MCP gateways, Google and Apple data-source adapters, indexing/scheduler stores, and agent-facing workflow docs.

Current local state observed before writing this report:

- Branch: `codex/goal-inbox-sym-214-docs-claims`.
- HEAD before this report: `2805b84`.
- `git status --short --branch` initially printed only `## codex/goal-inbox-sym-214-docs-claims`, so the tracked worktree was clean.
- `llm-tldr tree .` showed the expected repo-local surface: root Python modules, `tests/`, `docs/`, `modes/`, `config/`, `deploy/`, and `scripts/`.
- `rg --files -g '*.md' | wc -l` found 18 visible Markdown files, not the 6-file documentation set claimed by `DOCS_INDEX.md`.
- `rg -c '@app\.' inbox_server.py` found 160 FastAPI route decorators.
- `rg '^\s*def test_' tests | wc -l` found 864 test definitions.
- `rg -l 'pytestmark = pytest.mark.safe|@pytest.mark.safe' tests` found only `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py` marked safe at file or test level.
- A validation probe, `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest --collect-only -q`, failed before collection because `uv` attempted to download `pyobjc-framework-quartz==12.1` and network/DNS is unavailable in this sandbox. The temporary ignored `.venv` from that failed probe was removed.

## Documentation surface reviewed

Core docs reviewed:

- `README.md`
- `CLAUDE.md`
- `DOCS_INDEX.md`
- `MCP_SETUP.md`
- `MCP_V1_PLAN.md`
- `CONNECTOR_ROADMAP.md`
- `PLAN.md`
- `SHEETS.md`
- `SHEETS_QUICKSTART.md`
- `SHEETS_CHANGELOG.md`
- `docs/TESTING_FOR_AGENTS.md`
- `modes/_shared.md`
- `modes/morning-brief.md`
- `modes/triage.md`
- `modes/followup-sweep.md`
- `modes/batch-archive.md`
- `config/_profile.md`

Implementation and validation evidence reviewed:

- `pyproject.toml`
- `services.py`
- `inbox_server.py`
- `inbox.py`
- `inbox_client.py`
- `google_account_resolution.py`
- `mcp_gateway.py`
- `mcp_server.py`
- `inbox_mcp_stdio.py`
- `inbox_mcp_readonly.py`
- `inbox_mcp_readonly_stdio.py`
- `tools_registry.py`
- `.mcp.json`
- `.cursor/mcp.json`
- `.gitignore`
- `tests/test_server.py`
- `tests/test_server_endpoints.py`
- `tests/test_tools_registry.py`
- `tests/test_services.py`
- `tests/test_inbox_test_mode.py`
- `tests/test_mcp_gateway.py`

## Supported claims

The README's high-level purpose claim is mostly supported. `README.md:3` says the app consolidates iMessage, Gmail, Calendar, Sheets, Notes, Reminders, GitHub, and Drive. The backend has route families for conversations/messages, Calendar, Notes, Reminders, GitHub, Drive, Sheets, Docs, Tasks, WhatsApp, index views, workflow helpers, and AI endpoints in `inbox_server.py`. The TUI has tabs and state handlers for all/iMessage/Gmail/Calendar/Notes/Reminders/GitHub/Drive/actionable/waiting in `inbox.py:1179-1195` and `inbox.py:1830-1857`.

The client-server claim is supported. `README.md:24` and `CLAUDE.md:80-85` describe `services.py`, `inbox_server.py`, `inbox_client.py`, and `inbox.py` as data layer, FastAPI server, HTTP client, and TUI. The route list in `inbox_server.py` and client methods in `inbox_client.py` match that split.

The token-auth claim is supported for the private REST API and public MCP gateway. `README.md:50` and `CLAUDE.md:115-116` document `INBOX_SERVER_TOKEN`. `inbox_client.py:23` reads that env var for the HTTP client, and `inbox_server.py:213` defines `AUTH_TOKEN_ENV = "INBOX_SERVER_TOKEN"`. `MCP_SETUP.md:142-154` documents separate `INBOX_SERVER_TOKEN` and `INBOX_MCP_TOKEN`; `mcp_gateway.py:18-45` implements `INBOX_MCP_TOKEN` bearer auth for public MCP paths while allowing `/health`.

The MCP split in `MCP_SETUP.md` is broadly supported. The doc says `mcp_server.py` is the full HTTP gateway, `inbox_mcp_readonly.py` is the read-only HTTP gateway, and the `*_stdio.py` files are local subprocess entrypoints. Code matches: `mcp_server.py:145-151` exposes a Starlette `/mcp` app through uvicorn on `127.0.0.1:8000`, `inbox_mcp_readonly.py:80-87` does the same on `INBOX_MCP_READONLY_PORT` defaulting to `8001`, and `inbox_mcp_stdio.py:16-17` / `inbox_mcp_readonly_stdio.py:10-11` run the same MCP objects over stdio.

The confirmation-gating claim is supported for MCP tools registered through `tools_registry.py`. `tools_registry.py:35-42` defines `readonly` and `confirm`; `tools_registry.py:73-78` rejects confirmation-gated tool calls unless `confirm=True`; `tools_registry.py:110-118` omits non-readonly tools when registering the read-only MCP surface. Examples include `send_email_reply`, `create_sheet`, and `append_sheet_rows` in `tools_registry.py:153-229`.

The local test-mode safety claim is partly supported. `docs/TESTING_FOR_AGENTS.md:21-29` says `INBOX_TEST_MODE=1` blocks live writes and redirects test data. `inbox_test_mode.py` implements `assert_live_writes_allowed`, and `services.py:114-119` routes representative writes through it. `tests/test_services.py:909` and `tests/test_services.py:934` cover representative and extended live-write blocking.

The Google account routing roadmap is partly implemented. `CONNECTOR_ROADMAP.md:32-44` says `INBOX_DEFAULT_GOOGLE_ACCOUNT` should be backend-enforced. `google_account_resolution.py:24-33` implements that default helper, and `google_account_resolution.py:109-157` uses it for Gmail, Sheets, Drive, Tasks, Docs, and Calendar service resolution. The preflight layer is also present at `inbox_server.py:3009-3020`, backed by `google_account_resolution.py:160-303`.

The Sheets endpoint tables in `SHEETS.md` and `SHEETS_QUICKSTART.md` are mostly supported by route evidence. `SHEETS.md:63-100` lists 15 Sheets endpoints, and `inbox_server.py:2596-2758` defines the corresponding `/sheets` route family. The MCP tools expose a narrower Sheets subset: list/read/create/append in `tools_registry.py:174-230`.

The credential ignore claims are supported. `README.md:171-174` and `CLAUDE.md:91-93` document local credentials and tokens; `.gitignore:12-25` ignores `credentials.json`, `token.json`, `token.json.lock`, `tokens/`, `github_token.txt`, `google_maps_key.txt`, `gemini_api_key.txt`, `config/inbox.env`, and dotenv/secret files.

## Stale or unsupported claims

The Python version requirement is stale. `README.md:31-34` says Python 3.10+, but `pyproject.toml:5` requires `>=3.12,<3.15`, and Ruff/Pyright target Python 3.12 in `pyproject.toml:40-50`. A new agent following the README can choose an unsupported interpreter.

The README and CLAUDE key-binding docs are stale. `README.md:120-122` and `CLAUDE.md:193-196` say `Ctrl+6` toggles ambient listening and `Ctrl+7` is GitHub. Code now maps `Ctrl+6` to Reminders, `Ctrl+7` to GitHub, `Ctrl+8` to Drive, `Ctrl+9` to Actionable, `Ctrl+0` to Waiting On, and `Ctrl+Shift+6` to Ambient in `inbox.py:1179-1195`. The docs omit Drive/actionable/waiting bindings and point the ambient shortcut at the wrong action.

The "no cloud dependencies" privacy claim is too strong. `README.md:25` says local-first ML has no cloud dependencies, and `README.md:171` says all data processing happens on-device. The repo now has optional cloud integrations: `services.py:84-97` defines `google_maps_key.txt`, `gemini_api_key.txt`, and Google scopes for Gmail/Calendar/Drive/Sheets/Docs/Tasks; `CLAUDE.md:294-297` documents Gemini API and Google Maps as optional; `inbox_server.py:2197-2260` includes Gemini summarization/reply/digest/action-item endpoints. A safer claim is "local-first by default for ASR/autocomplete; optional cloud providers exist for explicit workflows."

The documentation index is stale. `DOCS_INDEX.md:173-175` says the docs were last updated April 2026, Sheets is complete/production-ready, and total documentation is 6 files. Local evidence finds 18 visible Markdown files and 160 backend routes. The index also undercounts system docs by not treating `MCP_SETUP.md`, `MCP_V1_PLAN.md`, `PLAN.md`, `docs/TESTING_FOR_AGENTS.md`, `modes/*.md`, and `config/_profile.md` as first-class docs.

The "All 736 tests pass" claim is stale and unverifiable here. `DOCS_INDEX.md:140` and `SHEETS_CHANGELOG.md:38,114` claim 736 passing tests. Local static evidence found 864 `def test_` definitions. The test command could not be run in this sandbox because `uv` tried to download a missing macOS wheel over a network-restricted connection. The report should not keep a fixed pass count unless CI evidence is linked or the count is generated.

The Sheets changelog is stale about auth tuple shape. `SHEETS_CHANGELOG.md:14` says `google_auth_all()` returns a 4-tuple, and `SHEETS_CHANGELOG.md:30` says the lifespan was updated to unpack a 4-tuple. Code now returns six values: Gmail, Calendar, Drive, Sheets, Docs, and Tasks in `services.py:330-338` and `services.py:416`, and the server lifespan unpacks six values at `inbox_server.py:1216-1222`.

The Sheets docs overstate complete API coverage. `SHEETS_CHANGELOG.md:106` says agents can perform any Sheets operation. The REST API provides 15 broad operations, including raw formatting, but it is not equivalent to every Google Sheets API operation. The MCP tool registry exposes only list/read/create/append for Sheets, so "any operation" is inaccurate for MCP agents. Better wording: "common CRUD, values, tab, copy, clear, batch read/write, and raw formatting requests are exposed over REST; MCP exposes a curated subset."

The Sheets default-account docs are stale. `SHEETS.md:195` and `SHEETS_QUICKSTART.md:130` say omitted account means first available account. `google_account_resolution.py:24-33` now prioritizes `INBOX_DEFAULT_GOOGLE_ACCOUNT` when present, then falls back to the first service key. The connector roadmap says that source-of-truth account should be enforced, so the Sheets docs should mention the env-driven policy.

CLAUDE's MCP architecture section is stale. `CLAUDE.md:83-85` and `CLAUDE.md:274-278` call `mcp_server.py` stdio-based and say agents can use MCP without hitting the server HTTP API. Current code makes `mcp_server.py` an HTTP gateway over `/mcp` that calls the private inbox REST server through `mcp_backend.py`; stdio is provided by `inbox_mcp_stdio.py`. The newer `MCP_SETUP.md` is more accurate than `CLAUDE.md`.

CLAUDE's slash-command claim references ignored local state. `CLAUDE.md:336-352` says the inbox skill router is `.claude/skills/inbox/SKILL.md`; `.gitignore:40-43` ignores `.claude/`, and a local existence check found `.claude/skills/inbox/SKILL.md` missing in this worktree. Future agents should not rely on hidden local slash-command files as repo documentation unless a tracked fallback exists.

The README API reference is not a complete API reference. It documents several main route families, but the server exposes many additional public routes for Gmail actions, Tasks, WhatsApp, Docs, preflight, contacts, index views, workflow helpers, query, notifications, AI helpers, Google Maps, and calendar scheduling. The command `rg -c '@app\.' inbox_server.py` found 160 route decorators, while `README.md:48-114` lists only a subset.

The safe-test marker workflow is under-applied. `docs/TESTING_FOR_AGENTS.md:31-37` defines `safe`, `integration`, `local_data`, `slow`, and `live_write`; `pyproject.toml:53-62` registers them. But only `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py` are safe-marked. `INBOX_TEST_MODE=1 uv run pytest -m safe` may therefore run a very small slice rather than the default deterministic proof set implied by the docs.

## Non-claims and boundaries

The docs do not claim that every server route is safe to call without credentials. Many route families are credentialed by design, and the testing guide explicitly warns against live provider tests.

The docs do not claim that a dev worktree has real Google tokens. `CLAUDE.md:55` explicitly says tokens are per-checkout, gitignored, and must be re-authed or copied.

The docs do not claim that full REST access should be exposed publicly. `MCP_SETUP.md:306-313` says to expose MCP, keep the raw REST API private, prefer read-only MCP for cloud agents, and keep destructive tools confirmation-gated.

The docs do not require a Sheets TUI tab today. `DOCS_INDEX.md:137` and `SHEETS_CHANGELOG.md:117` say a Sheets tab is later/future work; tests also show `tests/test_tui_tabs.py:16` expects detail tabs for Calendar, Notes, Reminders, GitHub, and Drive, not Sheets.

The docs do not require direct provider tools to replace Inbox MCP. `CONNECTOR_ROADMAP.md:335-342` says agents should prefer Inbox MCP, verify `INBOX_SERVER_URL`, and avoid relying on prompt-only routing until implementation is complete.

## Risks and stale assumptions

1. New agents can choose the wrong runtime. README says Python 3.10+, but `pyproject.toml` requires Python 3.12+. This can waste setup time or create misleading validation failures.

2. Shortcut docs can drive unsafe or confusing TUI behavior. A user pressing `Ctrl+6` expecting ambient listening will switch to Reminders; ambient is now `Ctrl+Shift+6`.

3. Privacy language overpromises. Optional Gemini, Google Maps, Google APIs, OAuth tokens, and hosted provider endpoints mean "all processing happens on-device" is not universally true.

4. Fixed test-count claims are stale. The docs say 736 pass while the local tree has 864 test definitions and validation cannot currently run from a cold sandbox without network/cache access.

5. The "production-ready" Sheets claim is stronger than the evidence. There is endpoint coverage and a few MCP/tooling tests, but `SHEETS_CHANGELOG.md:116` admits Sheets functionality is not directly tested in the suite.

6. API docs split creates source-of-truth ambiguity. README is partial, CLAUDE is broader but stale, MCP_SETUP is newer for MCP, and DOCS_INDEX undercounts docs. Agents can choose the wrong source for current behavior.

7. Hidden local skill dependency is fragile. `.claude/skills/inbox/SKILL.md` is ignored and missing here, but CLAUDE describes it as the slash-command router.

8. Preflight and default-account policy docs are behind code. The connector roadmap says the policy should exist; code has pieces of it; Sheets docs still say first account wins.

## Next safe work

1. Align runtime and validation docs.
   Acceptance criteria: `README.md`, `DOCS_INDEX.md`, and `docs/TESTING_FOR_AGENTS.md` all state Python `>=3.12,<3.15`; no fixed "736 tests pass" claim remains unless backed by a CI link; validation docs mention `UV_CACHE_DIR=/tmp/uv-cache` for sandboxed runs.
   Validation: `rg -n 'Python 3.10|736 tests|All 736|requires-python|UV_CACHE_DIR' README.md DOCS_INDEX.md docs/TESTING_FOR_AGENTS.md pyproject.toml`.

2. Refresh TUI key-binding docs from code.
   Acceptance criteria: README and CLAUDE list `Ctrl+6` Reminders, `Ctrl+7` GitHub, `Ctrl+8` Drive, `Ctrl+9` Actionable, `Ctrl+0` Waiting On, and `Ctrl+Shift+6` Ambient; docs do not claim `Ctrl+6` toggles ambient.
   Validation: `rg -n 'Ctrl\\+6|Ctrl\\+8|Ctrl\\+9|Ctrl\\+0|Ctrl\\+Shift\\+6' README.md CLAUDE.md inbox.py`.

3. Make docs source-of-truth explicit.
   Acceptance criteria: `DOCS_INDEX.md` lists all first-class docs or clearly separates user docs, agent docs, plans, and mode prompts; it points MCP readers to `MCP_SETUP.md` as authoritative and marks CLAUDE MCP content as historical unless updated.
   Validation: `rg --files -g '*.md' | sort` and `rg -n 'mcp_server.py|stdio|HTTP gateway|Total documentation' CLAUDE.md DOCS_INDEX.md MCP_SETUP.md`.

4. Tighten Sheets claims and add direct Sheets tests.
   Acceptance criteria: Sheets docs say REST supports a broad common subset rather than every Sheets API operation; default-account behavior mentions `INBOX_DEFAULT_GOOGLE_ACCOUNT`; tests cover at least list/create/read/update/append/clear/tabs/format endpoints with mocked services.
   Validation: `INBOX_TEST_MODE=1 UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_server.py tests/test_tools_registry.py -q` once dependencies are available.

5. Track or remove slash-command router claims.
   Acceptance criteria: either a tracked skill/router doc exists outside `.claude/`, or `CLAUDE.md` explains that `.claude/skills/inbox/SKILL.md` is optional local state and the tracked fallback is `modes/*.md`.
   Validation: `test -e .claude/skills/inbox/SKILL.md; git check-ignore -v .claude/skills/inbox/SKILL.md; rg -n 'Skill router|modes/\\*.md' CLAUDE.md`.

6. Add an agent-safe dependency bootstrap note.
   Acceptance criteria: testing docs describe that cold `uv run` may need network to download macOS wheels; they provide a local-cache or pre-sync expectation for overnight workers.
   Validation: `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest --collect-only -q` should either collect tests or fail with a documented known blocker.

## Validation command candidates

Required queue validation:

- `git status --short`
  Expected now: exit 0. Before commit, it should show only this report as an added file. After commit, it should be empty.

Safe docs-only checks:

- `rg --files -g '*.md' | sort`
  Expected now: exit 0 and include this report under `docs/overnight/`.

- `rg -n 'Python 3.10|All 736|Total documentation|Ctrl\\+6|no cloud dependencies|all data processing' README.md CLAUDE.md DOCS_INDEX.md SHEETS_CHANGELOG.md`
  Expected now: exit 0 with known stale-claim hits.

- `rg -n '@app\\.' inbox_server.py`
  Expected now: exit 0 and show the route surface used to compare API docs.

Blocked until dependencies are available locally:

- `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest --collect-only -q`
  Observed status: failed. `uv` created a fresh `.venv` and attempted to download `pyobjc-framework-quartz==12.1`; network/DNS is unavailable in this sandbox.

- `INBOX_TEST_MODE=1 uv run pytest -m safe`
  Expected after dependency bootstrap: likely pass for the two currently safe-marked test modules, but this command under-validates the project because most deterministic tests are not marked `safe`.

- `uv run ruff check .` and `uv run pyright`
  Expected after dependency bootstrap: unknown. These were not run because `uv run` could not sync dependencies from a cold cache.

## Unknowns

- Whether CI currently passes; no GitHub/CI access was used for this read-only local audit.
- Whether a primary checkout already has a populated `.venv` or uv cache; this isolated worktree did not.
- Whether the intended product language is "privacy-first" with optional cloud integrations or "strictly local." Current code supports the former, while README text implies the latter.
- Whether `.claude/skills/inbox/SKILL.md` exists in another local checkout; it is ignored and absent here.
- Whether every route in `inbox_server.py` is meant to be public documentation or only internal/local power-user surface.

## Handoff

Changed files:

- `docs/overnight/inbox-sym-214-docs-claims.md`

No product code, generated data, secrets, deploy configs, external services, pushes, PRs, or tracker state were intentionally changed.

Blockers:

- Python validation through `uv run` is blocked in this sandbox without a pre-populated uv cache or network access to download macOS wheels.
- Local commit creation is blocked in this sandbox. `git add docs/overnight/inbox-sym-214-docs-claims.md` failed because Git tried to create `/Users/jwalinshah/projects/inbox/.git/worktrees/inbox-sym-214-docs-claims/index.lock`, which is outside the writable roots.
- The docs cannot be made accurate without product judgment on privacy wording and which API surface is authoritative; this audit only reports the claim gaps.
