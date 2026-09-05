# Inbox — Wayfinder Map

Label: `wayfinder:map`

## Destination

Inbox is a reliable daily-driver unified inbox TUI. The server stays up, data
sources stay fresh, agents interact through the MCP interface without surprises,
and the codebase is maintainable enough that adding a new data source or slash
command is measured in hours, not days. Test coverage is at 90%+ with zero
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
- LifeOps action coordination: local capability inventory, deterministic
  `task.create` route selection, plan-only trace creation, and read-back were
  verified on 2026-08-31 (`cmd_a139357706c64e06a0ad386c72bbc65d`); provider
  state was not changed
- LLM stack: Qwen3.5-0.8B-MLX-4bit for extraction + autocomplete, Outlines for
  constrained generation
- Ambient audio: capture → ASR → extraction → Obsidian notes pipeline
- Scheduler: background task runner with persistent SQLite state
- Test suite: 2,029 passing in the repository-local `.venv` on 2026-08-31
- Overall coverage: 84% in that same local run

**Broken:**
- No current full-suite failure was observed in the repository-local `.venv`.
  This is a local reproducibility result, not proof of deployment or live
  provider access.
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

## Decisions so far

- 2026-08-31: **Local full-suite verification.** The repository-local `.venv`
  passed 2,029 tests with 84% coverage. The result is recorded as local test
  evidence only; deployment, live provider access, and external writes remain
  separate gates.

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
