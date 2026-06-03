# Health Check Workflow

Check server, tokens, and inbox state. Report ✓/✗ per check.

---

## 1. Server Health

```
curl -sf http://localhost:9849/health
```

**If fails:** Server is down.
- **Fix:** `cd /Users/jwalinshah/projects/inbox && uv run python inbox_server.py`

**If succeeds:** Continue to next check.

---

## 2. Gmail Accounts

```
curl -s -H "Authorization: Bearer ${INBOX_SERVER_TOKEN}" \
  http://localhost:9849/accounts
```

**Check:** Response includes all 3 accounts:
- jwalinshah13@gmail.com (primary)
- jshah1331@gmail.com
- jwalinsshah@gmail.com

**If missing:** One or more accounts not authenticated.
- **Fix:** In Inbox TUI, press `Ctrl+Shift+A` to re-auth the missing account

---

## 3. Token Validity

```
curl -s -H "Authorization: Bearer ${INBOX_SERVER_TOKEN}" \
  -H "Content-Type: application/json" \
  http://localhost:9849/gmail/labels
```

**Check:** Returns non-empty list of labels

**If fails (401 Unauthorized):** Token is invalid.
- **Fix:** Check `~/.config/inbox/server.env` for INBOX_SERVER_TOKEN and ensure it matches server's token (check server logs or restart server to regenerate)

---

## 4. Triage State

```
test -f ~/batch/triage-output.tsv && \
  find ~/batch/triage-output.tsv -mmin -240 >/dev/null 2>&1 && \
  echo "✓ Triage output fresh (< 4 hours)" || \
  echo "⚠ Triage output stale or missing"
```

**If stale/missing:** Run `/inbox triage` to generate fresh conversation scores.

---

## 5. Summary

```
echo "=== Inbox Health ==="
echo "✓ Server running"
echo "✓ 3 accounts authed"
echo "✓ Tokens valid"
echo "✓ Triage fresh"
echo ""
echo "Status: All clear. Ready for /inbox morning-brief or /inbox triage"
```

If any check failed, show:
```
⚠ Issues found:
  - [specific failure + fix command]
```

---

## Exit Criteria

If all checks pass: "Ready for work. Next: /inbox morning-brief or /inbox triage"
If any check fails: Show fix commands, suggest which to run first
