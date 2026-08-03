# Domain context

> Produced / maintained via the `domain-modeling` skill. Required by portfolio universal-pocock-policy (2026-07-30).

## Purpose

Inbox is a **privacy-first terminal TUI** that consolidates personal communication and productivity sources into one keyboard-driven interface. A local FastAPI server owns all data access; the Textual TUI, HTTP clients, and MCP server are thin clients. Agents reach the same API without the UI.

## Ubiquitous language

| Term | Meaning |
|---|---|
| Source | Data origin: imessage, gmail, calendar, notes, reminders, github, drive, sheets, docs |
| Conversation | Thread across a source; cached server-side for fast sends |
| Account | Per-Google OAuth token in `tokens/`; routes writes correctly |
| Ambient | Background audio capture → MLX Whisper → extraction → Obsidian vault |
| Preflight | Write-operation validation before execution |
| Optimistic send | Message shown immediately; confirmed asynchronously |

## Entities

| Entity | Invariants | Owner |
|---|---|---|
| FastAPI server | Port 9849 default; token auth on all routes except /health | inbox |
| services.py | Data layer for all sources + LLM + audio | inbox |
| TUI (inbox.py) | Tab state preserved across switches | inbox |
| MCP server | stdio protocol exposing inbox tools to agents | inbox |
| Scheduler | Recurring tasks in `.inbox_scheduler.sqlite3` | inbox |

## Boundaries

- **In scope:** unified inbox UI, server API, MCP, local ML (Qwen MLX, Whisper), macOS platform integrations
- **Out of scope:** cloud sync, telemetry, BTW/client portfolio context (context firewall for orchestrator spawns)
- **Upstream dependencies:** macOS SQLite DBs (Messages, Notes, Reminders, AddressBook), Google OAuth, GitHub PAT
- **Downstream consumers:** captain daily driver; Master Orchestrator project=inbox spawns; agent slash commands via inbox skill

## Events / lifecycle

1. `uv run python inbox.py` → auto-starts server + TUI
2. Refresh loads conversations from all authed accounts/sources
3. Send → optimistic UI → background confirm via correct account routing
4. Ambient auto-starts on server boot (graceful fail if deps missing)

## Open questions

- Concurrent mutations from primary + worktree copies sharing macOS SQLite paths
- Gemini API optional fallback vs fully local MLX stack
