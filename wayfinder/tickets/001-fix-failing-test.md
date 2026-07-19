# Ticket 001 — Fix failing test and add CI guard

Label: `wayfinder:ticket`
Status: open
Blocks: 002

## What

One test fails in the full suite: `test_print_summary_with_threads` in
`tests/test_message_sync.py`. Fix it. Then add a CI guard that prevents
regressions — at minimum, ensure `scripts/validate_agent_safe.sh` runs on
every push (or add a pre-push hook if CI is not set up).

## Why

A failing test erodes trust in the suite. The gnhf series added 700+ tests
and found real bugs; letting a test rot undoes that investment. The CI guard
ensures this doesn't happen again.

## Acceptance

- `uv run pytest tests/test_message_sync.py -k test_print_summary_with_threads` passes
- Full suite: `uv run pytest` — 0 failures
- `scripts/validate_agent_safe.sh` exits 0
- If CI exists, confirm it runs on push. If not, document how to add it (or
  add a pre-push hook as a stopgap).

## Approach notes

The test likely fails because a gnhf refactor changed `print_summary` output
format. Compare the expected vs actual assertion to identify which commit
broke it (`git log -- tests/test_message_sync.py` and `git log --
 message_sync.py`). Fix the test to match current behavior, or fix the
behavior if the test expectation is correct and the code regressed.
