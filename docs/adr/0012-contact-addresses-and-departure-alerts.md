# ADR 0012: Source-linked contact addresses and departure alerts

## Status

Accepted for the next LifeOps vertical slice.

## Decision

LifeOps keeps a local, source-linked person projection. Apple AddressBook and
Google People postal addresses are exposed as additive `addresses` records with
their source and account/database label. Multiple addresses are preserved;
they are not silently merged or written back to Apple or Google Contacts.

Departure calculation remains read-only until an alert is due. When the
opt-in departure worker is enabled and a live origin plus located calendar
event are available, it emits a local macOS notification and then creates a
Google Task or Apple Reminder as the synced follow-through. The event key is
deduplicated in the process so one event does not generate repeated alerts in
one runtime.

## Boundaries

- Current location or `INBOX_HOME_ADDRESS` is required; no origin means no
  departure alert.
- `INBOX_ENABLE_DEPARTURE_ALERTS=1` is required; the default remains off.
- Message/email sends and bulk task creation remain approval-gated and are not
  part of departure alerts.
- Siri and Shortcuts should capture into the existing authenticated capture
  path or Apple Notes/Reminders; bearer tokens must not be embedded in a
  public shortcut URL.

## Verification

- Google People API is enabled for project `inbox-503019`.
- Live provider status reports Google Contacts readable and syncable for the
  three configured Gmail identities.
- A live Apple AddressBook search returned source-labelled postal addresses.
- Departure notification behavior is covered by syntax/lint and focused
  server/notification tests; live notification delivery remains a deliberate
  user-facing test because it produces a desktop notification.
