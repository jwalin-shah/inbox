# Mode: triage

Score and prioritize inbox threads. Output a ranked table + write `batch/triage-output.tsv` for downstream batch ops. Route rejections to "log" action + flag interviews for immediate attention.

## Workflow

### 1. Fetch Threads

```
GET /conversations?source=all&limit=50
```

If `config/priorities.yml` exists, load it now — priority senders/keywords/rejection_keywords used in scoring.

### 2. Score Each Thread

For each conversation, assign:

**Urgency (1–5):**
- 5 — human sender, unread, last message > 48h ago (stale needs-reply)
- 4 — human sender, unread, last message < 48h
- 3 — human sender, read, last message this week
- 2 — automated (receipts, notifications, confirmations)
- 1 — newsletters, marketing, noreply

Boost +1 if sender is in `config/priorities.yml` priority_senders.
Boost +1 if snippet matches a priority_keyword.
Cap at 5.

**Special: Job Search Routing**

If snippet matches rejection_keywords (from priorities.yml):
- Action: `log` (not `archive` — user wants to track rejections)
- Flag: 🔴 REJECTION
- Still has urgency score, but different handling

If snippet contains interview keywords (phone screen, onsite, system design, take home):
- Action: `reply` (immediate attention needed)
- Flag: 🟢 INTERVIEW — boost urgency to 5
- These bypass normal scoring

**Action:**
- `reply` — human thread, you haven't replied yet (includes interviews)
- `log` — job rejections to track
- `track` — waiting on someone else, or FYI
- `archive` — automated, no action needed
- `ignore` — newsletter, promotional, bulk

**Category:** one of: `human` | `automated` | `newsletter` | `notification` | `receipt` | `job-rejection` | `job-interview`

### 3. If 20+ Threads

Split into chunks of 15. Process each chunk, then merge results sorted by urgency desc.

### 4. Write TSV

Write `batch/triage-output.tsv`:
```
thread_id\tsource\tscore\tcategory\taction\tname\tsnippet\tlast_ts\tflags
```

Added column: `flags` (e.g., "REJECTION", "INTERVIEW", or empty)

Create `batch/` dir if it doesn't exist.

### 5. Display Table

```
## Triage — {N} threads scored

| Flag      | Score | Action  | Name           | Snippet                    | Age    |
|-----------|-------|---------|----------------|----------------------------|--------|
| 🟢 INTVW  | 5     | reply   | Tierra Hall    | Re: onsite details...      | 1d ago |
| 🔴 REJECT | 4     | log     | Hiring Mgr XYZ | Re: decision...            | 2d ago |
| (empty)   | 5     | reply   | Jack (J&J)     | Re: availability confirm...|3d ago |
...
```

Show score 4-5 first, then 3, then summarize 1-2 as counts only.

**After table:**
```
Wrote batch/triage-output.tsv — {N} threads total
  • {X} need reply (including {Y} interviews)
  • {Z} job rejections to log
  • {W} waiting on others
  
Next steps:
  1. Review interviews: /inbox followup (highest priority)
  2. Log rejections: move rows with action=log to separate tracker
  3. Archive low-signal: /inbox batch (after promoting rows to archive-input.tsv)
```

---

## Job Search Tracking

**Rejections (action=log):**
- User should manually log to job tracker when they see these
- Future enhancement: auto-log to Google Sheets tracker

**Interviews (action=reply, flagged 🟢):**
- Auto-boost to score 5 regardless of age
- Appear first in followup-sweep
- User should prioritize these immediately

**Applications (action=track or reply):**
- Tracked via priority_senders (recruiters/hiring managers)
- Scored normally by urgency
