# WP-182 Workpad

## Issue

- Work pack: `WP-182`
- Title: Harden one error boundary
- Repo: `/Users/jwalinshah/projects/inbox`
- Worktree: `/Users/jwalinshah/projects/.workpack-runs/WP-182`
- Branch: `codex/WP-182-error-boundary-hardening`

## Plan

- Harden the connector search adapter boundary.
- Reject malformed JSON emitted by connector CLIs that are invoked with `--json`.
- Preserve valid JSON normalization and empty-output behavior.
- Cover the malformed-output path with a negative test.

## Validation

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_connector_registry.py tests/test_services.py tests/test_message_sync.py -q --no-cov
```

Result: passed, `91 passed in 5.91s`.

```bash
git diff --check
```

Result: passed.

## Handoff

- PR: https://github.com/jwalin-shah/inbox/pull/59
- Residual risk: connector search commands using `--json` now reject malformed
  non-empty output instead of treating it as text.

---

# MAX-250 Workpad

## Issue

- Linear: `MAX-250`
- Title: Inbox: require explicit API auth for personal-data and write endpoints
- Repo: `/Users/jwalinshah/projects/inbox`
- Worktree: `/Users/jwalinshah/projects/inbox-MAX-250`
- Branch: `codex/MAX-250-inbox-api-auth-fail-closed`
- Base: `origin/main` at `1327e97`

## Plan

- Make `/health` the only unauthenticated endpoint by default.
- Require `INBOX_SERVER_TOKEN` for all non-health endpoints unless an explicit dev/test bypass is enabled.
- Add `INBOX_SERVER_ALLOW_UNAUTHENTICATED=1` as the named bypass for isolated development and tests.
- Update auth tests to prove fail-closed, token success, X-API-Key success, and explicit dev bypass behavior.
- Update README/CLAUDE/config docs for the new default.

## Validation

```bash
uv run pytest tests/test_server.py::TestAuth -q --no-cov
```

Result: passed, 7 passed.

```bash
uv run pytest tests/test_server.py tests/test_server_endpoints.py tests/test_api_contract.py -q --no-cov
```

Result: passed, 186 passed.

```bash
uv run ruff check inbox_server.py tests/conftest.py tests/test_server.py
```

Result: passed.

```bash
git diff --check
```

Result: passed.

```bash
scripts/validate_agent_safe.sh
```

Result: passed. Ruff passed, Bandit completed with existing warnings only, and safe pytest passed with 11 passed and 874 deselected.

Review rerun after PR #43 landed:

```bash
uv lock --check
```

Result: passed.

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_server.py -q --no-cov
```

Result: passed, 126 passed.

```bash
scripts/validate_agent_safe.sh
```

Result: passed. Ruff passed, Bandit completed with existing warnings only, and safe pytest passed with 11 passed and 874 deselected.

```bash
git diff --check
```

Result: passed.

## Handoff

Pending PR.

## Portfolio Readiness Reconciliation - 2026-05-12

Scope: part of the workspace-wide portfolio readiness goal. Do not reset this
checkout; it contains active connector/account-routing work plus generated
architecture artifacts.

Live status at reconciliation:

- Branch: `main`
- Dirty surface: connector registry, WhatsApp/OpenHuman sync, Google auth
  diagnostics, Gmail filter audit, account/auth endpoints, tests, scripts,
  runbooks, `.gitignore`, and `docs/architecture/`
- Architecture candidates: `docs/architecture/linear-issue-candidates.md`
  names Personal Data Connector, account routing, and API contract follow-up
  slices.

Validation run:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_connector_registry.py tests/test_services.py tests/test_message_sync.py -q --no-cov
```

Result: passed, `84 passed in 1.04s`.

```bash
uv run ruff check tests/test_services.py tests/test_connector_registry.py tests/test_message_sync.py
```

Result: passed.

```bash
git diff --check
```

Result: passed.

Reconciliation fix applied:

- `tests/test_services.py` now clears `INBOX_TEST_MODE` only inside mocked
  AppleScript/Gmail write-path tests. The explicit live-write guard tests still
  set `INBOX_TEST_MODE=1` and prove the production guard blocks real write
  surfaces.

Next handoff:

- Preserve current work as a branch/PR or Linear issue before further
  architecture refactors.
- First implementation issue should start from Personal Data Connector, but
  only after deciding whether connector scripts and WhatsApp scanner belong in
  this repo or a separate personal-data adapter package.

## Gemini Secondary Review - 2026-05-13

Branch created to preserve the dirty state without leaving the work only on
`main`: `codex/inbox-preservation-split-review`.

Gemini was run in read-only plan mode as a secondary reviewer for the Inbox
preservation slice. It recommended against turning the whole dirty checkout into
a single PR because the current diff mixes several separable slices:

- Personal Data Connector registry and connector search/sync endpoints:
  `connector_registry.py`, `docs/CONNECTOR_REGISTRY.md`, connector endpoint
  additions in `inbox_server.py`, client helpers in `inbox_client.py`, and
  `tests/test_connector_registry.py` / connector endpoint tests.
- WhatsApp/OpenHuman local store integration: WhatsApp source support in
  `services.py`, `message_sync.py`, `inbox.py`, and related tests/scripts.
- Google auth and Gmail filter diagnostics: `google_auth_diagnostics`,
  `/accounts/auth-status`, `/gmail/filters/audit`, and
  `docs/GOOGLE_AUTH_RUNBOOK.md`.
- Calendar and classifier quality fixes: calendar selection/dedupe behavior and
  dev-notification classifier handling.
- Generated/review artifacts: `.agent-stack-review/` and
  `docs/architecture/`.

Decision for the next handoff: do not create one broad "everything dirty" PR.
Use this branch as the preservation checkpoint, then split into reviewable PRs
with the connector registry first. Generated review artifacts should stay out of
implementation PRs unless a repo maintainer explicitly wants to publish the
architecture report.

Validation rerun on `codex/inbox-preservation-split-review`:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_connector_registry.py tests/test_services.py tests/test_message_sync.py -q --no-cov
```

Result: passed, `84 passed in 1.82s`.

```bash
uv run ruff check tests/test_services.py tests/test_connector_registry.py tests/test_message_sync.py
```

Result: passed.

```bash
git diff --check
```

Result: passed.

---

# Command Center Slice - 2026-05-27

## Scope

- Branch: `codex/inbox-safe-daily-brief-slice`
- Added read-only command center endpoint for the "one place" Inbox surface.

## Implemented

- `GET /inbox/command-center`
- `InboxClient.command_center(...)`
- MCP/tool registry route `get_command_center`
- TUI refresh prefers the command-center endpoint when available
- `MessageIndexStore.source_counts()`
- Source coverage for indexed sources such as Gmail, iMessage, WhatsApp, and
  LinkedIn
- Agent lanes for `capture`, `triage`, `draft`, and `browser_exec`

## Validation

Reported during implementation:

```bash
focused tests
```

Result: passed, 6 passed.

```bash
broader related slice
```

Result: passed, 61 passed.

```bash
ruff on touched files
```

Result: passed.

Verified after restarting main server:

```bash
scripts/validate_agent_safe.sh
```

Result: passed. Ruff passed, Bandit completed with existing warnings only,
message sync CLI smoke passed, and safe pytest passed with 20 passed and 945
deselected.

```bash
curl -H "Authorization: Bearer $INBOX_SERVER_TOKEN" \
  "http://127.0.0.1:9849/inbox/command-center?limit=3"
```

Result: returned `read_model: command_center`, six queues, source coverage,
agent lanes, approval candidates, now items, and waiting threads.

## Residual Risk

- Live `/inbox/command-center?limit=3` on the main data set took about 41
  seconds. The endpoint works, but performance should be improved before
  treating it as a fast dashboard refresh path.

## Next

- Commit this branch as a preservation point.
- Add a follow-up slice to make command-center refresh latency bounded.
