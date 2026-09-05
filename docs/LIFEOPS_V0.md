# LifeOps v0 vertical slice

This slice makes the first durable loop executable without changing the
existing provider adapters or Google Sheets projections:

```text
MCP or HTTP
  -> life.capture
  -> SQLite raw capture
  -> extraction
  -> SQLite commitment state
  -> life.what_needs_me
  -> explicit completion
```

## Durable boundary

`MemoryStore` owns the existing `memory_entries` table and now also exposes a
`LifeOpsStore` over the same configured SQLite database. A capture gets a
`cap_...` ID and is committed before extraction starts. Extraction failure
marks the capture `FAILED` while retaining the exact raw text and error.

Commitments get `com_...` IDs and retain their source capture, owner, state,
next condition, confidence, and timestamps. Commitment projection is
transactional and idempotent for a processed capture.

The first extraction mapping is intentionally small:

- a commitment or action item owned by the user becomes `READY_HUMAN`;
- a commitment owned by another person becomes `WAITING`;
- every nonterminal commitment receives a non-empty `next_condition`;
- `life.what_needs_me` returns ready/review items and expired timed conditions;
- `DONE` items do not resurface.

## Surfaces

- HTTP: `POST /life/capture`, `GET /life/what-needs-me`, and
  `POST /life/commitments/{commitment_id}/complete`.
- MCP: `life_capture`, `life_what_needs_me`, and the confirmation-gated
  `life_complete_commitment` tools.

The current Google Sheets connectors remain available as source/projection
adapters. This slice does not write either named tracker until a live account,
spreadsheet ID, tab, and approval-bound projection contract are verified.

## Action coordination slice

LifeOps does not replace OpenClaw. It provides the provider-neutral contract
above it:

```text
natural language
  -> ActionEnvelope
  -> capability registry
  -> deterministic route
  -> OpenClaw adapter
  -> provider result and fresh read-back (when live)
  -> local action trace
```

The first route family is `task.create`. `scripts/lifeops capabilities sync` reads the
installed OpenClaw plugin and MCP inventories without installing, enabling, or
calling a provider. `scripts/lifeops routes task.create` prints candidate routes and
their proven/configured/unknown state. `scripts/lifeops execute task.create --title
\"...\"` is plan-only by default and writes a local trace. `--live` requires a
proven available route, and R1+ execution is still blocked until the underlying
OpenClaw/Inbox path accepts a server-minted grant. `scripts/lifeops trace <command_id>`
reads the local receipt.

This keeps provider credentials, OAuth, plugins, browser automation, and
workflow execution in OpenClaw. Consequential code/filesystem work remains a
Bridge-owned path; no Bridge call is needed for an ordinary task plan.

## Verification record

On 2026-08-31, the repository-local `.venv` ran the full test suite with
`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider`:
**2,029 tests passed in 102.00 seconds with 84% coverage**. This proves the
current local implementation against its checked-out test environment only.
It does not prove deployment, live Gmail/Calendar/Drive access, OAuth validity,
external writes, or a Bridge/HomeBase execution receipt; those remain separate
gates.

On the same date, the local action-coordination slice was exercised end to end
in plan-only mode: capability inventory sync, deterministic `task.create` route
selection, trace creation, and trace read-back. Command
`cmd_a139357706c64e06a0ad386c72bbc65d` returned `PLANNED` with
`live_execution=false` and the trace confirmed that no provider state changed.
This proves local intent/route/trace plumbing only; it is not proof that a
Google Task was created.

The durable LifeOps store/API vertical slice was also rerun against temporary
SQLite databases on 2026-08-31: `tests/test_lifeops_store.py` and
`tests/test_lifeops_api.py` passed **9 tests in 3.35 seconds**. This covers
capture retention on extraction failure, commitment projection, attention
queries, idempotent processing, completion removal, waiting-condition
resurfacing, API approval checks, and empty-input rejection. The temporary
database run changed no production data and called no external provider.
