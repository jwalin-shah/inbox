# Personal Data Gateway v0

Inbox server is the canonical gateway for normal personal-data operations. Do not use built-in Gmail, Calendar, or Drive tools as the default path when Inbox can read or propose the same operation locally.

## Canonical Entry Points

| Need | Local API | MCP tool | Account / attribution |
| --- | --- | --- | --- |
| Gateway health and parity | `GET /gateway/status` | `get_personal_data_gateway_status` | Provider rows include account lists, blockers, and remediation. |
| Read-only proof | `POST /gateway/read-proof` | `prove_personal_data_gateway_reads` | Lists Gmail, Calendar events, and Google Tasks through Inbox only; rows include source account attribution and blockers. |
| Multi-Gmail readiness | `POST /gateway/gmail-readiness` | `prove_multi_gmail_readiness` | Dry-run metadata proof for `jwalinshah13@gmail.com` and `jshah1331@gmail.com`; returns loaded accounts plus inbox/unread count estimates. |
| Calendar read | `GET /calendar/events`, `GET /calendar/events/{event_id}`, `GET /calendar/search` | `list_calendar_events`, `get_calendar_event`, `search_calendar_events` | Use `account` and `calendar_id`; responses include `account`, `calendar_id`, and `event_id`. |
| Calendar create/update | `POST /calendar/events`, `PUT /calendar/events/{event_id}` | `create_calendar_event`, `update_calendar_event` | Requires explicit account selection when ambiguous and a per-action approval lease. |
| Gmail search/triage | `GET /gmail/search`, `GET /gmail/conversations`, `GET /inbox/needs-action` | `search_email`, `list_inbox_threads`, `list_needs_action` | Use `account`; rows carry Gmail account/thread/message attribution. |
| iMessage lookup | `GET /conversations?source=imessage`, `GET /messages/imessage/{conv_id}`, `POST /search` with `connector:imessage` | `list_message_threads`, `get_message_thread`, `search_personal_data` | Local Messages database; rows carry source, conversation/message id, sender, timestamp. |
| WhatsApp readiness | `GET /connectors/status`, `POST /connectors/whatsapp/sync` | `get_connectors_status`, `plan_connector_sync` | Reports `wacli` install/auth/storage state. Sync is dry-run by default. |
| Tasks/todos | `GET /tasks/lists`, `GET /tasks`, `POST /tasks`, `PUT /tasks/{task_id}` | `list_task_lists`, `list_tasks`, `create_task`, `update_task` | Use `account`, `list_id`, and task ids. Writes require approval. |
| Sheets/app tracker | `GET /sheets`, `GET /sheets/{spreadsheet_id}/values/{range_}` | `list_sheets`, `read_sheet_values` | Use `account`, `spreadsheet_id`, and A1 range. Writes require approval. |
| Drive/Docs | `GET /drive/files`, `GET /docs` | `list_drive_files`, `list_docs` | Use `account`; rows include file/document ids. |

## Review Before Write

External writes are blocked unless the caller presents a per-action `X-Inbox-Approval-Lease` minted for the exact method, path, query, body, account, resource, and item count. Dry-run/proposal endpoints never apply provider mutations.

Useful preflight/proposal paths:

```bash
curl -s http://127.0.0.1:9849/gateway/status
curl -s -X POST http://127.0.0.1:9849/gateway/read-proof \
  -H 'Content-Type: application/json' \
  -d '{"account":"","gmail_limit":5,"calendar_limit":10,"task_limit":10}'
curl -s -X POST http://127.0.0.1:9849/gateway/gmail-readiness \
  -H 'Content-Type: application/json' \
  -d '{"accounts":["jwalinshah13@gmail.com","jshah1331@gmail.com"]}'
curl -s -X POST http://127.0.0.1:9849/gateway/dry-run/ahmed-office-location-calendar-update \
  -H 'Content-Type: application/json' \
  -d '{"event_id":"b9quemrk7mua74qfv1b707rik0","calendar_id":"primary","account":"","query":"Ahmed office location"}'
```

The read proof calls only Gmail search/list, Calendar events read, and Google Tasks list read. Missing auth or account loading is returned as per-source blockers; it does not call send, create, update, complete, or delete helpers.

The Gmail readiness proof calls only Gmail profile and message-list metadata reads. It does not fetch message bodies, send mail, delete, label, archive, or mark messages read/unread.

The Ahmed dry-run searches iMessage, reads the target calendar event when a calendar service is loaded, extracts a candidate office location, and returns a proposed `PUT /calendar/events/b9quemrk7mua74qfv1b707rik0` body. It does not call `calendar_update_event`.

## Diagnostics

`GET /gateway/status` returns:

- `parity_matrix`: local API and MCP coverage for Gmail, Calendar, Drive/Docs, iMessage, WhatsApp readiness, tasks, and Sheets.
- `providers`: loaded/readable/syncable/writable state with account lists and blockers.
- `connectors`: local CLI install/auth/storage checks for `gog`, `imsg`, `wacli`, LinkedIn, Discord, and X/Twitter.
- `missing_connector_diagnostics`: compact next fixes for unavailable connectors.
- `infisical`: secret-name-only gaps. It reports expected secret names such as `INBOX_GOOGLE_OAUTH_CLIENT_JSON` and whether the `infisical` CLI is installed, but never reads or prints secret values.

If live connectors are unavailable, the correct outcome is a dry-run evidence report with exact endpoint, command preview, missing binary/auth/storage diagnostics, and next fixes. Do not weaken checks to claim full readiness.

## Validation Evidence

The connector substrate is validated with the focused inbox suites that cover the
connector registry, calendar/todo control, MCP gateway surface, and the REST
approval gate. The read-only proof endpoints (`POST /gateway/read-proof`,
`POST /gateway/gmail-readiness`) use POST only to accept a request body; they call
provider list/read helpers exclusively and never invoke a mutation helper, so they
are classified as `external_read_sync` exceptions in the approval-route policy
alongside the existing `POST /search`, `POST /query`, and
`POST /gateway/dry-run/...` read paths.

Run the focused suites:

```bash
INBOX_TEST_MODE=1 uv run pytest \
  tests/test_connector_registry.py \
  tests/test_calendar.py \
  tests/test_tools_registry.py \
  tests/test_mcp_gateway.py \
  tests/test_inbox_calendar_todo_control.py \
  tests/test_server.py \
  tests/test_services.py \
  tests/test_approval_route_gate.py \
  -q --no-cov
```

Last local result: `365 passed` (validated 2026-06-04, `INBOX_TEST_MODE=1`, 1.58s). Per-suite counts:

| Suite | Result |
| --- | --- |
| `tests/test_connector_registry.py` | 8 passed |
| `tests/test_calendar.py` | 26 passed |
| `tests/test_tools_registry.py` | 15 passed |
| `tests/test_mcp_gateway.py` | 10 passed |
| `tests/test_inbox_calendar_todo_control.py` | 5 passed |
| `tests/test_server.py` | 156 passed |
| `tests/test_services.py` | 73 passed |
| `tests/test_approval_route_gate.py` | 72 passed |

`ruff check` is clean on all connector substrate files and their tests.

The approval-route gate suite specifically asserts:

- `test_all_mutating_routes_are_approval_gated_or_explicitly_excepted`: every
  guarded-method route is either approval-gated or holds an explicit
  read-only/provider-safe exception. The two gateway proof endpoints are listed as
  `external_read_sync` exceptions with a `no provider write` reason.
- `test_capability_inventory_routes_align_with_approval_policy`: every MCP/REST
  capability with a guarded method either requires an approval lease (writes) or
  has an explicit read/draft exception.
- The lease-binding probes confirm personal-data writes (Gmail send, Calendar
  create/update, Drive/Docs/Sheets writes, Tasks/Reminders, WhatsApp send,
  scheduler, connector sync execute) fail closed before the provider helper unless
  a per-action `X-Inbox-Approval-Lease` matching method, path, query, body,
  account, resource, and item count is presented. Review-before-write is preserved.

Project safe lanes used during validation:

```bash
INBOX_TEST_MODE=1 uv run python message_sync.py --smoke   # {"ok": true}
INBOX_TEST_MODE=1 uv run pytest -m safe -q --no-cov        # 25 passed
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py tests/test_services.py \
  -k "test_mode_blocks" -q --no-cov                        # live-write guard slice, 3 passed
```

`ruff check` is clean for every file in the connector substrate
(`connector_registry.py`, `inbox_server.py`, `services.py`, `tools_registry.py`,
`scripts/inbox_calendar_todo_control.py`, and the corresponding tests).
