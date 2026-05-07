# inbox-sym-116 docs-claims audit

Queue item: `inbox-sym-116-docs-claims`
Branch: `codex/goal-inbox-sym-116-docs-claims`
HEAD at audit start: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`
Focus area: docs-claims

## Scope

This is a read-only product audit plus one report file. I did not change product
code, generated data, credentials, deploy config, external trackers, or remote
services. I did not push, open a PR, or mark any tracker Done.

Non-goals:

- Do not validate live Gmail, Calendar, Drive, Docs, Sheets, Reminders, iMessage,
  GitHub, WhatsApp, microphone, or notification behavior.
- Do not start the inbox server or MCP gateways.
- Do not repair the docs in this slice.
- Do not create, delete, archive, send, or mutate personal data.

## Repo Purpose And State

The repo is a local personal inbox/control-plane application. The docs describe a
Python Textual TUI backed by a local FastAPI server, with data adapters for
iMessage, Gmail, Google Calendar, Google Sheets, Google Docs, Google Drive,
Apple Notes, Apple Reminders, GitHub, local ML/audio, MCP gateways, and workflow
tools.

Observed repo state:

- `git rev-parse --show-toplevel` -> `/Users/jwalinshah/projects/agent-stack/.agent-stack-worktrees/2026-05-07-overnight-marathon/inbox-sym-116-docs-claims`
- `git branch --show-current` -> `codex/goal-inbox-sym-116-docs-claims`
- `git rev-parse HEAD` -> `2805b8400519da188ca7d3f6e39b19a8ca42b05a`
- Initial `git status --short --branch` was clean.
- `llm-tldr tree .` showed a flat Python app plus root docs, `docs/TESTING_FOR_AGENTS.md`, `modes/`, `scripts/`, `deploy/`, `config/`, and 31 test files.

## Commands And Observations

- `llm-tldr tree .`: repo has root app modules (`inbox.py`, `inbox_server.py`,
  `services.py`, `mcp_server.py`, `tools_registry.py`), docs, deploy examples,
  mode prompts, scripts, and tests.
- `rg --files -g '*.md' | wc -l`: 18 markdown docs before this report, which
  conflicts with `DOCS_INDEX.md` saying total documentation is 6 files.
- `rg --files tests | wc -l`: 31 test files.
- `rg -n "^(async )?def test_" tests | wc -l`: 250 statically visible test
  functions, not 736.
- `rg -n "@pytest.mark.safe|pytestmark = pytest.mark.safe" tests`: only
  `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py` are marked
  safe.
- `rg -n "@app\\.(get|post|put|patch|delete)\\(" inbox_server.py | wc -l`: 159
  FastAPI route decorators, much broader than README and CLAUDE endpoint lists.
- `rg -n "Tool\\(" tools_registry.py | wc -l`: 60 MCP registry tool entries.
- `INBOX_TEST_MODE=1 uv run pytest --collect-only -q -p no:cacheprovider` failed
  because the default uv cache path under `~/.cache/uv` is not writable in this
  sandbox.
- `INBOX_TEST_MODE=1 UV_CACHE_DIR=/tmp/uv-cache uv run pytest --collect-only -q -p no:cacheprovider`
  created a temporary `.venv` and then failed because network access is blocked
  while trying to download `mlx-whisper==0.4.3`. The generated `.venv` was moved
  out of the repo to `/tmp/inbox-sym-116-docs-claims-venv`.

## Supported Claims

1. Client-server architecture is real.
   - `README.md` and `CLAUDE.md` describe FastAPI server plus thin TUI/client.
   - Local evidence: `inbox_server.py` defines the FastAPI app and routes;
     `inbox_client.py` is the HTTP client; `inbox.py` is the Textual TUI;
     `dev.sh` sets alternate worktree ports.

2. Google account routing exists in code.
   - `google_account_resolution.py:24` selects `INBOX_DEFAULT_GOOGLE_ACCOUNT`
     when it is present in a service map, then falls back to first service key.
   - `inbox_server.py:1460`, `1477`, `1481`, `1485`, `2767`, and `3389` delegate
     Gmail, Sheets, Drive, Tasks, Docs, and Calendar account lookup to that
     helper module.
   - `tests/test_server.py` contains default-account tests for Calendar, Drive,
     Docs, Tasks, and preflight paths.

3. Sheets implementation exists and is broad.
   - `services.py:4026` through `4358` includes listing, metadata, create,
     trash, values get/update/append/clear, batch values, tabs, formatting, and
     copy.
   - `inbox_server.py:2596` through `2754` exposes `/sheets` endpoints.
   - `tools_registry.py:176` through `235` exposes list/read/create/append
     Sheets tools, with writes confirmation-gated.

4. Google Docs exists even though some docs treat Sheets as the newest surface.
   - `services.py:4394` through `4508` implements docs list/get/create/delete,
     export, insert text, and text extraction.
   - `inbox_server.py:2932` through `2986` exposes `/docs` endpoints.
   - `tools_registry.py:751` through `817` exposes Docs tools over MCP.

5. MCP setup claims are substantially backed by local files.
   - `.mcp.json` and `.cursor/mcp.json` exist and configure full plus read-only
     stdio servers.
   - `mcp_backend.py:19` reads `INBOX_SERVER_URL` and `INBOX_SERVER_TOKEN`.
   - `mcp_gateway.py:18` uses `INBOX_MCP_TOKEN`; `mcp_gateway.py:48` protects
     non-health MCP routes; `mcp_gateway.py:87` mounts `/health` and `/mcp`.
   - `deploy/Caddyfile.example` proxies only `/health` and `/mcp` for full and
     read-only hosts.

6. Read-only MCP separation is backed by registry filtering.
   - `inbox_mcp_readonly.py:77` calls `register_all(..., readonly_only=True)`.
   - `tools_registry.py:110` skips non-readonly tools when `readonly_only` is
     true.
   - `tests/test_tools_registry.py:46` verifies readonly registration excludes
     write tools.

7. Live-write test mode is real, but not comprehensively documented in every
   command claim.
   - `inbox_test_mode.py` defines `INBOX_TEST_MODE` and `LiveWriteBlocked`.
   - `services.py:114` defines `_assert_live_write_allowed`.
   - `services.py` calls the guard before many live writes, including Gmail,
     Calendar, Reminders, Tasks, Drive, Sheets, Docs, GitHub notifications, and
     desktop notifications.

8. Apple Notes docs are partly true.
   - `services.py:1872` lists Apple Notes from `NoteStore.sqlite`.
   - `services.py:1922` fetches full note body via AppleScript, not direct
     SQLite parsing.
   - `inbox_server.py:1898` and `1904` expose `/notes` and `/notes/{id}`.

9. The index-driven inbox direction in `PLAN.md` is backed by code.
   - `message_index_store.py` and `message_sync.py` exist.
   - `inbox_server.py:3739` exposes `/inbox/needs-action`.
   - `inbox_server.py:3805` through `3850` exposes index status, views, health,
     bootstrap sync, and incremental sync endpoints.
   - `tests/test_server.py` has index endpoint and health tests.

## Unsupported Or Stale Claims

1. Python version claim is stale.
   - `README.md:32` says Python 3.10+.
   - `pyproject.toml:5` requires `>=3.12,<3.15`, and Ruff/Pyright are configured
     for Python 3.12.

2. Test pass-count claims are unsupported in this checkout.
   - `DOCS_INDEX.md:44`, `DOCS_INDEX.md:140`, `SHEETS_CHANGELOG.md:38`, and
     `SHEETS_CHANGELOG.md:114` claim all 736 tests pass.
   - Static local count found 250 `test_` functions across 31 test files.
   - Pytest collection could not run in this sandbox because uv needed package
     downloads and network is disabled.

3. "Total documentation: 6 files" is false.
   - `DOCS_INDEX.md:175` says total documentation is 6 files.
   - `rg --files -g '*.md'` found 18 markdown files before this report, including
     `PLAN.md`, `MCP_SETUP.md`, `MCP_V1_PLAN.md`, `docs/TESTING_FOR_AGENTS.md`,
     and five mode/profile docs.

4. TUI keybinding docs are stale.
   - `README.md:120` and `CLAUDE.md:195` say Ctrl+6 toggles ambient listening.
   - `inbox.py:1188` maps Ctrl+6 to Reminders.
   - `inbox.py:1193` maps Ctrl+Shift+6 to Ambient.
   - `tui_tabs.py:19` through `120` also shows current tabs include Now,
     Actionable, Waiting On, Reminders, GitHub, and Drive, beyond the README's
     older Ctrl+1-5 framing.

5. Local-only privacy wording is overbroad.
   - `README.md:25` says "Local-first ML" with "no cloud dependencies".
   - `README.md:171` says all data processing happens on-device.
   - `pyproject.toml:10` depends on `google-generativeai`.
   - `services.py:3249` through `3288` defines a Gemini backend.
   - `inbox_server.py:2197` through `2261` exposes Gemini-backed AI endpoints.
   - The app also intentionally talks to Google, GitHub, and optional Google
     Maps APIs. A safer claim is "local default for ML/autocomplete where MLX is
     used; provider APIs and optional Gemini/Maps are cloud surfaces."

6. `SHEETS_CHANGELOG.md` tuple claims are stale.
   - `SHEETS_CHANGELOG.md:14`, `30`, and `35` say `google_auth_all()` changed
     from a 3-tuple to a 4-tuple and tests were updated to a 4-tuple.
   - `services.py:330` through `416` returns a 6-tuple: Gmail, Calendar, Drive,
     Sheets, Docs, Tasks.
   - `inbox_server.py:1216`, `3334`, and `3351` unpack six values.

7. MCP V1 plan is historical, not current.
   - `MCP_V1_PLAN.md:17` says Calendar stays on the built-in ChatGPT Google
     connector for now.
   - `tools_registry.py:481` through `521` exposes calendar/maps conflict and
     travel tools; `inbox_server.py` exposes extensive calendar routes.
   - `MCP_V1_PLAN.md:28` lists a narrow V1 tool set, while `tools_registry.py`
     currently has 60 tool entries, including Sheets, Drive, Docs, Tasks,
     WhatsApp, task links, memory extraction, and GitHub.

8. API references are incomplete and internally inconsistent.
   - `README.md` lists a useful subset of endpoints, but `inbox_server.py`
     contains 159 route decorators.
   - `CLAUDE.md:130` lists `POST /preflight/write`, while the actual route is
     `GET /preflight/google-write` at `inbox_server.py:3009`.
   - README omits Google Tasks, Docs, index endpoints, workflow endpoints,
     WhatsApp, memory extraction, contacts, query, voice config, extended
     Calendar endpoints, and several Gmail actions.

9. Account-default wording is inconsistent.
   - `SHEETS.md:195` and `SHEETS_QUICKSTART.md:130` say omitted account uses the
     first available account.
   - `CONNECTOR_ROADMAP.md:38` says writes should default to
     `INBOX_DEFAULT_GOOGLE_ACCOUNT`.
   - Code does both: environment default if present, first service key otherwise.
     Docs should state the actual precedence.

10. Sheets "production-ready" is not locally evidenced.
   - `DOCS_INDEX.md:140` says all 736 tests pass and production-ready.
   - `SHEETS_CHANGELOG.md:114` says all 736 tests pass, then immediately notes
     "Sheets functionality not directly tested in test suite".
   - There are unit tests for routing, account helpers, and MCP registry guards,
     but I did not find direct service-level fake Sheets API tests for every
     claimed operation.

11. "All operations available via API" for Sheets needs precision.
   - `DOCS_INDEX.md:136` says all operations are available via API.
   - Local code supports broad CRUD/ranges/tabs/raw `batchUpdate`, but "all
     Sheets API operations" is too broad unless it means "all operations this
     app currently exposes".

## Risks And Stale Assumptions

1. Setup risk: a new worker following `README.md` may use Python 3.10 and fail
   before any product validation because the package requires Python 3.12+.

2. Validation risk: docs repeatedly cite "736 pass" and recommend full pytest,
   but this worktree cannot collect tests without a provisioned dependency cache
   or network. The `safe` marker also currently covers only two modules, so
   `pytest -m safe` is not equivalent to "all deterministic local tests".

3. Operator risk: stale keybinding docs can cause live-user mistakes. Ctrl+6 is
   no longer ambient; it switches to Reminders. Ambient is Ctrl+Shift+6.

4. Privacy/security risk: unqualified "no cloud dependencies" and "all data
   processing on-device" understate Google/GitHub/Maps/Gemini cloud surfaces and
   may mislead users about data movement.

5. API-handoff risk: agents using README/CLAUDE endpoint references may miss
   current routes or call stale ones such as `POST /preflight/write`.

6. Product-status risk: `CONNECTOR_ROADMAP.md`, `PLAN.md`, `MCP_V1_PLAN.md`,
   `DOCS_INDEX.md`, and `SHEETS_CHANGELOG.md` mix current truth, roadmap intent,
   and historical release notes without labeling lifecycle state.

7. Safety risk: write surfaces are extensive. MCP registry confirmation gates
   are supported by tests, but direct REST endpoints still rely on
   `INBOX_TEST_MODE` or external client discipline; docs should separate REST
   write risk from MCP write confirmation.

## Next Safe Work

1. Documentation truth pass for runtime and TUI claims.
   - Files: `README.md`, `CLAUDE.md`, `DOCS_INDEX.md`.
   - Acceptance criteria: Python version says 3.12+; keybindings match
     `inbox.py`; docs count no longer claims 6; test count/pass claims are
     removed or generated; privacy wording distinguishes local ML from provider
     APIs and optional Gemini/Maps.
   - Validation: `git diff --check README.md CLAUDE.md DOCS_INDEX.md` and
     `rg -n "Python 3.10|736|Total documentation: 6|Ctrl\\+6.*Ambient|no cloud dependencies|all data processing happens on-device" README.md CLAUDE.md DOCS_INDEX.md`.
     Expected after fix: no stale hits except intentionally quoted history.

2. API docs reconciliation check.
   - Files: add or update a docs test around `inbox_server.py`, `README.md`,
     `CLAUDE.md`, and `tools_registry.py`.
   - Acceptance criteria: there is one canonical generated or checked list of
     FastAPI routes and MCP tools; stale `POST /preflight/write` is removed or
     mapped to `GET /preflight/google-write`; docs clearly mark summary versus
     exhaustive endpoint tables.
   - Validation: `INBOX_TEST_MODE=1 UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_api_contract.py tests/test_tools_registry.py -q`.
     Expected in provisioned env: pass. Expected in this sandbox: blocked until
     dependencies are available locally.

3. Agent-safe test marker cleanup.
   - Files: `docs/TESTING_FOR_AGENTS.md`, `pyproject.toml`, relevant tests.
   - Acceptance criteria: either mark deterministic tests with `safe` or change
     docs so `pytest -m safe` is explicitly a small smoke suite; add a test that
     prevents docs from claiming an unverified global pass count.
   - Validation: `INBOX_TEST_MODE=1 UV_CACHE_DIR=/tmp/uv-cache uv run pytest -m safe --collect-only -q -p no:cacheprovider`.
     Expected after dependency setup: collection succeeds and selected count is
     intentional.

4. Mark historical docs explicitly.
   - Files: `MCP_V1_PLAN.md`, `SHEETS_CHANGELOG.md`, maybe `CONNECTOR_ROADMAP.md`.
   - Acceptance criteria: historical tuple/pass-count statements are labeled as
     old or corrected to six-service auth; MCP V1 plan states whether it is
     archival or current; roadmap items that are already partially implemented
     link to current endpoints/tests.
   - Validation: `rg -n "4-tuple|3-tuple|736|Calendar stays on the built-in|V1 Tools" MCP_V1_PLAN.md SHEETS_CHANGELOG.md CONNECTOR_ROADMAP.md`.
     Expected after fix: no unlabeled stale claims.

5. Sheets confidence upgrade.
   - Files: `tests/test_server.py`, `tests/test_services.py`, possibly a new
     `tests/test_sheets.py`.
   - Acceptance criteria: service-level fake Sheets/Drive tests cover create,
     values update/append/clear, tabs, formatting, trash, and account selection;
     docs avoid "production-ready" until those tests exist and pass.
   - Validation: `INBOX_TEST_MODE=1 UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_server.py tests/test_services.py -k "sheet or sheets" -q`.
     Expected after implementation: pass in provisioned env.

## Validation Candidates

- Required queue validation: `git status --short`. Expected now: one untracked
  report file under `docs/overnight/`.
- Formatting check for this docs-only slice: `git diff --check docs/overnight/inbox-sym-116-docs-claims.md`.
  Expected: pass.
- Full local safe loop from docs: `INBOX_TEST_MODE=1 uv run pytest -m safe`;
  expected in this sandbox: blocked by uv cache/network unless dependencies are
  already provisioned. Expected after setup: should pass, but currently exercises
  only safe-marked modules.
- API/docs contract candidate: `INBOX_TEST_MODE=1 UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_api_contract.py tests/test_tools_registry.py -q`.
  Expected in this sandbox: blocked by dependency download; expected in a
  provisioned local env: should pass if current tests are green.
- Static stale-claim scan: `rg -n "Python 3.10|736|Total documentation: 6|Ctrl\\+6|no cloud dependencies|4-tuple|POST /preflight/write" README.md CLAUDE.md DOCS_INDEX.md SHEETS_CHANGELOG.md MCP_V1_PLAN.md`.
  Expected now: fail with known stale claims; expected after docs cleanup: no
  unlabeled stale hits.

## Unknowns

- I did not know whether the user's primary checkout has a populated `.venv` or
  warm uv cache where pytest can run without network.
- I did not verify live Google, Apple, GitHub, MCP, Gemini, Maps, WhatsApp, MLX,
  audio, or notification behavior.
- I did not inspect external issue state, PRs, deployment hosts, or live Caddy
  configuration.
- I did not determine whether `MCP_V1_PLAN.md` is intended to remain archival or
  should be updated in place as current architecture.

## Handoff

Changed files:

- `docs/overnight/inbox-sym-116-docs-claims.md`

Commit SHA:

- No commit created by this worker. Audit base/head SHA:
  `2805b8400519da188ca7d3f6e39b19a8ca42b05a`

PR URL:

- None. PR creation is out of scope for this Goal Pack item.

Blockers:

- Pytest collection could not run in this sandbox because uv needed to download
  `mlx-whisper==0.4.3` and network/DNS is unavailable.
- Cleanup note: `rm -rf .venv` was blocked by command policy after the failed uv
  attempt created a temporary virtualenv, so I moved `.venv` out of the repo to
  `/tmp/inbox-sym-116-docs-claims-venv`.
