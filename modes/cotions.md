# Mode: cotions — Email to Career-Ops Status Bridge

Detect application-related emails and sync status changes into the
career-ops tracker. Designed to run standalone or chained from triage.

## Input

Recent emails (received or sent), typically from inbox's Gmail
connector via:
```
GET /conversations?source=gmail&limit=50
```

## Triggers

| Email type | Signal | Career-ops status |
|------------|--------|-------------------|
| Application confirmation | Auto-reply with "application received", "thank you for applying", "we've received your submission" | `Applied` |
| Recruiter outreach | Human-written reply from recruiter asking for availability, phone screen | `Responded` |
| Phone screen scheduled | Calendar invite or confirmation email with interview time | `Phone Screen` |
| On-site / technical scheduled | Interview confirmation, coding challenge link, system design invite | `On-site` |
| Rejection | "unfortunately", "not moving forward", "other candidates", "at this time" | `Rejected` |
| Offer | "pleased to offer", offer letter, comp details | `Offer` |

## Workflow

### 1. Fetch recent emails

Scan last 7 days of email (both inbox and sent). Filter to domains
matching companies in the career-ops tracker.

### 2. Extract company + role

From sender domain, subject line, and email body:
- Company: normalize domain → company name (match against career-ops data/applications.md)
- Role: extract from subject (typical format: "Your application for {Role} at {Company}")

### 3. Classify status change

Apply trigger rules above in priority order. A rejection email that
also mentions a role title → rejection for that role. An interview
scheduling email → phone screen or on-site depending on wording.

### 4. Idempotency check

Before writing a status change:
- Check if the same company + role already has this status or a more
  advanced status in data/applications.md
- Do NOT downgrade: if status is already "Offer", don't overwrite with
  "Rejected" from an old email
- Do NOT duplicate: if status is already "Phone Screen", skip another
  "Phone Screen" from a reminder email

### 5. Output format

Emit one line per status change, in career-ops tracker format:
```
[YYYY-MM-DD] | {Company} | {Role} | {New Status} | cotions
```

Also update the in-memory status so triage can display it inline.

### 6. Integration with triage

When `/inbox triage` runs:
- After triage processes each email, check cotions triggers
- If a match is found, append the status change to data/applications.md
  as a tracked event
- Report in triage output: `"✓ cotions: {Company} {Role} → {Status}"`

## Example

```
## cotions — Email Status Sync

Changes:
  ✓ Anthropic — Forward Deployed Engineer → Phone Screen (recruiter reply)
  ✓ Chroma — Product Engineer → Rejected (auto-reply)
  
No change:
  • Cohere — AI Systems Engineer — already at On-site (newer status)
  • VerAI — Founding Engineer — already at Rejected (terminal)

3 companies matched, 2 status changes, 1 skipped (duplicate/newer exists)
```

## Non-goals

- Does NOT send emails — read-only on the inbox side
- Does NOT apply to jobs — discovery only
- Does NOT create new career-ops tracker entries — only updates status
  on existing entries matched by company + role
