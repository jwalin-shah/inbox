# Testing For Agents

This repo contains personal-data integrations. Default agent runs must be deterministic, local, and safe.

## Safe Commands

Use the wrapper as the default pre-handoff verification loop:

```bash
scripts/validate_agent_safe.sh
```

The wrapper sets `INBOX_TEST_MODE=1`, points `UV_CACHE_DIR` at a writable temp cache, checks that the locked offline environment is available, and then runs:

```bash
uv run ruff check .
uv run bandit -c pyproject.toml -r .
INBOX_TEST_MODE=1 uv run pytest tests/test_connector_registry.py tests/test_services.py tests/test_message_sync.py -q --no-cov
```

The retired broad manual loop also included `uv run pyright`; do not use it as the default agent-safe gate unless the task explicitly asks for typechecking.

For focused local debugging after the wrapper identifies a failure, prefer the smallest relevant safe test:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py -q
```

## Test Mode

Set `INBOX_TEST_MODE=1` for agent-safe test runs.

In test mode:
- live writes are blocked through `assert_live_writes_allowed`
- test data should use `INBOX_TEST_DATA_DIR` or another test-local temp path
- date-sensitive tests can set `INBOX_TEST_NOW` to a fixed ISO timestamp
- tests must avoid real Gmail, Calendar, Reminders, Notes, Messages, Drive, Docs, Sheets, Tasks, OAuth, microphone input, and notification mutation unless explicitly opted in

## Markers

- `safe` -- deterministic tests that do not touch live personal data or external write surfaces
- `integration` -- tests that exercise integration behavior beyond a single module
- `local_data` -- tests that require local user data stores and must be explicitly opted into
- `slow` -- tests that are too slow for the default agent-safe loop
- `live_write` -- tests that perform externally visible writes and require explicit human approval

## Explicit Opt-In

Do not run live-write tests unless explicitly instructed by the user.

Do not run tests marked `local_data`, `live_write`, or live provider-specific integration tests unless the user asks for that class of verification by name.

Do not replace `scripts/validate_agent_safe.sh` with broad `uv run pytest`, marker-only subsets, server startup, TUI startup, OAuth flows, provider clients, fix/format commands, or integrations against local personal data for default agent validation.
