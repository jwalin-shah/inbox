# Mode: whatsapp (NEW)

Read + send WhatsApp messages. Requires `wacli` installed.

## Workflow

### 1. Prerequisites Check

```bash
which wacli >/dev/null || {
  echo "❌ wacli not installed"
  echo "Fix: brew install wacli OR pip install wacli"
  exit 1
}
```

### 2. List Unread Chats

```bash
wacli chats list --unread --json --limit 20
```

Output format:
```json
[
  {"chat_id": "16282358390@s.whatsapp.net", "name": "Tierra Hall", "unread": 2},
  ...
]
```

### 3. For Each Unread Chat, Get Messages

```bash
wacli messages list --chat {chat_id} --limit 5 --json
```

### 4. Score by Urgency (same as Gmail)

- 5 = Human, unread, >48h old (stale reply)
- 4 = Human, unread, <48h
- 3 = Human, read, this week
- 2 = Media, stickers, etc.
- 1 = Automated/bot

Boost +1 if name in priority_senders

### 5. Output Format

```
## WhatsApp — {N} unread chats

| Score | Name           | Last message        | Age    |
|-------|----------------|---------------------|--------|
| 4     | Tierra Hall    | "Can you confirm..." | 2h ago |
| 3     | Friend Name    | "Are you free?"     | 1d ago |
```

---

## Sending (Manual Approval)

When user wants to reply to WhatsApp:

```bash
# Draft first (agent writes)
# Show to user
# Get approval
# Then send:
wacli send text --to {chat_id} --message "{text}"
```

---

## Integration with Other Modes

- `/inbox triage` includes WhatsApp conversations
- `/inbox followup` can draft WhatsApp replies (with approval)
- `/inbox what-did-i-miss` includes WhatsApp unread

---

## Requirements

- `wacli` installed (WhatsApp CLI)
- WhatsApp logged in on connected device
- Bearer token for wacli API (optional, for more reliability)
