# Domain context

> Produced / maintained via the `domain-modeling` skill. Required by portfolio universal-pocock-policy (2026-07-30).

## Purpose

Inbox is a **privacy-first terminal TUI** that consolidates personal communication and productivity sources into one keyboard-driven interface. A local FastAPI server owns all data access; the Textual TUI, HTTP clients, and MCP server are thin clients. Agents reach the same API without the UI.

Inbox is also the **canonical action layer**: ChatGPT, DeepSeek Harness, Codex, Claude, and local models are interchangeable *clients* (brains) above a single Action Gateway. Decisions are recorded in `docs/adr/`; the target gateway state is `docs/ACTION_GATEWAY_V1.md`.

## Ubiquitous language

| Term | Meaning |
|---|---|
| Source | Data origin: imessage, gmail, calendar, notes, reminders, github, drive, sheets, docs |
| Observation | One source observation preserved as an append-only raw event before interpretation |
| Raw event | Versioned payload with source identity, timestamps, provenance, and confidence |
| Derived state | Rebuildable projection of raw events used to answer what is currently true |
| Provenance | Evidence describing where an observation came from and how it was captured |
| Freshness policy | Source-specific expectation for when an observation should be refreshed |
| Conversation | Thread across a source; cached server-side for fast sends |
| Account | Per-Google OAuth token in `tokens/`; routes writes correctly |
| Ambient | Background audio capture → MLX Whisper → extraction → Obsidian vault |
| Preflight | Write-operation validation before execution |
| Optimistic send | Message shown immediately; confirmed asynchronously |
| Action | A typed, catalogued provider operation (`gmail.draft.update`, `task.create`) with a param schema |
| Action Gateway | Single mediation point: identify → classify → validate → idempotency → policy → lease → dispatch → audit |
| Brain | A client above Inbox (ChatGPT, DeepSeek Harness, Codex, Claude, local model, scheduler) |
| Client identity | A registered, scoped credential identifying the caller; recorded as `requested_by` |
| Risk class | `read` · `reversible_write` · `consequential` — drives whether a lease is auto-issued or human-required |
| Provider adapter | Swappable boundary between the gateway and a provider (Google, Apple, GitHub, …) |
| Lease | One-time, body-bound approval token; the only thing that grants execution |

## Entities

| Entity | Invariants | Owner |
|---|---|---|
| FastAPI server | Port 9849 default; token auth on all routes except /health | inbox |
| services.py | Data layer for all sources + LLM + audio | inbox |
| Action Gateway (`action_gateway.py`) | Single mediation; every provider write goes through it (complete mediation) | inbox |
| Action catalog | Typed `namespace.verb` actions with param schema; unique `action_id` | inbox |
| Clients | Registered, scoped brain credentials; `requested_by` on every action | inbox |
| TUI (inbox.py) | Tab state preserved across switches | inbox |
| MCP server | stdio protocol exposing inbox tools to agents | inbox |
| Scheduler | Recurring tasks in `.inbox_scheduler.sqlite3` | inbox |
| Raw event log (`event_store.py`) | Append-only local evidence in `.inbox_event_log.sqlite3`; no provider writes | inbox |
| Source registry (`source_registry.py`) | Static source capabilities and freshness policy; live readiness remains `/capture/health` | inbox |

## Boundaries

- **In scope:** unified inbox UI, server API, MCP, action gateway + risk policy, local ML (Qwen MLX, Whisper), macOS platform integrations, raw evidence capture
- **Evidence boundary:** raw observations are preserved separately from the operational message index; interpretation and canonical state are rebuildable projections
- **Out of scope:** cloud sync, telemetry, BTW/client portfolio context (context firewall for orchestrator spawns)
- **Upstream dependencies:** macOS SQLite DBs (Messages, Notes, Reminders, AddressBook), Google OAuth, GitHub PAT
- **Downstream consumers:** captain daily driver; Master Orchestrator project=inbox spawns; agent slash commands via inbox skill; MCP clients (ChatGPT, DeepSeek Harness, Codex, Claude)

## Events / lifecycle

1. `uv run python inbox.py` → auto-starts server + TUI
2. Refresh loads conversations from all authed accounts/sources
3. Send → optimistic UI → background confirm via correct account routing
4. Ambient auto-starts on server boot (graceful fail if deps missing)
5. A guarded write → Action Gateway identifies caller, classifies risk, validates, then either auto-issues or requests a human lease → dispatch → audit
6. A source or user capture → raw event log append with provenance → later normalization and derived-state projection

## Open questions

- Risk-tiering migration: `reversible_write` auto-issue for trusted brains (ADR-0004) requires updating the AGENTS.md write-safety rule in the same change
- Provider-adapter seam and unified `inbox` CLI are open items (see `docs/ACTION_GATEWAY_V1.md`)
- Concurrent mutations from primary + worktree copies sharing macOS SQLite paths
- Gemini API optional fallback vs fully local MLX stack
- Which source adapters should emit raw events first, and how much source payload to preserve locally versus retain by content reference
