# ADR 0013: Calendar authority and multi-stop route planning

## Status

Accepted.

## Decision

Google Calendar remains LifeOps' cross-account commitment authority because the
Inbox gateway already reads and writes it with account routing and approval
leases. Apple Calendar is treated as a synchronized display surface unless a
separate native Apple Calendar read/write proof is added. Apple Reminders and
macOS notifications are delivery surfaces for approved follow-through, not a
second commitment database.

LifeOps exposes a read-only multi-stop-route capability. It accepts an origin,
ordered destinations, optional dwell time at intermediate stops, an arrival
time, and a safety buffer. It returns one latest safe departure time plus
per-leg evidence. It never creates or edits calendar events or reminders.

## Invariants

- One commitment produces one canonical route/reminder key.
- Source evidence may come from Gmail, iMessage, Contacts, or Calendar, but it
  does not create a second authority.
- Route calculations are snapshots and must be refreshed before departure.
- Missing origin, destination, or travel-time evidence blocks the calculation.
- Any Calendar, Tasks, Reminders, message, or notification write remains
  explicit-approval gated.

## Consequence

The user can keep using Apple Calendar and native notifications while LifeOps
joins cross-account Google Calendar commitments and message evidence. The next
safe extension is a deduplicated reminder delivery adapter keyed to the route
snapshot; it is not an automatic Apple/Google dual write.
