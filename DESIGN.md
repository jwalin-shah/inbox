# Design

> Produced / maintained via the `codebase-design` skill. Required by portfolio universal-pocock-policy (2026-07-30).

## Module map

| Module | Responsibility | May depend on |
|---|---|---|
| `services.py` | Gmail, Calendar, Sheets, Docs, Drive, iMessage, Notes, Reminders, GitHub, LLM, audio | platform DBs, Google API |
| `action_gateway.py` | Single mediation: identify caller → resolve action type → classify risk → validate + idempotency → policy (auto vs human lease) → dispatch → record (ADR-0002) | `approval_store`, `egress_audit`, `capability_inventory`, `connector_registry`, provider adapters |
| `inbox_server.py` | FastAPI wrapper; auth middleware; route handlers (writes delegate to gateway) | `action_gateway`, services |
| `inbox_client.py` | Sync HTTP client for server API | — |
| `inbox.py` | Textual TUI; tab state; auto-starts server | inbox_client |
| `mcp_server.py`, `mcp_backend.py` | MCP stdio server → HTTP backend | inbox_client, `action_gateway` (via backend) |
| `contacts.py` | AddressBook SQLite; phone variant matching | macOS |
| `ambient_daemon.py`, `ambient_notes.py` | Audio capture → ASR → Obsidian `~/vault/daily/` | MLX Whisper |
| `scheduler.py` | Background recurring tasks | SQLite state |
| `memory_store.py` | Persistent conversation memory | — |

## Dependency rules

- Allowed directions: TUI/MCP/CLI → client → gateway → services → provider adapters → external APIs/DBs
- Every provider write travels through `action_gateway.py`; no route or tool reaches a provider helper directly (complete mediation)
- Forbidden: TUI direct SQLite access; committing credentials (tokens/, credentials.json, github_token.txt); cross-project context injection in orchestrator spawns

## Interfaces / seams

- **HTTP:** `localhost:9849`; Bearer or X-API-Key via `INBOX_SERVER_TOKEN`
- **MCP:** full stdio (owner) · read-only stdio · full HTTP (trusted) · read-only HTTP (cloud) — collapses to per-client scopes over one gateway (ADR-0005)
- **Clients:** registered, scoped credentials; `requested_by` recorded on every action (ADR-0005)
- **Actions:** typed `namespace.verb` catalog shared by HTTP/MCP/CLI (ADR-0003)
- **Env:** `INBOX_SERVER_PORT`, `INBOX_SERVER_URL` for worktree isolation (9850+)
- **LLM:** Qwen3.5-0.8B-MLX-4bit singleton; Outlines constrained JSON generation
- **Dictation:** whisper-stream C++ binary; pyobjc CGEvent keyboard injection
- **Worktree:** `dev.sh` sets alt port; shared macOS DBs, per-checkout `tokens/`

## Test strategy

- `scripts/validate_agent_safe.sh` — default agent-safe validation gate
- `uv run pytest` with `conftest.py` stubs for mlx, sounddevice, Quartz, outlines
- `INBOX_TEST_MODE=1` blocks dangerous operations in targeted tests
- Gateway parity: keep `tests/test_approval_route_gate.py` green against the new `action_gateway.py` (ADR-0002)
- `uv run pyright` for type coverage

## Migration notes

- Flattened module structure (LLM/audio in services, not nested packages)
- Gateway consolidation is incremental + reversible: build `action_gateway.py` beside the existing gate, cut over via `INBOX_GATEWAY_ENABLE`, delete old code after parity (ADR-0002)
- Risk-tiered confirmation relaxes the AGENTS.md write-safety rule for `reversible_write` only; send/delete/cancel stay human-gated (ADR-0004)
- Gmail draft parity adds `draft.list/get/update/delete/send` + threaded reply (ADR-0006)
- New Google scopes (documents) require re-auth via Ctrl+Shift+A or `/accounts/reauth`
- Primary daily driver on 9849; dev worktrees must not reuse primary MCP `INBOX_SERVER_URL`