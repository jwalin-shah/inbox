# ADR 0014: External agent runtime boundaries

## Status

Accepted.

## Decision

LifeOps remains the governed personal-operations surface. Inbox remains the
personal-data gateway and the source-linked event/evidence spine. External
agent runtimes are workers or user interfaces; they are not authorities.

The runtime roles are:

| Runtime | Role | Allowed relationship to LifeOps |
|---|---|---|
| LifeOps + Inbox | Personal-data authority, evidence, projections, approval leases, read-back | Owns the cross-source contract |
| ChatGPT Business | Human-facing MCP client | Uses LifeOps MCP; does not become a database |
| OpenClaw / Pi / DeepSeek harness | Local or always-on workers | Uses the same LifeOps contract; no parallel writer |
| Google Workspace Studio | Google Workspace-native flow builder | May automate Workspace-local work, but must not create a second LifeOps task authority |
| Gemini Spark | Google-hosted personal/Workspace agent | May be a Google-native user surface; cross-source actions should become LifeOps proposals |
| Lindy | Cloud workflow/voice/automation worker | May submit bounded observations or proposals through a brokered adapter; never receives the Inbox bearer token |
| Apple Calendar / Reminders | Device-native display and notification surfaces | Receives approved, deduplicated delivery; does not own cross-source state |

## Data flow

~~~text
Gmail / iMessage / Calendar / Contacts / Drive / Tasks
                         |
                         v
                Inbox event + evidence spine
                         |
                         v
                 LifeOps projections
          (people, commitments, open loops, routes)
                         |
              +----------+----------+
              |                     |
              v                     v
       read/query to agents   proposed action
                                      |
                              human approval
                                      |
                            single-use lease
                                      |
                                  execute
                                      |
                               provider read-back
~~~

## Rules

- Google Calendar remains the cross-account commitment authority.
- Google Tasks remains the canonical approved next-action store until a single
  replacement writer is proven.
- Apple Calendar may display synced Google events and provide native alerts;
  direct Apple-only events are not part of the canonical cross-source view
  until native Apple Calendar read-back is implemented.
- Lindy, Spark, and Workspace Studio may not call arbitrary Inbox REST paths.
- Any external runtime integration must use a typed adapter with an allowlist,
  scoped account identity, idempotency key, provenance, and approval class.
- External runtime observations are appended as evidence; they do not directly
  mutate canonical state.
- A provider action is complete only after the exact provider object is
  re-read and the result is linked to the proposal receipt.

## Consequence

We can add Lindy or Google agents without rebuilding LifeOps. They become
replaceable workers behind the same evidence and approval contract. The next
implementation is a brokered agent-runtime adapter, not a generic HTTP proxy.
