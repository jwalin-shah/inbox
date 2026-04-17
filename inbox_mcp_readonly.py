"""
Read-only MCP surface for Inbox.

Use this for cloud agents or less-trusted clients that should be able to search
and read data but not mutate inbox state.
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
        "The 'mcp' package is required to run inbox_mcp_readonly.py. Install dependencies with: uv sync"
    ) from exc


MCP_TOKEN_ENV = "INBOX_MCP_TOKEN"  # nosec: B105 - env var name, not a hardcoded credential
MEMORY_DB_ENV = "INBOX_MEMORY_DB"
DEFAULT_HTTP_PORT = 8001


backend = InboxBackend()
memory_store = MemoryStore(
    Path(os.getenv(MEMORY_DB_ENV, "")).expanduser() if os.getenv(MEMORY_DB_ENV) else None
)
mcp = FastMCP(
    "Inbox Personal Assistant (Read Only)",
    stateless_http=True,
    json_response=True,
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
            "mode": "readonly",
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
async def list_message_threads(limit: int = 20) -> list[dict]:
    """List recent iMessage conversations."""
    return await backend.list_message_threads(limit=limit)


@mcp.tool()
async def get_message_thread(conv_id: str, limit: int = 50) -> list[dict]:
    """Fetch the messages for an iMessage conversation."""
    return await backend.get_message_thread(conv_id=conv_id, limit=limit)


@mcp.tool()
async def list_notes(limit: int = 20) -> list[dict]:
    """List recent Apple Notes."""
    return await backend.list_notes(limit=limit)


@mcp.tool()
async def get_note(note_id: str) -> dict:
    """Fetch one Apple Note by id."""
    return await backend.get_note(note_id)


@mcp.tool()
async def read_daily_note(date: str = "") -> dict:
    """Read today's daily note or a specific YYYY-MM-DD note if present."""
    path = ambient_notes._today_file() if not date else ambient_notes.VAULT_DIR / f"{date}.md"
    if not path.exists():
        return {"ok": False, "path": str(path), "content": ""}
    return {"ok": True, "path": str(path), "content": path.read_text(encoding="utf-8")}


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
async def departure_times(
    origin: str = "",
    mode: str = "driving",
    buffer_minutes: int = 10,
    lookahead_hours: int = 24,
) -> list[dict]:
    """Get departure times for upcoming calendar events with locations."""
    return await backend.departure_times(
        origin=origin, mode=mode, buffer_minutes=buffer_minutes, lookahead_hours=lookahead_hours
    )


@mcp.tool()
async def travel_time(origin: str, destination: str, mode: str = "driving") -> dict:
    """Get travel time between two locations via Google Maps."""
    return await backend.travel_time(origin=origin, destination=destination, mode=mode)


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
    """Search across all data sources (Gmail, iMessage, Notes, Reminders, Calendar)."""
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
async def check_calendar_conflicts(start: str, end: str, account: str = "") -> dict:
    """Find calendar conflicts in a time range. Returns list of conflicting events."""
    return await backend.check_calendar_conflicts(start=start, end=end, account=account)


_register_registry_tools(mcp, backend, readonly_only=True)


app = Starlette(
    routes=[
        Route("/health", endpoint=health),
        Mount("/mcp", app=mcp.streamable_http_app()),
    ],
    middleware=[Middleware(PublicAuthMiddleware)],
)


def main() -> None:
    import uvicorn

    port = int(os.getenv("INBOX_MCP_READONLY_PORT", str(DEFAULT_HTTP_PORT)))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
