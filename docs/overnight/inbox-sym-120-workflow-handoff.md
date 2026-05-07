# Overnight Audit: inbox-sym-120 Workflow Handoff

Queue item: `inbox-sym-120-workflow-handoff`
Date: 2026-05-07
Repo: `inbox-sym-120`
Worktree: `/Users/jwalinshah/projects/agent-stack/.agent-stack-worktrees/2026-05-07-overnight-marathon/inbox-sym-120-workflow-handoff`
Focus area: `workflow-handoff`

## Handoff Summary

This repo is a local-first personal inbox control plane: a FastAPI backend wraps Gmail, iMessage, Calendar, Google Workspace, Apple Notes/Reminders, GitHub, local ML/audio, an operational SQLite index, and a Textual TUI. The handoff-sensitive work is not missing feature scaffolding; it is missing a clean bridge from the existing workflow-level backend endpoints into the safer, agent-facing tool surface and validation story.

No product code was changed in this audit. The only intended write is this report.

## Repo State

- Branch: `codex/goal-inbox-sym-120-workflow-handoff`
- Initial HEAD: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`
- Remote: `origin https://github.com/jwalin-shah/inbox.git`
- Initial dirty state: clean (`git status --short --branch` printed only `## codex/goal-inbox-sym-120-workflow-handoff`)
- Recent history observation: current HEAD is also `origin/main` and a family of audit branches; latest visible merge is `Merge pull request #34 from jwalin-shah/codex/SYM-9-indexed-defaults`.
- Repo size observation: `rg --files | wc -l` returned `104`; key source/test/docs files sampled total `20,556` lines by `wc -l`.
- Existing `docs/overnight` state: `git ls-files docs/overnight` returned no tracked reports before this write.

## Evidence Map

- `README.md` describes a privacy-first terminal UI and claims Python 3.10+ quick-start support, local FastAPI server on port 9849, and agent access through the backend API.
- `CLAUDE.md` is the most complete current project context. It documents primary vs dev backend routing, `INBOX_SERVER_PORT`, `INBOX_SERVER_URL`, `INBOX_SERVER_TOKEN`, MCP routing, and the worktree caveat that macOS personal data stores are shared across worktrees.
- `pyproject.toml` requires Python `>=3.12,<3.15`, configures `ruff`, `pyright`, pytest coverage, and test markers `safe`, `integration`, `local_data`, `slow`, and `live_write`.
- `docs/TESTING_FOR_AGENTS.md` defines the safe loop as `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, and `uv run pyright`; it explicitly forbids live-write and local-data tests without opt-in.
- `inbox_server.py` contains the primary FastAPI surface. `ServerState` owns Google services, caches, ambient/dictation services, scheduler state, and the message index; `InboxServerRuntime` lets tests inject fake state and disable scheduler/ambient startup.
- `inbox_server.py` enforces optional API token auth via `INBOX_SERVER_TOKEN`; if the env var is absent, all local API requests are accepted.
- `services.py` is the large integration layer. It contains the live-write guard `_assert_live_write_allowed`, which delegates to `inbox_test_mode.assert_live_writes_allowed` when `INBOX_TEST_MODE` is set.
- `inbox_test_mode.py` blocks live writes with `LiveWriteBlocked`, redirects test-local data through `INBOX_TEST_DATA_DIR`, and supports deterministic time through `INBOX_TEST_NOW`.
- `google_account_resolution.py` implements `INBOX_DEFAULT_GOOGLE_ACCOUNT` routing and `preflight_google_write_payload` for doc, sheet, Drive folder, task, and calendar writes.
- `tools_registry.py` centralizes MCP tools and confirm-gates all tools marked mutating. The registry currently stops at Gmail, iMessage, Notes, Reminders, Tasks, Calendar/Maps, search, WhatsApp, scheduled/followup links, memory extraction, Drive, Docs, and GitHub.
- `tests/test_tools_registry.py` proves all mutating registry tools require `confirm`, read-only registration excludes write tools, path params are URL encoded, and body params remain raw.
- `tests/test_api_contract.py` checks every registered MCP tool path maps to an actual FastAPI endpoint and that `InboxClient` index methods match server response shape.
- `tests/test_server.py` has extensive mocked endpoint coverage for auth, runtime injection, index health, preflight, workflow classification, workflow event/doc/sheet/folder endpoints, and `/inbox/needs-action`.
- `CONNECTOR_ROADMAP.md` sets the target architecture: source adapters, normalization, policy, and intent tools. It explicitly says common workflows should be tool operations rather than prompt improvisation.
- `MCP_V1_PLAN.md` states the security model: private `inbox_server.py`, assistant-facing MCP layer, `INBOX_MCP_TOKEN`, `INBOX_SERVER_TOKEN`, confirmation-gated writes, and audit logging as future work.
- `MCP_SETUP.md` documents two MCP access patterns and warns that dev worktree testing silently talks to primary port 9849 unless both `cwd` and `INBOX_SERVER_URL` are changed.
- `inbox.py` contains an "Ask Inbox Assistant" TUI flow that imports `agents.runner.Supervisor` at call time, but no tracked `agents/` package exists in this worktree.
- `inbox_server.py` has a `/query` endpoint that imports optional `gemma4_hackathon` modules at request time and returns HTTP 503 when they are not installed; `pyproject.toml` does not list that package.

## Workflow-Handoff Assessment

The backend already exposes several workflow-oriented primitives:

- `/preflight/google-write` resolves destination and account before Google writes.
- `/gmail/threads/needing-reply` searches stale reply-needed inbox threads.
- `/calendar/workflow-event` prefixes event kinds and tags descriptions with workflow labels.
- `/inbox/needs-action` rolls up indexed threads, tasks, and near-term calendar events.
- `/drive/workflow-folder`, `/docs/workflow-doc`, and `/sheets/workflow-sheet` create workflow-specific Google Workspace artifacts.
- `/index/status`, `/index/health`, `/index/views/{view_name}`, and `/index/threads` expose the operational index status and compact read models.

Those endpoints are tested in `tests/test_server.py`, but they are not yet visible in `tools_registry.py`. That creates a handoff gap: future agents using MCP get many low-level CRUD actions, but not the intent-level workflow tools that the roadmap says they should prefer.

The second gap is validation clarity. The repo has an explicit `safe` marker system, but only `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py` are marked safe. Important deterministic safety tests in `tests/test_services.py` are not marked safe, so the documented safe command under-exercises the live-write guard surface.

The third gap is optional/runtime dependency clarity. The TUI assistant control path references `agents.runner`, and `/query` references `gemma4_hackathon`. Both are runtime-optional in practice, but they are not represented in `pyproject.toml` or clearly excluded from type-check expectations. This is a predictable handoff trap for agents asked to run `pyright` or inspect assistant behavior.

## Risks And Stale Assumptions

1. MCP workflow drift: `tools_registry.py` is the single MCP registry, but it does not expose `/preflight/google-write`, `/inbox/needs-action`, `/calendar/workflow-event`, `/drive/workflow-folder`, `/docs/workflow-doc`, or `/sheets/workflow-sheet`. This conflicts with `CONNECTOR_ROADMAP.md`, which says the model should use intent-level tools.

2. Direct backend writes bypass MCP confirmation: the MCP registry adds `confirm=True`, but FastAPI write endpoints themselves do not require confirmation. Any local caller with `INBOX_SERVER_TOKEN` can hit write endpoints directly. The service-level `INBOX_TEST_MODE` guard is good for tests, not production confirmation policy.

3. Preflight is advisory, not enforced: `google_account_resolution.py` can explain where writes will land, and `tests/test_server.py` covers it, but write endpoints such as workflow doc/sheet/folder and task/calendar creation do not require a successful preflight result before mutating provider state.

4. Safe test marker coverage is stale: docs tell agents to run `INBOX_TEST_MODE=1 uv run pytest -m safe`, but marker search found only two safe-marked files. Representative live-write guard tests in `tests/test_services.py` are deterministic but not safe-marked.

5. Documentation claims are inconsistent: `README.md` says Python 3.10+, while `pyproject.toml` and `.python-version` require Python 3.12. `DOCS_INDEX.md` claims "All 736 tests pass", but this audit did not find a current command observation supporting that claim.

6. Optional assistant dependencies are underspecified: `inbox.py` imports `agents.runner.Supervisor` at runtime and `/query` imports `gemma4_hackathon`; neither is tracked in the repo or declared as an optional dependency. Agents running type checks or TUI assistant flows may chase missing modules instead of intended product work.

7. Worktree isolation is partial: `CLAUDE.md` correctly warns that iMessage, Notes, Reminders, and AddressBook stores are shared across worktrees. Starting a dev backend without `INBOX_TEST_MODE=1`, alternate ports, and disabled ambient/scheduler settings can still touch personal data or external services.

8. Public HTTP MCP still needs audit hardening: `MCP_V1_PLAN.md` lists audit logging as a next step. Until then, token auth and confirm gates are the main controls, with no durable tool-call audit trail for remote/cloud clients.

## Next Grabbable Tasks

### Task 1: Expose Workflow Intent Tools Through MCP

Acceptance criteria:
- Add MCP registry entries for `preflight_google_write`, `get_needs_action`, `get_threads_needing_reply`, `create_workflow_event`, `create_workflow_folder`, `create_workflow_doc`, and `create_workflow_sheet`.
- Mark read-only tools as `readonly=True`.
- Mark all mutating workflow tools as `confirm=True`.
- Ensure read-only MCP registration excludes all mutating workflow tools.
- Keep one source of truth in `tools_registry.py`; do not add duplicated hand-written MCP handlers.

Suggested validation:
- `INBOX_TEST_MODE=1 uv run pytest tests/test_tools_registry.py tests/test_api_contract.py -q`
- Expected status: pass after registry/path updates.

### Task 2: Repair Agent-Safe Validation Coverage

Acceptance criteria:
- Mark deterministic live-write guard tests in `tests/test_services.py` as `safe`, or split them into a dedicated safe test file.
- Reconcile docs so `README.md`, `DOCS_INDEX.md`, `docs/TESTING_FOR_AGENTS.md`, `.python-version`, and `pyproject.toml` agree on Python version and test claims.
- Replace the stale "736 tests pass" claim with a reproducible command and last-known observation, or remove the count.
- Keep live provider, local-data, audio, and external-write tests outside the default safe loop.

Suggested validation:
- `INBOX_TEST_MODE=1 uv run pytest -m safe -q`
- `uv run ruff check .`
- Expected status: pass; the safe suite should include representative live-write guard coverage.

### Task 3: Enforce Preflight On Google Workflow Writes

Acceptance criteria:
- For workflow Google writes, require either a successful preflight or a shared helper that resolves the same destination/account before mutation.
- Include resolved account and destination in responses for workflow doc/sheet/folder/event/task writes.
- Add tests for missing account services, invalid Drive folder, invalid task list, and explicit non-default account writes.
- Update `config/inbox.env.example` and MCP docs to mention `INBOX_DEFAULT_GOOGLE_ACCOUNT`.

Suggested validation:
- `INBOX_TEST_MODE=1 uv run pytest tests/test_server.py -k "Preflight or workflow" -q`
- Expected status: pass after endpoint/helper tests are updated.

### Task 4: Harden Optional Assistant Features

Acceptance criteria:
- Decide whether `agents.runner` is an in-repo package, optional external package, or obsolete feature.
- If optional, hide or degrade the TUI command when unavailable and document setup requirements.
- Add a deterministic test for the command palette or assistant action so missing optional packages produce a user-readable failure instead of an implementation mystery.
- Treat `/query` the same way: either declare the optional `gemma4_hackathon` dependency or document that 503 is the expected unavailable state.

Suggested validation:
- `INBOX_TEST_MODE=1 uv run pytest tests/test_command_palette.py tests/test_inbox_app.py -q`
- `uv run pyright`
- Expected status: command tests pass; `pyright` may currently fail until optional imports are modeled or ignored.

## Validation Command Candidates

- Required queue validation: `git status --short`
  - Observed after writing the report: `?? docs/overnight/`; exit status 0.

- Safe agent loop: `INBOX_TEST_MODE=1 uv run pytest -m safe -q`
  - Expected today: likely pass, but coverage is too narrow because only two test files are safe-marked.

- MCP registry/API contract proof: `INBOX_TEST_MODE=1 uv run pytest tests/test_tools_registry.py tests/test_api_contract.py -q`
  - Expected today: likely pass for the current registry; should be rerun after adding workflow tools.

- Workflow/preflight endpoint proof: `INBOX_TEST_MODE=1 uv run pytest tests/test_server.py -k "Preflight or workflow" -q`
  - Expected today: likely pass based on existing tests; should fail first if used TDD for preflight enforcement.

- Lint: `uv run ruff check .`
  - Expected today: unknown in this worktree because the audit did not create a venv or run lint.

- Type check: `uv run pyright`
  - Expected today: higher risk than lint because optional imports like `agents.runner` and `gemma4_hackathon` are not represented in `pyproject.toml`.

## Non-Goals For This Queue Item

- No product code changes.
- No generated data, cache, or local database changes.
- No live backend startup.
- No live Google, Gmail, Calendar, Drive, Docs, Sheets, Tasks, iMessage, Notes, Reminders, GitHub, WhatsApp, audio, notification, or MCP calls.
- No external service writes.
- No deploys.
- No pushes or PR creation.
- No external tracker state changes.

## Unknowns

- Whether `agents.runner` is intentionally supplied by another checkout, a generated folder, or a stale missing package.
- Whether the primary daily-driver backend is currently running on port 9849; this audit intentionally did not call it.
- Whether `INBOX_DEFAULT_GOOGLE_ACCOUNT` is set in the user's real environment.
- Whether the full test suite currently passes in a fully hydrated local environment.
- Whether `gemma4_hackathon` is expected to be installed for this repo or only for an old experiment.
- Whether morning review expects a commit for report-only audit work; this worker left the report uncommitted unless the runner handles commits.

## Commands Run

- `llm-tldr tree .`
- `git status --short --branch`
- `git rev-parse HEAD`
- `git branch --show-current`
- `rtk read AGENTS.md`
- `rtk read README.md`
- `rtk read CLAUDE.md`
- `rtk read pyproject.toml`
- `rtk read docs/TESTING_FOR_AGENTS.md`
- `rtk read DOCS_INDEX.md`
- `rg -n "^(class|def|async def) |^app =|^@app" inbox_server.py`
- `rg -n "^(class|def|async def) " services.py`
- `rg -n "^(class|def|async def) " inbox.py`
- `rg -n "^(class|def|async def)|^@mcp|FastMCP|tool" mcp_backend.py mcp_server.py inbox_mcp_stdio.py inbox_mcp_readonly.py inbox_mcp_readonly_stdio.py`
- `rg -n "INBOX_TEST_MODE|assert_live_writes_allowed|live_write|safe" .`
- `nl -ba inbox_server.py | sed -n '750,1355p'`
- `nl -ba inbox_server.py | sed -n '2900,3025p'`
- `nl -ba inbox_test_mode.py | sed -n '1,120p'`
- `nl -ba mcp_backend.py | sed -n '1,220p'`
- `nl -ba tools_registry.py | sed -n '1,170p'`
- `nl -ba tools_registry.py | sed -n '170,360p'`
- `nl -ba tools_registry.py | sed -n '360,880p'`
- `nl -ba tests/test_tools_registry.py | sed -n '1,260p'`
- `nl -ba tests/test_inbox_test_mode.py | sed -n '1,260p'`
- `nl -ba tests/conftest.py | sed -n '1,260p'`
- `nl -ba tests/test_mcp_gateway.py | sed -n '1,240p'`
- `nl -ba tests/test_server.py | sed -n '1,260p'`
- `rg -n "workflow|preflight|confirm|live_write|scheduler|ambient|create_app|auth|INBOX_SERVER_TOKEN" tests/test_server.py tests/test_server_endpoints.py tests/test_api_contract.py tests/test_mcp_gateway.py tests/test_tools_registry.py tests/test_services.py tests/test_gmail_actions.py tests/test_message_sync.py`
- `nl -ba CONNECTOR_ROADMAP.md | sed -n '1,220p'`
- `nl -ba MCP_V1_PLAN.md | sed -n '1,180p'`
- `nl -ba PLAN.md | sed -n '1,180p'`
- `nl -ba gmail_triage.py | sed -n '1,360p'`
- `nl -ba message_index_store.py | sed -n '1,260p'`
- `nl -ba message_sync.py | sed -n '1,280p'`
- `git log --oneline -8 --decorate`
- `git remote -v`
- `git diff --stat`
- `git ls-files docs/overnight`
- `rg --files | wc -l`
- `wc -l services.py inbox_server.py inbox.py tools_registry.py message_sync.py message_index_store.py tests/test_server.py tests/test_tools_registry.py tests/test_inbox_test_mode.py docs/TESTING_FOR_AGENTS.md README.md CLAUDE.md CONNECTOR_ROADMAP.md PLAN.md`
- `rg -n "pytestmark = pytest.mark.safe|@pytest.mark.safe|@pytest.mark.integration|@pytest.mark.local_data|@pytest.mark.live_write|@pytest.mark.slow" tests`
- `rg -n "\[project\]|requires-python|dependencies =|\[dependency-groups\]|\[tool.ruff\]|\[tool.pyright\]|\[tool.pytest|markers|safe:|live_write" pyproject.toml`
- `nl -ba google_account_resolution.py | sed -n '1,260p'`
- `nl -ba tests/test_gmail_actions.py | sed -n '1,180p'`
- `nl -ba tests/test_server.py | sed -n '1488,1622p'`
- `mkdir -p docs/overnight`
- `git status --short`
- `rtk read docs/overnight/inbox-sym-120-workflow-handoff.md`
- `wc -l docs/overnight/inbox-sym-120-workflow-handoff.md`

## Final Handoff Fields

- Files changed: `docs/overnight/inbox-sym-120-workflow-handoff.md`
- Commit SHA at audit time: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`
- Validation result: `git status --short` exited 0 and printed `?? docs/overnight/`.
- PR URL: none; PR creation is out of scope for this queue item.
- Blockers: none for the audit report. Follow-up implementation should not run live provider tests or external writes without explicit human approval.
