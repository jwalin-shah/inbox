# iMessage Contacts Needing Reply

Generated: 2026-06-05T15:54:25-07:00

Queue item: `48c56767cf`

Read-only surface of iMessage threads where the **last message is not from you**. No messages were sent.

## Validation Evidence

- `curl http://localhost:9849/health`: backend healthy.
- `GET /index/health`: unhealthy (`no_sync_state`); `/index/views/waiting-on-me` returned 0 threads.
- Signal path: `services.imsg_contacts` + `services.imsg_thread` on `~/Library/Messages/chat.db` with AddressBook resolution.
- Excluded: tapbacks, receipts, recruiter spam, verification codes, attachment-only, and automated senders.

## Summary

| Tier | Count | Meaning |
|------|------:|---------|
| **Recent actionable** (≤7d) | **4** | Unread or recent threads worth replying to now |
| Stale named contacts (>7d) | 6 | AddressBook-resolved names you have not replied to |
| Phone / ambiguous | 0 | Unresolved numbers with substantive messages |
| Waiting on others | 22 | You sent the last message |
| Excluded noise | 102 | Tapbacks, automated, spam, empty |

## Recent Actionable — Reply Now

| Urgency | Unread | Age | Contact | Last message | Thread |
|--------:|-------:|-----|---------|--------------|--------|
| 5 | 1 | 11h | +15512060717, +17204963920 | But I appreciate it | `GET /messages/imessage/177` |
| 4 | 1 | 1d | +15109355072 | i think 15% off | `GET /messages/imessage/178` |
| 4 | 1 | 1d | family1 | whole | `GET /messages/imessage/8` |
| 2 | 0 | 1d | +14089089659 | Give the other agent this exact message:    The file is Open | `GET /messages/imessage/46` |

## Stale Named Contacts

| Unread | Age | Contact | Last message |
|-------:|-----|---------|--------------|
| 0 | 345d | The Ochos | Oooopsss how did that happennnn |
| 0 | 341d | 5 SHAHS | thank you thank you |
| 0 | 321d | Rutu and Younger but For Real | Heyyyy! |
| 0 | 297d | Rooftop Pool 8/13 | after all these years and I still can’t understand amion |
| 0 | 286d | quj | 😍😍 |
| 0 | 166d | Rutu and Younger but For Real | Hey! If y’all r back for break we should meet up for lunch o |

## Phone / Ambiguous

| Unread | Age | Contact | Last message |
|-------:|-----|---------|--------------|

## Recommended Next Actions

1. **+15512060717, +17204963920** — 11h, unread=1 (review thread first): `GET /messages/imessage/177`
2. **+15109355072** — 1d, unread=1 (review thread first): `GET /messages/imessage/178`
3. **family1** — 1d, unread=1 (named contact): `GET /messages/imessage/8`
4. **+14089089659** — 1d, unread=0 (review thread first): `GET /messages/imessage/46`

Machine-readable: `data/imessage_needs_reply.json`

## Stop Condition

Read-only evidence only. Replying requires explicit approval via TUI or `POST /messages/send`.
