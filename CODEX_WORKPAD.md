# MAX-90 Workpad

Issue: MAX-90, Inbox: extract compact Inbox Now read-only surface from PR #47
Branch: codex/MAX-90-inbox-now-readonly
Base: origin/main @ 42a32a2

## Acceptance Criteria

- Add a fresh-main `/inbox/now` read-only API surface without promoting stacked draft PR #47.
- Preserve privacy posture: no raw thread provider fallback and no write action exposure.
- Teach `InboxClient` and the TUI refresh loop to consume the compact read model when available.
- Validate with focused server/client/TUI tests and `git diff --check`.

## Plan

- Add `InboxNowOut`, read-model helper serialization, and `/inbox/now`.
- Add `InboxClient.inbox_now`.
- Let the TUI prefer `client.inbox_now(limit=20)` and fall back to existing index health/views.
- Port focused tests from the draft PR, adjusted to current main's existing thread summary model.

## Validation

- Pass: `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_server.py tests/test_client.py tests/test_inbox_app.py -q -k "now or needs_action or index_health"` (`26 passed, 327 deselected`)
- Pass: `uv run ruff check inbox_server.py inbox_client.py inbox.py tests/test_server.py tests/test_client.py tests/test_inbox_app.py`
- Pass: `git diff --check`
- 2026-05-11 factory privacy audit: `/inbox/now` no longer copies raw Google Task notes or Calendar event descriptions into `now_items`; focused regression asserts raw note/description text is absent.
- 2026-05-11 PR-readiness account-isolation review: `/inbox/now?account=...` now filters Calendar events by account before adding event items, preventing other-account event titles/descriptions from crossing into the compact read model.
- Pass: `git diff --check`
- Pass: `uv run ruff check inbox_server.py inbox_client.py inbox.py tests/test_server.py tests/test_client.py tests/test_inbox_app.py`
- Pass: `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_server.py -q -k "inbox_now"` (`2 passed, 123 deselected`)
- Pass: `UV_CACHE_DIR=/tmp/uv-cache INBOX_TEST_MODE=1 uv run pytest tests/test_server.py tests/test_client.py tests/test_inbox_app.py -q -k "now or needs_action or index_health"` (`26 passed, 327 deselected`)

## Evidence

- PR: https://github.com/jwalin-shah/inbox/pull/48
- Implementation commit: `70c626980e57b83af1843a928f421a86c73eebd1`
- Privacy/account-isolation review commit: `4ce53b14662358d9cbbe3d2a20a29bcdf6ad7450`
- No blockers.
