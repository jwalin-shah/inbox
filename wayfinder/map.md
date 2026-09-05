# Inbox — Wayfinder Map

Label: `wayfinder:map`

## Destination

Inbox is a reliable daily-driver unified inbox TUI. The server stays up, data
sources stay fresh, agents interact through the MCP interface without surprises,
and the codebase is maintainable enough that adding a new data source or slash
command is measured in hours, not days. The coverage target is 90%+ with zero
flaky tests. The codebase layout is consistent (no split between root and
`src/` modules).

## Notes

- Inbox is the captain's primary communication surface — downtime means missed
  messages, calendar events, and GitHub notifications. Reliability is the top
  priority.
- The gnhf test-coverage push (16 iterations, June-July 2026) raised coverage
  from ~70% to 82% and found real bugs (resource leaks, TypeError crashes).
  This was a good investment but it stopped mid-stream — the lowest-coverage
  files remain untouched.
- The `src/` directory was introduced during the gnhf series for new modules
  (`src/imessage_surface.py`, `src/imessage_learning.py`, etc.) while legacy
  code still lives at root (`services.py`, `inbox.py`, etc.). This split is
  accidental, not intentional — the gnhf agent placed new files in `src/`
  without a decision to reorganize the whole tree.
- The worktree dev workflow is documented and proven — primary on port 9849,
  dev worktrees on 9850+. This works well and should be preserved.
- 22 remote branches from Codex runs (SYM-*, WP-*) exist on origin. Most are
  stale; some may contain unlanded work. None have open PRs against main.

## Current state

**Working:**
- Server + TUI: starts cleanly, all tabs functional (iMessage, Gmail, Calendar,
  Notes, GitHub, Reminders)
- Multi-account Google: OAuth flow, token storage, account routing
- MCP server: stdio-based, exposes all inbox functionality to agents
- Agent slash commands: `/inbox morning-brief`, `triage`, `followup`, `batch`,
  `health` — all working
- LLM stack: Qwen3.5-0.8B-MLX-4bit for extraction + autocomplete, Outlines for
  constrained generation
- Ambient audio: capture → ASR → extraction → Obsidian notes pipeline
- Scheduler: background task runner with persistent SQLite state
- Test suite: 2,041 passing after the LifeOps worker, client-configuration,
  profile-verifier, task-review, and runtime-verifier changes
  changes; the prior `test_print_summary_with_threads` failure is no longer
  present in the current run
- Overall coverage: 83% (5,751/33,903 statements missed in the current run;
  remaining misses are concentrated in provider/error paths and utility
  scripts)

**Broken:**
- `unsubscribe_bulk.py` at 6% coverage, `unsubscribe_interactive.py` at 6%
  — these are the lowest-coverage files and were skipped in the gnhf push
- `docs/agents/` stubs were removed in the most recent commit (087b294) but
  CLAUDE.md still references `docs/agents/issue-tracker.md`,
  `docs/agents/triage-labels.md`, and `docs/agents/domain.md` — stale docs refs

**Unknown:**
- Whether any of the 22 stale Codex remote branches contain valuable unlanded
  work (SYM-115 through SYM-214, WP-014 through WP-182)
- Whether the ambient daemon's auto-start on server boot works reliably after
  the gnhf refactors (it was tested to 98% but only with mocks)

## LifeOps MCP v0 overlay — 2026-08-25

**Destination:** One governed LifeOps capability surface over the existing
Inbox server, with Streamable HTTP for ChatGPT Business and stdio for local
agents such as OpenClaw, Pi, and DeepSeek harnesses.

**Findings:** The v0 adapter now exposes read-only source-scoped search,
Google Sheets discovery/metadata/range reads, unified contacts, exact message
thread and calendar-event reads, current-location access, an attributed triage
projection, a bounded multi-source triage classifier, source health, calendar, travel, and Tasks. Its stdio transport was handshake-proved with
protocol `2025-06-18`; its read-only Sheet search and metadata/range reads
returned live Inbox-backed results. OpenClaw now has a side-by-side `lifeops_v0`
stdio server with writes excluded by tool filter. Existing older MCP servers
remain enabled until parity is proven.

**Decisions:** Google Drive/Sheets remain source systems; Inbox remains the
personal-data gateway; LifeOps is the governed MCP surface. `gog` is not a
required authority and is not installed on PATH. No second Google credential
store is introduced.

**Not yet specified:** When the older OpenClaw Inbox/LifeOps surfaces can be
removed; the canonical Google account for the LifeOps-named Sheets; how to
persist metadata-only triage receipts without changing `triage_all`'s
read-only contract.

**Out of scope:** Disabling existing agent surfaces, enabling v0 writes for
OpenClaw, moving Sheets data to Oracle, or installing `gog` before a real gap
is demonstrated.

## External agent-runtime boundary — 2026-08-25

**Decision:** LifeOps/Inbox remains the personal-data authority and approval
surface. ChatGPT Business, OpenClaw, Pi, DeepSeek harnesses, Lindy, Gemini
Spark, and Google Workspace Studio are replaceable clients or workers. Apple
Calendar/Reminders are notification and display surfaces.

**Findings:** Lindy documents autonomous Gmail/Calendar workflows, HTTP
requests, webhooks, and computer use. Google distinguishes Gemini Spark from
Workspace Studio: Spark is the personal/Workspace agent surface, while Studio
builds Workspace flows. Neither has been connected to this LifeOps checkout.

**Not yet specified:** The typed adapter contract for external agents beyond
the scoped worker packet, signed observation ingress, and the exact approval
class for each proposed action. The restricted worker profile now has an
explicit account allowlist. Pi has a project override that disables the broader
Inbox entries and exposes the two worker tools directly. Antigravity has a
native `lifeops-worker` registration and tool-schema discovery, but its headless
MCP permission path still needs an interactive call proof. Orca/Agy/Cursor
still do not have a governed execution adapter.

**Scope clarification (2026-08-25):** A worker packet's account selector
constrains provider reads wherever Inbox supports account routing. The canonical
local personal graph (Apple Contacts, approved identity links, local memory,
and explicitly captured property observations) is user-scoped rather than split
into one graph per Google account. The packet labels this distinction instead
of claiming tenant-style isolation. MCP registration also does not sandbox a
host agent's own shell or filesystem permissions.

**Task review (2026-08-25):** The live reconciliation reports 47 visible
Google Tasks and four conservative duplicate groups. LifeOps now exposes a
separate `task_duplicate_review` read-only projection with deterministic review
IDs and no mutation path; the current groups remain human-review items.

**Read-surface verification (2026-08-25):** A repeatable standard-library
verifier now proves the `2025-06-18` HTTP handshake, required read tools,
read-only annotations, and a bounded account-scoped `evidence_packet` without
printing personal content or calling a write tool. This is a runtime contract
check, not proof of a ChatGPT UI call or host-agent shell permissions.

**Orca/Pi read proof (2026-08-26):** The v0 checkout is registered as an Orca
worktree. An Orca-managed Pi terminal loaded `lifeops-worker` and completed a
bounded `evidence_packet` call for an allowlisted account, returning
`lifeops.evidence_packet.v1` with read-only and all four restrictive scope
flags proven. The temporary terminal was stopped after the proof. Orca's
general shell and execution capabilities remain separate and are not granted
by this MCP registration.

**Context reliability proof (2026-08-26):** `life_context` now limits its
read fan-out and retries one transport-level failure within the read-only
projection. Focused tests passed, the full read-surface verifier passed
against the managed endpoint, and three consecutive bounded live context
calls returned `lifeops.context.v1` without unavailable-source limitations.
Write paths do not use this retry behavior.

**Canonical-sheet account routing (2026-08-26):** The three loaded Google
accounts are provider scopes, while the LifeOps/Master Ops/project-tracker
Sheets are one canonical user-scoped personal-operations source. `life_context`
now sends those three projections through the explicit
`LIFEOPS_CANONICAL_GOOGLE_ACCOUNT` (the current deployment's
`jshah1331@gmail.com`) instead of forwarding the selected Gmail account. Live
Inbox probes showed the sheets are readable through that account and return
502 when routed through the other two accounts; this distinction is now
recorded in `source_health` rather than surfacing false unavailable-source
gaps for account-scoped context.

**Project-link normalization fix (2026-08-26):** Explicit LifeOps action and
project references now split the word `and` using a real word-boundary regex.
The prior separator contained a control character, so compound references
could remain unmatched. A regression test now proves that two explicit
projects resolve independently while retaining their source references.

**Unscoped provider aggregation (2026-08-26):** A blank `life_context`
account now reads Inbox's account inventory and explicitly fans out Docs,
Calendar, Drive, and Tasks across all loaded Google accounts. An exact
`account` still selects one provider account. If inventory discovery fails,
the route preserves the old default fallback but emits an incomplete-scope
limitation rather than presenting one mailbox as all-account context.

**Cross-process read coordination (2026-08-26):** LifeOps read projections
now coordinate separate MCP processes through a per-user owner-only lock file,
in addition to the in-process concurrency gates. This protects the shared
Inbox/provider session when HTTP, stdio, or restricted worker clients run at
the same time. It is a read-contention guard only; it does not expand client
permissions, turn partial results into complete results, or govern writes.

**Bounded triage recovery (2026-08-26):** A live revalidation reproduced the
request timeout on the bounded evidence packet when `/inbox/now` consumed the
request retry window. `triage_all` now caps each source read at 8 seconds and
the whole sequential triage at 45 seconds, returning a source-level
`read_errors` limitation and a unique `lifeops.triage_receipt.v1` run ID with
per-source transport trace. After restart, HTTP and restricted stdio proofs
both exited 0 concurrently in under 25 seconds. This is a bounded-read proof,
not provider completeness; the metadata-only receipt is also persisted locally
and can be read back by run ID.

**Bounded context recovery (2026-08-26):** `life_context` now applies an
8-second per-read and 120-second total deadline to its supplemental source
reads. They are scheduled in sequence because they share provider/session
objects and a cross-process lock. A hanging provider is returned as
source-health/limitation evidence instead of blocking the one-surface context
route. This protects response latency; it does not turn partial context into
complete coverage.

**TokenRouter triage compatibility (2026-08-26):** A live Kimi K3 catalog
read and bounded inference request succeeded through the Keychain-backed
TokenRouter route. The LifeOps adapter initially sent the DeepSeek-specific
disabled-thinking option, which Kimi rejects; it now selects
`reasoning_effort=low` for Kimi K3 and preserves the actual returned model in
the triage classification method. The live proof is synthetic and bounded;
it does not authorize unattended personal-data triage or imply that every
catalog-listed model is free or entitled.

**Restricted-client proof (2026-08-26):** OpenClaw's `lifeops_v0` probe
 returned 43 tools from the actual annotation-derived `read_only` process,
with `life_context` and `triage_all` present and no diagnostics. Hermes connected to
`lifeops_v0_readonly` and discovered the same 43-tool read catalog; its
`lifeops_v0_worker` entry still discovers exactly two tools, and DeepSeek Harness
completed one real bounded `evidence_packet` call. The new stdio verifier
also passed the exact two-tool worker set and all four restrictive scope
flags. These prove client consumption of the read boundary; they do not
grant those clients provider-write or host execution authority.

**ChatGPT Business app wiring (2026-08-26):** In the signed-in ChatGPT
Business workspace `Jwalin Shah's Workspace`, the installed `lifeops` app was
opened from the Plugins directory and `Try in chat` placed the `lifeops`
selection pill in the Work composer. This proves the app is installed and
selectable in the intended workspace. A subsequent bounded `source_health`
call and a `search` call for `LifeOps` both returned successfully in the
current ChatGPT context, with one search result and no provider mutation.
This proves the connected read path; it does not prove provider completeness
or any write/approval action.

**Transport profile hardening (2026-08-26):** LifeOps now supports an
annotation-derived `read_only` profile that removes every tool without an
explicit `read_only_hint=true`, alongside the existing exact two-tool
`worker` profile and the approval-capable `full` profile. The legacy
`lifeops` Business tunnel remains on `full`; a separate `lifeops-readonly`
tunnel runs the read-only process on port 9851. This preserves the legacy app
while giving the published `lifeops-read-only` app an isolated 43-tool catalog.

**Business app publication (2026-08-26):** The Business workspace
`Jwalin Shah's Workspace` now contains the published `lifeops-read-only` app
(`asdk_app_6a8f20a754d081918f4e6828cc1b6fa9`) bound to
`tunnel_6a8f1ed22d908191a4f3402d6cc5e74a` (`lifeops-readonly`). A
`server/discover` compatibility shim returns an honest 2025-06-18 discovery
card for Secure MCP Tunnel validation; the app imports 43 read tools and no
proposal/approval/execution tools. Publication proves catalog delivery, not a
fresh ChatGPT conversation call.

The shared Claude/Cursor configs now expose a named `lifeops-readonly` entry,
and OpenClaw's `lifeops_v0` entry starts the adapter with the same
`read_only` profile and complete read catalog. Legacy broad OpenClaw entries
remain visible until their parity and retirement are separately proven; this
change does not silently revoke those older surfaces.

**Bridge handoff design (2026-08-26):** Bridge ADR 0012 now specifies a
proposed reference-only LifeOps evidence binding. It carries packet identity,
canonical digest, declared account scope, freshness/limitations, and source
references, but no raw personal content or credentials. It is not implemented
or an execution/approval grant yet; the typed contract and review gate remain
the next Bridge slice.

**Overnight improvement record (2026-08-26):** The single control document at
`docs/overnight-improvement-record-2026-08-26.md` records the verified baseline,
decision rationale, worker/permission boundaries, acceptance tests, overnight
queue, and the learning loop for rejecting false completion claims. It is a
coordination record, not a grant of new permissions or a replacement for live
receipts.

**Additional finding (2026-08-25):** The BTW review found two different
repositories called `btw-v2`: a newer docs-only clean-slate repository nested
under `/Users/jwalinshah/projects/btw-v1/btw-v2`, and the older built `btw-v1`
repository used by the current Orca worktree. Their names must not be used as
an integration target until the canonical repository is explicitly chosen.
The review also found that an internal worker fork emitted a premature
completion signal while its parent terminal was still active. Worker status
is therefore not accepted as delivery proof without a coordinator receipt,
exact worktree binding, and an independently readable artifact.

**Out of scope:** Giving Lindy, Spark, or Workspace Studio the Inbox bearer
token; allowing any of them to call arbitrary Inbox REST; or creating a second
task/calendar database.

## Decisions so far

- 2026-07-17: **Memjuice strip + cleanup.** Removed auto-generated `docs/agents/`
  stubs, stripped memjuice context from AGENTS.md, added `__init__.py` files,
  updated `.gitignore`. CLAUDE.md references to `docs/agents/` still need
  updating.
- 2026-06 through 2026-07: **gnhf test-coverage push.** 16 iterations raised
  coverage from ~70% to 82%. Each iteration targeted a specific module, added
  focused unit tests, and fixed real bugs found by the tests. Pattern proven:
  resource leaks (`client.close()` on early returns) and TypeError crashes
  (None.email) found repeatedly across utility scripts.
- 2026-05: **Client-server architecture.** Server handles all data access
  (FastAPI, port 9849), TUI is a thin Textual client, agents hit the server
  via MCP or HTTP. This split lets the server run continuously while the TUI
  restarts, and lets agents work without the TUI running at all.
- 2026-Q1: **Python + Textual + Rich stack.** Chosen over Go+TUI for rapid
  prototyping and access to Google API Python client libraries. No plan to
  rewrite in another language.
- **Worktree dev workflow.** Primary checkout stays on main, port 9849.
  Development happens in git worktrees on alt ports (9850+). This avoids
  disrupting the daily-driver inbox during development. Documented in
  CLAUDE.md and proven across multiple dev sessions.
- **MLX-native AI stack.** Qwen3.5-0.8B-MLX-4bit for LLM, mlx-whisper for ASR,
  Outlines for constrained generation. All run locally on Apple Silicon. No
  cloud dependency for core AI features.

## Not yet specified

- **Root vs `src/` split.** The gnhf series introduced `src/` for new modules
  (`src/imessage_surface.py`, `src/imessage_learning.py`,
  `src/contact_relationship_sync.py`, `src/multi_source_sync.py`) while legacy
  code remains at root (`services.py`, `inbox.py`, `inbox_server.py`, etc.).
  Is the plan to move everything to `src/`? If so, when and in what order?
  If not, should the `src/` modules move back to root to match the existing
  pattern?
- **Ambient daemon as separate process.** Currently `ambient_daemon.py` runs
  inside the server process. Should it be a standalone daemon that the server
  manages? This would isolate ASR crashes from the server and allow independent
  restarts.
- **Stale Codex branches.** 22 remote branches from Codex runs. Some may
  contain useful work (MCP path encoding, Gmail history incremental sync, TUI
  refresh snapshot, calendar date range). Need a triage pass: which to land,
  which to delete.
- **Coverage target.** The gnhf push stopped at 82%. Is 90% the target? 95%?
  What's the stopping condition — all modules above some threshold, or just
  "no more low-hanging fruit"?
- **Flaky test prevention.** One test is currently failing. Is there a CI gate
  that catches regressions? The `scripts/validate_agent_safe.sh` wrapper exists
  but it's unclear if it runs on every push.

## Out of scope

- **New data source integrations** (Slack, Discord, WhatsApp, etc.). These are
  feature work, not baseline quality. They get their own map after this one
  is resolved.
- **TUI framework rewrite.** Textual is working. No migration to a different
  TUI framework or a web UI.
- **Multi-machine sync.** Inbox runs on one machine. Syncing state across
  machines is a separate concern.
- **Production deployment.** Inbox is a personal tool. Packaging for others
  (Homebrew formula, PyPI package) is out of scope.

## Tickets

Tickets are tracer-bullet: each resolves one unknown and unblocks the next.
Resolve in order.

| # | Ticket | Blocks | What it resolves |
|---|--------|--------|------------------|
| 001 | Fix failing test and add CI guard | 002 | Single known breakage; prove CI catches regressions |
| 002 | Coverage: utility scripts (unsubscribe_*) | 003 | Last sub-50% modules; close the gnhf gap |
| 003 | Resolve root vs `src/` split | 004 | Codebase layout consistency decision |
| 004 | Triage stale Codex remote branches | 005 | Either land valuable work or delete dead branches |
| 005 | Update stale CLAUDE.md references | — | `docs/agents/` refs removed from disk but still in docs |
