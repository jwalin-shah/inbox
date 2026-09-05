# ADR 0010: Gmail normalization and todo candidates

## Status

Accepted for the first LifeOps triage slice.

## Decision

Use the existing Inbox message index as the single operational read model for
all configured Gmail accounts. Expose two read-only projections:

- `GET /gmail/normalization` reports per-account indexed counts, sync freshness,
  open loops, reply/action counts, and an explicit coverage status.
- `GET /triage/todo-candidates` returns stable, deduplicated candidate IDs with
  source/account/thread identifiers, evidence references, and a proposed task
  payload.

LifeOps exposes both projections. Candidate results never create Google Tasks
automatically. A reviewed candidate may be turned into a
`POST /tasks/from-message` proposal, which retains the existing exact-payload
approval lease and message-to-task link. Execution still requires explicit
approval, one-use lease execution, and read-back verification.

`GET /tasks/reconciliation` reads every visible task list for the selected
accounts and conservatively labels candidates as matched, possible match, or
missing. It also reports existing tasks that are not linked to a current
candidate and duplicate task titles. It never edits, completes, or deletes a
task.

## Boundaries

The report proves local index coverage and recorded sync health, not that a
provider mailbox is complete beyond its recorded checkpoint. Google Contacts,
calendar, and task state remain separate provider-backed surfaces. Newegg
procurement remains its own database and MCP adapter; LifeOps may aggregate its
read-only results later without copying that authority into Inbox.
