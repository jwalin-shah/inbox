# Local Capture Runbook

## iMessage

Current state: Full Disk Access is working for the local terminal/Codex path.
`~/Library/Messages/chat.db` can be opened read-only, and an incremental sync
processed new iMessage rows on 2026-05-28.

Live iMessage sync is controlled by:

```bash
INBOX_DISABLE_IMESSAGE_SYNC=0
```

The LaunchAgent path uses `scripts/run_index_incremental.sh`, which defaults to
live iMessage sync enabled. To temporarily disable iMessage reads:

```bash
echo 'INBOX_DISABLE_IMESSAGE_SYNC=1' >> ~/.config/raycast/inbox-workflows.env
launchctl kickstart -k "gui/$(id -u)/com.jwalin.inbox.index-sync"
```

Manual smoke:

```bash
cd /Users/jwalinshah/projects/inbox
python3 - <<'PY'
import sqlite3
from pathlib import Path
p = Path.home() / "Library/Messages/chat.db"
conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
print(conn.execute("select max(rowid), count(*) from message").fetchone())
conn.close()
PY

INBOX_DISABLE_IMESSAGE_SYNC=0 uv run python message_sync.py incremental
```

If the smoke fails with `operation not permitted`, add the app that launches the
process to System Settings -> Privacy & Security -> Full Disk Access. This may
need to be Codex, Terminal, iTerm, Raycast, or the specific launchd parent,
depending on where the command runs from.

## WhatsApp

Current state: store exists, but body capture is thin. The scanner LaunchAgent
requires a reachable browser tab with WhatsApp Web.

Manual hydration:

```bash
cd /Users/jwalinshah/projects/inbox
scripts/open_whatsapp_scanner_browser.sh
# Log into WhatsApp Web if prompted.
scripts/run_whatsapp_scan_once.sh
```

If launchd logs say `uv: command not found`, set:

```bash
echo 'INBOX_UV_BIN=/opt/homebrew/bin/uv' >> ~/.config/raycast/inbox-workflows.env
```

## Exports To Add / Process

Highest priority:

1. LinkedIn full archive: messages, connections, job applications.
2. Google Takeout: contacts, calendar, Gmail metadata, Drive file lists, Chrome.
3. OpenAI and Claude exports: project/work history and useful context.
4. Meta/Facebook/Instagram: messages and contacts if relationship graph matters.
5. Apple data export: only if needed beyond direct iMessage local sync.
6. X/Reddit/Amazon/Netflix/Uber/TikTok: lower priority unless a specific task
   needs that history.

Do not upload raw personal exports to external providers. Process locally first
and promote only source-backed rows into the ops queues.
