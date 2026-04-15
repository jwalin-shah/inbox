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
async def list_inbox_threads(limit: int = 20, account: str = "") -> list[dict]:
    """List recent Gmail inbox threads across linked accounts."""
    return await backend.list_inbox_threads(limit=limit, account=account)


@mcp.tool()
async def search_email(
    query: str, limit: int = 20, account: str = "", label: str = ""
) -> list[dict]:
    """Search Gmail across linked accounts using Gmail query syntax."""
    return await backend.search_email(query=query, limit=limit, account=account, label=label)


@mcp.tool()
async def get_email_thread(message_id: str, thread_id: str = "") -> list[dict]:
    """Fetch a Gmail thread by message id and optional thread id."""
    return await backend.get_email_thread(message_id=message_id, thread_id=thread_id)


@mcp.tool()
async def send_email_reply(
    message_id: str,
    body: str,
    confirm: bool = False,
    thread_id: str = "",
    to: str = "",
    subject: str = "",
    message_id_header: str = "",
    account: str = "",
) -> dict:
    """Send a Gmail reply. This tool is confirmation-gated."""
    _require_confirmation(confirm, "send_email_reply")
    return await backend.send_email_reply(
        msg_id=message_id,
        body=body,
        thread_id=thread_id,
        to=to,
        subject=subject,
        message_id_header=message_id_header,
        account=account,
    )


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
) -> dict:
    """Create a reminder. This tool is confirmation-gated."""
    _require_confirmation(confirm, "create_reminder")
    return await backend.create_reminder(
        title=title,
        list_name=list_name,
        due_date=due_date,
        notes=notes,
    )


@mcp.tool()
async def complete_reminder(reminder_id: str, confirm: bool = False) -> dict:
    """Complete a reminder. This tool is confirmation-gated."""
    _require_confirmation(confirm, "complete_reminder")
    return await backend.complete_reminder(reminder_id)


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
async def search_all(query: str, sources: list[str] | None = None, limit: int = 50) -> dict:
    """Search across all data sources (Gmail, iMessage, Notes, Reminders, Calendar)."""
    return await backend.search_all(query=query, sources=sources or ["all"], limit=limit)


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
