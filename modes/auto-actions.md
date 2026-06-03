# Auto-Actions Skill Mode

Autonomous agent operations: archive, draft, schedule, log.

**Entry point:** `/inbox auto-actions`

---

## How It Works

When you run `/inbox auto-actions`, the agent:

1. Fetches unread conversations
2. Scores each 1-5 (by sender, keywords, history)
3. Takes 4 autonomous actions **in parallel**
4. Logs everything to ledger (auditable)
5. Shows summary of what was done

---

## Action 1: Auto-Archive (Fully Autonomous)

**Rule:** Score 1-2 → Archive without asking

**Examples:**
- Newsletter from "The AI Break" → Archive
- Receipt from Uber Eats → Archive
- GitHub "You were assigned to..." → Archive

**Happens:**
```bash
POST /gmail/batch-modify {
  "msg_ids": [thread_ids],
  "remove_label_ids": ["INBOX"],
  "add_label_ids": ["Triage/Archived"]
}
```

**Ledger:**
```
2026-06-03T06:30:00Z  action=auto_archive  count=8  reason=low_signal
```

**Undo:** Move threads back to INBOX from Archived label.

---

## Action 2: Auto-Draft (Approval Required)

**Rule:** Score 4+ human threads → Generate draft reply, show for approval

**Examples:**
- Tierra Hall: "Can you confirm..." → Draft: "Yes, I can confirm"
- Jack (J&J): "Interview scheduling..." → Draft: "Great! I'm available Tue 2pm"

**Shows User:**
```
[Draft] Tierra Hall — "Can you confirm..."

Generated Draft:
"Yes, I can confirm. Looking forward to it."

[✓ Send] [✏ Edit] [✗ Discard]
```

**User chooses:**
- **Send** → Sends reply via `/messages/gmail/reply`
- **Edit** → Modifies draft, sends, agent logs correction
- **Discard** → Skips, agent logs preference (learns not to draft for this sender)

**Ledger:**
```
2026-06-03T06:32:00Z  action=draft_reply  sender=Tierra Hall  status=pending_approval
2026-06-03T06:32:30Z  approval_action=send  draft_id=draft_abc
```

**How Draft Is Generated:**

Claude reads:
- Full thread context (all 3+ messages)
- Your profile (`_profile.md`) for tone/style
- Priority senders and keywords
- Calendar (to avoid commitments without checking)
- Contact history (if you've replied to this person before)

Draft rules:
- **Never repeats yourself** (reads full thread)
- **Never overcommits** (doesn't say "I'll do it by X" without checking calendar)
- **Includes context** (references previous emails if relevant)
- **Matches your style** (short, direct, no pleasantries)

---

## Action 3: Auto-Create Events (Approval Required)

**Rule:** Email mentions dates/times → Create calendar event

**Examples:**
- "Interview Tuesday 2pm at 1 Market St" → Creates event with location
- "Coffee Friday 10am with Tierra" → Creates 1h event
- "Project deadline Monday" → Creates all-day event

**Shows User:**
```
[Event] Interview with Acme Corp
When: Tuesday, June 10 at 2:00 PM - 3:00 PM
Where: 1 Market St, San Francisco, CA
Attendees: acme-recruiter@example.com

[✓ Create] [✏ Edit] [✗ Cancel]
```

**Ledger:**
```
2026-06-03T06:35:00Z  action=create_event  title="Interview with Acme"  date=2026-06-10
```

**Safety Bounds:**
- Only creates if date/time is **explicit** (not "sometime next week")
- **Never double-books** (checks calendar first)
- Defaults to **1 hour** (you can edit)
- **Includes timezone** automatically
- **Auto-adds attendees** from email sender

---

## Action 4: Auto-Log Rejections (Fully Autonomous)

**Rule:** Rejection detected → Log to job tracker sheet

**Examples:**
- "We've decided not to move forward" → Logs as rejection
- "Unfortunately we're going in another direction" → Logs as rejection
- Interview scheduled → Logs as "interviewing"

**Happens:**
```
POST /sheets/{job_tracker_id} {
  "date": "2026-06-03",
  "company": "Acme Corp",
  "role": "Senior Engineer",
  "status": "rejected",
  "notes": "Not moving forward after phone screen"
}
```

**Ledger:**
```
2026-06-03T06:38:00Z  action=log_rejection  company="Acme Corp"  status=rejected
```

**Why Autonomous (no approval):**
- Rejections are **facts**, not actions
- You can **always edit the sheet** if wrong
- Job tracking is **low-risk** (easy to fix)
- Logs everything **for learning**

---

## Full Run Example

```
$ /inbox auto-actions

Fetching unread threads...
Scoring 47 threads...

[✓] Archived 8 low-signal emails
  - Newsletter "The AI Break" #1, #2
  - GitHub notifications (5 threads)
  - Uber receipt
  
[⏳] Drafted 3 replies (pending your approval)
  1. Tierra Hall — "Can you confirm..."
     Draft: "Yes, I can confirm. Available Tuesday 2pm."
     [✓ Send] [✏ Edit] [✗ Discard]
  
  2. Jack (J&J) — "Interview scheduling"
     Draft: "Great! I'm available Thursday or Friday afternoon."
     [✓ Send] [✏ Edit] [✗ Discard]
  
  3. Hiring Manager ABC — "Next steps"
     Draft: "Thank you for the update. What should I prepare?"
     [✓ Send] [✏ Edit] [✗ Discard]

[✓] Created 2 calendar events
  - Interview with Acme Corp (Tue 2pm)
  - Project deadline (Mon EOD)
  
[✓] Logged 1 rejection
  - Company X rejected (Senior Engineer role)

---

Next: Review 3 drafts and approve to send.
```

---

## Scheduling

Auto-actions runs **every 30 minutes** (configurable):

```bash
# Option 1: Via cron (background)
*/30 * * * * /inbox auto-actions >/dev/null 2>&1

# Option 2: Manual
/inbox auto-actions

# Option 3: Check what's pending
/inbox auto-actions --approval-only
```

---

## Configuration

File: `~/.inbox/auto-actions.yml`

```yaml
auto_actions:
  enabled: true
  run_interval: 30min
  
  archive:
    enabled: true
    min_score: 1
    max_score: 2
    exclude_senders: []  # Never auto-archive from these
  
  draft:
    enabled: true
    min_score: 4
    require_approval: true
    model: claude
    temperature: 0.7
  
  calendar:
    enabled: true
    default_duration: 1h
    include_location: true
    auto_add_attendees: true
    exclude_keywords: ["deadline", "reminder"]  # Don't create all-day
  
  logging:
    enabled: true
    auto_log_rejections: true
    auto_log_interviews: true
```

---

## Ledger

Every action is logged to `~/.inbox/ledger`:

```bash
$ tail -20 ~/.inbox/ledger

2026-06-03T06:30:00Z  action=auto_archive    count=8
2026-06-03T06:32:30Z  action=draft_reply     count=3     status=pending_approval
2026-06-03T06:32:45Z  approval=send          draft_id=draft_abc
2026-06-03T06:35:00Z  action=create_event    count=2
2026-06-03T06:38:00Z  action=log_rejection   count=1
2026-06-03T06:39:00Z  summary_complete       total_actions=14
```

Query examples:
```bash
# See all auto-archives
grep "action=auto_archive" ~/.inbox/ledger

# See pending approvals
grep "status=pending_approval" ~/.inbox/ledger

# See rejections logged
grep "action=log_rejection" ~/.inbox/ledger

# Timeline of one day
grep "^2026-06-03" ~/.inbox/ledger
```

---

## Safety Guarantees

1. **Auto-archive** is fully autonomous (low-risk, reversible)
2. **Auto-draft** shows you before sending (approval required)
3. **Auto-schedule** shows you before creating (approval required)
4. **Auto-log** is autonomous (facts, not actions, easy to edit)

**Every action is:**
- Logged in ledger (full audit trail)
- Reversible (just undo in Gmail/Calendar/Sheet)
- Bounded (only 4 safe actions, no destructive ops)

---

## Approval Flow

For drafts and calendar events:

```
1. Agent generates + shows preview
2. User sees: [✓ Approve] [✏ Edit] [✗ Skip]
3. If approve → sends/creates immediately
4. If edit → user modifies, then confirms
5. If skip → agent logs preference (learns)
```

Edits are treated as corrections — agent logs them and may improve over time.

---

## Learning Integration

When you edit or reject a draft, agent logs:
```json
{
  "timestamp": "2026-06-03T06:33:00Z",
  "type": "correction",
  "action": "draft_reply",
  "original_draft": "...",
  "user_version": "...",
  "sender": "Tierra Hall",
  "reason": "user_feedback"
}
```

After 3+ corrections on the same sender, agent suggests:
```
[Learning] You've corrected 3 drafts from "Tierra Hall".
Should I learn to draft differently for her? (yes/no)
```

You approve → config updates automatically.

---

## What Agents Get Wrong (And How to Fix)

| Issue | How to Fix |
|-------|-----------|
| Draft is too formal | Edit it (agent learns your tone) |
| Draft repeats previous email | Edit to reference past (agent learns context) |
| Creates event at wrong time | Edit the time (agent learns date parsing) |
| Archives something it shouldn't | Move it back to INBOX (agent learns) |
| Logs wrong company name | Edit the sheet (agent learns to parse better) |

**No penalties for corrections.** They're how the agent learns.

---

## Audit Trail

See what agent did:
```bash
/inbox ledger --tail 50
/inbox ledger --grep "draft_reply"
/inbox ledger --date 2026-06-03
```

See what you corrected:
```bash
/inbox corrections
/inbox corrections --sender "Tierra Hall"
```

See what agent learned:
```bash
/inbox learning
/inbox learning --since 2026-06-01
```

---

## Troubleshooting

**"ERROR: Server not responding"**
```bash
/inbox health
# If server down: restart inbox_server.py
```

**"Permission denied on calendar"**
```bash
source ~/.config/inbox/server.env
# Verify GOOGLE_CALENDAR_TOKEN is set
/inbox health
```

**"Auto-actions not running"**
```bash
# Check if scheduled
crontab -l | grep auto-actions

# Check logs
grep "auto_action" ~/.inbox/ledger

# Run manually
/inbox auto-actions --dry-run
```

**"Draft is wrong, how do I teach it?"**
Just edit it. Agent logs the correction and learns.

---

## Metrics (After 1 Week)

Expected improvements:
- ✅ 50% of emails archived automatically (saves time)
- ✅ 30% of replies drafted (saves 10 min/day)
- ✅ 100% of interview scheduling handled
- ✅ 0 rejections missed (all logged)

**Time saved:** ~30 min/day  
**Trust built:** Agent makes safe, reversible decisions

