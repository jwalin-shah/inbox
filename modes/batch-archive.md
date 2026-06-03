# Mode: batch-archive

Bulk archive threads from `batch/archive-input.tsv`. Requires explicit user approval before executing.

## Workflow

### 1. Check Prerequisites

```
test -f ~/batch/archive-input.tsv || exit 1 "No ~/batch/archive-input.tsv found. Run /inbox triage first."
test -f ~/batch/triage-output.tsv || exit 1 "No ~/batch/triage-output.tsv found. Run /inbox triage first."
```

### 2. Load Archive Input

```
cat ~/batch/archive-input.tsv
```

Format (TSV from triage output):
```
thread_id\tsource\tscore\tcategory\taction\tname\tsnippet\tlast_ts
```

Count rows. Example output:
```
Loaded 12 threads from ~/batch/archive-input.tsv
```

### 3. Dry-Run Confirmation

Show what will be archived:

```
## Archive Confirmation

About to archive 12 threads:

| Name           | Snippet                    | Score | Source |
|----------------|----------------------------|-------|--------|
| Newsletter Bot | "Your weekly digest..."    | 1     | gmail  |
| EVgo           | "$5 off fast charging"     | 1     | gmail  |
...

**Action:** Remove from inbox, add label "Triage/Archived"
**Reversible:** Yes (files move to All Mail, can be restored)

**Confirm:** Type "yes I approve archiving 12 threads" to proceed.
```

### 4. Wait for Explicit Approval

User must type exact phrase: `"yes I approve archiving {N} threads"` (where {N} is the count)

If user does NOT confirm exactly:
```
❌ Confirmation phrase did not match. No threads archived. Try again or run /inbox batch to refresh.
```

### 5. Execute Archive

For each row in archive-input.tsv:
```
POST /gmail/batch-modify {
  "msg_ids": [thread_id],
  "remove_label_ids": ["INBOX"],
  "add_label_ids": ["Label_29"],  # Triage/Archived
  "account": <account from triage output>
}
```

Show progress:
```
Archiving... ✓ 1/12 ✓ 2/12 ✓ 3/12 ...
```

### 6. Update State File

Write `batch/archive-state.tsv`:
```
timestamp\tstatus\tarchived_count\tfailed_count\tnext_thread_id
2026-06-03T06:15:00Z\tcomplete\t12\t0\t(null)
```

This allows resumable re-runs if interrupted.

### 7. Cleanup and Report

```
✓ Archived 12 threads
✓ State saved to ~/batch/archive-state.tsv

Next: Run /inbox morning-brief to see updated inbox.
```

If any failed:
```
⚠ Archived 11/12 threads (1 failed)
  Failed: thread_id_xyz (reason: already archived or deleted)
  
Tip: Fix the failed row in ~/batch/archive-input.tsv and run /inbox batch again.
```

---

## Resumable State

If interrupted (user kills process), next run detects `batch/archive-state.tsv`:
```
- If last run was incomplete, resume from next_thread_id
- Confirm again before re-executing (don't assume approval carries over)
```

---

## Exit Criteria

✓ All threads archived OR
⚠ User denies confirmation (no threads archived) OR
✗ Network error (partial archive + state saved for resume)
