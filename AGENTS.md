# Inbox Agent Notes

## Invariants & Oracle System

Inbox invariants are formalized as tensor equations in `docs/invariants.md`, each mapped to a canonical oracle from the orbit research pipeline at `~/projects/orbit/docs/research/`.

### Quick reference

| Inbox subsystem | Oracle | Key invariants |
|---|---|---|
| Server API (`inbox_server.py`) | `api-design-oracle.md` | X-Request-ID, structured errors, timeouts, connection pool hygiene |
| Connectors (`connectors/`) | `saltzer-schroeder-oracle.md` | Auth check before use, 429 backoff, non-blocking sync, circuit breaker |
| MCP gateway (`mcp_gateway.py`) | `api-design-oracle.md` | JSON-RPC 2.0 conformance, tool call validation, session lifecycle |
| MCP control plane (`mcp_control_plane.py`) | `saltzer-schroeder-oracle.md` | Fail-closed auth, ApprovalStore lookup, ingest-only spawn=0, confirm≠authority |
| Message sync (`message_sync.py`) | `data-quality-oracle.md` | Unique message IDs, no sync duplicates, idempotent sync |
| Approval store (`approval_store.py`) | `saltzer-schroeder-oracle.md` | State machine consistency, complete mediation, audit logging |
| Egress audit (`egress_audit.py`) | `saltzer-schroeder-oracle.md` | Host allowlist, all outbound traffic logged |
| Scheduler (`scheduler.py`) | `ostep-oracle.md` | Task state machine, persistence across restarts |
| TUI (`inbox.py`) | `apple-platform-oracle.md` | Non-blocking updates, undo for destructive actions |

### Contract

1. Before modifying any subsystem, read the corresponding oracle in `~/projects/orbit/docs/research/`
2. Write the invariant as a tensor equation in `docs/invariants.md` before writing implementation code
3. Every P0 invariant must have a test that exercises the invariant boundary
4. Every P1 invariant must have a line-level tensor equation in `docs/invariants.md`

See `docs/oracle-map.md` for the full mapping table and `docs/invariants.md` for the complete tensor equations.

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
