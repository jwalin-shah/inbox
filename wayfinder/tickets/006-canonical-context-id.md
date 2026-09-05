# Ticket: Retarget LifeOps context projection to Canonical Registry

**ID:** INBOX-CONTEXT-CANONICAL-001  
**Date:** 2026-09-04  
**Status:** Fixed in tree (unit tests passed)

## Bug

`inbox_server._LIFEOPS_CONTEXT_SPREADSHEET_ID` defaulted to LEGACY workbook  
`1w0kjB11MW6lt9B-hD1g_Vzzb-FFp4KBdygv0qHtf_Ac`  
(Drive title: prefer Canonical Context Registry).

`/lifeops-sheet/projection` therefore read non-authoritative state. Tab names also differed.

## Fix

| | Before (LEGACY) | After (Canonical) |
|---|---|---|
| Spreadsheet | `1w0kjB11MW6lt9B-hD1g_Vzzb-FFp4KBdygv0qHtf_Ac` | `10XAlrmI7tMvXADyrHVK7hLYGcDV6V-IxZhihtxsh5m8` |
| people | `People` | `04_PEOPLE` |
| actions | `Actions` | `05_ACTIONS` |
| projects | `Projects` | `03_PROJECTS` |
| auxiliaries | Captures, Values, Authority Map, … | `01_PROFILE` … `15_RESEARCH_QUESTIONS` |

Env overrides: `LIFEOPS_CONTEXT_SPREADSHEET_ID`, `LIFEOPS_CONTEXT_TAB_{PEOPLE,ACTIONS,PROJECTS}`.

## Prove

```bash
cd ~/projects/inbox && .venv/bin/python -m pytest \
  tests/test_server_endpoints.py::TestContactsEndpoints::test_lifeops_sheet_projection_preserves_people_and_action_rows \
  tests/test_server_endpoints.py::TestContactsEndpoints::test_lifeops_sheet_projection_can_include_bounded_auxiliary_tabs \
  -q
# → 2 passed (2026-09-04)

# Live: Sheets API lists Canonical tabs 00_README … 15_RESEARCH_QUESTIONS
# Drive title for new default: "Jwalin — Canonical Context & LifeOps Registry"
```

## Challenge

ID-only swap would have broken projection — Canonical tab titles use numbered prefixes, not LEGACY `People`/`Actions`.
