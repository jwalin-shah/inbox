# inbox-sym-116 risk register audit

Queue item: `inbox-sym-116-risk-register`

Focus area: security, credentials, data, deployment, destructive-command, and external-service risks.

## Repo State

- Repo path: `/Users/jwalinshah/projects/agent-stack/.agent-stack-worktrees/2026-05-07-overnight-marathon/inbox-sym-116-risk-register`
- Purpose: local-first personal communications/productivity TUI and FastAPI backend for iMessage, Gmail, Calendar, Drive, Sheets, Docs, Tasks, Apple Notes, Reminders, GitHub, ambient audio, dictation, and MCP access. Evidence: `README.md:1`, `README.md:5`, `CLAUDE.md:1`, `CLAUDE.md:80`.
- Branch: `codex/goal-inbox-sym-116-risk-register`.
- HEAD at audit start: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`.
- Remote: `origin https://github.com/jwalin-shah/inbox.git`.
- Dirty state at audit start: `git status --short --branch` returned only `## codex/goal-inbox-sym-116-risk-register`, so no pre-existing tracked or untracked changes were visible.
- Scope decision: this audit only writes this report. No product code, generated data, secrets, deploys, external service calls, pushes, or PR creation were performed.

## Commands Run

- `llm-tldr tree .` to inventory repo structure.
- `rg --files -g '!*__pycache__*' -g '!*.pyc'` to list tracked visible source files.
- `rtk read README.md`, `rtk read CLAUDE.md`, `rtk read pyproject.toml`, `rtk read docs/TESTING_FOR_AGENTS.md`, and focused `nl -ba ... | sed -n ...` reads for code evidence.
- `rg -n "@app\\.(post|put|patch|delete)" inbox_server.py | wc -l` observed 95 mutating FastAPI routes.
- `rg -n "_assert_live_write_allowed" services.py | wc -l` observed 44 live-write guard call sites.
- `rg -n "confirm=True" tools_registry.py | wc -l` observed 34 confirmation-gated registry tools.
- `rg -n "readonly=True" tools_registry.py | wc -l` observed 29 read-only registry tools.
- `wc -l services.py inbox_server.py tools_registry.py tests/test_server.py tests/test_tools_registry.py` observed `services.py` at 6467 lines and `inbox_server.py` at 3940 lines.
- `fd -H -E .git -t f . | rg -n "(credentials|token|tokens|github_token|gemini_api_key|google_maps_key|inbox\\.env|server\\.log|\\.inbox_.*\\.sqlite3|archive-state|triage-output)"` found no live credential files; visible matches were a token-safety validation artifact and `config/inbox.env.example`.
- `rg -n "BEGIN|PRIVATE KEY|ghp_|AIza|ya29|refresh_token|client_secret" -g '!uv.lock' -g '!docs/overnight/**' .` found only test placeholders and code references, not real secrets.

## Local Evidence

1. `services.py:56` stores runtime secrets and local data paths relative to the repo for credentials, tokens, GitHub token, Google Maps key, Gemini key, and local sqlite state.
2. `services.py:88` requests broad Google scopes: Gmail read/modify/send/settings, Calendar, Drive, Sheets, Docs, and Tasks.
3. `inbox_server.py:1317` makes backend token auth optional; if `INBOX_SERVER_TOKEN` is unset, `_is_authorized` returns true.
4. `mcp_gateway.py:36` makes public MCP token auth optional; if `INBOX_MCP_TOKEN` is unset, non-health requests are allowed.
5. `mcp_gateway.py:67` returns backend health, memory DB path, and `auth_enabled` from `/health`.
6. `tools_registry.py:73` enforces `confirm=True` at the MCP registry handler layer for tools marked `confirm`.
7. `tools_registry.py:110` supports `readonly_only=True`, and `inbox_mcp_readonly.py:77` registers only readonly registry tools.
8. `mcp_server.py:142` registers the full registry with `readonly_only=False`; full MCP can reach mutating tools when confirmed.
9. `inbox_server.py:1434`, `inbox_server.py:1738`, `inbox_server.py:1819`, `inbox_server.py:2548`, `inbox_server.py:2612`, and `inbox_server.py:2940` expose direct REST write routes for messaging, Gmail, Calendar, Drive, Sheets, and Docs.
10. `services.py:114` defines test-mode live-write blocking, but production write calls proceed when `INBOX_TEST_MODE` is not set.
11. `services.py:576`, `services.py:970`, `services.py:998`, `services.py:1607`, `services.py:2867`, `services.py:3164`, `services.py:3732`, `services.py:3912`, `services.py:4083`, and `services.py:4437` show representative live-write surfaces.
12. `services.py:1044` executes unsubscribe URLs from email headers and then archives the message at `services.py:1083`.
13. `scheduler.py:70` stores scheduled message text in `.inbox_scheduler.sqlite3`; `inbox_server.py:982` sends due messages from the background loop.
14. `services.py:2804` executes AppleScript with retries; `services.py:2309` and `services.py:4702` inject text via macOS keyboard events.
15. `inbox_mcp_readonly.py:45` defines a readonly daily-note tool, but `inbox_mcp_readonly.py:47` references `ambient_notes.VAULT_DIR`; `ambient_notes.py:14` defines `VAULT_PATH`, `DAILY_DIR`, and `AMBIENT_DIR`, not `VAULT_DIR`.
16. `.gitignore:12` ignores credential/token files, environment files, logs, and local sqlite state. `config/inbox.env.example:3` and `config/inbox.env.example:6` document separate backend and MCP tokens.
17. `docs/TESTING_FOR_AGENTS.md:8` recommends `INBOX_TEST_MODE=1 uv run pytest -m safe`, plus ruff and pyright. Only `tests/test_inbox_test_mode.py:8` and `tests/test_mcp_gateway.py:18` are marked `safe`, so the safe marker currently covers a narrow guardrail subset.
18. `MCP_SETUP.md:248` says expose readonly MCP first, keep the raw backend private, require `INBOX_MCP_TOKEN`, and keep `INBOX_SERVER_TOKEN` private to the MCP host.

## Risk Register

### R1 - Raw backend is powerful and auth is fail-open when token is unset

Severity: high.

The backend guards all routes with `_is_authorized`, but `inbox_server.py:1317` returns allowed when `INBOX_SERVER_TOKEN` is empty. This is acceptable only if the backend is always bound to loopback and never exposed. The same codebase contains 95 mutating FastAPI routes, including message send, Gmail label/filter changes, Calendar CRUD, Drive upload/delete, Sheets/Docs writes, Tasks/Reminders, ambient/dictation control, and index sync. The backend binds to `127.0.0.1` in `inbox_server.py:3939`, and deployment docs say never expose it (`MCP_SETUP.md:269`), but the runtime still fails open locally.

Risk event: any local process, misrouted MCP client, reverse proxy mistake, or dev worktree pointed at the primary backend can mutate personal accounts without per-operation confirmation.

Current controls: loopback bind; optional bearer or `x-api-key` token; `.gitignore` for secrets; MCP confirmation gating.

Gap: REST has no mandatory auth-by-default and no central write confirmation/preflight layer.

### R2 - Public MCP token auth is also optional

Severity: high for remote deployment, medium for local-only use.

`mcp_gateway.py:36` allows all non-health MCP requests when `INBOX_MCP_TOKEN` is empty. The Caddy example exposes `/health` and `/mcp` (`deploy/Caddyfile.example:1`), and service examples load `config/inbox.env` (`deploy/inbox-mcp.service.example:7`). Docs warn to require `INBOX_MCP_TOKEN` (`MCP_SETUP.md:256`), but the process itself does not fail closed.

Risk event: an HTTP MCP gateway is exposed before `INBOX_MCP_TOKEN` is set; readonly mode still leaks personal data, and full mode exposes write tools subject only to MCP `confirm=True`.

Current controls: `config/inbox.env.example` has placeholders for separate tokens; `MCP_SETUP.md:144` explicitly says to use different backend and MCP tokens.

Gap: no startup refusal for externally exposed full or readonly MCP when token env is missing.

### R3 - Confirmation gating is MCP-only, not REST-wide

Severity: high.

`tools_registry.py:73` blocks mutating MCP tools unless `confirm=True`, and tests assert all non-readonly registry tools are confirm-gated (`tests/test_tools_registry.py:41`). Direct REST endpoints do not require a `confirm` field. For example, `/messages/send`, `/gmail/batch-modify`, `/calendar/events`, `/drive/upload`, `/docs/{document_id}/text`, `/scheduled`, and `/tasks/from-message` execute based on backend auth alone.

Risk event: a local agent or script bypasses MCP and calls REST directly with a valid token or no token in fail-open mode.

Current controls: service-layer `INBOX_TEST_MODE` blocks representative live writes during tests.

Gap: no central REST write policy decorator, no write-intent audit log, and preflight is advisory only for some Google writes.

### R4 - Google OAuth blast radius is broad and shared across accounts

Severity: high.

`services.py:88` requests full write scopes for Gmail, Calendar, Drive, Sheets, Docs, and Tasks. `google_auth_all()` loads every JSON token in `tokens/` (`services.py:367`) and builds all available services. Account fallback helpers use `INBOX_DEFAULT_GOOGLE_ACCOUNT` if set, then first service key (`google_account_resolution.py:24`). Connector roadmap documents this as a known source-of-truth risk (`CONNECTOR_ROADMAP.md:32`, `CONNECTOR_ROADMAP.md:216`).

Risk event: a write goes to the wrong Google account or an unnecessarily powerful token is compromised.

Current controls: account resolution helpers, preflight endpoint for selected Google write destinations, docs requiring default account policy.

Gap: scope separation is not enforced at token level; readonly clients still depend on tokens that may have write scopes; fallback to first account remains possible when defaults are absent.

### R5 - Unsubscribe follows arbitrary email-provided URLs and archives regardless

Severity: medium-high.

`gmail_unsubscribe()` parses `List-Unsubscribe` headers, then performs a `requests.post` or `requests.get` to the header URL (`services.py:1059`) and archives the message afterward (`services.py:1083`). This makes external calls to sender-provided URLs from the local host. It also archives even if the unsubscribe call fails.

Risk event: a malicious or compromised sender uses unsubscribe headers for tracking, SSRF-like local network probing, or unwanted state changes, then the original message is archived.

Current controls: timeout of 10 seconds; action goes through live-write guard in test mode.

Gap: no URL allowlist/blocklist, no scheme/host filtering, no dry-run mode, and archive is unconditional.

### R6 - Local macOS automation has high side-effect potential

Severity: medium-high.

iMessage sends use AppleScript (`services.py:576` and `services.py:622`), Reminders mutations use AppleScript with retries (`services.py:2804`), WhatsApp sends use Accessibility plus CGEvent keyboard injection (`services.py:2335`), and dictation injects text into the active cursor (`services.py:4702`). These are powerful local automations that can affect user-visible apps outside the repo.

Risk event: wrong conversation selection, active-window confusion, duplicate AppleScript retries, or dictation injection into the wrong app.

Current controls: test mode can block live writes; WhatsApp checks Accessibility before send.

Gap: no production dry-run/preview gate for direct REST callers; no explicit app/window assertion for every keyboard-injection path.

### R7 - Scheduler stores plaintext message content and auto-sends later

Severity: medium-high.

`scheduler.py:70` stores scheduled message text in local sqlite. `inbox_server.py:982` checks due messages every 30 seconds and sends Gmail/iMessage without a new confirmation at send time. `inbox_server.py:2066` lets REST create scheduled messages.

Risk event: stale scheduled messages send after context changes; local sqlite leaks sensitive draft content; accidental issue/worktree shares `.inbox_scheduler.sqlite3` if ignore controls are bypassed.

Current controls: `.gitignore` excludes `.inbox_scheduler.sqlite3`; cancel endpoint exists; service-layer send functions retain test-mode blocking.

Gap: no send-time revalidation, no redacted list mode, no expiry, no "pending message digest" requirement before daemon startup.

### R8 - Readonly MCP has a concrete daily-note bug and limited coverage

Severity: medium.

`inbox_mcp_readonly.py:47` references `ambient_notes.VAULT_DIR`, which does not exist. This breaks dated `read_daily_note(date=...)` requests in the safer surface recommended for cloud agents. Existing tests cover `ambient_notes.read_daily_note()` and MCP auth middleware, but not the readonly MCP daily-note handler.

Risk event: morning review or cloud-agent read-only setup fails on note reads and falls back to the full MCP server.

Current controls: separate readonly MCP entrypoint; registry readonly filtering is tested.

Gap: no test imports/runs readonly MCP hand-written tools.

### R9 - Health and logs can expose sensitive metadata

Severity: medium.

Backend `/health` returns account email lists and GitHub token configured status (`inbox_server.py:1346`). MCP `/health` returns backend health and memory DB path (`mcp_gateway.py:67`). `_log_service_failure()` formats arbitrary context (`services.py:139`) and many callers include email addresses, message ids, file paths, account names, and object titles.

Risk event: health endpoint or logs leak account inventory and local paths to remote clients or shared logs.

Current controls: backend health is token-protected when token is configured; MCP health is intentionally unauthenticated.

Gap: no redaction layer for health payloads or structured logs; no documented log retention policy for `/tmp/inbox-*.log`.

### R10 - Upload/download endpoints lack resource limits

Severity: medium.

`inbox_server.py:2548` reads the full upload body into memory before writing a temp file. Gmail attachment download returns base64 JSON (`inbox_server.py:1565`) and Drive download returns raw bytes (`inbox_server.py:2524`). These are convenient but have no visible size ceilings or streaming controls.

Risk event: large files or attachments exhaust memory or produce oversized responses through MCP/REST clients.

Current controls: upload temp file is unlinked in `finally`; Drive API handles storage-side file data.

Gap: no max upload size, no max attachment size, no streaming response, and no content-type/file-name policy.

## Stale Assumptions

- "Localhost means safe" is baked into both backend and MCP auth behavior. That assumption is fragile once Caddy, LaunchAgents, worktrees, or cloud agents enter the path.
- "Readonly MCP is the remote-safe surface" is directionally right, but hand-written readonly tools are not covered enough; the dated daily-note handler currently references a missing attribute.
- "One Google OAuth token set is simpler" conflicts with least-privilege operation. Read-only, write, and high-risk settings scopes are currently bundled.
- "MCP confirmation is enough" is stale because direct REST, TUI, local scripts, and scheduler paths can mutate state without MCP.
- "Safe validation is broad" is stale because only two test modules currently carry the `safe` marker.

## Next Safe Work

### Task 1 - Fail closed when exposed auth tokens are missing

Acceptance criteria:
- Backend exposes explicit `auth_enabled` and startup logs distinguish "loopback dev without token" from "service mode with token required".
- HTTP MCP full and readonly entrypoints refuse to start in service/public mode unless `INBOX_MCP_TOKEN` is set.
- Tests cover missing-token behavior for `mcp_gateway.py` and backend health/auth mode.

Validation command:
- `INBOX_TEST_MODE=1 uv run pytest tests/test_mcp_gateway.py tests/test_server.py -k "auth or health" -q`

### Task 2 - Add REST write policy metadata and confirmation/preflight coverage

Acceptance criteria:
- Every mutating FastAPI route is classified as local-state, external-write, destructive, or automation.
- High-risk REST routes require either a typed preflight token/operation id or an explicit `confirm` field, not just bearer auth.
- Tests prove representative routes reject missing confirmation while safe read routes continue to work.

Validation command:
- `INBOX_TEST_MODE=1 uv run pytest tests/test_server.py tests/test_tools_registry.py -q`

### Task 3 - Fix and test readonly MCP hand-written tools

Acceptance criteria:
- `inbox_mcp_readonly.read_daily_note(date=...)` delegates to `ambient_notes.read_daily_note()` or uses `DAILY_DIR`, not a missing `VAULT_DIR`.
- Tests import readonly MCP, exercise `read_daily_note()` for today and a dated note, and confirm registry writes are absent.
- The readonly MCP health payload remains useful without leaking more than intended.

Validation command:
- `INBOX_TEST_MODE=1 uv run pytest tests/test_mcp_gateway.py tests/test_ambient_notes.py -q`

### Task 4 - Harden unsubscribe execution

Acceptance criteria:
- `gmail_unsubscribe()` validates scheme and host, blocks localhost/private network targets, and supports dry-run/preflight.
- Archive happens only after a successful unsubscribe or explicit archive confirmation.
- Tests cover URL, mailto, invalid scheme, private-address URL, timeout, and failed unsubscribe without archive.

Validation command:
- `INBOX_TEST_MODE=1 uv run pytest tests/test_gmail_actions.py -k unsubscribe -q`

### Task 5 - Split Google scopes by capability lane

Acceptance criteria:
- Read-only MCP can use read-only Google scopes where possible.
- Write scopes are requested only for enabled write features.
- Reauth messaging and token migration make scope expansion explicit.

Validation command:
- `INBOX_TEST_MODE=1 uv run pytest tests/test_server.py tests/test_services.py -k "auth or account or scope" -q`

### Task 6 - Add scheduler safety checks

Acceptance criteria:
- Scheduled messages validate account, recipient/conversation, send time, and source at creation.
- List endpoints redact message body by default, with explicit opt-in for full text.
- Startup exposes a pending scheduled-message summary before background sends are enabled.

Validation command:
- `INBOX_TEST_MODE=1 uv run pytest tests/test_server.py -k "scheduled or followup" -q`

## Validation Candidates

- Required queue validation: `git status --short`
  - Expected status after this report is committed or intentionally left as the only dirty file: pass, exit 0.
- Agent-safe smoke: `INBOX_TEST_MODE=1 uv run pytest -m safe`
  - Expected status: pass, but coverage is narrow because only two modules are marked safe.
- Focused readonly MCP regression: `INBOX_TEST_MODE=1 uv run pytest tests/test_mcp_gateway.py tests/test_ambient_notes.py -q`
  - Expected status before Task 3: likely pass for existing tests, but it will not catch the `VAULT_DIR` bug until a readonly MCP handler test is added.
- REST auth/policy regression: `INBOX_TEST_MODE=1 uv run pytest tests/test_server.py -k "auth or preflight" -q`
  - Expected status: pass for existing optional-auth/preflight behavior; should fail after adding fail-closed expectations until code is updated.
- Lint: `uv run ruff check .`
  - Expected status: unknown in this audit; docs list it as standard validation but it was not run because the queue validation command is `git status --short`.
- Type check: `uv run pyright`
  - Expected status: unknown in this audit; repo uses basic type checking.

## Non-Goals

- No product code changes.
- No secret/token inspection beyond confirming live secret files were not present in the worktree.
- No live Gmail, Calendar, Drive, Docs, Sheets, Tasks, Reminders, iMessage, WhatsApp, audio, notification, or GitHub operations.
- No local server startup, Caddy/LaunchAgent changes, deploy changes, pushes, PR creation, or tracker updates.
- No attempt to resolve product decisions such as which Google scopes should be permanently removed.

## Unknowns

- Whether the daily-driver environment currently sets `INBOX_SERVER_TOKEN`, `INBOX_MCP_TOKEN`, and `INBOX_DEFAULT_GOOGLE_ACCOUNT`.
- Whether any deployed Caddy/LaunchAgent setup differs from the checked-in examples.
- Whether token files on the daily-driver host contain legacy broad scopes or recently reauthed scopes.
- Whether users rely on direct REST scripts that would break if write confirmation became mandatory.
- Whether any hidden local logs under `/tmp/inbox-*.log` contain account metadata or message snippets.
- Whether the scheduler has pending real scheduled messages in the daily-driver `.inbox_scheduler.sqlite3`.

## Handoff Notes

- The highest-leverage fix is to make public/service auth fail closed and classify all REST writes centrally.
- The lowest-risk starter fix is Task 3: repair `inbox_mcp_readonly.py:47` and add direct tests for readonly hand-written tools.
- Morning review should inspect this report with `git show -- docs/overnight/inbox-sym-116-risk-register.md` and verify that only this file changed for the queue item.
