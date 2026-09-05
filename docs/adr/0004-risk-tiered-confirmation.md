# ADR-0004: Risk-tiered confirmation; lease stays the only primitive

- **Status:** Accepted
- **Date:** 2026-08-19
- **Deciders:** captain (risk-tiered, over strict all-human)

## Context

Today **every** provider write requires a human-minted, body-bound, one-time
`X-Inbox-Approval-Lease` (see `docs/PER_ACTION_LEASE_IMPLEMENTATION_SEQUENCE.md`,
`_approval_decision_for_request` in `inbox_server.py`). That is maximally safe but
heavy: a reversible edit (fix a draft, add a task) still costs a
`/approvals/request` → human `/decide` → replay round-trip, which pushes
autonomous use toward native connectors that bypass Inbox.

The ChatGPT review proposed three levels: read / reversible-write / consequential,
with reversible writes allowed and consequential requiring confirmation.

## Decision

Adopt **three risk classes**, but keep the lease as the *only* enforcement
primitive — policy now decides whether a lease is auto-issued or human-required:

| Class | Examples | Confirmation |
|---|---|---|
| `read` | search/read email, task, calendar, notes | none |
| `reversible_write` | draft create/update, task create/update/complete, label apply, sheet/doc create, note create/update | auto-issue one-time body-bound lease for **identified trusted** callers |
| `consequential` | send, delete, cancel/RSVP, archive, trash, unlink, unsubscribe, anything publishing/irreversible | human-in-the-loop approval (`/approvals/request` → `/decide` → lease) |

Rules:

1. The lease (nonce + TTL + `payload_hash` + `query_hash` + `item_count` +
   one-shot spend + route/provider/account/resource binding) is the **only**
   thing that grants execution. Adding tiers changes *who mints* the lease, not
   *whether* it's required.
2. Auto-issue applies only to a caller that is a **registered, identified**
   client (ADR-0005) whose scope includes that action class. Unknown/unscoped
   callers stay fail-closed.
3. Every execution — auto or human — writes the `actions`/`audit_log` row with
   `requested_by`, so an auto-approved reversible write is still attributable and
   revertible-by-record.

The `confirm=True` MCP flag and `ToolAnnotations` (readOnly/destructive/idempotent
hints) remain as client-facing signals on top of server enforcement.

## Alternatives considered

- **Keep strict all-writes-human** (rejected): safe, but the approval round-trip
  drives autonomous use to bypass paths.
- **Fully autonomous for trusted brains** (rejected): breaks the write-safety
  rule for consequential/destructive actions and loses human power-of-review where
  it matters most.

## Consequences

- **Positive:** reversible day-to-day edits flow without friction; send/delete/
  cancel stay human-gated; all of it audited and attributed.
- **Positive:** Separation of Privilege holds on consequential actions (identity
  + human lease + body binding).
- **Negative:** **this changes the `AGENTS.md` write-safety rule**, which
  currently says external sends *and* calendar writes need human approval.
  Under this ADR, calendar `create`/`update` (reversible) may auto-issue;
  calendar `cancel`/RSVP and mail/message sends remain human. `AGENTS.md` must be
  updated in the same change that lands the tiers.
- **Negative:** "trusted caller" must be a concrete, revocable, per-client scope
  (ADR-0005), or auto-issue becomes a hole.

## Invariant consequences

Promote to `docs/invariants.md` (oracle: `saltzer-schroeder` → Fail-Safe
Defaults + Separation of Privilege):

```text
default_decision = deny
auto_issue(a) ⇒ requested_by(a) ∈ registered_clients ∧ risk(a) = reversible_write
execute(a ∈ consequential) ⇒ human_lease(a) ∧ request_binding(a)
```

P0: no provider side effect without a lease; consequential never auto-issues.
P1: `reversible_write` auto-issue requires a registered client with the matching
scope.

## Rollout

1. Add `risk_class` to the action catalog (ADR-0003).
2. Add `clients`/scopes (ADR-0005) first, so auto-issue has something to check.
3. Introduce the auto-issue branch in the gateway for `reversible_write`, leaving
   `consequential` on the existing human path.
4. Update `AGENTS.md` and `docs/invariants.md` in the same change; add P0 tests
   that `consequential` never auto-issues and unknown callers never auto-issue.

## Related

- ADR-0002 (gateway), ADR-0003 (catalog), ADR-0005 (identity).