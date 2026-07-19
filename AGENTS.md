# Inbox Agent Notes

## Validation

Default agent-safe local validation:

```bash
scripts/validate_agent_safe.sh
```

CI should hydrate the locked environment first, then run the same safe wrapper:

```bash
uv sync --frozen --all-groups
scripts/validate_agent_safe.sh
```

For the focused live-write guard slice:

```bash
INBOX_TEST_MODE=1 uv run pytest tests/test_inbox_test_mode.py tests/test_services.py -k "test_mode_blocks" -q --no-cov
```

## Platform Dependencies

MLX and PyObjC dependencies are Darwin-only in `pyproject.toml` so non-mac CI does not fail resolving mac-only wheels. On macOS, the default install includes them via platform markers; `uv sync --extra mac` makes the full macOS runtime dependency set explicit.

## Orchestrator Integration

Inbox is a portfolio project in `orchestrator-mvp`. Queue work with explicit project and write scopes:

```bash
./orch queue add --project inbox --role implementer --write-scope services.py "<bounded task>"
```

- **Context firewall:** `SESSION_BRIEF.txt` + `.orch-context.json` define high-isolation personal-data boundaries. Workers get project-filtered context only.
- **Agent contracts:** Follow `GEMINI.md` for PII/secrets handling; do not mix inbox message content into cross-project memory.
- **Hook compatibility:** Inherit global Cursor hooks (`~/.cursor/hooks.json`); never add project-local `hooks.json`.
- **Tooling doctor:** `scripts/check_tooling.sh` (tooling readiness) and `scripts/validate_agent_safe.sh` (test-mode pytest).
- **Write safety:** External sends (messages, mail mutations, calendar writes) require explicit human approval unless the queue item authorizes bounded test-mode work.
