# Mode: followup-sweep

Find threads where you owe a reply or are waiting on someone. For reply-owed threads, draft an opener with full context.

## Workflow

### 1. Load Triage Output

Check `batch/triage-output.tsv`:
- If exists and modified within 6 hours: use it
- Otherwise: run triage inline (fetch conversations + score, do not write TSV)

### 2. Partition

From scored threads:

**Needs reply (action=reply, score ≥3):**
For each: fetch **full thread** (not just last 3 messages) to understand context.
```
GET /messages/{source}/{conv_id}?thread_id={thread_id}
```

Check: is the last message from you? If yes, reclassify as `track`.

**Waiting on (action=track, score ≥3):**
Threads where you sent last and no response yet. Note age.

### 3. Enrich Context

For each needs-reply thread, gather:
- **Full message history** (all messages in thread, not just last 3)
- **Sender info:** 
  - Is this sender in your contacts? (priority senders list)
  - Have you corresponded before? (check conversation count)
- **Thread summary:** Read ALL messages to understand full context, not just last message

### 4. Draft Reply Starters

For each confirmed needs-reply thread (max 5):
- Read **full thread** to understand complete context
- Consider message history (are you repeating something already said?)
- Draft a 1-sentence reply opener that fits the context
- Include context note: `[Based on full thread context: {brief summary}]`

Example:
```
Thread: "Can you confirm availability?"
Full context: User asked about availability 3 days ago, you said pending, they followed up
Draft: "Thanks for the follow-up — I can confirm Tuesday 2pm works."
```

### 5. Prioritize by Urgency

Sort needs-reply threads by:
1. Age (oldest first — you're overdue)
2. Sender priority (priority_senders list boost)
3. Thread length (longer threads = more investment, prioritize those)

### 6. Output

```
## Followup Sweep — {date}

### Needs Reply ({N})
| Name           | Age    | Context Summary                    | Draft opener                        |
|----------------|--------|-----------------------------------|-------------------------------------|
| Tierra Hall    | 3d ago | Asked confirm availability, you... | "Thanks for the follow-up — I can..." |
| Jack (J&J)     | 1d ago | Interview scheduling for...       | "Yes, I'm available for phone..." |

### Waiting On ({N})
| Name        | Sent              | Age    | Context                           |
|-------------|-------------------|--------|-----------------------------------|
| Adam Chan   | "Let me know if..." | 5d ago | Sent your portfolio, waiting feedback |

### All Clear
{list any remaining threads where action is needed but score < 3, as a compact list}
```

If no needs-reply threads: say "Inbox clear — no threads waiting on your reply."

---

## Context Improvement Notes

- **Old behavior:** Draft from last 3 messages only → might repeat yourself or miss nuance
- **New behavior:** Read full thread → understand entire conversation arc → draft smarter openers
- **Validation:** If draft seems generic or contextless, likely thread was long; agent should have caught it
