# LifeOps triage v1

## Purpose

`life_triage` is the first human-facing LifeOps view. It combines the
read-only `/inbox/now` projection from the primary Inbox service with local
LifeOps commitments and failed captures.

It is a projection, not a new task database:

- Gmail remains the authority for email threads.
- Calendar remains the authority for events.
- Google Tasks remains the authority for tasks.
- LifeOps owns only raw captures and their derived commitment state.
- OpenClaw is an operator surface; it does not become a canonical store.

## Surface

The read-only OpenClaw MCP server is `lifeops_attention` and exposes:

```text
life_triage(limit=25, workflow="", account="")
life_what_needs_me(limit=25)
life_context(limit=25, section_limit=25)
```

`life_context` is the bounded current-memory projection. It groups existing
structured LifeOps memory into projects, goals, decisions, notes, and
commitments, adds Inbox's existing unified cross-source contact profiles to
people, adds Calendar-backed place observations, then includes the current
triage attention items and their source references. Live Gmail contact
scanning is opt-in. It is read-only and reports deferred or unavailable
domains in `limitations`; it does not create a second provider database.

The separate `lifeops_capture` server exposes only confirmation-gated
`life_capture(text, source, confirm=True)`. A successful call returns the
durable capture ID and processing result. It does not write to Gmail, Calendar,
Tasks, messaging, or any provider.

`life_triage` returns stable source references, a state/classification,
source-health information, counts, and a bounded item list. It never writes to
Inbox or any provider. Failed durable captures appear as `capture_failure`
items so a broken extractor cannot silently lose work.

## Current boundary

This slice covers the existing Inbox read model: indexed Gmail action items,
Google Tasks, upcoming Calendar events, and waiting Gmail threads. iMessage,
WhatsApp, Drive, GitHub, Reminders, and research/search results remain separate
read adapters until each has a tested, stable attention projection. They are
not silently represented as healthy merely because Inbox itself is reachable.

## Proof required

Completion requires all of the following:

1. deterministic merge tests pass;
2. the LifeOps MCP read-only server exposes `life_triage`;
3. the tool reaches the authenticated primary Inbox `/inbox/now` route;
4. OpenClaw discovers exactly the intended read-only triage tools; and
5. a live call returns both source health and item/read-model evidence.

The 2026-08-23 proof passed all five checks. The live result contained current
Gmail attention items and reported the existing Inbox index freshness warning as
`index:stale_checkpoint`; that warning is an open data-quality follow-up, not a
triage-service failure.
