# inbox-sym-117 risk-register audit

Queue item: `inbox-sym-117-risk-register`
Repo: `inbox-sym-117`
Branch: `codex/goal-inbox-sym-117-risk-register`
Focus area: risk-register
Audit date: 2026-05-07

## Executive summary

`inbox-sym-117` is a local-first Python inbox/control-plane application. It exposes a FastAPI backend, a Textual TUI, local and HTTP MCP gateways, scheduler workflows, Google/Gmail/Calendar/Drive/Sheets/Docs/Tasks integrations, macOS Messages/Notes/Reminders/Accessibility integrations, GitHub notification tooling, local ML, optional Gemini AI calls, and audio/dictation workflows.

The largest risk is not a single secret in the checkout. It is the combination of:

- broad local and cloud write authority,
- optional bearer-token auth,
- many REST write endpoints,
- MCP confirmation gates that do not cover direct REST/TUI paths,
- service-level `INBOX_TEST_MODE` write guards that are present but not exhaustive,
- privacy docs that still describe the AI path as local-only while Gemini endpoints can send inbox content to Google when a Gemini key is configured.

No product code was changed during this audit. The only intended change is this report.

## Repo purpose and state

Purpose from local docs:

- [README.md](../../README.md) describes a privacy-first terminal UI consolidating iMessage, Gmail, Calendar, Sheets, Notes, Reminders, GitHub, and Drive.
- [CLAUDE.md](../../CLAUDE.md) describes the client-server split: `services.py` for data access, `inbox_server.py` for the FastAPI backend, `inbox_client.py` for HTTP clients, MCP entrypoints, scheduler, local SQLite stores, and token files.
- [MCP_SETUP.md](../../MCP_SETUP.md) describes a private backend on `127.0.0.1:9849`, a full MCP HTTP gateway, and a read-only MCP HTTP gateway.

Observed git state:

- `git status --short --branch` before writing this report: `## codex/goal-inbox-sym-117-risk-register`; no tracked or untracked changes were present.
- `git rev-parse HEAD`: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`.
- `git log --oneline -5` shows HEAD as `2805b84 Merge pull request #34 from jwalin-shah/codex/SYM-9-indexed-defaults`.
- `git remote -v` points to `https://github.com/jwalin-shah/inbox.git`.
- `rtk read items/inbox-sym-117-risk-register/ISSUE.md` failed with `No such file or directory`; the queue item text in the prompt was used as the local work contract.
- `fd -H 'ISSUE\.md$|inbox-sym-117-risk-register' .` found no local issue file.

## Local evidence map

Repo shape and hidden/local state:

- `llm-tldr tree .` shows a flat Python app with `services.py`, `inbox_server.py`, `inbox.py`, MCP entrypoints, `tests/`, `deploy/`, `scripts/`, `modes/`, and docs.
- `fd -H -t f` shows hidden operational artifacts under `.factory/`, repo-local `.mcp.json`, `.cursor/mcp.json`, `.env.mcp.example`, `.pre-commit-config.yaml`, and `.tldrignore`.
- `fd -H '^(credentials\.json|token\.json|tokens|github_token\.txt|google_maps_key\.txt|gemini_api_key\.txt|inbox\.env|\.env)$' .` produced no output, so the obvious secret/token files were not present in this worktree.
- `fd -t f . docs/overnight` failed because `docs/overnight` did not exist before this report.

Credentials and auth:

- [.gitignore](../../.gitignore) ignores `credentials.json`, `token.json`, `tokens/`, `github_token.txt`, `google_maps_key.txt`, `gemini_api_key.txt`, `config/inbox.env`, `.env`, `.env.local`, `*.key`, and `*.secret`.
- [config/inbox.env.example](../../config/inbox.env.example) defines `INBOX_SERVER_TOKEN`, `INBOX_MCP_TOKEN`, and optional `INBOX_MEMORY_DB`.
- [.env.mcp.example](../../.env.mcp.example) leaves `INBOX_SERVER_TOKEN=` blank and sets a placeholder `INBOX_MCP_TOKEN`.
- [.mcp.json](../../.mcp.json) and [.cursor/mcp.json](../../.cursor/mcp.json) both point local MCP clients at `http://127.0.0.1:9849` and pass `${INBOX_SERVER_TOKEN}`.
- [inbox_server.py](../../inbox_server.py) has `AUTH_TOKEN_ENV = "INBOX_SERVER_TOKEN"` and `_is_authorized()` returns `True` when the token env var is unset.
- [mcp_gateway.py](../../mcp_gateway.py) has `MCP_TOKEN_ENV = "INBOX_MCP_TOKEN"` and `_is_publicly_authorized()` returns `True` when the public MCP token env var is unset.
- [tests/test_server.py](../../tests/test_server.py) verifies backend auth is not required when `INBOX_SERVER_TOKEN` is unset and is required when set.
- [tests/test_mcp_gateway.py](../../tests/test_mcp_gateway.py) verifies MCP token rejection only when `INBOX_MCP_TOKEN` is set; health remains public.

Write surfaces:

- `rg -n "^@app\.(post|put|patch|delete)" inbox_server.py` found many mutating routes: messages, Gmail archive/delete/unsubscribe/read state, calendar CRUD, reminders, tasks, scheduled messages, followups, Drive, Sheets, Docs, ambient/dictation, accounts, notifications, workflow creation, index sync, and memory extraction.
- [services.py](../../services.py) defines `_assert_live_write_allowed()` and calls it on many mutators.
- `rg -n "_assert_live_write_allowed" services.py` shows guards for representative Gmail, iMessage, Calendar, Reminders, Tasks, Drive folder/delete, Sheets create/value/tab add/delete, Docs create/delete, GitHub notification mutation, desktop notifications, WhatsApp, and attendee changes.
- [tests/test_services.py](../../tests/test_services.py) contains representative `INBOX_TEST_MODE` tests, but the tested set is not exhaustive.
- [tools_registry.py](../../tools_registry.py) confirms all registered mutating MCP tools require `confirm=True`, and [tests/test_tools_registry.py](../../tests/test_tools_registry.py) asserts all non-readonly MCP registry tools are confirmation-gated.

External services and local data:

- [services.py](../../services.py) reads local macOS personal-data SQLite stores for iMessage, Notes, Reminders, and AddressBook.
- [services.py](../../services.py) uses broad Google scopes: Gmail read/modify/send/settings, Calendar, Drive, Sheets, Docs, and Tasks.
- [services.py](../../services.py) reads `github_token.txt` or `gh auth token`, then calls `https://api.github.com`.
- [services.py](../../services.py) reads `google_maps_key.txt` or map-related env vars for location/travel APIs.
- [services.py](../../services.py) reads `gemini_api_key.txt` or `GEMINI_API_KEY`, then uses `google.generativeai`.
- [ambient_notes.py](../../ambient_notes.py) writes raw ambient transcripts into `~/vault/daily/YYYY-MM-DD.md`.
- [inbox_server.py](../../inbox_server.py) can start ambient listening and dictation via REST endpoints.
- [inbox_server.py](../../inbox_server.py) can auto-start ambient listening on server startup if voice config enables `ambient_autostart`.

Deployment and operations:

- [inbox_server.py](../../inbox_server.py), [mcp_server.py](../../mcp_server.py), and [inbox_mcp_readonly.py](../../inbox_mcp_readonly.py) bind uvicorn to `127.0.0.1`.
- [deploy/Caddyfile.example](../../deploy/Caddyfile.example) exposes only `/health` and `/mcp` for full and readonly MCP hostnames.
- [deploy/inbox-backend.service.example](../../deploy/inbox-backend.service.example), [deploy/inbox-mcp.service.example](../../deploy/inbox-mcp.service.example), and [deploy/inbox-mcp-readonly.service.example](../../deploy/inbox-mcp-readonly.service.example) hardcode `/Users/jwalinshah/projects/inbox` and `config/inbox.env`.
- [deploy/com.inbox.backend.plist.example](../../deploy/com.inbox.backend.plist.example), [deploy/com.inbox.mcp.plist.example](../../deploy/com.inbox.mcp.plist.example), and [deploy/com.inbox.mcp-readonly.plist.example](../../deploy/com.inbox.mcp-readonly.plist.example) source `config/inbox.env` through `bash -lc` and write logs under `/tmp`.
- [scripts/setup_inbox_mcp.sh](../../scripts/setup_inbox_mcp.sh) creates `config/inbox.env` with `chmod 600`, copies launch agents, unloads and loads them, and reports `/tmp` log paths.

Validation surface:

- [docs/TESTING_FOR_AGENTS.md](../TESTING_FOR_AGENTS.md) says safe agent commands are `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, and `uv run pyright`.
- [pyproject.toml](../../pyproject.toml) defines pytest markers `safe`, `integration`, `local_data`, `slow`, and `live_write`; default pytest includes coverage.
- [.pre-commit-config.yaml](../../.pre-commit-config.yaml) has ruff, ruff-format, trailing whitespace, end-of-file fixer, check-yaml, check-added-large-files, detect-private-key, and bandit.
- [pyproject.toml](../../pyproject.toml) configures bandit but skips several rules, including subprocess-related `B404`, `B603`, and `B607`.

## Risk register

### R1. Some external write paths bypass `INBOX_TEST_MODE` service guards

Severity: high
Likelihood: medium
Blast radius: Google Drive, Gmail labels, Sheets tabs/format/copy, Google Docs text.

Evidence:

- [services.py](../../services.py) has a clear guard pattern: `_assert_live_write_allowed(action)` delegates to `inbox_test_mode.assert_live_writes_allowed`.
- `rg -n "_assert_live_write_allowed" services.py` did not include `drive_upload`, `gmail_label_create`, `sheets_rename_sheet`, `sheets_format`, `sheets_copy_to`, or `docs_insert_text`.
- [services.py](../../services.py) `drive_upload()` calls `drive_service.files().create(...).execute()` without `_assert_live_write_allowed`.
- [inbox_server.py](../../inbox_server.py) `/drive/upload` reads uploaded content to a temp file and calls `drive_upload`.
- [services.py](../../services.py) `gmail_label_create()` calls `service.users().labels().create(...)` without `_assert_live_write_allowed`.
- [inbox_server.py](../../inbox_server.py) `/gmail/labels` calls `gmail_label_create`.
- [services.py](../../services.py) `sheets_rename_sheet()`, `sheets_format()`, and `sheets_copy_to()` call Google Sheets `batchUpdate` or `copyTo` without `_assert_live_write_allowed`.
- [inbox_server.py](../../inbox_server.py) exposes `/sheets/{spreadsheet_id}/tabs/{sheet_id}`, `/sheets/{spreadsheet_id}/tabs/{sheet_id}/copy`, and `/sheets/{spreadsheet_id}/format`.
- [services.py](../../services.py) `docs_insert_text()` calls Google Docs `documents().batchUpdate(...)` without `_assert_live_write_allowed`.
- [inbox_server.py](../../inbox_server.py) `/docs/{document_id}/text` calls `docs_insert_text`.
- [tests/test_services.py](../../tests/test_services.py) only checks representative write guards: `gmail_send`, `calendar_create_event`, `reminder_complete`, `task_create`, `drive_create_folder`, `sheets_values_update`, `docs_create`, `github_mark_read`, `send_notification`, and `whatsapp_send`.

Decision note:

This is not necessarily an auth bypass. It is a safety-mode bypass. A local safe test or agent-safe backend run can still touch live external services through these paths if a mocked test accidentally uses a real service, or if an agent calls the REST path directly while `INBOX_TEST_MODE=1` is expected to prevent writes.

Next safe work:

1. Add `_assert_live_write_allowed()` to every service function that writes to an external API or local personal store.
2. Add a table-driven test that enumerates all service mutators and proves each raises `LiveWriteBlocked` before touching a fake service in `INBOX_TEST_MODE=1`.
3. Add endpoint-level tests for the currently missed paths using service patches or sentinel objects.

Validation candidates:

- Expected fail before fix: `INBOX_TEST_MODE=1 uv run pytest tests/test_services.py -q -k live_write`
- Expected fail before fix if new coverage is added first: `INBOX_TEST_MODE=1 uv run pytest tests/test_drive.py tests/test_server_endpoints.py -q -k "upload or label or sheet or doc"`
- Expected pass after fix: `INBOX_TEST_MODE=1 uv run pytest -m safe`

### R2. Auth is fail-open when token env vars are unset

Severity: high if a service is exposed beyond loopback, medium for local-only use
Likelihood: medium
Blast radius: every backend or MCP operation on the exposed surface.

Evidence:

- [inbox_server.py](../../inbox_server.py) `_is_authorized()` returns `True` when `INBOX_SERVER_TOKEN` is unset.
- [mcp_gateway.py](../../mcp_gateway.py) `_is_publicly_authorized()` returns `True` when `INBOX_MCP_TOKEN` is unset.
- [README.md](../../README.md) describes token auth as optional for all endpoints at `localhost:9849`.
- [mcp_server.py](../../mcp_server.py) documents `INBOX_MCP_TOKEN` as optional.
- [.env.mcp.example](../../.env.mcp.example) leaves `INBOX_SERVER_TOKEN=` blank.
- [tests/test_server.py](../../tests/test_server.py) explicitly validates that auth is not required when token is unset.
- [tests/test_mcp_gateway.py](../../tests/test_mcp_gateway.py) explicitly validates MCP auth behavior only when `INBOX_MCP_TOKEN` is set.
- [MCP_SETUP.md](../../MCP_SETUP.md) says to require `INBOX_MCP_TOKEN` when exposing the MCP gateway and keep `INBOX_SERVER_TOKEN` private.

Decision note:

Loopback binding lowers risk for ordinary local runs. The risk grows sharply in the documented remote/cloud-agent path because a missing env var silently turns off public MCP auth.

Next safe work:

1. Add a startup warning or fail-closed mode for HTTP MCP when `INBOX_MCP_TOKEN` is unset outside explicit local/dev mode.
2. Split examples into `local-stdio`, `local-http-dev`, and `public-http` configs so public examples never show blank auth.
3. Add tests for a `INBOX_REQUIRE_AUTH=1` or similar mode that refuses to start when required tokens are missing.

Validation candidates:

- Expected pass today: `uv run pytest tests/test_server.py::TestServerAuth tests/test_mcp_gateway.py -q`
- Expected fail before hardening: a new test that sets public mode with no `INBOX_MCP_TOKEN` and expects startup/request rejection.

### R3. Privacy docs claim local-only AI, but Gemini endpoints can send inbox content to Google

Severity: high for sensitive inbox content
Likelihood: medium when `GEMINI_API_KEY` or `gemini_api_key.txt` exists
Blast radius: Gmail/iMessage/calendar/task snippets and message bodies sent to external Gemini API.

Evidence:

- [README.md](../../README.md) says local ML has "no cloud dependencies" and privacy says all data processing happens on-device with no cloud syncing.
- [pyproject.toml](../../pyproject.toml) includes `google-generativeai`.
- [CLAUDE.md](../../CLAUDE.md) documents an optional Gemini API backend via `gemini_api_key.txt`.
- [services.py](../../services.py) `_get_gemini_model()` reads `GEMINI_API_KEY` or `gemini_api_key.txt`, configures `google.generativeai`, and creates `gemini-2.5-flash`.
- [services.py](../../services.py) `gemini_summarize()` builds a prompt from the last 20 messages, including sender and body snippets, and calls `model.generate_content(...)`.
- [services.py](../../services.py) `gemini_smart_reply()` and `gemini_categorize()` also send message or email snippets through `generate_content`.
- [inbox_server.py](../../inbox_server.py) exposes `/ai/gemini-summarize`, `/ai/smart-reply`, `/ai/categorize`, `/ai/digest`, and `/ai/action-items`.

Decision note:

The code supports both local and cloud AI paths. The docs should not describe the system as categorically local-only unless cloud endpoints are removed or gated behind explicit opt-in with visible warnings.

Next safe work:

1. Add a `INBOX_ENABLE_CLOUD_AI=1` gate around Gemini endpoints and Gemini model initialization.
2. Update README/CLAUDE privacy sections to distinguish local ML from optional cloud Gemini.
3. Add a safe test proving Gemini endpoints return an explicit disabled response when cloud AI is not enabled.

Validation candidates:

- Expected fail before hardening: new test with `GEMINI_API_KEY` set but `INBOX_ENABLE_CLOUD_AI` unset expecting no `generate_content` call.
- Expected pass after hardening: `INBOX_TEST_MODE=1 uv run pytest tests/test_ai_layer.py tests/test_server.py -q -k "gemini or ai"`

### R4. Broad OAuth scopes and file-based token storage increase local compromise blast radius

Severity: high
Likelihood: medium
Blast radius: Gmail, Calendar, Drive, Sheets, Docs, Tasks across all authorized accounts.

Evidence:

- [services.py](../../services.py) requests `gmail.readonly`, `gmail.modify`, `gmail.send`, `gmail.settings.basic`, `calendar`, `drive`, `spreadsheets`, `documents`, and `tasks`.
- [services.py](../../services.py) stores `TOKEN_FILE` and `TOKENS_DIR` in the repo root by default, with test-mode overrides.
- [services.py](../../services.py) `_write_text_with_lock()` writes token JSON atomically with a lock but does not set file mode.
- [.gitignore](../../.gitignore) excludes token files, but ignore rules do not protect local file permissions or backups.
- [scripts/setup_inbox_mcp.sh](../../scripts/setup_inbox_mcp.sh) applies `chmod 600` to `config/inbox.env`, but there is no equivalent visible guard for token JSON files.
- `fd -H '^(credentials\.json|token\.json|tokens|github_token\.txt|google_maps_key\.txt|gemini_api_key\.txt|inbox\.env|\.env)$' .` found no obvious local secret files in this worktree.

Decision note:

File-based OAuth tokens are pragmatic for a personal local app. The risk is acceptable only if the repo directory is treated as sensitive and token files are permission-checked.

Next safe work:

1. Update `_write_text_with_lock()` or token-specific writers to set `0600` permissions.
2. Add a `health` or `doctor` check that warns when token/env files are group/world readable.
3. Document token restore/copy risks for multi-worktree development.

Validation candidates:

- Expected fail before fix: new test that writes a token through `_write_text_with_lock()` and asserts mode `0600`.
- Expected pass after fix: `INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py tests/test_services.py -q -k "token or test_mode"`

### R5. Account routing still defaults silently for many writes

Severity: medium-high
Likelihood: medium
Blast radius: writes landing in the wrong Google account.

Evidence:

- [google_account_resolution.py](../../google_account_resolution.py) `default_google_account()` chooses `INBOX_DEFAULT_GOOGLE_ACCOUNT` if present, otherwise the first service key.
- [google_account_resolution.py](../../google_account_resolution.py) Gmail message/thread routing is more conservative: it checks explicit account, cache, then live message/thread existence, then falls back.
- [CLAUDE.md](../../CLAUDE.md) says account routing uses helpers with fallback logic when account is not specified.
- [inbox_server.py](../../inbox_server.py) workflow endpoints create calendar events, Drive folders, Docs, and Sheets using account defaulting.
- [inbox_server.py](../../inbox_server.py) has `/preflight/google-write`, and [tests/test_server.py](../../tests/test_server.py) covers several preflight outcomes, but write endpoints do not require preflight tokens or an explicit resolved-account acknowledgement.

Decision note:

Defaulting is useful for a personal app, but high-authority writes need either an explicit account or a recent preflight acknowledgement once multiple accounts are authorized.

Next safe work:

1. Add an optional strict mode that requires `account` for Google writes when more than one account is authorized.
2. Return `resolved_account` on all write responses, not just some of them.
3. Connect preflight results to workflow writes with a small acceptance token or required client-side acknowledgement.

Validation candidates:

- Expected pass today for existing behavior: `uv run pytest tests/test_server.py -q -k "default_account or preflight"`
- Expected fail before strict mode: new test with two accounts and no `account` expecting a 400 for a high-risk write.

### R6. Scheduler can send messages or create tasks in the background after startup

Severity: medium-high
Likelihood: low-medium
Blast radius: scheduled Gmail/iMessage sends, Google Tasks, Apple Reminders.

Evidence:

- [inbox_server.py](../../inbox_server.py) `_process_scheduled_messages()` sends due Gmail messages via `gmail_compose_send()` and iMessages via `imsg_send()`.
- [inbox_server.py](../../inbox_server.py) `_process_followup_reminders()` creates Google Tasks or Apple Reminders for followups.
- [inbox_server.py](../../inbox_server.py) `_process_departure_alerts()` can create "leave now" tasks based on calendar/location.
- [inbox_server.py](../../inbox_server.py) `_scheduler_loop()` checks scheduled messages, followups, and departure alerts every 30 seconds.
- [scheduler.py](../../scheduler.py) stores persistent state in `.inbox_scheduler.sqlite3`, which is gitignored.

Decision note:

The service-level write guards should block these in `INBOX_TEST_MODE`, but a normal server start can process old queued work. This is an operational risk when switching between primary and dev worktrees or restoring scheduler DBs.

Next safe work:

1. Add a startup banner/health field showing pending scheduled sends and followups before background processing starts.
2. Add a `INBOX_DISABLE_SCHEDULER=1` dev/agent mode and document it alongside `INBOX_TEST_MODE=1`.
3. Add tests that scheduler loops respect disabled/test mode without touching service functions.

Validation candidates:

- Expected pass today for unit-level scheduler store: `INBOX_TEST_MODE=1 uv run pytest tests/test_server.py tests/test_services.py -q -k "scheduled or followup or scheduler"`
- Expected fail before new guard: test with `INBOX_DISABLE_SCHEDULER=1` expecting no scheduled send processing.

### R7. Deployment examples can leak operational details and PII into `/tmp` logs

Severity: medium
Likelihood: medium for launchd service users
Blast radius: account emails, contact names, message recipients, ambient previews, failures.

Evidence:

- [deploy/com.inbox.backend.plist.example](../../deploy/com.inbox.backend.plist.example), [deploy/com.inbox.mcp.plist.example](../../deploy/com.inbox.mcp.plist.example), and [deploy/com.inbox.mcp-readonly.plist.example](../../deploy/com.inbox.mcp-readonly.plist.example) write stdout/stderr to `/tmp/inbox-*.log`.
- [scripts/setup_inbox_mcp.sh](../../scripts/setup_inbox_mcp.sh) reports those `/tmp` log paths as the service logs.
- [inbox_server.py](../../inbox_server.py) startup prints loaded contact count and lists of Gmail/Calendar/Drive/Sheets/Docs/Tasks account emails.
- [inbox_server.py](../../inbox_server.py) scheduler logs sent Gmail recipients and iMessage contact names.
- [ambient_notes.py](../../ambient_notes.py) logs and prints ambient capture previews.
- [services.py](../../services.py) `_format_log_context()` truncates long strings but does not classify or redact context values by key.

Decision note:

Local logs are useful for a personal service, but `/tmp` is a poor default for logs that can include account identifiers and content previews.

Next safe work:

1. Move launchd logs to a user-private app log directory such as `~/Library/Logs/inbox/`.
2. Redact account emails, recipients, contact names, file paths, and content previews in default logs.
3. Add tests for log redaction helpers, especially around `INBOX_SERVER_TOKEN`, account emails, and message snippets.

Validation candidates:

- Expected fail before hardening: new unit tests for redacting account emails and message recipients from scheduler log messages.
- Expected pass after hardening: `INBOX_TEST_MODE=1 uv run pytest tests/test_services.py tests/test_server.py -q -k "log or scheduler"`

### R8. Ambient audio and dictation are powerful local capabilities exposed through the backend

Severity: medium-high
Likelihood: low by default, higher with autostart enabled or missing auth
Blast radius: microphone capture, raw transcripts in Obsidian vault, keyboard injection.

Evidence:

- [ambient_daemon.py](../../ambient_daemon.py) continuously listens and saves extracted notes.
- [ambient_notes.py](../../ambient_notes.py) saves raw transcript text under `~/vault/daily`.
- [services.py](../../services.py) voice config defaults include `ambient_autostart: False` and `vault_dir`.
- [inbox_server.py](../../inbox_server.py) can start/stop ambient listening through `/ambient/start` and `/ambient/stop`.
- [inbox_server.py](../../inbox_server.py) can start/stop dictation through `/dictation/start` and `/dictation/stop`.
- [inbox_server.py](../../inbox_server.py) startup can auto-start ambient listening when `ambient_autostart` is true and `INBOX_DISABLE_AMBIENT` is not set.
- [services.py](../../services.py) WhatsApp and dictation-related code uses Accessibility/CGEvent style capabilities.

Decision note:

The default is safer than the capability surface because ambient autostart is off. The main risk is an unauthenticated local or accidentally exposed backend starting capture or dictation.

Next safe work:

1. Treat ambient/dictation start endpoints as high-risk operations in docs and tests.
2. Add a separate local-only or explicit-confirmation guard for microphone/keyboard operations.
3. Add `INBOX_DISABLE_VOICE=1` for agent/dev sessions and make docs recommend it.

Validation candidates:

- Expected pass today: `INBOX_TEST_MODE=1 uv run pytest tests/test_voice_pipeline.py -q`
- Expected fail before hardening: new tests that require voice start endpoints to reject when a disable env var is set.

### R9. Read-only MCP daily-note tool appears stale

Severity: medium
Likelihood: high when using read-only MCP note reads
Blast radius: readonly MCP reliability; possible path-safety risk if fixed casually.

Evidence:

- [ambient_notes.py](../../ambient_notes.py) defines `VAULT_PATH`, `DAILY_DIR`, and `AMBIENT_DIR`.
- [inbox_mcp_readonly.py](../../inbox_mcp_readonly.py) `read_daily_note()` references `ambient_notes.VAULT_DIR`, which is not defined.
- `rg -n "read_daily_note|inbox_mcp_readonly|VAULT_DIR|VAULT_PATH" .` found no tests covering `inbox_mcp_readonly.read_daily_note`.

Decision note:

This is likely a stale name from an older implementation. Fixing it should also validate date input as `YYYY-MM-DD`, not just switch to a different path constant.

Next safe work:

1. Fix `read_daily_note()` to use `ambient_notes.read_daily_note(date)` or `DAILY_DIR`.
2. Validate the `date` parameter strictly and reject path separators.
3. Add tests for today's note, explicit date, missing date, and invalid date.

Validation candidates:

- Expected fail today if added: `uv run pytest tests/test_mcp_gateway.py -q -k "read_daily_note"`
- Expected pass after fix: `INBOX_TEST_MODE=1 uv run pytest tests/test_mcp_gateway.py tests/test_ambient_notes.py -q`

### R10. Drive upload reads whole files into memory and has no apparent size limit

Severity: medium
Likelihood: medium
Blast radius: local memory/disk pressure and external Drive writes.

Evidence:

- [inbox_server.py](../../inbox_server.py) `/drive/upload` reads `content = await file.read()` before writing to a temp file.
- [inbox_server.py](../../inbox_server.py) uses `NamedTemporaryFile(delete=False, suffix=f"_{file.filename}")`, so client filenames influence temp file suffixes.
- [inbox_server.py](../../inbox_server.py) deletes the temp file in a `finally` block.
- [services.py](../../services.py) `drive_upload()` calls `MediaFileUpload(..., resumable=True)` after the temp file is created.
- [tests/test_drive.py](../../tests/test_drive.py) covers direct `drive_upload()` success/failure but not the FastAPI upload endpoint's size, temp-file naming, or `INBOX_TEST_MODE` behavior.

Decision note:

The `finally` cleanup is good. The risk is that the endpoint can allocate all uploaded bytes before size checks and then perform an external write that lacks the current live-write guard.

Next safe work:

1. Stream uploads to a temp file with a maximum byte limit.
2. Sanitize temp suffix/file display names.
3. Add `INBOX_TEST_MODE` guard to `drive_upload()` before any external API call.

Validation candidates:

- Expected fail before hardening: endpoint test uploading over a configured limit expects 413.
- Expected pass after hardening: `INBOX_TEST_MODE=1 uv run pytest tests/test_drive.py tests/test_server_endpoints.py -q -k "upload"`

### R11. Unsubscribe automation performs external HTTP/mail actions and archives regardless of method success

Severity: medium
Likelihood: low-medium
Blast radius: external unsubscribe requests, Gmail archive state.

Evidence:

- [services.py](../../services.py) `gmail_unsubscribe()` reads `List-Unsubscribe`, performs `requests.post()` or `requests.get()` for URL unsubscribes, may send an unsubscribe email for `mailto`, then calls `gmail_archive(service, msg_id)`.
- [inbox_server.py](../../inbox_server.py) exposes single and bulk unsubscribe endpoints.
- [unsubscribe_bulk.py](../../unsubscribe_bulk.py) and [unsubscribe_all_newsletters.py](../../unsubscribe_all_newsletters.py) have interactive confirmations, but REST endpoints depend on backend auth and service guard, not a per-call confirmation.

Decision note:

The service-level guard covers agent safe mode. The behavior still deserves a high-friction confirmation path because it can notify external parties and change mailbox state.

Next safe work:

1. Split "inspect unsubscribe method" from "execute unsubscribe and archive".
2. Require explicit confirmation metadata for bulk unsubscribe calls.
3. Add a dry-run response showing method, target domain/email, and archive effect.

Validation candidates:

- Expected pass today: `INBOX_TEST_MODE=1 uv run pytest tests/test_gmail_actions.py -q -k unsubscribe`
- Expected fail before hardening: new endpoint test requiring dry-run/confirm for bulk unsubscribe.

## Stale assumptions and unsupported claims

1. README privacy/local-only claim is stale relative to Gemini support. Evidence: [README.md](../../README.md) says local ML has no cloud dependencies and all data processing happens on-device, while [services.py](../../services.py) and [inbox_server.py](../../inbox_server.py) expose Gemini prompt calls.
2. "Read-only MCP" is not fully validated. It excludes registry write tools, but its handwritten daily-note read tool references a missing constant.
3. "All mutations are confirmation-gated" is true for `tools_registry.py` MCP tools, but not true for direct REST/TUI paths. Direct backend auth is optional and REST mutators do not carry `confirm=True`.
4. Preflight exists for Google writes, but it is advisory. It does not appear to gate the actual write endpoints.
5. Token safety is mostly gitignore-based. Config env files get `chmod 600` in setup, but OAuth token JSON writers do not visibly enforce private permissions.
6. Launchd/systemd examples assume one fixed path and one primary checkout, while `CLAUDE.md` encourages multiple worktrees and alternate ports. That creates handoff risk if services are bootstrapped from the wrong checkout.

## Independently grabbable next tasks

### Task 1: Exhaustive live-write guard coverage

Acceptance criteria:

- Every external-service or personal-data mutator in `services.py` calls `_assert_live_write_allowed()` before touching service clients, subprocesses, or local personal stores.
- Newly covered functions include `drive_upload`, `gmail_label_create`, `sheets_rename_sheet`, `sheets_format`, `sheets_copy_to`, and `docs_insert_text`.
- A table-driven test proves each covered function raises `LiveWriteBlocked` before touching a sentinel fake service in `INBOX_TEST_MODE=1`.

Validation:

- `INBOX_TEST_MODE=1 uv run pytest tests/test_services.py tests/test_drive.py -q -k "live_write or upload or label or sheet or doc"`
- `INBOX_TEST_MODE=1 uv run pytest -m safe`

### Task 2: Cloud AI privacy gate and documentation correction

Acceptance criteria:

- Gemini model initialization and Gemini REST endpoints require explicit cloud-AI opt-in, for example `INBOX_ENABLE_CLOUD_AI=1`.
- When disabled, Gemini endpoints return a clear disabled response without calling `generate_content`.
- README and CLAUDE privacy sections distinguish local ML from optional Gemini cloud processing.

Validation:

- `INBOX_TEST_MODE=1 uv run pytest tests/test_ai_layer.py tests/test_server.py -q -k "gemini or cloud_ai or privacy"`
- `uv run ruff check README.md CLAUDE.md services.py inbox_server.py tests`

### Task 3: Public MCP fail-closed mode

Acceptance criteria:

- Public HTTP MCP can be configured to require `INBOX_MCP_TOKEN`.
- In required mode, missing token rejects startup or all non-health routes.
- Docs and examples for public HTTP MCP never show a blank token.
- Local stdio remains ergonomic and does not require public MCP token.

Validation:

- `uv run pytest tests/test_mcp_gateway.py -q`
- `uv run ruff check mcp_gateway.py mcp_server.py inbox_mcp_readonly.py tests/test_mcp_gateway.py`

### Task 4: Account-routing strict mode for high-risk Google writes

Acceptance criteria:

- When more than one account exists and strict mode is enabled, high-risk Google writes require an explicit `account`.
- Write responses consistently include `account` or `resolved_account`.
- Existing default-account behavior remains available in normal local mode.

Validation:

- `INBOX_TEST_MODE=1 uv run pytest tests/test_server.py tests/test_gmail_actions.py -q -k "account or preflight or workflow"`

### Task 5: Private log and token-file permission hardening

Acceptance criteria:

- Token JSON writes set private file permissions.
- Launchd log defaults move from `/tmp` to a user-private app log directory.
- Log redaction tests cover tokens, account emails, recipients, and content previews.

Validation:

- `INBOX_TEST_MODE=1 uv run pytest tests/test_services.py tests/test_server.py -q -k "token or log or redaction"`
- `pre-commit run detect-private-key --all-files`

### Task 6: Read-only MCP daily-note repair

Acceptance criteria:

- `inbox_mcp_readonly.read_daily_note()` no longer references `ambient_notes.VAULT_DIR`.
- Date inputs are restricted to `YYYY-MM-DD` or empty for today.
- Tests cover existing note, missing note, and invalid/path-like date.

Validation:

- `INBOX_TEST_MODE=1 uv run pytest tests/test_ambient_notes.py tests/test_mcp_gateway.py -q -k "daily_note or readonly"`

## Validation command candidates

Required queue validation:

- Command: `git status --short`
- Expected status after report write, before any commit: one untracked or modified report path under `docs/overnight/`.
- Expected status after an optional local commit: clean output.

Agent-safe validation:

- Command: `INBOX_TEST_MODE=1 uv run pytest -m safe`
- Expected status now: should pass if dependencies are installed and the repo's safe-test contract is current. This audit did not run it because the queue item's explicit validation command is `git status --short` and the task is read-only documentation.

Lint/type validation:

- Command: `uv run ruff check .`
- Expected status now: should pass or surface existing lint unrelated to this report.
- Command: `uv run pyright`
- Expected status now: should pass or surface existing type debt unrelated to this report.

Risk-focused future validation:

- Command: `pre-commit run detect-private-key --all-files`
- Expected status now: should pass based on `.gitignore` and absence of obvious secret files in this worktree.
- Command: `uv run bandit -c pyproject.toml -r .`
- Expected status now: may pass while missing subprocess risks because `pyproject.toml` skips subprocess-related bandit rules.

## Non-goals

- No product code changes.
- No test rewrites.
- No generated data changes.
- No local server starts.
- No external service calls.
- No deploys.
- No pushes or PR creation.
- No Linear/GitHub tracker state changes.
- No attempts to read real personal token files or local personal databases.
- No migration of hidden `.factory/` artifacts.

## Unknowns and blockers

- The local queue issue file `items/inbox-sym-117-risk-register/ISSUE.md` is missing from this worktree.
- I did not run the safe pytest suite; only the required queue validation command is intended for this worker.
- I did not verify runtime behavior against live Gmail/Calendar/Drive/Sheets/Docs/Tasks, iMessage, Notes, Reminders, GitHub, Gemini, Google Maps, or audio hardware because external services and personal data access are out of scope.
- I did not inspect actual ignored token files because none were present in this worktree and secret discovery beyond gitignored placeholders is out of scope.
- I did not compare sibling repos from `repos.json` because this repo is not small and the queue item is scoped to one repo/worktree.

## Handoff notes

Changed files:

- `docs/overnight/inbox-sym-117-risk-register.md`

Suggested owner handoff:

- Start with R1 before any new live-write-capable feature work.
- Treat R3 as a documentation and product-policy decision: either Gemini is an explicit cloud feature or it should be disabled by default.
- Treat R2 as deployment hardening: local stdio can stay easy, public HTTP MCP should fail closed.
