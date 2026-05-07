# Overnight Docs-Claims Audit: inbox-sym-117

Queue item: `inbox-sym-117-docs-claims`
Branch: `codex/goal-inbox-sym-117-docs-claims`
Base HEAD observed before report: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`
Audit date: 2026-05-07

## Scope

This is a read-only docs-claims audit plus this single report. I did not edit product code, run live provider writes, push, deploy, create a PR, or touch external trackers.

The repo is a local-first personal inbox/TUI/backend that joins macOS personal data stores, Google APIs, GitHub notifications, local ML/audio features, and MCP surfaces. The current docs are broad and mostly useful, but several claims have drifted from the code and validation reality.

## Repo State

- `git status --short --branch` initially returned only `## codex/goal-inbox-sym-117-docs-claims`, so no tracked or untracked dirty state was visible before this report.
- `git rev-parse HEAD` returned `2805b8400519da188ca7d3f6e39b19a8ca42b05a`.
- `llm-tldr tree .` showed a flat Python app with core modules (`inbox.py`, `inbox_server.py`, `services.py`, `inbox_client.py`), MCP modules, 31 test files under `tests/`, operational docs, config examples, deploy examples, and no existing `docs/overnight/` report directory.
- Running `uv run pytest -m safe -q` created a local `.venv` and `.coverage`; both are ignored by `.gitignore` (`.gitignore:9-10`, `.gitignore:27-29`).
- The exact documented safe command, `INBOX_TEST_MODE=1 uv run pytest -m safe -q`, failed in this sandbox because `uv` attempted to initialize `/Users/jwalinshah/.cache/uv`, outside the writable roots.
- Workaround command `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe -q` passed with `11 passed, 855 deselected` on CPython 3.12.12.
- Required validation `git status --short` passed after writing the report and showed `?? docs/overnight/`.
- Staging/commit was attempted but blocked by sandbox permissions: `git add docs/overnight/inbox-sym-117-docs-claims.md && git diff --cached --stat` failed because Git could not create `/Users/jwalinshah/projects/inbox/.git/worktrees/inbox-sym-117-docs-claims/index.lock`.

## Documentation Inventory

Relevant local docs and config evidence:

- `README.md` is the public overview, quick start, API summary, keybindings, architecture, dev commands, and privacy statement.
- `CLAUDE.md` is the broad project context with worktree workflow, a larger API list, data sources, integration details, testing notes, and session-start health check.
- `DOCS_INDEX.md` is a docs navigation page with explicit test-count and production-ready claims.
- `SHEETS.md`, `SHEETS_QUICKSTART.md`, and `SHEETS_CHANGELOG.md` are the highest-claim docs, especially around "full" Sheets access.
- `MCP_SETUP.md` and `MCP_V1_PLAN.md` describe public/private MCP topology, token separation, and v1 tool intent.
- `CONNECTOR_ROADMAP.md` is planning material, not shipped-state docs; it names target policies such as `INBOX_DEFAULT_GOOGLE_ACCOUNT`.
- `docs/TESTING_FOR_AGENTS.md` defines the safe local validation loop and live-write opt-in policy.
- `config/inbox.env.example`, `config/codex.inbox.example.toml`, `deploy/Caddyfile.example`, and launch/service examples support the MCP setup docs.

## Supported Claims

These claims are well supported by local code:

- Client/server architecture is real. `README.md:23-25` and `CLAUDE.md:78-85` map to `inbox_server.py` FastAPI construction at `inbox_server.py:1288-1310`, HTTP client defaults at `inbox_client.py:16-25`, and TUI client startup at `inbox_client.py:49-77`.
- Default server port and worktree override are supported. `CLAUDE.md:13`, `CLAUDE.md:31-45`, `dev.sh:7-11`, and `inbox_client.py:16-17` all agree on `9849` default and `9850` dev override patterns.
- Optional REST auth via `INBOX_SERVER_TOKEN` is implemented. `README.md:50` and `CLAUDE.md:115-116` map to `inbox_server.py:1313-1340`, which accepts bearer tokens and `x-api-key`.
- Google service construction covers Gmail, Calendar, Drive, Sheets, Docs, and Tasks. `services.py:88-98` lists scopes, and `services.py:330-416` returns six service maps.
- Sheets REST endpoints broadly match the detailed Sheets docs. `SHEETS_CHANGELOG.md:25-29`, `SHEETS.md:63-100`, and `inbox_server.py:2596-2761` align on list/create/get/delete, value get/update/append/clear/batch, tab add/delete/rename/copy, and format.
- Local SQLite reads use read-only URI mode. This supports the read-only data-source framing in `README.md:144-148`; implementation evidence is `services.py:220-230`.
- MCP public auth and `/mcp`/`/health` routing are implemented. `MCP_SETUP.md:142-154` and `MCP_SETUP.md:281-290` map to `mcp_gateway.py:18-45` and `mcp_gateway.py:87-93`.
- Read-only MCP registration is test-covered. `inbox_mcp_readonly.py:77-80` registers only readonly tools, and `tests/test_tools_registry.py:46-53` checks write tools are absent from readonly registration.
- Test docs correctly warn that personal-data integrations need explicit opt-in. `docs/TESTING_FOR_AGENTS.md:21-43` aligns with `inbox_test_mode.py` checks in `tests/test_inbox_test_mode.py:11-80` and write-guard tests in `tests/test_services.py:934-951`.

## Stale Or Unsupported Claims

1. Python version requirement is wrong in README.
   - Claim: `README.md:31-34` says Python 3.10+.
   - Evidence: `pyproject.toml:5` requires `>=3.12,<3.15`; `pyproject.toml:40-49` targets Python 3.12 in Ruff/Pyright.
   - Risk: a new user on 3.10 or 3.11 will follow the README and hit install or syntax/runtime failures.

2. The "736 tests pass" claim is stale.
   - Claim: `DOCS_INDEX.md:40-45`, `DOCS_INDEX.md:134-140`, `SHEETS_CHANGELOG.md:34-38`, and `SHEETS_CHANGELOG.md:112-121` say all 736 tests pass.
   - Evidence: `rg -n "^\s*def test_" tests | wc -l` returned `864`; safe pytest output reported `11 passed, 855 deselected`, implying 866 collected test cases in that run.
   - Risk: morning reviewers may trust a dated count instead of running the current suite.

3. The documented agent-safe test command is incomplete for sandboxed agent runs.
   - Claim: `docs/TESTING_FOR_AGENTS.md:7-13` recommends `INBOX_TEST_MODE=1 uv run pytest -m safe`.
   - Evidence: exact command failed here with `failed to open file /Users/jwalinshah/.cache/uv/... Operation not permitted`; adding `UV_CACHE_DIR=/tmp/uv-cache` made it pass.
   - Risk: local isolated workers can falsely report validation blocked even though the test itself is healthy.

4. `safe` marker coverage is much narrower than the test suite.
   - Claim context: `docs/TESTING_FOR_AGENTS.md:7-18` presents `pytest -m safe` as the default verification loop.
   - Evidence: only `tests/test_inbox_test_mode.py:8` and `tests/test_mcp_gateway.py:18` set `pytestmark = pytest.mark.safe`; safe run selected 11 tests and deselected 855.
   - Risk: docs may imply a broader proof than the marker currently provides.

5. README keybinding for ambient listening is stale.
   - Claim: `README.md:120-122` and `CLAUDE.md:193-199` say `Ctrl+6` toggles ambient listening.
   - Evidence: `inbox.py:1179-1194` binds `ctrl+6` to Reminders and `ctrl+shift+6` to Ambient; `tests/test_inbox_app.py:706-718` asserts `Ctrl+6` opens Reminders.
   - Risk: users following docs will switch tabs instead of toggling ambient capture.

6. MCP transport descriptions conflict.
   - Claim: `CLAUDE.md:83-85` and `CLAUDE.md:274-278` call `mcp_server.py` stdio-based.
   - Evidence: `mcp_server.py:34-38` creates a stateless HTTP `FastMCP`, `mcp_server.py:145-151` serves it through uvicorn on port 8000, and `inbox_mcp_stdio.py:13-17` is the stdio wrapper.
   - Counter-evidence: `MCP_SETUP.md:19-36` correctly distinguishes HTTP and stdio surfaces.
   - Risk: agent/client setup can point at the wrong transport.

7. "No cloud dependencies" for LLM/ASR is overstated.
   - Claim: `README.md:23-25` says local-first ML has "no cloud dependencies"; `README.md:165` says no API calls for ASR or LLM.
   - Evidence: `pyproject.toml:10` includes `google-generativeai`; `CLAUDE.md:294` documents optional Gemini; `services.py:3249-3473` implements Gemini summarization, replies, categorization, digest, and action extraction; `inbox_server.py:2197-2262` exposes Gemini endpoints.
   - Risk: privacy docs under-disclose optional cloud LLM paths.

8. README privacy credential list is incomplete.
   - Claim: `README.md:171-174` lists `credentials.json`, `tokens/`, and `github_token.txt`.
   - Evidence: `.gitignore:13-20` and `services.py:84-86` also include `google_maps_key.txt`, `gemini_api_key.txt`, and `config/inbox.env`; `CLAUDE.md:294-297` documents Gemini and Maps keys.
   - Risk: a user doing a secret sweep from README alone can miss sensitive local files.

9. "Full Google Sheets API access" and "any Sheets operation" are too broad.
   - Claim: `SHEETS_QUICKSTART.md:1-3`, `SHEETS_CHANGELOG.md:102-110`, and `CLAUDE.md:222-230` say full/any Sheets operation access.
   - Evidence: REST code implements a useful but finite subset at `inbox_server.py:2596-2761`; MCP exposes only `list_sheets`, `read_sheet_values`, `create_sheet`, and `append_sheet_rows` for Sheets in `tools_registry.py:176-237`.
   - Risk: agents may assume capabilities such as protected ranges, named ranges, charts, pivot tables, or permissions exist as first-class operations when they do not.

10. Sheets multi-account body examples are partly wrong.
   - Claim: `SHEETS.md:181-193` says write operations can specify `account` in the request body.
   - Evidence: `SheetValuesUpdateRequest` has only `values` and `value_input` (`inbox_server.py:504-507`), while update/append/batch endpoints take `account` as a query parameter (`inbox_server.py:2650-2670`, `inbox_server.py:2698-2705`). Body `account` only exists for create/add/format request models (`inbox_server.py:498-523`).
   - Risk: a multi-account write can silently default to the first available account if the caller puts account in the wrong place.

11. Live-write guard coverage is incomplete for some Sheets writes.
   - Claim: `docs/TESTING_FOR_AGENTS.md:25-29` says live writes are blocked through `assert_live_writes_allowed`.
   - Evidence: `sheets_values_update`, `sheets_values_append`, `sheets_values_clear`, `sheets_add_sheet`, and delete paths call `_assert_live_write_allowed` (`services.py:4161-4244`, `services.py:4255-4303`), but `sheets_rename_sheet`, `sheets_format`, and `sheets_copy_to` do not (`services.py:4315-4388`).
   - Risk: test-mode and agent-safe guarantees are weaker than documented for those Sheets mutations.

12. `SHEETS_CHANGELOG.md` contains a stale tuple migration claim.
   - Claim: `SHEETS_CHANGELOG.md:11-15`, `SHEETS_CHANGELOG.md:30-36`, and `SHEETS_CHANGELOG.md:124-129` describe a move to a 4-tuple and "only addition: sheets service + endpoints".
   - Evidence: current `google_auth_all()` returns six maps (`services.py:330-416`) and includes Docs and Tasks scopes/services (`services.py:88-98`, `services.py:404-416`).
   - Risk: implementers updating fixtures or auth code from the changelog will miss Docs/Tasks.

13. `MCP_V1_PLAN.md` is useful as plan history but no longer describes the full MCP surface.
   - Claim: `MCP_V1_PLAN.md:28-62` lists a narrow v1 tool set.
   - Evidence: `tools_registry.py:129-848` contains many more Gmail, Sheets, Tasks, Calendar, WhatsApp, scheduled/followup, Drive, Docs, and GitHub tools.
   - Risk: treating the plan as current API reference will under-document available tools and policy coverage.

## Explicit Non-Claims

- `PLAN.md` and `CONNECTOR_ROADMAP.md` are forward-looking. For example, `PLAN.md:74-80` explicitly lists incomplete areas, and `CONNECTOR_ROADMAP.md:32-45` describes desired account-default policy rather than current enforcement.
- `MCP_V1_PLAN.md` should be read as historical planning unless promoted or replaced by a current MCP API reference.
- The audit did not verify live Gmail, Calendar, Drive, Sheets, Docs, Tasks, iMessage, Notes, Reminders, GitHub, Maps, Gemini, microphone, or accessibility behavior.
- The report does not claim the app is unsafe to run; it only identifies places where docs overstate or misroute current behavior.

## Risks And Stale Assumptions

1. Multi-account write safety risk: stale account-location docs plus first-account fallback can route Sheets writes to the wrong Google account.
2. Validation trust risk: "736 tests pass" and a narrow `safe` marker can create false confidence in morning review.
3. Privacy/compliance risk: README's local/no-cloud phrasing under-discloses optional Gemini and Maps integrations plus extra key files.
4. Agent setup risk: conflicting MCP transport docs can make clients use HTTP vs stdio incorrectly or hit the wrong backend.
5. Live-write test-mode risk: several Sheets mutations lack `_assert_live_write_allowed`, so the docs' safety guarantee is not universal.
6. User workflow risk: stale `Ctrl+6` documentation can accidentally switch to Reminders instead of toggling ambient listening.

## Next Safe Work

1. Update README/DOCS_INDEX/CLAUDE runtime and keybinding claims.
   - Acceptance: README says Python 3.12+, `Ctrl+6` is Reminders, `Ctrl+Shift+6` is Ambient, and test-count wording avoids fixed stale totals.
   - Validation: `rg -n "Python 3.10|736 tests|Ctrl\\+6.*Ambient|stdio-based MCP server" README.md DOCS_INDEX.md CLAUDE.md` returns no stale matches except historical notes explicitly marked as historical.

2. Fix agent-safe validation docs for sandboxed workers.
   - Acceptance: `docs/TESTING_FOR_AGENTS.md` documents `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe`, explains that `safe` currently covers 11 tests, and points broader validation to explicit commands.
   - Validation: `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe -q` passes.

3. Tighten Sheets multi-account and "full API" language.
   - Acceptance: `SHEETS.md`, `SHEETS_QUICKSTART.md`, and `SHEETS_CHANGELOG.md` say "supported Sheets operations" instead of "any operation"; account placement is documented per endpoint as query vs body.
   - Validation: `rg -n "full Google Sheets API|any Sheets operation|account.*body" SHEETS.md SHEETS_QUICKSTART.md SHEETS_CHANGELOG.md CLAUDE.md` has no unsupported broad claim.

4. Add test-mode guards for uncovered Sheets mutations.
   - Acceptance: `sheets_rename_sheet`, `sheets_format`, and `sheets_copy_to` call `_assert_live_write_allowed`; tests cover all three under `INBOX_TEST_MODE=1`.
   - Validation: `INBOX_TEST_MODE=1 uv run pytest tests/test_services.py -q` passes, with `UV_CACHE_DIR=/tmp/uv-cache` in sandboxed workers.

5. Split current MCP API docs from historical MCP plans.
   - Acceptance: a current MCP surface doc is generated from `tools_registry.TOOLS`, and `MCP_V1_PLAN.md` is labeled historical or archived.
   - Validation: `uv run pytest tests/test_tools_registry.py tests/test_mcp_gateway.py -q` passes; a docs check confirms every tool name appears in the current MCP reference.

6. Update README privacy section to include optional cloud and key files.
   - Acceptance: README lists `google_maps_key.txt`, `gemini_api_key.txt`, `config/inbox.env`, and explains optional Gemini/Maps network behavior.
   - Validation: `rg -n "gemini_api_key|google_maps_key|config/inbox.env|Gemini API|Google Maps" README.md` returns expected lines.

## Validation Candidates

| Command | Expected status | Notes |
|---|---:|---|
| `git status --short` | Pass | Required queue validation; should show only this report before commit or clean after commit. |
| `INBOX_TEST_MODE=1 uv run pytest -m safe -q` | Fail in this sandbox | Fails on default uv cache path under `/Users/jwalinshah/.cache/uv`; docs do not mention cache override. |
| `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe -q` | Pass | Observed `11 passed, 855 deselected`; good cheap proof for docs-only edits touching test guidance. |
| `uv run ruff check .` | Unknown/not run | Candidate for code/doc-adjacent changes; may need `UV_CACHE_DIR=/tmp/uv-cache` in sandbox. |
| `uv run pyright` | Unknown/not run | Candidate for code changes; not necessary for this report-only audit. |
| `uv run pytest tests/ -q` | Unknown/not run | Current docs claim stale 736 total; full suite should be run before any "all tests pass" claim is restored. |

## Commands Run

- `llm-tldr tree .`
- `git status --short --branch`
- `git rev-parse --show-toplevel && git rev-parse --abbrev-ref HEAD && git rev-parse HEAD`
- `rg --files -g 'README*' -g 'AGENTS.md' -g 'CLAUDE.md' -g 'docs/**' -g '*.md'`
- `rtk read README.md`
- `rtk read DOCS_INDEX.md`
- `rtk read pyproject.toml`
- `rtk read CLAUDE.md`
- `rtk read MCP_SETUP.md`
- `rtk read docs/TESTING_FOR_AGENTS.md`
- `rg` searches over docs, routes, services, tests, MCP, keybindings, privacy, and Sheets claims
- `sed`/`nl -ba` targeted line reads for docs and implementation evidence
- `uv run pytest -m safe -q`
- `INBOX_TEST_MODE=1 uv run pytest -m safe -q`
- `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe -q`
- `rg -n "^\s*def test_" tests | wc -l`
- `rg --files tests | wc -l`
- `git ls-files docs/overnight docs || true`
- `git status --short`
- `git add docs/overnight/inbox-sym-117-docs-claims.md && git diff --cached --stat` (blocked by sandbox permissions)

## Unknowns

- Whether the full suite currently passes; this audit did not run `uv run pytest tests/ -q`.
- Whether live provider endpoints work with current local credentials; live credentials and external writes were out of scope.
- Whether the current primary checkout differs from this isolated worktree in runtime config, tokens, or generated state.
- Whether the fixed test count after full pytest collection is exactly 866; the safe run reported 855 deselected plus 11 passed, while a simple `def test_` grep returned 864 definitions.
- Whether all MCP tools are intentionally exposed; the registry has grown beyond `MCP_V1_PLAN.md`.

## Handoff

Changed file: `docs/overnight/inbox-sym-117-docs-claims.md`
Commit SHA: no new commit created; current HEAD remains `2805b8400519da188ca7d3f6e39b19a8ca42b05a`.
PR URL: none; PR creation is out of scope for this queue item.
Validation result: `git status --short` exited 0 and showed `?? docs/overnight/`.
Blockers: none for writing the report. Local staging/commit is blocked by sandbox permissions on the parent repo worktree index lock. Exact documented safe-test command is blocked in this sandbox without `UV_CACHE_DIR=/tmp/uv-cache`.
