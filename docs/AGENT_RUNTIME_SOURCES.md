# Agent runtime sources

This document records how agent runtimes participate in LifeOps without
becoming a second personal-data authority.

## Ownership

| Surface | Role | LifeOps access | Writes |
| --- | --- | --- | --- |
| Inbox/LifeOps | Personal-data authority, evidence, triage, approvals, receipts | Canonical | Approval-gated only |
| OpenHuman | Local memory and agent runtime | Read local/exported stores through explicit adapters | Never through the connector registry |
| Hermes Agent | Agent runtime, skills, sessions, MCP client | Filtered LifeOps MCP only | Proposal-only until separately approved |
| OpenClaw | Channel/runtime and notifications | Existing filtered LifeOps MCP surfaces | Existing approval boundaries |

## Current state

The connector registry reports these runtimes as inventory entries. It does not
claim that they are installed, authenticated, or usable. Those states must be
proved independently:

1. runtime binary or application exists;
2. local store exists and is readable;
3. source-specific read proof succeeds;
4. normalized records retain source IDs and timestamps;
5. no write is enabled without an Inbox approval lease and provider read-back.

OpenHuman already has explicit read-only WhatsApp and LinkedIn database readers
in `message_sync.py`. The runtime inventory is separate so an OpenHuman app
installation is not mistaken for a configured local store or authenticated
provider. The current Mac has the native app installed, but its workspace and
account onboarding still require an independent read proof.

Hermes is installed locally and is connected to the existing filtered LifeOps
MCP surface with six explicitly allowlisted read tools. Its first integration
target is not direct access to the Inbox SQLite database or provider
credentials. Hermes MCP guidance also recommends starting with one server and
an explicit tool allowlist.

The current setup proof is:

- Hermes `0.20.5` is installed at `~/.local/bin/hermes` and its local state is
  present at `~/.hermes`.
- OpenHuman `0.63.12` is installed as `/Applications/OpenHuman.app`; its local
  workspace is not present yet, so no provider read proof exists.
- Hermes `lifeops_readonly` uses
  `/Users/jwalinshah/projects/dotfiles/bin/lifeops-mcp-readonly` and selects
only `life_triage`, `life_what_needs_me`, `get_memory`,
  `life_context`, `list_open_commitments`, and `search_personal_data`.
- The MCP initialize, tool discovery, and `life_what_needs_me` read call have
  all passed locally.
- An OpenClaw-to-Hermes `user-data` migration was previewed with `--dry-run`.
  It was not applied because OpenClaw is running and the preview includes
  multiple MCP definitions; importing secrets is intentionally disabled.

## Invariants

```text
runtime_present(r) = true does not imply source_authenticated(r) = true
source_authenticated(r) = true does not imply write_authorized(r) = true
write_authorized(r, action) -> approval_lease(action) ∧ provider_readback(action)
```

Agent runtime setup must therefore be staged: inventory, read proof, filtered
MCP exposure, proposal proof, then an independently reviewed write path.
