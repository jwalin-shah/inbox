"""
MCP gateway for Inbox.

This server is the public assistant-facing layer. It talks to the private
local inbox REST server and exposes a smaller, safer tool surface over MCP.

Run:
    uv run python mcp_server.py

Environment:
    INBOX_MCP_TOKEN      Optional bearer token for the public MCP endpoint.
    INBOX_SERVER_URL     Private inbox server URL (defaults to localhost:9849).
    INBOX_SERVER_TOKEN   Bearer token for the private inbox server, if enabled.
    INBOX_MEMORY_DB      Optional path for the local memory store sqlite file.
"""

from __future__ import annotations

import os
from pathlib import Path
from secrets import compare_digest

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

import ambient_notes
from mcp_backend import InboxBackend, InboxBackendError
from memory_store import MemoryStore
from tools_registry import register_all as _register_registry_tools

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - runtime-only path
    raise RuntimeError(
        "The 'mcp' package is required to run mcp_server.py. Install dependencies with: uv sync"
    ) from exc


MCP_TOKEN_ENV = "INBOX_MCP_TOKEN"  # nosec: B105 - env var name, not a hardcoded credential
MEMORY_DB_ENV = "INBOX_MEMORY_DB"


backend = InboxBackend()
memory_store = MemoryStore(
    Path(os.getenv(MEMORY_DB_ENV, "")).expanduser() if os.getenv(MEMORY_DB_ENV) else None
)
mcp = FastMCP(
    "Inbox Personal Assistant",
    stateless_http=True,
    json_response=True,
)


def _require_confirmation(confirm: bool, action: str) -> None:
    if not confirm:
        raise ValueError(
            f"{action} requires explicit confirmation. Retry with confirm=True after user approval."
        )


def _public_token() -> str:
    return os.getenv(MCP_TOKEN_ENV, "").strip()


def _is_publicly_authorized(request: Request) -> bool:
    token = _public_token()
    if not token:
        return True

    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        provided = auth_header[7:].strip()
        return bool(provided) and compare_digest(provided, token)
    return False


class PublicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        if not _is_publicly_authorized(request):
            return JSONResponse(
                {"detail": "Unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)


async def health(_request: Request) -> JSONResponse:
    try:
        backend_health = await backend.health()
    except InboxBackendError as exc:
        backend_health = {"status": "error", "detail": str(exc)}

    return JSONResponse(
        {
            "status": "ok",
            "mcp_path": "/mcp",
            "backend": backend_health,
            "memory_db": str(memory_store.db_path),
            "auth_enabled": bool(_public_token()),
        }
    )


@mcp.tool()
async def get_email_thread(message_id: str, thread_id: str = "") -> list[dict]:
    """Fetch a Gmail thread by message id and optional thread id."""
    return await backend.get_email_thread(message_id=message_id, thread_id=thread_id)


@mcp.tool()
async def archive_email_thread(message_id: str, confirm: bool = False) -> dict:
    """Archive a Gmail thread by removing the INBOX label."""
    _require_confirmation(confirm, "archive_email_thread")
    return await backend.archive_email_thread(message_id)


@mcp.tool()
async def mark_email_read(message_id: str, confirm: bool = False) -> dict:
    """Mark a Gmail message as read."""
    _require_confirmation(confirm, "mark_email_read")
    return await backend.mark_email_read(message_id)


@mcp.tool()
async def list_message_threads(limit: int = 20) -> list[dict]:
    """List recent iMessage conversations."""
    return await backend.list_message_threads(limit=limit)


@mcp.tool()
async def get_message_thread(conv_id: str, limit: int = 50) -> list[dict]:
    """Fetch the messages for an iMessage conversation."""
    return await backend.get_message_thread(conv_id=conv_id, limit=limit)


@mcp.tool()
async def send_imessage(conv_id: str, body: str, confirm: bool = False) -> dict:
    """Send an iMessage reply. This tool is confirmation-gated."""
    _require_confirmation(confirm, "send_imessage")
    return await backend.send_imessage(conv_id=conv_id, text=body)


@mcp.tool()
async def list_notes(limit: int = 20) -> list[dict]:
    """List recent Apple Notes."""
    return await backend.list_notes(limit=limit)


@mcp.tool()
async def get_note(note_id: str) -> dict:
    """Fetch one Apple Note by id."""
    return await backend.get_note(note_id)


@mcp.tool()
async def append_daily_note(content: str, confirm: bool = False) -> dict:
    """Append content to today's daily note in the Obsidian vault."""
    _require_confirmation(confirm, "append_daily_note")
    ambient_notes.append_to_daily(content)
    return {"ok": True, "date": str(ambient_notes._today_file().stem)}


@mcp.tool()
async def list_reminders(
    list_name: str = "",
    show_completed: bool = False,
    limit: int = 100,
) -> list[dict]:
    """List Apple Reminders."""
    return await backend.list_reminders(
        list_name=list_name,
        show_completed=show_completed,
        limit=limit,
    )


@mcp.tool()
async def create_reminder(
    title: str,
    confirm: bool = False,
    list_name: str = "Reminders",
    due_date: str = "",
    notes: str = "",
    priority: int = 0,
    flagged: bool = False,
) -> dict:
    """Create a reminder. This tool is confirmation-gated."""
    _require_confirmation(confirm, "create_reminder")
    return await backend.create_reminder(
        title=title,
        list_name=list_name,
        due_date=due_date,
        notes=notes,
        priority=priority,
        flagged=flagged,
    )


@mcp.tool()
async def complete_reminder(reminder_id: str, confirm: bool = False) -> dict:
    """Complete a reminder. This tool is confirmation-gated."""
    _require_confirmation(confirm, "complete_reminder")
    return await backend.complete_reminder(reminder_id)


@mcp.tool()
async def uncomplete_reminder(reminder_id: str, confirm: bool = False) -> dict:
    """Mark a reminder as incomplete. This tool is confirmation-gated."""
    _require_confirmation(confirm, "uncomplete_reminder")
    return await backend.uncomplete_reminder(reminder_id)


@mcp.tool()
async def list_task_lists(account: str = "") -> list[dict]:
    """List all Google Task lists."""
    return await backend.list_task_lists(account=account)


@mcp.tool()
async def list_tasks(
    list_id: str = "@default",
    show_completed: bool = False,
    limit: int = 100,
    account: str = "",
) -> list[dict]:
    """List tasks in a Google Task list."""
    return await backend.list_tasks(
        list_id=list_id,
        show_completed=show_completed,
        limit=limit,
        account=account,
    )


@mcp.tool()
async def create_task(
    title: str,
    confirm: bool = False,
    list_id: str = "@default",
    due: str = "",
    notes: str = "",
    account: str = "",
) -> dict:
    """Create a Google Task. This tool is confirmation-gated."""
    _require_confirmation(confirm, "create_task")
    return await backend.create_task(
        title=title,
        list_id=list_id,
        due=due,
        notes=notes,
        account=account,
    )


@mcp.tool()
async def complete_task(
    task_id: str, list_id: str = "@default", confirm: bool = False, account: str = ""
) -> dict:
    """Complete a Google Task. This tool is confirmation-gated."""
    _require_confirmation(confirm, "complete_task")
    return await backend.complete_task(task_id=task_id, list_id=list_id, account=account)


@mcp.tool()
async def update_task(
    task_id: str,
    confirm: bool = False,
    list_id: str = "@default",
    title: str | None = None,
    due: str | None = None,
    notes: str | None = None,
    account: str = "",
) -> dict:
    """Update a Google Task. This tool is confirmation-gated."""
    _require_confirmation(confirm, "update_task")
    return await backend.update_task(
        task_id=task_id,
        list_id=list_id,
        title=title,
        due=due,
        notes=notes,
        account=account,
    )


@mcp.tool()
async def delete_task(
    task_id: str, list_id: str = "@default", confirm: bool = False, account: str = ""
) -> dict:
    """Delete a Google Task. This tool is confirmation-gated."""
    _require_confirmation(confirm, "delete_task")
    return await backend.delete_task(task_id=task_id, list_id=list_id, account=account)


@mcp.tool()
async def departure_times(
    origin: str = "",
    mode: str = "driving",
    buffer_minutes: int = 10,
    lookahead_hours: int = 24,
) -> list[dict]:
    """Get departure times for upcoming calendar events with locations.
    Uses Google Maps Distance Matrix API for real-time travel estimates.
    origin: home address (defaults to INBOX_HOME_ADDRESS env var).
    mode: 'driving' | 'transit' | 'walking' | 'bicycling'."""
    return await backend.departure_times(
        origin=origin, mode=mode, buffer_minutes=buffer_minutes, lookahead_hours=lookahead_hours
    )


@mcp.tool()
async def travel_time(origin: str, destination: str, mode: str = "driving") -> dict:
    """Get travel time between two locations via Google Maps."""
    return await backend.travel_time(origin=origin, destination=destination, mode=mode)


@mcp.tool()
async def whatsapp_contacts(limit: int = 20) -> list[dict]:
    """List WhatsApp conversations via macOS Accessibility API (read-only).
    WhatsApp app must be running. Returns empty list if app is not running or inspection fails."""
    return await backend.whatsapp_contacts(limit=limit)


@mcp.tool()
async def whatsapp_messages(chat_name: str, limit: int = 50) -> list[dict]:
    """Fetch WhatsApp messages for a conversation (placeholder).
    Returns empty list pending full AX tree navigation implementation."""
    return await backend.whatsapp_messages(chat_name=chat_name, limit=limit)


@mcp.tool()
async def list_scheduled_messages(status: str = "pending") -> list[dict]:
    """List scheduled messages waiting to be sent. Status: pending|sent|cancelled|failed."""
    return await backend.list_scheduled(status=status)


@mcp.tool()
async def schedule_message(
    source: str,
    conv_id: str,
    text: str,
    send_at: str,
    confirm: bool = False,
    account: str = "",
) -> dict:
    """Schedule a message to be sent at a future time.
    source: 'gmail' | 'imessage'.
    conv_id: iMessage contact id, or for Gmail compose use format 'to@email.com|Subject'.
    send_at: ISO datetime (e.g. '2026-04-16T09:00:00').
    This tool is confirmation-gated."""
    _require_confirmation(confirm, "schedule_message")
    return await backend.schedule_message(
        source=source, conv_id=conv_id, text=text, send_at=send_at, account=account
    )


@mcp.tool()
async def cancel_scheduled_message(msg_id: int, confirm: bool = False) -> dict:
    """Cancel a scheduled message by id. Confirmation-gated."""
    _require_confirmation(confirm, "cancel_scheduled_message")
    return await backend.cancel_scheduled(msg_id)


@mcp.tool()
async def list_followups(status: str = "active") -> list[dict]:
    """List follow-up reminders. Status: active|fired|cancelled|replied."""
    return await backend.list_followups(status=status)


@mcp.tool()
async def create_followup(
    source: str,
    conv_id: str,
    remind_after: str,
    reminder_title: str,
    confirm: bool = False,
    thread_id: str = "",
    reminder_list: str = "Reminders",
) -> dict:
    """Create a follow-up reminder for a conversation.
    If no reply comes in by remind_after, an Apple Reminder will be created.
    source: 'gmail' | 'imessage'.
    remind_after: ISO datetime (e.g. '2026-04-15T18:00:00').
    This tool is confirmation-gated."""
    _require_confirmation(confirm, "create_followup")
    return await backend.create_followup(
        source=source,
        conv_id=conv_id,
        remind_after=remind_after,
        reminder_title=reminder_title,
        thread_id=thread_id,
        reminder_list=reminder_list,
    )


@mcp.tool()
async def cancel_followup(fid: int, confirm: bool = False) -> dict:
    """Cancel a follow-up reminder by id. Confirmation-gated."""
    _require_confirmation(confirm, "cancel_followup")
    return await backend.cancel_followup(fid)


@mcp.tool()
async def list_task_links(
    message_id: str = "",
    message_source: str = "",
    task_id: str = "",
    task_source: str = "",
) -> list[dict]:
    """List task↔message links. Provide either (message_id, message_source) OR (task_id, task_source)."""
    return await backend.list_task_links(
        message_id=message_id,
        message_source=message_source,
        task_id=task_id,
        task_source=task_source,
    )


@mcp.tool()
async def link_task_to_message(
    task_id: str,
    task_source: str,
    message_id: str,
    message_source: str,
    confirm: bool = False,
    thread_id: str = "",
    account: str = "",
) -> dict:
    """Link an existing task to a message. Confirmation-gated.
    task_source: 'google_tasks' | 'reminders'.
    message_source: 'gmail' | 'imessage'."""
    _require_confirmation(confirm, "link_task_to_message")
    return await backend.link_task_to_message(
        task_id=task_id,
        task_source=task_source,
        message_id=message_id,
        message_source=message_source,
        thread_id=thread_id,
        account=account,
    )


@mcp.tool()
async def unlink_task(link_id: int, confirm: bool = False) -> dict:
    """Delete a task↔message link. Confirmation-gated."""
    _require_confirmation(confirm, "unlink_task")
    return await backend.unlink_task(link_id)


@mcp.tool()
async def create_task_from_message(
    message_id: str,
    message_source: str,
    title: str,
    confirm: bool = False,
    task_type: str = "google_tasks",
    list_id: str = "@default",
    list_name: str = "Reminders",
    notes: str = "",
    thread_id: str = "",
    account: str = "",
) -> dict:
    """Create a task from a message and auto-link it.
    message_source: 'gmail' | 'imessage'.
    task_type: 'google_tasks' | 'reminders'.
    This tool is confirmation-gated."""
    _require_confirmation(confirm, "create_task_from_message")
    return await backend.create_task_from_message(
        message_id=message_id,
        message_source=message_source,
        title=title,
        task_type=task_type,
        list_id=list_id,
        list_name=list_name,
        notes=notes,
        thread_id=thread_id,
        account=account,
    )


@mcp.tool()
async def get_memory(
    query: str = "",
    memory_type: str = "",
    subject: str = "",
    status: str = "",
    limit: int = 10,
) -> list[dict]:
    """Retrieve structured memory entries for people, projects, preferences, or commitments."""
    return memory_store.query_entries(
        query=query,
        memory_type=memory_type,
        subject=subject,
        status=status,
        limit=limit,
    )


@mcp.tool()
async def save_memory_note(
    memory_type: str,
    subject: str,
    content: str,
    confirm: bool = False,
    source: str = "chat",
    confidence: float = 0.8,
    status: str = "active",
    expires_at: str = "",
) -> dict:
    """Save a structured memory note. This tool is confirmation-gated."""
    _require_confirmation(confirm, "save_memory_note")
    return memory_store.save_entry(
        memory_type=memory_type,
        subject=subject,
        content=content,
        source=source,
        confidence=confidence,
        status=status,
        expires_at=expires_at or None,
    )


@mcp.tool()
async def list_open_commitments(limit: int = 25) -> list[dict]:
    """List open commitment memory entries."""
    return memory_store.list_open_commitments(limit=limit)


@mcp.tool()
async def search_all(
    query: str,
    sources: list[str] | None = None,
    limit: int = 50,
    from_addr: str = "",
    before: str = "",
    after: str = "",
    has_attachment: bool = False,
    is_unread: bool = False,
) -> dict:
    """Search across all data sources (Gmail, iMessage, Notes, Reminders, Calendar).

    Advanced filters (all optional):
        from_addr: filter by sender (e.g. 'alice@example.com')
        before: ISO date upper bound (e.g. '2026-04-15')
        after: ISO date lower bound
        has_attachment: Gmail only — restrict to messages with attachments
        is_unread: Gmail only — restrict to unread messages
    """
    return await backend.search_all(
        query=query,
        sources=sources or ["all"],
        limit=limit,
        from_addr=from_addr,
        before=before,
        after=after,
        has_attachment=has_attachment,
        is_unread=is_unread,
    )


@mcp.tool()
async def list_gmail_labels(account: str = "") -> list[dict]:
    """List all Gmail labels for the account."""
    return await backend.list_gmail_labels(account=account)


@mcp.tool()
async def batch_modify_emails(
    msg_ids: list[str],
    add_label_ids: list[str] | None = None,
    remove_label_ids: list[str] | None = None,
    confirm: bool = False,
    account: str = "",
) -> dict:
    """Batch modify Gmail message labels. This tool is confirmation-gated."""
    _require_confirmation(confirm, "batch_modify_emails")
    return await backend.batch_modify_emails(
        msg_ids=msg_ids,
        add_labels=add_label_ids or [],
        remove_labels=remove_label_ids or [],
        account=account,
    )


@mcp.tool()
async def create_gmail_filter(
    from_filter: str = "",
    subject_filter: str = "",
    add_label_ids: list[str] | None = None,
    remove_label_ids: list[str] | None = None,
    confirm: bool = False,
    account: str = "",
) -> dict:
    """Create a Gmail filter. This tool is confirmation-gated."""
    _require_confirmation(confirm, "create_gmail_filter")
    return await backend.create_gmail_filter(
        from_filter=from_filter,
        subject_filter=subject_filter,
        add_labels=add_label_ids or [],
        remove_labels=remove_label_ids or [],
        account=account,
    )


@mcp.tool()
async def update_memory(
    entry_id: int,
    confirm: bool = False,
    subject: str | None = None,
    content: str | None = None,
    status: str | None = None,
    confidence: float | None = None,
) -> dict:
    """Update a memory entry. This tool is confirmation-gated."""
    _require_confirmation(confirm, "update_memory")
    kwargs = {}
    if subject is not None:
        kwargs["subject"] = subject
    if content is not None:
        kwargs["content"] = content
    if status is not None:
        kwargs["status"] = status
    if confidence is not None:
        kwargs["confidence"] = confidence
    return memory_store.update_entry(entry_id, **kwargs)


@mcp.tool()
async def close_commitment(entry_id: int, confirm: bool = False) -> dict:
    """Close a commitment (set status to 'closed'). This tool is confirmation-gated."""
    _require_confirmation(confirm, "close_commitment")
    return memory_store.close_commitment(entry_id)


@mcp.tool()
async def create_gmail_label(
    name: str, visibility: str = "labelShow", confirm: bool = False, account: str = ""
) -> dict:
    """Create a new Gmail label. This tool is confirmation-gated."""
    _require_confirmation(confirm, "create_gmail_label")
    return await backend.create_gmail_label(name=name, visibility=visibility, account=account)


@mcp.tool()
async def check_calendar_conflicts(start: str, end: str, account: str = "") -> dict:
    """Find calendar conflicts in a time range. Returns list of conflicting events."""
    return await backend.check_calendar_conflicts(start=start, end=end, account=account)


@mcp.tool()
async def extract_and_save_memory(
    text: str, source: str = "manual", auto_save: bool = False, confirm: bool = False
) -> dict:
    """Extract memory entities (people, projects, commitments) from text and optionally auto-save them. This tool is confirmation-gated if auto_save=True."""
    if auto_save:
        _require_confirmation(confirm, "extract_and_save_memory")
    return await backend.extract_memory(text=text, source=source, auto_save=auto_save)


_register_registry_tools(mcp, backend, readonly_only=False)


app = Starlette(
    routes=[
        Route("/health", endpoint=health),
        Mount("/mcp", app=mcp.streamable_http_app()),
    ],
    middleware=[Middleware(PublicAuthMiddleware)],
)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
