# Ticket 002 — Coverage: utility scripts (unsubscribe_*)

Label: `wayfinder:ticket`
Status: open
Blocked by: 001
Blocks: 003

## What

Raise coverage on the two lowest-coverage files:

- `unsubscribe_bulk.py`: 6% (50 missed statements)
- `unsubscribe_interactive.py`: 6% (50 missed statements)

Target: 90%+ each. The gnhf series proved this pattern works — add focused
unit tests, mock external dependencies, verify error paths and early returns.

## Why

These are the last sub-50% modules in the codebase. Every other module
targeted by the gnhf series is at 64%+. These two were skipped (gnhf 1-3
targeted the other unsubscribe script at 96%). Closing this gap brings the
overall coverage baseline up and eliminates the "we know these are untested"
excuse.

## Acceptance

- `uv run pytest tests/ -k "unsubscribe" --cov=unsubscribe_bulk --cov=unsubscribe_interactive --cov-report=term`
  shows 90%+ for both files
- Full suite: 0 regressions
- `scripts/validate_agent_safe.sh` exits 0

## Approach notes

The gnhf 1-3 pattern is the template: mock `inbox_client.InboxClient`, verify
all code paths (success, early return, error), check that `client.close()` is
called on every path (this was the bug class found in the other unsubscribe
scripts). The same bug class is likely present here given the identical
pattern.
