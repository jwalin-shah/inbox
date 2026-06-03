# Mode: what-did-i-miss (NEW)

Quick scan of all channels. Run every 3-4 hours during work to surface urgent items immediately. Faster than morning-brief, focused on "did something important happen?"

## Workflow

### 1. Time Check

```
hour=$(date +%H)
if (( hour < 9 || hour > 18 )); then
  echo "Outside work hours (9am-6pm). Skipping check."
  exit 0
fi
```

Skip outside work hours (9am-6pm). Can be configured via `TRIAGE_WORK_HOURS` env var.

### 2. Fast Scan (max 30 seconds)

**Gmail unread (last 2 hours only):**
```
GET /conversations?source=gmail&limit=20
```
Filter to: last message in last 120 minutes + unread
Boost priority_senders first.

**iMessage unread:**
```
GET /conversations?source=imessage&limit=10
```
Show only unread. Skip if none.

**GitHub mentions:**
```
GET /github/notifications?all=false
```
Show PR reviews + issues only. Skip if none.

### 3. Classify by Urgency

Quick scoring (not full triage, just "urgent or not?"):
- **🔴 URGENT:** Priority sender + unread, OR contains job keywords (interview, offer, rejection)
- **🟡 IMPORTANT:** Human sender + unread, age < 2h
- **🟢 FYI:** Everything else

### 4. Output (compact)

```
## What Did I Miss? — {time}

🔴 URGENT
  • Tierra Hall: "Can you confirm onsite availability?" (15m ago)
  • Jack (J&J): "Interview scheduled for Tuesday" (45m ago)

🟡 IMPORTANT
  • Friend Name: "Are you free this weekend?" (1h ago)

🟢 FYI
  • 2 GitHub notifications (skipped)

Next: /inbox morning-brief for full brief, or /inbox triage to score all.
```

If nothing: `All clear — no urgent items in last 2 hours.`

### 5. Interruption Handling

If user is in a meeting/focused, this should be non-intrusive:
- Print to stdout only (no popup)
- Can be consumed in background or ignored
- Doesn't interrupt workflow

---

## Configuration

Can be called automatically via cron every 3-4 hours during work:
```
# Every 3 hours, 9am-6pm, weekdays only
0 9,12,15,18 * * 1-5 /inbox what-did-i-miss
```

Or called manually anytime: `/inbox what-did-i-miss`

---

## Design Notes

**Why not just use morning-brief more often?**
- Morning-brief is comprehensive (calendar + reminders + GitHub)
- This is minimal (just new messages + GitHub)
- This runs frequently (every 3-4h)
- Morning-brief runs once (8am)

**Bustamante's pattern:**
"Every few hours, I want to ask 'What did I miss?' and have the agent scan WhatsApp, Telegram, Gmail, SMS, Calendar, and the relevant Drive changes."

This is the minimal Gmail + GitHub version. Scope for future: add WhatsApp, SMS, Drive changes.
