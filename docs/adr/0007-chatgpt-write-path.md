# ADR-0007: ChatGPT write path — wait; native connectors as fallback only

- **Status:** Accepted
- **Date:** 2026-08-19
- **Deciders:** captain (wait, over building the sheet bridge)

## Context

Three candidate write paths to Inbox from ChatGPT:

- **A — native ChatGPT connectors write** (works today for first-party surfaces).
- **B — ChatGPT → Inbox MCP directly** (the clean destination; OpenAI gates
  full custom-MCP *write* to Business/Enterprise/Edu — Pro is read/fetch only,
  per OpenAI's developer-mode docs).
- **C — a shared Google Sheet `ACTION_QUEUE`** that ChatGPT writes intent rows
  into and an Inbox worker executes.

`docs/MCP_SETUP.md` already pins the current posture: the `life-ops-inbox` tunnel
is intentionally *read-only*; the full local surface stays owner-only via
`inbox-mcp-full`; repointing the read-only tunnel at the full server is forbidden.

## Decision

**Do not build the sheet bridge (C) now.** Use path A *only* as a convenience
fallback where a native connector is genuinely better today, while treating Inbox
(ADR-0001) as canonical. Design for path B; the ChatGPT-facing MCP stays
read-only-scoped (ADR-0005) until full custom-MCP writes are available to the
user's workspace.

If path B stays blocked and a real workflow is stalling, revisit C — but only
under the constraint that a Sheet row is **untrusted input into the same gateway**
(validate → idempotency → risk class → human decision for consequential → audit),
never a bypass around it. The Sheet must not carry any authority of its own.

Revisit trigger: OpenAI grants write-capable custom MCP to the user's ChatGPT
workspace, OR a concrete job is blocked and native connectors can't cover it.

## Alternatives considered

- **Build the sheet bridge now** (rejected): adds polling/latency/races and a
  shared-edit command surface whose Google ACL ≠ Inbox's per-action approval;
  low value while native Gmail/Calendar/Sheets connectors already cover the
  pro-available writes.
- **Repoint the read-only tunnel at the full server to get writes today**
  (rejected): silently widens permissions of every client already using it —
  explicitly forbidden by `docs/MCP_SETUP.md`.

## Consequences

- **Positive:** no polling bridge to run/secure; least-privilege cloud surface
  preserved.
- **Positive:** when path B opens, it's a scoped-client registration (ADR-0005),
  not a rewire.
- **Negative:** ChatGPT cannot write to Inbox autonomously until path B opens;
  native-connector writes bypass Inbox's audit for now (acceptable, fallback-only).

## Invariant consequences

Promote to `docs/invariants.md` (oracles: `saltzer-schroeder` → Least Privilege,
Fail-Safe Defaults):

```text
cloud_surface(chatgpt) = read_only  while ¬write_mcp_eligibile(workspace)
sheet_route_authority = ∅             # a sheet row never grants execution
```

P0: the ChatGPT-facing tunnel exposes no write tool until eligibility is
confirmed. P1: no sheet/queue input ever short-circuits the gateway's risk +
human-decision path.

## Related

- ADR-0001, ADR-0005 (identity). `docs/MCP_SETUP.md` (read-only tunnel rule).