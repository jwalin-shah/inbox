# Design

> Produced / maintained via the `codebase-design` skill. Required by portfolio universal-pocock-policy (2026-07-30).

## Module map

| Module | Responsibility | May depend on |
|---|---|---|
| `services.py` | Gmail, Calendar, Sheets, Docs, Drive, iMessage, Notes, Reminders, GitHub, LLM, audio | platform DBs, Google API |
| `inbox_server.py` | FastAPI wrapper; auth middleware; route handlers | services |
| `inbox_client.py` | Sync HTTP client for server API | — |
| `inbox.py` | Textual TUI; tab state; auto-starts server | inbox_client |
| `mcp_server.py`, `mcp_backend.py` | MCP stdio server → HTTP backend | inbox_client |
| `contacts.py` | AddressBook SQLite; phone variant matching | macOS |
| `ambient_daemon.py`, `ambient_notes.py` | Audio capture → ASR → Obsidian `~/vault/daily/` | MLX Whisper |
| `scheduler.py` | Background recurring tasks | SQLite state |
| `memory_store.py` | Persistent conversation memory | — |

## Dependency rules

- Allowed directions: TUI/MCP → client → server → services → external APIs/DBs
- Forbidden: TUI direct SQLite access; committing credentials (tokens/, credentials.json, github_token.txt); cross-project context injection in orchestrator spawns

## Interfaces / seams

- **HTTP:** `localhost:9849`; Bearer or X-API-Key via `INBOX_SERVER_TOKEN`
- **Env:** `INBOX_SERVER_PORT`, `INBOX_SERVER_URL` for worktree isolation (9850+)
- **LLM:** Qwen3.5-0.8B-MLX-4bit singleton; Outlines constrained JSON generation
- **Dictation:** whisper-stream C++ binary; pyobjc CGEvent keyboard injection
- **Worktree:** `dev.sh` sets alt port; shared macOS DBs, per-checkout `tokens/`

## Test strategy

- `scripts/validate_agent_safe.sh` — default agent-safe validation gate
- `uv run pytest` with `conftest.py` stubs for mlx, sounddevice, Quartz, outlines
- `INBOX_TEST_MODE=1` blocks dangerous operations in targeted tests
- `uv run pyright` for type coverage

## Migration notes

- Flattened module structure (LLM/audio in services, not nested packages)
- New Google scopes (documents) require re-auth via Ctrl+Shift+A or `/accounts/reauth`
- Primary daily driver on 9849; dev worktrees must not reuse primary MCP `INBOX_SERVER_URL`
