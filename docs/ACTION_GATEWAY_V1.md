# Action Gateway v1 — target state & migration plan

> Companion to `docs/PERSONAL_DATA_GATEWAY_V0.md` (current proof endpoints) and the
> ADRs in `docs/adr/`. This is the **target** architecture, not the current code.
> Status: design-only; no implementation yet (2026-08-19).

## Purpose

Inbox is the canonical action layer (ADR-0001). Brains — ChatGPT, DeepSeek
Harness, Codex, Claude, local models, the scheduler — are interchangeable,
*identified* clients above a single **Action Gateway**. This doc pins the end
state and the reversible path to reach it.

## Target architecture

```text
                ChatGPT   DeepSeek Harness   Codex   Claude   Local   Scheduler
                   │            │             │        │        │        │
                   └────────────┴──────┬──────┴────────┴────────┴────────┘
                                      │  (each: registered client + scoped token)
        ┌────────────────────────── INTERFACES ──────────────────────────┐
        │  stdio MCP (owner/full)   HTTP MCP (readonly cloud / full trusted)│
        │  CLI `inbox …` (thin)     REST (canonical)      TUI (captain)   │
        └─────────────────────────────┬───────────────────────────────────┘
                                      ▼
                 ┌────────────  ACTION GATEWAY  ────────────┐
                 │  identify caller (clients table)        │
                 │  resolve action type (catalog)          │
                 │  classify risk (read/rev/consequential) │
                 │  validate + idempotency key             │
                 │  policy: auto-issue vs human lease      │
                 │  lease check (one-time, body-bound)     │
                 │  record: action + audit + egress        │
                 └───────┬──────────────────┬──────────────┘
                         │                  │
         ┌───────────────▼──────┐    ┌──────▼───────────────┐
         │  provider adapters   │    │  approval_store /    │
         │  google · apple ·    │    │  egress_audit /      │
         │  github · (notion,   │    │  capability_inventory │
         │  mac, browser later) │    │  (owned by gateway)  │
         └───────────────┬──────┘    └──────────────────────┘
                         ▼
          provider APIs / local macOS DBs
```

## Component inventory

| Component | State in v0 | Change |
|---|---|---|
| `inbox_server.py` (FastAPI) | owns all data access | keep; guarded-write handlers become thin adapters calling the gateway |
| `action_gateway.py` | — (logic scattered in server) | **new**: single mediation module (ADR-0002) |
| `approval_store.py` | `approval_requests` + `audit_log` | keep; owned by gateway; evolves into `actions` (ADR-0003) |
| `egress_audit.py` | host allowlist + outbound audit | keep; invoked only through gateway |
| `capability_inventory.py` | read-only catalog/risk metadata | keep as catalog source; gateway reads it |
| `connector_registry.py` | CLI source adapters | keep; provider *sync* adapters (not write-path adapters) |
| `tools_registry.py` + `inbox_mcp_factory.py` | single MCP tool source | keep; tools resolve to catalog actions |
| provider adapters | — (Google calls in `services.py`) | **new seam**: per-provider boundary behind the gateway (open item) |
| CLI | — (scattered scripts) | **new**: unified `inbox <verb> <noun>` (open item) |
| `clients` table | — (two coarse tokens) | **new**: scoped per-brain credentials (ADR-0005) |

## Interfaces matrix (ADR-0005)

| Interface | Transport | Default scope |
|---|---|---|
| REST | HTTP `127.0.0.1:9849` | canonical; per-client scoped |
| MCP full (owner) | stdio | full catalog, human-gated consequential |
| MCP read-only (cloud) | HTTP + Caddy/TLS | `read:*` only; `chatgpt` stays here while write-MCP ineligible (ADR-0007) |
| CLI | subprocess → REST | inherits a named client scope |
| TUI (captain) | HTTP | full; owns the approval `/decide` flow |
| Sheet bridge | n/a this version | **deferred**; if ever built, untrusted input to the same gateway (ADR-0007) |

## Risk-tiered confirmation (ADR-0004)

| Class | Examples | Lease |
|---|---|---|
| `read` | search/read email, task, calendar, notes | none |
| `reversible_write` | draft create/update, task create/update/complete, label, sheet/doc create, note create/update | auto-issued for registered, in-scope clients |
| `consequential` | send, delete, cancel/RSVP, archive, trash, unlink, unsubscribe | human-in-the-loop `/approvals/request` → `/decide` → lease |

The one-time, body-bound lease is the **only** grant of execution; tiers choose
who mints it. Every execution records `requested_by`.

## Starter action catalog (ADR-0003)

```text
gmail.draft.create|get|update|delete|send      gmail.thread.reply|archive|label
task.create|update|complete|delete             calendar.event.create|update|cancel
drive.file.upload|trash                        sheet.values.write
doc.text.insert                                note.create|update
```

Curated, intent-shaped; not a raw passthrough of every Google API verb.

## Open items (not yet ADR'd)

1. **Provider-adapter seam.** `services.py` calls Google directly. Add an adapter
   boundary so `task.create` can target Google Tasks today and another provider
   tomorrow without the model noticing.
2. **Unified CLI.** `inbox task create …`, `inbox draft update …`, wrapping the
   same gateway the MCP/HTTP surfaces use.

## Migration plan (incremental, reversible)

Phases are ordered so each step is independently testable; the AGENTS.md contract
(oracle → tensor equation in `docs/invariants.md` → code → P0/P1 test) applies at
the implementation step, not to this design doc.

0. **Pre-flight (required before code):** read `saltzer-schroeder-oracle.md` +
   `api-design-oracle.md` (done for design); write the P0/P1 tensor equations
   below into `docs/invariants.md`; worktree on `feat/action-gateway` (port 9850+).
1. **Identity (ADR-0005).** `clients` + `client_scopes` tables; seed
   `tui`, `cli`, `scheduler`, `deepseek-harness`, `claude`, read-only `chatgpt`.
2. **Catalog + record (ADR-0003).** Typed action table + `actions` row; migrate
   `approval_store.create_request` to the same shape.
3. **Gateway module (ADR-0002).** Build `action_gateway.py` beside the gate;
   route guarded writes through it behind `INBOX_GATEWAY_ENABLE=1`; prove parity
   against `tests/test_approval_route_gate.py` before defaulting.
4. **Risk-tiering (ADR-0004).** Auto-issue branch for `reversible_write` +
   registered in-scope clients; update `AGENTS.md` and add P0 tests that
   `consequential` and unknown callers never auto-issue.
5. **Cutover.** Flip default to the gateway; keep flag for one release; delete
   dead gate code and fold `/approvals/*` into the gateway.
6. **Draft parity (ADR-0006)** — independent of the above; can land first
   (it fixes the Luke failure today).
7. **Then:** provider-adapter seam, unified CLI, then Notion / notifications /
   browser-computer per `CONNECTOR_ROADMAP.md`.

## Invariant checklist to promote into `docs/invariants.md`

| # | Equation (sketch) | Oracle | Class |
|---|---|---|---|
| I1 | `∀ provider write: side_effect ⇒ gateway.mediate` | Complete Mediation | P0 |
| I2 | `default_decision = deny` (fail-safe) | Fail-Safe Defaults | P0 |
| I3 | `execute(a ∈ consequential) ⇒ human_lease(a) ∧ request_binding(a)` | Separation of Privilege | P0 |
| I4 | `auto_issue(a) ⇒ registered(requested_by) ∧ risk(a)=reversible_write` | Least Privilege | P0 |
| I5 | `replay(idempotency_key) ⇒ ¬re-execute` | api-design §5 | P1 |
| I6 | `¬auth → 401 ; auth ∧ ¬scope → 403` | api-design §9 | P1 |
| I7 | `∀ action: requested_by ∈ registered_clients ∧ action_id unique` | Compromise Recording | P1 |

## Definition of done

A brain performs a reversible edit and a consequential send through Inbox with:
one gateway decision path, a scoped caller identity, a body-bound lease, and an
`actions` + `audit_log` row — and no route/tool that reaches a provider helper
without the gateway.