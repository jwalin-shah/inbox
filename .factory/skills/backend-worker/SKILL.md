---
name: backend-worker
description: Backend-focused worker for services, server, client, and infrastructure changes
---

# Backend Worker

NOTE: Startup and cleanup are handled by `worker-base`. This skill defines the WORK PROCEDURE.

## When to Use This Skill

Use for features that primarily modify:
- `services.py` — data access layer functions
- `inbox_server.py` — API endpoints, server state
- `inbox_client.py` — HTTP client methods
- `contacts.py` — contact resolution
- `ambient_notes.py` / `ambient_daemon.py` — ambient capture
- Test files in `tests/`
- Configuration and infrastructure (logging, connection pooling, etc.)

NOT for features that require TUI changes (use fullstack-worker instead).

## Required Skills

None — this worker operates purely on backend code and tests.

## Work Procedure

1. **Read the feature description** carefully. Understand exactly what behavior is expected, what preconditions must hold, and what verification steps are defined.

2. **Investigate the current code** relevant to this feature:
   - Read the specific files you'll be modifying
   - Understand existing patterns and conventions
   - Check AGENTS.md for coding conventions and boundaries
   - Check `.factory/library/architecture.md` for system architecture
   - Check `.factory/services.yaml` for commands and services

3. **Write failing tests first (RED)**:
   - Follow existing test patterns from `tests/conftest.py` and peer test files
   - For server endpoints: use `FastAPI TestClient` (see `tests/test_server_endpoints.py`)
   - For client methods: mock `httpx.Client` (see `tests/test_client.py`)
   - For service functions: direct calls with mocked dependencies
   - Tests must fail before implementation (verify with `uv run pytest path/to/test_file.py -x`)

4. **Implement to make tests pass (GREEN)**:
   - Write the minimum code to pass the tests
   - Follow existing patterns in the codebase
   - Use loguru for all logging (`from loguru import logger`)
   - Never silently swallow exceptions
   - Add type hints to all new functions

5. **Run full validation**:
   - `uv run pytest -x -q` — all tests pass
   - `uv run pyright` — 0 errors
   - `uv run ruff check .` — 0 errors
   - Fix any failures before proceeding

6. **Manual verification** (if feature has API endpoints):
   - Start the server: `uv run python inbox_server.py &`
   - Test endpoints with curl
   - Stop the server: `lsof -ti :9849 | xargs kill`

7. **Verify preconditions and expected behavior** from the feature description:
   - Check each item in `expectedBehavior` — is it satisfied?
   - Run each item in `verificationSteps`

8. **Commit** your changes with a descriptive message.

## Example Handoff

```json
{
  "salientSummary": "Added structured loguru logging to all service functions in services.py, replacing 47 silent except blocks with logger.error/exception calls. All 190 tests pass, pyright 0 errors, ruff 0 errors. Manually triggered a service error and confirmed log output in stderr.",
  "whatWasImplemented": "Replaced all bare except:pass and except Exception:return[] patterns in services.py with loguru logging. Added `from loguru import logger` import. Each except block now logs the function name, arguments (sanitized), and full traceback via logger.exception(). Added 3 new tests verifying error logging behavior.",
  "whatWasLeftUndone": "",
  "verification": {
    "commandsRun": [
      {"command": "uv run pytest -x -q", "exitCode": 0, "observation": "193 passed in 3.8s"},
      {"command": "uv run pyright", "exitCode": 0, "observation": "0 errors, 0 warnings"},
      {"command": "uv run ruff check .", "exitCode": 0, "observation": "All checks passed"},
      {"command": "curl -sf http://localhost:9849/health", "exitCode": 0, "observation": "200 OK with status healthy"}
    ],
    "interactiveChecks": [
      {"action": "Triggered imsg_contacts with invalid DB path", "observed": "loguru error line in stderr: 'imsg_contacts failed: no such table: chat'"}
    ]
  },
  "tests": {
    "added": [
      {
        "file": "tests/test_services.py",
        "cases": [
          {"name": "test_imsg_contacts_logs_error_on_db_failure", "verifies": "loguru.error called when SQLite query fails"},
          {"name": "test_gmail_contacts_logs_error_on_api_failure", "verifies": "loguru.error called when Gmail API raises"},
          {"name": "test_service_errors_not_silently_swallowed", "verifies": "grep for bare except:pass returns 0 matches in services.py"}
        ]
      }
    ]
  },
  "discoveredIssues": []
}
```

## When to Return to Orchestrator

- Feature requires TUI changes that weren't anticipated
- A dependency or service needed by the feature is unavailable
- Existing tests fail in ways unrelated to your feature
- The feature's preconditions aren't met (e.g., an endpoint it depends on doesn't exist)
- Requirements are ambiguous or contradictory
