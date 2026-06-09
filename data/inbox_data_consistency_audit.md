# Inbox Data Consistency Audit

**Date:** 2026-06-08  
**Queue item:** eaa5f053f0  
**Validator:** QA (read-only)  
**Live target:** `http://127.0.0.1:9849` (launchd `com.inbox.backend`)  
**Machine evidence:** `data/inbox_data_consistency_audit.json`

---

## Verdict: PASS

14/14 consistency checks passed. API layer, `services.py` read paths, and upstream originals (Google APIs, `chat.db`, Reminders SQLite) agree on spot-checked samples. No data drift detected in the audited surfaces.

| Metric | Value |
|--------|-------|
| Checks passed | 14 |
| Warnings | 0 |
| Failures | 0 |
| Gmail accounts | 3 |
| iMessage DB size | 37,281,792 bytes |

---

## Methodology

Read-only spot checks comparing three layers where applicable:

1. **HTTP API** — authenticated requests to the live server (`INBOX_SERVER_TOKEN` from `~/.config/inbox/server.env`, value not logged).
2. **Services layer** — direct `services.py` calls with `init_contacts()` loaded (mirrors server startup).
3. **Original source** — raw SQLite (`~/Library/Messages/chat.db`, Reminders DBs) or Google APIs via `google_auth_all()` tokens.

Spot-check depth: top 5 iMessage threads by recency; top 5 overlapping Gmail message IDs across API vs Google; today's calendar; 10 reminders; 3 AddressBook phone resolutions.

---

## Results by Source

### iMessage (`chat.db`)

| Check | Result | Detail |
|-------|--------|--------|
| DB readable | PASS | `~/Library/Messages/chat.db` present, 37 MB |
| Contacts API ↔ services | PASS | 20/20 overlap, 0 field mismatches (name, unread, snippet) |
| Thread spot-check (5 chats) | PASS | API ↔ services ↔ DB agree on text bodies |

**Spot-check samples (threads with text):**

| Chat | Name | API↔svc | svc↔DB | Last message (truncated) |
|------|------|---------|--------|--------------------------|
| 49 | The Ochos | ✓ | ✓ | "My dad's in town for a day so we might be going out with him" |
| 159 | Soham Shah | ✓ | ✓ | "Going to come visit Fremont on Wednesday are you going to be" |
| 8 | family1 | ✓ | ✓ | "i'll send 2 back" |

**Expected empty threads:** chats `179` (214136) and `3` (Jwalin Shah) contain only attachment/reaction rows with no `_clean_body` text — API, services, and filtered DB query all return empty; not a consistency bug.

### Gmail (Google API)

| Check | Result | Detail |
|-------|--------|--------|
| `/conversations?source=gmail` ↔ `/gmail/conversations` | PASS | 58 threads, identical top-5 ordering |
| API ↔ direct Google API | PASS | 18 overlapping IDs in sample, 0 snippet mismatches |

**Sample top threads (verified identical snippets):**

- `19ea7bbf892b67cd` — Annabel at Encord
- `19ea7a773d103ec7` — Blaze Pizza
- `19ea79aad90f949c` — Astral Codex Ten

### Google Calendar

| Check | Result | Detail |
|-------|--------|--------|
| `GET /calendar/events?date=2026-06-08` ↔ `calendar_events()` | PASS | 1 event, titles match exactly |

### Apple Reminders (SQLite)

| Check | Result | Detail |
|-------|--------|--------|
| `GET /reminders` ↔ `reminders_list()` | PASS | 10/10 ID overlap |

### Apple Notes (SQLite)

| Check | Result | Detail |
|-------|--------|--------|
| `GET /notes` ↔ `notes_list()` | PASS | Both return 0 (empty or no readable notes in sample window) |

### AddressBook (contact resolution)

| Check | Result | Detail |
|-------|--------|--------|
| `ContactBook.resolve()` spot-check | PASS | 3/3 phones resolved to expected names |

| Phone | Resolved name |
|-------|---------------|
| +12144910544 | Veer Mistry |
| +12096277456 | Kevin (deevy) |
| +12137131656 | Xiya Tang |

### Cross-source search

| Check | Result | Detail |
|-------|--------|--------|
| `POST /search` (`meeting`, imessage+gmail) | PASS | 5 results across gmail + imessage |

### Gateway read-proof

| Check | Result | Detail |
|-------|--------|--------|
| `POST /gateway/read-proof` | PASS | gmail ✓, calendar ✓, tasks ✓; 0 blockers |

---

## Known Limitations (not failures)

### Connector CLIs not installed

Per settled decision `50a387c1`, cross-channel reconcile via external CLIs is blocked until installed:

| Connector | Installed | Auth | Sync ready |
|-----------|-----------|------|------------|
| google (gog) | no | not_installed | no |
| imessage (imsg) | no | not_installed | no |
| whatsapp (wacli) | no | not_installed | no |
| discord | no | not_installed | no |
| twitter | no | not_installed | no |
| linkedin | yes | ok | no |

Inbox native read paths (services + API) are consistent; `scripts/reconcile.py` cross-CLI search is not exercised in this audit.

### Gateway health: degraded

`GET /gateway/status` reports `health=degraded` (Google OAuth remediation hints). Read paths still work — confirmed by read-proof and direct comparisons.

### Audit prerequisites

- `services.init_contacts()` must be called before comparing iMessage names in standalone scripts; the live server does this on startup.
- iMessage thread comparison must apply `_clean_body` filtering when reading raw `chat.db` rows.

---

## Commands Run

```bash
# Health
curl -sf http://localhost:9849/health

# Full audit (generates JSON evidence)
cd ~/projects/inbox
set -a && . ~/.config/inbox/server.env && set +a
uv run python3  # inline audit script → data/inbox_data_consistency_audit.json
```

---

## Conclusion

Core inbox data paths are **consistent** across API, services, and originals for iMessage, Gmail, Calendar, Reminders, and AddressBook resolution. No corrective action required for data integrity. Optional follow-ups: install `gog`/`imsg`/`wacli` for cross-channel reconcile CLI coverage; address gateway `degraded` OAuth hints if token refresh warnings persist.
