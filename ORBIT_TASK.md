# ORBIT_TASK.md — Gmail draft-update endpoint + Google Tasks writer dedup

Status: partial — Task 1 deferred, Task 2 done

## Requirement

Isolated worktree (primary `~/projects/inbox` has unrelated uncommitted
trigger-engine work in flight — not touched). Two fixes from the 2026-08-19
fleet reconciliation:

1. Inbox only exposes `POST /messages/drafts` (create). No update/edit
   endpoint exists, matching Gmail's real `users.drafts.update`. A 2026-08-19
   session tried to "update" a draft and created a duplicate instead. Add a
   proper update endpoint, gated through the existing approval-lease system
   (`APPROVAL_ROUTE_RULES` in inbox_server.py), with a test.
2. Two independent Google Tasks write paths exist (Inbox-MCP writer +
   a separate Sheets/Apps-Script bridge) with no shared dedup — investigate
   and add the smallest correct guard against double-creating the same task.

## Gates

- [ ] Draft-update route added, approval-gated same as draft-create — DEFERRED,
      see note below
- [ ] Test added and passing for the new route — N/A, deferred
- [x] Google Tasks dedup investigated; fix applied (`services.task_create`
      now checks incomplete tasks in the target list for an exact title
      match before inserting; Apps-Script-side bridge source not found in
      this repo, so this is a one-sided guard as anticipated)
- [x] Full relevant test files pass (`tests/test_services.py`: 75 passed,
      2 new)
- [x] Not merged to main — on branch `feat/gmail-draft-update-and-tasks-dedup`

## Note: Task 1 (Gmail draft-update) deferred, not implemented

The draft-create feature itself (`POST /messages/drafts`, `GmailDraftRequest`,
`services.gmail_create_draft`) does not exist in committed history — it only
exists as **uncommitted work-in-progress in the primary checkout**
(`~/projects/inbox`), alongside unrelated uncommitted trigger-engine/gas-price
work. This worktree branches from committed `main` (5bf4e6c) per this repo's
own dev-worktree convention, so draft-create isn't present here to build an
update endpoint against. Implementing it here would mean recreating an
already-in-flight, uncommitted feature in parallel — guaranteed conflict when
the primary's WIP eventually lands. Correct sequencing: once the primary's
uncommitted draft/trigger-engine work is committed, add the update endpoint
as a follow-up patch on top of that commit (same approval-gate pattern used
for `/messages/drafts`), not in an isolated worktree.
