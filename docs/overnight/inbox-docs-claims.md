# inbox-docs-claims

Queue item: `inbox-docs-claims`
Repo: `inbox`
Focus area: docs claims
Branch observed: `codex/goal-inbox-docs-claims`
HEAD observed: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`
Report date: 2026-05-07

## Scope And Method

This is a read-only documentation-claims audit. Product code, generated data,
secrets, external services, deploys, pushes, PR creation, and tracker updates
were out of scope. The only intended filesystem change is this report:
`docs/overnight/inbox-docs-claims.md`.

Initial dirty state was clean:

```text
$ git status --short --branch
## codex/goal-inbox-docs-claims
```

The repo purpose, as supported by `README.md` and `CLAUDE.md`, is a local
Python/Textual/FastAPI personal inbox that unifies iMessage, Gmail, Google
Calendar, Google Sheets, Apple Notes, Apple Reminders, GitHub notifications,
Google Drive, Google Docs, Google Tasks, voice/ambient capture, and MCP access.
The code is a flat Python application rather than a package tree.

## Commands Run

- `llm-tldr tree .` - mapped repo structure, including top-level app files,
  docs, config examples, deploy examples, scripts, modes, batch helpers, and
  31 test files.
- `git status --short --branch` - confirmed starting branch and clean dirty
  state.
- `git rev-parse HEAD` - recorded
  `2805b8400519da188ca7d3f6e39b19a8ca42b05a`.
- `rg --files -g '*.md'` - found 18 Markdown files, not the six docs claimed
  by `DOCS_INDEX.md`.
- `rg -n "@app\.(get|post|put|delete|patch)" inbox_server.py | wc -l` -
  found 159 FastAPI endpoint decorators.
- `rg -n "^\s*Tool\(" tools_registry.py | wc -l` - found 60 MCP registry
  tools.
- `rg --files tests | wc -l` - found 31 test files.
- `rg -n "^def test_|^    def test_" tests | wc -l` - found 864 static
  `test_` definitions.
- `rg -n "pytestmark = pytest\.mark\.safe|@pytest\.mark\.safe" tests` -
  found only `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py`
  marked safe at module/decorator level.
- `test -e .claude/skills/inbox/SKILL.md && echo present || echo missing` -
  confirmed the documented slash-command skill router is absent in this
  checkout.

## Evidence Inventory

1. `README.md:1-27` claims a unified communication/productivity TUI with
   iMessage, Gmail, Calendar, Sheets, Notes, Reminders, GitHub, Drive, ambient
   listening, dictation, autocomplete, optimistic UI, client-server split, local
   ML, and multi-account Gmail routing.
2. `README.md:31-45` says requirements are Python 3.10+, macOS, and `uv`, and
   gives `uv run python inbox.py` / `uv run python inbox_server.py`.
3. `pyproject.toml:1-25` is stronger evidence for runtime support than the
   README: it requires Python `>=3.12,<3.15` and declares FastAPI, Textual,
   MLX, Outlines, MCP, Google API clients, PyObjC, sounddevice, Rich, and
   Uvicorn dependencies.
4. `pyproject.toml:53-62` configures pytest to use `tests` and coverage, and
   registers safe/integration/local_data/slow/live_write markers.
5. `CLAUDE.md:118-190` lists a broad endpoint catalog, but
   `inbox_server.py:1346-3896` currently exposes 159 FastAPI endpoint
   decorators, including many endpoints absent from the short README.
6. `inbox_server.py:2596-2761` supports the Sheets endpoint family listed in
   the Sheets docs: list, create, get, delete, range read/write/append/clear,
   batch get/update, tab add/delete/rename/copy, and formatting.
7. `services.py:4083-4388` implements the Sheets service operations. Most
   mutating operations call `_assert_live_write_allowed`, but
   `sheets_rename_sheet`, `sheets_format`, and `sheets_copy_to` do not.
8. `inbox_server.py:2932-2998` supports Google Docs list/create/get/delete/text
   insert/export endpoints.
9. `services.py:4437-4474` blocks live writes for Docs create/delete, but
   `services.py:4476-4495` inserts text without `_assert_live_write_allowed`.
10. `google_account_resolution.py:24-33` implements
    `INBOX_DEFAULT_GOOGLE_ACCOUNT` fallback for service selection; this supports
    the connector-roadmap direction that default account routing should be in
    code.
11. `google_account_resolution.py:85-106` resolves Gmail replies by explicit
    account, cached message/thread owner, message/thread existence probes, then
    default fallback. `inbox_server.py:1581-1594` returns the resolved account
    for Gmail replies.
12. `tools_registry.py:1-11` says one central table drives full and read-only
    MCP servers. `tools_registry.py:110-119` filters by `readonly_only`, and
    `tests/test_tools_registry.py:41-53` asserts all mutating tools are
    confirmation-gated and read-only registration excludes write tools.
13. `mcp_server.py:34-38` creates a stateless HTTP `FastMCP`; `mcp_server.py:148-151`
    runs Uvicorn on `127.0.0.1:8000`. This contradicts older `CLAUDE.md`
    language calling `mcp_server.py` stdio-based.
14. `inbox_mcp_stdio.py:13-17` is the actual local stdio entrypoint for the full
    tool surface; `inbox_mcp_readonly_stdio.py:7-11` is the actual read-only
    stdio entrypoint.
15. `.mcp.json:1-28`, `config/codex.inbox.example.toml:1-28`, and
    `MCP_SETUP.md:144-169` support the two-token routing claim:
    `INBOX_SERVER_TOKEN` protects the private backend and `INBOX_MCP_TOKEN`
    protects the public MCP gateway.
16. `.gitignore:12-24` supports the credential-storage claims for
    `credentials.json`, `token.json`, `tokens/`, `github_token.txt`,
    `google_maps_key.txt`, `gemini_api_key.txt`, `config/inbox.env`, and env
    files.
17. `docs/TESTING_FOR_AGENTS.md:1-43` documents a safe validation policy:
    `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, and
    `uv run pyright`, with live/local data requiring explicit opt-in.
18. `inbox_test_mode.py:18-31` implements test mode and test-local data roots.
    `tests/test_services.py:909-951` verifies representative live-write blocks,
    but it does not cover every mutating service function.
19. `inbox.py:1179-1196` is the authoritative current keybinding list:
    `ctrl+6` is Reminders, `ctrl+7` GitHub, `ctrl+8` Drive, `ctrl+shift+6`
    Ambient, `ctrl+9` Actionable, and `ctrl+0` Waiting On.
20. `README.md:120-123` and `CLAUDE.md:193-196` still claim `Ctrl+6` toggles
    ambient listening. This is stale relative to `inbox.py:1179-1196` and
    `tests/test_inbox_app.py:706-718`.
21. `tui_tabs.py:19-120` defines ten tabs: Now, Actionable, Waiting On,
    iMessage, Gmail, Calendar, Notes, Reminders, GitHub, and Drive. README's
    keybinding table still describes only the older All/iMessage/Gmail/Calendar
    /Notes plus GitHub layout.
22. `DOCS_INDEX.md:101-111` explicitly admits quickstart/changelog coverage is
    Sheets-only; this is a useful non-claim for Gmail, Calendar, Drive,
    iMessage, Notes/Reminders, and GitHub.
23. `DOCS_INDEX.md:173-175` says total documentation is six files. Static local
    inventory found 18 Markdown files, including `MCP_SETUP.md`,
    `CONNECTOR_ROADMAP.md`, `PLAN.md`, `docs/TESTING_FOR_AGENTS.md`, and
    `modes/*.md`.
24. `CLAUDE.md:338-350` claims first-class `/inbox` slash commands with router
    `.claude/skills/inbox/SKILL.md`; the file is missing in this checkout, and
    `.gitignore:40-41` ignores `.claude/`.
25. `modes/batch-archive.md:45-50` tells agents to archive Gmail with
    `add_label_ids: ["ARCHIVED"]` and `remove_label_ids: ["INBOX"]`, while
    `batch/batch-runner.sh:74-80` uses `add_label_ids: []` and
    `remove_label_ids: ["INBOX"]`. The shell runner looks more consistent with
    Gmail archive semantics than the mode prompt.

## Supported Claims

- The project is genuinely client-server: `inbox_server.py` owns FastAPI
  endpoints and service access; `inbox_client.py` calls those endpoints; the TUI
  in `inbox.py` uses the client. This matches README/CLAUDE architecture claims.
- The repo has real Google Sheets API support at the service and server layers.
  The endpoint set in `SHEETS.md` is mostly backed by `inbox_server.py` and
  `services.py`.
- The repo has real Google Docs support, though the docs surface is thinner than
  Sheets and has a write-safety gap for text insertion.
- The repo has real Google Tasks support despite older docs underemphasizing it:
  `services.py:88-98` includes the tasks scope, `google_auth_all` returns a
  tasks service dict, and `inbox_server.py:2006-2054` exposes task endpoints.
- Token and credential non-commit claims are supported by `.gitignore`.
- MCP read-only vs full surfaces exist and are enforced at registry registration
  time for registry-backed tools.
- The documented test-safety concept exists in code: test mode redirects data
  roots and blocks many representative live writes.
- The connector-roadmap account-routing direction is partly implemented:
  `INBOX_DEFAULT_GOOGLE_ACCOUNT` is honored by shared service-resolution helpers
  and covered by tests in `tests/test_server.py`.

## Unsupported Or Stale Claims

- Python version support is stale. `README.md:31-34` says Python 3.10+, but
  `pyproject.toml:5` requires `>=3.12,<3.15`; `pyproject.toml:48-50` sets
  pyright to Python 3.12.
- The 736 passing test claim is stale or at least unevidenced in this checkout.
  `DOCS_INDEX.md:40-45`, `DOCS_INDEX.md:134-140`, and
  `SHEETS_CHANGELOG.md:38,114-121` cite 736 pass / production-ready. Static
  local inventory found 31 test files and 864 `test_` definitions, and no test
  run artifact was present in this audit.
- Current keybindings are stale in README and CLAUDE. `Ctrl+6` no longer
  toggles ambient; code and tests make it Reminders. Ambient moved to
  `Ctrl+Shift+6`; Drive, Actionable, and Waiting On also have keybindings that
  the old docs do not explain.
- `CLAUDE.md:274-278` says `mcp_server.py` is stdio-based and agents can use MCP
  without hitting the server HTTP API. Current code makes `mcp_server.py` an HTTP
  Uvicorn app; the stdio wrapper is `inbox_mcp_stdio.py`, which imports the HTTP
  tool surface and runs it over stdio.
- "Exposes all inbox functionality" is too broad for MCP. The FastAPI app has
  159 endpoint decorators; the central registry has 60 tools plus a few
  hand-written memory/note tools. This is a curated surface, not all endpoints.
- `DOCS_INDEX.md` is no longer a complete documentation index. It claims six
  docs, but the repo contains 18 Markdown files and several operational docs are
  not represented in the coverage table.
- The slash-command claim is unsupported in this checkout because
  `.claude/skills/inbox/SKILL.md` is absent.
- "All mutations return operation stats" for Sheets is too broad:
  create/get/delete/tab operations return metadata or `{"ok": bool}` in
  `inbox_server.py:2612-2761`, while only values operations naturally return
  Google update/append stats.
- "Tests (stubs ML/macOS deps)" is broadly plausible from `conftest.py` and
  test coverage, but `docs/TESTING_FOR_AGENTS.md` is the safer source for agent
  validation because it distinguishes safe, local-data, and live-write classes.

## Risks And Stale Assumptions

1. Documentation can lead users to run with an unsupported Python version.
   README's Python 3.10+ claim conflicts directly with `pyproject.toml`.
2. Safe test-mode claims are too broad. Several mutating functions lack
   `_assert_live_write_allowed`: `sheets_rename_sheet`, `sheets_format`,
   `sheets_copy_to`, and `docs_insert_text`. Direct server endpoint calls can
   reach those functions in test mode.
3. MCP docs are split-brain. `MCP_SETUP.md` matches the current HTTP/stdout
   architecture better than `CLAUDE.md`, so agents using `CLAUDE.md` may point
   clients at the wrong entrypoint.
4. The slash-command docs depend on ignored local state. A fresh clone or
   isolated worktree will not have `.claude/skills/inbox/SKILL.md`, so `/inbox`
   commands are not reproducible from tracked files alone.
5. Test-count and "production-ready" claims look like release-note residue.
   Static test inventory no longer lines up with the cited count, and the docs
   do not say which commit produced the passing run.
6. Keybinding drift is user-facing. Users following README/CLAUDE would press
   `Ctrl+6` expecting ambient listening and land on Reminders instead.
7. The batch archive mode prompt and shell runner disagree on Gmail archive
   label mutation. Agents following the prompt could try to add a nonstandard
   `ARCHIVED` label.
8. Docs use broad "full API" language for Sheets and MCP. The implementation is
   useful and broad, but not every Google Sheets API concept or every inbox
   endpoint is exposed as a first-class safe tool.

## Next Safe Work

### Task 1: Refresh Core Docs To Match Current Runtime

Acceptance criteria:
- `README.md` says Python `>=3.12,<3.15` or links to `pyproject.toml` as the
  source of truth.
- README and CLAUDE keybindings match `inbox.py:1179-1196`.
- README mentions Reminders, Drive, Actionable, Waiting On, and Ambient's
  current `Ctrl+Shift+6` binding.
- `CLAUDE.md` describes `mcp_server.py` as HTTP and
  `inbox_mcp_stdio.py` / `inbox_mcp_readonly_stdio.py` as stdio.

Validation candidates:
- `git diff -- README.md CLAUDE.md`
- `INBOX_TEST_MODE=1 uv run pytest tests/test_tui_tabs.py tests/test_inbox_app.py -q`
- Expected status: docs diff should show only claim corrections; focused tests
  are expected to pass if dependencies are installed.

### Task 2: Close Test-Mode Write-Safety Gaps

Acceptance criteria:
- Add `_assert_live_write_allowed(...)` to every Google Sheets and Google Docs
  mutating service function, including rename, format, copy, and insert text.
- Extend `tests/test_services.py::test_test_mode_blocks_extended_live_writes`
  or add focused tests so those paths are covered.
- Update `docs/TESTING_FOR_AGENTS.md` only if the validation command changes.

Validation candidates:
- `INBOX_TEST_MODE=1 uv run pytest tests/test_services.py::test_test_mode_blocks_extended_live_writes -q`
- `INBOX_TEST_MODE=1 uv run pytest -m safe`
- Expected status: focused test should pass after implementation; full safe set
  should pass if environment dependencies are installed.

### Task 3: Make Docs Index A Real Inventory

Acceptance criteria:
- `DOCS_INDEX.md` lists all tracked Markdown docs or explicitly scopes itself
  to "core user docs" and links to an operational-docs section.
- Remove hard-coded "736 tests pass" and replace it with validation command
  guidance plus "last verified" format that includes commit/date when known.
- Reconcile `SHEETS_CHANGELOG.md` release-note claims so they do not state a
  stale pass count as current fact.

Validation candidates:
- `rg --files -g '*.md'`
- `rg -n "736|production-ready|Total documentation" DOCS_INDEX.md SHEETS_CHANGELOG.md`
- Expected status: inventory command should match the index or the index should
  explain its scope; stale pass-count search should return no current claims.

### Task 4: Make Slash Commands Reproducible Or Downgrade The Claim

Acceptance criteria:
- Either commit a tracked skill/router equivalent for `/inbox` commands, or
  change `CLAUDE.md` to say the tracked `modes/*.md` files are prompts and the
  slash-command router is local-only if installed.
- Document how a fresh worktree should invoke `modes/morning-brief.md`,
  `modes/triage.md`, `modes/followup-sweep.md`, and `modes/batch-archive.md`
  without relying on ignored `.claude/` state.

Validation candidates:
- `test -e .claude/skills/inbox/SKILL.md && echo present || echo missing`
- `rg -n "Skill router|/inbox|modes/" CLAUDE.md modes`
- Expected status: either router exists or docs no longer claim tracked
  first-class slash commands.

### Task 5: Reconcile Batch Archive Prompt With Runner

Acceptance criteria:
- `modes/batch-archive.md` uses the same Gmail archive payload as
  `batch/batch-runner.sh`: remove `INBOX`, do not add `ARCHIVED`.
- Document that iMessage archive is unsupported by the runner unless/until
  implemented.

Validation candidates:
- `rg -n "ARCHIVED|batch-modify|unsupported source" modes/batch-archive.md batch/batch-runner.sh`
- Expected status: mode and runner agree on the Gmail payload and unsupported
  source behavior.

## Validation Map

Required queue validation:

```bash
git status --short
```

Expected final result after this report is written: the output should show only
`docs/overnight/inbox-docs-claims.md` as an added/untracked report file.

Agent-safe validation from tracked docs:

```bash
INBOX_TEST_MODE=1 uv run pytest -m safe
uv run ruff check .
uv run pyright
```

Expected status: not run for this docs-only audit because the queue item only
requires `git status --short`, product code changes were out of scope, and a
full test/type/lint loop may need dependencies and create local caches. These
are the correct next commands for implementation tasks.

Focused docs/safety commands:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py -q
INBOX_TEST_MODE=1 uv run pytest tests/test_tools_registry.py -q
INBOX_TEST_MODE=1 uv run pytest tests/test_tui_tabs.py -q
```

Expected status: should pass if dependencies are installed. These target the
specific docs-claim surfaces: test mode docs, MCP registry confirmation gates,
and current tab metadata.

## Non-Goals

- No product-code changes.
- No test, lint, or type fixes.
- No external credential checks.
- No live server startup.
- No Google, GitHub, AppleScript, microphone, WhatsApp, Drive, Docs, Sheets, or
  Calendar calls.
- No PR, push, deploy, or tracker update.
- No attempt to validate personal data paths under `~/Library`.

## Unknowns

- Whether the full test suite currently passes on a fully provisioned macOS
  machine.
- Which commit, if any, produced the "736 tests pass" claim.
- Whether the ignored `.claude/skills/inbox/SKILL.md` exists in the user's
  primary checkout outside this isolated worktree.
- Whether all OAuth scopes are currently granted for the user's local tokens.
- Whether remote/cloud MCP deployment is currently active; this audit only
  checked tracked local code and examples.
- Whether `repos.json` has sibling repos with overlapping docs; this queue item
  was scoped to the `inbox` repo and did not require touching unrelated repos.

## Handoff

Changed files:
- `docs/overnight/inbox-docs-claims.md`

Commit SHA:
- Current HEAD at audit time:
  `2805b8400519da188ca7d3f6e39b19a8ca42b05a`

PR URL:
- None. PR creation was out of scope for this queue item.

Blockers:
- None for writing this report.

Validation result:
- Ran `git status --short`; exit code 0. Output:

```text
?? docs/overnight/
```

This is expected for a new untracked report directory containing only
`docs/overnight/inbox-docs-claims.md`.
