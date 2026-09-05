# ADR-0003: Action vocabulary and canonical action record

- **Status:** Accepted
- **Date:** 2026-08-19
- **Deciders:** captain, with DeepSeek Harness

## Context

An "executor" taxonomy already exists implicitly (`inbox.gmail.send_email`,
`inbox.calendar.create_event`, `inbox.tasks.write`, …) in
`docs/APPROVAL_ADAPTER_MAP.md`, but there is no first-class action *type*, no
`action_id`, and no `requested_by` on every action. The ChatGPT review proposed
exactly this — a small, stable vocabulary plus a compact `actions` table — and it
maps almost 1:1 onto the existing `approval_requests` schema (which already
carries method, path, body, provider, operation, class, executor, account,
resource, item_count, payload/query hash, state, timestamps).

## Decision

Define a **typed action catalog**: stable, versioned `namespace.verb` action types
with a JSON-Schema parameter contract per action:

```text
gmail.draft.create | gmail.draft.get | gmail.draft.update | gmail.draft.delete | gmail.draft.send
gmail.thread.reply | gmail.message.send | gmail.thread.archive | gmail.thread.label
task.create | task.update | task.complete | task.delete
calendar.event.create | calendar.event.update | calendar.event.cancel
drive.file.upload | drive.file.trash
sheet.values.write | doc.text.insert | note.create | note.update
```

Every execution is recorded as a **canonical action record**:

```json
{
  "action_id": "act_…",
  "type": "gmail.draft.update",
  "target": "draft:abc",
  "requested_by": "chatgpt",
  "idempotency_key": "…",
  "risk_class": "reversible_write",
  "status": "proposed|approved|executed|completed|failed|denied",
  "parameters_sha": "…",
  "provider_result": {},
  "error": "",
  "created_at": "…", "approved_at": "…", "executed_at": "…"
}
```

`approval_requests` evolves into (or is fronted by) an `actions` table carrying
these fields; `audit_log` remains the append-only trail (ADR-0002).

## Alternatives considered

- **Raw Google API verbs exposed directly** (rejected): leaks provider detail to
  every brain and breaks "backends can change."
- **Prompt-only vocabulary** (rejected): unenforceable; contradicts the
  "routing in code, not prompts" principle already in `CONNECTOR_ROADMAP.md`.

## Consequences

- **Positive:** one vocabulary shared by HTTP / MCP / CLI, so all four interfaces
  expose the same semantics.
- **Positive:** enables idempotency, per-action audit, and per-brain attribution
  (ADR-0005) from one record.
- **Negative:** catalog must stay curated — a proliferation of low-level
  actions recreates the raw-API problem. Keep it intent-shaped, per
  `CONNECTOR_ROADMAP.md`.

## Invariant consequences

Promote to `docs/invariants.md` (oracles: `data-quality` → unique ids;
`api-design` → idempotency):

```text
∀ a: action_id(a) unique ∧ requested_by(a) ∈ registered_clients
replay(key) ⇒ ¬re-execute ∧ return(stored(key))
```

P0: `action_id` unique + `requested_by` non-empty. P1: same `idempotency_key`
never produces a second provider side effect.

## Rollout

Land the catalog + `actions` table first (read/write of the record is local,
no provider change), then migrate `approval_store.create_request` to write the
same row shape. Reference implementation: `approval_store.py` schema is the
starting point.

## Related

- ADR-0002 (gateway), ADR-0004 (risk tiers), ADR-0005 (identity).