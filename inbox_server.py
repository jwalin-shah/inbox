"""
Inbox API server — local REST API for iMessage, Gmail, Calendar, Notes, Reminders.
Run: uv run python inbox_server.py
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

import ambient_notes
from services import (
    AmbientService,
    CalendarEvent,
    Contact,
    DictationService,
    DriveFile,
    GitHubNotification,
    Msg,
    Note,
    Reminder,
    add_google_account,
    calendar_create_event,
    calendar_delete_event,
    calendar_events,
    calendar_update_event,
    drive_create_folder,
    drive_delete,
    drive_files,
    drive_get,
    drive_upload,
    github_mark_all_read,
    github_mark_read,
    github_notifications,
    github_pulls,
    gmail_contacts,
    gmail_send,
    gmail_thread,
    google_auth_all,
    imsg_contacts,
    imsg_send,
    imsg_thread,
    init_contacts,
    note_body,
    notes_list,
    parse_quick_event,
    reauth_google_account,
    reminder_complete,
    reminder_create,
    reminders_list,
    reminders_lists,
)
from services import (
    autocomplete as services_autocomplete,
)

PORT = 9849


# ── Pydantic models ──────────────────────────────────────────────────────────


class ConversationOut(BaseModel):
    id: str
    name: str
    source: str
    snippet: str
    unread: int
    last_ts: str
    guid: str = ""
    is_group: bool = False
    members: list[str] = []
    reply_to: str = ""
    thread_id: str = ""
    message_id_header: str = ""
    gmail_account: str = ""


class MessageOut(BaseModel):
    sender: str
    body: str
    ts: str
    is_me: bool
    source: str


class CalendarEventOut(BaseModel):
    summary: str
    start: str
    end: str
    location: str = ""
    description: str = ""
    account: str = ""
    all_day: bool = False
    event_id: str = ""
    calendar_id: str = ""


class NoteOut(BaseModel):
    id: str
    title: str
    snippet: str
    modified: str
    folder: str = ""


class SendRequest(BaseModel):
    conv_id: str
    source: str  # "imessage" | "gmail"
    text: str


class CreateEventRequest(BaseModel):
    summary: str
    start: str  # ISO datetime or quick format
    end: str  # ISO datetime
    location: str = ""
    description: str = ""
    all_day: bool = False
    account: str = ""  # defaults to first calendar account


class QuickEventRequest(BaseModel):
    text: str  # e.g. "Meeting 2pm-3pm @ Office"
    account: str = ""


class UpdateEventRequest(BaseModel):
    summary: str | None = None
    start: str | None = None
    end: str | None = None
    location: str | None = None
    description: str | None = None


class AccountRequest(BaseModel):
    email: str = ""


class ReminderOut(BaseModel):
    id: str
    title: str
    completed: bool
    list_name: str = ""
    due_date: str | None = None
    notes: str = ""
    priority: int = 0
    flagged: bool = False
    creation_date: str | None = None


class ReminderCreateRequest(BaseModel):
    title: str
    list_name: str = "Reminders"
    due_date: str = ""
    notes: str = ""


class GitHubNotificationOut(BaseModel):
    id: str
    title: str
    repo: str
    type: str
    reason: str
    unread: bool
    updated_at: str
    url: str = ""


class DriveFileOut(BaseModel):
    id: str
    name: str
    mime_type: str
    modified: str
    size: int = 0
    shared: bool = False
    web_link: str = ""
    parents: list[str] = []
    account: str = ""


class DriveCreateFolderRequest(BaseModel):
    name: str
    parent_id: str = ""
    account: str = ""


class AutocompleteRequest(BaseModel):
    draft: str = ""
    messages: list[dict] = []  # type: ignore[type-arg]
    max_tokens: int = 32
    temperature: float = 0.5
    mode: str = "complete"


# ── Server state ─────────────────────────────────────────────────────────────


class ServerState:
    def __init__(self) -> None:
        self.gmail_services: dict[str, object] = {}
        self.cal_services: dict[str, object] = {}
        self.drive_services: dict[str, object] = {}
        self.conv_cache: dict[str, Contact] = {}  # "source:id" -> Contact
        self.events_cache: list[CalendarEvent] = []
        self.ambient: AmbientService = AmbientService(on_note=lambda raw, summary: None)
        self.dictation: DictationService = DictationService()


state = ServerState()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _contact_to_out(c: Contact) -> ConversationOut:
    return ConversationOut(
        id=c.id,
        name=c.name,
        source=c.source,
        snippet=c.snippet,
        unread=c.unread,
        last_ts=c.last_ts.isoformat(),
        guid=c.guid,
        is_group=c.is_group,
        members=c.members,
        reply_to=c.reply_to,
        thread_id=c.thread_id,
        message_id_header=c.message_id_header,
        gmail_account=c.gmail_account,
    )


def _msg_to_out(m: Msg) -> MessageOut:
    return MessageOut(
        sender=m.sender,
        body=m.body,
        ts=m.ts.isoformat(),
        is_me=m.is_me,
        source=m.source,
    )


def _event_to_out(e: CalendarEvent) -> CalendarEventOut:
    return CalendarEventOut(
        summary=e.summary,
        start=e.start.isoformat(),
        end=e.end.isoformat(),
        location=e.location,
        description=e.description,
        account=e.account,
        all_day=e.all_day,
        event_id=e.event_id,
        calendar_id=e.calendar_id,
    )


def _note_to_out(n: Note) -> NoteOut:
    return NoteOut(
        id=n.id,
        title=n.title,
        snippet=n.snippet,
        modified=n.modified.isoformat(),
        folder=n.folder,
    )


def _reminder_to_out(r: Reminder) -> ReminderOut:
    return ReminderOut(
        id=r.id,
        title=r.title,
        completed=r.completed,
        list_name=r.list_name,
        due_date=r.due_date.isoformat() if r.due_date else None,
        notes=r.notes,
        priority=r.priority,
        flagged=r.flagged,
        creation_date=r.creation_date.isoformat() if r.creation_date else None,
    )


def _gh_notif_to_out(n: GitHubNotification) -> GitHubNotificationOut:
    return GitHubNotificationOut(
        id=n.id,
        title=n.title,
        repo=n.repo,
        type=n.type,
        reason=n.reason,
        unread=n.unread,
        updated_at=n.updated_at.isoformat(),
        url=n.url,
    )


def _drive_to_out(f: DriveFile, account: str = "") -> DriveFileOut:
    return DriveFileOut(
        id=f.id,
        name=f.name,
        mime_type=f.mime_type,
        modified=f.modified.isoformat(),
        size=f.size,
        shared=f.shared,
        web_link=f.web_link,
        parents=f.parents,
        account=account or f.account,
    )


def _cache_key(source: str, conv_id: str) -> str:
    return f"{source}:{conv_id}"


# ── App lifecycle ────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    n = await asyncio.to_thread(init_contacts)
    print(f"Loaded {n} contacts")

    gmail, cal, drive = await asyncio.to_thread(google_auth_all)
    state.gmail_services = gmail
    state.cal_services = cal
    state.drive_services = drive
    print(
        f"Gmail accounts: {list(gmail.keys())}, "
        f"Calendar accounts: {list(cal.keys())}, "
        f"Drive accounts: {list(drive.keys())}"
    )

    yield


app = FastAPI(title="Inbox API", lifespan=lifespan)


# ── Health ───────────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    from services import _github_token

    return {
        "status": "ok",
        "gmail_accounts": list(state.gmail_services.keys()),
        "calendar_accounts": list(state.cal_services.keys()),
        "drive_accounts": list(state.drive_services.keys()),
        "github_configured": _github_token() is not None,
    }


# ── Conversations ────────────────────────────────────────────────────────────


@app.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(source: str = "all", limit: int = 50):
    results: list[Contact] = []

    if source in ("all", "imessage"):
        imsg = await asyncio.to_thread(imsg_contacts, limit=limit)
        results.extend(imsg)

    if source in ("all", "gmail"):
        for email, svc in state.gmail_services.items():
            gmail = await asyncio.to_thread(gmail_contacts, svc, email, limit=limit)
            results.extend(gmail)

    results.sort(key=lambda c: c.last_ts, reverse=True)

    # Update cache
    state.conv_cache.clear()
    for c in results:
        state.conv_cache[_cache_key(c.source, c.id)] = c

    return [_contact_to_out(c) for c in results]


# ── Messages ─────────────────────────────────────────────────────────────────


@app.get("/messages/{source}/{conv_id}", response_model=list[MessageOut])
async def get_messages(source: str, conv_id: str, thread_id: str = "", limit: int = 50):
    if source == "imessage":
        msgs = await asyncio.to_thread(imsg_thread, conv_id, limit=limit)
    elif source == "gmail":
        # Find the right service
        contact = state.conv_cache.get(_cache_key("gmail", conv_id))
        if contact and contact.gmail_account in state.gmail_services:
            svc = state.gmail_services[contact.gmail_account]
        elif state.gmail_services:
            svc = next(iter(state.gmail_services.values()))
        else:
            raise HTTPException(404, "No Gmail service available")
        tid = thread_id or (contact.thread_id if contact else "")
        msgs = await asyncio.to_thread(gmail_thread, svc, conv_id, tid)
    else:
        raise HTTPException(400, f"Unknown source: {source}")

    return [_msg_to_out(m) for m in msgs]


@app.post("/messages/send")
async def send_message(req: SendRequest):
    contact = state.conv_cache.get(_cache_key(req.source, req.conv_id))
    if not contact:
        raise HTTPException(404, "Conversation not found in cache — call /conversations first")

    if req.source == "imessage":
        ok = await asyncio.to_thread(imsg_send, contact, req.text)
    elif req.source == "gmail":
        svc = state.gmail_services.get(contact.gmail_account)
        if not svc:
            raise HTTPException(404, "Gmail account not found")
        ok = await asyncio.to_thread(gmail_send, svc, contact, req.text)
    else:
        raise HTTPException(400, f"Unknown source: {req.source}")

    return {"ok": ok}


# ── Calendar ─────────────────────────────────────────────────────────────────


@app.get("/calendar/events", response_model=list[CalendarEventOut])
async def list_events(date: str | None = None):
    dt = datetime.fromisoformat(date) if date else None
    evts = await asyncio.to_thread(calendar_events, state.cal_services, dt)
    state.events_cache = evts
    return [_event_to_out(e) for e in evts]


@app.post("/calendar/events")
async def create_event(req: CreateEventRequest):
    account = req.account or (next(iter(state.cal_services)) if state.cal_services else "")
    svc = state.cal_services.get(account)
    if not svc:
        raise HTTPException(404, "No calendar account available")

    event_id = await asyncio.to_thread(
        calendar_create_event,
        svc,
        summary=req.summary,
        start=datetime.fromisoformat(req.start),
        end=datetime.fromisoformat(req.end),
        location=req.location,
        description=req.description,
        all_day=req.all_day,
    )
    return {"ok": event_id is not None, "event_id": event_id}


@app.post("/calendar/events/quick")
async def create_quick_event(req: QuickEventRequest):
    account = req.account or (next(iter(state.cal_services)) if state.cal_services else "")
    svc = state.cal_services.get(account)
    if not svc:
        raise HTTPException(404, "No calendar account available")

    parsed = parse_quick_event(req.text)
    event_id = await asyncio.to_thread(
        calendar_create_event,
        svc,
        summary=parsed["summary"],
        start=parsed["start"],
        end=parsed["end"],
        location=parsed.get("location", ""),
        all_day=parsed.get("all_day", False),
    )
    return {"ok": event_id is not None, "event_id": event_id}


@app.put("/calendar/events/{event_id}")
async def update_event(
    event_id: str,
    req: UpdateEventRequest,
    calendar_id: str = "primary",
    account: str = "",
):
    acct = account or (next(iter(state.cal_services)) if state.cal_services else "")
    svc = state.cal_services.get(acct)
    if not svc:
        raise HTTPException(404, "No calendar account available")

    ok = await asyncio.to_thread(
        calendar_update_event,
        svc,
        event_id,
        summary=req.summary,
        start=(datetime.fromisoformat(req.start) if req.start else None),
        end=datetime.fromisoformat(req.end) if req.end else None,
        location=req.location,
        description=req.description,
        calendar_id=calendar_id,
    )
    return {"ok": ok}


@app.delete("/calendar/events/{event_id}")
async def delete_event(
    event_id: str,
    calendar_id: str = "primary",
    account: str = "",
):
    acct = account or (next(iter(state.cal_services)) if state.cal_services else "")
    svc = state.cal_services.get(acct)
    if not svc:
        raise HTTPException(404, "No calendar account available")

    ok = await asyncio.to_thread(calendar_delete_event, svc, event_id, calendar_id)
    return {"ok": ok}


# ── Notes ────────────────────────────────────────────────────────────────────


@app.get("/notes", response_model=list[NoteOut])
async def list_notes(limit: int = 50):
    notes = await asyncio.to_thread(notes_list, limit=limit)
    return [_note_to_out(n) for n in notes]


@app.get("/notes/{note_id}")
async def get_note(note_id: str):
    notes = await asyncio.to_thread(notes_list, limit=500)
    note = next((n for n in notes if n.id == note_id), None)
    if not note:
        raise HTTPException(404, "Note not found")
    body = await asyncio.to_thread(note_body, note.title)
    return {
        "id": note.id,
        "title": note.title,
        "body": body or note.snippet,
        "modified": note.modified.isoformat(),
        "folder": note.folder,
    }


# ── Reminders ────────────────────────────────────────────────────────────────


@app.get("/reminders/lists")
async def list_reminder_lists():
    lists = await asyncio.to_thread(reminders_lists)
    return lists


@app.get("/reminders", response_model=list[ReminderOut])
async def list_reminders(
    list_name: str | None = None,
    show_completed: bool = False,
    limit: int = 100,
):
    items = await asyncio.to_thread(
        reminders_list,
        list_name=list_name,
        show_completed=show_completed,
        limit=limit,
    )
    return [_reminder_to_out(r) for r in items]


@app.post("/reminders/{reminder_id}/complete")
async def complete_reminder(reminder_id: str):
    # Look up title from the DB to use with AppleScript
    items = await asyncio.to_thread(reminders_list, show_completed=False, limit=500)
    reminder = next((r for r in items if r.id == reminder_id), None)
    if not reminder:
        raise HTTPException(404, "Reminder not found")
    ok = await asyncio.to_thread(reminder_complete, reminder.title)
    return {"ok": ok}


@app.post("/reminders")
async def create_reminder(req: ReminderCreateRequest):
    ok = await asyncio.to_thread(
        reminder_create,
        title=req.title,
        list_name=req.list_name,
        due_date=req.due_date,
        notes=req.notes,
    )
    return {"ok": ok}


# ── GitHub ───────────────────────────────────────────────────────────────────


@app.get("/github/notifications", response_model=list[GitHubNotificationOut])
async def list_github_notifications(all: bool = False):
    notifs = await asyncio.to_thread(github_notifications, all_notifs=all)
    return [_gh_notif_to_out(n) for n in notifs]


@app.post("/github/notifications/{notification_id}/read")
async def mark_github_read(notification_id: str):
    ok = await asyncio.to_thread(github_mark_read, notification_id)
    return {"ok": ok}


@app.post("/github/notifications/read-all")
async def mark_all_github_read():
    ok = await asyncio.to_thread(github_mark_all_read)
    return {"ok": ok}


@app.get("/github/pulls")
async def list_github_pulls(repo: str | None = None):
    pulls = await asyncio.to_thread(github_pulls, repo=repo)
    return pulls


# ── Google Drive ─────────────────────────────────────────────────────────────


@app.get("/drive/files", response_model=list[DriveFileOut])
async def list_drive_files(
    q: str = "",
    shared: bool = False,
    limit: int = 20,
    account: str = "",
):
    results: list[DriveFileOut] = []
    targets = (
        {account: state.drive_services[account]}
        if account and account in state.drive_services
        else state.drive_services
    )
    for email, svc in targets.items():
        files = await asyncio.to_thread(
            drive_files, svc, query=q, limit=limit, shared_with_me=shared
        )
        results.extend(_drive_to_out(f, account=email) for f in files)
    results.sort(key=lambda f: f.modified, reverse=True)
    return results[:limit]


@app.get("/drive/files/{file_id}", response_model=DriveFileOut)
async def get_drive_file(file_id: str, account: str = ""):
    acct = account or (next(iter(state.drive_services)) if state.drive_services else "")
    svc = state.drive_services.get(acct)
    if not svc:
        raise HTTPException(404, "No Drive account available")
    f = await asyncio.to_thread(drive_get, svc, file_id)
    if not f:
        raise HTTPException(404, "File not found")
    return _drive_to_out(f, account=acct)


_file_field = File(...)


@app.post("/drive/upload", response_model=DriveFileOut)
async def upload_to_drive(
    file: UploadFile = _file_field,
    folder_id: str = "",
    account: str = "",
):
    import tempfile
    from pathlib import Path

    acct = account or (next(iter(state.drive_services)) if state.drive_services else "")
    svc = state.drive_services.get(acct)
    if not svc:
        raise HTTPException(404, "No Drive account available")

    # Save upload to temp file, then upload to Drive
    with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{file.filename}") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = await asyncio.to_thread(
            drive_upload, svc, tmp_path, folder_id=folder_id, name=file.filename or ""
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if not result:
        raise HTTPException(500, "Upload failed")
    return _drive_to_out(result, account=acct)


@app.post("/drive/folder", response_model=DriveFileOut)
async def create_drive_folder(req: DriveCreateFolderRequest):
    acct = req.account or (next(iter(state.drive_services)) if state.drive_services else "")
    svc = state.drive_services.get(acct)
    if not svc:
        raise HTTPException(404, "No Drive account available")
    result = await asyncio.to_thread(drive_create_folder, svc, req.name, parent_id=req.parent_id)
    if not result:
        raise HTTPException(500, "Failed to create folder")
    return _drive_to_out(result, account=acct)


@app.delete("/drive/files/{file_id}")
async def delete_drive_file(file_id: str, account: str = ""):
    acct = account or (next(iter(state.drive_services)) if state.drive_services else "")
    svc = state.drive_services.get(acct)
    if not svc:
        raise HTTPException(404, "No Drive account available")
    ok = await asyncio.to_thread(drive_delete, svc, file_id)
    return {"ok": ok}


# ── Ambient / Dictation ─────────────────────────────────────────────────────


@app.post("/ambient/start")
async def start_ambient():
    if state.ambient.is_running:
        return {"status": "already_running"}
    state.ambient.start()
    return {"status": "started"}


@app.post("/ambient/stop")
async def stop_ambient():
    if not state.ambient.is_running:
        return {"status": "not_running"}
    state.ambient.stop()
    return {"status": "stopped"}


@app.get("/ambient/status")
async def ambient_status():
    return {
        "ambient": state.ambient.is_running,
        "dictation": state.dictation.is_running,
        "dictation_available": state.dictation.available,
    }


@app.get("/ambient/notes")
async def list_ambient_notes(limit: int = 50, q: str = ""):
    notes = await asyncio.to_thread(ambient_notes.list_daily_notes, limit=limit)
    return notes


@app.get("/ambient/notes/{date}")
async def get_ambient_note(date: str):
    content = await asyncio.to_thread(ambient_notes.read_daily_note, date)
    if content is None:
        raise HTTPException(404, "Note not found")
    return {"date": date, "content": content}


@app.post("/dictation/start")
async def start_dictation():
    if not state.dictation.available:
        raise HTTPException(400, "whisper-stream binary not available")
    if state.dictation.is_running:
        return {"status": "already_running"}
    state.dictation.start()
    return {"status": "started"}


@app.post("/dictation/stop")
async def stop_dictation():
    if not state.dictation.is_running:
        return {"status": "not_running"}
    state.dictation.stop()
    return {"status": "stopped"}


# ── Autocomplete / LLM ──────────────────────────────────────────────────────


@app.post("/autocomplete")
async def autocomplete_endpoint(req: AutocompleteRequest):
    try:
        result = await asyncio.to_thread(
            services_autocomplete,
            req.draft,
            req.messages,
            req.max_tokens,
            req.temperature,
            req.mode,
        )
        return {"completion": result}
    except Exception as e:
        return {"completion": None, "error": str(e)}


@app.get("/llm/status")
async def llm_status():
    from services import llm_is_loaded

    return {"loaded": llm_is_loaded()}


@app.post("/llm/warmup")
async def llm_warmup_endpoint():
    from services import llm_warmup

    await asyncio.to_thread(llm_warmup)
    return {"status": "ready"}


# ── Accounts ─────────────────────────────────────────────────────────────────


@app.get("/accounts")
async def list_accounts():
    from services import _github_token

    return {
        "gmail": list(state.gmail_services.keys()),
        "calendar": list(state.cal_services.keys()),
        "drive": list(state.drive_services.keys()),
        "github": _github_token() is not None,
    }


@app.post("/accounts/add")
async def add_account():
    email = await asyncio.to_thread(add_google_account)
    if not email:
        raise HTTPException(400, "Failed to add account — no credentials.json")
    # Reload all services
    gmail, cal, drive = await asyncio.to_thread(google_auth_all)
    state.gmail_services = gmail
    state.cal_services = cal
    state.drive_services = drive
    return {"email": email}


@app.post("/accounts/reauth")
async def reauth_account(req: AccountRequest):
    if not req.email:
        raise HTTPException(400, "email is required")
    email = await asyncio.to_thread(reauth_google_account, req.email)
    if not email:
        raise HTTPException(400, "Re-auth failed")
    gmail, cal, drive = await asyncio.to_thread(google_auth_all)
    state.gmail_services = gmail
    state.cal_services = cal
    state.drive_services = drive
    return {"email": email}


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
