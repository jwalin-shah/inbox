# Ticket 005 — Update stale CLAUDE.md references

Label: `wayfinder:ticket`
Status: open
Blocked by: 004
Blocks: —

## What

Update CLAUDE.md to remove references to files that no longer exist. The
`docs/agents/` stubs were removed in commit 087b294 but CLAUDE.md still
references:
- `docs/agents/issue-tracker.md`
- `docs/agents/triage-labels.md`
- `docs/agents/domain.md`

Either recreate minimal versions of these docs if they serve a purpose, or
remove the references.

## Why

Stale doc references mislead agents and contributors. CLAUDE.md is the first
thing an agent reads when working in this repo — every claim in it must be
verifiable.

## Acceptance

- No references in CLAUDE.md to files that don't exist on disk
- If docs are recreated: minimal, accurate, useful
- If references are removed: the information they pointed to is either
  captured elsewhere or deemed unnecessary
- `rg "docs/agents" CLAUDE.md` returns no hits (or only hits for existing files)
