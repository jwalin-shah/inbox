# inbox-sym-120 risk register audit

Queue item: `inbox-sym-120-risk-register`
Audit date: 2026-05-07
Scope: risk-register audit only. No product code, generated data, secrets, external services, deploys, pushes, or PRs were touched.

## Repo State

- Purpose: `inbox-sym-120` is a local-first Python inbox assistant/TUI with a FastAPI backend, MCP gateways, macOS data-source readers, Google/GitHub integrations, local ML/audio features, and agent-facing tools. Evidence: `README.md`, `CLAUDE.md`, `services.py`, `inbox_server.py`, `mcp_server.py`, `tools_registry.py`.
- Branch at audit start: `codex/goal-inbox-sym-120-risk-register`.
- HEAD at audit start: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`.
- Dirty state at audit start: `git status --short --branch` printed only `## codex/goal-inbox-sym-120-risk-register`; `git status --short` printed no entries.
- Dirty state after report creation: `git status --short` exits 0 and prints `?? docs/overnight/`, representing this one report directory/file.
- Commit status: local commit is blocked in this sandbox because `git add docs/overnight/inbox-sym-120-risk-register.md && git diff --cached --stat` failed while trying to create `/Users/jwalinshah/projects/inbox/.git/worktrees/inbox-sym-120-risk-register/index.lock` with `Operation not permitted`. The worktree contents are updated, but the report is not committed.
- Sibling-repo comparison: skipped. This repo is not small: `llm-tldr tree .` showed 30+ Python modules, deployment/config/script directories, `.factory` validation artifacts, and 31 tests under `tests/`. The risk surface was large enough to use the full slice inside this repo.

## Commands Run

- `llm-tldr tree .`: mapped top-level modules, config/deploy/scripts/docs/tests, MCP entrypoints, and local data stores.
- `git status --short --branch`: confirmed the branch and clean starting state.
- `git rev-parse --show-toplevel && git rev-parse --abbrev-ref HEAD && git rev-parse HEAD`: captured repo root, branch, and starting SHA.
- `rtk read README.md`, `rtk read CLAUDE.md`, `rtk read pyproject.toml`, `rtk read docs/TESTING_FOR_AGENTS.md`: read purpose, workflow, dependencies, and test policy.
- `rtk read MCP_SETUP.md`, `rtk read config/inbox.env.example`, `rtk read config/codex.inbox.example.toml`, `rtk read config/gemini-settings.inbox.example.json`: read auth/deployment guidance and token examples.
- `rg -n "_assert_live_write_allowed\\(" services.py inbox_server.py mcp_backend.py tools_registry.py`: counted 44 service-level live-write guard occurrences.
- `rg -n "drive_upload|upload_to_drive|/drive/upload" tests services.py inbox_server.py tools_registry.py README.md CLAUDE.md`: found Drive upload is exposed in docs/API and tested for upload behavior, but not covered by a test-mode live-write assertion.
- `git check-ignore -v credentials.json token.json tokens/foo.json github_token.txt google_maps_key.txt gemini_api_key.txt .inbox_scheduler.sqlite3 .inbox_index.sqlite3 .inbox_memory.sqlite3 config/inbox.env .env batch/triage-output.tsv batch/archive-state.tsv`: confirmed core secrets and generated state are ignored by `.gitignore`.
- `git status --short --ignored`: printed no entries at audit time, so no ignored local secrets or generated DBs were present in this worktree.
- `rg --files -uu`: confirmed tracked hidden surfaces include `.mcp.json`, `.cursor/mcp.json`, `.env.mcp.example`, `.factory` validation artifacts, and `.gitignore`.

## Positive Controls Already Present

- Secrets and generated state are gitignored: `.gitignore:13-21` ignores Google credentials/tokens, GitHub/Maps/Gemini key files, config env files, and generic secret files; `.gitignore:42-43` ignores local memory/scheduler SQLite; `.gitignore:58` ignores `.inbox_index.sqlite3`.
- Private backend binds to loopback by default: `inbox_server.py:3939-3940` runs uvicorn on `127.0.0.1`; `mcp_server.py:148-151` and `inbox_mcp_readonly.py:83-87` do the same for MCP HTTP servers.
- Backend auth compares bearer or `X-API-Key` with `secrets.compare_digest`: `inbox_server.py:1313-1339`.
- MCP write tools are confirmation-gated in the registry: `tools_registry.py:52-79` injects `confirm`, and `tools_registry.py:41-43`/`tests/test_tools_registry.py:41-43` enforce that mutating registry tools require confirmation.
- The read-only MCP server filters non-readonly registry tools: `inbox_mcp_readonly.py:77`, `tools_registry.py:110-118`, `tests/test_tools_registry.py:46-53`.
- Agent-safe test mode exists: `inbox_test_mode.py:18-24` blocks live writes when `INBOX_TEST_MODE` is set, and `services.py` calls `_assert_live_write_allowed` in many external write functions.
- Prior local validation exists for token locking and AppleScript escaping: `.factory/validation/architecture-hardening/scrutiny/reviews/token-safety-applescript.json` records a pass for locked token writes and AppleScript sanitizer coverage at commit `dde493c`.

## Risk Register

### R1. Raw backend auth is optional even for mutating REST routes

Evidence:
- `README.md:50` describes auth as optional via `INBOX_SERVER_TOKEN`.
- `inbox_server.py:1317-1320` returns authorized when the token env var is unset.
- `tests/test_server.py:371-375` explicitly asserts `/health` is available when token is unset.
- Mutating routes are numerous: `inbox_server.py:1434`, `1489`, `1496`, `1819`, `1883`, `1962`, `1994`, `2028`, `2051`, `2548`, `2586`, `2612`, `2632`, `2940`, `2960`, `2978`.

Impact:
- On loopback this is acceptable for a trusted local TUI, but it becomes high risk if a reverse proxy, local malware, browser extension, or misconfigured agent can reach `localhost:9849`.
- Raw HTTP bypasses the MCP confirmation layer. A caller can send, delete, archive, upload, create tasks, edit calendars, or mutate docs/sheets without an explicit human-confirmation field.

Current controls:
- Loopback binding by default.
- Optional bearer token.
- MCP-facing registry confirmation for many tool paths.

Next safe work:
- Require `INBOX_SERVER_TOKEN` for all non-GET routes by default, with an explicit `INBOX_ALLOW_UNAUTH_LOCAL_WRITES=1` development escape hatch.
- Add tests proving missing auth rejects representative mutating endpoints while health/read endpoints retain the intended behavior.
- Update README/MCP setup to state unauthenticated backend mode is read-only or development-only.

### R2. Public MCP health can disclose backend state without MCP auth

Evidence:
- `mcp_gateway.py:48-58` allows `/health` through before checking `INBOX_MCP_TOKEN`.
- `mcp_gateway.py:61-82` health includes backend health, memory DB path, and `auth_enabled`.
- `inbox_server.py:1346-1357` backend health returns linked Gmail/Calendar/Drive/Sheets account names and GitHub configured status.
- `deploy/Caddyfile.example:3-11` and `deploy/Caddyfile.example:17-27` expose `/health` for full and read-only MCP hostnames.

Impact:
- If the MCP gateways are exposed publicly as documented, `/health` can leak local filesystem paths and account emails even when `/mcp` is token-protected.
- This weakens the "public read-only endpoint is safer" story because metadata still reveals personal infrastructure shape.

Current controls:
- `/mcp` itself is token-gated when `INBOX_MCP_TOKEN` is set.
- HTTP MCP servers bind loopback; Caddy is the external exposure point.

Next safe work:
- Split `/health` into unauthenticated liveness with no account/path payload and authenticated diagnostics with backend details.
- Add an MCP gateway test asserting public `/health` does not include account emails, backend detail, or memory DB paths.
- Update `MCP_SETUP.md` and `deploy/Caddyfile.example` to expose only the minimal health endpoint publicly.

### R3. MCP confirmation does not protect raw REST clients or local scripts

Evidence:
- `tools_registry.py:73-79` requires `confirm=True` only inside generated MCP handlers.
- `mcp_server.py:41-45` gates hand-written memory/note writes.
- Raw REST endpoints in `inbox_server.py` accept writes without a confirmation field, for example `/messages/send` at `inbox_server.py:1434-1447`, `/calendar/events` at `inbox_server.py:1819-1837`, `/drive/upload` at `inbox_server.py:2548-2574`, and `/docs/{document_id}/text` at `inbox_server.py:2978-2983`.
- `batch/batch-runner.sh:74-80` archives Gmail messages directly through `/gmail/batch-modify`.

Impact:
- Agents or scripts that target REST instead of MCP can mutate live personal data without the user-visible confirmation contract that MCP tools advertise.
- The docs present both REST and MCP as agent-accessible surfaces, so this is not just theoretical.

Current controls:
- Service-level `INBOX_TEST_MODE` blocks many live writes in tests.
- Backend token can restrict callers if configured.

Next safe work:
- Add server-side confirmation or preflight enforcement for mutating REST endpoints used by agents.
- Convert batch scripts to require `--confirm` for live runs and keep `--dry-run` as the default.
- Add tests that representative raw REST writes reject missing confirmation when called outside the TUI trust path.

### R4. Drive upload lacks the live-write guard used by other external writes

Evidence:
- `services.py:3864-3882` defines `drive_upload` and calls `drive_service.files().create(...)` without `_assert_live_write_allowed`.
- `inbox_server.py:2548-2574` exposes `/drive/upload` and calls `drive_upload`.
- `rg -n "_assert_live_write_allowed\\(" services.py` counted 44 guard occurrences, including Drive folder/delete at `services.py:3912-3949`, but not upload.
- `tests/test_drive.py:69-112` tests upload behavior with mocks but does not assert `INBOX_TEST_MODE` blocks upload.
- `tests/test_services.py:934-951` covers many extended live-write blockers, including Drive folder, but not Drive upload.

Impact:
- In `INBOX_TEST_MODE=1`, a test or local agent path can still reach a mocked or real Drive upload call if it hits `drive_upload`.
- This is the clearest concrete gap found in the live-write safety model.

Current controls:
- The MCP registry does not currently expose an upload tool.
- The endpoint still requires whatever backend auth policy is configured.

Next safe work:
- Add `_assert_live_write_allowed("upload Google Drive file")` at the start of `drive_upload`.
- Add a regression test in `tests/test_services.py` or `tests/test_drive.py` that `INBOX_TEST_MODE=1` blocks `drive_upload` before `MediaFileUpload` or the Drive client is touched.
- Add an API endpoint test for `/drive/upload` under `INBOX_TEST_MODE=1` if multipart test helpers are already available.

### R5. Scheduled message and follow-up state can trigger future live writes

Evidence:
- `scheduler.py:118-148` stores scheduled messages in `.inbox_scheduler.sqlite3`.
- `inbox_server.py:982-1036` sends due scheduled Gmail/iMessage messages in the background loop.
- `inbox_server.py:1179-1187` runs the scheduler loop every 30 seconds by default.
- `InboxServerRuntime.start_scheduler` defaults to `True` at `inbox_server.py:825-832`.
- `tools_registry.py:570-585` confirmation-gates schedule creation for MCP, but `inbox_server.py:2066-2076` raw REST schedule creation does not include confirmation.

Impact:
- A scheduled write is a delayed live mutation. The original confirmation context is not persisted in a way the scheduler can review at send time.
- A stale or accidental scheduled row can send later after the user has forgotten the original command.

Current controls:
- Under `INBOX_TEST_MODE`, the eventual send functions should block if the process still has that env var.
- Scheduled rows can be listed and cancelled.

Next safe work:
- Persist `created_by`, `confirmed_at`, and a human-readable preview for scheduled writes.
- Add a startup warning or block when pending scheduled sends exist and the backend is unauthenticated.
- Add a safe test around scheduler processing in `INBOX_TEST_MODE=1`.

### R6. Broad OAuth scopes plus default-account fallback increase blast radius

Evidence:
- `services.py:88-98` requests broad Google scopes: Gmail read/modify/send/settings, Calendar, Drive, Sheets, Docs, and Tasks.
- `google_account_resolution.py:24-33` defaults to `INBOX_DEFAULT_GOOGLE_ACCOUNT` or the first service key.
- `google_account_resolution.py:51-58`, `119-126`, `129-136`, and `149-157` resolve Gmail/Drive/Tasks/Calendar writes to a default account when no account is provided.
- `google_account_resolution.py:160-304` implements preflight payloads, but `inbox_server.py:3009-3020` exposes preflight as a separate GET endpoint rather than enforcing it on writes.

Impact:
- A missing `account` parameter can create/delete/update in the wrong Google account.
- A compromised token or backend grants a wide cross-product write surface.

Current controls:
- Per-account token files in `tokens/`.
- Account-specific service helpers and preflight endpoint exist.
- Docs warn about multi-account routing in `CLAUDE.md`.

Next safe work:
- Require explicit `account` on mutating Google endpoints unless `INBOX_DEFAULT_GOOGLE_ACCOUNT` is set and acknowledged.
- Tie confirmation payloads to a preflight result showing resolved account and destination.
- Add tests for "missing account rejects write" on high-risk endpoints: Drive, Docs, Sheets, Calendar, Tasks.

### R7. Privacy/local-first claim has optional cloud AI and Maps egress paths

Evidence:
- `README.md:24-25` claims local-first ML and no cloud dependencies.
- `README.md:169-174` says all data processing happens on-device.
- `services.py:3249-3264` configures `google.generativeai` from `GEMINI_API_KEY` or `gemini_api_key.txt`.
- `services.py:3270-3291` sends conversation text to Gemini summarization.
- `inbox_server.py:2197-2263` exposes Gemini summarize, smart reply, categorize, digest, and action-items endpoints.
- `services.py:3510-3522` reads Google Cloud/Maps keys and `services.py:3578-3582` calls the Google Distance Matrix API with origin/destination.

Impact:
- If keys are configured, personal messages, calendar/task summaries, and locations can leave the device.
- The current docs say Gemini is optional in `CLAUDE.md`, but the README privacy section is stronger than the code supports.

Current controls:
- Cloud calls require explicit key files/env vars.
- Local ML remains available.

Next safe work:
- Add a visible cloud-egress policy flag, for example `INBOX_ALLOW_CLOUD_AI=1`, and make cloud AI endpoints return 403 unless enabled.
- Label `/ai/gemini-*`, `/ai/digest`, `/ai/action-items`, and Maps endpoints as cloud egress in docs and OpenAPI descriptions.
- Add tests proving cloud endpoints are disabled by default when the new flag is unset.

### R8. Logs can contain personal data, paths, recipients, and locations

Evidence:
- `_format_log_context` in `services.py:139-147` only truncates long strings; it does not redact emails, locations, document IDs, message IDs, or file paths.
- `_log_service_failure` in `services.py:150-155` logs exceptions with that context.
- `services.py:1199` logs Gmail compose recipient and subject on failure.
- `services.py:3598` logs Maps origin and destination on failure.
- `inbox_server.py:1011-1032` logs scheduled send recipients/contact names.
- `ambient_notes.py:73-76` logs and prints a preview of captured ambient transcript/summary.
- Deploy examples write logs under `/tmp`: `deploy/com.inbox.backend.plist.example`, `deploy/com.inbox.mcp.plist.example`, `deploy/com.inbox.mcp-readonly.plist.example`, and `scripts/setup_inbox_mcp.sh:52-59`.

Impact:
- Logs can preserve sensitive recipients, calendar locations, note previews, and local filesystem paths outside the app's normal privacy boundary.
- `/tmp` service logs can be copied into debugging reports or read by local processes depending on host permissions.

Current controls:
- The logger truncates long string values.
- Token file contents are not printed by the reviewed paths.

Next safe work:
- Centralize log redaction for emails, tokens, addresses, message IDs, and local paths before calling logger.
- Default service logs to `~/Library/Logs/inbox` or another user-scoped directory with documented permissions.
- Add tests for `_format_log_context` redaction behavior.

### R9. Local generated databases store sensitive indexed content in repo root

Evidence:
- `memory_store.py:9-11` defaults to `.inbox_memory.sqlite3` in repo root.
- `scheduler.py:15-17` defaults to `.inbox_scheduler.sqlite3` in repo root and stores scheduled message text at `scheduler.py:70-80`.
- `message_index_store.py:12-15` defaults to `.inbox_index.sqlite3`; its `items` table stores sender, recipients, subject, snippet, body text, labels, and raw pointers at `message_index_store.py:100-120`.
- `.gitignore:42-43` and `.gitignore:58` ignore those DB files.

Impact:
- The ignore rules prevent accidental commits, but root-local databases are easy to copy with the repo, include in manual archives, or leave in multiple worktrees.
- The index DB can contain substantial message bodies and metadata, not just harmless cache state.

Current controls:
- `.gitignore` covers the generated DB names.
- `INBOX_MEMORY_DB` can override memory DB path through `mcp_gateway.py:26-29`; `INBOX_TEST_DATA_DIR` redirects some service paths under test mode.

Next safe work:
- Move runtime DB defaults to a user data directory such as `~/.local/share/inbox` or `~/Library/Application Support/inbox`.
- Add startup diagnostics that warn if runtime DBs live inside a git worktree.
- Document backup/cleanup and file-permission expectations.

### R10. Batch archive runner can mutate Gmail with brittle JSON/state handling

Evidence:
- `batch/batch-runner.sh:15-19` defaults to `MODE=archive`, `DRY_RUN=false`, and `PARALLEL=1`.
- `batch/batch-runner.sh:74-80` posts directly to `/gmail/batch-modify`.
- `batch/batch-runner.sh:78-79` interpolates `SERVER_TOKEN` and `thread_id` into a shell/curl command and JSON body.
- `batch/batch-runner.sh:92-101` rewrites the shared state file via `awk` and `mv`; parallel workers can race when `--parallel N` is used.

Impact:
- A malformed TSV row can produce invalid JSON or target unexpected input.
- Parallel runs can lose state updates.
- Live archive behavior is one flag away from a dry run, but dry run is not the default.

Current controls:
- Input/state/output files are separated; generated state/logs are ignored.
- Unsupported sources return an error.

Next safe work:
- Make `--dry-run` the default and require `--confirm-live` for archive mode.
- Use `jq -n --arg` or a small Python/HTTP client to build JSON safely.
- Add file locking around `archive-state.tsv` updates.

## Validation Candidates

Required queue validation:
- `git status --short`
- Actual result after report creation: exit 0 with `?? docs/overnight/`.
- Expected if a human or less-restricted runner stages/commits the report: exit 0 with no output.

Commit/blocker evidence:
- `git add docs/overnight/inbox-sym-120-risk-register.md && git diff --cached --stat`
- Actual result: failed before staging with `fatal: Unable to create '/Users/jwalinshah/projects/inbox/.git/worktrees/inbox-sym-120-risk-register/index.lock': Operation not permitted`.

Cheap safety commands for future implementation tasks:
- `INBOX_TEST_MODE=1 uv run pytest -m safe`
- Expected: pass, but narrow. Local evidence from `rg -n "pytestmark = pytest.mark.safe|@pytest.mark.safe" tests` found only `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py` marked safe.

- `INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py tests/test_mcp_gateway.py -q`
- Expected: pass. Covers the two currently safe-marked risk-control files.

- `INBOX_TEST_MODE=1 uv run pytest tests/test_services.py::test_test_mode_blocks_extended_live_writes tests/test_drive.py::TestDriveUpload -q`
- Expected today: likely pass without proving Drive upload blocking, because `TestDriveUpload` does not set `INBOX_TEST_MODE`. After fixing R4, add a new assertion that currently would fail: `drive_upload` should raise `LiveWriteBlocked` before touching Drive.

- `uv run ruff check .`
- Expected: candidate pass based on repo docs and prior `.factory/validation/architecture-hardening/scrutiny/synthesis.json`.

- `uv run pyright`
- Expected: candidate pass based on repo docs and prior `.factory/validation/architecture-hardening/scrutiny/synthesis.json`.

- `uv run bandit -c pyproject.toml -r .`
- Expected: limited signal. `pyproject.toml` skips `B404`, `B603`, and `B607`, which are relevant because this repo intentionally uses subprocess/AppleScript.

## Independently Grabbable Next Tasks

1. Server-side write confirmation for REST mutators
   - Acceptance criteria:
     - Representative raw REST mutators reject missing confirmation or auth according to a documented policy.
     - TUI-owned local flows still work through a clear trust path.
     - README/CLAUDE/MCP docs explain which clients may call REST writes.
   - Validation:
     - `INBOX_TEST_MODE=1 uv run pytest tests/test_server.py -q`
     - `uv run ruff check inbox_server.py tests/test_server.py`

2. Close the Drive upload live-write gap
   - Acceptance criteria:
     - `drive_upload` calls `_assert_live_write_allowed` before `MediaFileUpload` or Drive client calls.
     - A regression test proves `INBOX_TEST_MODE=1` blocks upload.
     - Existing mocked upload tests still pass outside test mode.
   - Validation:
     - `INBOX_TEST_MODE=1 uv run pytest tests/test_drive.py tests/test_services.py::test_test_mode_blocks_extended_live_writes -q`
     - `uv run ruff check services.py tests/test_drive.py tests/test_services.py`

3. Harden public MCP health
   - Acceptance criteria:
     - Unauthenticated `/health` returns only liveness/mode/auth-enabled, not backend account emails, local paths, or backend error details.
     - Authenticated diagnostics remain available through a separate endpoint or header-gated mode.
     - Caddy/deploy docs describe the public health payload.
   - Validation:
     - `INBOX_TEST_MODE=1 uv run pytest tests/test_mcp_gateway.py -q`
     - `uv run ruff check mcp_gateway.py tests/test_mcp_gateway.py`

4. Require explicit account or preflight-bound confirmation for Google writes
   - Acceptance criteria:
     - High-risk Drive/Docs/Sheets/Calendar/Tasks writes either require `account` or include a confirmed preflight token/object with resolved account and destination.
     - Tests cover missing-account rejection and explicit-account success.
     - Docs show the safe call sequence.
   - Validation:
     - `INBOX_TEST_MODE=1 uv run pytest tests/test_server.py tests/test_drive.py tests/test_calendar.py tests/test_gmail_actions.py -q`
     - `uv run pyright`

5. Redact logs and relocate runtime DBs
   - Acceptance criteria:
     - `_format_log_context` redacts emails, tokens, addresses, paths, and IDs in common contexts.
     - Runtime DB defaults move outside repo root or warn when inside a git worktree.
     - Deploy examples write logs to a user-scoped directory.
   - Validation:
     - `INBOX_TEST_MODE=1 uv run pytest tests/test_services.py tests/test_memory_store.py tests/test_message_index_store.py -q`
     - `uv run ruff check services.py memory_store.py message_index_store.py scheduler.py`

## Non-goals

- No fixes were implemented in this queue item.
- No live Gmail, Calendar, Drive, Docs, Sheets, Tasks, GitHub, Maps, Gemini, iMessage, Notes, Reminders, WhatsApp, audio, notification, or Obsidian operations were run.
- No dev server was started.
- No browser QA was run.
- No generated runtime DBs, token files, local env files, or batch state files were created.
- No external trackers were updated.
- No PR was opened.

## Unknowns

- Whether production/daily-driver runs always set `INBOX_SERVER_TOKEN` and `INBOX_MCP_TOKEN`.
- Whether the raw REST API is considered a trusted local-only implementation detail or an agent-supported public contract.
- Whether cloud Gemini/Maps endpoints are actively used or legacy features.
- Whether runtime DBs in the primary checkout already contain sensitive indexed content; this worktree had no ignored DB files at audit time.
- Whether Caddy/deployment examples are copied verbatim into a live host.
- Whether scheduled messages/followups have existing rows in the primary checkout.

## Decisions

- Treated MCP confirmation as a useful control but not sufficient for the raw FastAPI backend.
- Treated `INBOX_TEST_MODE` coverage as a safety boundary because `docs/TESTING_FOR_AGENTS.md` instructs agents to rely on it.
- Did not run pytest, lint, typecheck, servers, or cloud/local integration commands; the queue validation command is `git status --short`, and this task is an audit report.
- Did not inspect or copy any ignored secrets or generated personal-data DBs.
- Did not create a local commit because the linked-worktree git administrative directory is outside the writable sandbox.
