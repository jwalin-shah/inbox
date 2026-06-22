# Inbox Personal Data Gateway Validation

**Date:** 2026-06-07  
**Validator:** QA subagent (inbox gateway workpack)  
**Live target:** `http://127.0.0.1:9849` (launchd `com.inbox.backend`)  
**Source repo:** `~/projects/inbox`

---

## 1. Source tests (pytest)

**Command:**

```bash
cd ~/projects/inbox && uv run pytest \
  tests/test_imessage_link_helpers.py \
  tests/test_server.py::TestMessages::test_imessage_links_extracts_x_urls \
  tests/test_approval_route_gate.py::test_missing_lease_denies_imessage_send_before_provider_call \
  -q
```

**Result: 5 passed, 0 failed** (2.41s)

| Test | Status |
|------|--------|
| `test_extract_x_links_handles_https_and_bare_urls` | PASS |
| `test_extract_x_links_dedupes_and_strips_trailing_punct` | PASS |
| `test_extract_x_links_ignores_unrelated_text` | PASS |
| `TestMessages::test_imessage_links_extracts_x_urls` | PASS |
| `test_missing_lease_denies_imessage_send_before_provider_call` | PASS |

**Conclusion:** `GET /imessage/links` and the iMessage send approval gate behave correctly in source/tests.

---

## 2. Live server probes

**Auth:** Bearer token from `~/.config/inbox/server.env` (`INBOX_SERVER_TOKEN` present; value not logged).

**Process:**

| Field | Value |
|-------|-------|
| launchd label | `com.inbox.backend` |
| PID | 23314 |
| Started | Sun Jun 7 12:38:13 2026 |
| Elapsed at probe | ~1h14m |
| Launcher | `/Users/jwalinshah/Applications/InboxBackend.app/Contents/MacOS/InboxBackend` |
| Actual runtime | `/Users/jwalinshah/projects/inbox/.venv/bin/python3 inbox_server.py` |

**Note:** `InboxBackend.app` is a shell-script launcher (not a frozen binary). It `cd`s to `~/projects/inbox`, sources `server.env`, and `exec`s the project venv `inbox_server.py`.

| Route | HTTP | Notes |
|-------|------|-------|
| `GET /health` | **200** | `status: ok`; Gmail/Calendar/Drive/Sheets accounts loaded; `api_auth_required: true` |
| `GET /gateway/status` | **200** | `health.status: degraded` (Google OAuth remediation hint); imessage provider `readable: true` |
| `GET /imessage/links?q=x&limit=5` | **404** | Body: `{"detail":"Not Found"}` |
| `GET /conversations?source=imessage&limit=1` | **200** | Other iMessage read paths work |

**`/imessage/links` mounted on live server?** **No** (404).

**Root cause (stale process):** `inbox_server.py` was modified at **13:39** (commit `e583317 Add iMessage API endpoints`), but the live process started at **12:38** — before the route existed. The running FastAPI app never picked up the new endpoint.

---

## 3. Orchestrator fallback (`sync_tweets_from_imessage.py`)

**Command:**

```bash
cd ~/projects/orchestrator-mvp && python3 scripts/sync_tweets_from_imessage.py
```

**Result:** exit 0 — `Catalog: 10 tweets (0 new from iMessage)`

**Fallback chain (traced):**

1. HTTP `GET /imessage/links?q=x&limit=5` → **404** (`urllib.error.HTTPError`, subclass of `URLError` → caught).
2. Script falls back to `import services` from `~/projects/inbox`.
3. With **system `python3`**: fallback **fails** — `ModuleNotFoundError: No module named 'google.auth'`.
4. Exception swallowed → returns `[]` (silent empty result).
5. With **inbox venv** (`PYTHONPATH=~/projects/inbox`, venv on `PATH`): fallback **succeeds** — `services.imsg_links(link_type="x", limit=5)` returned **5 rows**.

**Conclusion:** Fallback logic is wired correctly (HTTP failure → local `services.imsg_links`), but the orchestrator's default `python3` lacks inbox dependencies, so the fallback **does not actually work** in the normal invocation path. The script exits 0 with zero new tweets, masking the failure.

---

## 4. Recommendation

### Immediate: restart launchd service (not rebuild app)

`InboxBackend.app` already launches source from `~/projects/inbox`. Rebuilding the `.app` wrapper is unnecessary; the live process is simply stale.

```bash
launchctl kickstart -k gui/$(id -u)/com.inbox.backend
# then verify:
curl -s -H "Authorization: Bearer $INBOX_SERVER_TOKEN" \
  "http://127.0.0.1:9849/imessage/links?q=x&limit=3"
```

Expected after restart: **200** with JSON link rows.

### Secondary: harden orchestrator fallback

Update `sync_tweets_from_imessage.py` to invoke fallback via inbox venv:

```bash
~/projects/inbox/.venv/bin/python3 -c "import services; ..."
```

—or call `uv run` from `~/projects/inbox`—so HTTP 404/offline does not silently return an empty list.

### Do not rely on dev-server vs packaged-binary distinction here

Both paths run the same source `inbox_server.py` today. The gap is **process age**, not packaging.

---

## 5. Summary

| Check | Status |
|-------|--------|
| Source tests | **5/5 pass** |
| Live `/health` | **200 OK** |
| Live `/gateway/status` | **200 OK** (degraded) |
| Live `/imessage/links` | **404 — not mounted** (stale server) |
| Orchestrator fallback (default python3) | **Broken** (missing deps, silent empty) |
| Orchestrator fallback (inbox venv) | **Works** (5 X links returned) |

**Primary action:** `launchctl kickstart -k gui/$(id -u)/com.inbox.backend`  
**Secondary action:** Fix orchestrator fallback to use inbox venv when HTTP fails.
