# ADR 0011: Google People runtime attachment

## Status

Implemented, pending Google Cloud project enablement.

## Decision

Reuse the existing per-account OAuth token files and Contacts scope. Build one
Google People API client per account at Inbox startup, probe the exact
connections read used by contact search, and only mark the provider readable
when that probe succeeds. The local Apple AddressBook and message-derived
contact paths remain available as fallbacks.

## Current blocker

The tokens are valid, but Google returns `SERVICE_DISABLED` for
`people.googleapis.com` in the OAuth project. The user must enable 2-step
verification for Google Cloud access, then enable the People API in the
project's APIs & Services page. No new OAuth secret or token is required unless
Google later reports a missing scope or revoked refresh token.
