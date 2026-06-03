# Mode: drive-changes (NEW)

Scan Google Drive for recent changes. Good for "what did I miss in my documents?"

## Workflow

### 1. Get Drive Changes

```bash
GET /drive/files?q=modifiedTime>="2026-06-02T00:00:00Z"&pageSize=20
```

Sort by modifiedTime desc.

### 2. Filter to Important Folders

Only show changes in:
- `~/control-surface/` (workspace command)
- `~/job-applications/` (job docs)
- `~/personal/` (personal projects)
- Root-level files (important files live here)

### 3. For Each File

Show:
- File name
- Who modified it (owner email)
- Last modified time
- File type (doc, sheet, pdf, etc.)

### 4. Output

```
## Drive Changes — Last 24 hours

### Shared with me
  • Job Tracker (Google Sheet) — Jwalin Shah — 2h ago
  
### My files
  • control-surface/WIP-improvements.md — You — 3h ago
  • personal/goals-2026.md — You — 1d ago

### Awaiting review
  (files shared by others, not modified by you yet)
```

---

## Integration with "What Did I Miss"

`/inbox what-did-i-miss` includes:
- Recent Gmail (2h)
- Recent iMessage (2h)
- Recent GitHub (notifications only)
- Recent Drive changes (24h)

Shows in this order: urgent items first, then informational.

---

## Notes

- Shows **shared with me** first (might need action)
- Then **my files** (in case you forgot what you're working on)
- Skips archived/trashed files automatically
