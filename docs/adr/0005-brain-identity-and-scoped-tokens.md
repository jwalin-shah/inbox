# ADR-0005: Brain identity and scoped client tokens

- **Status:** Accepted
- **Date:** 2026-08-19
- **Deciders:** captain, with DeepSeek Harness

## Context

Auth today is two coarse secrets plus a per-flavor read-only/full split:

- `INBOX_SERVER_TOKEN` — protects the private REST API (used by the MCP hop).
- `INBOX_MCP_TOKEN` — protects the public HTTP MCP gateway.
- read-only vs full is a *server flavor* (`readonly=True`), not per-client.

There is no first-class "which brain is this", so the gateway cannot attribute
actions per brain or enforce per-brain scopes — a prerequisite for ADR-0004's
auto-issue rule and for "who did this" in the audit log.

## Decision

Introduce **registered client credentials**:

- Each client (`chatgpt`, `deepseek-harness`, `codex`, `claude`, `local-model`,
  `scheduler`, `tui`, `cli`) gets a distinct opaque credential (API key / bearer
  token) and a scope set.
- Scopes are the same vocabulary as the action catalog (ADR-0003), e.g.
  `read:*`, `gmail.draft.*`, `task.*`, `calendar.event.*`, `consequential` (a
  marker, not a grant — see below).
- The gateway resolves `caller → client_id → scopes` on **every** request
  (complete mediation; no cached authorization). Comparison via
  `secrets.compare_digest`; missing/invalid → 401, valid but out-of-scope → 403
  (`api-design` §9).
- Every action record carries `requested_by = client_id`.
- Secrets live outside the repo (`infisical://`/`keychain://` encrypted refs, per
  `docs/CONNECTOR_REGISTRY.md`), never plaintext in source.

`INBOX_SERVER_TOKEN` becomes the internal service↔MCP-hop credential (trusted to
impersonate *only* the MCP layer's own client identity), not a blanket grant.

## Alternatives considered

- **Keep two tokens + readonly/full flavors** (rejected): cannot attribute or
  enforce per-brain policy; auto-issue (ADR-0004) would be unsafe.
- **OAuth for every brain** (rejected for now): heavier than the single-user
  local threat model warrants; opaque keys + scopes are enough and stay revocable.

## Consequences

- **Positive:** least privilege per brain; attributable audit; revocable per-brain
  without rotating everything.
- **Positive:** makes the readonly/full split a *scope*, not a separate server,
  so the surfaces can collapse to one gateway with per-client scopes.
- **Negative:** a small `clients` store + scope-check code to build and keep
  fail-closed; the two existing tokens must be migrated (not silently widened).

## Invariant consequences

Promote to `docs/invariants.md` (oracles: `saltzer-schroeder` → Least Privilege,
Fail-Safe Defaults; `api-design` §9 auth):

```text
scope(client) = min(actions the client needs)
allow(client, a) ⇒ a.class ∈ scope(client)
¬authenticated(client) → 401 ; authenticated ∧ ¬scoped → 403
```

P0: every action's `requested_by` is a registered client; missing/invalid
credential never reaches a provider. P1: scope rejection is `403 PERMISSION_DENIED`,
distinct from `401 UNAUTHENTICATED`.

## Rollout

1. Add `clients` + `client_scopes` tables; seed `tui`, `cli`, `scheduler`,
   `deepseek-harness`, `claude`, and read-only-scoped `chatgpt` (per ADR-0007).
2. Wire the gateway's identify step; keep current tokens working via a migration
   mapping during transition.
3. Migrate `INBOX_MCP_TOKEN`-style gateways to the client table; delete the
   two-token check last.

## Related

- ADR-0002 (gateway), ADR-0003 (catalog), ADR-0004 (tiers), ADR-0007 (ChatGPT).