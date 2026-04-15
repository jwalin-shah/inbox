"""
Inbox API server — local REST API for iMessage, Gmail, Calendar, Notes, Reminders.
Run: uv run python inbox_server.py
"""

from __future__ import annotations

import asyncio
import base64
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from secrets import compare_digest

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel

import ambient_notes
from services import (
    MLX_LARGE_MODEL,
    AmbientService,
    CalendarEvent,
    Contact,
    DictationService,
    DriveFile,
    GitHubNotification,
    Msg,
    Note,
    Reminder,
    SheetTab,
    Spreadsheet,
    add_google_account,
    ai_briefing,
    ai_extract_actions,
    ai_summarize,
    ai_triage,
    ambient_available,
    calendar_create_event,
    calendar_delete_event,
    calendar_events,
    calendar_update_event,
    close_sqlite_connections,
    contacts_profile,
    contacts_search,
    drive_create_folder,
    drive_delete,
    drive_download,
    drive_files,
    drive_get,
    drive_upload,
    github_mark_all_read,
    github_mark_read,
    github_notifications,
    github_pulls,
    gmail_archive,
    gmail_attachment_download,
    gmail_batch_modify,
    gmail_compose_send,
    gmail_contacts,
    gmail_contacts_by_label,
    gmail_create_filter,
    gmail_delete,
    gmail_labels,
    gmail_mark_read,
    gmail_mark_unread,
    gmail_reply,
    gmail_search,
    gmail_send,
    gmail_star,
    gmail_thread,
    gmail_unstar,
    gmail_unsubscribe,
    google_auth_all,
    imsg_contacts,
    imsg_send,
    imsg_thread,
    init_contacts,
    llm_large_is_loaded,
    llm_large_is_loading,
    load_favorites,
    load_notification_config,
    load_voice_config,
    note_body,
    notes_list,
    parse_quick_event,
    reauth_google_account,
    reminder_by_id,
    reminder_complete,
    reminder_create,
    reminder_delete,
    reminder_edit,
    reminders_list,
    reminders_lists,
    save_favorites,
    save_notification_config,
    save_voice_config,
    search_all,
    send_notification,
    sheets_add_sheet,
    sheets_copy_to,
    sheets_create,
    sheets_delete,
    sheets_delete_sheet,
    sheets_format,
    sheets_get,
    sheets_list,
    sheets_rename_sheet,
    sheets_values_append,
    sheets_values_batch_get,
    sheets_values_batch_update,
    sheets_values_clear,
    sheets_values_get,
    sheets_values_update,
)
from services import (
    autocomplete as services_autocomplete,
)

PORT = 9849
AUTH_TOKEN_ENV = "INBOX_SERVER_TOKEN"  # nosec: B105 - env var name, not a hardcoded credential


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
    attachments: list[dict] = []  # type: ignore[type-arg]
    message_id: str = ""


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
    attendees: list[dict[str, str]] = []


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
    attendees: list[dict[str, str]] = []
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


class ReminderEditRequest(BaseModel):
    title: str | None = None
    due_date: str | None = None
    notes: str | None = None


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


class SheetTabOut(BaseModel):
    sheet_id: int
    title: str
    index: int
    row_count: int
    col_count: int


class SpreadsheetOut(BaseModel):
    id: str
    title: str
    url: str
    sheets: list[SheetTabOut] = []
    account: str = ""


class CreateSpreadsheetRequest(BaseModel):
    title: str
    sheets: list[str] = []
    account: str = ""


class SheetValuesUpdateRequest(BaseModel):
    values: list[list]  # type: ignore[type-arg]
    value_input: str = "USER_ENTERED"


class SheetValuesBatchUpdateRequest(BaseModel):
    data: list[dict]  # type: ignore[type-arg]
    value_input: str = "USER_ENTERED"


class AddSheetRequest(BaseModel):
    title: str
    rows: int = 1000
    cols: int = 26
    account: str = ""


class FormatRequest(BaseModel):
    requests: list[dict]  # type: ignore[type-arg]
    account: str = ""


class BatchGetRequest(BaseModel):
    ranges: list[str]


class CopySheetRequest(BaseModel):
    dest_spreadsheet_id: str


class AutocompleteRequest(BaseModel):
    draft: str = ""
    messages: list[dict] = []  # type: ignore[type-arg]
    max_tokens: int = 32
    temperature: float = 0.5
    mode: str = "complete"


class NotificationTestRequest(BaseModel):
    title: str
    body: str = ""


class VoiceConfigRequest(BaseModel):
    ambient_autostart: bool | None = None
    dictation_hotkey: str | None = None
    vault_dir: str | None = None


class ComposeRequest(BaseModel):
    to: str
    subject: str
    body: str
    account: str = ""


class GmailReplyRequest(BaseModel):
    msg_id: str
    body: str
    thread_id: str = ""
    to: str = ""
    subject: str = ""
    message_id_header: str = ""
    account: str = ""


class GmailBatchModifyRequest(BaseModel):
    msg_ids: list[str]
    add_label_ids: list[str] = []
    remove_label_ids: list[str] = []
    account: str = ""


class GmailFilterCreateRequest(BaseModel):
    from_filter: str = ""
    to_filter: str = ""
    subject_filter: str = ""
    query: str = ""
    has_words: str = ""
    does_not_have_words: str = ""
    add_label_ids: list[str] = []
    remove_label_ids: list[str] = []
    forward: str = ""
    account: str = ""


class SearchRequest(BaseModel):
    q: str
    sources: list[str] = ["all"]
    limit: int = 50


class TriageRequest(BaseModel):
    conversations: list[dict] = []  # type: ignore[type-arg]


class SummarizeRequest(BaseModel):
    thread_id: str = ""
    messages: list[dict] = []  # type: ignore[type-arg]


class ExtractActionsRequest(BaseModel):
    text: str


class BulkUnsubscribeRequest(BaseModel):
    msg_ids: list[str]


# ── Server state ─────────────────────────────────────────────────────────────


class ServerState:
    def __init__(self) -> None:
        self.gmail_services: dict[str, object] = {}
        self.cal_services: dict[str, object] = {}
        self.drive_services: dict[str, object] = {}
        self.sheets_services: dict[str, object] = {}
        self.conv_cache: dict[str, Contact] = {}  # "source:id" -> Contact
        self.events_cache: list[CalendarEvent] = []
        self.ambient: AmbientService = AmbientService(
            on_note=lambda raw, summary: ambient_notes.save_note(raw, summary)
        )
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
        attachments=m.attachments,
        message_id=m.message_id,
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
        attendees=e.attendees,
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


def _sheet_tab_to_out(tab: SheetTab) -> SheetTabOut:
    return SheetTabOut(
        sheet_id=tab.sheet_id,
        title=tab.title,
        index=tab.index,
        row_count=tab.row_count,
        col_count=tab.col_count,
    )


def _spreadsheet_to_out(s: Spreadsheet, account: str = "") -> SpreadsheetOut:
    return SpreadsheetOut(
        id=s.id,
        title=s.title,
        url=s.url,
        sheets=[_sheet_tab_to_out(tab) for tab in s.sheets],
        account=account or s.account,
    )


def _cache_key(source: str, conv_id: str) -> str:
    return f"{source}:{conv_id}"


# ── App lifecycle ────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    n = await asyncio.to_thread(init_contacts)
    print(f"Loaded {n} contacts")

    gmail, cal, drive, sheets = await asyncio.to_thread(google_auth_all)
    state.gmail_services = gmail
    state.cal_services = cal
    state.drive_services = drive
    state.sheets_services = sheets
    print(
        f"Gmail accounts: {list(gmail.keys())}, "
        f"Calendar accounts: {list(cal.keys())}, "
        f"Drive accounts: {list(drive.keys())}, "
        f"Sheets accounts: {list(sheets.keys())}"
    )

    # Pre-warm conversation cache if enabled (reduces cold-start latency)
    if os.environ.get("INBOX_PRE_WARM_CONVERSATIONS", "").strip() in ("1", "true", "yes"):
        try:
            results = await _fetch_conversations("all", limit=50)
            state.conv_cache.clear()
            for c in results:
                state.conv_cache[_cache_key(c.source, c.id)] = c
            print(f"Pre-warmed {len(state.conv_cache)} conversations")
        except Exception:
            logger.warning("Pre-warm conversations failed (non-fatal)")

    # Ambient autostart — can be disabled by env and otherwise respects voice config
    try:
        disable_ambient = os.environ.get("INBOX_DISABLE_AMBIENT", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        voice_cfg = load_voice_config()
        if disable_ambient:
            print("[ambient] Autostart disabled by INBOX_DISABLE_AMBIENT")
        elif voice_cfg.get("ambient_autostart", False):
            avail, reason = ambient_available()
            if avail:
                state.ambient.start()
                print("[ambient] Auto-started ambient listening")
            else:
                print(f"[ambient] Autostart skipped: {reason}")
    except Exception:
        logger.warning("Ambient autostart failed (non-fatal)")

    try:
        yield
    finally:
        state.ambient.stop()
        await asyncio.to_thread(close_sqlite_connections)


app = FastAPI(title="Inbox API", lifespan=lifespan)


def _auth_token() -> str:
    return os.getenv(AUTH_TOKEN_ENV, "").strip()


def _is_authorized(request: Request) -> bool:
    token = _auth_token()
    if not token:
        return True

    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        provided = auth_header[7:].strip()
        if provided and compare_digest(provided, token):
            return True

    api_key = request.headers.get("x-api-key", "").strip()
    return bool(api_key) and compare_digest(api_key, token)


@app.middleware("http")
async def require_api_token(request: Request, call_next):
    if not _is_authorized(request):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Unauthorized"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await call_next(request)


# ── Health ───────────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    from services import _github_token

    return {
        "status": "ok",
        "gmail_accounts": list(state.gmail_services.keys()),
        "calendar_accounts": list(state.cal_services.keys()),
        "drive_accounts": list(state.drive_services.keys()),
        "sheets_accounts": list(state.sheets_services.keys()),
        "github_configured": _github_token() is not None,
    }


# ── Conversations ────────────────────────────────────────────────────────────


async def _fetch_conversations(source: str, limit: int) -> list[Contact]:
    """Fetch conversations from all requested sources in parallel.

    iMessage and Gmail fetches run concurrently via asyncio.gather().
    Multiple Gmail accounts are also fetched concurrently.
    """
    fetch_tasks: list[asyncio.Task[list[Contact]]] = []

    if source in ("all", "imessage"):
        fetch_tasks.append(asyncio.create_task(asyncio.to_thread(imsg_contacts, limit=limit)))

    if source in ("all", "gmail"):
        for email, svc in state.gmail_services.items():
            fetch_tasks.append(
                asyncio.create_task(asyncio.to_thread(gmail_contacts, svc, email, limit=limit))
            )

    if not fetch_tasks:
        return []

    result_lists = await asyncio.gather(*fetch_tasks)
    results: list[Contact] = []
    for contacts in result_lists:
        results.extend(contacts)

    return results


@app.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(source: str = "all", limit: int = 50):
    results = await _fetch_conversations(source, limit)

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


# ── Gmail actions ────────────────────────────────────────────────────────────


def _get_gmail_service(msg_id: str) -> tuple[object, Contact | None]:
    """Look up the correct Gmail service for a message, using cache or fallback."""
    contact = state.conv_cache.get(_cache_key("gmail", msg_id))
    if contact and contact.gmail_account in state.gmail_services:
        return state.gmail_services[contact.gmail_account], contact
    if state.gmail_services:
        return next(iter(state.gmail_services.values())), contact
    raise HTTPException(404, "No Gmail service available")


def _get_gmail_service_for_account(account: str = "") -> tuple[str, object]:
    acct = account or (next(iter(state.gmail_services)) if state.gmail_services else "")
    svc = state.gmail_services.get(acct)
    if not svc:
        raise HTTPException(404, "No Gmail account available")
    return acct, svc


def _get_sheets_service_for_account(account: str = "") -> tuple[str, object]:
    acct = account or (next(iter(state.sheets_services)) if state.sheets_services else "")
    svc = state.sheets_services.get(acct)
    if not svc:
        raise HTTPException(404, "No Sheets account available")
    return acct, svc


def _get_drive_service_for_account(account: str = "") -> tuple[str, object]:
    acct = account or (next(iter(state.drive_services)) if state.drive_services else "")
    svc = state.drive_services.get(acct)
    if not svc:
        raise HTTPException(404, "No Drive account available")
    return acct, svc


@app.post("/messages/gmail/{msg_id}/archive")
async def archive_gmail(msg_id: str):
    svc, _ = _get_gmail_service(msg_id)
    ok = await asyncio.to_thread(gmail_archive, svc, msg_id)
    return {"ok": ok}


@app.post("/messages/gmail/{msg_id}/delete")
async def delete_gmail(msg_id: str):
    svc, _ = _get_gmail_service(msg_id)
    ok = await asyncio.to_thread(gmail_delete, svc, msg_id)
    return {"ok": ok}


@app.post("/messages/gmail/{msg_id}/unsubscribe")
async def unsubscribe_gmail(msg_id: str):
    svc, _ = _get_gmail_service(msg_id)
    result = await asyncio.to_thread(gmail_unsubscribe, svc, msg_id)
    if not result["raw"]:
        raise HTTPException(422, "No List-Unsubscribe header found")
    return result


@app.post("/messages/gmail/bulk-unsubscribe")
async def bulk_unsubscribe_gmail(req: BulkUnsubscribeRequest):
    """Unsubscribe from multiple emails in parallel."""
    results = []
    for msg_id in req.msg_ids:
        try:
            svc, _ = _get_gmail_service(msg_id)
            result = await asyncio.to_thread(gmail_unsubscribe, svc, msg_id)
            results.append({"msg_id": msg_id, **result})
        except Exception as e:
            results.append({"msg_id": msg_id, "error": str(e)})

    return {"total": len(req.msg_ids), "results": results}


@app.post("/messages/gmail/{msg_id}/star")
async def star_gmail(msg_id: str):
    svc, _ = _get_gmail_service(msg_id)
    ok = await asyncio.to_thread(gmail_star, svc, msg_id)
    return {"ok": ok}


@app.post("/messages/gmail/{msg_id}/unstar")
async def unstar_gmail(msg_id: str):
    svc, _ = _get_gmail_service(msg_id)
    ok = await asyncio.to_thread(gmail_unstar, svc, msg_id)
    return {"ok": ok}


@app.post("/messages/gmail/{msg_id}/read")
async def mark_gmail_read(msg_id: str):
    svc, _ = _get_gmail_service(msg_id)
    ok = await asyncio.to_thread(gmail_mark_read, svc, msg_id)
    return {"ok": ok}


@app.post("/messages/gmail/{msg_id}/unread")
async def mark_gmail_unread(msg_id: str):
    svc, _ = _get_gmail_service(msg_id)
    ok = await asyncio.to_thread(gmail_mark_unread, svc, msg_id)
    return {"ok": ok}


@app.get("/gmail/labels")
async def list_gmail_labels(account: str = ""):
    acct = account or (next(iter(state.gmail_services)) if state.gmail_services else "")
    svc = state.gmail_services.get(acct)
    if not svc:
        raise HTTPException(404, "No Gmail account available")
    labels = await asyncio.to_thread(gmail_labels, svc)
    return labels


@app.get("/messages/gmail/{msg_id}/attachments/{att_id}")
async def download_gmail_attachment(msg_id: str, att_id: str):
    svc, _ = _get_gmail_service(msg_id)
    data = await asyncio.to_thread(gmail_attachment_download, svc, msg_id, att_id)
    if data is None:
        raise HTTPException(404, "Attachment not found")
    return {"data": base64.urlsafe_b64encode(data).decode(), "size": len(data)}


@app.post("/messages/compose")
async def compose_email(req: ComposeRequest):
    _, svc = _get_gmail_service_for_account(req.account)
    ok = await asyncio.to_thread(gmail_compose_send, svc, req.to, req.subject, req.body)
    return {"ok": ok}


@app.post("/messages/gmail/reply")
async def reply_gmail(req: GmailReplyRequest):
    acct, svc = _get_gmail_service_for_account(req.account)
    ok = await asyncio.to_thread(
        gmail_reply,
        svc,
        req.msg_id,
        req.body,
        req.thread_id,
        req.to,
        req.subject,
        req.message_id_header,
    )
    return {"ok": ok, "account": acct}


@app.get("/gmail/conversations", response_model=list[ConversationOut])
async def list_gmail_by_label(label: str = "INBOX", limit: int = 50, account: str = ""):
    """List Gmail conversations filtered by label."""
    results: list[Contact] = []
    targets = (
        {account: state.gmail_services[account]}
        if account and account in state.gmail_services
        else state.gmail_services
    )
    for email, svc in targets.items():
        contacts = await asyncio.to_thread(
            gmail_contacts_by_label, svc, email, label_id=label, limit=limit
        )
        results.extend(contacts)

    results.sort(key=lambda c: c.last_ts, reverse=True)

    # Update cache with these results
    for c in results:
        state.conv_cache[_cache_key(c.source, c.id)] = c

    return [_contact_to_out(c) for c in results]


@app.get("/gmail/search", response_model=list[ConversationOut])
async def search_gmail(
    q: str = "",
    limit: int = 20,
    label: str = "",
    from_filter: str = "",
    subject_filter: str = "",
    after: str = "",
    before: str = "",
    account: str = "",
):
    results: list[Contact] = []
    targets = (
        {account: state.gmail_services[account]}
        if account and account in state.gmail_services
        else state.gmail_services
    )
    for email, svc in targets.items():
        contacts = await asyncio.to_thread(
            gmail_search,
            svc,
            email,
            q,
            limit,
            label,
            from_filter,
            subject_filter,
            after,
            before,
        )
        results.extend(contacts)

    results.sort(key=lambda c: c.last_ts, reverse=True)
    for c in results:
        state.conv_cache[_cache_key(c.source, c.id)] = c
    return [_contact_to_out(c) for c in results[:limit]]


@app.post("/gmail/batch-modify")
async def batch_modify_gmail(req: GmailBatchModifyRequest):
    acct, svc = _get_gmail_service_for_account(req.account)
    ok = await asyncio.to_thread(
        gmail_batch_modify,
        svc,
        req.msg_ids,
        req.add_label_ids,
        req.remove_label_ids,
    )
    return {"ok": ok, "account": acct, "count": len(req.msg_ids)}


@app.post("/gmail/filters")
async def create_gmail_filter(req: GmailFilterCreateRequest):
    acct, svc = _get_gmail_service_for_account(req.account)
    criteria = {
        "from": req.from_filter,
        "to": req.to_filter,
        "subject": req.subject_filter,
        "query": req.query or req.has_words,
        "negatedQuery": req.does_not_have_words,
    }
    result = await asyncio.to_thread(
        gmail_create_filter,
        svc,
        criteria,
        req.add_label_ids,
        req.remove_label_ids,
        req.forward,
    )
    if not result:
        raise HTTPException(
            400,
            "Failed to create Gmail filter. Re-auth may be required for gmail.settings.basic scope.",
        )
    return {"ok": True, "account": acct, "filter": result}


# ── Calendar ─────────────────────────────────────────────────────────────────


@app.get("/calendar/events", response_model=list[CalendarEventOut])
async def list_events(
    date: str | None = None,
    start: str | None = None,
    end: str | None = None,
):
    if start and end:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
        evts = await asyncio.to_thread(
            calendar_events,
            state.cal_services,
            start_date=start_dt,
            end_date=end_dt,
        )
    else:
        dt = datetime.fromisoformat(date) if date else None
        evts = await asyncio.to_thread(calendar_events, state.cal_services, dt)
    state.events_cache = evts
    return [_event_to_out(e) for e in evts]


@app.get("/calendar/upcoming", response_model=list[CalendarEventOut])
async def list_upcoming_events(days: int = 7):
    days = max(1, min(days, 30))
    start_dt = datetime.now()
    end_dt = start_dt + timedelta(days=days - 1)
    evts = await asyncio.to_thread(
        calendar_events,
        state.cal_services,
        start_date=start_dt,
        end_date=end_dt,
    )
    state.events_cache = evts
    return [_event_to_out(e) for e in evts]


@app.post("/calendar/events")
async def create_event(req: CreateEventRequest):
    account = req.account or (next(iter(state.cal_services)) if state.cal_services else "")
    svc = state.cal_services.get(account)
    if not svc:
        raise HTTPException(404, "No calendar account available")

    try:
        event_id = await asyncio.to_thread(
            calendar_create_event,
            svc,
            summary=req.summary,
            start=datetime.fromisoformat(req.start),
            end=datetime.fromisoformat(req.end),
            location=req.location,
            description=req.description,
            all_day=req.all_day,
            attendees=req.attendees,
        )
        return {"ok": True, "event_id": event_id}
    except Exception as e:
        raise HTTPException(500, f"Failed to create event: {str(e)}") from e


@app.post("/calendar/events/quick")
async def create_quick_event(req: QuickEventRequest):
    account = req.account or (next(iter(state.cal_services)) if state.cal_services else "")
    svc = state.cal_services.get(account)
    if not svc:
        raise HTTPException(404, "No calendar account available")

    parsed = parse_quick_event(req.text)
    try:
        event_id = await asyncio.to_thread(
            calendar_create_event,
            svc,
            summary=parsed["summary"],
            start=parsed["start"],
            end=parsed["end"],
            location=parsed.get("location", ""),
            all_day=parsed.get("all_day", False),
        )
        return {"ok": True, "event_id": event_id}
    except Exception as e:
        raise HTTPException(500, f"Failed to create event: {str(e)}") from e


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
    reminder = await asyncio.to_thread(reminder_by_id, reminder_id)
    if not reminder:
        raise HTTPException(404, "Reminder not found")
    ok = await asyncio.to_thread(reminder_complete, reminder.title, reminder.list_name)
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


@app.put("/reminders/{reminder_id}")
async def edit_reminder(reminder_id: str, req: ReminderEditRequest):
    reminder = await asyncio.to_thread(reminder_by_id, reminder_id)
    if not reminder:
        raise HTTPException(404, "Reminder not found")
    ok = await asyncio.to_thread(
        reminder_edit,
        current_title=reminder.title,
        title=req.title,
        due_date=req.due_date,
        notes=req.notes,
        list_name=reminder.list_name,
    )
    return {"ok": ok}


@app.delete("/reminders/{reminder_id}")
async def delete_reminder(reminder_id: str):
    reminder = await asyncio.to_thread(reminder_by_id, reminder_id)
    if not reminder:
        raise HTTPException(404, "Reminder not found")
    ok = await asyncio.to_thread(reminder_delete, reminder.title, reminder.list_name)
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
    folder_id: str = "",
):
    results: list[DriveFileOut] = []
    targets = (
        {account: state.drive_services[account]}
        if account and account in state.drive_services
        else state.drive_services
    )
    for email, svc in targets.items():
        files = await asyncio.to_thread(
            drive_files,
            svc,
            query=q,
            limit=limit,
            shared_with_me=shared,
            folder_id=folder_id,
        )
        results.extend(_drive_to_out(f, account=email) for f in files)
    results.sort(key=lambda f: f.modified, reverse=True)
    return results[:limit]


@app.get("/drive/files/{file_id}/download")
async def download_drive_file(file_id: str, account: str = ""):
    from fastapi.responses import Response

    acct = account or (next(iter(state.drive_services)) if state.drive_services else "")
    svc = state.drive_services.get(acct)
    if not svc:
        raise HTTPException(404, "No Drive account available")
    result = await asyncio.to_thread(drive_download, svc, file_id)
    if not result:
        raise HTTPException(404, "File not found or download failed")
    content, mime_type = result
    return Response(content=content, media_type=mime_type)


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


# ── Sheets ───────────────────────────────────────────────────────────────────


@app.get("/sheets", response_model=list[SpreadsheetOut])
async def list_sheets(q: str = "", limit: int = 20, account: str = ""):

    # List spreadsheets from Drive (need Drive service)
    if account and account in state.drive_services:
        drive_svcs = {account: state.drive_services[account]}
    else:
        drive_svcs = state.drive_services

    results = []
    for acct, drive_svc in drive_svcs.items():
        sheets = await asyncio.to_thread(sheets_list, drive_svc, q, limit, acct)
        results.extend(sheets)
    return [_spreadsheet_to_out(s, s.account) for s in results]


@app.post("/sheets", response_model=SpreadsheetOut)
async def create_spreadsheet(req: CreateSpreadsheetRequest):

    acct, sheets_svc = _get_sheets_service_for_account(req.account)
    result = await asyncio.to_thread(sheets_create, sheets_svc, req.title, req.sheets or [])
    if not result:
        raise HTTPException(400, "Failed to create spreadsheet")
    return _spreadsheet_to_out(result, acct)


@app.get("/sheets/{spreadsheet_id}", response_model=SpreadsheetOut)
async def get_spreadsheet(spreadsheet_id: str, account: str = ""):

    acct, sheets_svc = _get_sheets_service_for_account(account)
    result = await asyncio.to_thread(sheets_get, sheets_svc, spreadsheet_id)
    if not result:
        raise HTTPException(404, "Spreadsheet not found")
    return _spreadsheet_to_out(result, acct)


@app.delete("/sheets/{spreadsheet_id}")
async def delete_spreadsheet(spreadsheet_id: str, account: str = ""):

    acct, drive_svc = _get_drive_service_for_account(account)
    ok = await asyncio.to_thread(sheets_delete, drive_svc, spreadsheet_id)
    return {"ok": ok}


@app.get("/sheets/{spreadsheet_id}/values/{range_}")
async def read_range(spreadsheet_id: str, range_: str, account: str = ""):

    acct, sheets_svc = _get_sheets_service_for_account(account)
    result = await asyncio.to_thread(sheets_values_get, sheets_svc, spreadsheet_id, range_)
    if result is None:
        raise HTTPException(404, "Failed to read range")
    return {"range": range_, "values": result}


@app.put("/sheets/{spreadsheet_id}/values/{range_}")
async def update_range(
    spreadsheet_id: str, range_: str, req: SheetValuesUpdateRequest, account: str = ""
):

    acct, sheets_svc = _get_sheets_service_for_account(account)
    result = await asyncio.to_thread(
        sheets_values_update, sheets_svc, spreadsheet_id, range_, req.values, req.value_input
    )
    if result is None:
        raise HTTPException(400, "Failed to update range")
    return result


@app.post("/sheets/{spreadsheet_id}/values/{range_}/append")
async def append_range(
    spreadsheet_id: str, range_: str, req: SheetValuesUpdateRequest, account: str = ""
):

    acct, sheets_svc = _get_sheets_service_for_account(account)
    result = await asyncio.to_thread(
        sheets_values_append, sheets_svc, spreadsheet_id, range_, req.values, req.value_input
    )
    if result is None:
        raise HTTPException(400, "Failed to append range")
    return result


@app.delete("/sheets/{spreadsheet_id}/values/{range_}")
async def clear_range(spreadsheet_id: str, range_: str, account: str = ""):

    acct, sheets_svc = _get_sheets_service_for_account(account)
    ok = await asyncio.to_thread(sheets_values_clear, sheets_svc, spreadsheet_id, range_)
    return {"ok": ok}


@app.post("/sheets/{spreadsheet_id}/values/batch-get")
async def batch_get_values(spreadsheet_id: str, req: BatchGetRequest, account: str = ""):

    acct, sheets_svc = _get_sheets_service_for_account(account)
    result = await asyncio.to_thread(
        sheets_values_batch_get, sheets_svc, spreadsheet_id, req.ranges
    )
    if result is None:
        raise HTTPException(404, "Failed to read ranges")
    return result


@app.post("/sheets/{spreadsheet_id}/values/batch-update")
async def batch_update_values(
    spreadsheet_id: str, req: SheetValuesBatchUpdateRequest, account: str = ""
):

    acct, sheets_svc = _get_sheets_service_for_account(account)
    result = await asyncio.to_thread(
        sheets_values_batch_update, sheets_svc, spreadsheet_id, req.data, req.value_input
    )
    if result is None:
        raise HTTPException(400, "Failed to batch update ranges")
    return result


@app.post("/sheets/{spreadsheet_id}/tabs", response_model=SheetTabOut)
async def add_sheet_tab(spreadsheet_id: str, req: AddSheetRequest):

    acct, sheets_svc = _get_sheets_service_for_account(req.account)
    result = await asyncio.to_thread(
        sheets_add_sheet, sheets_svc, spreadsheet_id, req.title, req.rows, req.cols
    )
    if not result:
        raise HTTPException(400, "Failed to add sheet tab")
    return _sheet_tab_to_out(result)


@app.delete("/sheets/{spreadsheet_id}/tabs/{sheet_id}")
async def delete_sheet_tab(spreadsheet_id: str, sheet_id: int, account: str = ""):

    acct, sheets_svc = _get_sheets_service_for_account(account)
    ok = await asyncio.to_thread(sheets_delete_sheet, sheets_svc, spreadsheet_id, sheet_id)
    return {"ok": ok}


@app.patch("/sheets/{spreadsheet_id}/tabs/{sheet_id}")
async def rename_sheet_tab(spreadsheet_id: str, sheet_id: int, title: str, account: str = ""):

    acct, sheets_svc = _get_sheets_service_for_account(account)
    ok = await asyncio.to_thread(sheets_rename_sheet, sheets_svc, spreadsheet_id, sheet_id, title)
    return {"ok": ok}


@app.post("/sheets/{spreadsheet_id}/tabs/{sheet_id}/copy")
async def copy_sheet_tab(
    spreadsheet_id: str, sheet_id: int, req: CopySheetRequest, account: str = ""
):

    acct, sheets_svc = _get_sheets_service_for_account(account)
    result = await asyncio.to_thread(
        sheets_copy_to, sheets_svc, spreadsheet_id, sheet_id, req.dest_spreadsheet_id
    )
    if not result:
        raise HTTPException(400, "Failed to copy sheet")
    return _sheet_tab_to_out(result)


@app.post("/sheets/{spreadsheet_id}/format")
async def format_spreadsheet(spreadsheet_id: str, req: FormatRequest):

    acct, sheets_svc = _get_sheets_service_for_account(req.account)
    result = await asyncio.to_thread(sheets_format, sheets_svc, spreadsheet_id, req.requests)
    if result is None:
        raise HTTPException(400, "Failed to apply formatting")
    return result


# ── Search ───────────────────────────────────────────────────────────────────


@app.post("/search")
async def search_endpoint(req: SearchRequest):
    result = await asyncio.to_thread(
        search_all,
        query=req.q,
        sources=req.sources,
        limit=req.limit,
        gmail_services=state.gmail_services,
        cal_services=state.cal_services,
    )
    return result


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
    avail, reason = ambient_available()
    return {
        "ambient": state.ambient.is_running,
        "available": avail,
        "reason": reason,
        "dictation": state.dictation.is_running,
        "dictation_available": state.dictation.available,
    }


@app.get("/ambient/transcript")
async def get_ambient_transcript(limit: int = 50):
    segments = state.ambient.get_transcript(max_segments=limit)
    return {"segments": segments, "count": len(segments)}


@app.get("/ambient/notes")
async def list_ambient_notes(limit: int = 50, q: str = ""):
    notes = await asyncio.to_thread(ambient_notes.list_daily_notes, limit=limit)
    if q:
        q_lower = q.lower()
        notes = [n for n in notes if q_lower in n.get("date", "").lower()]
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


@app.get("/dictation/status")
async def dictation_status():
    return {
        "running": state.dictation.is_running,
        "available": state.dictation.available,
    }


# ── Voice Config ─────────────────────────────────────────────────────────────


@app.get("/voice/config")
async def get_voice_config():
    return await asyncio.to_thread(load_voice_config)


@app.put("/voice/config")
async def put_voice_config(req: VoiceConfigRequest):
    current = await asyncio.to_thread(load_voice_config)
    updates = req.model_dump(exclude_none=True)
    merged = {**current, **updates}
    await asyncio.to_thread(save_voice_config, merged)
    return merged


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

    return {
        "loaded": llm_is_loaded(),
        "small": {
            "loaded": llm_is_loaded(),
            "model_id": "mlx-community/Qwen3.5-0.8B-MLX-4bit",
        },
        "large": {
            "loaded": llm_large_is_loaded(),
            "model_id": MLX_LARGE_MODEL,
            "loading": llm_large_is_loading(),
        },
    }


@app.post("/llm/warmup")
async def llm_warmup_endpoint():
    from services import llm_warmup

    await asyncio.to_thread(llm_warmup)
    return {"status": "ready"}


# ── Contacts ─────────────────────────────────────────────────────────────────


@app.get("/contacts/search")
async def search_contacts(q: str = "", limit: int = 20):
    results = await asyncio.to_thread(
        contacts_search,
        state.gmail_services,
        q,
        limit,
    )
    return results


@app.get("/contacts/{contact_id}/profile")
async def get_contact_profile(contact_id: str):
    profile = await asyncio.to_thread(
        contacts_profile,
        contact_id,
        state.gmail_services,
        state.cal_services,
    )
    return profile


@app.get("/contacts/favorites")
async def get_favorites():
    favs = await asyncio.to_thread(load_favorites)
    return {"favorites": sorted(favs)}


@app.post("/contacts/favorites/{contact_id}")
async def add_favorite(contact_id: str):
    favs = await asyncio.to_thread(load_favorites)
    favs.add(contact_id)
    await asyncio.to_thread(save_favorites, favs)
    return {"ok": True, "favorites": sorted(favs)}


@app.delete("/contacts/favorites/{contact_id}")
async def remove_favorite(contact_id: str):
    favs = await asyncio.to_thread(load_favorites)
    favs.discard(contact_id)
    await asyncio.to_thread(save_favorites, favs)
    return {"ok": True, "favorites": sorted(favs)}


# ── AI endpoints ─────────────────────────────────────────────────────────────


@app.post("/ai/briefing")
async def ai_briefing_endpoint():
    """Compile a morning briefing from today's data."""
    try:
        today_dt = datetime.now()
        events_raw = await asyncio.to_thread(calendar_events, state.cal_services, today_dt)
        events = [
            {
                "summary": e.summary,
                "start": e.start.isoformat(),
                "end": e.end.isoformat(),
                "all_day": e.all_day,
            }
            for e in events_raw
        ]
    except Exception:
        events = []

    try:
        reminders_raw = await asyncio.to_thread(reminders_list)
        reminders = [
            {"title": r.title, "completed": r.completed, "list_name": r.list_name}
            for r in reminders_raw
        ]
    except Exception:
        reminders = []

    try:
        all_convos: list[dict] = []  # type: ignore[type-arg]
        for acct_email, svc in state.gmail_services.items():
            try:
                gmail_raw = await asyncio.to_thread(gmail_contacts, svc, acct_email, 20)
                all_convos.extend({"source": "gmail", "unread": c.unread} for c in gmail_raw)
            except Exception:
                pass
        imsg_raw = await asyncio.to_thread(lambda: imsg_contacts(limit=50))
        all_convos.extend({"source": "imessage", "unread": c.unread} for c in imsg_raw)
    except Exception:
        all_convos = []

    try:
        gh_notifications = await asyncio.to_thread(github_notifications)
        gh_notifs = [{"unread": n.unread} for n in gh_notifications]
    except Exception:
        gh_notifs = []

    try:
        gh_prs = await asyncio.to_thread(github_pulls)
    except Exception:
        gh_prs = []

    result = await asyncio.to_thread(ai_briefing, events, reminders, all_convos, gh_notifs, gh_prs)
    return result


@app.post("/ai/triage")
async def ai_triage_endpoint(req: TriageRequest):
    """Return priority mapping for a list of conversations."""
    result = await asyncio.to_thread(ai_triage, req.conversations)
    return result


@app.post("/ai/summarize")
async def ai_summarize_endpoint(req: SummarizeRequest):
    """Summarize an email thread."""
    result = await asyncio.to_thread(ai_summarize, req.thread_id, req.messages)
    return result


@app.post("/ai/extract-actions")
async def ai_extract_actions_endpoint(req: ExtractActionsRequest):
    """Extract action items from message text."""
    result = await asyncio.to_thread(ai_extract_actions, req.text)
    return result


# ── Accounts ─────────────────────────────────────────────────────────────────


@app.get("/accounts")
async def list_accounts():
    from services import _github_token

    return {
        "gmail": list(state.gmail_services.keys()),
        "calendar": list(state.cal_services.keys()),
        "drive": list(state.drive_services.keys()),
        "sheets": list(state.sheets_services.keys()),
        "github": _github_token() is not None,
    }


@app.post("/accounts/add")
async def add_account():
    email = await asyncio.to_thread(add_google_account)
    if not email:
        raise HTTPException(400, "Failed to add account — no credentials.json")
    # Reload all services
    gmail, cal, drive, sheets = await asyncio.to_thread(google_auth_all)
    state.gmail_services = gmail
    state.cal_services = cal
    state.drive_services = drive
    state.sheets_services = sheets
    return {"email": email}


@app.post("/accounts/reauth")
async def reauth_account(req: AccountRequest):
    if not req.email:
        raise HTTPException(400, "email is required")
    email = await asyncio.to_thread(reauth_google_account, req.email)
    if not email:
        raise HTTPException(400, "Re-auth failed")
    gmail, cal, drive, sheets = await asyncio.to_thread(google_auth_all)
    state.gmail_services = gmail
    state.cal_services = cal
    state.drive_services = drive
    state.sheets_services = sheets
    return {"email": email}


# ── Notifications ────────────────────────────────────────────────────────────


@app.get("/notifications/config")
async def get_notification_config():
    return await asyncio.to_thread(load_notification_config)


@app.put("/notifications/config")
async def put_notification_config(cfg: dict):  # type: ignore[type-arg]
    ok = await asyncio.to_thread(save_notification_config, cfg)
    if not ok:
        raise HTTPException(500, "Failed to save notification config")
    return {"ok": True}


@app.post("/notifications/test")
async def test_notification(req: NotificationTestRequest):
    sent = await asyncio.to_thread(send_notification, req.title, req.body or "Test notification")
    return {"ok": sent, "sent": sent}


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
