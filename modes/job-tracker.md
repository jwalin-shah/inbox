# Mode: job-tracker (NEW)

Log rejections + offers automatically to a Google Sheet.

## Workflow

### 1. Prerequisites

Google Sheet ID: `JWALIN_JOB_TRACKER_SHEET_ID` (set in env or config)

Sheet columns:
- Date
- Company
- Role
- Status (applied, phone screen, onsite, offer, rejected)
- Notes

### 2. Scan Recent Emails

```
GET /conversations?source=gmail&limit=50
```

Filter to: received in last 24h + contains rejection_keywords OR interview keywords

### 3. For Each Match

Extract:
- Company (from sender name or email domain)
- Role (from subject/snippet)
- Status (rejection | interview | offer)
- Date received

### 4. Check if Already Logged

Query Google Sheet: "Did we already log Company + Role?"

If yes, skip. If no, add row.

### 5. Auto-Log to Sheet

```bash
POST /sheets/{sheet_id}/values/append {
  "range": "Sheet1!A:F",
  "values": [
    [date, company, role, status, notes]
  ]
}
```

### 6. Output

```
## Job Tracker Auto-Log

Added:
  ✓ Waymo — Senior Engineer (rejected) — 6/2/2026
  ✓ YC Company — Founding Engineer (interview) — 6/2/2026
  
Already logged:
  • Anthropic — Staff Engineer — 5/31/2026

Total applications tracked: 932
  • Rejected: 237
  • Interviewing: 12
  • Offers: 1
```

---

## Auto-Update in Triage

When `/inbox triage` detects a rejection or interview:
- Triage mode calls `/modes/job-tracker-mode`
- Auto-logs to sheet
- Returns count of newly logged items
- Triage shows "✓ Logged to job tracker" in output

---

## Manual Update

User can also run manually:
```
/inbox job-tracker
```

To manually edit sheet and sync back to local view.

---

## Integration

- Rejections auto-route to `action=log` in triage (not archive)
- Interviews auto-boost to score 5
- Every triage run also syncs to job tracker sheet
