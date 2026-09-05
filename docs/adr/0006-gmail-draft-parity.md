# ADR-0006: Gmail draft parity (close the Luke gap)

- **Status:** Accepted
- **Date:** 2026-08-19
- **Deciders:** captain, with DeepSeek Harness

## Context

The "Luke" failure: ChatGPT's native Gmail connector has `list_drafts`,
`create_draft`, `update_draft` (in place), `send_draft`, `send_email`, threaded
reply, archive, labels, forward, trash, attachments. Inbox currently has only
`gmail_create_draft` (`services.py` L1682; `POST /messages/drafts`) — so a brain
that wants to update an existing draft has no Inbox primitive and improvises a
*second* draft (or reaches past Inbox to the native connector).

## Decision

Add the missing Gmail draft primitives to Inbox and register them as catalog
actions (ADR-0003):

```text
gmail.draft.list    GET   /gmail/drafts
gmail.draft.get     GET   /gmail/drafts/{draft_id}
gmail.draft.create  POST  /messages/drafts            (exists; re-map to catalog)
gmail.draft.update  PUT   /gmail/drafts/{draft_id}    (in place — the fix)
gmail.draft.delete  DELETE /gmail/drafts/{draft_id}
gmail.draft.send    POST  /gmail/drafts/{draft_id}/send
```

Threading: `gmail.thread.reply` / `gmail.message.reply` must key on the Gmail
message/thread ID (already partially present via `POST /messages/gmail/reply` with
`msg_id`/`thread_id`/`message_id_header`), so replies hang off the same thread
instead of starting a new one.

Risk classing (ADR-0004): `create`/`update` = `reversible_write`; `send` and
`delete` = `consequential`.

## Alternatives considered

- **Rely on ChatGPT's native Gmail for drafts** (rejected): non-portable, not
  auditable, and contradicts ADR-0001 — it's the fallback, not the path.

## Consequences

- **Positive:** closes the duplicate-draft failure deterministically — the model
  updates the existing draft in place through Inbox.
- **Positive:** draft ops enter the audit trail with `requested_by`.
- **Negative:** adds six endpoints + six MCP tools and their approval-route
  entries (`docs/APPROVAL_ADAPTER_MAP.md`), touching `services.py`,
  `inbox_server.py`, `tools_registry.py`, `mcp_backend.py`.

## Invariant consequences

Promote to `docs/invariants.md` (oracle: `data-quality` → unique ids):
`draft.update` targets an existing Gmail draft ID and never creates a second one.

```text
update(draft_id) ⇒ ∃ draft(draft_id)  ∧  ¬∃ draft' created
```

P0: `gmail.draft.update` on a nonexistent ID fails (no fallback-create). P1:
draft idempotency — replaying a `create` with the same `idempotency_key` returns
the same draft id.

## Rollout

Implement in the order that fixes the failure first: `draft.list`/`get`
(read-only, low risk) + `draft.update` (the fix), then `draft.delete`/`send`.
Each is a thin wrapper over the Gmail `drafts()` resource that already backs
`gmail_create_draft`.

## Related

- ADR-0001 (canonical layer), ADR-0003 (catalog), ADR-0004 (tiers).