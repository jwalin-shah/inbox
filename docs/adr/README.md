# Architectural Decision Records

Status legend: **Accepted** (decided, in force) · **Proposed** (open for review).

| # | Title | Status | Date |
|---|-------|--------|------|
| [0001](0001-inbox-is-the-canonical-action-layer.md) | Inbox is the canonical action layer; brains are clients | Accepted | 2026-08-19 |
| [0002](0002-consolidated-action-gateway.md) | Consolidated Action Gateway (single mediation module) | Accepted | 2026-08-19 |
| [0003](0003-action-vocabulary-and-record.md) | Action vocabulary and canonical action record | Accepted | 2026-08-19 |
| [0004](0004-risk-tiered-confirmation.md) | Risk-tiered confirmation; lease stays the only primitive | Accepted | 2026-08-19 |
| [0005](0005-brain-identity-and-scoped-tokens.md) | Brain identity and scoped client tokens | Accepted | 2026-08-19 |
| [0006](0006-gmail-draft-parity.md) | Gmail draft parity (close the Luke gap) | Accepted | 2026-08-19 |
| [0007](0007-chatgpt-write-path.md) | ChatGPT write path: wait; native connectors as fallback only | Accepted | 2026-08-19 |
| [0008](0008-raw-evidence-event-spine.md) | Append-only raw evidence event spine | Accepted | 2026-08-25 |

Open items (not yet ADR'd, tracked in `docs/ACTION_GATEWAY_V1.md`):

- Provider-adapter seam (make "backends can change" true).
- Unified `inbox <verb> <noun>` CLI.

Target-state map and phased migration plan: `docs/ACTION_GATEWAY_V1.md`.
