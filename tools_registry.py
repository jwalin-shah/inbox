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
from urllib.parse import quote

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


def _encode_path_value(value: Any) -> str:
    return quote(str(value), safe="")


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

        path_kwargs: dict[str, str] = {}
        query: dict[str, Any] = dict(tool.extra_query)
        body: dict[str, Any] = dict(tool.extra_body)

        for p in user_params:
            if p.name not in kwargs:
                continue
            value = kwargs[p.name]
            if p.location == "path":
                path_kwargs[p.name] = _encode_path_value(value)
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
    # ---------- Indexed inbox (read) ----------
    Tool(
        name="get_index_health",
        method="GET",
        path="/index/health",
        description="Get inbox index health, freshness, and sync-state diagnostics.",
        readonly=True,
    ),
    Tool(
        name="get_index_status",
        method="GET",
        path="/index/status",
        description="Get inbox index counts and sync-state overview.",
        readonly=True,
    ),
    Tool(
        name="list_index_view",
        method="GET",
        path="/index/views/{view_name}",
        description=(
            "List a compact indexed inbox view by name, such as recent, actionable, "
            "waiting-on, waiting-on-me, or waiting-on-others."
        ),
        readonly=True,
        params=[
            Param("view_name", str, _EMPTY, "path"),
            Param("limit", int, 20, "query"),
        ],
    ),
    Tool(
        name="list_needs_action",
        method="GET",
        path="/inbox/needs-action",
        description=(
            "List the compact cross-source needs-action rollup from indexed threads, "
            "tasks, and upcoming calendar events."
        ),
        readonly=True,
        params=[
            Param("workflow", str, "", "query"),
            Param("account", str, "", "query"),
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
        confirm=True,
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
        confirm=True,
        params=[
            Param("spreadsheet_id", str, _EMPTY, "path"),
            Param("range_", str, _EMPTY, "path"),
            Param("values", list, _EMPTY, "body"),
            Param("value_input", str, "USER_ENTERED", "body"),
            Param("account", str, "", "query"),
        ],
    ),
    # ---------- Gmail (remainder) ----------
    Tool(
        name="get_email_thread",
        method="GET",
        path="/messages/gmail/{message_id}",
        description="Fetch a Gmail thread by message id and optional thread id.",
        readonly=True,
        params=[
            Param("message_id", str, _EMPTY, "path"),
            Param("thread_id", str, "", "query"),
        ],
    ),
    Tool(
        name="archive_email_thread",
        method="POST",
        path="/messages/gmail/{message_id}/archive",
        description="Archive a Gmail thread by removing the INBOX label. Confirmation-gated.",
        confirm=True,
        params=[Param("message_id", str, _EMPTY, "path")],
    ),
    Tool(
        name="mark_email_read",
        method="POST",
        path="/messages/gmail/{message_id}/read",
        description="Mark a Gmail message as read. Confirmation-gated.",
        confirm=True,
        params=[Param("message_id", str, _EMPTY, "path")],
    ),
    Tool(
        name="list_gmail_labels",
        method="GET",
        path="/gmail/labels",
        description="List all Gmail labels for the account.",
        readonly=True,
        params=[Param("account", str, "", "query")],
    ),
    Tool(
        name="batch_modify_emails",
        method="POST",
        path="/gmail/batch-modify",
        description="Batch modify Gmail message labels. Confirmation-gated.",
        confirm=True,
        params=[
            Param("msg_ids", list, _EMPTY, "body"),
            Param("add_label_ids", list, None, "body"),
            Param("remove_label_ids", list, None, "body"),
            Param("account", str, "", "body"),
        ],
    ),
    Tool(
        name="create_gmail_filter",
        method="POST",
        path="/gmail/filters",
        description="Create a Gmail filter. Confirmation-gated.",
        confirm=True,
        params=[
            Param("from_filter", str, "", "body"),
            Param("subject_filter", str, "", "body"),
            Param("add_label_ids", list, None, "body"),
            Param("remove_label_ids", list, None, "body"),
            Param("account", str, "", "body"),
        ],
    ),
    Tool(
        name="create_gmail_label",
        method="POST",
        path="/gmail/labels",
        description="Create a new Gmail label. Confirmation-gated.",
        confirm=True,
        params=[
            Param("name", str, _EMPTY, "query"),
            Param("visibility", str, "labelShow", "query"),
            Param("account", str, "", "query"),
        ],
    ),
    # ---------- iMessage ----------
    Tool(
        name="list_message_threads",
        method="GET",
        path="/conversations",
        description="List recent iMessage conversations.",
        readonly=True,
        params=[Param("limit", int, 20, "query")],
        extra_query={"source": "imessage"},
    ),
    Tool(
        name="get_message_thread",
        method="GET",
        path="/messages/imessage/{conv_id}",
        description="Fetch the messages for an iMessage conversation.",
        readonly=True,
        params=[
            Param("conv_id", str, _EMPTY, "path"),
            Param("limit", int, 50, "query"),
        ],
    ),
    Tool(
        name="send_imessage",
        method="POST",
        path="/messages/send",
        description="Send an iMessage reply. Confirmation-gated.",
        confirm=True,
        params=[
            Param("conv_id", str, _EMPTY, "body"),
            Param("text", str, _EMPTY, "body"),
        ],
        extra_body={"source": "imessage"},
    ),
    # ---------- Notes ----------
    Tool(
        name="list_notes",
        method="GET",
        path="/notes",
        description="List recent Apple Notes.",
        readonly=True,
        params=[Param("limit", int, 20, "query")],
    ),
    Tool(
        name="get_note",
        method="GET",
        path="/notes/{note_id}",
        description="Fetch one Apple Note by id.",
        readonly=True,
        params=[Param("note_id", str, _EMPTY, "path")],
    ),
    # ---------- Reminders ----------
    Tool(
        name="list_reminders",
        method="GET",
        path="/reminders",
        description="List Apple Reminders.",
        readonly=True,
        params=[
            Param("list_name", str, "", "query"),
            Param("show_completed", bool, False, "query"),
            Param("limit", int, 100, "query"),
        ],
    ),
    Tool(
        name="create_reminder",
        method="POST",
        path="/reminders",
        description="Create a reminder. Confirmation-gated.",
        confirm=True,
        params=[
            Param("title", str, _EMPTY, "body"),
            Param("list_name", str, "Reminders", "body"),
            Param("due_date", str, "", "body"),
            Param("notes", str, "", "body"),
            Param("priority", int, 0, "body"),
            Param("flagged", bool, False, "body"),
        ],
    ),
    Tool(
        name="complete_reminder",
        method="POST",
        path="/reminders/{reminder_id}/complete",
        description="Complete a reminder. Confirmation-gated.",
        confirm=True,
        params=[Param("reminder_id", str, _EMPTY, "path")],
    ),
    Tool(
        name="uncomplete_reminder",
        method="POST",
        path="/reminders/{reminder_id}/uncomplete",
        description="Mark a reminder as incomplete. Confirmation-gated.",
        confirm=True,
        params=[Param("reminder_id", str, _EMPTY, "path")],
    ),
    # ---------- Google Tasks ----------
    Tool(
        name="list_task_lists",
        method="GET",
        path="/tasks/lists",
        description="List all Google Task lists.",
        readonly=True,
        params=[Param("account", str, "", "query")],
    ),
    Tool(
        name="list_tasks",
        method="GET",
        path="/tasks",
        description="List tasks in a Google Task list.",
        readonly=True,
        params=[
            Param("list_id", str, "@default", "query"),
            Param("show_completed", bool, False, "query"),
            Param("limit", int, 100, "query"),
            Param("account", str, "", "query"),
        ],
    ),
    Tool(
        name="create_task",
        method="POST",
        path="/tasks",
        description="Create a Google Task. Confirmation-gated.",
        confirm=True,
        params=[
            Param("title", str, _EMPTY, "body"),
            Param("list_id", str, "@default", "body"),
            Param("due", str, "", "body"),
            Param("notes", str, "", "body"),
            Param("account", str, "", "query"),
        ],
    ),
    Tool(
        name="complete_task",
        method="POST",
        path="/tasks/{task_id}/complete",
        description="Complete a Google Task. Confirmation-gated.",
        confirm=True,
        params=[
            Param("task_id", str, _EMPTY, "path"),
            Param("list_id", str, "@default", "query"),
            Param("account", str, "", "query"),
        ],
    ),
    # ---------- Capture Health ----------
    Tool(
        name="capture_status",
        method="GET",
        path="/capture/status",
        description="List read-only capture health records for every configured source.",
        readonly=True,
    ),
    Tool(
        name="capture_health",
        method="GET",
        path="/capture/health",
        description="Summarize whether Inbox can currently read every configured source.",
        readonly=True,
    ),
    Tool(
        name="egress_status",
        method="GET",
        path="/egress/status",
        description="Show local-only egress mode, allowlist, and audit coverage.",
        readonly=True,
    ),
    Tool(
        name="egress_audit",
        method="GET",
        path="/egress/audit",
        description="List recent audited direct outbound HTTP requests.",
        readonly=True,
        params=[Param("limit", int, 100, "query")],
    ),
    Tool(
        name="get_capability_inventory",
        method="GET",
        path="/capabilities",
        description=(
            "List Inbox modules, capabilities, risk categories, approval policy, "
            "and exposure metadata without calling providers."
        ),
        readonly=True,
    ),
    Tool(
        name="get_personal_data_gateway_status",
        method="GET",
        path="/gateway/status",
        description="Return the canonical Inbox personal-data gateway parity matrix, health, connector diagnostics, and secret-name-only gaps.",
        readonly=True,
    ),
    Tool(
        name="prove_personal_data_gateway_reads",
        method="POST",
        path="/gateway/read-proof",
        description="Read-only proof that Inbox can list Gmail, Calendar events, and Google Tasks with account attribution. Does not mutate provider data.",
        readonly=True,
        params=[
            Param("account", str, "", "body"),
            Param("gmail_query", str, "in:inbox", "body"),
            Param("gmail_limit", int, 5, "body"),
            Param("calendar_days", int, 7, "body"),
            Param("calendar_limit", int, 10, "body"),
            Param("task_list_id", str, "@default", "body"),
            Param("task_limit", int, 10, "body"),
        ],
    ),
    Tool(
        name="prove_multi_gmail_readiness",
        method="POST",
        path="/gateway/gmail-readiness",
        description="Dry-run proof that required Gmail accounts are loaded and readable, with inbox and unread count metadata only. Does not mutate provider data.",
        readonly=True,
        params=[
            Param(
                "accounts",
                list[str],
                ["jwalinshah13@gmail.com", "jshah1331@gmail.com"],
                "body",
            ),
        ],
    ),
    Tool(
        name="dry_run_ahmed_office_calendar_update",
        method="POST",
        path="/gateway/dry-run/ahmed-office-location-calendar-update",
        description=(
            "Dry-run finding Ahmed's office location in iMessage and proposing a "
            "calendar event location update. Does not mutate external data."
        ),
        readonly=True,
        params=[
            Param("event_id", str, "b9quemrk7mua74qfv1b707rik0", "body"),
            Param("calendar_id", str, "primary", "body"),
            Param("account", str, "", "body"),
            Param("query", str, "Ahmed office location", "body"),
            Param("limit", int, 10, "body"),
        ],
    ),
    Tool(
        name="update_task",
        method="PUT",
        path="/tasks/{task_id}",
        description="Update a Google Task. Confirmation-gated.",
        confirm=True,
        params=[
            Param("task_id", str, _EMPTY, "path"),
            Param("title", str, "", "body"),
            Param("due", str, "", "body"),
            Param("notes", str, "", "body"),
            Param("list_id", str, "@default", "query"),
            Param("account", str, "", "query"),
        ],
    ),
    Tool(
        name="delete_task",
        method="DELETE",
        path="/tasks/{task_id}",
        description="Delete a Google Task. Confirmation-gated.",
        confirm=True,
        params=[
            Param("task_id", str, _EMPTY, "path"),
            Param("list_id", str, "@default", "query"),
            Param("account", str, "", "query"),
        ],
    ),
    # ---------- Calendar + Maps ----------
    Tool(
        name="list_calendar_events",
        method="GET",
        path="/calendar/events",
        description="List calendar events for a date or ISO start/end range across loaded calendar accounts.",
        readonly=True,
        params=[
            Param("date", str, "", "query"),
            Param("start", str, "", "query"),
            Param("end", str, "", "query"),
        ],
    ),
    Tool(
        name="list_upcoming_calendar_events",
        method="GET",
        path="/calendar/upcoming",
        description="List upcoming calendar events, optionally scoped to a specific account.",
        readonly=True,
        params=[
            Param("days", int, 7, "query"),
            Param("limit", int, 50, "query"),
            Param("account", str, "", "query"),
        ],
    ),
    Tool(
        name="list_calendars",
        method="GET",
        path="/calendar/calendars",
        description="List Google calendars across loaded accounts.",
        readonly=True,
        params=[Param("account", str, "", "query")],
    ),
    Tool(
        name="get_calendar_event",
        method="GET",
        path="/calendar/events/{event_id}",
        description="Read one calendar event by event id, calendar id, and optional account.",
        readonly=True,
        params=[
            Param("event_id", str, _EMPTY, "path"),
            Param("calendar_id", str, "primary", "query"),
            Param("account", str, "", "query"),
        ],
    ),
    Tool(
        name="search_calendar_events",
        method="GET",
        path="/calendar/search",
        description="Search calendar events by text, attendee, location, time range, calendar, and account.",
        readonly=True,
        params=[
            Param("q", str, "", "query"),
            Param("attendee", str, "", "query"),
            Param("location", str, "", "query"),
            Param("start", str, "", "query"),
            Param("end", str, "", "query"),
            Param("calendar_id", str, "", "query"),
            Param("account", str, "", "query"),
            Param("limit", int, 50, "query"),
        ],
    ),
    Tool(
        name="create_calendar_event",
        method="POST",
        path="/calendar/events",
        description="Create a calendar event. Confirmation-gated.",
        confirm=True,
        params=[
            Param("summary", str, _EMPTY, "body"),
            Param("start", str, _EMPTY, "body"),
            Param("end", str, _EMPTY, "body"),
            Param("location", str, "", "body"),
            Param("description", str, "", "body"),
            Param("all_day", bool, False, "body"),
            Param("attendees", list, None, "body"),
            Param("account", str, "", "body"),
        ],
    ),
    Tool(
        name="update_calendar_event",
        method="PUT",
        path="/calendar/events/{event_id}",
        description="Update a calendar event. Confirmation-gated.",
        confirm=True,
        params=[
            Param("event_id", str, _EMPTY, "path"),
            Param("summary", str, "", "body"),
            Param("start", str, "", "body"),
            Param("end", str, "", "body"),
            Param("location", str, "", "body"),
            Param("description", str, "", "body"),
            Param("calendar_id", str, "primary", "query"),
            Param("account", str, "", "query"),
        ],
    ),
    Tool(
        name="departure_times",
        method="GET",
        path="/calendar/departure-times",
        description=(
            "Departure times for upcoming calendar events with locations. "
            "mode: driving|transit|walking|bicycling."
        ),
        readonly=True,
        params=[
            Param("origin", str, "", "query"),
            Param("mode", str, "driving", "query"),
            Param("buffer_minutes", int, 10, "query"),
            Param("lookahead_hours", int, 24, "query"),
        ],
    ),
    Tool(
        name="travel_time",
        method="GET",
        path="/maps/travel-time",
        description="Travel time between two locations via Google Maps.",
        readonly=True,
        params=[
            Param("origin", str, _EMPTY, "query"),
            Param("destination", str, _EMPTY, "query"),
            Param("mode", str, "driving", "query"),
        ],
    ),
    Tool(
        name="check_calendar_conflicts",
        method="POST",
        path="/calendar/conflicts",
        description="Find calendar conflicts in a time range. Returns list of conflicting events.",
        readonly=True,
        params=[
            Param("start", str, _EMPTY, "body"),
            Param("end", str, _EMPTY, "body"),
            Param("account", str, "", "body"),
        ],
    ),
    Tool(
        name="suggest_message_reply",
        method="POST",
        path="/autocomplete",
        description=(
            "Suggest a draft reply from message context using the local MLX model. "
            "Does not send. Returns null when the model is unavailable (non-macOS or not loaded)."
        ),
        readonly=True,
        params=[
            Param("messages", list, _EMPTY, "body"),
            Param("max_tokens", int, 64, "body"),
            Param("temperature", float, 0.5, "body"),
        ],
        extra_body={"mode": "reply", "draft": ""},
    ),
    # ---------- Search ----------
    Tool(
        name="search_all",
        method="POST",
        path="/search",
        description="Search across all sources (Gmail, iMessage, Notes, Reminders, Calendar).",
        readonly=True,
        params=[
            Param("q", str, _EMPTY, "body"),
            Param("sources", list, None, "body"),
            Param("limit", int, 50, "body"),
            Param("from_addr", str, "", "body"),
            Param("before", str, "", "body"),
            Param("after", str, "", "body"),
            Param("has_attachment", bool, False, "body"),
            Param("is_unread", bool, False, "body"),
        ],
    ),
    Tool(
        name="search_personal_data",
        method="POST",
        path="/search",
        description="Search local Inbox and explicit connector sources such as connector:imessage, connector:whatsapp, and connectors.",
        readonly=True,
        params=[
            Param("q", str, _EMPTY, "body"),
            Param("sources", list, None, "body"),
            Param("limit", int, 50, "body"),
            Param("from_addr", str, "", "body"),
            Param("before", str, "", "body"),
            Param("after", str, "", "body"),
            Param("has_attachment", bool, False, "body"),
            Param("is_unread", bool, False, "body"),
        ],
    ),
    Tool(
        name="get_connectors_status",
        method="GET",
        path="/connectors/status",
        description="Return local connector install/auth/storage/readiness diagnostics.",
        readonly=True,
    ),
    Tool(
        name="search_connectors",
        method="POST",
        path="/connectors/search",
        description="Search configured local connector CLIs directly.",
        readonly=True,
        params=[
            Param("q", str, _EMPTY, "body"),
            Param("sources", list, None, "body"),
            Param("limit", int, 20, "body"),
        ],
    ),
    Tool(
        name="plan_connector_sync",
        method="POST",
        path="/connectors/{connector_id}/sync",
        description="Return a connector sync dry-run plan. This MCP tool never requests sync execution.",
        readonly=True,
        params=[
            Param("connector_id", str, _EMPTY, "path"),
        ],
    ),
    # ---------- WhatsApp ----------
    Tool(
        name="whatsapp_contacts",
        method="GET",
        path="/whatsapp/contacts",
        description="List WhatsApp conversations via local OpenHuman export or macOS Accessibility.",
        readonly=True,
        params=[Param("limit", int, 20, "query")],
    ),
    Tool(
        name="whatsapp_messages",
        method="GET",
        path="/whatsapp/messages/{chat_name}",
        description="Fetch WhatsApp messages for a conversation.",
        readonly=True,
        params=[
            Param("chat_name", str, _EMPTY, "path"),
            Param("limit", int, 50, "query"),
        ],
    ),
    # ---------- LinkedIn ----------
    Tool(
        name="linkedin_contacts",
        method="GET",
        path="/linkedin/contacts",
        description="List LinkedIn conversations from the local OpenHuman export.",
        readonly=True,
        params=[Param("limit", int, 20, "query")],
    ),
    Tool(
        name="linkedin_messages",
        method="GET",
        path="/linkedin/messages/{thread_id}",
        description="Fetch LinkedIn messages for a conversation from the local OpenHuman export.",
        readonly=True,
        params=[
            Param("thread_id", str, _EMPTY, "path"),
            Param("limit", int, 50, "query"),
        ],
    ),
    # ---------- Scheduled messages ----------
    Tool(
        name="list_scheduled_messages",
        method="GET",
        path="/scheduled",
        description="List scheduled messages. Status: pending|sent|cancelled|failed.",
        readonly=True,
        params=[Param("status", str, "pending", "query")],
    ),
    Tool(
        name="schedule_message",
        method="POST",
        path="/scheduled",
        description=(
            "Schedule a message to send at a future time. source: gmail|imessage. "
            "send_at: ISO datetime. Confirmation-gated."
        ),
        confirm=True,
        params=[
            Param("source", str, _EMPTY, "body"),
            Param("conv_id", str, _EMPTY, "body"),
            Param("text", str, _EMPTY, "body"),
            Param("send_at", str, _EMPTY, "body"),
            Param("account", str, "", "body"),
        ],
    ),
    Tool(
        name="cancel_scheduled_message",
        method="DELETE",
        path="/scheduled/{msg_id}",
        description="Cancel a scheduled message by id. Confirmation-gated.",
        confirm=True,
        params=[Param("msg_id", int, _EMPTY, "path")],
    ),
    # ---------- Follow-ups ----------
    Tool(
        name="list_followups",
        method="GET",
        path="/followups",
        description="List follow-up reminders. Status: active|fired|cancelled|replied.",
        readonly=True,
        params=[Param("status", str, "active", "query")],
    ),
    Tool(
        name="create_followup",
        method="POST",
        path="/followups",
        description="Create a follow-up reminder for a conversation. Confirmation-gated.",
        confirm=True,
        params=[
            Param("source", str, _EMPTY, "body"),
            Param("conv_id", str, _EMPTY, "body"),
            Param("remind_after", str, _EMPTY, "body"),
            Param("reminder_title", str, _EMPTY, "body"),
            Param("thread_id", str, "", "body"),
            Param("reminder_list", str, "Reminders", "body"),
        ],
    ),
    Tool(
        name="cancel_followup",
        method="DELETE",
        path="/followups/{fid}",
        description="Cancel a follow-up reminder by id. Confirmation-gated.",
        confirm=True,
        params=[Param("fid", int, _EMPTY, "path")],
    ),
    # ---------- Task links ----------
    Tool(
        name="list_task_links",
        method="GET",
        path="/tasks/links",
        description="List task-message links.",
        readonly=True,
        params=[
            Param("message_id", str, "", "query"),
            Param("message_source", str, "", "query"),
            Param("task_id", str, "", "query"),
            Param("task_source", str, "", "query"),
        ],
    ),
    Tool(
        name="link_task_to_message",
        method="POST",
        path="/tasks/links",
        description="Link an existing task to a message. Confirmation-gated.",
        confirm=True,
        params=[
            Param("task_id", str, _EMPTY, "body"),
            Param("task_source", str, _EMPTY, "body"),
            Param("message_id", str, _EMPTY, "body"),
            Param("message_source", str, _EMPTY, "body"),
            Param("thread_id", str, "", "body"),
            Param("account", str, "", "body"),
        ],
    ),
    Tool(
        name="unlink_task",
        method="DELETE",
        path="/tasks/links/{link_id}",
        description="Delete a task-message link. Confirmation-gated.",
        confirm=True,
        params=[Param("link_id", int, _EMPTY, "path")],
    ),
    Tool(
        name="create_task_from_message",
        method="POST",
        path="/tasks/from-message",
        description=(
            "Create a task from a message and auto-link it. "
            "task_type: google_tasks|reminders. Confirmation-gated."
        ),
        confirm=True,
        params=[
            Param("message_id", str, _EMPTY, "body"),
            Param("message_source", str, _EMPTY, "body"),
            Param("title", str, _EMPTY, "body"),
            Param("task_type", str, "google_tasks", "body"),
            Param("list_id", str, "@default", "body"),
            Param("list_name", str, "Reminders", "body"),
            Param("notes", str, "", "body"),
            Param("thread_id", str, "", "body"),
            Param("account", str, "", "body"),
        ],
    ),
    # ---------- Memory extraction (HTTP) ----------
    Tool(
        name="extract_and_save_memory",
        method="POST",
        path="/memory/extract",
        description=(
            "Extract memory entities (people, projects, commitments) from text. "
            "If auto_save=True this is confirmation-gated (caller must set confirm=True)."
        ),
        confirm=True,
        params=[
            Param("text", str, _EMPTY, "query"),
            Param("source", str, "manual", "query"),
            Param("auto_save", bool, False, "query"),
        ],
    ),
    # ---------- Google Drive ----------
    Tool(
        name="list_drive_files",
        method="GET",
        path="/drive/files",
        description="List or search Google Drive files.",
        readonly=True,
        params=[
            Param("q", str, "", "query"),
            Param("shared", bool, False, "query"),
            Param("limit", int, 20, "query"),
            Param("account", str, "", "query"),
            Param("folder_id", str, "", "query"),
        ],
    ),
    Tool(
        name="get_drive_file",
        method="GET",
        path="/drive/files/{file_id}",
        description="Get Drive file metadata by id.",
        readonly=True,
        params=[
            Param("file_id", str, _EMPTY, "path"),
            Param("account", str, "", "query"),
        ],
    ),
    Tool(
        name="create_drive_folder",
        method="POST",
        path="/drive/folder",
        description="Create a Google Drive folder. Confirmation-gated.",
        confirm=True,
        params=[
            Param("name", str, _EMPTY, "body"),
            Param("parent_id", str, "", "body"),
            Param("account", str, "", "body"),
        ],
    ),
    Tool(
        name="delete_drive_file",
        method="DELETE",
        path="/drive/files/{file_id}",
        description="Trash a Drive file (recoverable). Confirmation-gated.",
        confirm=True,
        params=[
            Param("file_id", str, _EMPTY, "path"),
            Param("account", str, "", "query"),
        ],
    ),
    # ---------- Google Docs ----------
    Tool(
        name="list_docs",
        method="GET",
        path="/docs",
        description="List or search Google Docs across linked accounts.",
        readonly=True,
        params=[
            Param("q", str, "", "query"),
            Param("limit", int, 20, "query"),
            Param("account", str, "", "query"),
        ],
    ),
    Tool(
        name="create_doc",
        method="POST",
        path="/docs",
        description="Create a new Google Doc. Confirmation-gated.",
        confirm=True,
        params=[
            Param("title", str, _EMPTY, "body"),
            Param("account", str, "", "body"),
        ],
    ),
    Tool(
        name="get_doc",
        method="GET",
        path="/docs/{document_id}",
        description="Get Google Doc metadata.",
        readonly=True,
        params=[
            Param("document_id", str, _EMPTY, "path"),
            Param("account", str, "", "query"),
        ],
    ),
    Tool(
        name="delete_doc",
        method="DELETE",
        path="/docs/{document_id}",
        description="Trash a Google Doc. Confirmation-gated.",
        confirm=True,
        params=[
            Param("document_id", str, _EMPTY, "path"),
            Param("account", str, "", "query"),
        ],
    ),
    Tool(
        name="get_doc_text",
        method="GET",
        path="/docs/{document_id}/text",
        description="Get the plain text content of a Google Doc.",
        readonly=True,
        params=[
            Param("document_id", str, _EMPTY, "path"),
            Param("account", str, "", "query"),
        ],
    ),
    Tool(
        name="insert_doc_text",
        method="POST",
        path="/docs/{document_id}/text",
        description="Insert text into a Google Doc at the given index. Confirmation-gated.",
        confirm=True,
        params=[
            Param("document_id", str, _EMPTY, "path"),
            Param("text", str, _EMPTY, "body"),
            Param("index", int, 1, "body"),
            Param("account", str, "", "query"),
        ],
    ),
    # ---------- GitHub ----------
    Tool(
        name="list_github_notifications",
        method="GET",
        path="/github/notifications",
        description="List GitHub notifications. all=True includes read.",
        readonly=True,
        params=[Param("all", bool, False, "query")],
    ),
    Tool(
        name="mark_github_notification_read",
        method="POST",
        path="/github/notifications/{notification_id}/read",
        description="Mark a GitHub notification as read. Confirmation-gated.",
        confirm=True,
        params=[Param("notification_id", str, _EMPTY, "path")],
    ),
    Tool(
        name="mark_all_github_notifications_read",
        method="POST",
        path="/github/notifications/read-all",
        description="Mark all GitHub notifications as read. Confirmation-gated.",
        confirm=True,
    ),
    Tool(
        name="list_github_pulls",
        method="GET",
        path="/github/pulls",
        description="List GitHub pull requests requesting review from the authed user.",
        readonly=True,
        params=[Param("repo", str, "", "query")],
    ),
]
