# Ticket 006 — Prove Inbox MCP from an external agent runtime

Label: `wayfinder:ticket`
Status: open

## What

Prove that the existing Inbox MCP server can be registered and consumed by one
external agent runtime without making that runtime a source of truth.

Use OpenClaw as the first reference client. Keep the integration replaceable: no
OpenClaw-specific state may be required for Inbox correctness.

## Why

Inbox already exposes the capabilities. The next tracer bullet is to prove that
an always-on agent runtime can use those capabilities through MCP while Inbox
continues to own canonical state, source attribution, approvals, and audit.

## Acceptance

- Document the exact command/config needed to register the local Inbox MCP server
  in OpenClaw.
- `openclaw mcp ...` can enumerate the Inbox MCP tools successfully.
- A fixture/safe read can query Inbox health/source readiness through MCP.
- A fixture/safe read can query one structured Inbox capability through MCP.
- Results retain account/source attribution supplied by Inbox.
- No live external mutation is required for this ticket.
- No personal data is copied into test fixtures or committed to the repository.
- Restarting or replacing the OpenClaw client does not change Inbox canonical
  state.
- Add a short runbook under `docs/` for reproducing the proof.
- Run the documented agent-safe test command and include the result in the
  implementation report/PR.

## Constraints

- Do not change the primary daily-driver server/worktree during development.
- Use the existing alternate-port/worktree workflow where server changes are
  needed.
- Do not add another database for runtime state.
- Do not bypass Inbox approval policy.
- Do not add new source integrations as part of this ticket.

## Follow-on

After this works, a separate ticket can add a sandboxed worker profile and prove
issue-scoped delegation. The broader contract is documented in
`docs/PERSONAL_AGENT_RUNTIME_V0.md`.
