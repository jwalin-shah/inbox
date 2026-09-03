# Inbox ↔ Chief of Staff Integration Map

Status: investigation-backed (2026-09-03). Describes how an external orchestrator
(Grok Bot Chief of Staff, OpenClaw, or any MCP-capable agent) should invoke Inbox
for narrow dogfood: **triage unread**, **draft a reply (no send)**, and **surface
calendar conflicts**.

Inbox is the canonical personal-data gateway. The orchestrator is a **client**, not
a second control plane. Do not route Gmail/Calendar/iMessage around Inbox.

## System shape

```text
Chief of Staff (Grok / OpenClaw / MCP client)
  │
  ├─ local stdio ──► inbox_mcp_stdio.py | inbox_mcp_readonly_stdio.py
  │                      │
  └─ HTTP MCP ─────► mcp_server.py (full) | inbox_mcp_readonly.py (read-only)
                         │
                         ▼
                   mcp_gateway.py  (optional INBOX_MCP_TOKEN)
                         │
                         ▼
                   mcp_backend.py    (httpx → private REST API)
                         │
                         ▼
                   inbox_server.py   (FastAPI, 127.0.0.1:9849)
                         │
                         ▼
                   services.py       (Gmail, Calendar, iMessage, Tasks, …)
                         │
           ┌─────────────┼─────────────┐
           ▼             ▼             ▼
    Google APIs    macOS SQLite    GitHub API
    (tokens/)      (Messages, Notes) (github_token.txt)
```

**Not in this path:** webhooks, a separate LifeOps message bus, or provider MCP
tools (Gmail/Calendar built-ins). CoS should use Inbox MCP or Inbox HTTP only.

### Entrypoints (real, not stubs)

| Surface | Module | Role |
| --- | --- | --- |
| Private REST API | `inbox_server.py` | Canonical backend; all data + policy |
| Sync HTTP client | `inbox_client.py` | TUI and scripts |
| MCP tool registry | `tools_registry.py` | 86 tools; 53 read-only; drives MCP |
| MCP factory | `inbox_mcp_factory.py` | Single registration path (stdio + HTTP) |
| MCP HTTP gateway | `mcp_server.py` / `inbox_mcp_readonly.py` | Assistant-facing layer on port 8000/8001 |
| MCP stdio | `inbox_mcp_stdio.py` / `inbox_mcp_readonly_stdio.py` | Local Cursor/Claude spawn (see `.mcp.json`) |
| TUI | `inbox.py` | Human daily driver; auto-starts server |
| Agent workflows | `modes/*.md` | Prompt contracts for `/inbox triage`, `followup-sweep`, `morning-brief` |
| Message index | `message_sync.py` + `message_index_store.py` | Cross-source rollup for `/inbox/needs-action` |
| Connector doctor | `connector_registry.py` | CLI adapter status (gog, wacli, imsg, …); dry-run sync only |

`main.py` is a placeholder. `POST /query` (gemma4-hackathon) is optional and
returns 503 when that package is not installed — not the CoS path.

## How Chief of Staff should connect

### Recommended: read-only MCP for cloud / less-trusted agents

```json
{
  "mcpServers": {
    "inbox-readonly": {
      "command": "uv",
      "args": ["run", "python", "inbox_mcp_readonly_stdio.py"],
      "env": {
        "INBOX_SERVER_URL": "http://127.0.0.1:9849",
        "INBOX_SERVER_TOKEN": "${INBOX_SERVER_TOKEN}"
      }
    }
  }
}
```

For a remote CoS on another host: expose **only** the read-only HTTP MCP gateway
(see `MCP_SETUP.md`, `deploy/Caddyfile.example`) with `INBOX_MCP_TOKEN` set.
The private `inbox_server.py` must stay on localhost.

### Full MCP (local, trusted)

Use `inbox_mcp_stdio.py` or `mcp_server.py` when the agent may request approval-
gated writes. Writes still require `confirm=True` on MCP tools **and** a per-action
`X-Inbox-Approval-Lease` on the underlying HTTP route (see Safety gates).

### HTTP direct (no MCP)

CoS may call `http://127.0.0.1:9849` with `Authorization: Bearer $INBOX_SERVER_TOKEN`
(or `X-API-Key`). `/health` is unauthenticated. Prefer MCP for tool discovery and
consistent read-only boundaries.

### Startup checklist (human)

1. On the Mac that holds Messages + OAuth tokens: `uv run python inbox_server.py`
2. Confirm: `curl -sf http://127.0.0.1:9849/health`
3. Confirm accounts: `GET /accounts` (or MCP `get_personal_data_gateway_status`)
4. Optional index freshness: `INBOX_TEST_MODE=0 uv run python message_sync.py --smoke`
5. Point CoS MCP env at the correct port (9849 primary, 9850+ dev worktree)

## Auth assumptions

| Secret / config | Purpose | Where |
| --- | --- | --- |
| `INBOX_SERVER_TOKEN` | Bearer for all non-`/health` REST routes | env or `~/.config/inbox/server.env` |
| `INBOX_SERVER_ALLOW_UNAUTHENTICATED=1` | Dev/test only; bypasses token | env |
| `INBOX_MCP_TOKEN` | Optional bearer on public MCP HTTP | env |
| `tokens/*.json` | Per-account Google OAuth | gitignored, per checkout |
| `credentials.json` | Google OAuth client | gitignored |
| `github_token.txt` | GitHub notifications | gitignored |
| `gemini_api_key.txt` | Optional cloud LLM (`/ai/smart-reply`) | gitignored |

`GET /gateway/status` reports connector blockers and Infisical secret **names**
only (never values). Use it before claiming readiness.

## Safety gates (never auto-send)

1. **MCP `confirm=True`** — mutating tools raise unless the caller explicitly sets
   `confirm=True` after human approval (`tools_registry.py`).
2. **Per-action approval lease** — guarded HTTP mutations require
   `X-Inbox-Approval-Lease` bound to method, path, query, body, account, and item
   count. Mint via `POST /approvals/request` → captain approves →
   `GET /approvals/{id}` → attach lease header. See `docs/PERSONAL_DATA_GATEWAY_V0.md`.
3. **`INBOX_TEST_MODE=1`** — blocks live provider writes in tests and agent-safe runs.
4. **Read-only MCP** — write tools are not registered on `inbox_mcp_readonly_*`.
5. **Dry-run defaults** — connector sync and gateway dry-run endpoints never mutate.

CoS dogfood for this PR is **read + draft only**. Sending mail, iMessage, or
calendar creates must stay behind human approval.

## Smallest dogfood path (works today or nearly)

Three-step loop aligned with gated sends:

### Step 1 — Triage unread / needs action

**Preferred (indexed rollup):**

| MCP tool | HTTP equivalent |
| --- | --- |
| `list_needs_action` | `GET /inbox/needs-action?workflow=&account=` |

Returns reply-needed threads (from `.inbox_index.sqlite3` when populated), overdue
tasks, and upcoming calendar events. Requires `message_sync.py` bootstrap/incremental
runs for best Gmail/iMessage coverage; without index data the thread list may be empty
(server does not fall back to live Gmail for this route).

**Alternatives:**

| MCP tool | HTTP | Notes |
| --- | --- | --- |
| `list_inbox_threads` | `GET /gmail/conversations?label=INBOX` | Live Gmail; filter `unread` client-side |
| `search_email` | `GET /gmail/search?q=is:unread` | Gmail query syntax |
| `list_message_threads` | `GET /conversations?source=imessage` | macOS Messages DB |
| `get_personal_data_gateway_status` | `GET /gateway/status` | Blockers before triage |

Agent prompt contract: `modes/triage.md` (scores threads → `batch/triage-output.tsv`).
CoS can implement the same logic via MCP without the TSV.

### Step 2 — Draft a reply (no send)

1. Load context: `get_email_thread` / `get_message_thread` with `thread_id` when present.
2. Draft using **one** of:
   - **CoS model** (recommended for cloud): Grok drafts from thread JSON; no Inbox send.
   - **MCP `suggest_message_reply`** → `POST /autocomplete` with `mode=reply` (local MLX;
     macOS only; returns `null` if model not loaded).
   - **HTTP `POST /ai/smart-reply`** — requires `gemini_api_key.txt`; still no send.

Do **not** call `send_email_reply` or `send_imessage` in dogfood. If a send is
requested later: full MCP + `confirm=True` + approval lease + human step.

Agent prompt contract: `modes/followup-sweep.md`.

### Step 3 — Surface calendar conflicts

| MCP tool | HTTP |
| --- | --- |
| `check_calendar_conflicts` | `POST /calendar/conflicts` body: `{"start":"ISO","end":"ISO","account":""}` |
| `list_calendar_events` | `GET /calendar/events?date=YYYY-MM-DD` |

Pass today's window, e.g. `start=2026-09-03T00:00:00`, `end=2026-09-03T23:59:59`.
Requires Google Calendar OAuth in `tokens/`. Overlapping events are returned in
`conflicts[]`.

Morning-brief style context: `modes/morning-brief.md`.

### Example CoS session (read-only MCP)

```text
1. get_personal_data_gateway_status          → confirm Gmail/Calendar loaded
2. list_needs_action(workflow="", account="") → top threads/tasks/events
3. get_email_thread(message_id, thread_id)   → full thread for top Gmail item
4. suggest_message_reply(messages=[...])     → optional local draft (macOS MLX)
   — OR CoS drafts from thread body itself
5. check_calendar_conflicts(start, end)      → conflicts for today
```

Present drafts to the human; never call send tools without explicit approval.

## Implemented vs stubbed / blocked

| Capability | Status | Blocker if missing |
| --- | --- | --- |
| Gmail read/search/triage | Implemented | `tokens/`, re-auth Ctrl+A |
| Calendar read/conflicts | Implemented | Google Calendar scope in tokens |
| iMessage read | Implemented (macOS) | Full Disk Access, `~/Library/Messages/chat.db` |
| `/inbox/needs-action` index | Implemented | Run `message_sync.py bootstrap` once |
| MCP read-only surface | Implemented | Server up + `INBOX_SERVER_TOKEN` |
| MCP draft suggest | Implemented (`suggest_message_reply`) | MLX on macOS; else use CoS model |
| WhatsApp / Discord / X connectors | Partial | Install `wacli` / `discrawl` / `birdclaw`; see `/connectors/status` |
| LinkedIn scanner | Opt-in | `INBOX_ENABLE_LINKEDIN_SCRAPER=1` + export DB |
| `POST /query` gemma4 orchestrator | Optional dep | `gemini4-hackathon` not in default install |
| Cloud agent → localhost | Blocked by network | Tunnel or run CoS on same Mac as Inbox |
| Slash `/inbox` router skill | Modes only in repo | `.claude/skills/inbox/` gitignored; use `modes/*.md` |

## Provider wiring (how data actually flows)

- **Gmail / Calendar / Tasks / Drive / Sheets / Docs** — `services.py` via
  `google_auth_all()` → per-account services in `ServerState` (`inbox_server.py`).
- **iMessage** — read-only SQLite (`IMSG_DB`); send via AppleScript (approval-gated).
- **Apple Notes / Reminders** — local SQLite + AppleScript mutations.
- **GitHub** — `github_token.txt` REST API.
- **External CLIs** — `connector_registry.py` normalizes `gog`, `wacli`, `imsg`, etc.;
  not auto-used unless search sources include `connector:*`.

## Orchestrator integration (LifeOps / portfolio)

From `AGENTS.md`: queue bounded work with explicit write scopes:

```bash
./orch queue add --project inbox --role implementer --write-scope services.py "<task>"
```

Context firewall: do not copy message bodies or OAuth tokens into cross-project
memory. CoS should pass **structured summaries** and tool citations, not raw PII
blobs, to other portfolio agents.

## Validation

Agent-safe (no live writes):

```bash
scripts/validate_agent_safe.sh
```

Gateway-focused slice (documented in `docs/PERSONAL_DATA_GATEWAY_V0.md`):

```bash
INBOX_TEST_MODE=1 uv run pytest \
  tests/test_tools_registry.py tests/test_mcp_gateway.py \
  tests/test_approval_route_gate.py -q --no-cov
```

## Related docs

- `MCP_SETUP.md` — stdio vs HTTP MCP, ports, dev worktree
- `docs/PERSONAL_DATA_GATEWAY_V0.md` — gateway proofs and approval policy
- `docs/PERSONAL_AGENT_RUNTIME_V0.md` — OpenClaw / runtime roles (main vs worker)
- `modes/triage.md`, `modes/followup-sweep.md`, `modes/morning-brief.md` — dogfood prompts
- `wayfinder/tickets/006-prove-external-mcp-runtime.md` — external MCP proof ticket

## Honest dogfood status (2026-09-03)

| Step | Ready? | Notes |
| --- | --- | --- |
| Triage unread | **Yes** (with caveats) | Live Gmail via `list_inbox_threads` / `search_email`; richer rollup needs index sync |
| Draft reply, no send | **Yes** | Thread fetch via MCP; draft via CoS LLM or `suggest_message_reply` (MLX/macOS) |
| Calendar conflicts | **Yes** (after body fix) | `check_calendar_conflicts` + Google tokens |
| Auto-send | **Intentionally blocked** | Approval lease + confirm; use read-only MCP for CoS |

**Next human steps if dogfood fails on a fresh machine:**

1. Start `inbox_server.py` on the Mac with real tokens.
2. Set `INBOX_SERVER_TOKEN` in CoS MCP env (match server).
3. Run `message_sync.py bootstrap` for needs-action quality.
4. For cloud CoS: tunnel read-only MCP or run the agent locally — localhost is not reachable remotely by default.
