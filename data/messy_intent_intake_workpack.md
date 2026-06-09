# iMessage Contacts Needing Reply (2+ Weeks Silent)

Generated: 2026-06-05T16:19:08

Queue item: `190d857e35`

Read-only surface of iMessage threads where **the last message is not from you** and **last activity is ≥14 days ago**. No messages were sent.

## Validation Evidence

- `curl http://localhost:9849/health`: ok
- `GET /index/health`: healthy=False stale=True
- `uv run pytest tests/test_services.py -k imsg_contacts -q --no-cov`: 1 passed
- Signal path: `services.imsg_contacts` + `services.imsg_thread` on `~/Library/Messages/chat.db` with AddressBook resolution.
- Named tier: chats with explicit `display_name` in Messages DB (group labels / saved thread names).
- Excluded: tapbacks, receipts, recruiter spam, verification codes, attachment-only, and automated senders.

## Summary

| Tier | Count | Meaning |
|------|------:|---------|
| **Stale named (≥14d)** | **6** | Custom thread name; they messaged last, silent 2+ weeks |
| Stale phone / ambiguous (≥14d) | 60 | Unresolved numbers with substantive messages |
| Recent actionable (≤7d) | 5 | Needs reply but within last week (out of 2-week scope) |
| Waiting on others | 22 | You sent the last message |
| Excluded noise | 77 | Tapbacks, automated, spam, empty |

## Stale Named Contacts — Need Reply, 2+ Weeks Silent

| Unread | Age | Contact | Last message | Last timestamp | Thread |
|-------:|-----|---------|--------------|----------------|--------|
| 0 | 344d | The Ochos | Oooopsss how did that happennnn | 2025-06-25T20:36:11 | `GET /messages/imessage/49` |
| 0 | 340d | 5 SHAHS | thank you thank you | 2025-06-29T21:10:41 | `GET /messages/imessage/40` |
| 0 | 320d | Rutu and Younger but For Real | Heyyyy! | 2025-07-19T21:05:23 | `GET /messages/imessage/19` |
| 0 | 297d | Rooftop Pool 8/13 | after all these years and I still can’t understand amion | 2025-08-12T16:10:21 | `GET /messages/imessage/81` |
| 0 | 286d | quj | 😍😍 | 2025-08-23T16:06:32 | `GET /messages/imessage/127` |
| 0 | 166d | Rutu and Younger but For Real | Hey! If y’all r back for break we should meet up for lunch o | 2025-12-21T15:27:15 | `GET /messages/imessage/162` |

## Stale Phone / Ambiguous (sample top 10)

| Unread | Age | Contact | Last message | Last timestamp |
|-------:|-----|---------|--------------|----------------|
| 0 | 1053d | +16503913948, Mihir Shah | 8:30 | 2023-07-17T16:34:44 |
| 0 | 352d | +14086368367 | Where r u going | 2025-06-18T08:36:44 |
| 0 | 350d | +18883566618 | Your appointment with Mariela Costello on Friday, June 20th  | 2025-06-20T10:51:24 |
| 0 | 339d | +15104587112 | Been a minute | 2025-07-01T13:03:27 |
| 0 | 338d | +13134829042 | Please confirm a time that works best for TODAY and I will s | 2025-07-02T07:20:16 |
| 0 | 337d | +14082146368 | Hello, you have a visit with Crossover San Tomas (Santa Clar | 2025-07-02T20:28:27 |
| 0 | 332d | +15105797012 | Ya lmk what the referral thing looks like | 2025-07-07T23:20:25 |
| 0 | 331d | Krusha Shah, Soham Shah | Whoops, forgot to look, I’ll check | 2025-07-09T09:19:40 |
| 0 | 330d | +18335070438 | Hi Jwalin, thanks for your interest in our Client Care Coord | 2025-07-09T18:53:51 |
| 0 | 330d | +18446758585 | Hi Jwalin,

Thank you for your interest in the Client Care C | 2025-07-09T19:02:42 |

## Recommended Next Actions

1. **The Ochos** — 344d, last 2025-06-25T20:36:11: `GET /messages/imessage/49`
2. **5 SHAHS** — 340d, last 2025-06-29T21:10:41: `GET /messages/imessage/40`
3. **Rutu and Younger but For Real** — 320d, last 2025-07-19T21:05:23: `GET /messages/imessage/19`
4. **Rooftop Pool 8/13** — 297d, last 2025-08-12T16:10:21: `GET /messages/imessage/81`
5. **quj** — 286d, last 2025-08-23T16:06:32: `GET /messages/imessage/127`
6. **Rutu and Younger but For Real** — 166d, last 2025-12-21T15:27:15: `GET /messages/imessage/162`

Machine-readable: `data/imessage_stale_needs_reply.json`

## Stop Condition

Read-only evidence only. Replying requires explicit approval via TUI or `POST /messages/send`.
