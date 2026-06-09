# Multi-Gmail/Data Connect Readiness Workpack

Date: 2026-06-04
Repo: `/Users/jwalinshah/projects/inbox`

## Outcome

Use Inbox native Google OAuth/API support as the primary path for three Gmail accounts. `gog` is fallback only if the native checks below cannot load/read/search by account.

The native path already supports:

- Account representation: `services.google_auth_all()` loads token files from `tokens/*.json` and keys Gmail services by `users().getProfile(userId="me").emailAddress`.
- Sync/read attribution: `message_sync.py` stores Gmail index rows as `(source="gmail", account=<email>, external_id=<message_id>)`.
- Search attribution: `services.gmail_search(service, account_email=...)` returns `Contact(..., gmail_account=account_email)`.
- Raw pointer attribution: indexed Gmail messages use `raw_pointer="gmail:<account>:<message_id>"`.
- Data Connect scope matrix: `services.google_auth_diagnostics()` now exposes Gmail, Calendar, Drive, Sheets, Docs, Contacts, and Tasks readiness metadata without token values.

## Native OAuth/Data Connect Coverage

| Product | Native surface | Required scope | Readiness |
| --- | --- | --- | --- |
| Gmail | `gmail:v1` | `gmail.readonly`, `gmail.modify`, `gmail.send`, `gmail.settings.basic` | Loaded service required |
| Calendar | `calendar:v3` | `calendar` | Loaded service required |
| Drive | `drive:v3` | `drive` | Loaded service required |
| Sheets | `sheets:v4` | `spreadsheets` | Loaded service required |
| Docs | `docs:v1` | `documents` | Loaded service required |
| Contacts | `people:v1` | `contacts.readonly` | OAuth scope reserved; People API wrapper still future work |
| Tasks | `tasks:v1` | `tasks` | Loaded service required |

## Stop Checklist

Target accounts:

- `jshah1331@gmail.com`
- `jwalinshah13@gmail.com`
- `jwalinsshah@gmail.com`

Current redacted account-metadata result:

- `tokens_present=3`
- `email_hints=["jshah1331@gmail.com", "jwalinshah13@gmail.com", "jwalinsshah@gmail.com"]`
- `missing_scope_counts=1` for all three accounts
- Remediation: reauth all three accounts once to grant the newly added `contacts.readonly` scope.

For each account:

- `tokens/<account>.json` exists locally and is never printed.
- `/accounts/auth-status` shows `email_hint=<account>`, `has_refresh_token=true`, no missing Gmail scopes, and no token values.
- `/status/providers` shows the account under `google_gmail`.
- `message_sync.py --smoke` passes without touching auth or data stores.
- The safe sync plan command is known before any live sync.
- The safe search command is account-filtered and read-only.
- If Contacts is needed now, reauth is required because `contacts.readonly` was added to `GOOGLE_SCOPES`.

## Safe Validation Commands

These commands are dry-run/account metadata only unless explicitly marked as live read. They do not send, delete, label, archive, star, or mark messages.

Do not set `INBOX_TEST_MODE=1` for real token metadata or Gmail sync/search checks; test mode redirects token lookup to the isolated test data directory.

Auth metadata, no refresh:

```bash
uv run python - <<'PY'
from services import google_auth_diagnostics
d = google_auth_diagnostics(check_refresh=False)
print({
    "tokens_present": d["counts"]["tokens_present"],
    "email_hints": [t["email_hint"] for t in d["tokens"]],
    "missing_scope_counts": {t["email_hint"]: len(t["missing_scopes"]) for t in d["tokens"]},
    "data_connect_products": sorted(d["data_connect"].keys()),
})
PY
```

Server metadata, if the Inbox server is running:

```bash
curl -sS http://127.0.0.1:9849/accounts/auth-status | jq '{counts, tokens: [.tokens[] | {email_hint, has_refresh_token, missing_scopes, reason}]}'
curl -sS http://127.0.0.1:9849/status/providers | jq '.providers[] | select(.provider | startswith("google_")) | {provider, accounts, readable, syncable, blockers}'
```

CLI smoke, no auth/data access:

```bash
INBOX_TEST_MODE=1 uv run python message_sync.py --smoke
```

Safe per-account sync plan, no execution:

```bash
uv run python - <<'PY'
from pathlib import Path
from message_index_store import MessageIndexStore
store = MessageIndexStore(Path("data/multi_gmail_readiness.sqlite3"))
for account in ["jshah1331@gmail.com", "jwalinshah13@gmail.com", "jwalinsshah@gmail.com"]:
    state = store.get_sync_state("gmail", account) or {}
    print({"account": account, "existing_state": state, "safe_next": "uv run python message_sync.py incremental --db data/multi_gmail_readiness.sqlite3"})
PY
```

Live read-only sync command, run only after auth metadata is clean:

```bash
uv run python message_sync.py incremental --db data/multi_gmail_readiness.sqlite3
```

Safe per-account search commands, live read-only:

```bash
curl -sS 'http://127.0.0.1:9849/search?q=from%3Ame&sources=gmail&limit=5&account=jshah1331%40gmail.com' | jq '.results[] | {source, account, gmail_account, thread_id, id}'
curl -sS 'http://127.0.0.1:9849/search?q=from%3Ame&sources=gmail&limit=5&account=jwalinshah13%40gmail.com' | jq '.results[] | {source, account, gmail_account, thread_id, id}'
curl -sS 'http://127.0.0.1:9849/search?q=from%3Ame&sources=gmail&limit=5&account=jwalinsshah%40gmail.com' | jq '.results[] | {source, account, gmail_account, thread_id, id}'
```

Index attribution proof after sync:

```bash
sqlite3 data/multi_gmail_readiness.sqlite3 "
SELECT account, COUNT(*) AS messages
FROM items
WHERE source='gmail'
GROUP BY account
ORDER BY account;"
```

## Remediation

If an account is missing:

1. Confirm `credentials.json` is present and is the intended OAuth client.
2. With explicit approval for an OAuth browser flow, run:

```bash
uv run python - <<'PY'
from services import add_google_account
print(add_google_account())
PY
```

3. Re-run auth metadata and confirm the account appears.

If scopes are missing:

1. Reauth that account with `/accounts/reauth` or `services.reauth_google_account("<account>")`.
2. Expect Contacts to require reauth because `contacts.readonly` was added for future People API/Data Connect coverage.
3. Re-run `/accounts/auth-status` and verify `missing_scopes=[]`.

If sync/search attribution fails:

1. Confirm `/status/providers` lists the account under `google_gmail`.
2. Confirm `message_sync.py --smoke` passes.
3. Run the account-filtered search command and verify returned objects include the same account in `account`/`gmail_account` metadata.
4. Use `gog` only if native `google_auth_all()`, `gmail_search()`, or `message_sync.py` cannot load/read/search an otherwise valid account.

## Fallback Boundary

`gog` remains a fallback connector. It should not be used for this readiness proof unless one of these native blockers is confirmed:

- Google OAuth token exists but `google_auth_all()` cannot load the Gmail service for that account.
- Gmail API read/search fails for an account with clean required scopes.
- Native index sync cannot preserve account attribution in `items.account`.

Fallback discovery only:

```bash
command -v gog
gog auth status --json
gog sync --dry-run --json
```

Do not use fallback commands for sends, deletes, labels, or live mutations.
