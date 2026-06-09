# Inbox Project Instructions (Unified)

This workspace is a **personal communication hub** — Gmail, iMessage, Calendar, and related connectors. It handles sensitive personal data and must stay isolated from other portfolio projects.

## Workspace Structure

- `services.py` / `inbox_server.py` — data access layer and FastAPI server
- `inbox.py` — Textual TUI (thin HTTP client)
- `mcp_server.py` / `inbox_mcp_*.py` — MCP integration for agents
- `tokens/` — per-account Google OAuth tokens (**gitignored, HIGH ISOLATION**)
- `credentials.json`, `github_token.txt` — API secrets (**never commit**)
- `config/` — user priorities and profile (never auto-updated by agents)
- `tests/` — unit test suite (agent-safe via `INBOX_TEST_MODE=1`)
- `scripts/` — validation, reconcile, and utility scripts

## Mandatory Data Isolation

- **Personal PII:** Message bodies, contact graphs, calendar details, and OAuth tokens are personal data.
- **Strict separation:** Do NOT mix inbox content into client datasets (e.g. BTW), cross-project training corpora, or public artifacts.
- **Git safety:** `tokens/`, credentials, and runtime caches stay gitignored. **NEVER force-add secrets.**
- **Write guard:** Sending messages, modifying mail labels, creating calendar events, or completing reminders requires explicit human approval unless the queue item explicitly authorizes bounded test-mode writes.

## Operating Rules

1. **Source isolation:** Read macOS SQLite DBs and Google APIs only through `services.py` / server endpoints — not ad-hoc file scraping in agents.
2. **Test mode:** Use `INBOX_TEST_MODE=1` and `scripts/validate_agent_safe.sh` for agent validation; never hit live Gmail/iMessage in CI.
3. **Account routing:** Multi-account Google writes must route through the message-owning account, not the default.
4. **Worktree discipline:** Primary runs on port 9849; dev worktrees on 9850+ with matching `INBOX_SERVER_URL`.

## Data Classification

| Type | Examples | Policy |
| :--- | :--- | :--- |
| **Public docs** | `docs/`, architecture markdown, test fixtures | Safe to cite in PRs and reviews. |
| **Personal comms** | iMessage threads, Gmail bodies, contact names | Project-scoped only; redact in cross-project summaries. |
| **Secrets** | `tokens/`, `INBOX_SERVER_TOKEN`, OAuth refresh tokens | Never log, commit, or inject into worker context. |
| **Derived work** | Triage TSVs, connector registry docs, test outputs | Treat as inbox-owned; no cross-project bleed. |

## Master Orchestrator Integration

Inbox is registered in the orchestrator portfolio (`orchestrator-mvp/data/portfolio.json`) as a **high-isolation personal-data** project.

- **Session brief:** `SESSION_BRIEF.txt` — injected for `project=inbox` queue workers.
- **Project card:** `.orch-context.json` — isolation posture, validation commands, hook inheritance.
- **Context firewall:** Orchestrator must pass `project=inbox` so memories/thoughts stay project-scoped. Never inject BTW/client or unrelated portfolio context into inbox workers.
- **Hooks:** Inherit global Cursor hooks only. Do not add a project-local `hooks.json`.
- **Queue example:** `./orch queue add --project inbox --role implementer --write-scope services.py "<task>"`
- **Doctor:** `scripts/check_tooling.sh` or `scripts/validate_agent_safe.sh`
