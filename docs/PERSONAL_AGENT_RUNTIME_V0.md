# Personal Agent Runtime v0

Status: design contract / tracer-bullet target

## Purpose

Inbox is the canonical personal-data gateway. This document defines the smallest
runtime around Inbox that gives a user one place to think, supports deep work,
can spawn isolated workers, and remains model/provider/runtime agnostic.

This is **not** a new source of truth. It is an execution layer over existing
canonical systems.

## Product outcome

The user should have one front door that can answer and act on questions such as:

- What needs me now?
- What am I waiting on?
- Is anything falling through the cracks?
- What should I work on next?
- Work with me on this one objective.
- Scope this idea; do not activate it yet.
- Spawn a worker for this scoped engineering ticket.

The user should not need to remember which provider, mailbox, project tracker,
model, or agent runtime contains a fact.

## Non-negotiable invariants

1. Inbox owns live operational personal state and personal-data capability policy.
2. Models and agent runtimes are clients, never canonical stores.
3. One canonical owner per fact; other systems link or project it.
4. Capture does not imply commitment.
5. Stored does not imply surfaced; surfaced does not imply notification.
6. Waiting is a machine-readable state with a dependency/trigger.
7. External writes remain approval/capability gated through Inbox policy.
8. Sensitive raw personal data is not copied into worker environments by default.
9. Every agent execution that matters can be traced to input, tools, outputs, and outcome.
10. A user can switch model/provider/runtime without migrating operational state.

## Component ownership

### Inbox

Canonical operational gateway:

- account/source enumeration
- Gmail, Calendar, Tasks, Drive, messages and other live sources
- source attribution and capability readiness
- operational states such as READY / ACTIVE / WAITING / SCHEDULED / DONE
- follow-ups and trigger evaluation
- travel/departure computation
- approval leases and audit metadata
- MCP + HTTP capability surface

### OpenHuman

Optional semantic-memory sidecar, not operational authority:

- entities and relationships
- historical semantic context
- topic/person/project summaries
- long-horizon retrieval

Inbox should be able to call or query this layer, but a memory result must not
silently create a commitment.

### Trajectory

Agent-execution evidence boundary:

- normalize supported agent/runtime transcripts
- retain tool calls/results and reasoning-visible records where available
- feed evaluation/regression datasets
- optionally feed personal-context extraction with provenance

### Notion

Human-readable portfolio/control plane only:

- major commitments/projects
- applications/career pipeline
- system architecture/ownership documentation
- durable conversation summaries/decisions

Do not mirror live source data or repo-local issue state.

### GitHub + Wayfinder

Engineering execution truth:

- repository destination/current state/decisions
- scoped tracer-bullet tickets
- implementation branches/PRs/tests

### Google Calendar / Tasks / Drive

Provider-owned canonical projections:

- Calendar: time-bound commitments and event locations
- Tasks: atomic actions
- Drive: durable files/artifacts

## Runtime abstraction

The runtime should be replaceable. A client needs only:

1. an MCP client
2. a model/provider adapter
3. a session/workspace abstraction
4. an optional sub-agent/spawn abstraction

Target runtimes include OpenClaw, ChatGPT custom MCP surfaces when available,
Hermes, Codex, Claude Code, or future clients.

No runtime-specific session memory is allowed to become the only copy of an
operational commitment.

## Recommended v0 runtime: OpenClaw

Use OpenClaw first as the always-on runtime because it already provides:

- MCP client/server surfaces
- model-provider abstraction and fallbacks
- scheduled/heartbeat execution
- channel routing
- isolated sub-agent spawning
- per-agent/session sandboxing
- Docker and SSH sandbox backends

OpenClaw remains replaceable. Its session store is not canonical personal state.

## Runtime roles

Keep the number of agents small.

### `main`

The one conversational front door.

Responsibilities:

- query Inbox before answering personal-state questions
- decide whether input is reference / possible / active / waiting / scheduled
- surface only attention-worthy state
- initiate deep-work sessions
- delegate bounded work

Default permissions:

- read Inbox + memory
- reversible internal organization
- no unapproved external send/delete/high-risk write

### `worker`

Issue-scoped implementation agent.

Responsibilities:

- receive a GitHub issue/Wayfinder ticket
- work in an isolated worktree/sandbox
- run tests
- produce branch/PR/artifact
- return verification evidence

It does not receive unrestricted personal data.

### `research`

Isolated research/synthesis agent.

Responsibilities:

- current public research
- compare alternatives
- produce source-backed artifact

It receives only explicitly selected private context.

More roles should be added only after a concrete need appears.

## VM / sandbox design

Use a separate worker environment for delegated code/research execution.

Preferred order:

1. local Docker sandbox for ordinary scoped work
2. SSH-accessible Linux VM for heavier/long-running work
3. more specialized managed sandbox only if necessary

The VM is an execution environment, not the brain.

### Worker VM rules

- no personal OAuth tokens by default
- no mount of the user's home directory
- clone only the repository/worktree needed for the task
- short-lived scoped credentials where required
- Inbox MCP access is read-only or capability-limited unless the task genuinely needs more
- outbound network can be restricted per worker type
- worker outputs are commits, PRs, reports, tests, or structured results
- worker result returns to the parent session; the worker does not demand user attention directly

## Deep-work mode

The primary UX goal is to reduce context switching.

### Enter

`focus(objective)`

The main agent creates a Focus Session containing:

- one objective
- definition of done
- selected project/repo/application
- relevant Inbox state
- relevant memory/evidence links
- current Wayfinder/project state
- a short working-context bundle

### During focus

- suppress ordinary FYI and unchanged WAITING items
- interrupt only for a configured high-priority state change
- route new unrelated thoughts to Capture / Possible without switching contexts
- allow the main agent to spawn worker/research sessions
- workers report results to the same focus thread
- never make the user monitor worker dashboards manually

### Exit

A Focus Session must end with one or more explicit outcomes:

- completed
- next action
- waiting dependency
- scoped engineering issue
- durable artifact
- dropped/deferred decision

Then update canonical state and release the context.

## Idea-development workflow

Ideas should not become commitments merely because they are discussed.

```text
capture idea
  -> retrieve related history/work/evidence
  -> research existing systems first
  -> sharpen problem/thesis
  -> define smallest falsifiable experiment
  -> user promotes to ACTIVE only if desired
  -> create project or scoped GitHub ticket
  -> spawn worker if executable
```

This allows exploration without making the attention queue explode.

## Provider/model agnosticism

Model/provider independence is tested, not assumed.

- domain capabilities are MCP tools with stable schemas
- operational state lives behind Inbox
- model refs/config live in runtime configuration
- prompts/policies are versioned separately from personal state
- each critical behavior has model-independent acceptance tests
- changing primary/fallback model must not require data migration

## First vertical slice

Prove one end-to-end loop before adding integrations:

```text
User -> `main` agent
     -> Inbox MCP: `what_needs_me`
     -> choose one scoped GitHub/Wayfinder ticket
     -> spawn isolated worker
     -> worker implements + tests
     -> result/PR returns to main
     -> canonical task/project state updates
     -> user receives one completion/decision message
```

## Acceptance tests

### A. Personal-state parity

Ask two different MCP clients the same fixture-backed question:

`What needs me?`

They must return semantically equivalent canonical items from Inbox, with source
health/completeness metadata.

### B. No duplicate state

A conversation promotes one item to an actionable task. Re-running classification
or using a second client must update/refer to the same canonical item, not create
a duplicate.

### C. Waiting transition

A fixture starts in WAITING with a machine-readable dependency. Trigger change
moves the same record to READY and creates at most one attention event.

### D. Deep-work isolation

During a focus session, informational events and unchanged waiting items do not
interrupt. A configured urgent state change does.

### E. Delegated engineering

`main` can hand one synthetic Wayfinder ticket to an isolated worker. The worker
receives no personal fixtures/secrets, runs the documented safe test suite, and
returns a commit/PR plus verification result.

### F. Runtime/model swap

Run A-E with at least two model/provider configurations. Operational records and
IDs remain unchanged; only runtime/model metadata differs.

### G. Reconciliation

If a source connector is stale/failed, `What needs me?` must not imply complete
coverage. The source-health gap is visible in structured output.

## Rollout

### Phase 0 — protect the substrate

Complete/parallelize the current Inbox reliability Wayfinder work. Do not let
runtime experimentation destabilize the daily-driver server.

### Phase 1 — local vertical slice

- run Inbox server locally
- register Inbox MCP in OpenClaw
- create `main` and sandboxed `worker`
- prove acceptance tests A, B, E, G with fixtures

### Phase 2 — operational-state loop

- generalize WAITING -> READY triggers
- add attention/reconciliation query
- add focus-session suppression policy
- prove C and D

### Phase 3 — memory + trajectory

- connect OpenHuman as a read-oriented semantic context provider
- normalize agent executions with Trajectory
- create regression cases from real failures using sanitized/synthetic fixtures

### Phase 4 — additional client parity

Connect another MCP client/runtime and prove F. ChatGPT, Hermes, Codex, or Claude
Code can serve as the second client depending on current product support.

### Phase 5 — historical ingestion

Only after provenance, deduplication, privacy, and state-promotion rules pass the
vertical-slice tests, ingest historical chats/mail/files at scale.

## Explicit non-goals for v0

- one database containing every raw provider record
- autonomous sending of human communications
- moving canonical tasks/calendar/files into an agent runtime
- adding many agent personas
- building another memory system before evaluating OpenHuman
- running multiple always-on runtimes merely for redundancy
- bulk historical ingestion before the live state machine is trustworthy
- using a VM as a second source of truth
