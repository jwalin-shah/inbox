# Inbox — Project Context

## What this is
A terminal TUI (Python + Textual + Rich) that unifies iMessage, Gmail, Google Calendar, and Apple Notes into one inbox. Client-server architecture: a local FastAPI server handles all data access, the TUI is a thin HTTP client. Agents can also hit the server API directly.

## Run it
```bash
cd ~/projects/inbox
uv run python inbox.py          # starts server automatically + TUI
uv run python inbox_server.py   # server only (for agent access)
```

## Architecture
```
services.py       — data access layer (iMessage, Gmail, Calendar, Notes, Reminders, GitHub, Drive, auth, LLM, audio)
inbox_server.py   — FastAPI server wrapping services.py (port 9849)
inbox_client.py   — sync HTTP client for the server API
inbox.py          — Textual TUI (thin client, auto-starts server)
contacts.py       — reads macOS AddressBook SQLite DBs, resolves phone→name
ambient_notes.py  — writes ambient captures to Obsidian vault (~/vault/daily/)
ambient_daemon.py — background daemon for audio capture → ASR → extraction → notes
tokens/           — per-account Google OAuth tokens (auto-created)
credentials.json  — Google OAuth client secret (never commit)
github_token.txt  — GitHub personal access token (never commit)
```

## API endpoints (localhost:9849)
```
GET  /health
GET  /conversations?source=all|imessage|gmail&limit=50
GET  /messages/{source}/{conv_id}?thread_id=...
POST /messages/send  {"conv_id", "source", "text"}
GET  /calendar/events?date=YYYY-MM-DD
POST /calendar/events  {"summary", "start", "end", ...}
POST /calendar/events/quick  {"text": "Meeting 2pm-3pm @ Office"}
PUT  /calendar/events/{id}
DELETE /calendar/events/{id}
GET  /notes?limit=50
GET  /notes/{id}
GET  /reminders?list_name=...&show_completed=false&limit=100
GET  /reminders/lists
POST /reminders  {"title", "list_name", "due_date", "notes"}
POST /reminders/{id}/complete
PUT  /reminders/{id}  {"title", "due_date", "notes"}
DELETE /reminders/{id}
GET  /github/notifications?all=false
POST /github/notifications/{id}/read
POST /github/notifications/read-all
GET  /github/pulls?repo=owner/name
GET  /drive/files?q=...&shared=false&limit=20&account=...&folder_id=...
GET  /drive/files/{id}?account=...
POST /drive/upload  (multipart: file + folder_id + account)
POST /drive/folder  {"name", "parent_id", "account"}
DELETE /drive/files/{id}?account=...
POST /ambient/start
POST /ambient/stop
GET  /ambient/status
GET  /ambient/notes?limit=50&q=search
GET  /ambient/notes/{id}
POST /dictation/start
POST /dictation/stop
POST /autocomplete  {"draft", "messages", "max_tokens", "temperature", "mode"}
GET  /llm/status
POST /llm/warmup
GET  /accounts
POST /accounts/add
POST /accounts/reauth  {"email": "..."}
GET  /notifications/config
PUT  /notifications/config  {enabled, sources, quiet_hours}
POST /notifications/test  {"title", "body"}
```

## Key bindings (TUI)
- **Ctrl+1-5** — switch tabs: All, iMessage, Gmail, Calendar, Notes
- **Ctrl+6** — toggle ambient listening (start/stop)
- **Ctrl+7** — switch to GitHub tab
- **Ctrl+R** — refresh all data
- **Ctrl+A** — add Google account (opens browser)
- **Ctrl+Shift+A** — re-auth current account (new scopes)
- **Ctrl+N** — new calendar event
- **Ctrl+D** — delete selected event
- **r** — mark selected GitHub notification as read (GitHub tab only)
- **Shift+R** — mark all GitHub notifications as read (GitHub tab only)
- **o** — open notification URL in browser (GitHub tab only)
- **Tab** — accept autocomplete suggestion (in compose input)
- **Ctrl+Q** — quit

## Google Drive
- Uses the same OAuth token as Gmail/Calendar (full `drive` scope)
- Upload files, create folders, list/search/delete files
- Multi-account: queries all authed accounts, routes by `account` param
- Delete = trash (recoverable), not permanent delete
- Supports folder filtering via `folder_id` parameter

## GitHub
- Personal access token in `github_token.txt` (needs `notifications` + `repo` scopes)
- Notifications: displayed in TUI with type icons (🔀 PR review, 🐛 issue, 📦 release, 🔔 other) plus unread indicator; mark-read individual or all
- Pull requests: searches for PRs requesting review from the authed user
- Token file is gitignored

## Apple Reminders
- Reads from all Reminders SQLite DBs in `~/Library/Group Containers/group.com.apple.reminders/`
- Multiple DBs = multiple accounts (iCloud, local, etc.) — scans all non-empty ones
- Timestamps use Apple epoch (2001-01-01), same as Notes
- Mutations (complete, create) via AppleScript — SQLite is read-only
- Lists come from `ZREMCDBASELIST`, reminders from `ZREMCDREMINDER`

## Multi-account Gmail
- Each Google account gets its own token in `tokens/`
- Legacy `token.json` auto-migrates to `tokens/` on first run
- All accounts queried on refresh, contacts tagged with `gmail_account`
- Sends route through the correct account's service
- Scopes: `gmail.readonly` + `gmail.send` + `calendar` + `drive` (full read/write)

## LLM + Audio stack
- **LLM**: Qwen3.5-0.8B-MLX-4bit (~500MB) — shared singleton for extraction + autocomplete
- **Outlines model**: Cached singleton wrapping the base model — reused for all constrained generation calls
- **Constrained gen**: Outlines with mlx-lm backend — FSM token masking for valid JSON
- **Ambient ASR**: mlx-whisper (whisper-base.en-mlx) — chunk-based, MLX-native
- **Dictation ASR**: whisper-stream C++ binary — streaming 500ms step, low latency
- **Ambient notes**: Written to Obsidian vault at `~/vault/daily/` as markdown; captures logged with preview
- **Keyboard injection**: pyobjc CGEvent (dictation mode, needs Accessibility permission)
- **Ambient auto-start**: Ambient listening starts automatically on server startup (gracefully fails if dependencies unavailable)

## Key design decisions
- **Client-server split** — server handles data, TUI and agents are both clients
- **Server-side conv cache** — server caches conversations so `/messages/send` just needs conv_id + text
- **Query by chat.rowid, not handle.id** — handles group chats correctly
- **contact.guid** holds the iMessage chat GUID for sending to groups via AppleScript
- **Contact.id for iMessage** = `chat.rowid` (integer as string), NOT a phone number
- **Contact.reply_to for Gmail** = actual email address; `contact.id` is the Gmail message ID
- **Phone matching** generates variants for inconsistent iMessage/AddressBook storage
- **Gmail HTML→text** — strips HTML tags, quoted replies, signatures, tracking URLs
- **Optimistic send** — message appears in TUI immediately, confirmed in background
- **Notes via SQLite** for listing, AppleScript for full body (protobuf parsing is too complex)
- **Flattened module structure** — LLM and audio logic integrated into main services rather than nested directories
- **Tab state preservation** — switching between tabs preserves active conversation/event selection so returning to a tab shows the same context

## Data sources
- **iMessage**: `~/Library/Messages/chat.db` (read-only SQLite)
- **AddressBook**: `~/Library/Application Support/AddressBook/Sources/*/AddressBook-v22.abcddb`
- **Apple Notes**: `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite`
- **Apple Reminders**: `~/Library/Group Containers/group.com.apple.reminders/Container_v1/Stores/Data-*.sqlite`
- **Gmail/Calendar/Drive**: Google API via OAuth tokens in `tokens/`
- **GitHub**: REST API via personal access token in `github_token.txt`

## Testing
- Comprehensive test suite in `tests/` covers services, server, client, audio, LLM, contacts, ambient notes
- `conftest.py` stubs heavy ML/hardware dependencies (`mlx_lm`, `mlx_whisper`, `sounddevice`, `Quartz`, `outlines`) so tests run in CI without full deps installed
- Fixtures for temp reminders DB, vault paths, mock services

## Dev commands
```bash
uv run ruff check --fix .   # lint
uv run pyright              # type check
uv run pytest               # unit tests
```
