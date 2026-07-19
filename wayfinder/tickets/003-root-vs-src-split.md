# Ticket 003 — Resolve root vs `src/` split

Label: `wayfinder:ticket`
Status: open
Blocked by: 002
Blocks: 004

## What

Decide and execute: either move all production code to `src/` (Python package
layout) or move the `src/` modules back to root (flat layout matching the
existing pattern). Update all imports, test paths, and `pyproject.toml`
accordingly.

## Why

The current split is accidental — the gnhf agent placed new modules in
`src/` without a decision to reorganize the whole tree. This creates
confusion: some modules are at root (`services.py`, `inbox.py`), others in
`src/` (`src/imessage_surface.py`, `src/imessage_learning.py`,
`src/contact_relationship_sync.py`, `src/multi_source_sync.py`). New
contributors (or agents) don't know where to put new files.

## Acceptance

- Decision documented in this ticket (flat or package layout)
- All imports updated and working
- Full test suite passes: `uv run pytest` — 0 failures
- `uv run ruff check --fix .` clean
- `uv run pyright` clean
- `scripts/validate_agent_safe.sh` exits 0
- CLAUDE.md updated to reflect the chosen layout

## Approach notes

Option A (flat): move `src/*.py` → root. Simpler, matches the existing
pattern, no package setup needed. Downside: less conventional for Python
projects of this size.

Option B (package): move root modules → `src/inbox/`. Add `pyproject.toml`
package config. More conventional, better for tooling. Downside: more churn,
every import changes from `import services` to `from inbox import services`.

Recommendation: Option A (flat) unless there's a compelling reason for a
package. The project works fine flat, and the captain's time is better spent
on features than restructuring.
