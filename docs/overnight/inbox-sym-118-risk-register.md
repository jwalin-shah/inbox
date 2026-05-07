# inbox-sym-118 risk register audit

Queue item: `inbox-sym-118-risk-register`
Repo: `inbox-sym-118`
Worktree: `/Users/jwalinshah/projects/agent-stack/.agent-stack-worktrees/2026-05-07-overnight-marathon/inbox-sym-118-risk-register`
Branch: `codex/goal-inbox-sym-118-risk-register`
Base HEAD before this report: `2805b8400519da188ca7d3f6e39b19a8ca42b05a`
Audit date: 2026-05-07

## Scope and method

This was a read-only risk-register audit. I did not call live Inbox, Gmail,
Calendar, Drive, GitHub, WhatsApp, macOS automation, cloud deployment, or MCP
services. The only write intended by this queue item is this report.

Evidence came from compact structure/search commands plus targeted file reads.
One validation-discovery probe attempted to build the test environment with
`uv`; it failed before tests ran because this sandbox has no network access. The
temporary `.venv` created by that probe was removed.

## Repo purpose and current state

`README.md` describes Inbox as a privacy-first terminal UI that consolidates
iMessage, Gmail, Google Calendar, Google Sheets, Apple Notes, Apple Reminders,
GitHub notifications, Google Drive, ambient audio, dictation, and local ML into
one keyboard-driven interface. The runtime is a local FastAPI backend
(`inbox_server.py`) with thin clients (`inbox.py`, `inbox_client.py`) and MCP
surfaces (`mcp_server.py`, `inbox_mcp_readonly.py`, `mcp_backend.py`).

Observed repo state:

- `pwd` returned this assigned worktree path.
- `git status --short --branch` initially returned only
  `## codex/goal-inbox-sym-118-risk-register`; no pre-existing dirty state was
  observed.
- `git log --oneline -5` showed HEAD at merge commit `2805b84` with recent
  indexed inbox/default sync work.
- `llm-tldr tree .` showed the important risk surfaces: `config/`, `deploy/`,
  `scripts/`, `batch/`, `tests/`, `inbox_server.py`, `services.py`,
  `tools_registry.py`, MCP entrypoints, local stores, and unsubscribe utilities.
- `docs/` initially contained only `docs/TESTING_FOR_AGENTS.md`; this report
  creates `docs/overnight/`.

## Local evidence inventory

These are the highest-signal local observations used for the register.

- `README.md:48-83` documents many REST write endpoints, including message send,
  Gmail unsubscribe, calendar create/update/delete, reminder completion, GitHub
  notification mutation, Sheets writes, and Drive delete.
- `README.md:146-156` says auth is optional through `INBOX_SERVER_TOKEN`, and
  `README.md:158-164` names local credential files: `credentials.json`,
  `tokens/`, and `github_token.txt`.
- `inbox_server.py:1313-1340` implements optional API-token auth; if
  `INBOX_SERVER_TOKEN` is unset, `_is_authorized` returns true for every
  request.
- `inbox_server.py:1346-1357` returns health metadata including configured
  Gmail, calendar, Drive, and Sheets accounts plus GitHub-token presence.
- `mcp_gateway.py:48-58` explicitly lets `/health` bypass public MCP auth, while
  `mcp_gateway.py:67-79` includes backend health, memory DB path, and auth
  status in the health payload.
- `deploy/Caddyfile.example:4-11` and `deploy/Caddyfile.example:21-28` expose
  `/health` and `/mcp` for full and read-only MCP hostnames.
- `tools_registry.py:110-119` filters read-only MCP registration by
  `tool.readonly`, and `tools_registry.py:73-79` enforces MCP `confirm=True` for
  registry tools marked confirm-gated.
- `tools_registry.py:41-42`, `tools_registry.py:126-851`, and
  `tests/test_tools_registry.py:41-53` show that registry-exposed mutating MCP
  tools are expected to be confirmation-gated and excluded from read-only MCP.
- `inbox_mcp_readonly.py:44-50` still exposes `read_daily_note`; it reads from
  the local Obsidian vault path computed in `ambient_notes.py`.
- `services.py:88-98` requests broad Google OAuth scopes: Gmail read/modify/send
  and settings, Calendar, Drive, Sheets, Docs, and Tasks.
- `.gitignore:12-20` ignores credential/token files, and `.gitignore:40-48`
  ignores local memory, scheduler, index, and batch state files.
- `git ls-files | rg ...` found only `config/inbox.env.example` and
  `oci_retry.sh` tracked among the searched credential/cloud-state patterns.
- `services.py:198-212` writes token payloads through a lock/temp-file/replace
  helper, but the helper does not set restrictive file permissions itself.
- `services.py:215-232` opens Apple SQLite sources with `mode=ro`, a good
  mitigation for iMessage/Notes/AddressBook-style reads.
- `services.py:114-120` defines the test-mode live-write guard, and
  `rg -n "_assert_live_write_allowed" services.py` found 43 guarded call sites.
- `docs/TESTING_FOR_AGENTS.md:8-18` defines the safe test loop and
  `INBOX_TEST_MODE=1`; `docs/TESTING_FOR_AGENTS.md:23-43` forbids live-write,
  local-data, and provider-specific integration tests unless explicitly opted in.
- `tests/test_services.py:909-951` verifies representative live-write blocking,
  but it does not enumerate every mutating helper.
- `rg -n "@app\\.(post|put|patch|delete)" inbox_server.py` found 95 mutating
  HTTP routes. Many are direct REST endpoints with no per-call `confirm`
  parameter.
- `services.py:3864-3890` uploads files to Drive without calling
  `_assert_live_write_allowed`.
- `services.py:4341-4372` applies raw Sheets formatting and copies sheets
  without a live-write guard.
- `services.py:4476-4492` inserts text into a Google Doc without a live-write
  guard.
- `services.py:6236-6249` RSVPs to a calendar event without a live-write guard.
- `inbox_server.py:3047-3060` exposes ambient start/stop, and
  `services.py:4635-4659` records microphone audio into a transcript buffer.
- `services.py:4702-4714` injects typed text through Quartz events, and
  `inbox_server.py:3098-3113` exposes dictation start/stop.
- `ambient_notes.py:14-21` writes to `~/vault/daily` and `~/vault/ambient`;
  `ambient_notes.py:28-39` appends daily-note content.
- `message_index_store.py:100-117` persists indexed message subject, snippet,
  body text, labels, and raw pointers in `.inbox_index.sqlite3`.
- `scheduler.py:70-80` persists scheduled message text and account data in
  `.inbox_scheduler.sqlite3`.
- `memory_store.py:50-61` persists memory subjects/content/metadata in
  `.inbox_memory.sqlite3`.
- `google_account_resolution.py:24-33` picks
  `INBOX_DEFAULT_GOOGLE_ACCOUNT` when present, otherwise the first service key.
  `config/inbox.env.example:1-9` does not document that default account env var.
- `CONNECTOR_ROADMAP.md:32-45` and `CONNECTOR_ROADMAP.md:216-229` state that
  Google writes should default to `jshah1331@gmail.com` and that this should be
  enforced, not only prompt-documented.
- `batch/batch-runner.sh:61-80` builds raw curl calls for Gmail batch-modify,
  with auth only if `INBOX_SERVER_TOKEN` is present.
- `unsubscribe_bulk.py:10-58`,
  `unsubscribe_all_newsletters.py:10-164`, and
  `unsubscribe_interactive.py:10-67` call the local REST API directly and do not
  add `INBOX_SERVER_TOKEN` headers.
- `oci_retry.sh:7-13` tracks concrete OCI compartment, image, subnet, SSH-key,
  and log paths; `oci_retry.sh:16-52` loops forever launching a public-IP
  instance until success.
- `pyproject.toml:55-61` configures safe/integration/local-data/slow/live-write
  pytest markers and default coverage addopts.
- `DOCS_INDEX.md:136-140` claims "All 736 tests pass"; this was not verifiable
  in this sandbox.
- `pytest --collect-only -q` failed in the bare environment because
  `pytest-cov` options from `pyproject.toml` were not available.
- `INBOX_TEST_MODE=1 uv run pytest -m safe --collect-only -q` first failed
  because `uv` could not access `~/.cache/uv`; with
  `UV_CACHE_DIR=/tmp/uv-cache`, dependency installation then failed on PyPI DNS
  for `googleapis-common-protos`.

## Existing mitigations

- The private server binds to loopback by default:
  `inbox_server.py:3936-3940` runs Uvicorn on `127.0.0.1`.
- The full MCP and read-only MCP HTTP apps also bind to loopback by default:
  `mcp_server.py:148-151` and `inbox_mcp_readonly.py:83-87`.
- `MCP_SETUP.md:246-260` documents the intended topology: keep
  `inbox_server.py` private, expose MCP rather than raw REST, prefer read-only
  MCP remotely, and keep tokens in service env.
- `.gitignore` covers the obvious local secrets and generated sqlite state.
- MCP registry tools use a centralized `readonly` plus `confirm` table, and the
  read-only MCP entrypoint uses `readonly_only=True`.
- `INBOX_TEST_MODE=1` blocks many service-level live writes.
- Apple SQLite reads use `mode=ro`, reducing risk to local Messages/Notes style
  databases.
- `dev.sh:7-8` defaults worktree dev servers to port 9850, which reduces
  primary-vs-dev collisions when agents follow the documented workflow.

## Risk register

### R1. Private REST auth is optional while the REST write surface is broad

Severity: High.

If `INBOX_SERVER_TOKEN` is unset, every local request is accepted
(`inbox_server.py:1317-1320`). The server exposes high-impact mutations:
message send/delete/archive, Gmail filters/labels, calendar create/update/delete,
reminders/tasks, Drive/Docs/Sheets writes, ambient/dictation controls, account
reauth, notification config, memory/index writes, and workflow creates. The MCP
layer adds confirmation, but direct REST endpoints do not.

Why this matters: any local process or misconfigured agent pointed at port 9849
can mutate personal inbox state without per-action confirmation when the token is
unset. This also weakens the "read-only remote MCP first" story if a proxy or
client ever reaches raw REST.

Current mitigations: loopback bind, optional token auth, docs recommending token
separation, MCP confirmation gates.

Gap: token absence is treated as an allowed mode rather than an explicit unsafe
mode. There is no server-level confirmation/preflight policy for direct REST.

### R2. MCP `/health` is intentionally unauthenticated and can leak sensitive metadata

Severity: Medium to High.

`mcp_gateway.py:48-58` bypasses auth for `/health`, and the health payload
includes backend health, memory DB path, auth status, and extra mode payload
(`mcp_gateway.py:67-79`). The backend health response includes configured
account emails and GitHub-token presence (`inbox_server.py:1346-1357`). The
Caddy example exposes `/health` for both full and read-only MCP hostnames
(`deploy/Caddyfile.example:4-11`, `deploy/Caddyfile.example:21-28`).

Why this matters: a public read-only endpoint can disclose account inventory,
local filesystem paths, and whether GitHub is configured. That is useful for
debugging but not necessary for unauthenticated external observers.

Current mitigations: only `/health` and `/mcp` are routed by Caddy; the private
backend remains loopback in examples.

Gap: no sanitized public health mode or auth requirement for health on exposed
MCP hostnames.

### R3. Live-write test guard coverage is incomplete

Severity: High for agent safety, Medium for production.

The repo has a useful live-write guard (`services.py:114-120`) and tests for
representative writes (`tests/test_services.py:909-951`). However, several
mutating helpers do not call the guard:

- `drive_upload` creates Drive files (`services.py:3864-3890`).
- `sheets_format` and `sheets_copy_to` mutate Sheets
  (`services.py:4341-4372`).
- `docs_insert_text` mutates Docs (`services.py:4476-4492`).
- `calendar_rsvp_event` patches an event (`services.py:6236-6249`).
- Local config/favorite writers (`services.py:5476`, `services.py:5579`,
  `services.py:6114`) mutate local user state outside the guard.
- Scheduler and memory store methods write local state directly
  (`scheduler.py:118-157`, `scheduler.py:229-278`,
  `memory_store.py:72-116`, `memory_store.py:173-198`).

Why this matters: `INBOX_TEST_MODE=1` is the documented safety contract for
agents, but it does not prove all write paths are blocked. Tests can accidentally
exercise real providers if a missing guard is combined with live credentials and
insufficient mocking.

Current mitigations: most high-profile provider writes are guarded; safe test
docs exist; many tests use mocks.

Gap: no exhaustive test or static policy mapping all mutating services/routes to
the live-write guard.

### R4. MCP confirmation is not an end-to-end write policy

Severity: High.

The MCP registry properly confirm-gates mutating tools
(`tools_registry.py:73-79`, `tests/test_tools_registry.py:41-53`), but raw REST
and utility scripts bypass MCP. `batch/batch-runner.sh:74-80` posts directly to
`/gmail/batch-modify`; unsubscribe scripts post to unsubscribe endpoints directly
without auth headers (`unsubscribe_bulk.py:10-58`,
`unsubscribe_all_newsletters.py:10-164`, `unsubscribe_interactive.py:10-67`).

Why this matters: a user or agent can accidentally run a helper script against
the primary daily-driver server and perform bulk mailbox changes. Scripts do ask
for user confirmation in some cases, but not all of them enforce server token
use or test mode.

Current mitigations: some scripts prompt interactively; batch runner has
`--dry-run`.

Gap: no shared client wrapper enforcing token presence, target server display,
dry-run preview, or primary-vs-dev warnings for write scripts.

### R5. Credential and token blast radius is large

Severity: High.

`services.py:88-98` asks Google OAuth for broad scopes covering Gmail modify/send
and settings, Calendar, Drive, Sheets, Docs, and Tasks. Token files live under
the repo directory by default (`services.py:56-67`), and GitHub, Maps, and Gemini
keys are read from repo-root text files (`services.py:84-86`). `.gitignore`
protects these names (`.gitignore:12-20`), and `setup_inbox_mcp.sh:17-24`
creates `config/inbox.env` with `chmod 600`.

Why this matters: compromise of the host or checkout grants broad write access
across personal communications and workspace data. The token write helper
(`services.py:198-212`) does not itself set restrictive permissions on token
files, so actual mode depends on umask or existing file state.

Current mitigations: gitignore, local-first design, env-token docs, token
separation advice in `MCP_SETUP.md`.

Gap: no documented token file permission check, scope minimization matrix, or
startup warning for over-broad production tokens.

### R6. Cross-account write routing still depends on defaults and caller discipline

Severity: Medium to High.

`google_account_resolution.py:24-33` honors
`INBOX_DEFAULT_GOOGLE_ACCOUNT` when present, otherwise uses the first service key.
The roadmap says writes should default to `jshah1331@gmail.com` and be enforced
in backend policy (`CONNECTOR_ROADMAP.md:32-45`,
`CONNECTOR_ROADMAP.md:216-229`), but `config/inbox.env.example:1-9` does not
document `INBOX_DEFAULT_GOOGLE_ACCOUNT`.

Why this matters: Drive/Docs/Sheets/Tasks/Calendar writes can land in whichever
account happens to be first when env is unset. For personal systems, wrong
account is a data-placement and privacy bug.

Current mitigations: shared account-resolution helper, tests for some routing
cases, explicit `account` params on many endpoints.

Gap: default-account policy is not surfaced in the default env template and is
not enforced as a startup invariant for write-capable deployments.

### R7. Ambient listening and dictation are high-privacy/high-impact controls

Severity: High.

Ambient capture can be started by REST (`inbox_server.py:3047-3060`), records
microphone audio through `sounddevice` (`services.py:4635-4659`), and writes
transcripts into Obsidian daily notes (`ambient_notes.py:28-39`,
`ambient_notes.py:69-76`). Dictation can be started by REST
(`inbox_server.py:3098-3113`) and injects keyboard events into the current UI
(`services.py:4702-4714`, `services.py:4768-4811`).

Why this matters: these are not ordinary data fetches. Ambient listening can
capture sensitive room audio, and dictation can type into any focused
application. The direct REST endpoints have no per-call confirmation or test-mode
guard.

Current mitigations: loopback bind, server token if configured, availability
checks, local ML.

Gap: no explicit confirmation/startup warning, session timeout, visible active
indicator requirement, or audit trail tied to the REST calls.

### R8. Local persistent stores contain sensitive personal data

Severity: Medium.

The index stores message body text, snippets, labels, senders, recipients, and
raw pointers (`message_index_store.py:100-117`). Scheduler storage includes
scheduled message text and account (`scheduler.py:70-80`). Memory storage keeps
subjects, content, status, and metadata (`memory_store.py:50-61`). These files
are gitignored, but the MCP health endpoint can expose memory DB paths and the
REST index endpoints expose index DB paths and indexed thread data
(`inbox_server.py:3805-3841`).

Why this matters: local sqlite files become a second data lake for personal
communications. Backups, file permissions, path disclosure, and retention policy
matter even if the original providers are protected.

Current mitigations: gitignore, local-only defaults.

Gap: no retention/redaction story, no permission checks, and no clear boundary
around which agents can read index/memory endpoints.

### R9. Tracked cloud automation script can create public cloud resources

Severity: High.

`oci_retry.sh` is tracked and contains concrete OCI compartment, image, subnet,
SSH key, log path, and display-name values (`oci_retry.sh:7-15`). It loops
forever and launches a public-IP A1.Flex instance until success
(`oci_retry.sh:16-52`).

Why this matters: it is outside the core Inbox product, contains cloud resource
identifiers, and can incur cloud activity/cost if run. It also undermines the
repo's "personal connector" boundary by mixing cloud provisioning into the same
checkout.

Current mitigations: none observed beyond being a shell script that must be run
manually.

Gap: no quarantine, dry-run, confirmation, or separation into a private ops repo.

### R10. Validation docs assume a synced environment that this sandbox did not have

Severity: Medium.

`docs/TESTING_FOR_AGENTS.md:8-18` gives a sensible safe loop. In this sandbox,
bare `pytest --collect-only -q` failed because the configured coverage plugin
was unavailable. `uv run` with the default cache failed due `~/.cache/uv`
permission; retrying with `UV_CACHE_DIR=/tmp/uv-cache` then failed on PyPI DNS
for `googleapis-common-protos`. `DOCS_INDEX.md:136-140` claims all 736 tests
pass, but that claim could not be verified here.

Why this matters: future overnight workers may misclassify validation failures
as product failures when they are actually environment/cache/network failures.

Current mitigations: scripts set `UV_CACHE_DIR=/tmp/uv-cache`; safe test docs
exist.

Gap: the agent-safe validation docs do not mention the uv cache override or a
network-free dependency setup path.

## Decisions made during this audit

- Treat the raw REST API as the critical write boundary. MCP confirmation is a
  helpful client policy, but it is not sufficient when scripts and direct clients
  can hit REST.
- Treat account routing as a risk even though helper code exists, because the
  default-account env var is not documented in the env example and roadmap text
  says enforcement is still a work item.
- Treat local stores as sensitive data stores, not caches, because they contain
  message body text, scheduled message text, and memory content.
- Do not run live provider tests, local-data tests, macOS automation, server
  startup, or MCP calls in this queue item.

## Next safe work

### Task 1: Exhaustive live-write guard coverage

Acceptance criteria:

- Add a test or static registry that enumerates every service-level provider
  mutation and asserts it calls `_assert_live_write_allowed` before touching the
  provider.
- Add guards at minimum for `drive_upload`, `sheets_format`, `sheets_copy_to`,
  `docs_insert_text`, and `calendar_rsvp_event`.
- Decide whether local-only writes such as memory, scheduler, favorites,
  notification config, and voice config should be blocked in `INBOX_TEST_MODE`
  or explicitly exempted with tests.

Validation command candidate:

`UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_services.py tests/test_drive.py tests/test_tools_registry.py -q`

Expected status: pass once dependencies are available. In this sandbox, `uv run`
cannot install missing dependencies because network is restricted.

### Task 2: Harden auth and public health responses

Acceptance criteria:

- Require `INBOX_SERVER_TOKEN` for write-capable server startup unless an
  explicit unsafe env var such as `INBOX_ALLOW_UNAUTH_LOCAL=1` is set.
- Either auth-protect MCP `/health` or return a sanitized public payload that
  does not include backend account emails or local DB paths.
- Add tests for unauthenticated full/read-only MCP health behavior and private
  server startup policy.

Validation command candidate:

`UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_server.py tests/test_mcp_gateway.py -q`

Expected status: pass after tests are updated.

### Task 3: Move confirmation/preflight policy into REST for high-risk writes

Acceptance criteria:

- Add server-side confirmation or preflight requirements for high-risk REST
  writes: sends, delete/archive/bulk Gmail operations, account reauth, Drive,
  Docs, Sheets, Calendar mutations, ambient/dictation start, and notification
  tests.
- Keep MCP `confirm=True`, but make direct REST clients satisfy the same policy
  or route through a shared safe client.
- Update `batch/` and unsubscribe scripts to show target server, require token
  when configured, support dry-run, and refuse obvious primary-vs-dev mistakes.

Validation command candidate:

`UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_server_endpoints.py tests/test_gmail_actions.py tests/test_client.py -q`

Expected status: initial failures until endpoint/client contracts are updated,
then pass.

### Task 4: Enforce source-of-truth Google writes

Acceptance criteria:

- Add `INBOX_DEFAULT_GOOGLE_ACCOUNT` to `config/inbox.env.example`,
  `MCP_SETUP.md`, and startup/self-check output.
- For Google writes, fail closed when no default account is configured and no
  explicit account is provided, or make the chosen default visible in a required
  preflight response.
- Add tests proving Docs, Sheets, Drive, Calendar, and Tasks writes route to the
  configured default and never the first dict key by accident.

Validation command candidate:

`UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_server.py tests/test_calendar.py tests/test_drive.py -q`

Expected status: pass after account-routing tests and docs are updated.

### Task 5: Quarantine or remove tracked cloud automation

Acceptance criteria:

- Move `oci_retry.sh` out of the Inbox repo, replace it with a private ops note,
  or make it a non-executable documented example with placeholders only.
- Remove real compartment, subnet, image, SSH-key, and log path values from
  tracked files.
- Add a simple secret/resource-id grep check for OCI OCIDs and private absolute
  paths.

Validation command candidate:

`git ls-files | xargs rg -n "ocid1\\.|/Users/jwalinshah/\\.ssh|assign-public-ip true" --`

Expected status: fail today because `oci_retry.sh` matches; pass after cleanup
or explicit allowlisting.

### Task 6: Make validation reproducible for agents

Acceptance criteria:

- Update `docs/TESTING_FOR_AGENTS.md` to include
  `UV_CACHE_DIR=/tmp/uv-cache` for sandboxed agents.
- Document expected failure modes when dependencies are not synced and network is
  unavailable.
- Consider a `make`/script wrapper for the safe test loop that sets
  `INBOX_TEST_MODE=1`, cache path, and no-live-test marker policy.

Validation command candidate:

`UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe --collect-only -q`

Expected status: pass in a synced or network-enabled environment; failed in this
sandbox due PyPI DNS after uv cache was moved to `/tmp/uv-cache`.

## Validation candidates and observed status

- Required queue validation: `git status --short`
  - Expected after this report is committed: pass with no output.
- Agent-safe unit loop: `INBOX_TEST_MODE=1 uv run pytest -m safe`
  - Expected in a synced environment: pass.
  - Observed here: not run to completion because dependency setup required
    network.
- Focused safety tests:
  `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py tests/test_tools_registry.py tests/test_mcp_gateway.py -q`
  - Expected in a synced environment: pass.
  - Observed here: not run because broader uv dependency resolution failed first.
- Bare pytest discovery: `pytest --collect-only -q`
  - Observed here: failed because `pyproject.toml` adds `--cov` options but the
    bare interpreter did not have `pytest-cov`.
- Uv safe discovery with default cache:
  `INBOX_TEST_MODE=1 uv run pytest -m safe --collect-only -q`
  - Observed here: failed because sandbox could not open `~/.cache/uv`.
- Uv safe discovery with sandbox cache:
  `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest -m safe --collect-only -q`
  - Observed here: failed to download `googleapis-common-protos` due DNS/network
    restriction.
- Lint/type candidates from docs:
  `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .` and
  `UV_CACHE_DIR=/tmp/uv-cache uv run pyright`
  - Expected in a synced environment: pass according to project docs.
  - Observed here: not run because uv dependency setup was blocked by network.

## Non-goals

- No product code changes.
- No secret reads beyond file/path names present in tracked source.
- No Gmail, Calendar, Drive, Docs, Sheets, Tasks, GitHub, WhatsApp, iMessage,
  Notes, Reminders, microphone, dictation, desktop notification, or MCP calls.
- No deploys, pushes, PRs, issue tracker changes, cloud jobs, or OCI operations.
- No attempt to prove whether the user's primary daily-driver Inbox instance is
  currently secured; this audit stayed inside the assigned worktree.

## Unknowns

- Whether the real daily-driver process has `INBOX_SERVER_TOKEN` and
  `INBOX_MCP_TOKEN` set.
- Whether full MCP or read-only MCP is publicly exposed anywhere today.
- Actual OAuth token scopes and token file permissions on the primary checkout.
- Whether `INBOX_DEFAULT_GOOGLE_ACCOUNT` is set in the user's shell or service
  environment.
- Whether `oci_retry.sh` is still intentionally used or only stale local ops
  residue.
- Whether generated sqlite stores are backed up, encrypted, rotated, or
  routinely deleted.
- Whether external agents ever receive raw REST access instead of only curated
  MCP tools.

## Handoff notes

- File changed by this queue item: `docs/overnight/inbox-sym-118-risk-register.md`.
- Product code was intentionally untouched.
- PR creation is out of scope for this Goal Pack item.
- Blocker for deeper automated validation: this sandbox cannot access PyPI, and
  dependencies were not already synced for `uv run`.
