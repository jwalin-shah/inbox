# TASK-026 Source Convergence Manifest

Base: `61c824f0847d87e2444f14dd5b6413425efb2f24` (origin/main)
Provenance: PR0 `c2844f5…` → PR1 `fe2ceb7…` → PR2 `b5acc062…`

## REQUIRED_CONVERGENCE

| Path | Action | Why |
|---|---|---|
| `event_store.py` | add from PR2 | append-only capture ledger |
| `mcp_control_plane.py` | add from PR2 | ingest-only MCP + Bridge handoff |
| `bridge_work_client.py` | add from PR2 | thin `bridge ingest` client |
| `config/shortcut_registry.example.json` | add from PR2 | control-plane `run_shortcut` deny path (no exec) |
| `tests/test_event_store.py` | add from PR2 | EventStore contract |
| `tests/test_event_capture.py` | add from PR2 | HTTP capture contract |
| `tests/test_mcp_control_plane.py` | add from PR2 | MCP + Bridge handoff contract |
| `.gitignore` | add `.inbox_event_log.sqlite3*` | runtime DB ignore |
| `inbox_server.py` | surgical patch | EventStore wiring + `POST /events/capture` only |
| `tests/test_approval_route_gate.py` | surgical | exception for `/events/capture` |
| `tools_registry.py` | surgical additive | `include_names` + optional `names=` (test dep) |
| `AGENTS.md` | replay PR2 note if needed | docs freshness |
| `MCP_SETUP.md` | replay control-plane section | docs |
| `docs/invariants.md` | replay intake invariants | docs |
| `docs/oracle-map.md` | replay one-line if needed | docs |

## ALREADY_ON_MAIN_EQUIVALENT / MAIN WINS

| Path | Decision |
|---|---|
| `services.py` | **keep main** (Phase-C provider identity/idempotency) |
| `tests/test_task_create_provider_identity.py` | **keep main** (PR2 tip deletes it — do not) |

## STALE_BRANCH_DRIFT (exclude)

- Wholesale `inbox_server.py` / `services.py` from actuator tip
- Any dirty runtime SQLite/logs/credentials
- Prototype LifeOps stores / commitment DBs
- Unrelated Inbox feature drift on actuator branches
- ASSET-087 reconstruction / OCI/GAS templates

## RUNTIME_STATE / SECRET_SENSITIVE / GENERATED

None imported. EventStore default path `.inbox_event_log.sqlite3` is gitignored runtime only.

## EventStore persistence review

**Stores (allowed):** append-only observation rows in `.inbox_event_log.sqlite3` (gitignored): event_id, source, source_object_id, timestamps, event_type, payload, provenance, digest/schema metadata.

**Does NOT own:** SYS-002 projects, Google Tasks lifecycle, provider facts, HomeBase authz, Bridge execution receipts, commitments, provider idempotency sidecars, ApprovalStore, egress audit.

## Authority boundaries

- EventStore = capture/evidence intake history only
- MCP control plane = ingest-only; `confirm=true` ≠ authority; model lease/capability denied; `spawn=0`
- `submit_work` = thin Bridge `ingest` handoff only; Inbox does not execute
- Phase-C provider semantics on main (`services.py`, bindings removed) remain authoritative

## Explicitly excluded branch drift

- wholesale actuator `inbox_server.py` / `services.py`
- PR2 tip deletion of `tests/test_task_create_provider_identity.py`
- runtime DBs/logs/credentials/`.env`
- `state/connector_state.db`, LifeOps prototype stores, ASSET-087 bytes
- OCI/GAS/LaunchAgent/runtime path changes
