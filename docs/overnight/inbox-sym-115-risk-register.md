# inbox-sym-115 Risk Register Audit

Queue item: `inbox-sym-115-risk-register`
Repo path: `/Users/jwalinshah/projects/agent-stack/.agent-stack-worktrees/2026-05-07-overnight-marathon/inbox-sym-115-risk-register`
Audit date: 2026-05-07
Focus area: `risk-register`

## Scope And State

This is a read-only risk audit of the Inbox personal assistant repo. Product code, generated data, live provider calls, deploys, pushes, and PR creation were out of scope. The only intended repo write is this report.

Observed repo purpose:

- `README.md` describes a privacy-first Python/Textual terminal inbox that consolidates iMessage, Gmail, Google Calendar, Sheets, Notes, Reminders, GitHub notifications, and Drive through a local FastAPI backend and optional MCP access.
- `CLAUDE.md` describes the same client-server split plus worktree routing: primary checkout on port `9849`, dev worktrees on `9850+`, and shared macOS personal-data stores across worktrees.
- `pyproject.toml` defines a Python `>=3.12,<3.15` app with FastAPI, Google APIs, MCP, MLX, Textual, sounddevice, ruff, pyright, pytest, coverage, Hypothesis, and Bandit.

Branch and dirty state observations:

- `git branch --show-current` -> `codex/goal-inbox-sym-115-risk-register`.
- `git rev-parse HEAD` -> `2805b8400519da188ca7d3f6e39b19a8ca42b05a`.
- Initial `git status --short` returned no output, so the worktree started clean.
- `rg --files ... tokens credentials.json config/inbox.env ...` found only `.gitignore` and `.mcp.json`; no live token files, `credentials.json`, or `config/inbox.env` were present in the worktree.
- `git ls-files | rg "(credentials\.json|token\.json|tokens/|github_token|google_maps_key|gemini_api_key|config/inbox\.env|\.env|\.inbox_.*sqlite|batch/.*state)"` returned only `.env.mcp.example` and `config/inbox.env.example`, so secret paths are ignored but examples are tracked.

Command notes:

- `llm-tldr tree .` showed the repo has a flat Python service/TUI layout, `tests/`, `scripts/`, `deploy/`, `config/`, `modes/`, and one existing docs file.
- `rg -n "pytest\.mark\.(safe|integration|local_data|live_write|slow)|pytestmark" tests` found only `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py` marked `safe`.
- `INBOX_TEST_MODE=1 uv run pytest -m safe --collect-only -q` failed before collection because the default uv cache at `/Users/jwalinshah/.cache/uv` is outside the sandbox.
- `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe --collect-only -q` created an ignored `.venv/`, then failed because network access is unavailable while resolving `mlx-whisper==0.4.3`.
- Cleanup of the generated `.venv/` with `rm -rf .venv` was blocked by policy. It is ignored by `.gitignore` and was 68K when observed with `du -sh .venv`.

## Risk Register

### 1. Raw REST Write Surface Is Broad And Not Confirmation-Gated

Risk: MCP write tools are confirmation-gated, but the underlying FastAPI endpoints mutate once HTTP auth passes. Any local client, misrouted MCP backend, browser automation, or script with access to the backend can invoke writes without `confirm=True`.

Evidence:

- `tools_registry.py:67-78` enforces `confirm=True` inside MCP handler generation.
- `tools_registry.py:157-164`, `tools_registry.py:250-256`, `tools_registry.py:807-812` describe confirmation-gated MCP tools such as Gmail reply, archive, and Docs text insert.
- `inbox_server.py:1434-1450` sends iMessage or Gmail from `/messages/send` with no request-level confirmation.
- `inbox_server.py:1489-1552` exposes Gmail archive, delete, unsubscribe, star, read, and unread endpoints directly.
- `inbox_server.py:1819-1892` exposes calendar create, quick-create, update, and delete directly.
- `inbox_server.py:2548-2590`, `inbox_server.py:2612-2761`, and `inbox_server.py:2940-2983` expose Drive upload/folder/delete, Sheets writes, and Docs create/delete/insert directly.

Why it matters:

The user-facing safety model is split by transport. MCP callers see confirmation prompts, but the REST API and TUI path do not share the same gate. This is especially risky because `README.md` and `CLAUDE.md` advertise agents hitting the local server directly.

Next safe work:

- Add a shared write-policy layer at the FastAPI boundary for all mutating endpoints.
- Require either explicit `confirm` metadata, a local interactive TUI origin, or a stronger internal-only credential for raw REST mutations.
- Add endpoint tests proving direct REST write endpoints reject missing confirmation in agent-safe mode.

### 2. Backend And MCP Auth Fail Open When Tokens Are Unset

Risk: Both the private backend and MCP gateway allow unauthenticated access when their token env vars are empty. This is convenient for local dev, but dangerous if a launchd/systemd/Caddy/ngrok path is exposed before env setup is complete.

Evidence:

- `inbox_server.py:1313-1320` returns authorized when `INBOX_SERVER_TOKEN` is unset.
- `mcp_gateway.py:32-45` returns authorized when `INBOX_MCP_TOKEN` is unset.
- `mcp_gateway.py:48-58` exempts `/health` from public auth.
- `config/inbox.env.example` contains placeholder tokens but real `config/inbox.env` is absent in this worktree.
- `MCP_SETUP.md` recommends two different tokens and warns the backend should never be internet-facing.
- `deploy/Caddyfile.example` exposes `/health` and `/mcp` for both full and read-only MCP hostnames.

Why it matters:

If the full MCP HTTP gateway is exposed with missing `INBOX_MCP_TOKEN`, every registered full MCP tool is callable. If the private backend is exposed with missing `INBOX_SERVER_TOKEN`, raw REST write endpoints are callable.

Next safe work:

- Make HTTP MCP fail closed by default unless `INBOX_MCP_ALLOW_UNAUTH_LOCAL=1` is explicitly set.
- Make backend startup print or expose a red warning when auth is disabled.
- Keep `/health` public only for read-only status, and redact backend details from public health responses.

### 3. Live-Write Guard Coverage Has Concrete Gaps

Risk: `INBOX_TEST_MODE=1` blocks many representative writes, but not all mutating service functions call `_assert_live_write_allowed`.

Evidence:

- `services.py:114-119` centralizes `_assert_live_write_allowed`.
- `tests/test_services.py:909-951` tests representative live-write blocking.
- `rg -n "def (drive_upload|sheets_rename_sheet|sheets_format|sheets_copy_to|docs_insert_text|calendar_rsvp_event)|_assert_live_write_allowed" services.py` showed guard calls around many writes, but the following mutators have definitions without nearby guards:
  - `services.py:3864-3909` `drive_upload`
  - `services.py:4315-4338` `sheets_rename_sheet`
  - `services.py:4341-4355` `sheets_format`
  - `services.py:4358-4388` `sheets_copy_to`
  - `services.py:4476-4495` `docs_insert_text`
  - `services.py:6236-6259` `calendar_rsvp_event`
- `tests/test_drive.py:69-112` exercises `drive_upload`, but there is no `INBOX_TEST_MODE` block assertion for that path.

Why it matters:

Agent-safe validation can accidentally hit a live provider if a test or endpoint touches one of these uncovered helpers. Some gaps are direct user data writes, including file upload, raw spreadsheet batch updates, document insertion, and RSVP mutation.

Next safe work:

- Add `_assert_live_write_allowed(...)` to every mutating service helper listed above.
- Add a parametrized test that enumerates all mutators and proves they raise `LiveWriteBlocked` before touching mock provider chains.
- Add a grep/check script that fails if known write verbs are introduced without a live-write guard.

### 4. OAuth Scope Blast Radius Is High

Risk: One Google OAuth token set carries broad read/write access across Gmail, Calendar, Drive, Sheets, Docs, and Tasks. The same token directory powers local UI, backend, and MCP flows.

Evidence:

- `services.py:88-98` includes `gmail.readonly`, `gmail.modify`, `gmail.send`, `gmail.settings.basic`, full `calendar`, full `drive`, full `spreadsheets`, full `documents`, and `tasks`.
- `services.py:330-416` loads every token in `tokens/` and builds service clients for all providers.
- `services.py:341-358` auto-reauths legacy tokens missing scopes when `credentials.json` exists.
- `CLAUDE.md:265-272` documents multi-account tokens and fallback write routing.
- `.gitignore` excludes `credentials.json`, `token.json`, `tokens/`, `github_token.txt`, `google_maps_key.txt`, and `gemini_api_key.txt`.

Why it matters:

A leaked token, exposed gateway, or wrong account selection has full cross-product impact. The app needs a different risk posture for read-only agents, local trusted TUI usage, and remote write-capable clients.

Next safe work:

- Split read-only and write-capable OAuth profiles.
- Require explicit reauth for full Drive/Docs/Sheets write scopes.
- Store token metadata with scope class and refuse write endpoints when only read profile is active.

### 5. Primary-Vs-Dev Routing Can Mutate The Daily Driver

Risk: Docs warn that primary runs at `9849` and dev worktrees run at `9850+`, but repo-local MCP configs still point to `9849` by default. Misconfigured agent clients can appear to test a dev branch while mutating the primary daily-driver backend.

Evidence:

- `CLAUDE.md:16-21` says primary checkout `~/projects/inbox` on `9849` is the daily driver.
- `CLAUDE.md:54-56` warns macOS data-source paths are shared across worktrees and MCP defaults to `9849`.
- `.mcp.json` points both `inbox` and `inbox-readonly` at `http://127.0.0.1:9849`.
- `config/codex.inbox.example.toml` also defaults to `9849`, with dev override shown only as a commented example.
- `dev.sh` correctly sets `INBOX_SERVER_PORT=9850` and `INBOX_SERVER_URL=http://127.0.0.1:9850`.

Why it matters:

Wrong-port mutation is a credible failure mode already documented in `MCP_SETUP.md`. It is worse when raw REST writes are not confirmation-gated.

Next safe work:

- Add `/health` fields for repo root, branch, port, and `INBOX_TEST_MODE`.
- Add a client-side startup check that refuses writes when `cwd` and `INBOX_SERVER_URL` do not match the expected worktree.
- Provide generated per-worktree MCP config instead of repo-default `9849` examples for active development.

### 6. Local Personal Data Is Copied Into Plaintext App Stores

Risk: The app reads sensitive local stores in read-only mode, but also creates its own plaintext caches and notes that can contain message bodies, contact details, commitments, and transcripts.

Evidence:

- `services.py:67-80` resolves iMessage, Notes, and Reminders DBs under `~/Library/...` unless `INBOX_TEST_MODE` redirects paths.
- `contacts.py:38-75` reads AddressBook SQLite files directly with `mode=ro`.
- `message_sync.py:452-469` reads iMessage messages from `chat.db` in `mode=ro`.
- `message_index_store.py:100-120` stores `sender`, `recipients_json`, `subject`, `snippet`, and full `body_text` in `.inbox_index.sqlite3`.
- `memory_store.py:9-39` creates `.inbox_memory.sqlite3` in the repo by default.
- `ambient_notes.py:14-38` writes daily notes under `~/vault/daily/`.

Why it matters:

The repo-level `.gitignore` prevents accidental commits, but the local artifacts remain sensitive. A backup, agent file read, prompt, or support bundle can leak raw message bodies and transcripts.

Next safe work:

- Add a data-retention doc with exact local files, plaintext fields, and cleanup commands.
- Add optional redaction for indexed body text and memory entries.
- Add a health/status endpoint that reports cache locations without revealing sensitive content.

### 7. Ambient Listening And Dictation Have Permission And Data-Leak Risks

Risk: Ambient capture reads microphone input and writes transcripts/summaries to disk. Dictation injects recognized text into the current macOS focus using CGEvent. These are high-trust local automations with limited guardrails at the REST boundary.

Evidence:

- `services.py:4525-4537` configures MLX Whisper, whisper-stream paths, sample rate, chunk length, and silence threshold.
- `services.py:4613-4620` starts ambient capture and flush threads.
- `services.py:4628-4696` records audio through `sounddevice`, transcribes it, and calls the note writer.
- `services.py:4702-4714` injects typed text via Quartz CGEvent.
- `services.py:4750-4812` starts `whisper-stream` and types new transcript segments into the focused app.
- `inbox_server.py:3047-3113` exposes `/ambient/start`, `/ambient/stop`, `/dictation/start`, and `/dictation/stop`.
- `inbox_server.py:1249-1267` can auto-start ambient listening when voice config enables it, unless `INBOX_DISABLE_AMBIENT` is set.
- `services.py:6090-6118` persists voice config under `~/.config/inbox/voice.json`.

Why it matters:

Accidental remote/local invocation can start microphone capture or keyboard injection. The persisted transcript and vault notes can include private conversations.

Next safe work:

- Require explicit local confirmation for ambient/dictation start endpoints.
- Include running state and last-start origin in health/status.
- Add tests ensuring `INBOX_TEST_MODE` blocks ambient/dictation start and voice config mutations unless explicitly opted in.

### 8. Bulk Helper Scripts Can Mutate Without Shared Auth/Policy

Risk: Several scripts directly target `http://localhost:9849`; some do not pass `INBOX_SERVER_TOKEN`, and some perform bulk archive/unsubscribe workflows after only a terminal prompt.

Evidence:

- `batch/batch-runner.sh` reads `INBOX_SERVER_URL` and `INBOX_SERVER_TOKEN`, supports `--dry-run`, and posts `/gmail/batch-modify`.
- `unsubscribe_bulk.py` hardcodes `http://localhost:9849` and posts `/messages/gmail/bulk-unsubscribe` without token handling.
- `unsubscribe_interactive.py` hardcodes `http://localhost:9849` and posts individual unsubscribe endpoints without token handling.
- `unsubscribe_all_newsletters.py` hardcodes `http://localhost:9849`, scans up to 500 conversations, then batches `/messages/gmail/bulk-unsubscribe`.
- `organize_inbox.py` uses the first Gmail account returned by `google_auth_all()` rather than `INBOX_DEFAULT_GOOGLE_ACCOUNT`.

Why it matters:

Scripts either fail against an authenticated backend or succeed against an unauthenticated/misconfigured backend. They bypass MCP confirmation and can mutate the wrong account if the first token is not the intended account.

Next safe work:

- Convert scripts to `InboxClient`, including token and URL handling.
- Make dry-run the default for bulk scripts.
- Require account display and typed confirmation that includes account plus operation count.

### 9. Deployment And Logs Expose Operational Details

Risk: Deployment examples are helpful but expose health publicly, source env files through shell, and write logs to `/tmp`. Errors may include account names, paths, provider IDs, and operational traces.

Evidence:

- `deploy/Caddyfile.example` exposes `/health` and `/mcp` for full and read-only hostnames.
- `mcp_gateway.py:61-82` health includes backend health, memory DB path, and whether public auth is enabled.
- `deploy/com.inbox.backend.plist.example`, `deploy/com.inbox.mcp.plist.example`, and `deploy/com.inbox.mcp-readonly.plist.example` use `source config/inbox.env` through `/bin/bash -lc`.
- The launchd plists log to `/tmp/inbox-*.out.log` and `/tmp/inbox-*.err.log`.
- `scripts/setup_inbox_mcp.sh` installs all three launch agents and starts them with `launchctl load`.

Why it matters:

Public health can reveal filesystem layout and backend state. `/tmp` logs may be readable depending on host policy and can collect sensitive traces over time.

Next safe work:

- Split public health from private diagnostics.
- Add log redaction and log rotation guidance.
- Prefer system service environment mechanisms over shell-sourcing env files where possible.

### 10. External Compute Retry Script Is Out Of Band

Risk: `oci_retry.sh` is unrelated to inbox runtime and can launch OCI compute instances in an infinite loop with hardcoded compartment, subnet, image, public IP, and SSH key path.

Evidence:

- `oci_retry.sh` loops forever until `oci compute instance launch` succeeds.
- It requests `VM.Standard.A1.Flex`, 4 OCPUs, 24 GB RAM, 200 GB boot volume, and public IP.
- It logs to `/Users/jwalinshah/projects/inbox/oci_retry.log`.

Why it matters:

This is a cost/external-service risk living in a personal inbox repo. It is not protected by the app's auth, test-mode, or confirmation conventions.

Next safe work:

- Move it out of the repo or quarantine it under a clearly labeled manual-ops directory.
- Add an explicit prompt/confirmation and max attempt count.
- Document provider, region, expected cost, and stop conditions.

## Stale Or Weak Assumptions

- `README.md` says Python 3.10+ is required, but `pyproject.toml` requires `>=3.12,<3.15`.
- `MCP_V1_PLAN.md` says write tools are confirmation-gated, which is true for MCP tools but not for raw REST endpoints or TUI/client methods.
- `README.md` says all data processing happens on-device, but the repo also uses Google APIs, GitHub REST, optional Google Maps, and optional Gemini.
- `docs/TESTING_FOR_AGENTS.md` recommends `INBOX_TEST_MODE=1 uv run pytest -m safe`, but only two test modules are marked `safe` today.
- `CLAUDE.md` says organization does not archive/delete, but adjacent scripts such as `unsubscribe_all_newsletters.py` explicitly bulk unsubscribe and archive.
- The read-only MCP surface filters the shared registry by `readonly=True`, but public health can still disclose backend and memory DB information.

## Validation Surface

Observed available validation commands:

- Required queue validation: `git status --short`.
- Agent-safe test loop in `docs/TESTING_FOR_AGENTS.md`: `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, `uv run pyright`.
- Full default pytest command from `pyproject.toml`: `uv run pytest`, with coverage addopts.
- Lint/type commands in `README.md` and `CLAUDE.md`: `uv run ruff check --fix .`, `uv run pyright`.
- Security scanner dependency is present in `pyproject.toml` as `bandit`; Bandit config skips several subprocess/assert-related rules.

Validation blockers observed:

- `INBOX_TEST_MODE=1 uv run pytest -m safe --collect-only -q` failed because uv tried to use `/Users/jwalinshah/.cache/uv`, which is outside the sandbox.
- `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe --collect-only -q` failed because dependencies were not cached and network is unavailable for downloading `mlx-whisper`.
- The second `uv` attempt created an ignored `.venv/`; cleanup was blocked by command policy.

Exact validation command candidates:

- `git status --short` should pass locally and is the only required queue validation.
- `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe -q` is expected to fail in this worker until dependencies are already cached or network is available.
- `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py tests/test_mcp_gateway.py -q` is the cheapest current safe-test candidate after dependency resolution.
- `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .` is expected to be a useful lint command after dependency resolution.
- `UV_CACHE_DIR=/tmp/uv-cache uv run pyright` is expected to be useful after dependency resolution, but may surface existing type debt because the repo uses many dynamic provider clients.

## Next Grabbable Tasks

### Task 1: Add Endpoint-Level Write Policy

Acceptance criteria:

- All FastAPI mutating endpoints require explicit confirmation or an approved local trusted origin.
- MCP confirmation and REST confirmation use one shared policy helper.
- Tests prove direct calls to Gmail, calendar, reminders, Drive, Sheets, Docs, Tasks, ambient/dictation, notifications, and GitHub write endpoints reject missing confirmation.

Validation:

- `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_server.py tests/test_mcp_gateway.py -q`
- `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .`

### Task 2: Close Live-Write Guard Gaps

Acceptance criteria:

- Add `_assert_live_write_allowed` to `drive_upload`, `sheets_rename_sheet`, `sheets_format`, `sheets_copy_to`, `docs_insert_text`, and `calendar_rsvp_event`.
- Add parametrized tests that each function raises `LiveWriteBlocked` before touching provider mocks when `INBOX_TEST_MODE=1`.
- Add a grep-based test or static test listing known mutators.

Validation:

- `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_services.py tests/test_drive.py tests/test_calendar.py -q`

### Task 3: Harden HTTP MCP And Health Exposure

Acceptance criteria:

- HTTP MCP fails closed when `INBOX_MCP_TOKEN` is unset unless an explicit local-dev env var is set.
- Public health no longer exposes memory DB path or private backend error details.
- Docs and examples explain fail-closed behavior and local dev override.

Validation:

- `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_mcp_gateway.py -q`
- `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check mcp_gateway.py mcp_server.py inbox_mcp_readonly.py`

### Task 4: Make Agent-Safe Validation Boring

Acceptance criteria:

- Expand `pytest.mark.safe` coverage or add a curated safe test target file/list.
- Document `UV_CACHE_DIR=/tmp/uv-cache` for sandboxed workers.
- Add a no-network collect smoke command that does not create `.venv` in restricted environments unless explicitly requested.

Validation:

- `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe --collect-only -q`
- `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe -q`

### Task 5: Normalize Bulk Scripts Through The Client

Acceptance criteria:

- `unsubscribe_bulk.py`, `unsubscribe_interactive.py`, and `unsubscribe_all_newsletters.py` use `InboxClient` or shared URL/token config.
- Dry-run is default for all bulk operations.
- Confirmation includes account, operation, number of messages, and whether archive/trash/unsubscribe will occur.

Validation:

- `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_client.py tests/test_gmail_actions.py -q`
- Manual dry-run only; no live provider calls.

## Non-Goals

- No product code edits.
- No live Gmail, Calendar, Drive, Docs, Sheets, Tasks, iMessage, Reminders, GitHub, Maps, microphone, desktop notification, or external compute calls.
- No secrets, token files, or local personal data stores were opened.
- No deploys, service starts, pushes, PRs, or external tracker updates.
- No attempt to resolve all docs-claim drift; only risk-relevant stale assumptions were recorded.

## Unknowns

- Whether the daily-driver host currently has `INBOX_SERVER_TOKEN` or `INBOX_MCP_TOKEN` configured.
- Whether the HTTP MCP gateway is exposed through Caddy/ngrok or only used locally.
- Whether user intent is to keep raw REST endpoints friendly for local TUI use or to make every write confirmation-gated.
- Whether `.inbox_index.sqlite3`, `.inbox_memory.sqlite3`, vault notes, and `/tmp/inbox-*.log` are backed up or synced elsewhere.
- Whether broad Google scopes are required for near-term workflows or can be split now.
- Whether the ignored `.venv/` created by the validation attempt should be cleaned manually outside the policy-restricted worker.
