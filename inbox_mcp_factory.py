"""
Inbox MCP factory — transport-aware FastMCP construction.

This module is the single source of truth for which tools are registered and
how the MCP instance is configured.  Both HTTP and stdio entry points call
build_mcp() so that:

  • HTTP-only FastMCP settings (stateless_http, json_response) are NOT applied
    to stdio-mode instances.
  • Hand-written ambient/memory tools are registered once here, not duplicated
    across mcp_server.py and inbox_mcp_readonly.py.

Usage
-----
  mcp, backend, memory_store = build_mcp(readonly=False, for_http=False)
  mcp.run(transport="stdio")

  mcp, backend, memory_store = build_mcp(readonly=False, for_http=True)
  app = make_mcp_app(mcp=mcp, health_endpoint=health)
"""

from __future__ import annotations

from typing import Any

import ambient_notes
from mcp_gateway import make_backend, make_memory_store
from tools_registry import register_all as _register_registry_tools

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "The 'mcp' package is required. Install with: uv sync"
    ) from exc


def _require_confirmation(confirm: bool, action: str) -> None:
    if not confirm:
        raise ValueError(
            f"{action} requires explicit confirmation. "
            "Retry with confirm=True after user approval."
        )


async def read_daily_note(date: str = "") -> dict:
    """Read today's daily note or a specific YYYY-MM-DD note if present."""
    path = (
        ambient_notes._today_file()
        if not date
        else ambient_notes.DAILY_DIR / f"{date}.md"
    )
    if not path.exists():
        return {"ok": False, "path": str(path), "content": ""}
    return {"ok": True, "path": str(path), "content": path.read_text(encoding="utf-8")}


def build_mcp(
    *,
    readonly: bool = False,
    for_http: bool = False,
    include_names: set[str] | None = None,
) -> tuple[Any, Any, Any]:
    """
    Build a configured FastMCP instance for the inbox MCP surface.

    Parameters
    ----------
    readonly:
        Expose only the read-only tool surface.  Mutation and confirm-gated
        write tools are not registered.
    for_http:
        Enable FastMCP HTTP transport optimisations (stateless_http,
        json_response).  Set False for stdio to avoid applying HTTP-specific
        settings to the wrong transport.

    Returns
    -------
    (mcp, backend, memory_store)
        The FastMCP instance and its backing objects, needed by callers that
        also build a health endpoint or Starlette app.
    """
    backend = make_backend()
    memory_store = make_memory_store()

    name = "Inbox Personal Assistant" + (" (Read Only)" if readonly else "")
    mcp = FastMCP(name, stateless_http=for_http, json_response=for_http)

    # --- Ambient notes ---

    @mcp.tool()
    async def read_daily_note(date: str = "") -> dict:
        """Read today's daily note or a specific YYYY-MM-DD note if present."""
        path = (
            ambient_notes._today_file()
            if not date
            else ambient_notes.DAILY_DIR / f"{date}.md"
        )
        if not path.exists():
            return {"ok": False, "path": str(path), "content": ""}
        return {"ok": True, "path": str(path), "content": path.read_text(encoding="utf-8")}

    if not readonly:

        @mcp.tool()
        async def append_daily_note(content: str, confirm: bool = False) -> dict:
            """Append content to today's daily note in the Obsidian vault."""
            _require_confirmation(confirm, "append_daily_note")
            ambient_notes.append_to_daily(content)
            return {"ok": True, "date": str(ambient_notes._today_file().stem)}

    # --- Memory ---

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

    if not readonly:

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
            kwargs: dict[str, Any] = {}
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

    # --- Registry-driven tools ---
    if include_names is None:
        _register_registry_tools(mcp, backend, readonly_only=readonly)
    else:
        _register_registry_tools(
            mcp, backend, readonly_only=readonly, include_names=include_names
        )

    return mcp, backend, memory_store
