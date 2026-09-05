# ADR-0008: Append-only raw evidence event spine

- **Status:** Accepted
- **Date:** 2026-08-25
- **Deciders:** captain

## Context

The existing `.inbox_index.sqlite3` is an operational read model for Gmail and
Messages. It contains normalized items, thread summaries, labels, and sync
checkpoints. It is optimized for current inbox work, not for preserving every
source observation or rebuilding interpretations.

LifeOps needs a World Monitor-style evidence boundary: source observations must
retain their payload, timestamps, provenance, and confidence before any model
labels them as a task, person, project, or claim.

## Decision

Create a separate local SQLite event log at `.inbox_event_log.sqlite3`.

Each raw event contains source and source object identity, observed and occurred
timestamps, actor and object hints, event type, raw payload or content reference,
metadata, provenance, confidence, and schema version.

The event log is append-only at the application boundary. Retries are
idempotent using a deterministic dedupe key over source object, event type,
occurred time, and payload. There are no update or delete methods.

The initial interface is:

- `POST /events/capture` — append one local observation;
- `POST /events/backfill/index` — resumably copy existing indexed messages into
  the evidence log without calling providers;
- `GET /events` and `GET /events/{event_id}` — inspect evidence;
- `POST /triage/messages` — derive a bounded, read-only usefulness queue from
  the operational message index and link each result back to evidence events;
- `GET /sources/registry` — inspect source capability and freshness policy.

The existing message index remains the operational read model. Entity
resolution, interpretation, canonical state, and action queues consume raw
events later and must remain rebuildable projections rather than edits to the
event log. The first interpretation is the message triage projection: it
separates reply-now, task, calendar, waiting, FYI, and archive candidates while
retaining source/account/thread/evidence references and an explanation for each
classification. Its bounded pages preserve category priority and order items
freshest-first within each category, so a limited review starts with the most
recent evidence rather than the stalest matching thread.

## Invariants

```text
∀ e ∈ CapturedEvents: append(e) ⇒ ∃! row(e.event_id)
∀ retry(e): dedupe_key(e) = dedupe_key(e') ⇒ row_count(e) = 1
∀ e ∈ RawEvents: payload(e), provenance(e), observed_at(e) are immutable
∀ s ∈ DerivedState: s = reduce(RawEvents) and may be rebuilt without mutating RawEvents
∀ w ∈ ExternalWrites: side_effect(w) ⇒ mediator(w) = inbox_action_gateway
```

## Consequences

- Raw evidence can be reinterpreted without losing the original message or
  manual capture.
- SQLite remains local and bounded by evidence volume; no graph database or
  Oracle deployment is required for this spine.
- Source adapters must eventually emit events during sync, but that wiring is
  separate from creating the durable contract.
- Historical index backfills are labeled `message.indexed_backfill` and carry
  `raw_payload_available: false`; they are not misrepresented as fresh raw
  provider observations.
- Event storage is not permission to send, edit, archive, or delete anything.
  External writes continue through the existing approval gateway.

## Out of scope for this increment

- automatic person/project identity resolution;
- LLM interpretation or canonical state reducers;
- copying Calendar, Tasks, Drive, or Sheets into the event log;
- push/webhook infrastructure;
- a cloud or multi-machine event store.
