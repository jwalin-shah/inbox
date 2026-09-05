# ADR-0001: Inbox is the canonical action layer; brains are clients

- **Status:** Accepted
- **Date:** 2026-08-19
- **Deciders:** captain, with DeepSeek Harness

## Context

The same personal data (Gmail, Calendar, Tasks, Drive, Sheets, Docs, iMessage,
Notes, Reminders, GitHub) is reachable from several "brains": ChatGPT, DeepSeek
Harness, Codex, Claude, local models, and the scheduler. Left unmediated, each
brain grows its own connectors and its own access rules:

```text
ChatGPT → Gmail/Calendar/Notion/Drive connectors
DeepSeek → different tools
Codex → another tool set
local   → another integration
```

The repo already embodies the opposite direction: `docs/PERSONAL_DATA_GATEWAY_V0.md`
requires personal-data operations go through the local Inbox API/MCP gateway, and
`CONNECTOR_ROADMAP.md` defines the four-layer model (source adapters →
normalization → policy → intent tools). The ChatGPT review of the "Luke draft"
failure independently concluded the same thing: the built-in connectors are useful
but must not become the architecture.

## Decision

**Inbox (server + Action Gateway) is the canonical authority for personal-data
actions.** Brains are interchangeable, *identified* clients that sit above it.
They reach it only through the Inbox interfaces (HTTP / MCP / CLI / TUI) and never
bypass the gateway for writes. Inbox owns:

- the normalized action vocabulary and semantics,
- policy (account routing, risk tiers, confirmation rules),
- execution history and the audit trail,
- provider credentials and rate/backoff handling.

Consequence for the recent failure mode: a brain that cannot update a draft must
get a deterministic gateway answer ("no such action / requires approval"), not
improvise a second draft through a different connector. Native ChatGPT connectors
are a fallback convenience, never the canonical write path (see ADR-0007).

## Alternatives considered

- **Each brain owns its integrations** (rejected): fragments policy and audit,
  duplicates connectors, and makes brains "architecturally special."
- **ChatGPT native connectors as the primary write path** (rejected): richest
  today for Gmail, but not portable, not auditable, and out of Inbox's control.

## Consequences

- **Positive:** one policy point, one audit trail, cheap brain replacement
  (glue is per-brain adapter code only, ~100 lines).
- **Positive:** backends can migrate without the model changing what it calls.
- **Negative:** Inbox must keep connector parity high enough that brains rarely
  need a native fallback — Gmail draft parity (ADR-0006) is the first example.
- **Constraint:** every new write capability lands in the gateway first, then is
  surfaced to MCP/CLI/HTTP, never the reverse.

## Invariant consequences

Promote to `docs/invariants.md` at implementation time (oracle:
`saltzer-schroeder` → Complete Mediation):

```text
∀ w ∈ WriteActions: side_effect(w) ⇒ mediator(w) = inbox_action_gateway
```

P0: every provider mutation is observable as an `actions` row with
`requested_by` set. P1: `provider_side_effects > 0` implies `gateway.mediate(w)`
completed first.

## Related

- ADR-0002 (gateway consolidation), ADR-0007 (ChatGPT write path).
- `docs/PERSONAL_DATA_GATEWAY_V0.md`, `CONNECTOR_ROADMAP.md`.