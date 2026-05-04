# CODEX Workpad — SYM-29

- Issue: https://linear.app/symphony-test-jwalin/issue/SYM-29/inbox-b-resume-interrupted-bootstrap-sync-without-duplicates
- Branch: `codex/SYM-29-resume-bootstrap-without-duplicates`
- HEAD: `dd112cb`
- Status: In Review

## Scope
- Resume behavior + duplicate avoidance in Gmail bootstrap sync.

## Plan
1. Add a focused regression test simulating an interrupted bootstrap where resume data includes an already-indexed message.
2. Update bootstrap sync behavior to avoid reprocessing already-indexed messages while still advancing checkpoints deterministically.
3. Run focused resume tests and then the repository standard test command.

## Validation
- Executed: `uv run pytest tests/test_message_sync.py -q` (2 passed)
- Executed: `uv run pytest` (787 passed, 25 failed)
- Validation notes: full-suite failures are unrelated to resume slice (`test_command_palette.py`, `test_inbox_app.py`, `tests/test_message_index_store.py` assertion mismatch).

## Changes made
- Added `MessageIndexStore.insert_item_if_absent(...)` using `ON CONFLICT ... DO NOTHING`.
- Updated Gmail bootstrap loop in [message_sync.py] to only count/record inserts when new rows are added.
- Added regression test `test_sync_gmail_bootstrap_does_not_double_count_or_rewrite_items_on_resume` in [tests/test_message_sync.py].

## Handoff
- Commit: `dd112cb`
- PR: `https://github.com/walin-shah/inbox/pull/13`
- Push: `origin/codex/SYM-29-resume-bootstrap-without-duplicates`
