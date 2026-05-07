# inbox-risk-register

Deep read-only risk-register audit for the `inbox` repo.

## Scope And State

- Queue item: `inbox-risk-register`
- Repo path: `/Users/jwalinshah/projects/agent-stack/.agent-stack-worktrees/2026-05-07-overnight-marathon/inbox-risk-register`
- Branch: `codex/goal-inbox-risk-register`
- Starting HEAD: `2805b8400519da188ca7d3f6e39b19a8ca42b05a` (`Merge pull request #34 from jwalin-shah/codex/SYM-9-indexed-defaults`)
- Starting dirty state: `git status --short --branch` returned only `## codex/goal-inbox-risk-register`.
- Intended tracked change: this report only, at `docs/overnight/inbox-risk-register.md`.
- Product code, generated data, credentials, deploys, pushes, and PR creation were out of scope.

## Repo Purpose

`inbox` is a local-first personal communication and productivity surface. The README describes a FastAPI backend plus Textual TUI and agent/MCP access for iMessage, Gmail, Google Calendar, Sheets, Docs, Drive, Tasks, Apple Notes, Apple Reminders, GitHub notifications, WhatsApp, ambient audio capture, dictation, local ML, and cross-silo search. The practical risk profile is high because the same repo reads local personal databases, stores derived indexes, holds OAuth/PAT/API-key material locally, and exposes many live-write operations through HTTP and MCP.

## Commands Run And Observations

- `llm-tldr tree .`: repo has one large Python app surface with `services.py`, `inbox_server.py`, `inbox_client.py`, MCP entrypoints, deployment examples, `tests/`, `batch/`, and config examples.
- `git status --short --branch`: clean at audit start; no tracked or untracked files were reported before this report was written.
- `git log --oneline -5`: recent HEAD is the indexed-defaults merge after thread rebuild and sync-health work.
- `rg -n "@app\.|app\.(get|post|put|delete)\(" inbox_server.py`: found a broad REST surface, including message send, Gmail archive/delete/reply, Calendar, Reminders, Tasks, Drive, Sheets, Docs, scheduler, index sync, and workflow creation endpoints.
- `llm-tldr search "TOKEN|SECRET|PASSWORD|OPENAI|GMAIL|GOOGLE|IMESSAGE|INBOX_SERVER_TOKEN|ANTHROPIC|GEMINI" .`: found token paths and env handling in `services.py`, `inbox_server.py`, `mcp_gateway.py`, `.mcp.json`, `.cursor/mcp.json`, config examples, and docs.
- `rg -n "assert_live|INBOX_TEST_MODE|live_write|_assert_live_write_allowed" services.py inbox_test_mode.py tests`: found a central live-write blocker used across Gmail, Google, Apple, WhatsApp, GitHub, notifications, and test coverage.
- `uv run python - <<'PY' ... tools_registry ...`: counted `60` MCP registry tools: `29` read-only and `31` mutating; all mutating registry tools currently have `confirm=True`. This command created an ignored local `.venv`, and `git status --short --branch` still reported no tracked dirt before this report.
- `rg -n "pytestmark = pytest.mark.safe|@pytest.mark.safe|@pytest.mark.local_data|@pytest.mark.live_write|@pytest.mark.integration|@pytest.mark.slow" tests`: only `tests/test_inbox_test_mode.py` and `tests/test_mcp_gateway.py` are module-marked safe, despite many tests being deterministic mocks.
- `rtk read docs/TESTING_FOR_AGENTS.md`: agent-safe command guidance exists and requires `INBOX_TEST_MODE=1`.
- `rg -n "archive|bulk|confirm|INBOX_SERVER_TOKEN|curl|POST|DELETE|dry" batch modes unsubscribe_*.py organize_inbox.py organize-inbox-helper.sh`: found a batch archive runner whose default path executes live Gmail archive calls unless `--dry-run` is passed.

`llm-tldr context inbox_server.py require_auth` and similar context calls failed with "unrecognized arguments"; the audit fell back to `rg`, `rtk read`, and line-numbered slices with `nl`.

## Evidence Map

### Authentication And Exposure

- `inbox_server.py:213` defines `INBOX_SERVER_TOKEN`.
- `inbox_server.py:1317-1329` treats an unset token as authorized and accepts either `Authorization: Bearer` or `X-API-Key` when the token exists.
- `inbox_server.py:1332-1340` applies the auth middleware to the whole FastAPI app.
- `tests/test_server.py:371-410` verifies the intended behavior: no auth is required when the token is unset; a token gates requests when configured.
- `README.md:50` documents backend auth as optional for `localhost:9849`.
- `mcp_gateway.py:32-45` applies the same optional-token pattern to public MCP auth using `INBOX_MCP_TOKEN`.
- `mcp_gateway.py:48-58` always allows `/health` through the public MCP middleware.
- `mcp_gateway.py:73-79` includes `memory_db` path and `auth_enabled` in the health payload.
- `deploy/Caddyfile.example` reverse-proxies public-looking MCP hosts to `127.0.0.1:8000` and `127.0.0.1:8001` with no Caddy-side auth.
- `deploy/inbox-mcp.service.example` and `deploy/inbox-backend.service.example` both use `EnvironmentFile=/Users/jwalinshah/projects/inbox/config/inbox.env`.

### Credential And OAuth Surface

- `.gitignore:12-25` ignores `credentials.json`, `token.json`, `tokens/`, `github_token.txt`, `google_maps_key.txt`, `gemini_api_key.txt`, env files, and secret-like suffixes.
- `services.py:57-66` resolves Google credentials and token storage under the repo by default, or under `INBOX_TEST_DATA_DIR` in test mode.
- `services.py:84-86` reads GitHub, Google Maps, and Gemini keys from local files.
- `services.py:88-98` requests broad Google scopes: Gmail readonly/modify/send/settings, Calendar, Drive, Sheets, Docs, and Tasks.
- `services.py:335-416` loads every JSON token in `tokens/` and builds per-account service maps.
- `services.py:419-437` can add or reauth Google accounts through local browser OAuth and writes per-account token JSON.
- `config/inbox.env.example:1-9` documents separate backend and public MCP bearer tokens.
- `.mcp.json:1-28` and `.cursor/mcp.json:1-28` pass `INBOX_SERVER_TOKEN` into both full and read-only stdio MCP servers.

### Backend Live Writes

- `services.py:114-119` delegates live-write blocking to `inbox_test_mode.assert_live_writes_allowed`.
- `inbox_test_mode.py:18-24` blocks writes only when `INBOX_TEST_MODE` is truthy.
- `services.py:576-623` sends iMessages via AppleScript and `osascript`.
- `services.py:970-1084` sends Gmail replies, archives Gmail, follows List-Unsubscribe URLs or mailto links, and then archives the message.
- `services.py:1087-1095` moves Gmail messages to trash.
- `services.py:1607-1716` creates, updates, and deletes Google Calendar events.
- `services.py:2335-2377` sends WhatsApp messages using Accessibility and synthesized keystrokes.
- `services.py:2868-3092` completes, uncompletes, creates, edits, and deletes Apple Reminders through AppleScript.
- `services.py:3164-3225` creates, completes, deletes, and updates Google Tasks.
- `services.py:3912-3949` creates Drive folders and trashes Drive files.
- `services.py:4083-4248` creates Sheets and updates/appends/clears sheet values.
- `services.py:5504-5512` treats desktop notifications as live writes in test mode.
- `tests/test_services.py:909-951` covers representative and extended write blocking for Gmail, Calendar, Apple Reminders, Tasks, Drive, Sheets, Docs, GitHub, notifications, and WhatsApp.

### REST Write Surface

- `inbox_server.py:1434-1450` exposes `/messages/send` for iMessage and Gmail replies.
- `inbox_server.py:1489-1589` exposes Gmail archive/delete/unsubscribe/star/read/compose/reply actions.
- `inbox_server.py:1819-1889` exposes Calendar create, quick create, update, and delete.
- `inbox_server.py:1944-1994` exposes Reminder complete/uncomplete/create/update/delete.
- `inbox_server.py:2028-2053` exposes Google Task create/complete/update/delete.
- `inbox_server.py:2548-2588` exposes Drive upload, folder create, and delete.
- `inbox_server.py:2612-2757` exposes Sheet create/delete/value writes/tab writes/format writes.
- `inbox_server.py:2940-2989` exposes Docs create/delete/text/export flows.
- `inbox_server.py:3844-3853` exposes index bootstrap and incremental sync.
- `inbox_server.py:3856-3884` exposes workflow folder/doc/sheet creation.

### MCP Surface

- `tools_registry.py:1-12` centralizes MCP tool definitions for both full and read-only servers.
- `tools_registry.py:52-107` adds a `confirm` keyword to confirm-gated tools and blocks when `confirm` is false.
- `tools_registry.py:110-119` filters non-read-only tools when `readonly_only=True`.
- `tools_registry.py:126-260` begins a registry that includes Gmail read tools, Gmail send, Sheet create/append, Gmail archive/read, and more.
- Command observation: the registry has 60 tools, 31 mutating, 29 read-only, and no mutating registry tools missing `confirm=True`.
- `mcp_server.py:41-45` confirmation-gates hand-written memory and note mutation tools.
- `mcp_server.py:142` registers the full registry with `readonly_only=False`.
- `inbox_mcp_readonly.py:44-50` still reads daily notes from the Obsidian vault.
- `inbox_mcp_readonly.py:77` registers registry tools with `readonly_only=True`.
- `tests/test_tools_registry.py:41-53` verifies all mutating registry tools require confirm and are excluded from read-only registration.
- `tests/test_mcp_gateway.py:36-53` verifies MCP health bypass and bearer rejection/acceptance when `INBOX_MCP_TOKEN` is set.

### Local Data Stores And Derived Personal Data

- `services.py:67-80` reads iMessage, Notes, and Reminders SQLite paths directly from `~/Library/...` outside test mode.
- `contacts.py:38-59` discovers AddressBook database paths under `~/Library/Application Support/AddressBook`.
- `contacts.py:65-129` reads contacts, phone numbers, and emails from AddressBook SQLite.
- `message_index_store.py:12-14` defaults the message index to `.inbox_index.sqlite3` under the repo.
- `message_index_store.py:100-120` stores `sender`, `recipients_json`, `subject`, `snippet`, `body_text`, labels, and raw pointers.
- `memory_store.py:9-10` defaults memory to `.inbox_memory.sqlite3`.
- `memory_store.py:50-62` stores memory type, subject, content, source, confidence, status, expiration, and metadata.
- `scheduler.py:15-16` defaults scheduling state to `.inbox_scheduler.sqlite3`.
- `scheduler.py:70-80` stores scheduled message source, conversation id, plaintext text, send time, status, account, sent time, and error.
- `.gitignore:40-43` ignores Claude state, memory DB, and scheduler DB; `.gitignore:58` ignores the index DB.

### Scheduler And Deferred Side Effects

- `inbox_server.py:816-817` constructs a scheduler store and message index store in global server state.
- `inbox_server.py:982-1045` sends any due scheduled Gmail/iMessage messages and marks them sent or failed.
- `inbox_server.py:1179-1192` runs scheduler, follow-up, and departure checks every 30 seconds.
- `inbox_server.py:1269-1272` starts the scheduler task by default in the app lifespan.
- `inbox_server.py:2061-2082` exposes list/create/cancel scheduled-message endpoints.
- `scheduler.py:118-148` persists scheduled message text immediately.
- `scheduler.py:181-204` selects pending messages due at or before now.
- `scheduler.py:206-225` marks scheduled messages sent or failed.

### Batch And Bulk Operations

- `batch/archive-input.tsv:1` currently has only the TSV header and no queued archive items.
- `batch/batch-runner.sh:15-19` defaults to `MODE=archive`, `PARALLEL=1`, `DRY_RUN=false`, and retries disabled.
- `batch/batch-runner.sh:61-65` constructs an unused `AUTH_HEADER`; the actual curl uses inline token expansion later.
- `batch/batch-runner.sh:74-80` posts directly to `/gmail/batch-modify` to remove the `INBOX` label.
- `batch/batch-runner.sh:126-133` only avoids mutation when `--dry-run` is explicitly provided.
- `modes/batch-archive.md:32-39` says the workflow should show a "Proceed? [y/N]" confirmation before archiving.
- `modes/batch-archive.md:43-49` documents archiving through `/gmail/batch-modify`.
- `unsubscribe_all_newsletters.py` and `unsubscribe_bulk.py` both have interactive confirmation prompts before bulk unsubscribe/archive operations.

### Validation And Tooling

- `pyproject.toml:1-18` requires Python `>=3.12,<3.15` despite README quickstart saying Python 3.10+.
- `pyproject.toml:53-61` defines pytest markers for safe, integration, local_data, slow, and live_write.
- `pyproject.toml:64-66` configures Bandit but skips several subprocess/assert-related checks (`B101`, `B110`, `B112`, `B404`, `B603`, `B607`).
- `.pre-commit-config.yaml` runs Ruff, Ruff format, basic pre-commit hooks, `detect-private-key`, and Bandit with `pyproject.toml`.
- `docs/TESTING_FOR_AGENTS.md:8-18` recommends `INBOX_TEST_MODE=1 uv run pytest -m safe`, `uv run ruff check .`, and `uv run pyright`.
- `docs/TESTING_FOR_AGENTS.md:23-43` forbids local-data, live-write, and provider-specific integration tests unless explicitly opted in.
- Command observation: only two test modules are currently marked `safe`, so `pytest -m safe` proves the new test-mode/MCP-auth guardrails but does not exercise most deterministic endpoint mocks.

## Risk Register

### R1: Optional Auth On High-Impact Local Backend

Severity: high.

The backend and public MCP gateway both allow all requests when their token env vars are unset. This is intentional and tested, but it is risky because the backend has write endpoints for Gmail, Calendar, Reminders, Tasks, Drive, Sheets, Docs, iMessage, WhatsApp, scheduler, and index sync. The MCP Caddy examples expose `/mcp*` externally and rely entirely on `INBOX_MCP_TOKEN` being set correctly. `/health` is unauthenticated on the public MCP gateway and leaks local path/status details.

Safe next direction: fail closed for public HTTP modes and provide an explicit dev-only no-auth mode.

### R2: Runtime Write Confirmation Exists In MCP, Not At The REST Boundary

Severity: high.

MCP registry tools are confirm-gated, but the REST endpoints call service write functions directly. Any client that can reach the backend and pass backend auth can call write endpoints without a second write-intent check. The test-mode guard is only for `INBOX_TEST_MODE`; in production it intentionally allows writes.

Safe next direction: add a backend write policy that can require per-action confirmation or a short-lived write-intent token for all mutating endpoints, independent of the MCP caller.

### R3: Broad OAuth Scopes And Account Fallback Can Mutate The Wrong Account

Severity: high.

Google OAuth scopes cover Gmail modify/send/settings, Calendar, Drive, Sheets, Docs, and Tasks. Multi-account resolution falls back to `INBOX_DEFAULT_GOOGLE_ACCOUNT` or the first service key. Some write endpoints accept optional account values and otherwise rely on fallback. `preflight_google_write_payload` exists, but the endpoint layer does not require a preflight before all writes.

Safe next direction: require explicit account on all Google writes unless a configured default is present and verified, and require preflight for Drive/Docs/Sheets/Tasks/Calendar workflow writes.

### R4: Deferred Scheduler Can Turn A Low-Friction API Call Into A Later Live Send

Severity: high.

The `/scheduled` endpoint stores future message text and recipient/conversation data. The background scheduler starts by default and sends due Gmail/iMessage messages every 30 seconds. There is no human confirmation at send time in production; the original schedule call is the critical control point.

Safe next direction: make scheduled sends reviewable by default, require confirmation when enqueueing and when firing, and store only the minimum plaintext required.

### R5: Derived Local Caches Contain Personal Data With No Retention Boundary

Severity: medium-high.

The index store persists message body text, snippets, subjects, participants, labels, and raw pointers. The scheduler stores plaintext messages. The memory store stores arbitrary personal memory content. These files are ignored by git, but they live under the repo by default and are not encrypted, TTL-governed, or scrubbed by a documented cleanup flow.

Safe next direction: centralize private data directory selection, document retention, add purge/export commands, and consider redaction for index body storage.

### R6: Batch Archive Runner Defaults To Live Mutation Despite Docs Promising Confirmation

Severity: medium-high.

`modes/batch-archive.md` says the workflow should prompt before archiving. The shell runner defaults to `DRY_RUN=false` and executes pending archive rows immediately. The input file is currently empty, but this is a sharp edge once populated.

Safe next direction: make batch archive dry-run by default, add an explicit `--execute` flag, and align docs/tests with the runner.

### R7: List-Unsubscribe Follows Untrusted Header URLs

Severity: medium.

`gmail_unsubscribe` extracts List-Unsubscribe headers, performs HTTP GET/POST requests, can send mailto unsubscribe messages, and then archives the original message. This behavior touches untrusted URLs derived from email headers and creates external network traffic beyond Google APIs.

Safe next direction: require explicit domain/method preview before URL unsubscribe, prefer one-click POST only when verified, and do not archive when unsubscribe fails unless separately requested.

### R8: Local Apple Automation Depends On Full Disk Access And Accessibility Permissions

Severity: medium.

iMessage, Notes, Reminders, AddressBook, ambient notes, desktop notifications, and WhatsApp automation rely on direct SQLite reads, AppleScript, or Accessibility. This is appropriate for a local personal assistant but fragile: permission prompts, stale schemas, and background process restrictions can cause partial failure or unexpected UI actions.

Safe next direction: add explicit preflight endpoints for Apple-data read/write permissions and require dry-run previews for AppleScript/Accessibility writes.

### R9: Public Read-Only MCP Still Exposes Sensitive Read Surfaces

Severity: medium.

The read-only MCP server excludes mutating registry tools, but it still exposes Gmail search/thread reads, Sheet reads, notes reads, memory reads, and daily note reads. "Read-only" is not low-risk for a personal-data repo, especially if connected to cloud agents.

Safe next direction: document "read-only means non-mutating, not non-sensitive"; add per-source allowlists and redaction limits for cloud agents.

### R10: Validation Lane Is Good But Under-Applied

Severity: medium.

The repo has strong safe-test guidance and good representative write-block tests. However, only two modules are marked `safe`, so the advertised `pytest -m safe` command does not cover many deterministic endpoint tests that already mock providers. This can give a false sense of validation coverage.

Safe next direction: classify deterministic mocked tests as `safe` and add a small risk-focused safe suite for auth, MCP confirmation, account resolution, and batch dry-run behavior.

## Stale Assumptions And Claim Gaps

- README says Python 3.10+; `pyproject.toml` requires Python `>=3.12,<3.15`.
- README says "Local-first ML" and "no cloud dependencies"; the app also uses Google APIs, Gemini API/key paths, Google Maps keys, GitHub tokens, and optional public MCP deployment.
- README says optional backend auth; that is accurate, but risky for a backend with live writes.
- "Read-only MCP" is accurate for mutation exclusion, but it can still disclose very sensitive content.
- "Multi-account Gmail routing" is partly supported, but fallback to first/default account remains a stale assumption risk for writes.
- Batch archive docs promise a confirmation prompt; the shell runner does not prompt unless the caller uses `--dry-run`.

## Next Safe Work

### Task 1: Fail Closed For Public Auth

Acceptance criteria:
- HTTP MCP startup fails or refuses non-health `/mcp*` traffic when `INBOX_MCP_TOKEN` is unset in HTTP mode.
- Backend startup has an explicit `INBOX_ALLOW_NO_AUTH=1` or equivalent dev-only override if `INBOX_SERVER_TOKEN` is unset.
- Health payload no longer exposes local private paths unless authenticated or in dev mode.
- Docs and deployment examples state which auth env vars are mandatory.

Validation command candidates:
- `INBOX_TEST_MODE=1 uv run pytest tests/test_mcp_gateway.py tests/test_server.py::TestAuth --no-cov -p no:cacheprovider`
- `uv run ruff check mcp_gateway.py inbox_server.py tests/test_mcp_gateway.py tests/test_server.py`

Expected status: should pass after implementation; current code would fail stricter no-token expectations because no-auth is tested as allowed.

### Task 2: Add REST-Level Write Intent Guard

Acceptance criteria:
- Every mutating REST endpoint passes through one shared write-intent check.
- `INBOX_TEST_MODE=1` remains a hard block.
- MCP `confirm=True` is not the only write gate; direct REST calls need an equivalent explicit confirmation mechanism.
- Tests cover at least Gmail reply/archive, Calendar create, Reminder create, Task create, Drive delete, Sheet append, Scheduler create, and Workflow doc/sheet/folder creation.

Validation command candidates:
- `INBOX_TEST_MODE=1 uv run pytest tests/test_services.py::test_test_mode_blocks_representative_live_writes tests/test_services.py::test_test_mode_blocks_extended_live_writes --no-cov -p no:cacheprovider`
- `INBOX_TEST_MODE=1 uv run pytest tests/test_server.py tests/test_server_endpoints.py --no-cov -p no:cacheprovider`

Expected status: current test-mode write blockers should pass; new REST write-intent tests would fail until implemented.

### Task 3: Require Explicit Account Or Verified Default For Google Writes

Acceptance criteria:
- All Google write endpoints resolve a write account through one strict helper.
- If no account is supplied, the helper only uses `INBOX_DEFAULT_GOOGLE_ACCOUNT` when it maps to the target service.
- Falling back to `next(iter(services))` is allowed for reads but not writes.
- Preflight responses are required or embedded for Drive/Docs/Sheets/Tasks/Calendar workflow writes.

Validation command candidates:
- `INBOX_TEST_MODE=1 uv run pytest tests/test_gmail_actions.py tests/test_calendar.py tests/test_drive.py --no-cov -p no:cacheprovider`
- `uv run pyright`

Expected status: existing tests may need updates because current write helpers permit fallback.

### Task 4: Make Batch Archive Safe By Default

Acceptance criteria:
- `batch/batch-runner.sh` defaults to dry-run behavior and requires `--execute` for live archive.
- The docs in `modes/batch-archive.md` match the implemented CLI.
- The runner refuses to execute when `INBOX_SERVER_TOKEN` is unset unless an explicit local no-auth flag is supplied.
- A shell-level smoke test or script check covers empty input, dry-run, and execute gating without contacting the live backend.

Validation command candidates:
- `bash batch/batch-runner.sh --mode archive --dry-run`
- `bash -n batch/batch-runner.sh`
- `uv run ruff check .`

Expected status: current empty-input dry-run should exit cleanly; stricter execute-gating tests would fail until implemented.

### Task 5: Document And Constrain Private Local Data Stores

Acceptance criteria:
- A single doc names every local private data store, file path, env override, retention expectation, and cleanup command.
- `.inbox_index.sqlite3`, `.inbox_memory.sqlite3`, `.inbox_scheduler.sqlite3`, tokens, config files, Obsidian vault writes, and Apple local DB reads are all covered.
- Index configuration can disable body-text persistence or cap retention.
- Health endpoints avoid leaking exact private paths by default.

Validation command candidates:
- `uv run ruff check message_index_store.py memory_store.py scheduler.py mcp_gateway.py`
- `INBOX_TEST_MODE=1 uv run pytest tests/test_memory_store.py tests/test_message_index_store.py tests/test_mcp_gateway.py --no-cov -p no:cacheprovider`

Expected status: existing store tests should mostly pass; retention/redaction tests would be new.

## Validation Notes

Required queue validation:

```bash
git status --short
```

Observed after writing this report:

```text
?? docs/overnight/
```

Commit attempt blocker: `git add docs/overnight/inbox-risk-register.md && git commit -m "Add inbox risk register audit"` failed because the sandbox could not write `/Users/jwalinshah/projects/inbox/.git/worktrees/inbox-risk-register/index.lock` (`Operation not permitted`). The report is therefore intentionally left uncommitted in this worktree.

Ignored local side effect: the `uv run python ... tools_registry ...` inspection command created `.venv/`. A cleanup attempt with `rm -rf .venv` was rejected by local command policy, so `.venv/` remains ignored local state.

Additional candidate validations for future implementation work:

- `INBOX_TEST_MODE=1 uv run pytest -m safe --no-cov -p no:cacheprovider` should pass but currently covers only two safe-marked modules.
- `INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py tests/test_mcp_gateway.py tests/test_tools_registry.py --no-cov -p no:cacheprovider` should pass and directly covers test-mode, public MCP auth, and registry confirmation.
- `uv run ruff check .` should be the cheapest full lint proof.
- `uv run pyright` should be run before product changes that touch shared service models or endpoint contracts.
- `uv run bandit -c pyproject.toml -r .` should be used for security-oriented changes, with awareness that several subprocess/assert checks are intentionally skipped in `pyproject.toml`.

## Non-Goals

- No product code was changed.
- No tests or lint commands were run beyond local inspection/counting commands.
- No generated artifact was intended as a deliverable; the ignored `.venv/` was an inspection side effect and cleanup was policy-blocked.
- No credentials, tokens, local Apple data, Gmail data, Google data, GitHub data, Obsidian vault data, or remote services were accessed intentionally.
- No server was started.
- No deploy, push, PR, or external tracker update was performed.
- No attempt was made to fix the risks in this queue item.

## Unknowns

- Whether `INBOX_SERVER_TOKEN` and `INBOX_MCP_TOKEN` are always set in the user's real local and public deployments.
- Whether Caddy or another upstream proxy adds auth, IP filtering, mTLS, or firewall rules outside this repo.
- Whether local token files are encrypted or otherwise protected by filesystem policy outside git.
- Whether `.inbox_index.sqlite3`, `.inbox_memory.sqlite3`, and `.inbox_scheduler.sqlite3` already exist in the real working repo and how large/sensitive they are.
- Whether cloud agents are expected to use the full MCP server or only `inbox_mcp_readonly.py`.
- Whether List-Unsubscribe network calls are acceptable product behavior or should require a preview step.
- Whether scheduled sends are used operationally and what human approval expectation exists at enqueue and fire time.
