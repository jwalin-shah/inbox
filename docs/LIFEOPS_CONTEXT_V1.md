# LifeOps current context v1

## Problem

LifeOps already has durable captures, commitments, structured memory entries,
and an authenticated Inbox `inbox_now` projection. Those pieces are useful
individually, but agents still have to call several tools and decide which
records belong together. OpenHuman's strongest product lesson is a readable
current-memory projection over raw evidence, not another provider database.

This slice adds that projection without changing source ownership.

## Ownership

- Gmail, Calendar, Google Tasks, Messages, Drive, and Contacts remain owned by
  their existing providers and Inbox adapters.
- LifeOps owns raw captures and derived commitments only.
- `life_context` is a bounded read model. It is not a synchronization job,
  canonical contact store, embedding store, or write queue.
- Every item retains a source reference or an explicit local-memory reference.

## Data flow

```text
Inbox /inbox/now ───────┐
LifeOps commitments ────┼─> context projection ─> life_context MCP read
MemoryStore entries ───┐          │
unified contact profiles ─┐      │
Inbox contact addresses ──┤      │
Calendar upcoming events ─┘      │
                                  ├─ attention
                                  ├─ people
                                  ├─ place observations
                                  ├─ projects
                                  ├─ goals / decisions / notes
                                  ├─ commitments
                                  └─ source health + limitations
```

The projection is generated on demand and is intentionally bounded by per-
section limits. It groups existing structured entries by `memory_type`, adds
Inbox's existing `inbox.unified_contacts.v1` profiles to the people section,
then adds current triage items, explicit contact addresses, explicit rows from
Inbox's canonical LifeOps project-tracker projection, and source references.
Project entries are conservatively grouped by a normalized name while retaining every
supporting memory/capture or sheet-row reference. Live Gmail scanning is
disabled by default; callers can explicitly request it for a bounded contact
refresh. It does not infer new projects from arbitrary text in this slice.
Confirmed LifeOps captures may persist extractor-returned people and project
records as local memory entries; those records retain the originating capture
ID in their provenance.

## Contract

`life_context(limit=25, section_limit=25, include_live_gmail=false,
calendar_days=7)` returns:

- `schema_version`: `lifeops.context.v1`;
- `checked_at` and `read_only`;
- `sections.attention`: current Inbox/LifeOps attention items;
  curated open Email Action Queue rows may also appear here, clearly marked
  with `attention_class=curated_email_action` and their spreadsheet-row
  provenance;
- `sections.people`: unified cross-source contact profiles plus any active
  person memory entries and explicit LifeOps People rows. Exact-name matches
  are labeled as matched; unresolved or ambiguous identities remain labeled
  rather than being silently merged;
- `sections.places`: locations observed on upcoming Calendar events and
  explicit Apple/Google contact addresses, each tied to the Calendar event or
  contact record that supplied it. These are observations, not yet a canonical
  address book;
- `sections.projects`: active explicit project records, conservatively
  deduplicated by normalized name with `evidence_refs` and any explicitly
  attached `linked_source_refs` for every merged record. The canonical tracker
  rows retain spreadsheet ID, tab, account, and row-number attribution;
- `sections.goals`, `decisions`, `notes`, and `commitments`: active structured
  memory entries;
- `sections.commitments`: open durable LifeOps commitments, including items
  that are not yet due for attention, plus open explicit LifeOps Actions rows;
- `source_health`: Inbox/LifeOps health from the triage projection;
  plus the read-only Master Tracker queue projection when available;
- `limitations`: domains not included in this projection or unavailable during
  the read;
- `provenance`: a count and bounded list of source references.

## Invariants

```text
∀ item i in context: i.source_ref ≠ ∅ ∨ i.local_memory_id ≠ ∅
∀ context c: c.read_only = true
∀ source s: unavailable(s) → s is listed in limitations
∀ context c: c does not mutate provider state
∀ generated context c: c.checked_at is present
```

## Deliberately deferred

- deeper identity resolution across Contacts, WhatsApp, and Calendar beyond
  Inbox's current unified contact projection;
- canonical place/address resolution and deduplication beyond source-backed
  Calendar and contact observations;
- embeddings or a vector database;
- automatic provider synchronization;
- contact/address writes;
- task/calendar/message writes;
- replacing Inbox's source-health and index proof;
- importing OpenHuman or Hermes memory as authoritative data.

Those are subsequent slices. They must consume this contract rather than create
parallel authorities.
