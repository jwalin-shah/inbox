# Approval Adapter Map

Mutating REST routes are denied by default unless the caller supplies a local
per-action `X-Inbox-Approval-Lease` id minted for the exact request.

The prototype lease binds HTTP method, normalized path, provider, operation,
approval class, executor, account/resource references, item count, canonical
payload hash, expiry, nonce, and one-time spend. The gate returns
`can_execute=false` before route handlers call provider helpers when the lease is
missing, unknown, expired, replayed, or mismatched. It does not call providers,
read credentials, or mint OAuth approvals.

`INBOX_TEST_MODE=1` still has a temporary compatibility shim for the historical
`test-local-approval-lease` because the broader `tests/test_server.py` fixture
injects that header and is outside WI-052C's allowed write scope. New approval
gate tests use `mint_local_approval_lease(...)` and prove replay, expiry, and
payload hash/body-change denial.

| Adapter family | Provider | Class | Executor |
|---|---:|---:|---|
| iMessage/Gmail send | `imessage_gmail` | `external_write` | `inbox.messages.send` |
| Gmail compose/reply | `gmail` | `external_write` | `inbox.gmail.send_email`, `inbox.gmail.reply` |
| Gmail archive/delete/unsubscribe/labels | `gmail` | `external_write`, `external_destructive` | `inbox.gmail.modify` |
| Calendar create/update/RSVP/attendees/reminders | `calendar` | `external_write`, `external_destructive` | `inbox.calendar.*` |
| Apple Reminders | `apple_reminders` | `external_write`, `external_destructive` | `inbox.reminders.*` |
| Google Tasks | `google_tasks` | `external_write`, `external_destructive` | `inbox.tasks.*` |
| Scheduled messages/follow-ups | `scheduler` | `external_write`, `external_destructive` | `inbox.scheduler.*`, `inbox.followups.*` |
| WhatsApp launch/send/scroll | `whatsapp` | `external_write` | `inbox.whatsapp.write` |
| GitHub notification mutation | `github` | `external_write` | `inbox.github.notifications` |
| Drive upload/folder/delete/workflow folder | `drive` | `external_write`, `external_destructive` | `inbox.drive.*` |
| Sheets create/update/append/format/tabs/delete/workflow sheet | `sheets` | `external_write`, `external_destructive` | `inbox.sheets.*` |
| Docs create/delete/insert/workflow doc | `docs` | `external_write`, `external_destructive` | `inbox.docs.*` |
| Google OAuth account add/reauth | `google_oauth` | `external_write` | `inbox.google.auth_flow` |

## Local Fail-Closed Route Matrix

`tests/test_approval_route_gate.py` includes a local missing-lease matrix that
patches each provider helper and asserts the helper is not called when the
request has no approval lease.

It also includes per-action lease tests:

- valid task lease reaches a mocked helper once and then replay returns `403`
  with `lease_replayed`;
- changed Gmail compose body returns `403` with `payload_hash_mismatch` before
  the mocked provider helper is called;
- expired task lease returns `403` with `lease_expired` before the mocked
  provider helper is called.
- a lease minted for a sibling Sheets append route cannot authorize the same
  provider's update route; denial happens before the mocked update helper;
- two strict xfail TDD gates pin remaining prototype debt: static
  `test-local-approval-lease` denial even under `INBOX_TEST_MODE=1` after
  fixture migration, and fail-closed denial when an adapter cannot derive a
  stable resource binding instead of falling back to a payload hash.

It also includes a route coverage gate that enumerates every registered FastAPI
`POST`, `PUT`, `PATCH`, and `DELETE` route. Each route must either match
`APPROVAL_ROUTE_RULES` after path-parameter materialization, or appear in the
explicit `MUTATING_METHOD_EXCEPTION_POLICY` table in the test.

Exceptions are no longer a broad local/read-only bucket. Each exception must
name a side-effect class, a provider-safety assertion, and a reason. The tests
fail if an exception uses an undocumented class, has no reason, is marked
provider-unsafe, or no longer matches a registered route.

The exception table is also red-team checked for ambiguous side effects. Risky
exception classes must make the provider boundary explicit in their reason:
`external_read_sync`, `llm_call`, `local_audio_capture`, `local_write`, and
`local_notification` entries must state that they perform no provider writes.
Local-write exceptions must also identify the local target, and local
notification exceptions must stay visibly notification-scoped. Connector sync is
only excepted as a default dry-run/read plan: `ConnectorSyncRequest.execute`
must default to `false`, so future route drift toward executing sync work
becomes visible in the approval-route tests.

The adversarial route tests also pin regressions that are easy to miss during
adapter expansion:

- the critical mutating adapter families must retain missing-lease probes;
- the historical fixed `test-local-approval-lease` is denied outside
  `INBOX_TEST_MODE=1`;
- a lease minted for one provider/path cannot be reused on another provider;
- batch body changes that alter item count fail before the provider helper;
- provider-safe exception reasons may not describe send/delete/archive/
  unsubscribe/RSVP/create-event/create-task or `execute=true` semantics.

Red-team note: `/connectors/{connector_id}/sync` is a route-level exception,
but its request body can represent `execute=true`. The exception is only safe
for the default dry-run/read-plan shape. If live connector sync execution is
kept or expanded, split the dry-run route from the execute route or remove the
exception and require a per-action approval lease for `execute=true`.

| Exception class | Meaning |
|---|---|
| `pure_read` | Read-only operation exposed through a mutating HTTP verb for request-body ergonomics. |
| `external_read_sync` | Provider read or sync path that must not perform provider writes. |
| `llm_call` | Model call for summarization, extraction, triage, or drafting with no provider mutation. |
| `local_audio_capture` | Local microphone/dictation control with no provider mutation. |
| `local_write` | Local filesystem or local state write with no provider mutation. |
| `local_notification` | Local desktop notification with no provider mutation. |

| Surface | Route exercised | Helper patched | Expected executor |
|---|---|---|---|
| Gmail | `POST /messages/compose` | `gmail_compose_send` | `inbox.gmail.send_email` |
| Calendar | `POST /calendar/events` | `calendar_create_event` | `inbox.calendar.create_event` |
| Drive | `POST /drive/folder` | `drive_create_folder` | `inbox.drive.write` |
| Docs | `POST /docs/{document_id}/text` | `docs_insert_text` | `inbox.docs.write` |
| Sheets | `PUT /sheets/{spreadsheet_id}/values/{range_}` | `sheets_values_update` | `inbox.sheets.update_cells` |
| Reminders | `POST /reminders` | `reminder_create` | `inbox.reminders.write` |
| Tasks | `POST /tasks` | `task_create` | `inbox.tasks.write` |
| WhatsApp | `POST /whatsapp/send` | `whatsapp_send` | `inbox.whatsapp.write` |
| Scheduler | `POST /scheduled` | `state.scheduler.schedule_message` | `inbox.scheduler.write` |

Service helpers also retain the `INBOX_TEST_MODE` live-write guard. This work
adds missing helper guards for Drive upload, Sheets rename/format/copy, Docs
text insertion, and Calendar RSVP.
