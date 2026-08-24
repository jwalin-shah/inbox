# LifeOps MCP v0

## Goal

Make ChatGPT Business the cockpit for the existing Inbox/Mac capability layer without exposing the whole Inbox REST API or weakening its write-approval invariants.

```text
ChatGPT Business
      |
      | MCP over HTTPS
      v
Secure MCP Tunnel (preferred for ChatGPT)
      |
      v
lifeops_mcp.py :9850
      |
      | authenticated localhost HTTP
      v
inbox_server.py :9849
      |
      +-- iMessage / Contacts / Notes / Reminders
      +-- Gmail / Calendar / Tasks / Drive / Docs / Sheets
      +-- Maps travel time / current location
      +-- GitHub / connector index / audit
```

The MCP adapter is intentionally smaller than Inbox. V0 proves one useful vertical slice before widening permissions.

## V0 tool surface

Read tools:

- `search` and `fetch` — cross-source evidence retrieval
- `source_health` — provider, capture, and egress health
- `calendar_events` — calendar commitments
- `travel_time` — route duration
- `departure_times` — leave-time calculation for located events
- `tasks` — current Google Tasks

Bounded write workflow:

- `propose_create_task`
- `propose_update_calendar_event`
- `approve_pending_action`
- `execute_approved_action`

No MCP tool can send messages, delete data, run arbitrary shell commands, or execute arbitrary Inbox endpoints in v0.

## Why writes are not direct

Inbox already has a stronger invariant than a generic confirmation dialog: each guarded action is approved through a single-use lease bound to the exact HTTP method, path, provider, operation, account/resource, item count, query hash, payload hash, and expiry.

The MCP layer preserves that sequence:

```text
propose -> pending approval -> explicit confirmation -> lease -> exact execution -> read-back verification
```

Do not add a generic `request(method, path, body)` tool and do not bypass the Inbox approval middleware.

## Local startup

Checkout the branch and install the existing project dependencies:

```bash
git checkout lifeops-mcp-v0
uv sync
```

Use a strong existing Inbox token or generate a new random one. Never commit it:

```bash
export INBOX_SERVER_TOKEN='<strong-random-token>'
```

Start both local services:

```bash
bash scripts/run_lifeops_mcp_v0.sh
```

Defaults:

- Inbox REST: `http://127.0.0.1:9849`
- LifeOps MCP: `http://127.0.0.1:9850/mcp`
- automatic departure-task creation: OFF during validation

The MCP process binds only to loopback. The tunnel is the only intended remote ingress.

## ChatGPT Business connection — preferred

ChatGPT cannot connect directly to localhost. For the actual Business connection, use OpenAI Secure MCP Tunnel so the MCP server stays private rather than placing it directly on the public internet.

In ChatGPT Business on web:

1. As a workspace admin/owner, open Workspace Settings -> Apps -> Create and enable Developer Mode for yourself if needed.
2. Choose the private/local MCP connection flow and Secure MCP Tunnel.
3. Point the tunnel's local target at `http://127.0.0.1:9850/mcp`.
4. Let ChatGPT scan the tools.
5. Keep the app in developer/draft mode while the tool surface is changing.
6. Test the acceptance sequence below before publishing it to the workspace.

Follow the current Secure MCP Tunnel instructions presented by ChatGPT/OpenAI for the tunnel client rather than copying a stale tunnel command into this repository.

## ngrok — useful dev path, not the default trust boundary

For a quick network/MCP smoke test, ngrok can forward an HTTPS endpoint to the local MCP port:

```bash
brew install ngrok
ngrok config add-authtoken '<YOUR_NGROK_AUTHTOKEN>'
ngrok http 9850
```

That produces a public HTTPS endpoint whose MCP URL is approximately:

```text
https://<assigned-host>/mcp
```

Important: **do not connect a bare public ngrok endpoint to personal-data/write tools.** `INBOX_SERVER_TOKEN` protects LifeOps -> Inbox; it does not authenticate Internet -> LifeOps MCP. If ngrok is used beyond a disposable smoke test, add a ChatGPT-compatible MCP authentication layer or verified edge policy first. For the normal ChatGPT Business setup, prefer Secure MCP Tunnel.

## First acceptance test: Street play practice

Do not broaden the connector until this works end to end.

1. `source_health()` shows iMessage/Calendar/Tasks/Maps dependencies usable enough for the test.
2. Search for `street play practice`, `45738 Bridgeport`, or the relevant contact and retrieve the source messages as evidence.
3. Read the 2026-08-24 calendar and identify the existing `Street play practice` event.
4. Calculate travel time for the known legs, including pickup and practice destination.
5. Propose updating the existing calendar event location to the evidence-backed practice address.
6. Show the exact proposed change to the user. Do not approve it implicitly.
7. After explicit user approval, approve and execute the recorded action.
8. Re-read the calendar event and verify the location changed.
9. Run `departure_times` and verify a sensible leave time can now be produced.

A later `prepare_travel` tool may compose these primitives once the behavior is proven. Do not build it first.

## Expansion rule

Add a new MCP write tool only when a real workflow is blocked without it. The next likely candidates are:

- complete/update Google Task
- draft/send or reply to a message
- local notification / Apple Shortcut invocation
- GitHub actions

Each must map to a typed Inbox capability and preserve the same propose/approve/execute/verify discipline where consequences warrant it.

## Non-goals for v0

- no generic shell
- no unrestricted filesystem access
- no arbitrary REST proxy
- no automatic deletion
- no direct messaging writes
- no World Monitor integration
- no Perplexity UI automation
- no Postgres migration
- no new user interface

Those are backlog items, not prerequisites for proving the cockpit.
