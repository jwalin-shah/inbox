# Google Auth Runbook

Inbox stores per-account OAuth tokens in `tokens/*.json`. If Gmail or Calendar
comes back empty while token files exist, check whether Google rejected the
refresh tokens.

## Diagnose

Start with the local helper:

```bash
cd ~/projects/inbox
scripts/restore_google_oauth.sh
```

If it reports that `credentials.json` is missing, restore the Google OAuth
client secret first. The helper does not print secrets.

Run the read-only diagnostic:

```bash
uv run python - <<'PY'
from services import google_auth_diagnostics
status = google_auth_diagnostics(check_refresh=True)
print(status["counts"])
print(status["likely_causes"])
for token in status["tokens"]:
    print(token["email_hint"], token["refresh_status"], token["reason"])
PY
```

Or, after the Inbox server has been restarted with this code:

```bash
curl -H "Authorization: Bearer $INBOX_SERVER_TOKEN" \
  "http://127.0.0.1:9849/accounts/auth-status?check_refresh=true"
```

The endpoint is redacted: it reports token filenames, scopes, expiry, and
refresh status, but not access tokens, refresh tokens, or user message data.

To prove multi-Gmail readiness without mutations after reauth/restart:

```bash
curl -s -X POST http://127.0.0.1:9849/gateway/gmail-readiness \
  -H "Authorization: Bearer $INBOX_SERVER_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"accounts":["jwalinshah13@gmail.com","jshah1331@gmail.com"]}'
```

This reads Gmail profile and inbox/unread count metadata only.

## Common Causes

- `refresh_token_expired_or_revoked`: Google rejected the refresh grant. The
  most common local-development cause is an OAuth consent screen in
  `External` + `Testing` mode.
- `missing_required_scopes`: the token was created before Inbox requested its
  current Gmail/Calendar/Drive/Sheets/Docs/Tasks scopes.
- `missing_refresh_token`: the OAuth flow did not grant offline access.
- `admin_policy_enforced` or `session_control_reauth_required`: Google
  Workspace policy is forcing reauth.

## Durable Personal Setup

Go to Google Cloud Console:

1. Select the project from `credentials.json` (`project_id`).
2. Open **APIs & Services** -> **OAuth consent screen**.
3. Check **Publishing status**.
4. If it is **Testing** and user type is **External**, refresh tokens for broad
   Google API scopes expire after about 7 days.
5. For a personal Inbox app, either publish the app to production or use an
   Internal Workspace app if all accounts are in the same Google Workspace.
6. Keep yourself listed as a test user until the publishing state is changed.
7. Reauthorize each account after the consent-screen change.

## Reauthorize On This Mac

After `credentials.json` is present and the Inbox server is running:

```bash
cd ~/projects/inbox
scripts/restore_google_oauth.sh --start
```

This calls the local `/accounts/add` endpoint, opens the browser OAuth flow, and
stores the resulting per-account token under `tokens/<email>.json`.

Google's documented refresh-token expiration cases include app access revoked,
six months of inactivity, password changes with Gmail scopes, refresh-token
limits, time-based access expiry, admin policy, and External/Testing OAuth
apps issuing 7-day refresh tokens for non-basic scopes.

Reference:
https://developers.google.com/identity/protocols/oauth2#expiration
