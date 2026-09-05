# Inbox → Bridge adapter

## Destination

Emit normalized Inbox records as a stable Bridge event envelope without
changing personal-data ownership.

## Findings

- Inbox already has normalized message and memory records plus approval-gated
  actions.
- No Bridge adapter contract existed in this repository.
- The existing Inbox worktree is dirty with unrelated OAuth/action changes.

## Decisions

- The adapter is stdlib-only and pure: record in, JSON envelope out.
- Existing record IDs become stable event IDs; the adapter does not create a
  second canonical store.
- Bridge is responsible for intake acceptance, execution authority,
  verification, and Git delivery.

## Not yet specified

- Which normalized source records should become automatic work packets.
- Live transport to a running Bridge/HomeBase process.
- Provider/resource adapter registration beyond the shared contract.

## Out of scope

- Personal-data writes, OAuth, message sync, Postgres, and provider migration.
