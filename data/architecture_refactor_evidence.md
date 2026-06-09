# Architecture Refactor Evidence

**Date:** 2026-06-07  
**Scope:** Read-only audit + one bounded refactor (max 3 code files)

## Audit Summary

| File | Lines | Role |
|------|------:|------|
| `services.py` | ~7,430 | All provider integrations (iMessage, Gmail, Calendar, WhatsApp, LinkedIn, Drive, Sheets, Docs, GitHub, LLM, search, notifications, voice) |
| `inbox_server.py` | ~6,420 | FastAPI app: routes, Pydantic models, approval gate, provider/capture/index health, scheduler loops |
| `connector_registry.py` | ~710 | Connector catalog, status probes, search execution, sync planning |

## Architecture Issues Identified (5)

1. **`services.py` is a god module** — 150+ public/private functions across unrelated domains with no package boundaries. Any change risks cross-domain regressions and slows navigation.

2. **`inbox_server.py` mixes HTTP, policy, and orchestration** — ~130 Pydantic models, ~250 route handlers, approval-route rules (~500 lines), capture/index health builders, and background scheduler tasks all live in one file. The HTTP layer directly imports dozens of `services` symbols.

3. **`connector_registry.py` couples catalog data with runtime** — Large static `CONNECTORS` tuple (~230 lines) sits beside subprocess execution (`_run`, `search_connectors`, `connector_sync_plan`), making the registry hard to extend without touching probe logic.

4. **Duplicated OpenHuman DB resolution** — `_openhuman_whatsapp_db_*` and `_openhuman_linkedin_db_*` helpers in `services.py` are re-imported by `message_sync.py` and `inbox_server.py`; test fixtures duplicate DB bootstrap in `test_services.py` and `test_message_sync.py`.

5. **Approval routing embedded in server** — `ApprovalRouteRule`, `_route_rule`, `_approval_rule_for_request`, and lease minting live in `inbox_server.py` rather than a dedicated policy module (contrast with prior extraction of `google_account_resolution.py`).

## Refactor Implemented

**Extract iMessage X/Twitter link helpers to `imessage_link_helpers.py`**

Pure string-parsing logic (`extract_x_links`, `strip_url_trailing_punct`) was isolated from `services.py`. `imsg_links()` now imports `extract_x_links` from the new module. Pattern matches existing extractions like `google_account_resolution.py`.

### Files Changed (refactor)

| File | Change |
|------|--------|
| `imessage_link_helpers.py` | **New** — regex + link extraction helpers |
| `services.py` | Removed inline helpers; import `extract_x_links` |
| `tests/test_services.py` | Import from `imessage_link_helpers` instead of `services._extract_x_links` |

## Tests Run

```bash
uv run pytest \
  tests/test_services.py::test_extract_x_links_handles_https_and_bare_urls \
  tests/test_services.py::test_extract_x_links_dedupes_and_strips_trailing_punct \
  -v
```

**Result:** 2 passed in 2.90s (exit 0)

## Top 3 Remaining Refactor Recommendations

1. **Extract approval routing from `inbox_server.py`** — Move `ApprovalRouteRule`, route matching, lease minting, and gate middleware into `approval_routes.py` (or extend existing approval helpers). Reduces server file by ~500 lines and clarifies security boundary.

2. **Split `connector_registry.py` catalog from runtime** — Move `CONNECTORS` definitions + credential schemas to `connector_catalog.py`; keep `connector_registry.py` as thin status/search/sync executor. Enables adding connectors without loading subprocess logic in tests.

3. **Centralize OpenHuman DB path resolution** — Extract `_openhuman_*_db_candidates/path` into `openhuman_store.py` shared by `services.py`, `message_sync.py`, and `inbox_server.py`; dedupe test DB fixtures into `tests/fixtures/openhuman_db.py`.
