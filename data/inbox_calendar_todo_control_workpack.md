# Inbox/Calendar/Todo Control Surface v0 Workpack

## Outcome

Implement a single local orchestrator command that summarizes actionable todos from configured inbox, task, and calendar sources, links every item to evidence, and emits only explicit review-before-write proposals for task creation or calendar holds.

Command:

```bash
python3 scripts/inbox_calendar_todo_control.py --fixture tests/fixtures/inbox_calendar_todo_control.json
```

JSON dry-run:

```bash
python3 scripts/inbox_calendar_todo_control.py --fixture tests/fixtures/inbox_calendar_todo_control.json --json
```

## Scope And Source Policy

- Gmail, Google Calendar, and Google Tasks are represented as external connector-backed sources.
- Future custom connector CLIs (`gog`, `imsg`, `wacli`) are reported as installed/not_installed only; they are not executed.
- The command does not send messages, delete data, create tasks, or write calendar events.
- `--execute` is reserved and currently refused with a non-zero exit code.

## Review-Before-Write Contract

The report contains proposed changes only:

- `create_task` proposals target `POST /tasks`.
- `calendar_hold` proposals target `POST /calendar/events`.
- Every proposal includes `approval.required=true`, `server_lease_required=true`, `execute=false`, and evidence IDs.

## Validation

Focused validation:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_calendar_todo_control.py -q --no-cov
```

Agent-safe validation:

```bash
scripts/validate_agent_safe.sh
```

## Stop Condition

Automated queue workers must stop at dry-run output. No external mutation occurs unless a future adapter adds explicit human approval and a server lease for the exact payload.
