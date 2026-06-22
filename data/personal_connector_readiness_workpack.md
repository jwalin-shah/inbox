# Personal Connector Readiness Workpack

Date: 2026-06-04 PDT

Scope: dry-run/doctor/status only. No sends, deletes, labels, task writes, data export requests, or live sync execution were performed.

## Implementation Summary

- Extended `connector_registry.py` status output with command previews, required env, required permissions, sync readiness, and remediation steps.
- Added Google `gog` auth/sync command definitions and LinkedIn scanner/export readiness to the connector registry.
- Extended `/status/providers` with `syncable`, `remediation`, Google token-diagnostic fallback, and a `job_outreach` workflow row.
- Updated docs and focused tests for the new readiness contract.

## Dry-Run Evidence

Commands run:

```bash
uv run pytest tests/test_connector_registry.py tests/test_server.py -q --no-cov
uv run ruff check connector_registry.py inbox_server.py tests/test_connector_registry.py tests/test_server.py
uv run python -m py_compile connector_registry.py inbox_server.py
scripts/restore_google_oauth.sh
INBOX_SERVER_PORT=9850 INBOX_SERVER_ALLOW_UNAUTHENTICATED=1 uv run python inbox_server.py
GET http://127.0.0.1:9850/connectors/status
GET http://127.0.0.1:9850/status/providers
```

Results:

- Focused pytest: `157 passed in 1.06s`.
- Focused ruff: `All checks passed!`.
- Py compile: passed.
- Full `scripts/validate_agent_safe.sh`: blocked by pre-existing unrelated lint in `scripts/auto-actions.py`, `scripts/export-contacts.py`, `tests/test_approval_route_gate.py`, and `tests/test_gmail_actions.py`.
- Google OAuth dry-run: 3 token files present, refresh OK for all 3, missing scopes 0.
- Temporary server on port 9850 started and was stopped after endpoint checks.

## Connector Checklist

### Google Workspace / `gog`

Registry command validation:

- Auth command: `gog auth status --json`
- Search command: `gog gmail search {query} --max {limit} --json`
- Dry-run sync command: `gog sync --dry-run --json`

Observed status:

- `gog` binary: not installed on PATH.
- `~/Library/Application Support/gogcli`: missing.
- Inbox Google API readiness: Gmail, Calendar, and Sheets are loaded/readable for `jshah1331@gmail.com`, `jwalinshah13@gmail.com`, and `jwalinsshah@gmail.com`.
- Google OAuth script: credentials present, refresh OK for all 3 token files, missing scopes 0.

Remediation:

- Install `gog` and ensure it is on PATH.
- Run `gog auth/login` for intended accounts.
- Run `gog auth status --json`.
- Run `gog sync --dry-run --json` before any live sync.
- Keep existing Inbox Google OAuth path as the current working fallback.

### iMessage / `imsg`

Registry command validation:

- Auth/read probe command: `imsg chats --limit 1 --json`
- Search command: `imsg search {query} --limit {limit} --json`
- Sync command: not supported.

Observed status:

- `imsg` binary: not installed on PATH.
- `~/Library/Messages/chat.db`: exists; status probe reported 36,720,640 bytes.
- Updated `/status/providers`: iMessage local SQLite readable in the temporary server.

Remediation:

- Install `imsg` and ensure it is on PATH.
- Grant Full Disk Access to the launcher process if `chat.db` becomes unreadable.
- Run `imsg chats --limit 1 --json` after install to confirm CLI read access.

### WhatsApp / `wacli`

Registry command validation:

- Doctor command: `wacli doctor --json`
- Search command: `wacli messages search {query} --limit {limit} --json`
- Dry-run sync plan: `POST /connectors/whatsapp/sync` returns `wacli sync --once` without execute.

Observed status:

- `wacli` binary: not installed on PATH.
- `~/.wacli`: missing.
- OpenHuman WhatsApp backing DB: missing.
- `/status/providers`: WhatsApp not configured with blocker `backing_store_missing`.

Remediation:

- Install `wacli` and ensure it is on PATH.
- Run `wacli doctor --json` and address reported auth/session gaps.
- Create or sync the local WhatsApp backing store.
- Review `POST /connectors/whatsapp/sync` dry-run output before any `execute=true` path.

### LinkedIn

Registry command validation:

- Scanner import/readiness probe: `python3 -c "from scripts import linkedin_web_scanner; print(...)"`.
- Search command: not a CLI registry search command yet; Inbox reads LinkedIn from local `linkedin_data.db`.
- Sync command: not supported by registry.

Observed status:

- Python scanner module: importable; auth state `ok`.
- `INBOX_ENABLE_LINKEDIN_SCRAPER`: not set.
- `~/.openhuman/**/linkedin_data/linkedin_data.db`: missing in checked default/staging paths.
- `/status/providers`: LinkedIn not configured with blocker `backing_store_missing`.

Remediation:

- Prefer LinkedIn data export when possible.
- For scanner use, open LinkedIn Messaging in the CDP browser and set `INBOX_ENABLE_LINKEDIN_SCRAPER=1` only for that command.
- Produce/sync `linkedin_data.db`.
- Run index sync after DB creation before relying on outreach workflows.

### Job Outreach

Observed status:

- Gmail side: ready/readable for 3 accounts.
- LinkedIn side: not readable because `linkedin_data.db` is missing.
- `/status/providers` now includes `job_outreach` as a workflow row.
- Current `job_outreach` status: not readable/syncable, blocker `linkedin_not_readable`.

Remediation:

- Keep Gmail as the ready recruiter-email source.
- Add readable LinkedIn message history via export/scanner DB.
- Recheck `/status/providers`; `job_outreach` should become readable only when Gmail and LinkedIn are both readable.

## Endpoint Evidence

Updated `/connectors/status` on temporary port 9850:

- `google`: installed false, auth_state `not_installed`, sync_ready false.
- `whatsapp`: installed false, auth_state `not_installed`, sync_ready false.
- `imessage`: installed false, auth_state `not_installed`, `chat.db` exists, sync_ready false.
- `linkedin`: installed true via `.venv/bin/python3`, auth_state `ok`, required env not present, local DB missing, sync_ready false.

Updated `/status/providers` on temporary port 9850:

- `google_gmail`: configured/authenticated/readable/syncable true for 3 accounts.
- `google_calendar`: configured/authenticated/readable/syncable true for 3 accounts.
- `google_sheets`: configured/authenticated/readable/syncable true for 3 accounts.
- `imessage`: configured/authenticated/readable true.
- `whatsapp`: configured false, blocker `backing_store_missing`.
- `linkedin`: configured false, blocker `backing_store_missing`.
- `job_outreach`: configured true, readable/syncable false, blocker `linkedin_not_readable`.
- Summary: status `degraded`, blocked 1, not_configured 2, ready 10, total 13.

## Safe Local Fixes Landed

- `connector_registry.py`: added readiness metadata and LinkedIn scanner connector.
- `inbox_server.py`: added Google auth diagnostic fallback, `syncable`/`remediation`, and `job_outreach` readiness.
- `docs/CONNECTOR_REGISTRY.md`: documented LinkedIn and readiness checklist.
- `tests/test_connector_registry.py`: added command/readiness assertions.
- `tests/test_server.py`: added token-present/service-not-loaded and job outreach readiness assertions.

