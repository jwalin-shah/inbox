from __future__ import annotations

import base64
import json
import os
import re
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

INBOX_BASE_URL = os.environ.get("INBOX_SERVER_URL", "http://127.0.0.1:9849").rstrip("/")
INBOX_TOKEN = os.environ.get("INBOX_SERVER_TOKEN", "").strip()
MCP_PORT = int(os.environ.get("LIFEOPS_MCP_PORT", "9850"))

mcp = FastMCP(
    "LifeOps",
    instructions=(
        "LifeOps exposes evidence-backed personal context and bounded actions through the local Inbox server. "
        "Prefer reads before writes. Never infer a write succeeded: execute it, then verify the resulting state. "
        "Approval tools may only be used after the user explicitly confirms the exact pending action."
    ),
    host="127.0.0.1",
    port=MCP_PORT,
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
)


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    if not INBOX_TOKEN:
        raise RuntimeError("INBOX_SERVER_TOKEN is required")
    headers = {"Authorization": f"Bearer {INBOX_TOKEN}"}
    if extra:
        headers.update(extra)
    return headers


async def _request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> Any:
    async with httpx.AsyncClient(base_url=INBOX_BASE_URL, timeout=45.0) as client:
        response = await client.request(
            method,
            path,
            params=params,
            json=body,
            headers=_headers(extra_headers),
        )
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()


def _encode_search_id(query: str) -> str:
    token = base64.urlsafe_b64encode(query.encode("utf-8")).decode("ascii").rstrip("=")
    return f"search:{token}"


def _decode_search_id(item_id: str) -> str:
    if not item_id.startswith("search:"):
        raise ValueError("Unsupported item id")
    token = item_id.removeprefix("search:")
    token += "=" * (-len(token) % 4)
    return base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")


def _approval_path(path: str, params: dict[str, str] | None = None) -> str:
    clean = path
    if params:
        nonempty = {k: v for k, v in params.items() if v != ""}
        if nonempty:
            clean = f"{path}?{urlencode(nonempty)}"
    return clean


async def _request_approval(method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    return await _request(
        "POST",
        "/approvals/request",
        body={"method": method, "path": path, "body": body},
    )


def _allowed_execution(row: dict[str, Any]) -> bool:
    method = str(row.get("method", "")).upper()
    path = str(row.get("path", ""))
    path_only = path.split("?", 1)[0]
    if method == "POST" and path_only == "/tasks":
        return True
    if method == "PUT" and re.fullmatch(r"/calendar/events/[^/]+", path_only):
        return True
    return False


@mcp.tool(
    title="Search LifeOps sources",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def search(query: str) -> str:
    """Search Inbox-backed personal sources. Use this for company-knowledge/deep-research style discovery."""
    await _request("POST", "/search", body={"q": query, "sources": ["all"], "limit": 50})
    item_id = _encode_search_id(query)
    payload = {
        "results": [
            {
                "id": item_id,
                "title": f"LifeOps search: {query}",
                "url": f"lifeops://{item_id}",
            }
        ]
    }
    return json.dumps(payload, ensure_ascii=False)


@mcp.tool(
    title="Fetch LifeOps search evidence",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def fetch(item_id: str) -> str:
    """Fetch the evidence bundle for a LifeOps search result id returned by search."""
    query = _decode_search_id(item_id)
    data = await _request("POST", "/search", body={"q": query, "sources": ["all"], "limit": 50})
    payload = {
        "id": item_id,
        "title": f"LifeOps search: {query}",
        "text": json.dumps(data, ensure_ascii=False),
        "url": f"lifeops://{item_id}",
        "metadata": {"query": query, "source": "Inbox /search"},
    }
    return json.dumps(payload, ensure_ascii=False)


@mcp.tool(
    title="Check LifeOps source health",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def source_health() -> dict[str, Any]:
    """Check which local and cloud sources are configured, readable, writable, stale, or blocked."""
    providers, capture, egress = await _parallel_reads()
    return {"providers": providers, "capture": capture, "egress": egress}


async def _parallel_reads() -> tuple[Any, Any, Any]:
    import asyncio

    return tuple(
        await asyncio.gather(
            _request("GET", "/status/providers"),
            _request("GET", "/capture/health"),
            _request("GET", "/egress/status"),
        )
    )  # type: ignore[return-value]


@mcp.tool(
    title="Get calendar events",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def calendar_events(date: str) -> list[dict[str, Any]]:
    """Get calendar events for an ISO date such as 2026-08-24 before reasoning about commitments or travel."""
    data = await _request("GET", "/calendar/events", params={"date": date})
    return list(data or [])


@mcp.tool(
    title="Calculate departure times",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
)
async def departure_times(
    origin: str = "",
    mode: Literal["driving", "walking", "bicycling", "transit"] = "driving",
    buffer_minutes: int = 10,
    lookahead_hours: int = 24,
) -> list[dict[str, Any]]:
    """Calculate traffic-aware leave times for upcoming calendar events that have locations."""
    params: dict[str, Any] = {
        "mode": mode,
        "buffer_minutes": max(0, min(buffer_minutes, 120)),
        "lookahead_hours": max(1, min(lookahead_hours, 72)),
    }
    if origin:
        params["origin"] = origin
    data = await _request("GET", "/calendar/departure-times", params=params)
    return list(data or [])


@mcp.tool(
    title="Calculate travel time",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
)
async def travel_time(
    origin: str,
    destination: str,
    mode: Literal["driving", "walking", "bicycling", "transit"] = "driving",
) -> dict[str, Any]:
    """Calculate current travel time between two places using Inbox's maps service."""
    data = await _request(
        "GET",
        "/maps/travel-time",
        params={"origin": origin, "destination": destination, "mode": mode},
    )
    return dict(data or {})


@mcp.tool(
    title="List Google Tasks",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
async def tasks(
    list_id: str = "@default",
    show_completed: bool = False,
    limit: int = 50,
    account: str = "",
) -> list[dict[str, Any]]:
    """Read current Google Tasks before proposing task changes or checking whether work already exists."""
    params: dict[str, Any] = {
        "list_id": list_id,
        "show_completed": show_completed,
        "limit": max(1, min(limit, 200)),
    }
    if account:
        params["account"] = account
    data = await _request("GET", "/tasks", params=params)
    return list(data or [])


@mcp.tool(
    title="Propose Google Task creation",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def propose_create_task(
    title: str,
    due: str = "",
    notes: str = "",
    list_id: str = "@default",
    account: str = "",
) -> dict[str, Any]:
    """Create a pending, payload-bound approval request for a new Google Task. This does not create the task yet."""
    params = {"account": account} if account else None
    path = _approval_path("/tasks", params)
    body = {"title": title, "list_id": list_id, "due": due, "notes": notes}
    return await _request_approval("POST", path, body)


@mcp.tool(
    title="Propose calendar event update",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def propose_update_calendar_event(
    event_id: str,
    calendar_id: str = "primary",
    account: str = "",
    summary: str | None = None,
    start: str | None = None,
    end: str | None = None,
    location: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Create a pending, payload-bound approval request to update an existing calendar event. No update happens yet."""
    body = {
        key: value
        for key, value in {
            "summary": summary,
            "start": start,
            "end": end,
            "location": location,
            "description": description,
        }.items()
        if value is not None
    }
    if not body:
        raise ValueError("At least one field must be supplied")
    path = _approval_path(
        f"/calendar/events/{event_id}",
        {"calendar_id": calendar_id, "account": account},
    )
    return await _request_approval("PUT", path, body)


@mcp.tool(
    title="Approve pending LifeOps action",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def approve_pending_action(request_id: str) -> dict[str, Any]:
    """Approve a pending LifeOps action. Only use after the user explicitly confirms the exact pending action in this conversation."""
    row = await _request("GET", f"/approvals/{request_id}")
    if not isinstance(row, dict) or not _allowed_execution(row):
        raise ValueError("This MCP adapter only approves task creation and calendar updates")
    if row.get("state") != "pending":
        return row
    return await _request(
        "POST",
        f"/approvals/{request_id}/decide",
        body={"approve": True, "decided_by": "chatgpt-business-lifeops"},
    )


@mcp.tool(
    title="Execute approved LifeOps action",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def execute_approved_action(request_id: str) -> dict[str, Any]:
    """Execute exactly the already-approved task/calendar action bound to request_id, then return the provider result."""
    row = await _request("GET", f"/approvals/{request_id}")
    if not isinstance(row, dict) or not _allowed_execution(row):
        raise ValueError("This MCP adapter only executes task creation and calendar updates")
    if row.get("state") != "approved" or not row.get("lease_id"):
        raise ValueError("Action is not approved or has no approval lease")

    body = json.loads(row.get("body_json") or "{}")
    method = str(row["method"]).upper()
    path = str(row["path"])
    # Keep the exact path/query that was approved. httpx accepts the query in the path string.
    result = await _request(
        method,
        path,
        body=body,
        extra_headers={"X-Inbox-Approval-Lease": str(row["lease_id"])},
    )
    return {"request_id": request_id, "executed": True, "result": result}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
