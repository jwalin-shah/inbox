# ADR-0009: Local evidence-linked person profiles

- **Status:** Accepted
- **Date:** 2026-08-25
- **Deciders:** captain

## Decision

Add a separate local `.inbox_people.sqlite3` store for canonical person
profiles. Apple Contacts, Google Contacts, Gmail, iMessage, and Calendar remain
source systems; the local store holds a rebuildable profile cache plus explicit
LifeOps notes and relationship claims.

Each profile keeps:

- stable local `person_id` and external contact identifier;
- source-backed email, phone, and alias identifiers;
- explicit notes with source, provenance, confidence, confirmation, and expiry;
- relationship claims such as `friend`, `coworker`, or `family`, with context and
  confirmation state.

Different external identifiers are not automatically merged because their
display names match. A future alias-link workflow must be user-approved.

## Interface

- `GET /people/search` hydrates local profiles from the existing contact merger;
- `GET /people/{person_id}/profile` returns local profile data and the existing
  cross-source contact profile when available;
- `POST /people/{person_id}/notes` stores a local note only;
- `POST /people/{person_id}/relationships` stores a local relationship claim
  only.

LifeOps exposes profile reads directly. Note and relationship writes use the
same propose -> explicit approval -> single-use lease -> execute sequence as
other bounded LifeOps writes.

## Invariants

```text
∀ p ∈ LocalPeople: source_write(p) = false
∀ n ∈ Notes: n.person_id ∈ LocalPeople
∀ r ∈ Relationships: r.person_id ∈ LocalPeople
∀ c1,c2: display_name(c1) = display_name(c2) ⇒ person_id(c1) = person_id(c2) is not assumed
∀ w ∈ ProfileWrites: side_effect(w) ⇒ approval_lease(w) binds exact payload(w)
```

## Out of scope

- silent merging of people with conflicting identifiers;
- writing private notes into Apple or Google Contacts;
- treating inferred relationship labels as confirmed facts;
- a graph database or cloud-hosted people store.
