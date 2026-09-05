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

import asyncio
from typing import Any

import ambient_notes
from lifeops.context import build_context
from lifeops.triage import merge_triage
from mcp_gateway import make_backend, make_memory_store
from services import ai_extract_memory
from src.multi_source_sync import build_unified_profiles
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

    @mcp.tool()
    async def life_what_needs_me(limit: int = 25) -> dict:
        """Return the small set of LifeOps commitments that currently need human judgment."""
        return await asyncio.to_thread(memory_store.what_needs_me, limit)

    @mcp.tool()
    async def life_triage(
        limit: int = 25, workflow: str = "", account: str = ""
    ) -> dict:
        """Return a read-only triage of Inbox sources plus LifeOps commitments."""
        local = await asyncio.to_thread(memory_store.what_needs_me, limit)
        try:
            inbox = await backend.inbox_now(
                limit=limit,
                workflow=workflow,
                account=account,
            )
        except Exception as exc:
            result = merge_triage(None, local, limit=limit)
            result["source_health"]["inbox"] = {
                "status": "unavailable",
                "read_only": True,
                "reasons": [f"inbox_read_failed:{type(exc).__name__}"],
            }
            return result
        return merge_triage(inbox, local, limit=limit)

    @mcp.tool()
    async def life_context(
        limit: int = 25,
        section_limit: int = 25,
        include_live_gmail: bool = False,
        calendar_days: int = 7,
    ) -> dict:
        """Return a read-only context tree, optionally scanning Gmail live."""
        if limit < 1 or section_limit < 1 or calendar_days < 1:
            raise ValueError("limit, section_limit, and calendar_days must be at least 1")
        calendar_days = min(calendar_days, 30)
        local = await asyncio.to_thread(memory_store.what_needs_me, limit)
        try:
            inbox = await backend.inbox_now(limit=limit, workflow="", account="")
            triage = merge_triage(inbox, local, limit=limit)
        except Exception as exc:
            triage = merge_triage(None, local, limit=limit)
            triage["source_health"]["inbox"] = {
                "status": "unavailable",
                "read_only": True,
                "reasons": [f"inbox_read_failed:{type(exc).__name__}"],
            }
        memory_entries = await asyncio.to_thread(
            memory_store.query_entries,
            query="",
            memory_type="",
            subject="",
            status="",
            limit=min(250, max(section_limit * 8, section_limit)),
        )
        life_commitments = await asyncio.to_thread(
            memory_store.list_open_life_commitments,
            section_limit,
        )
        people_profiles: list[Any] = []
        people_metadata: dict[str, Any] | None = None
        try:
            people_profiles, people_metadata = await asyncio.to_thread(
                build_unified_profiles,
                gmail_limit=min(300, max(section_limit * 6, section_limit)),
                include_gmail=include_live_gmail,
                limit=section_limit,
            )
        except Exception as exc:
            people_metadata = {
                "schema": "inbox.unified_contacts.v1",
                "available": False,
                "profile_count": 0,
                "cross_channel_profile_count": 0,
                "source_status": {
                    "unified_contacts": {
                        "available": False,
                        "detail": f"projection failed: {type(exc).__name__}",
                    }
                },
            }
        calendar_events: list[dict[str, Any]] = []
        calendar_metadata: dict[str, Any]
        try:
            calendar_events = await backend.list_upcoming_calendar_events(
                days=calendar_days,
                limit=min(200, max(section_limit * 4, section_limit)),
                account="",
            )
            calendar_metadata = {
                "available": True,
                "event_count": len(calendar_events),
                "lookahead_days": calendar_days,
                "detail": "Inbox upcoming calendar projection",
            }
        except Exception as exc:
            calendar_metadata = {
                "available": False,
                "event_count": 0,
                "lookahead_days": calendar_days,
                "detail": f"calendar read failed: {type(exc).__name__}",
            }
        contact_rows: list[dict[str, Any]] = []
        contact_metadata: dict[str, Any]
        try:
            contact_rows = await backend.list_contacts(limit=min(200, max(section_limit * 4, section_limit)))
            contact_metadata = {
                "available": True,
                "contact_count": len(contact_rows),
                "address_count": sum(
                    len(row.get("addresses") or [])
                    for row in contact_rows
                    if isinstance(row, dict) and isinstance(row.get("addresses") or [], list)
                ),
                "detail": "Inbox contacts projection",
            }
        except Exception as exc:
            contact_metadata = {
                "available": False,
                "contact_count": 0,
                "address_count": 0,
                "detail": f"contacts read failed: {type(exc).__name__}",
            }
        project_rows: list[dict[str, Any]] = []
        project_metadata: dict[str, Any]
        try:
            project_rows = await backend.list_project_records(
                limit=min(200, max(section_limit * 4, section_limit)),
            )
            project_metadata = {
                "available": True,
                "project_count": len(project_rows),
                "detail": "Inbox canonical project tracker projection",
            }
        except Exception as exc:
            project_metadata = {
                "available": False,
                "project_count": 0,
                "detail": f"project tracker read failed: {type(exc).__name__}",
            }
        queue_rows: list[dict[str, Any]] = []
        queue_metadata: dict[str, Any]
        try:
            queue_projection = await backend.master_ops_queues(
                limit=min(200, max(section_limit * 4, section_limit)),
            )
            queues = queue_projection.get("queues") if isinstance(queue_projection, dict) else {}
            email_queue = queues.get("email_actions") if isinstance(queues, dict) else {}
            queue_rows = list(email_queue.get("records") or []) if isinstance(email_queue, dict) else []
            queue_metadata = {
                "available": True,
                "email_action_count": len(queue_rows),
                "capture_count": len(
                    (queues.get("captures") or {}).get("records") or []
                )
                if isinstance(queues, dict) and isinstance(queues.get("captures"), dict)
                else 0,
                "task_mirror_count": len(
                    (queues.get("task_mirror") or {}).get("records") or []
                )
                if isinstance(queues, dict) and isinstance(queues.get("task_mirror"), dict)
                else 0,
                "detail": "Inbox Master Tracker queue projection",
            }
        except Exception as exc:
            queue_metadata = {
                "available": False,
                "email_action_count": 0,
                "capture_count": 0,
                "task_mirror_count": 0,
                "detail": f"Master Tracker queue read failed: {type(exc).__name__}",
            }
        lifeops_people_rows: list[dict[str, Any]] = []
        lifeops_action_rows: list[dict[str, Any]] = []
        lifeops_project_rows: list[dict[str, Any]] = []
        lifeops_metadata: dict[str, Any]
        try:
            lifeops_projection = await backend.lifeops_sheet_projection(
                limit=min(200, max(section_limit * 4, section_limit)),
            )
            tabs = lifeops_projection.get("tabs") if isinstance(lifeops_projection, dict) else {}
            people_tab = tabs.get("people") if isinstance(tabs, dict) else {}
            actions_tab = tabs.get("actions") if isinstance(tabs, dict) else {}
            projects_tab = tabs.get("projects") if isinstance(tabs, dict) else {}
            lifeops_people_rows = (
                list(people_tab.get("records") or []) if isinstance(people_tab, dict) else []
            )
            lifeops_action_rows = (
                list(actions_tab.get("records") or []) if isinstance(actions_tab, dict) else []
            )
            lifeops_project_rows = (
                list(projects_tab.get("records") or []) if isinstance(projects_tab, dict) else []
            )
            lifeops_metadata = {
                "available": True,
                "people_count": len(lifeops_people_rows),
                "action_count": len(lifeops_action_rows),
                "project_count": len(lifeops_project_rows),
                "detail": "Inbox LifeOps Persistent Context sheet projection",
            }
        except Exception as exc:
            lifeops_metadata = {
                "available": False,
                "people_count": 0,
                "action_count": 0,
                "project_count": 0,
                "detail": f"LifeOps sheet read failed: {type(exc).__name__}",
            }
        return build_context(
            memory_entries=memory_entries,
            triage=triage,
            people_profiles=people_profiles,
            people_metadata=people_metadata,
            calendar_events=calendar_events,
            calendar_metadata=calendar_metadata,
            contact_rows=contact_rows,
            contact_metadata=contact_metadata,
            project_rows=project_rows + lifeops_project_rows,
            project_metadata=project_metadata,
            queue_rows=queue_rows,
            queue_metadata=queue_metadata,
            lifeops_people_rows=lifeops_people_rows,
            lifeops_action_rows=lifeops_action_rows,
            lifeops_metadata=lifeops_metadata,
            life_commitments=life_commitments,
            limit=limit,
            section_limit=section_limit,
        )

    if not readonly:

        @mcp.tool()
        async def life_capture(
            text: str, source: str = "chatgpt", confirm: bool = False
        ) -> dict:
            """Durably capture raw LifeOps text, then extract and project commitments."""
            _require_confirmation(confirm, "life_capture")
            if not text.strip():
                raise ValueError("life_capture text must not be empty")
            return await asyncio.to_thread(
                memory_store.capture_and_process,
                text,
                source,
                ai_extract_memory,
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

        @mcp.tool()
        async def life_complete_commitment(
            commitment_id: str, confirm: bool = False
        ) -> dict:
            """Mark a LifeOps commitment DONE after explicit user confirmation."""
            _require_confirmation(confirm, "life_complete_commitment")
            return await asyncio.to_thread(
                memory_store.complete_life_commitment,
                commitment_id,
            )

    # --- Registry-driven tools ---
    if include_names is None:
        _register_registry_tools(mcp, backend, readonly_only=readonly)
    else:
        _register_registry_tools(
            mcp, backend, readonly_only=readonly, include_names=include_names
        )

    return mcp, backend, memory_store
