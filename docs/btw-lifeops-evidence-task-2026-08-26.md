# BTW → LifeOps bounded evidence task

## Purpose

Give BTW a measurable, read-only job behind LifeOps without giving it Inbox
credentials, provider-write authority, secrets, or arbitrary host control.
This is a work order, not a claim that BTW is already connected to LifeOps.

## Assigned job

Use the synthetic packet `synthetic-btw-probe-001` to answer:

> Who is Air Canada's current CEO?

The packet must use intent `current_state`, the bounded queries
`Air Canada chief executive` and `succeeded Air Canada CEO`, `k=20`,
`take=10`, `allow_web=false`, and `allow_writes=false`. The worker may make
exactly one `retrieve_facts` call.

## Required result

Return only a normalized evidence result containing:

- LifeOps/evidence-packet request ID and BTW upstream request ID;
- dated fact IDs and fact text used for the answer;
- `facts_by_recency`, `evidence_features`, `reason_codes`, and `routing`;
- retrieval timing and explicit missing/ambiguous/conflict reasons.

The answer must distinguish retrieved evidence from current truth. If the
packet is insufficient or contradictory, return that state instead of filling
the gap from model memory.

## Acceptance checks

1. The restricted worker handshake succeeds and exposes only the approved
   read surface.
2. The request contains the exact synthetic packet and query strings.
3. The receipt contains both request IDs and no secret or personal source ID.
4. The result cites dated evidence or an explicit insufficiency reason.
5. No write, shell, filesystem, provider, or worker-control operation occurs.
6. The run is reproducible offline through BTW's existing conflict/eval
   harness.

## Current blockers

- `btw-v1` has the usable retrieval client/MCP and offline conflict tests, but
  no `evidence_packet` adapter into LifeOps.
- `btw-v2` is currently documentation-only.
- BTW's MCP request log is append-on-failure, so the worker path is not yet
  filesystem-pure read-only.
- A live retrieval proof requires its own credential and network boundary;
  none is passed through LifeOps for this task.

## Progress measures

Track these per run: handshake success, exact-query match, evidence-hit count,
dated-evidence rate, unsupported/ambiguous rate, median latency, write count,
secret-access count, and receipt completeness. Do not report the task as
complete until all acceptance checks pass.

## Next implementation boundary

Build the adapter in a separate BTW worktree with synthetic input first. It
should consume an `evidence_packet` over the restricted LifeOps worker
transport and emit the normalized result locally. Only after the offline
acceptance checks pass should a separately approved live source be considered.
