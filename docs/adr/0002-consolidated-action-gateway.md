# ADR-0002: Consolidated Action Gateway (single mediation module)

- **Status:** Accepted
- **Date:** 2026-08-19
- **Deciders:** captain (full consolidation, over the thin-orchestrator option)

## Context

The gateway's *decision logic* is currently distributed:

- `inbox_server.py` holds the approval route rules, lease minting, and the
  per-request decision (`APPROVAL_ROUTE_RULES`, `_approval_rule_for_request`,
  `_approval_context_for_action`, `mint_local_approval_lease`,
  `_approval_decision_for_request`), plus the human-in-the-loop endpoints
  (`POST /approvals/request`, `POST /approvals/{id}/decide`).
- `approval_store.py` persists `approval_requests` + `audit_log`.
- `egress_audit.py` enforces the host allowlist and records outbound traffic.
- `capability_inventory.py` classifies tools into categories/risk classes.
- `connector_registry.py` describes provider CLIs and their `action_policy`.

This works, but the enforcement authority is spread across four+ modules, which
makes Complete Mediation hard to prove and invites drift (a new write route that
forgets the gate).

## Decision

Create **`action_gateway.py` as the single mediation module** that owns the whole
decision flow for every action:

```text
identify caller → resolve action type → classify risk
→ validate + idempotency → policy (auto vs human) → lease
→ dispatch to provider → record (action + provider result + audit/egress)
```

The existing modules become *owned components of the gateway*, reachable only
through it, not independent entry points:

- `approval_store.py`, `egress_audit.py` — persistence/observation the gateway composes.
- `capability_inventory.py`, `connector_registry.py` — catalog/policy metadata the gateway reads.
- `inbox_server.py` guarded-write handlers become thin adapters: they parse input,
  build the action, call `gateway.execute(action, caller)`, and return its result.
  The route rules + lease minting + decision logic **move out** of `inbox_server.py`.
- MCP tools (via `tools_registry.py` + `InboxBackend`) and the CLI call the same
  gateway; nothing mints or checks a lease outside it.

"Full consolidation" therefore means: one place *decides and dispatches*; the
stores are its data layer, not separate authorities.

## Alternatives considered

- **Thin orchestrator over existing modules** (rejected per decision): less
  churn but leaves decision authority split across modules.
- **Fill gaps in place, no gateway** (rejected): ADR-0001 needs a provable single
  choke point.

## Consequences

- **Positive:** Complete Mediation becomes a single code path; Economy of
  Mechanism (one mechanism, not several).
- **Positive:** a new write = one registration in the catalog (ADR-0003), not N
  touchpoints.
- **Negative:** migration risk — must be incremental and reversible; see rollout.
- **Negative:** `inbox_server.py` is large (6.7k lines) and entangled with route
  handlers; extracting the gate is the highest-churn step.

## Invariant consequences

Promote to `docs/invariants.md` (oracles: `saltzer-schroeder` → Complete
Mediation + Fail-Safe Defaults; `api-design` → structured errors):

```text
∀ a ∈ Actions: dispatch(a) ⇔ gateway.mediate(a)          # no bypass
default_decision = deny                                    # fail-safe
denial(a) ⇒ reason(a) ∈ STRUCTURED_CODES                  # machine-readable
```

P0: a provider-helper is never called unless `gateway.mediate` returned
`can_execute=true`. P1: `struct reason` is a documented code
(`missing_lease`, `payload_hash_mismatch`, `risk_requires_human`, …).

## Migration / rollout

1. Build `action_gateway.py` *alongside* the existing gate, re-using
   `approval_store`/`egress_audit`/`capability_inventory`; do not delete gate code yet.
2. Route guarded writes through the gateway behind `INBOX_GATEWAY_ENABLE=1`;
   keep the old gate as the default path until parity.
3. Prove parity with the existing `tests/test_approval_route_gate.py` matrix
   (missing lease, replay, body-change, item-count, wrong-route, expiry,
   cross-provider reuse) against the new gateway.
4. Flip default; keep a flag to revert to the old gate for one release.
5. Delete the now-dead gate code in `inbox_server.py` and fold the
   `/approvals/*` endpoints to call the gateway.

Reversibility: step 2–4 keep the old gate switchable. Cutover is a flag, not a
repoint.

## Related

- ADR-0001 (canonical layer), ADR-0003 (vocabulary/record), ADR-0004 (risk tiers).