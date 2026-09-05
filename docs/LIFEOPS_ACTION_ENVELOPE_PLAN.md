# LifeOps action-envelope vertical slice

## Problem

The existing LifeOps slice durably captures intent and commitments, but it
does not yet normalize an executable capability request or route it to the
existing OpenClaw substrate. The first slice must add coordination without
recreating plugins, OAuth, browser automation, workflows, memory, or provider
execution.

## Architecture

```text
LifeOps action envelope
  -> provider-neutral capability registry
  -> deterministic route selection
  -> OpenClaw execution adapter (plan by default; live requires explicit grant)
  -> structured result / verification status
  -> local trace record
```

LifeOps owns the envelope, route policy, and trace metadata. OpenClaw owns
provider/plugin/MCP execution. Inbox provider writes remain behind the existing
server-side approval lease. Bridge is not called for ordinary reversible task
creation; consequential execution remains a later Bridge-owned path.

## Invariants

```text
∀ envelope e: e.capability ≠ "" ∧ e.command_id ≠ "" ∧ e.risk ∈ {R0,R1,R2,R3,R4}
∀ route r selected for e: r.available = true ∧ r.capability = e.capability
∀ live execution e: e.risk = R0 ∨ explicit_grant(e) = true
∀ persisted trace t: t.command_id is unique ∧ secrets(t) = ∅
∀ sync: OpenClaw configuration is read-only; sync never installs, enables, or mutates plugins
```

The fail-safe default is plan-only. A live OpenClaw invocation requires an
explicit `--live` flag and an approval/grant token; the adapter never treats a
normal confirmation boolean as provider authorization.

## Files

- `lifeops/action_envelope.py` — immutable envelope, risk validation, trace store.
- `lifeops/capability_registry.py` — static route policy plus read-only OpenClaw
  plugin/MCP inventory sync and deterministic route resolution.
- `lifeops/executors/openclaw.py` — narrow subprocess adapter that builds and,
  only with an explicit grant, invokes `openclaw agent --json`.
- `lifeops_cli.py` — `capabilities sync`, `routes`, `execute`, and `trace`.
- `pyproject.toml` — editable `lifeops` console entry point.
- `tests/test_lifeops_action_envelope.py` — contract, fail-safe, secret, and
  trace tests.
- `tests/test_lifeops_capability_registry.py` — sync and route-selection tests.
- `tests/test_lifeops_openclaw.py` — command construction and grant gate tests.
- `tests/test_lifeops_cli.py` — harmless command-level tests.
- `docs/invariants.md` — permanent equations and test mapping.
- `docs/LIFEOPS_V0.md` — operator-facing boundary and command examples.

## Steps

1. Add pure contract modules and unit tests with injected subprocess runners.
2. Add the CLI as a thin composition layer; default `execute` to plan mode.
3. Run `lifeops capabilities sync` against the installed OpenClaw CLI in
   read-only mode and store only metadata, not secrets or provider data.
4. Run the focused test suite, then the repository agent-safe suite.

## Edge cases

- OpenClaw missing, malformed JSON, or non-zero exit: sync returns a failed
  readiness result and does not invent an available route.
- A route configured but not probed is `available: null`, never `true`.
- Unknown capability or no available route: resolution fails closed.
- R1+ live execution without a grant: rejected before subprocess creation.
- Secret-looking envelope fields: rejected before persistence or execution.
- Existing dirty LifeOps capture changes are preserved; this slice does not
  rewrite their files or migrate their SQLite schema.

## Grill result

**Pass with one deliberate limitation.** The installed OpenClaw CLI and MCP
registry are real and can be inspected without mutation. However, the current
Inbox task MCP path does not prove that an OpenClaw agent invocation carries the
server-minted Inbox approval lease required for a provider write. The adapter
therefore supports a real plan/trace path now and refuses live R1+ execution
until a grant contract is connected to the underlying executor. A `--live` flag
alone is never treated as authorization.
