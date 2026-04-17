"""
Central tool registry for the Inbox MCP surface.

A `Tool` describes one capability: its MCP name, description, HTTP method+path
on the local inbox server, the parameter list (with types/defaults/location),
and flags controlling exposure (readonly, confirm-gated).

`register_all(mcp, backend, readonly_only=...)` iterates the registry and
attaches each tool to a FastMCP instance as an `@mcp.tool()` handler that
dispatches through the shared `InboxBackend._request`. One table drives both
the full and readonly MCP servers, so they cannot drift.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

ParamLocation = Literal["query", "body", "path"]
_EMPTY = inspect.Parameter.empty


@dataclass
class Param:
    name: str
    type: Any = str
    default: Any = _EMPTY
    location: ParamLocation = "query"


@dataclass
class Tool:
    name: str
    method: str
    path: str
    description: str
    params: list[Param] = field(default_factory=list)
    readonly: bool = False
    confirm: bool = False
    # Static extras baked into every call (e.g., `source="gmail"`).
    extra_query: dict[str, Any] = field(default_factory=dict)
    extra_body: dict[str, Any] = field(default_factory=dict)


def _build_handler(tool: Tool, backend: Any) -> Callable[..., Any]:
    user_params = list(tool.params)
    handler_params = list(user_params)
    if tool.confirm:
        handler_params.append(Param("confirm", bool, False))

    sig_params: list[inspect.Parameter] = []
    annotations: dict[str, Any] = {}
    for p in handler_params:
        default = p.default if p.default is not _EMPTY else _EMPTY
        sig_params.append(
            inspect.Parameter(
                p.name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=p.type,
            )
        )
        annotations[p.name] = p.type
    annotations["return"] = Any

    async def handler(**kwargs: Any) -> Any:
        if tool.confirm and not kwargs.pop("confirm", False):
            raise ValueError(
                f"{tool.name} requires explicit confirmation. "
                "Retry with confirm=True after user approval."
            )

        path_kwargs: dict[str, Any] = {}
        query: dict[str, Any] = dict(tool.extra_query)
        body: dict[str, Any] = dict(tool.extra_body)

        for p in user_params:
            if p.name not in kwargs:
                continue
            value = kwargs[p.name]
            if p.location == "path":
                path_kwargs[p.name] = value
            elif p.location == "query":
                query[p.name] = value
            elif p.location == "body":
                body[p.name] = value

        path = tool.path.format(**path_kwargs) if path_kwargs else tool.path
        return await backend._request(
            tool.method,
            path,
            params=query or None,
            json=body or None,
        )

    handler.__name__ = tool.name
    handler.__doc__ = tool.description
    handler.__signature__ = inspect.Signature(sig_params, return_annotation=Any)  # type: ignore[attr-defined]
    handler.__annotations__ = annotations
    return handler


def register_all(mcp: Any, backend: Any, *, readonly_only: bool) -> list[str]:
    """Register every applicable tool from TOOLS onto `mcp`. Returns names registered."""
    registered: list[str] = []
    for tool in TOOLS:
        if readonly_only and not tool.readonly:
            continue
        handler = _build_handler(tool, backend)
        mcp.tool()(handler)
        registered.append(tool.name)
    return registered


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    # ---------- Gmail (read) ----------
    Tool(
        name="list_inbox_threads",
        method="GET",
        path="/gmail/conversations",
        description="List recent Gmail inbox threads across linked accounts.",
        readonly=True,
        params=[
            Param("limit", int, 20, "query"),
            Param("account", str, "", "query"),
        ],
        extra_query={"label": "INBOX"},
    ),
    Tool(
        name="search_email",
        method="GET",
        path="/gmail/search",
        description="Search Gmail across linked accounts using Gmail query syntax.",
        readonly=True,
        params=[
            Param("q", str, _EMPTY, "query"),
            Param("limit", int, 20, "query"),
            Param("account", str, "", "query"),
            Param("label", str, "", "query"),
        ],
    ),
    # ---------- Gmail (write) ----------
    Tool(
        name="send_email_reply",
        method="POST",
        path="/messages/gmail/reply",
        description=(
            "Send a Gmail reply. Provide message_id (origin message) and body. "
            "Confirmation-gated: caller must set confirm=True."
        ),
        readonly=False,
        confirm=True,
        params=[
            Param("msg_id", str, _EMPTY, "body"),
            Param("body", str, _EMPTY, "body"),
            Param("thread_id", str, "", "body"),
            Param("to", str, "", "body"),
            Param("subject", str, "", "body"),
            Param("message_id_header", str, "", "body"),
            Param("account", str, "", "body"),
        ],
    ),
    # ---------- Google Sheets (read) ----------
    Tool(
        name="list_sheets",
        method="GET",
        path="/sheets",
        description="List or search Google Sheets across linked accounts.",
        readonly=True,
        params=[
            Param("q", str, "", "query"),
            Param("limit", int, 20, "query"),
            Param("account", str, "", "query"),
        ],
    ),
    Tool(
        name="read_sheet_values",
        method="GET",
        path="/sheets/{spreadsheet_id}/values/{range_}",
        description=(
            "Read cell values from a sheet range in A1 notation "
            "(e.g., 'Sheet1!A1:D100'). Returns {range, values}."
        ),
        readonly=True,
        params=[
            Param("spreadsheet_id", str, _EMPTY, "path"),
            Param("range_", str, _EMPTY, "path"),
            Param("account", str, "", "query"),
        ],
    ),
    # ---------- Google Sheets (write) ----------
    Tool(
        name="create_sheet",
        method="POST",
        path="/sheets",
        description=(
            "Create a new Google Sheet. `title` is required. Optional `sheets` is a "
            "list of tab names. Returns the new spreadsheet metadata including id."
        ),
        readonly=False,
        params=[
            Param("title", str, _EMPTY, "body"),
            Param("sheets", list, None, "body"),
            Param("account", str, "", "body"),
        ],
    ),
    Tool(
        name="append_sheet_rows",
        method="POST",
        path="/sheets/{spreadsheet_id}/values/{range_}/append",
        description=(
            "Append rows to a sheet range. `values` is a list of row lists "
            "(list[list[Any]]). `value_input` is USER_ENTERED or RAW."
        ),
        readonly=False,
        params=[
            Param("spreadsheet_id", str, _EMPTY, "path"),
            Param("range_", str, _EMPTY, "path"),
            Param("values", list, _EMPTY, "body"),
            Param("value_input", str, "USER_ENTERED", "body"),
            Param("account", str, "", "query"),
        ],
    ),
]
