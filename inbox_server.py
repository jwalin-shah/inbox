"""
Inbox API server — local REST API for iMessage, Gmail, Calendar, Notes, Reminders.
Run: uv run python inbox_server.py
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import shutil
import sqlite3
from collections.abc import Callable, Iterable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from secrets import compare_digest, token_urlsafe
from typing import Any, Literal
from urllib.parse import parse_qs, parse_qsl, urlsplit

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel, StrictBool

import ambient_notes
import egress_audit
import google_account_resolution as _gacct
from approval_store import ApprovalStore
from capability_inventory import build_capability_inventory
from capture_health import CaptureHealthRecord, CaptureHealthStore, capture_summary, utc_now_iso
from connector_registry import (
    connector_sync_plan,
    connectors_status,
    merge_connector_search_results,
    partition_search_sources,
    search_connectors,
)
from event_store import CaptureEvent, EventStore, EventStoreConflict, EventStoreValidationError
from gmail_triage import (
    KIND_PREFIX as _KIND_PREFIX,
)
from gmail_triage import (
    WORKFLOW_DISPLAY as _WORKFLOW_DISPLAY,
)
from gmail_triage import (
    GmailThreadSummaryOut,
    ThreadBriefOut,
)
from gmail_triage import (
    classify_workflow as _classify_workflow,
)
from gmail_triage import (
    contact_to_thread_summary as _contact_to_thread_summary,
)
from gmail_triage import (
    extract_action_items as _extract_action_items,
)
from gmail_triage import (
    extract_rich_data as _extract_rich_data,
)
from gmail_triage import (
    indexed_thread_to_summary as _indexed_thread_to_summary,
)
from gmail_triage import (
    rank_thread as _rank_thread,
)
from gmail_triage import (
    thread_summary_to_out as _thread_summary_to_out,
)
from memory_store import MemoryStore
from message_index_store import MessageIndexStore
from message_sync import bootstrap as index_bootstrap_sync
from message_sync import incremental as index_incremental_sync
from scheduler import SchedulerStore
from service_models import ApprovalGateDecision, ApprovalLease
from services import (
    IMSG_DB,
    MLX_LARGE_MODEL,
    NOTES_DB,
    REMINDERS_DIR,
    AmbientService,
    CalendarEvent,
    Contact,
    DictationService,
    DriveFile,
    GitHubNotification,
    GoogleTask,
    Msg,
    Note,
    Reminder,
    SheetTab,
    Spreadsheet,
    _openhuman_linkedin_db_path,
    _openhuman_whatsapp_db_path,
    add_google_account,
    ai_briefing,
    ai_extract_actions,
    ai_extract_memory,
    ai_summarize,
    ai_triage,
    ambient_available,
    calendar_create_event,
    calendar_delete_event,
    calendar_event_to_reminder,
    calendar_events,
    calendar_find_conflicts,
    calendar_find_free_slots,
    calendar_freebusy,
    calendar_get_event,
    calendar_get_recurring_instances,
    calendar_list_calendars,
    calendar_modify_attendees,
    calendar_rsvp_event,
    calendar_search_events,
    calendar_update_event,
    close_sqlite_connections,
    contacts_profile,
    contacts_search,
    departure_times_for_events,
    docs_create,
    docs_delete,
    docs_export,
    docs_get,
    docs_get_text,
    docs_insert_text,
    docs_list,
    drive_create_folder,
    drive_delete,
    drive_download,
    drive_files,
    drive_get,
    drive_upload,
    gemini_categorize,
    gemini_digest,
    gemini_extract_action_items,
    gemini_smart_reply,
    gemini_summarize,
    get_current_location,
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
    gmail_filter_audit,
    gmail_inbox_counts,
    gmail_label_create,
    gmail_labels,
    gmail_mark_read,
    gmail_mark_unread,
    gmail_reply,
    gmail_search,
    gmail_send,
    gmail_star,
    gmail_thread,
    gmail_thread_summary,
    gmail_unstar,
    gmail_unsubscribe,
    google_auth_all,
    google_auth_diagnostics,
    imsg_contacts,
    imsg_links,
    imsg_messages,
    imsg_send,
    imsg_thread,
    init_contacts,
    linkedin_contacts,
    linkedin_thread,
    llm_large_is_loaded,
    llm_large_is_loading,
    load_favorites,
    load_notification_config,
    load_voice_config,
    maps_travel_time,
    note_body,
    notes_list,
    parse_quick_event,
    reauth_google_account,
    reminder_by_id,
    reminder_complete,
    reminder_create,
    reminder_delete,
    reminder_edit,
    reminder_uncomplete,
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
    task_complete,
    task_create,
    task_delete,
    task_update,
    tasks_list,
    tasks_lists,
    whatsapp_check_accessibility,
    whatsapp_contacts,
    whatsapp_contacts_all,
    whatsapp_launch,
    whatsapp_scroll_sidebar,
    whatsapp_send,
    whatsapp_thread,
    whatsapp_thread_full,
)
from services import (
    autocomplete as services_autocomplete,
)

# Test-only: keeps _extract_* / _rank_thread imports live for ruff.
_gmail_triage_reexports = (
    _extract_action_items,
    _extract_rich_data,
    _rank_thread,
)

PORT = 9849
AUTH_TOKEN_ENV = "INBOX_SERVER_TOKEN"  # nosec: B105 - env var name, not a hardcoded credential
AUTH_BYPASS_ENV = "INBOX_SERVER_ALLOW_UNAUTHENTICATED"
AUTH_BYPASS_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
APPROVAL_LEASE_HEADER = "x-inbox-approval-lease"
APPROVAL_LEASE_ENV = "INBOX_APPROVAL_LEASE"
APPROVAL_TEST_LEASE = "test-local-approval-lease"
APPROVAL_GUARDED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
APPROVAL_LEASE_TTL_SECONDS = 300
GOOGLE_SERVICE_SET = tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]


@dataclass(frozen=True)
class ApprovalRouteRule:
    method: str
    pattern: re.Pattern[str]
    provider: str
    operation: str
    approval_class: str
    executor: str


_approval_lease_lock = asyncio.Lock()
_approval_leases: dict[str, ApprovalLease] = {}


def _route_rule(
    method: str,
    path_pattern: str,
    provider: str,
    operation: str,
    executor: str,
    approval_class: str = "external_write",
) -> ApprovalRouteRule:
    return ApprovalRouteRule(
        method=method,
        pattern=re.compile(path_pattern),
        provider=provider,
        operation=operation,
        approval_class=approval_class,
        executor=executor,
    )


APPROVAL_ROUTE_RULES: tuple[ApprovalRouteRule, ...] = (
    _route_rule(
        "POST", r"^/messages/send$", "imessage_gmail", "send_message", "inbox.messages.send"
    ),
    _route_rule(
        "POST", r"^/imessage/send$", "imessage_gmail", "send_message", "inbox.messages.send"
    ),
    _route_rule("POST", r"^/messages/compose$", "gmail", "compose_send", "inbox.gmail.send_email"),
    _route_rule("POST", r"^/messages/gmail/reply$", "gmail", "reply", "inbox.gmail.reply"),
    _route_rule(
        "POST",
        r"^/messages/gmail/[^/]+/(archive|delete|unsubscribe|star|unstar|read|unread)$",
        "gmail",
        "message_modify",
        "inbox.gmail.modify",
        "external_destructive",
    ),
    _route_rule(
        "POST",
        r"^/messages/gmail/bulk-unsubscribe$",
        "gmail",
        "bulk_unsubscribe",
        "inbox.gmail.unsubscribe",
        "external_destructive",
    ),
    _route_rule(
        "POST",
        r"^/gmail/(batch-modify|filters|labels)$",
        "gmail",
        "gmail_modify",
        "inbox.gmail.modify",
        "external_write",
    ),
    _route_rule(
        "POST",
        r"^/calendar/events(/quick)?$",
        "calendar",
        "create_event",
        "inbox.calendar.create_event",
    ),
    _route_rule(
        "PUT",
        r"^/calendar/events/[^/]+$",
        "calendar",
        "update_event",
        "inbox.calendar.update_event",
    ),
    _route_rule(
        "DELETE",
        r"^/calendar/events/[^/]+$",
        "calendar",
        "delete_event",
        "inbox.calendar.delete_event",
        "external_destructive",
    ),
    _route_rule(
        "POST",
        r"^/calendar/events/[^/]+/(rsvp|create-reminder)$",
        "calendar",
        "event_action",
        "inbox.calendar.event_action",
    ),
    _route_rule(
        "PATCH",
        r"^/calendar/events/[^/]+/attendees$",
        "calendar",
        "modify_attendees",
        "inbox.calendar.modify_attendees",
    ),
    _route_rule(
        "PUT",
        r"^/calendar/events/[^/]+/reminders$",
        "calendar",
        "set_reminders",
        "inbox.calendar.update_event",
    ),
    _route_rule(
        "POST",
        r"^/calendar/workflow-event$",
        "calendar",
        "create_workflow_event",
        "inbox.calendar.create_event",
    ),
    _route_rule(
        "POST",
        r"^/reminders(/[^/]+/(complete|uncomplete))?$",
        "apple_reminders",
        "write_reminder",
        "inbox.reminders.write",
    ),
    _route_rule(
        "PUT", r"^/reminders/[^/]+$", "apple_reminders", "edit_reminder", "inbox.reminders.write"
    ),
    _route_rule(
        "DELETE",
        r"^/reminders/[^/]+$",
        "apple_reminders",
        "delete_reminder",
        "inbox.reminders.delete",
        "external_destructive",
    ),
    _route_rule(
        "POST",
        r"^/tasks(/[^/]+/complete|/from-message|/links)?$",
        "google_tasks",
        "write_task",
        "inbox.tasks.write",
    ),
    _route_rule("PUT", r"^/tasks/[^/]+$", "google_tasks", "update_task", "inbox.tasks.write"),
    _route_rule(
        "DELETE",
        r"^/tasks(/links)?/[^/]+$",
        "google_tasks",
        "delete_task",
        "inbox.tasks.delete",
        "external_destructive",
    ),
    _route_rule(
        "POST", r"^/scheduled$", "scheduler", "create_scheduled_message", "inbox.scheduler.write"
    ),
    _route_rule(
        "DELETE",
        r"^/scheduled/[^/]+$",
        "scheduler",
        "delete_scheduled_message",
        "inbox.scheduler.delete",
        "external_destructive",
    ),
    _route_rule("POST", r"^/followups$", "scheduler", "create_followup", "inbox.followups.write"),
    _route_rule(
        "DELETE",
        r"^/followups/[^/]+$",
        "scheduler",
        "delete_followup",
        "inbox.followups.delete",
        "external_destructive",
    ),
    _route_rule(
        "POST",
        r"^/whatsapp/(launch|send|scroll)$",
        "whatsapp",
        "whatsapp_action",
        "inbox.whatsapp.write",
    ),
    _route_rule(
        "POST",
        r"^/github/notifications(/[^/]+/read|/read-all)$",
        "github",
        "notification_modify",
        "inbox.github.notifications",
    ),
    _route_rule(
        "POST",
        r"^/drive/(upload|folder|workflow-folder)$",
        "drive",
        "drive_write",
        "inbox.drive.write",
    ),
    _route_rule(
        "DELETE",
        r"^/drive/files/[^/]+$",
        "drive",
        "drive_delete",
        "inbox.drive.delete",
        "external_destructive",
    ),
    _route_rule(
        "POST",
        r"^/sheets(/workflow-sheet|/[^/]+/(values/[^/]+/append|values/batch-update|tabs|tabs/[^/]+/copy|format))?$",
        "sheets",
        "sheets_write",
        "inbox.sheets.write",
    ),
    _route_rule(
        "PUT",
        r"^/sheets/[^/]+/values/[^/]+$",
        "sheets",
        "update_values",
        "inbox.sheets.update_cells",
    ),
    _route_rule(
        "PATCH", r"^/sheets/[^/]+/tabs/[^/]+$", "sheets", "rename_tab", "inbox.sheets.write"
    ),
    _route_rule(
        "DELETE",
        r"^/sheets/[^/]+(/values/[^/]+|/tabs/[^/]+)?$",
        "sheets",
        "sheets_delete",
        "inbox.sheets.delete",
        "external_destructive",
    ),
    _route_rule(
        "POST", r"^/docs(/workflow-doc|/[^/]+/text)?$", "docs", "docs_write", "inbox.docs.write"
    ),
    _route_rule(
        "DELETE",
        r"^/docs/[^/]+$",
        "docs",
        "docs_delete",
        "inbox.docs.delete",
        "external_destructive",
    ),
    _route_rule(
        "POST", r"^/connectors/[^/]+/sync$", "connector", "execute_sync", "inbox.connectors.sync"
    ),
    # /accounts/add and /accounts/reauth are intentionally NOT approval-gated here.
    # inbox_client.add_account()/reauth_account() never mint or attach an
    # x-inbox-approval-lease header, so this rule made the TUI's own Ctrl+A flow
    # (its only way to connect a Google account) unconditionally fail with
    # missing_per_action_approval_lease. Google's own browser OAuth consent screen
    # is the real human-approval step for granting account access; gating the
    # local callback a second time with an unmintable lease was a dead-end, not
    # defense in depth.
)


def _approval_rule_for_request(method: str, path: str) -> ApprovalRouteRule | None:
    if method not in APPROVAL_GUARDED_METHODS:
        return None

    for rule in APPROVAL_ROUTE_RULES:
        if method == rule.method and rule.pattern.match(path):
            return rule
    return None


def _local_approval_lease() -> str:
    if os.getenv("INBOX_TEST_MODE", "").lower() in AUTH_BYPASS_TRUE_VALUES:
        return APPROVAL_TEST_LEASE
    return os.getenv(APPROVAL_LEASE_ENV, "")


def _canonical_payload_hash(body: bytes) -> str:
    if not body:
        canonical = b"{}"
    else:
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            canonical = body
        else:
            canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _canonical_query_hash(query_items: Iterable[tuple[str, str]]) -> str:
    canonical = json.dumps(
        sorted((str(key), str(value)) for key, value in query_items),
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _approval_body_fields(body: bytes) -> dict[str, Any]:
    if not body:
        return {}
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _connector_sync_is_dry_run(path: str, fields: dict[str, Any]) -> bool:
    return bool(re.match(r"^/connectors/[^/]+/sync$", path)) and fields.get("execute") is not True


def _approval_item_count(fields: dict[str, Any]) -> int:
    for key in (
        "ids",
        "message_ids",
        "event_ids",
        "file_ids",
        "task_ids",
        "values",
        "requests",
        "items",
    ):
        value = fields.get(key)
        if isinstance(value, list):
            return max(1, len(value))
    return 1


def _approval_account_ref(request: Request, fields: dict[str, Any]) -> str:
    account = fields.get("account") or request.query_params.get("account")
    if isinstance(account, str) and account.strip():
        return account.strip()
    return "unspecified"


def _approval_resource_ref(request: Request, fields: dict[str, Any]) -> str:
    path = request.url.path
    connector_match = re.match(r"^/connectors/([^/]+)/sync$", path)
    if connector_match:
        return f"connector:{connector_match.group(1)}"
    if path == "/calendar/events":
        calendar_id = fields.get("calendar_id")
        if isinstance(calendar_id, str) and calendar_id.strip():
            return f"calendar_id:{calendar_id.strip()}"
        account = fields.get("account") or request.query_params.get("account")
        if isinstance(account, str) and account.strip():
            return f"calendar_account:{account.strip()}"
        return "calendar:default"
    if path == "/tasks":
        title = fields.get("title")
        if isinstance(title, str) and title.strip():
            return f"task_title:{title.strip()}"
    if path == "/drive/folder":
        return ""
    if path == "/drive/upload":
        for key in ("folder_id", "file_id", "parent_id"):
            value = fields.get(key)
            if isinstance(value, str) and value.strip():
                return f"{key}:{value.strip()}"
        return ""
    if path == "/drive/workflow-folder":
        workflow = fields.get("workflow")
        parent_id = fields.get("parent_id") or fields.get("folder_id")
        if (
            isinstance(workflow, str)
            and workflow.strip()
            and isinstance(parent_id, str)
            and parent_id.strip()
        ):
            return f"workflow:{workflow.strip()}:parent:{parent_id.strip()}"
        if isinstance(workflow, str) and workflow.strip():
            return f"workflow:{workflow.strip()}"
        return ""

    for key in (
        "message_id",
        "thread_id",
        "conv_id",
        "event_id",
        "calendar_id",
        "file_id",
        "document_id",
        "spreadsheet_id",
        "task_id",
        "reminder_id",
        "chat_name",
        "to",
        "email",
    ):
        value = fields.get(key)
        if isinstance(value, str) and value.strip():
            return f"{key}:{value.strip()}"
    tail = path.rstrip("/").rsplit("/", 1)[-1]
    if tail and tail not in {
        "compose",
        "events",
        "tasks",
        "reminders",
        "scheduled",
        "followups",
        "send",
    }:
        return f"path:{tail}"
    # For create endpoints that have no existing resource ID, use the title/subject as ref
    for key in ("title", "subject", "name", "summary"):
        value = fields.get(key)
        if isinstance(value, str) and value.strip():
            return f"{key}:{value.strip()}"
    if tail:
        return f"op:{tail}"
    return ""


def _approval_decision(
    rule: ApprovalRouteRule,
    *,
    can_execute: bool,
    reason: str,
    request: Request,
    account_ref: str = "",
    resource_ref: str = "",
    item_count: int = 1,
    metadata: dict[str, Any] | None = None,
) -> ApprovalGateDecision:
    return ApprovalGateDecision(
        provider=rule.provider,
        operation=rule.operation,
        approval_class=rule.approval_class,
        executor=rule.executor,
        can_execute=can_execute,
        reason=reason,
        target_resource=resource_ref or request.url.path,
        account=account_ref,
        item_count=item_count,
        metadata=metadata or {},
    )


def _approval_context_for_action(
    method: str, path: str, body: bytes | dict[str, Any] | None = None
) -> dict[str, Any]:
    """Compute the (rule, account_ref, resource_ref, item_count, payload_hash,
    query_hash) tuple that a lease for this exact action would be scoped to,
    without minting anything. Shared by mint_local_approval_lease() and
    POST /approvals/request so the two can never compute this differently."""
    body_bytes = (
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        if isinstance(body, dict)
        else body or b""
    )
    parsed_path = urlsplit(path)
    request_path = parsed_path.path
    query_params = {
        key: values[-1] for key, values in parse_qs(parsed_path.query).items() if values
    }
    rule = _approval_rule_for_request(method.upper(), request_path)
    if rule is None:
        raise ValueError(f"no approval route rule for {method} {path}")
    fields = _approval_body_fields(body_bytes)
    fake_request = type(
        "_LeaseRequest",
        (),
        {"url": type("_Url", (), {"path": request_path})(), "query_params": query_params},
    )()
    return {
        "rule": rule,
        "request_path": request_path,
        "body_bytes": body_bytes,
        "account_ref": _approval_account_ref(fake_request, fields),
        "resource_ref": _approval_resource_ref(fake_request, fields),
        "item_count": _approval_item_count(fields),
        "payload_hash": _canonical_payload_hash(body_bytes),
        "query_hash": _canonical_query_hash(parse_qsl(parsed_path.query, keep_blank_values=True)),
    }


def mint_local_approval_lease(
    method: str,
    path: str,
    *,
    body: bytes | dict[str, Any] | None = None,
    now: datetime | None = None,
    ttl_seconds: int = APPROVAL_LEASE_TTL_SECONDS,
) -> str:
    """Create a local per-action lease for tests and local approval adapters."""
    ctx = _approval_context_for_action(method, path, body)
    rule: ApprovalRouteRule = ctx["rule"]
    lease_id = f"lease_{token_urlsafe(18)}"
    lease = ApprovalLease(
        lease_id=lease_id,
        method=method.upper(),
        path=ctx["request_path"],
        provider=rule.provider,
        operation=rule.operation,
        approval_class=rule.approval_class,
        executor=rule.executor,
        account_ref=ctx["account_ref"],
        resource_ref=ctx["resource_ref"],
        item_count=ctx["item_count"],
        payload_hash=ctx["payload_hash"],
        query_hash=ctx["query_hash"],
        not_after=(now or datetime.now(UTC)) + timedelta(seconds=ttl_seconds),
        nonce=token_urlsafe(18),
    )
    _approval_leases[lease_id] = lease
    return lease_id


async def _approval_decision_for_request(request: Request) -> ApprovalGateDecision | None:
    rule = _approval_rule_for_request(request.method, request.url.path)
    if rule is None:
        return None
    supplied = request.headers.get(APPROVAL_LEASE_HEADER, "")
    body = await request.body()
    fields = _approval_body_fields(body)
    if _connector_sync_is_dry_run(request.url.path, fields):
        return None
    payload_hash = _canonical_payload_hash(body)
    query_hash = _canonical_query_hash(request.query_params.multi_items())
    account_ref = _approval_account_ref(request, fields)
    resource_ref = _approval_resource_ref(request, fields)
    item_count = _approval_item_count(fields)
    if not supplied:
        return _approval_decision(
            rule,
            can_execute=False,
            reason="missing_per_action_approval_lease",
            request=request,
            account_ref=account_ref,
            resource_ref=resource_ref,
            item_count=item_count,
        )
    async with _approval_lease_lock:
        lease = _approval_leases.get(supplied)
        now = datetime.now(UTC)
        if lease is None:
            return _approval_decision(
                rule, can_execute=False, reason="unknown_per_action_approval_lease", request=request
            )
        if not resource_ref:
            return _approval_decision(
                rule,
                can_execute=False,
                reason="missing_resource_ref",
                request=request,
                account_ref=account_ref,
                resource_ref=resource_ref,
                item_count=item_count,
            )
        checks = (
            ("method_mismatch", request.method == lease.method),
            ("path_mismatch", request.url.path == lease.path),
            ("provider_mismatch", rule.provider == lease.provider),
            ("operation_mismatch", rule.operation == lease.operation),
            ("approval_class_mismatch", rule.approval_class == lease.approval_class),
            ("executor_mismatch", rule.executor == lease.executor),
            ("account_mismatch", account_ref == lease.account_ref),
            ("resource_mismatch", resource_ref == lease.resource_ref),
            ("item_count_mismatch", item_count == lease.item_count),
            ("query_hash_mismatch", query_hash == lease.query_hash),
            ("payload_hash_mismatch", payload_hash == lease.payload_hash),
            ("lease_expired", now <= lease.not_after),
            ("lease_replayed", not lease.spent),
        )
        for reason, passed in checks:
            if not passed:
                return _approval_decision(
                    rule,
                    can_execute=False,
                    reason=reason,
                    request=request,
                    account_ref=account_ref,
                    resource_ref=resource_ref,
                    item_count=item_count,
                    metadata={
                        "nonce": lease.nonce,
                        "payload_hash": payload_hash,
                        "query_hash": query_hash,
                    },
                )
        _approval_leases[supplied] = ApprovalLease(**{**lease.__dict__, "spent": True})
    return _approval_decision(
        rule,
        can_execute=True,
        reason="approved_by_per_action_lease",
        request=request,
        account_ref=account_ref,
        resource_ref=resource_ref,
        item_count=item_count,
        metadata={"nonce": lease.nonce, "payload_hash": payload_hash, "query_hash": query_hash},
    )


def _deny_approval_response(decision: ApprovalGateDecision) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={
            "error": "approval_required",
            "provider": decision.provider,
            "operation": decision.operation,
            "approval_class": decision.approval_class,
            "executor": decision.executor,
            "can_execute": False,
            "reason": decision.reason,
        },
    )


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


class IMessageOut(MessageOut):
    chat_id: str
    contact: str


class IMessageLinkOut(BaseModel):
    url: str
    message_id: str
    chat_id: str
    contact: str
    sender: str
    body: str
    ts: str
    is_me: bool
    source: str = "imessage"


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
    recurrence: list[str] = []
    reminders: dict = {}
    recurring_event_id: str = ""
    workflow: str = ""


class CalendarOut(BaseModel):
    id: str
    summary: str
    description: str = ""
    primary: bool = False
    access_role: str = ""
    background_color: str = ""
    account: str = ""


class RsvpRequest(BaseModel):
    response: str  # "accepted" | "declined" | "tentative"
    calendar_id: str = "primary"
    account: str = ""


class ModifyAttendeesRequest(BaseModel):
    add: list[dict[str, str]] = []
    remove: list[str] = []
    calendar_id: str = "primary"
    account: str = ""


class EventRemindersRequest(BaseModel):
    use_default: bool = False
    overrides: list[dict[str, int | str]] = []
    calendar_id: str = "primary"
    account: str = ""


class FreeBusyRequest(BaseModel):
    time_min: str
    time_max: str
    calendar_ids: list[str] = ["primary"]
    timezone: str = "UTC"
    account: str = ""


class FreeSlotsRequest(BaseModel):
    time_min: str
    time_max: str
    calendar_ids: list[str] = ["primary"]
    duration_minutes: int = 30
    timezone: str = "UTC"
    account: str = ""


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
    reminders: dict | None = None


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
    priority: int = 0
    flagged: bool = False


class ReminderEditRequest(BaseModel):
    title: str | None = None
    due_date: str | None = None
    notes: str | None = None
    priority: int | None = None
    flagged: bool | None = None


class TaskOut(BaseModel):
    id: str
    title: str
    status: str
    list_id: str
    list_title: str
    due: str | None = None
    notes: str = ""
    completed: str | None = None
    account: str = ""
    workflow: str = ""


class TaskCreateRequest(BaseModel):
    title: str
    list_id: str = "@default"
    due: str = ""
    notes: str = ""
    # Optional stable request identity. When set, create embeds a provider-native
    # notes marker and retries read that marker before insert (no local binding DB).
    idempotency_key: str = ""


class TaskUpdateRequest(BaseModel):
    title: str | None = None
    due: str | None = None
    notes: str | None = None


class ScheduleMessageRequest(BaseModel):
    source: str  # "gmail" | "imessage"
    conv_id: str  # iMessage contact id, or Gmail "to|subject" for compose
    text: str
    send_at: str  # ISO datetime
    account: str = ""


class FollowupCreateRequest(BaseModel):
    source: str  # "gmail" | "imessage"
    conv_id: str
    thread_id: str = ""
    remind_after: str  # ISO datetime
    reminder_title: str
    reminder_list: str = "Reminders"


class TaskLinkRequest(BaseModel):
    task_id: str
    task_source: str  # "google_tasks" | "reminders"
    message_id: str
    message_source: str  # "gmail" | "imessage"
    thread_id: str = ""
    account: str = ""


class ApprovalRequestIn(BaseModel):
    """Describes a pending guarded action, in the exact shape the lease
    system already hashes on: method + path (+ query string) + body."""

    method: str
    path: str
    body: dict[str, Any] | None = None


class ApprovalDecisionIn(BaseModel):
    approve: StrictBool
    decided_by: str = "captain"
    denial_reason: str = ""


class TaskFromMessageRequest(BaseModel):
    message_id: str
    message_source: str  # "gmail" | "imessage"
    title: str
    task_type: str = "google_tasks"  # "google_tasks" | "reminders"
    list_id: str = "@default"  # for google_tasks
    list_name: str = "Reminders"  # for reminders
    notes: str = ""
    thread_id: str = ""
    account: str = ""


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


class DocumentOut(BaseModel):
    id: str
    title: str
    url: str
    mime_type: str = "application/vnd.google-apps.document"
    account: str = ""


class PreflightResult(BaseModel):
    kind: str
    resolved_account: str
    destination: str
    destination_id: str
    valid: bool
    warnings: list[str] = []
    explanation: str


class CreateDocumentRequest(BaseModel):
    title: str
    account: str = ""


class WorkflowEventRequest(BaseModel):
    kind: str = ""  # "interview" | "deadline" | "meeting"
    title: str
    workflow: str = ""
    start: str
    end: str
    location: str = ""
    description: str = ""
    attendees: list[dict[str, str]] = []
    account: str = ""


class NeedsActionOut(BaseModel):
    thread_read_model: str = "index"
    raw_thread_provider_fetch: bool = False
    threads: list[GmailThreadSummaryOut]
    tasks: list[TaskOut]
    events: list[CalendarEventOut]
    workflow_counts: dict[str, int]


class IndexSyncOut(BaseModel):
    ok: bool
    mode: str
    stats: dict[str, dict[str, int]]


class IndexSyncStateOut(BaseModel):
    source: str
    account: str
    checkpoint_type: str
    checkpoint_value: str
    last_success_at: str
    last_full_sync_at: str
    status: str
    last_run_started_at: str
    last_error: str
    metadata: dict[str, Any]


class IndexStatusOut(BaseModel):
    db_path: str
    read_model: str = "index"
    raw_provider_fetch: bool = False
    threads: list[GmailThreadSummaryOut]


class IndexOverviewOut(BaseModel):
    db_path: str
    read_model: str = "index"
    raw_provider_fetch: bool = False
    counts: dict[str, int]
    sync_states: list[IndexSyncStateOut]


class IndexSyncHealthStateOut(IndexSyncStateOut):
    last_success_age_seconds: int | None
    healthy: bool
    stale: bool
    reasons: list[str]


class IndexHealthOut(BaseModel):
    db_path: str
    healthy: bool
    stale: bool
    checked_at: str
    stale_after_seconds: int
    newest_success_at: str | None
    newest_success_age_seconds: int | None
    reasons: list[str]
    sync_states: list[IndexSyncHealthStateOut]


class CaptureSourceOut(BaseModel):
    key: str
    source_id: str
    display_name: str
    source_type: str
    account: str = ""
    configured: bool
    authenticated: bool
    readable: bool
    writable: bool
    last_success_at: str
    newest_seen_at: str
    newest_seen_id: str
    item_count: int
    checked_at: str
    last_error: str
    coverage_notes: str
    status: str


class CaptureStatusOut(BaseModel):
    db_path: str
    checked_at: str
    summary: dict[str, int]
    sources: list[CaptureSourceOut]


class CaptureHealthOut(CaptureStatusOut):
    healthy: bool
    reasons: list[str]


class ProviderStatusOut(BaseModel):
    provider: str
    category: str
    configured: bool
    authenticated: bool = False
    readable: bool = False
    syncable: bool = False
    writable: bool = False
    accounts: list[str] = []
    blockers: list[str] = []
    remediation: list[str] = []
    notes: str = ""


class ProviderReadinessOut(BaseModel):
    status: str
    checked_at: str
    providers: list[ProviderStatusOut]
    summary: dict[str, int]
    api: dict[str, bool]
    recommendations: list[str]


class IndexedThreadListOut(BaseModel):
    view: str
    db_path: str
    read_model: str = "index"
    raw_provider_fetch: bool = False
    threads: list[GmailThreadSummaryOut]


class InboxNowOut(BaseModel):
    read_model: str = "inbox_now"
    read_only: bool = True
    raw_thread_provider_fetch: bool = False
    write_actions: list[str] = []
    index_health: IndexHealthOut
    reasons: list[str]
    now_items: list[dict[str, Any]]
    actionable_threads: list[GmailThreadSummaryOut]
    waiting_threads: list[GmailThreadSummaryOut]
    commitments: list[dict[str, Any]]
    source_refs: list[dict[str, str]]
    workflow_counts: dict[str, int]


class WorkflowFolderRequest(BaseModel):
    workflow: str
    name: str = ""
    parent_id: str = ""
    account: str = ""


class WorkflowDocRequest(BaseModel):
    title: str
    workflow: str = ""
    account: str = ""


class WorkflowSheetRequest(BaseModel):
    title: str
    workflow: str = ""
    account: str = ""


class InsertTextRequest(BaseModel):
    text: str
    index: int = 1


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
    from_addr: str = ""  # filter by sender (gmail/imessage)
    before: str = ""  # ISO date cutoff (inclusive upper bound)
    after: str = ""  # ISO date cutoff (inclusive lower bound)
    has_attachment: bool = False  # Gmail only
    is_unread: bool = False  # Gmail only


class ConnectorSearchRequest(BaseModel):
    q: str
    sources: list[str] = ["all"]
    limit: int = 20


class ConnectorSyncRequest(BaseModel):
    execute: StrictBool = False


class AhmedOfficeLocationDryRunRequest(BaseModel):
    event_id: str = "b9quemrk7mua74qfv1b707rik0"
    calendar_id: str = "primary"
    account: str = ""
    query: str = "Ahmed office location"
    limit: int = 10


class GatewayReadProofRequest(BaseModel):
    account: str = ""
    gmail_query: str = "in:inbox"
    gmail_limit: int = 5
    calendar_days: int = 7
    calendar_limit: int = 10
    task_list_id: str = "@default"
    task_limit: int = 10


class GmailReadinessRequest(BaseModel):
    accounts: list[str] = ["jwalinshah13@gmail.com", "jshah1331@gmail.com"]


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


class ProductionGmailSourceAdapter:
    def search(
        self,
        service: object,
        account_email: str,
        q: str = "",
        limit: int = 20,
        label: str = "",
        from_filter: str = "",
        subject_filter: str = "",
        after: str = "",
        before: str = "",
    ) -> list[Contact]:
        return gmail_search(
            service,
            account_email,
            q,
            limit,
            label,
            from_filter,
            subject_filter,
            after,
            before,
        )


class ProductionCalendarSourceAdapter:
    def events(
        self,
        cal_services: dict[str, object],
        date: datetime | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[CalendarEvent]:
        if start_date is not None or end_date is not None:
            return calendar_events(
                cal_services,
                date,
                start_date=start_date,
                end_date=end_date,
            )
        return calendar_events(cal_services, date, start_date, end_date)


@dataclass
class SourceAdapters:
    gmail: ProductionGmailSourceAdapter = field(default_factory=ProductionGmailSourceAdapter)
    calendar: ProductionCalendarSourceAdapter = field(
        default_factory=ProductionCalendarSourceAdapter
    )


class CaptureEventRequest(BaseModel):
    source: str
    event_type: str = "manual.capture"
    source_object_id: str
    observed_at: str
    occurred_at: str
    payload: Any
    provenance: dict[str, Any]
    event_id: str = ""


class CapturedEventOut(BaseModel):
    event_id: str
    source: str
    source_object_id: str
    observed_at: str
    occurred_at: str
    event_type: str
    payload: Any
    provenance: dict[str, Any]
    ingested_at: str
    schema_version: str


class CaptureEventOut(BaseModel):
    result: Literal["created", "already_exists", "error"]
    event: CapturedEventOut | None = None
    error: str | None = None


class ServerState:
    def __init__(self) -> None:
        self.gmail_services: dict[str, object] = {}
        self.cal_services: dict[str, object] = {}
        self.drive_services: dict[str, object] = {}
        self.sheets_services: dict[str, object] = {}
        self.docs_services: dict[str, object] = {}
        self.tasks_services: dict[str, object] = {}
        self.conv_cache: dict[str, Contact] = {}  # "source:id" -> Contact
        self.events_cache: list[CalendarEvent] = []
        self.ambient: AmbientService = AmbientService(
            on_note=lambda raw, summary: ambient_notes.save_note(raw, summary)
        )
        self.dictation: DictationService = DictationService()
        self.scheduler: SchedulerStore = SchedulerStore()
        self.approvals: ApprovalStore = ApprovalStore()
        self.index_store: MessageIndexStore = MessageIndexStore()
        self.capture_health_store: CaptureHealthStore = CaptureHealthStore()
        self.event_store: EventStore = EventStore()
        self.source_adapters: SourceAdapters = SourceAdapters()


state = ServerState()
memory_store = MemoryStore()


@dataclass
class InboxServerRuntime:
    server_state: ServerState | None = None
    init_contacts_func: Callable[[], int] | None = None
    google_auth_func: Callable[[], GOOGLE_SERVICE_SET] | None = None
    start_scheduler: bool = True
    ambient_autostart: bool = True
    prewarm_conversations: bool | None = None
    close_sqlite_func: Callable[[], None] | None = None


def _empty_google_services() -> GOOGLE_SERVICE_SET:
    return {}, {}, {}, {}, {}, {}


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
        workflow=_classify_workflow(f"{e.summary} {e.description}"),
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


def _task_to_out(t: GoogleTask, account: str = "") -> TaskOut:
    return TaskOut(
        id=t.id,
        title=t.title,
        status=t.status,
        list_id=t.list_id,
        list_title=t.list_title,
        due=t.due.isoformat() if t.due else None,
        notes=t.notes,
        completed=t.completed.isoformat() if t.completed else None,
        account=account,
        workflow=_classify_workflow(f"{t.title} {t.notes}"),
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


def _scheduler_durable_approval_denial(row: dict[str, Any]) -> str:
    """Return a fail-closed denial reason when a due scheduler row is not durably approved."""
    proposal_id = str(row.get("proposal_id") or "").strip()
    intent_hash = str(row.get("intent_hash") or "").strip()
    approval_state = str(row.get("approval_state") or "").strip()
    if not proposal_id:
        return "missing_durable_approval_proposal_id"
    if not intent_hash:
        return "missing_durable_approval_intent_hash"
    if approval_state != "approved":
        return f"scheduler_durable_approval_not_approved:{approval_state or 'missing'}"
    return ""


# ── Background scheduler loop ────────────────────────────────────────────────


async def _process_scheduled_messages() -> None:
    """Send any scheduled messages that are due."""
    try:
        due = await asyncio.to_thread(state.scheduler.get_due_messages)
        for msg in due:
            msg_id = msg["id"]
            source = msg["source"]
            try:
                approval_denial = _scheduler_durable_approval_denial(msg)
                if approval_denial:
                    await asyncio.to_thread(state.scheduler.mark_failed, msg_id, approval_denial)
                    logger.warning(
                        f"[scheduler] Scheduled message {msg_id} denied: {approval_denial}"
                    )
                    continue
                if source == "gmail":
                    acct = msg.get("account", "")
                    svc_key = acct or (
                        next(iter(state.gmail_services)) if state.gmail_services else ""
                    )
                    svc = state.gmail_services.get(svc_key)
                    if not svc:
                        await asyncio.to_thread(
                            state.scheduler.mark_failed, msg_id, "No Gmail service"
                        )
                        continue
                    # conv_id here holds the "to" email address for compose
                    # Format: "to|subject" — if no pipe, treat whole as recipient with empty subject
                    raw_conv = msg["conv_id"]
                    if "|" in raw_conv:
                        to, subject = raw_conv.split("|", 1)
                    else:
                        to, subject = raw_conv, "(no subject)"
                    ok = await asyncio.to_thread(gmail_compose_send, svc, to, subject, msg["text"])
                    if ok:
                        await asyncio.to_thread(state.scheduler.mark_sent, msg_id)
                        logger.info(f"[scheduler] Sent gmail msg {msg_id} → {to}")
                    else:
                        await asyncio.to_thread(
                            state.scheduler.mark_failed, msg_id, "gmail_compose_send returned False"
                        )
                elif source == "imessage":
                    cache_key = _cache_key("imessage", msg["conv_id"])
                    contact = state.conv_cache.get(cache_key)
                    if not contact:
                        contacts = await asyncio.to_thread(imsg_contacts, 200)
                        contact = next((c for c in contacts if c.id == msg["conv_id"]), None)
                        if contact:
                            state.conv_cache[cache_key] = contact
                    if not contact:
                        await asyncio.to_thread(
                            state.scheduler.mark_failed, msg_id, "Contact not found"
                        )
                        continue
                    ok = await asyncio.to_thread(imsg_send, contact, msg["text"])
                    if ok:
                        await asyncio.to_thread(state.scheduler.mark_sent, msg_id)
                        logger.info(f"[scheduler] Sent imsg {msg_id} → {contact.name}")
                    else:
                        await asyncio.to_thread(
                            state.scheduler.mark_failed, msg_id, "imsg_send returned False"
                        )
                else:
                    await asyncio.to_thread(
                        state.scheduler.mark_failed, msg_id, f"Unknown source: {source}"
                    )
            except Exception as e:
                logger.exception(f"[scheduler] Failed to send msg {msg_id}")
                await asyncio.to_thread(state.scheduler.mark_failed, msg_id, str(e))
    except Exception:
        logger.exception("[scheduler] _process_scheduled_messages failed")


async def _process_followup_reminders() -> None:
    """Check follow-up reminders — create Apple Reminders if no reply has come in."""
    try:
        due = await asyncio.to_thread(state.scheduler.get_due_followups)
        for fu in due:
            fid = fu["id"]
            try:
                approval_denial = _scheduler_durable_approval_denial(fu)
                if approval_denial:
                    logger.warning(f"[scheduler] Follow-up {fid} denied: {approval_denial}")
                    continue
                created_at = datetime.fromisoformat(fu["created_at"])
                replied = False
                if fu["source"] == "gmail" and fu["thread_id"]:
                    svc_key = next(iter(state.gmail_services)) if state.gmail_services else ""
                    svc = state.gmail_services.get(svc_key)
                    if svc:
                        msgs = await asyncio.to_thread(
                            gmail_thread, svc, fu["conv_id"], fu["thread_id"]
                        )
                        # Reply = any message in thread newer than created_at that isn't from me
                        replied = any(m.ts > created_at and not m.is_me for m in msgs)
                elif fu["source"] == "imessage":
                    cache_key = _cache_key("imessage", fu["conv_id"])
                    contact = state.conv_cache.get(cache_key)
                    if not contact:
                        contacts = await asyncio.to_thread(imsg_contacts, 200)
                        contact = next((c for c in contacts if c.id == fu["conv_id"]), None)
                    if contact:
                        msgs = await asyncio.to_thread(imsg_thread, contact, 20)
                        replied = any(m.ts > created_at and not m.is_me for m in msgs)

                if replied:
                    await asyncio.to_thread(state.scheduler.mark_followup_replied, fid)
                    logger.info(f"[scheduler] Follow-up {fid} replied — skipping task")
                else:
                    # Try Google Tasks first (integrates with Google Calendar)
                    ok = False
                    task_created_via = ""
                    title = fu["reminder_title"]
                    notes = f"No reply in conversation: {fu['conv_id']}"

                    if state.tasks_services:
                        try:
                            _, tasks_svc = _get_tasks_service_for_account("")
                            due_iso = datetime.now().strftime("%Y-%m-%dT00:00:00.000Z")
                            created = await asyncio.to_thread(
                                task_create, tasks_svc, title, "@default", due_iso, notes
                            )
                            ok = (
                                bool(created.get("ok"))
                                if isinstance(created, dict)
                                else bool(created)
                            )
                            if ok:
                                task_created_via = "google_tasks"
                        except Exception as e:
                            logger.warning(
                                f"[scheduler] Google Tasks followup failed ({e}), falling back to Apple Reminders"
                            )

                    # Fallback: Apple Reminders
                    if not ok:
                        now_str = datetime.now().strftime("%B %d, %Y %I:%M:%S %p")
                        ok = await asyncio.to_thread(
                            reminder_create,
                            title=title,
                            list_name=fu["reminder_list"],
                            due_date=now_str,
                            notes=notes,
                        )
                        if ok:
                            task_created_via = "apple_reminders"

                    if ok:
                        await asyncio.to_thread(state.scheduler.mark_followup_fired, fid)
                        logger.info(
                            f"[scheduler] Follow-up {fid} fired — created via {task_created_via}"
                        )
                    else:
                        logger.warning(
                            f"[scheduler] Follow-up {fid} failed to create task via any backend"
                        )
            except Exception:
                logger.exception(f"[scheduler] Failed to process followup {fid}")
    except Exception:
        logger.exception("[scheduler] _process_followup_reminders failed")


# Track which events we've already created departure tasks for (avoid duplicates)
_departure_task_created: set[str] = set()


async def _process_departure_alerts() -> None:
    """Check upcoming events and create 'time to leave' tasks when departure time is near."""
    if os.environ.get("INBOX_ENABLE_DEPARTURE_ALERTS") != "1":
        return
    home = await asyncio.to_thread(get_current_location)
    if not home:
        return  # No location available — skip departure alerts

    try:
        events = await asyncio.to_thread(calendar_events, state.cal_services)
        departures = await asyncio.to_thread(
            departure_times_for_events, events, home, "driving", 10, 4
        )
        now = datetime.now()
        for dep in departures:
            # Alert if departure time is within 15 minutes from now
            minutes_until_departure = (dep.departure_time - now).total_seconds() / 60
            if -5 < minutes_until_departure < 15:
                event_key = f"{dep.event_summary}|{dep.event_start.isoformat()}"
                if event_key in _departure_task_created:
                    continue
                _departure_task_created.add(event_key)

                title = f"🚗 Leave now for {dep.event_summary} ({dep.duration_text})"
                notes = f"Travel: {dep.distance_text}, {dep.duration_text} ({dep.mode})\nTo: {dep.event_location}\nEvent: {dep.event_start.strftime('%I:%M %p')}"

                # Try Google Tasks first, fallback to Apple Reminders
                ok = False
                if state.tasks_services:
                    try:
                        _, tasks_svc = _get_tasks_service_for_account("")
                        due_iso = dep.departure_time.strftime("%Y-%m-%dT00:00:00.000Z")
                        created = await asyncio.to_thread(
                            task_create, tasks_svc, title, "@default", due_iso, notes
                        )
                        ok = bool(created.get("ok")) if isinstance(created, dict) else bool(created)
                    except Exception:
                        pass
                if not ok:
                    now_str = dep.departure_time.strftime("%B %d, %Y %I:%M:%S %p")
                    ok = await asyncio.to_thread(
                        reminder_create, title=title, due_date=now_str, notes=notes
                    )

                if ok:
                    logger.info(f"[scheduler] Departure alert: {title}")
    except Exception:
        logger.exception("[scheduler] _process_departure_alerts failed")


_INDEX_SYNC_INTERVAL_TICKS = 40  # 40 * 30s = every 20 minutes
# Widened from 5 to 20 minutes 2026-07-20: this Mac is on a pre-release macOS
# (27.0, "Tier 2 unsupported" per Homebrew) that crashes with EXC_BREAKPOINT/
# SIGTRAP inside Python's built-in _ssl module's TLS-alert error-handling path
# under network load — confirmed via ~/Library/Logs/DiagnosticReports/, not
# specific to any one CPython patch version (reproduced on both 3.12.13 and
# 3.12.12). Not fixable at this layer; widening the interval only reduces how
# often the crash path gets hit, it doesn't fix the underlying OS bug.


async def _scheduler_loop() -> None:
    """Background loop: check scheduled messages, followups, departures every 30s.

    Also runs incremental mail/iMessage index sync every 5 minutes. Before this,
    index_incremental_sync() was only reachable via a manual POST to
    /index/sync/incremental — nothing called it automatically, so the index went
    stale between manual triggers (this is what caused it to sit empty for weeks).
    """
    logger.info("[scheduler] Background loop started")
    tick = 0
    while True:
        try:
            await asyncio.sleep(30)
            tick += 1
            await _process_scheduled_messages()
            await _process_followup_reminders()
            await _process_departure_alerts()
            if tick % _INDEX_SYNC_INTERVAL_TICKS == 0:
                try:
                    stats = await asyncio.to_thread(index_incremental_sync, state.index_store)
                    logger.info("[scheduler] incremental index sync: %s", stats)
                except Exception:
                    logger.exception("[scheduler] incremental index sync failed")
        except asyncio.CancelledError:
            logger.info("[scheduler] Background loop cancelled")
            raise
        except Exception:
            logger.exception("[scheduler] Loop iteration failed")


# ── App lifecycle ────────────────────────────────────────────────────────────


def make_lifespan(runtime: InboxServerRuntime | None = None):
    runtime = runtime or InboxServerRuntime()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        global state

        previous_state = state
        if runtime.server_state is not None:
            state = runtime.server_state

        init_contacts_func = runtime.init_contacts_func or init_contacts
        google_auth_func = runtime.google_auth_func or google_auth_all
        close_sqlite_func = runtime.close_sqlite_func or close_sqlite_connections

        n = await asyncio.to_thread(init_contacts_func)
        print(f"Loaded {n} contacts")

        gmail, cal, drive, sheets, docs, tasks = await asyncio.to_thread(google_auth_func)
        state.gmail_services = gmail
        state.cal_services = cal
        state.drive_services = drive
        state.sheets_services = sheets
        state.docs_services = docs
        state.tasks_services = tasks
        print(
            f"Gmail accounts: {list(gmail.keys())}, "
            f"Calendar accounts: {list(cal.keys())}, "
            f"Drive accounts: {list(drive.keys())}, "
            f"Sheets accounts: {list(sheets.keys())}, "
            f"Docs accounts: {list(docs.keys())}, "
            f"Tasks accounts: {list(tasks.keys())}"
        )

        prewarm = runtime.prewarm_conversations
        if prewarm is None:
            prewarm = os.environ.get("INBOX_PRE_WARM_CONVERSATIONS", "").strip() in (
                "1",
                "true",
                "yes",
            )
        if prewarm:
            try:
                results = await _fetch_conversations("all", limit=50)
                state.conv_cache.clear()
                for c in results:
                    state.conv_cache[_cache_key(c.source, c.id)] = c
                print(f"Pre-warmed {len(state.conv_cache)} conversations")
            except Exception:
                logger.warning("Pre-warm conversations failed (non-fatal)")

        if runtime.ambient_autostart:
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

        scheduler_task = None
        if runtime.start_scheduler:
            scheduler_task = asyncio.create_task(_scheduler_loop())

        try:
            yield
        finally:
            if scheduler_task is not None:
                scheduler_task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await scheduler_task
            state.ambient.stop()
            await asyncio.to_thread(close_sqlite_func)
            if runtime.server_state is not None:
                state = previous_state

    return lifespan


def create_app(runtime: InboxServerRuntime | None = None) -> FastAPI:
    new_app = FastAPI(
        title="Inbox API",
        lifespan=make_lifespan(runtime),
        docs_url="/api-docs",
        redoc_url="/api-redoc",
        openapi_url="/api-openapi.json",
    )

    existing_app = globals().get("app")
    if existing_app is not None:
        generated_paths = {"/api-docs", "/api-redoc", "/api-openapi.json"}
        for route in existing_app.router.routes:
            if getattr(route, "path", "") not in generated_paths:
                new_app.router.routes.append(route)
        new_app.user_middleware.extend(existing_app.user_middleware)
        new_app.exception_handlers.update(existing_app.exception_handlers)
        new_app.middleware_stack = None

    return new_app


app = create_app()


def _auth_token() -> str:
    return os.getenv(AUTH_TOKEN_ENV, "").strip()


def _auth_bypass_enabled() -> bool:
    return os.getenv(AUTH_BYPASS_ENV, "").strip().lower() in AUTH_BYPASS_TRUE_VALUES


def _non_health_auth_required() -> bool:
    return bool(_auth_token()) or not _auth_bypass_enabled()


def _is_authorized(request: Request) -> bool:
    if request.url.path == "/health":
        return True

    token = _auth_token()
    if token:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            provided = auth_header[7:].strip()
            if provided and compare_digest(provided, token):
                return True

        api_key = request.headers.get("x-api-key", "").strip()
        return bool(api_key) and compare_digest(api_key, token)

    return _auth_bypass_enabled()


@app.middleware("http")
async def require_api_token(request: Request, call_next):
    if not _is_authorized(request):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Unauthorized"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    decision = await _approval_decision_for_request(request)
    if decision is not None and not decision.can_execute:
        return _deny_approval_response(decision)
    exc: BaseException | None = None
    response = None
    try:
        response = await call_next(request)
    except BaseException as caught:  # noqa: BLE001 - must audit before re-raising
        exc = caught
    if decision is not None and decision.can_execute:
        # Audit every guarded write that actually reached the provider helper,
        # regardless of which path minted its lease (approvals flow, direct
        # mint_local_approval_lease() call, or test helper) -- including ones
        # that blew up inside the route handler, not just non-2xx responses.
        status_code = response.status_code if response is not None else 500
        await asyncio.to_thread(
            state.approvals.log_event,
            "guarded_write_executed",
            lease_id=request.headers.get(APPROVAL_LEASE_HEADER, ""),
            method=request.method,
            path=request.url.path,
            provider=decision.provider,
            operation=decision.operation,
            account=decision.account,
            resource=decision.target_resource,
            payload_hash=decision.metadata.get("payload_hash", ""),
            result="success" if status_code < 400 else "failed",
            detail={
                "status_code": status_code,
                "executor": decision.executor,
                **({"exception": repr(exc)} if exc is not None else {}),
            },
        )
    if exc is not None:
        raise exc
    return response


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
        "api_auth_required": _non_health_auth_required(),
        "api_auth_configured": bool(_auth_token()),
        "api_auth_dev_bypass": _auth_bypass_enabled(),
    }


def _sqlite_read_probe(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "path_missing"
    try:
        uri = f"file:{path}?mode=ro&immutable=1"
        with sqlite3.connect(uri, uri=True, timeout=2.0) as conn:
            conn.execute("SELECT 1").fetchone()
        return True, ""
    except sqlite3.DatabaseError as exc:
        return False, str(exc)
    except OSError as exc:
        return False, str(exc)


def _local_sqlite_provider(
    provider: str,
    path: Path,
    notes: str,
) -> ProviderStatusOut:
    readable, error = _sqlite_read_probe(path)
    blockers = [] if readable else [error]
    return ProviderStatusOut(
        provider=provider,
        category="local_sqlite",
        configured=path.exists(),
        authenticated=readable,
        readable=readable,
        writable=False,
        blockers=blockers,
        notes=notes,
    )


def _reminders_provider() -> ProviderStatusOut:
    candidates = sorted(REMINDERS_DIR.glob("Data-*.sqlite")) if REMINDERS_DIR.exists() else []
    if not candidates:
        return ProviderStatusOut(
            provider="apple_reminders",
            category="local_sqlite",
            configured=REMINDERS_DIR.exists(),
            blockers=["no_reminders_store_found"],
            notes="Requires macOS Full Disk Access for the launcher process.",
        )

    readable_errors: list[str] = []
    for candidate in candidates[:3]:
        readable, error = _sqlite_read_probe(candidate)
        if readable:
            return ProviderStatusOut(
                provider="apple_reminders",
                category="local_sqlite",
                configured=True,
                authenticated=True,
                readable=True,
                writable=False,
                notes="At least one Reminders SQLite store is readable.",
            )
        readable_errors.append(error)
    return ProviderStatusOut(
        provider="apple_reminders",
        category="local_sqlite",
        configured=True,
        blockers=[error for error in readable_errors if error],
        notes="Requires macOS Full Disk Access for the launcher process.",
    )


def _github_provider() -> ProviderStatusOut:
    from services import _github_token

    configured = _github_token() is not None
    return ProviderStatusOut(
        provider="github",
        category="external_api",
        configured=configured,
        authenticated=configured,
        readable=configured,
        writable=configured,
        blockers=[] if configured else ["missing_github_token"],
        notes="Configured credential presence only; endpoint-specific calls still validate permissions.",
    )


_GOOGLE_PROVIDER_SCOPES = {
    "google_gmail": [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.settings.basic",
    ],
    "google_calendar": ["https://www.googleapis.com/auth/calendar"],
    "google_drive": ["https://www.googleapis.com/auth/drive"],
    "google_sheets": ["https://www.googleapis.com/auth/spreadsheets"],
    "google_docs": ["https://www.googleapis.com/auth/documents"],
    "google_contacts": ["https://www.googleapis.com/auth/contacts.readonly"],
    "google_tasks": ["https://www.googleapis.com/auth/tasks"],
}


def _google_token_accounts(
    diagnostics: dict[str, Any],
    required_scopes: list[str],
) -> tuple[list[str], list[str]]:
    accounts: list[str] = []
    blockers: list[str] = []
    required = set(required_scopes)
    for token in diagnostics.get("tokens", []):
        if not isinstance(token, dict):
            continue
        missing = set(token.get("missing_scopes") or [])
        reason = str(token.get("reason") or "")
        if required and required.issubset(missing):
            blockers.append(f"{token.get('email_hint', 'unknown')}:missing_required_scopes")
            continue
        if reason in {"unreadable_token", "missing_refresh_token"}:
            blockers.append(f"{token.get('email_hint', 'unknown')}:{reason}")
            continue
        accounts.append(str(token.get("email_hint") or "unknown"))
    return accounts, blockers


def _google_provider(
    name: str,
    services: dict[str, object],
    diagnostics: dict[str, Any],
    writable: bool = True,
) -> ProviderStatusOut:
    accounts = list(services.keys())
    token_accounts, token_blockers = _google_token_accounts(
        diagnostics,
        _GOOGLE_PROVIDER_SCOPES.get(name, []),
    )
    configured = bool(accounts or token_accounts)
    blockers = list(token_blockers)
    if token_accounts and not accounts:
        blockers.append("oauth_token_present_but_service_not_loaded")
    if not configured:
        blockers.append("no_google_oauth_token_or_loaded_account")
    return ProviderStatusOut(
        provider=name,
        category="google_api",
        configured=configured,
        authenticated=bool(accounts or token_accounts),
        readable=bool(accounts),
        syncable=bool(accounts),
        writable=bool(accounts) and writable,
        accounts=accounts or token_accounts,
        blockers=blockers,
        remediation=[]
        if accounts
        else ["Run scripts/restore_google_oauth.sh, then restart or rehydrate Inbox auth."],
        notes="Uses loaded Google services when present; falls back to redacted OAuth token diagnostics for configuration state.",
    )


def _optional_db_provider(
    provider: str,
    db_path: Path | None,
    notes: str,
) -> ProviderStatusOut:
    if db_path is None:
        return ProviderStatusOut(
            provider=provider,
            category="connector_db",
            configured=False,
            blockers=["backing_store_missing"],
            notes=notes,
        )
    readable, error = _sqlite_read_probe(db_path)
    return ProviderStatusOut(
        provider=provider,
        category="connector_db",
        configured=True,
        authenticated=readable,
        readable=readable,
        syncable=readable,
        writable=False,
        blockers=[] if readable else [error],
        notes=notes,
    )


def _job_outreach_provider(providers: list[ProviderStatusOut]) -> ProviderStatusOut:
    by_name = {provider.provider: provider for provider in providers}
    gmail = by_name.get("google_gmail")
    linkedin = by_name.get("linkedin")
    configured_sources = [
        provider.provider for provider in (gmail, linkedin) if provider and provider.configured
    ]
    gmail_ready = bool(gmail and gmail.readable)
    linkedin_ready = bool(linkedin and linkedin.readable)
    blockers: list[str] = []
    if not gmail_ready:
        blockers.append("gmail_not_readable")
    if not linkedin_ready:
        blockers.append("linkedin_not_readable")
    ready = gmail_ready and linkedin_ready
    return ProviderStatusOut(
        provider="job_outreach",
        category="workflow",
        configured=bool(configured_sources),
        authenticated=ready,
        readable=ready,
        syncable=ready,
        writable=False,
        accounts=sorted(
            {account for provider in (gmail, linkedin) if provider for account in provider.accounts}
        ),
        blockers=blockers,
        remediation=[
            "Make Gmail readable for recruiter email history.",
            "Make LinkedIn linkedin_data.db readable or sync the LinkedIn export/scanner output.",
        ]
        if blockers
        else [],
        notes="Readiness for job/recruiter outreach workflows based on Gmail and LinkedIn sources only.",
    )


def _provider_recommendations(providers: list[ProviderStatusOut]) -> list[str]:
    recommendations: list[str] = []
    local_blocked = [
        provider.provider
        for provider in providers
        if provider.category == "local_sqlite" and provider.configured and not provider.readable
    ]
    if local_blocked:
        recommendations.append(
            "Grant Full Disk Access to the app that launches Inbox, then restart the server."
        )
    if any(
        provider.provider.startswith("google_") and not provider.readable for provider in providers
    ):
        recommendations.append(
            "Run scripts/restore_google_oauth.sh and reauth missing accounts if prompted."
        )
    if any(provider.provider == "github" and not provider.configured for provider in providers):
        recommendations.append("Add github_token.txt or the configured GitHub token source.")
    if any(provider.provider == "whatsapp" and not provider.configured for provider in providers):
        recommendations.append(
            "Keep WhatsApp deferred until the browser/native integration path is chosen."
        )
    return recommendations


def _provider_readiness() -> ProviderReadinessOut:
    google_diag = google_auth_diagnostics(check_refresh=False)
    providers = [
        _google_provider("google_gmail", state.gmail_services, google_diag),
        _google_provider("google_calendar", state.cal_services, google_diag),
        _google_provider("google_drive", state.drive_services, google_diag),
        _google_provider("google_sheets", state.sheets_services, google_diag),
        _google_provider("google_docs", state.docs_services, google_diag),
        _google_provider("google_contacts", {}, google_diag, writable=False),
        _google_provider("google_tasks", state.tasks_services, google_diag),
        _github_provider(),
        _local_sqlite_provider(
            "imessage",
            IMSG_DB,
            "Requires macOS Full Disk Access for the launcher process.",
        ),
        _local_sqlite_provider(
            "apple_notes",
            NOTES_DB,
            "Requires macOS Full Disk Access for the launcher process.",
        ),
        _reminders_provider(),
        _optional_db_provider(
            "whatsapp",
            _openhuman_whatsapp_db_path(),
            "Deferred connector; reports only whether a local OpenHuman backing DB is readable.",
        ),
        _optional_db_provider(
            "linkedin",
            _openhuman_linkedin_db_path(),
            "Planning connector; reports only whether a local OpenHuman backing DB is readable.",
        ),
    ]
    providers.append(_job_outreach_provider(providers))
    summary = {
        "total": len(providers),
        "ready": sum(1 for provider in providers if provider.readable),
        "blocked": sum(
            1 for provider in providers if provider.configured and not provider.readable
        ),
        "not_configured": sum(1 for provider in providers if not provider.configured),
    }
    status_text = "ok" if summary["blocked"] == 0 else "degraded"
    return ProviderReadinessOut(
        status=status_text,
        checked_at=utc_now_iso(),
        providers=providers,
        summary=summary,
        api={
            "auth_required": _non_health_auth_required(),
            "auth_configured": bool(_auth_token()),
            "dev_bypass_enabled": _auth_bypass_enabled(),
        },
        recommendations=_provider_recommendations(providers),
    )


@app.get("/status/providers", response_model=ProviderReadinessOut)
async def provider_readiness_status():
    return await asyncio.to_thread(_provider_readiness)


@app.get("/providers/status", response_model=ProviderReadinessOut)
async def provider_readiness_status_alias():
    return await asyncio.to_thread(_provider_readiness)


# ── Capture Health ───────────────────────────────────────────────────────────


def _capture_iso(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _capture_record(
    *,
    source_id: str,
    display_name: str,
    source_type: str,
    configured: bool,
    authenticated: bool = False,
    readable: bool = False,
    writable: bool = False,
    account: str = "",
    newest_seen_at: str = "",
    newest_seen_id: str = "",
    item_count: int = 0,
    last_error: str = "",
    coverage_notes: str = "",
) -> CaptureHealthRecord:
    checked_at = utc_now_iso()
    return CaptureHealthRecord(
        source_id=source_id,
        display_name=display_name,
        source_type=source_type,
        account=account,
        configured=configured,
        authenticated=authenticated,
        readable=readable,
        writable=writable,
        last_success_at=checked_at if readable else "",
        newest_seen_at=newest_seen_at,
        newest_seen_id=newest_seen_id,
        item_count=item_count,
        checked_at=checked_at,
        last_error=last_error,
        coverage_notes=coverage_notes,
    )


def _probe_collection(
    *,
    source_id: str,
    display_name: str,
    source_type: str,
    configured: bool,
    loader: Callable[[], list[Any]],
    account: str = "",
    authenticated: bool = False,
    writable: bool = False,
    newest_attr: str = "",
    id_attr: str = "id",
    coverage_notes: str = "",
) -> CaptureHealthRecord:
    if not configured:
        return _capture_record(
            source_id=source_id,
            display_name=display_name,
            source_type=source_type,
            account=account,
            configured=False,
            authenticated=authenticated,
            writable=writable,
            coverage_notes=coverage_notes,
        )

    try:
        items = list(loader() or [])
    except Exception as exc:
        return _capture_record(
            source_id=source_id,
            display_name=display_name,
            source_type=source_type,
            account=account,
            configured=True,
            authenticated=authenticated,
            writable=writable,
            last_error=str(exc),
            coverage_notes=coverage_notes,
        )

    newest_item = items[0] if items else None
    newest_seen_at = ""
    newest_seen_id = ""
    if newest_item is not None:
        if newest_attr:
            newest_seen_at = _capture_iso(getattr(newest_item, newest_attr, ""))
        newest_seen_id = str(getattr(newest_item, id_attr, "") or "")

    return _capture_record(
        source_id=source_id,
        display_name=display_name,
        source_type=source_type,
        account=account,
        configured=True,
        authenticated=authenticated,
        readable=True,
        writable=writable,
        newest_seen_at=newest_seen_at,
        newest_seen_id=newest_seen_id,
        item_count=len(items),
        coverage_notes=coverage_notes,
    )


def _build_capture_records() -> list[CaptureHealthRecord]:
    from services import _github_token

    google_diag = google_auth_diagnostics(check_refresh=False)
    google_causes = google_diag.get("likely_causes", [])
    google_note = ", ".join(str(cause) for cause in google_causes) or "no loaded service"

    records: list[CaptureHealthRecord] = [
        _probe_collection(
            source_id="imessage",
            display_name="iMessage",
            source_type="local_db",
            configured=IMSG_DB.exists(),
            loader=lambda: imsg_contacts(limit=1),
            newest_attr="last_ts",
            coverage_notes=f"Reads local Messages SQLite database: {IMSG_DB}",
        ),
        _probe_collection(
            source_id="apple_notes",
            display_name="Apple Notes",
            source_type="local_db",
            configured=NOTES_DB.exists(),
            loader=lambda: notes_list(limit=1),
            newest_attr="modified",
            coverage_notes=f"Reads local Notes SQLite database: {NOTES_DB}",
        ),
        _probe_collection(
            source_id="apple_reminders",
            display_name="Apple Reminders",
            source_type="local_db",
            configured=REMINDERS_DIR.exists(),
            loader=lambda: reminders_list(limit=1),
            newest_attr="creation_date",
            writable=True,
            coverage_notes=f"Reads local Reminders stores under: {REMINDERS_DIR}",
        ),
        _probe_collection(
            source_id="whatsapp",
            display_name="WhatsApp",
            source_type="openhuman_or_accessibility",
            configured=bool(_openhuman_whatsapp_db_path())
            or whatsapp_check_accessibility(prompt=False),
            loader=lambda: whatsapp_contacts(limit=1),
            newest_attr="last_ts",
            coverage_notes="Reads OpenHuman WhatsApp export first, then macOS Accessibility fallback.",
        ),
        _probe_collection(
            source_id="linkedin",
            display_name="LinkedIn",
            source_type="openhuman",
            configured=bool(_openhuman_linkedin_db_path()),
            loader=lambda: linkedin_contacts(limit=1),
            newest_attr="last_ts",
            coverage_notes="Reads local OpenHuman LinkedIn messaging export.",
        ),
    ]

    if not state.gmail_services:
        records.append(
            _capture_record(
                source_id="gmail",
                display_name="Gmail",
                source_type="google_api",
                configured=False,
                writable=True,
                coverage_notes=f"No Gmail service loaded; Google auth: {google_note}.",
            )
        )
    for account, svc in state.gmail_services.items():
        records.append(
            _probe_collection(
                source_id="gmail",
                display_name="Gmail",
                source_type="google_api",
                account=account,
                configured=True,
                authenticated=True,
                loader=lambda svc=svc, account=account: gmail_contacts(svc, account, limit=1),
                newest_attr="last_ts",
                writable=True,
                coverage_notes="Provider probe lists the newest Gmail conversation for this account.",
            )
        )

    if not state.cal_services:
        records.append(
            _capture_record(
                source_id="google_calendar",
                display_name="Google Calendar",
                source_type="google_api",
                configured=False,
                writable=True,
                coverage_notes=f"No Calendar service loaded; Google auth: {google_note}.",
            )
        )
    for account, svc in state.cal_services.items():
        records.append(
            _probe_collection(
                source_id="google_calendar",
                display_name="Google Calendar",
                source_type="google_api",
                account=account,
                configured=True,
                authenticated=True,
                loader=lambda svc=svc: calendar_events({"_capture": svc})[:1],
                newest_attr="start",
                writable=True,
                coverage_notes="Provider probe lists one upcoming calendar event.",
            )
        )

    if not state.tasks_services:
        records.append(
            _capture_record(
                source_id="google_tasks",
                display_name="Google Tasks",
                source_type="google_api",
                configured=False,
                writable=True,
                coverage_notes=f"No Tasks service loaded; Google auth: {google_note}.",
            )
        )
    for account, svc in state.tasks_services.items():
        records.append(
            _probe_collection(
                source_id="google_tasks",
                display_name="Google Tasks",
                source_type="google_api",
                account=account,
                configured=True,
                authenticated=True,
                loader=lambda svc=svc: tasks_list(svc, limit=1),
                newest_attr="due",
                writable=True,
                coverage_notes="Provider probe lists one task from @default.",
            )
        )

    if not state.drive_services:
        records.extend(
            [
                _capture_record(
                    source_id="google_drive",
                    display_name="Google Drive",
                    source_type="google_api",
                    configured=False,
                    writable=True,
                    coverage_notes=f"No Drive service loaded; Google auth: {google_note}.",
                ),
                _capture_record(
                    source_id="google_sheets",
                    display_name="Google Sheets",
                    source_type="google_api",
                    configured=False,
                    writable=True,
                    coverage_notes=f"No Drive service loaded; Sheets discovery uses Drive. Google auth: {google_note}.",
                ),
                _capture_record(
                    source_id="google_docs",
                    display_name="Google Docs",
                    source_type="google_api",
                    configured=False,
                    writable=True,
                    coverage_notes=f"No Drive service loaded; Docs discovery uses Drive. Google auth: {google_note}.",
                ),
            ]
        )
    for account, svc in state.drive_services.items():
        records.extend(
            [
                _probe_collection(
                    source_id="google_drive",
                    display_name="Google Drive",
                    source_type="google_api",
                    account=account,
                    configured=True,
                    authenticated=True,
                    loader=lambda svc=svc: drive_files(svc, limit=1),
                    newest_attr="modified",
                    writable=True,
                    coverage_notes="Provider probe lists newest non-trashed Drive file.",
                ),
                _probe_collection(
                    source_id="google_sheets",
                    display_name="Google Sheets",
                    source_type="google_api",
                    account=account,
                    configured=True,
                    authenticated=True,
                    loader=lambda svc=svc, account=account: sheets_list(
                        svc, limit=1, account=account
                    ),
                    writable=account in state.sheets_services,
                    coverage_notes="Provider probe lists spreadsheets through Drive.",
                ),
                _probe_collection(
                    source_id="google_docs",
                    display_name="Google Docs",
                    source_type="google_api",
                    account=account,
                    configured=True,
                    authenticated=True,
                    loader=lambda svc=svc, account=account: docs_list(
                        svc, limit=1, account=account
                    ),
                    writable=account in state.docs_services,
                    coverage_notes="Provider probe lists Docs through Drive.",
                ),
            ]
        )

    records.append(
        _probe_collection(
            source_id="github_notifications",
            display_name="GitHub Notifications",
            source_type="external_api",
            configured=_github_token() is not None,
            authenticated=_github_token() is not None,
            loader=lambda: github_notifications(all_notifs=False)[:1],
            newest_attr="updated_at",
            coverage_notes="Provider probe lists unread GitHub notifications.",
        )
    )

    return records


def _refresh_capture_status() -> CaptureStatusOut:
    for record in _build_capture_records():
        state.capture_health_store.upsert(record)
    rows = state.capture_health_store.list_records()
    return CaptureStatusOut(
        db_path=str(state.capture_health_store.db_path),
        checked_at=utc_now_iso(),
        summary=capture_summary(rows),
        sources=[CaptureSourceOut(**row) for row in rows],
    )


def _capture_health_reasons(sources: list[CaptureSourceOut]) -> list[str]:
    reasons: list[str] = []
    if not sources:
        reasons.append("no_capture_state")
    for source in sources:
        if source.status == "error":
            reasons.append(f"{source.key}:capture_error")
        elif source.status == "not_configured":
            reasons.append(f"{source.key}:not_configured")
    return reasons


@app.get("/capture/status", response_model=CaptureStatusOut)
async def get_capture_status():
    return await asyncio.to_thread(_refresh_capture_status)


@app.get("/capture/health", response_model=CaptureHealthOut)
async def get_capture_health():
    capture_status = await asyncio.to_thread(_refresh_capture_status)
    reasons = _capture_health_reasons(capture_status.sources)
    return CaptureHealthOut(
        **capture_status.model_dump(),
        healthy=not reasons,
        reasons=reasons,
    )


# ── Egress Audit ─────────────────────────────────────────────────────────────


@app.post("/events/capture")
async def capture_event(req: CaptureEventRequest):
    """Append one raw observation. Local evidence only. Not a grant.

    201 created. 200 already_exists (same id and digest; original receipt).
    409 when the same id is reused with a different digest.
    422 malformed, untrusted locator, or unused id that is not the digest identity.
    413 oversized payload.
    """
    try:
        event = CaptureEvent.create(
            source=req.source,
            source_object_id=req.source_object_id,
            observed_at=req.observed_at,
            occurred_at=req.occurred_at,
            event_type=req.event_type,
            payload=req.payload,
            provenance=req.provenance,
            event_id=req.event_id or None,
        )
        stored, result = await asyncio.to_thread(state.event_store.append, event)
    except EventStoreConflict as exc:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"result": "error", "error": str(exc), "event": None},
        )
    except EventStoreValidationError as exc:
        code = (
            status.HTTP_413_CONTENT_TOO_LARGE
            if "oversized" in str(exc)
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        return JSONResponse(
            status_code=code,
            content={"result": "error", "error": str(exc), "event": None},
        )
    payload = CaptureEventOut(
        result=result,
        event=CapturedEventOut(**stored.to_dict()),
    )
    status_code = status.HTTP_201_CREATED if result == "created" else status.HTTP_200_OK
    return JSONResponse(status_code=status_code, content=payload.model_dump())


@app.get("/egress/status")
async def get_egress_status():
    return egress_audit.status()


@app.get("/egress/audit")
async def get_egress_audit(limit: int = 100):
    return {
        **egress_audit.status(),
        "events": await asyncio.to_thread(egress_audit.audit_store().list_recent, limit),
    }


# ── Conversations ────────────────────────────────────────────────────────────


async def _fetch_conversations(source: str, limit: int, account: str = "") -> list[Contact]:
    """Fetch conversations from all requested sources in parallel.

    iMessage and Gmail fetches run concurrently via asyncio.gather().
    Multiple Gmail accounts are also fetched concurrently.
    """
    fetch_tasks: list[asyncio.Task[list[Contact]]] = []

    if source in ("all", "imessage"):
        fetch_tasks.append(asyncio.create_task(asyncio.to_thread(imsg_contacts, limit=limit)))

    if source in ("all", "gmail"):
        targets = (
            {account: state.gmail_services[account]}
            if account and account in state.gmail_services
            else state.gmail_services
        )
        for email, svc in targets.items():
            fetch_tasks.append(
                asyncio.create_task(asyncio.to_thread(gmail_contacts, svc, email, limit=limit))
            )

    if source in ("all", "linkedin"):
        fetch_tasks.append(asyncio.create_task(asyncio.to_thread(linkedin_contacts, limit=limit)))

    if source in ("all", "whatsapp"):
        fetch_tasks.append(asyncio.create_task(asyncio.to_thread(whatsapp_contacts, limit=limit)))

    if not fetch_tasks:
        return []

    result_lists = await asyncio.gather(*fetch_tasks)
    results: list[Contact] = []
    for contacts in result_lists:
        results.extend(contacts)

    return results


@app.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(source: str = "all", limit: int = 50, account: str = ""):
    results = await _fetch_conversations(source, limit, account)

    def _sort_ts(contact: Contact) -> float:
        value = contact.last_ts
        if isinstance(value, datetime):
            if value.tzinfo is not None:
                value = value.astimezone(UTC).replace(tzinfo=None)
            return value.timestamp()
        return 0.0

    results.sort(key=_sort_ts, reverse=True)

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
    elif source == "linkedin":
        msgs = await asyncio.to_thread(linkedin_thread, conv_id, limit=limit)
    elif source == "whatsapp":
        msgs = await asyncio.to_thread(whatsapp_thread, conv_id, limit=limit)
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
    return _gacct.get_gmail_service(state, msg_id, _cache_key)


def _get_gmail_service_for_account(account: str = "") -> tuple[str, object]:
    return _gacct.get_gmail_service_for_account(state, account)


_gmail_message_or_thread_exists = _gacct.gmail_message_or_thread_exists


def _get_gmail_service_for_message(
    msg_id: str = "",
    thread_id: str = "",
    account: str = "",
) -> tuple[str, object]:
    return _gacct.get_gmail_service_for_message(
        state, msg_id, thread_id, account, cache_key=_cache_key
    )


def _get_sheets_service_for_account(account: str = "") -> tuple[str, object]:
    return _gacct.get_sheets_service_for_account(state, account)


def _get_drive_service_for_account(account: str = "") -> tuple[str, object]:
    return _gacct.get_drive_service_for_account(state, account)


def _get_tasks_service_for_account(account: str = "") -> tuple[str, object]:
    return _gacct.get_tasks_service_for_account(state, account)


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
    acct, svc = _get_gmail_service_for_message(req.msg_id, req.thread_id, req.account)
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
            state.source_adapters.gmail.search,
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


# ── Thread summaries ───────────────────────────────────────────────────────────


@app.get("/gmail/threads/{thread_id}/summary", response_model=GmailThreadSummaryOut)
async def get_gmail_thread_summary(thread_id: str, account: str = ""):
    acct, svc = _get_gmail_service_for_message(thread_id=thread_id, account=account)
    ts = await asyncio.to_thread(gmail_thread_summary, svc, thread_id, acct)
    if ts is None:
        raise HTTPException(404, "Thread not found")
    label_data = await asyncio.to_thread(gmail_labels, svc)
    label_map = {lbl["id"]: lbl["name"] for lbl in label_data}
    return _thread_summary_to_out(ts, label_map)


@app.get("/gmail/thread-summaries", response_model=list[GmailThreadSummaryOut])
async def search_gmail_thread_summaries(
    q: str = "",
    workflow: str = "",
    needs_reply: bool | None = None,
    account: str = "",
    limit: int = 20,
):
    """Search Gmail and return normalized thread summaries with workflow tags."""
    acct, svc = _get_gmail_service_for_account(account)
    contacts = await asyncio.to_thread(gmail_search, svc, acct, q, limit * 3)
    seen: set[str] = set()
    summaries: list[GmailThreadSummaryOut] = []
    for c in contacts:
        tid = c.thread_id or c.id
        if tid in seen:
            continue
        seen.add(tid)
        ts = _contact_to_thread_summary(c)
        if workflow and ts.workflow != workflow:
            continue
        if needs_reply is not None and ts.needs_reply != needs_reply:
            continue
        summaries.append(ts)
    summaries.sort(key=lambda t: t.rank, reverse=True)
    return summaries[:limit]


@app.get("/gmail/thread-briefs", response_model=list[ThreadBriefOut])
async def get_gmail_thread_briefs(
    q: str = "",
    workflow: str = "",
    needs_reply: bool | None = None,
    account: str = "",
    limit: int = 20,
):
    """Ultra-compact thread list for triage — brief + rank only, no body or participants."""
    acct, svc = _get_gmail_service_for_account(account)
    contacts = await asyncio.to_thread(gmail_search, svc, acct, q, limit * 3)
    seen: set[str] = set()
    raw: list[GmailThreadSummaryOut] = []
    for c in contacts:
        tid = c.thread_id or c.id
        if tid in seen:
            continue
        seen.add(tid)
        ts = _contact_to_thread_summary(c)
        if workflow and ts.workflow != workflow:
            continue
        if needs_reply is not None and ts.needs_reply != needs_reply:
            continue
        raw.append(ts)
    raw.sort(key=lambda t: t.rank, reverse=True)
    return [
        ThreadBriefOut(
            thread_id=t.thread_id,
            brief=t.brief,
            rank=t.rank,
            workflow=t.workflow,
            needs_reply=t.needs_reply,
        )
        for t in raw[:limit]
    ]


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
            state.source_adapters.calendar.events,
            state.cal_services,
            start_date=start_dt,
            end_date=end_dt,
        )
    else:
        dt = datetime.fromisoformat(date) if date else None
        evts = await asyncio.to_thread(
            state.source_adapters.calendar.events, state.cal_services, dt
        )
    state.events_cache = evts
    return [_event_to_out(e) for e in evts]


@app.get("/calendar/upcoming", response_model=list[CalendarEventOut])
async def list_upcoming_events(days: int = 7, limit: int = 50, account: str = ""):
    days = max(1, min(days, 30))
    limit = max(1, min(limit, 200))
    services = state.cal_services
    if account:
        services = {account: state.cal_services[account]} if account in state.cal_services else {}
    start_dt = datetime.now()
    end_dt = start_dt + timedelta(days=days - 1)
    evts = await asyncio.to_thread(
        state.source_adapters.calendar.events,
        services,
        start_date=start_dt,
        end_date=end_dt,
    )
    evts = evts[:limit]
    state.events_cache = evts
    return [_event_to_out(e) for e in evts]


@app.post("/calendar/events")
async def create_event(req: CreateEventRequest):
    account, svc = _get_cal_service_for_account(req.account)

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
    account, svc = _get_cal_service_for_account(req.account)

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
    acct, svc = _get_cal_service_for_account(account)

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
    acct, svc = _get_cal_service_for_account(account)

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


@app.post("/reminders/{reminder_id}/uncomplete")
async def uncomplete_reminder(reminder_id: str):
    reminder = await asyncio.to_thread(reminder_by_id, reminder_id)
    if not reminder:
        raise HTTPException(404, "Reminder not found")
    ok = await asyncio.to_thread(reminder_uncomplete, reminder.title, reminder.list_name)
    return {"ok": ok}


@app.post("/reminders")
async def create_reminder(req: ReminderCreateRequest):
    ok = await asyncio.to_thread(
        reminder_create,
        title=req.title,
        list_name=req.list_name,
        due_date=req.due_date,
        notes=req.notes,
        priority=req.priority,
        flagged=req.flagged,
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
        priority=req.priority,
        flagged=req.flagged,
    )
    return {"ok": ok}


@app.delete("/reminders/{reminder_id}")
async def delete_reminder(reminder_id: str):
    reminder = await asyncio.to_thread(reminder_by_id, reminder_id)
    if not reminder:
        raise HTTPException(404, "Reminder not found")
    ok = await asyncio.to_thread(reminder_delete, reminder.title, reminder.list_name)
    return {"ok": ok}


# ── Google Tasks ─────────────────────────────────────────────────────────────


@app.get("/tasks/lists", response_model=list[dict])
async def list_task_lists(account: str = ""):
    _, svc = _get_tasks_service_for_account(account)
    return await asyncio.to_thread(tasks_lists, svc)


@app.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    list_id: str = "@default",
    show_completed: bool = False,
    limit: int = 100,
    account: str = "",
    workflow: str = "",
):
    acct, svc = _get_tasks_service_for_account(account)
    raw = await asyncio.to_thread(tasks_list, svc, list_id, show_completed, limit)
    out = [_task_to_out(t, acct) for t in raw]
    if workflow:
        out = [t for t in out if t.workflow == workflow]
    return out


@app.post("/tasks")
async def create_task(req: TaskCreateRequest, account: str = ""):
    _, svc = _get_tasks_service_for_account(account)
    result = await asyncio.to_thread(
        task_create,
        svc,
        req.title,
        req.list_id,
        req.due,
        req.notes,
        req.idempotency_key,
    )
    if not isinstance(result, dict):
        result = {"ok": bool(result), "task_id": "", "list_id": req.list_id}
    return result


@app.post("/tasks/{task_id}/complete")
async def complete_task(task_id: str, list_id: str = "@default", account: str = ""):
    _, svc = _get_tasks_service_for_account(account)
    ok = await asyncio.to_thread(task_complete, svc, task_id, list_id)
    return {"ok": ok}


@app.put("/tasks/{task_id}")
async def update_task(
    task_id: str, req: TaskUpdateRequest, list_id: str = "@default", account: str = ""
):
    _, svc = _get_tasks_service_for_account(account)
    ok = await asyncio.to_thread(task_update, svc, task_id, list_id, req.title, req.due, req.notes)
    return {"ok": ok}


@app.delete("/tasks/{task_id}")
async def delete_task(task_id: str, list_id: str = "@default", account: str = ""):
    _, svc = _get_tasks_service_for_account(account)
    ok = await asyncio.to_thread(task_delete, svc, task_id, list_id)
    return {"ok": ok}


# ── Scheduled Messages ───────────────────────────────────────────────────────


@app.get("/scheduled")
async def list_scheduled_messages(status: str = "pending"):
    return await asyncio.to_thread(state.scheduler.list_scheduled, status)


@app.post("/scheduled")
async def create_scheduled_message(req: ScheduleMessageRequest):
    result = await asyncio.to_thread(
        state.scheduler.schedule_message,
        req.source,
        req.conv_id,
        req.text,
        req.send_at,
        req.account,
    )
    return result


@app.delete("/scheduled/{msg_id}")
async def cancel_scheduled_message(msg_id: int):
    ok = await asyncio.to_thread(state.scheduler.cancel_scheduled, msg_id)
    return {"ok": ok}


# ── Follow-up Reminders ──────────────────────────────────────────────────────


@app.get("/followups")
async def list_followup_reminders(status: str = "active"):
    return await asyncio.to_thread(state.scheduler.list_followups, status)


@app.post("/followups")
async def create_followup_reminder(req: FollowupCreateRequest):
    result = await asyncio.to_thread(
        state.scheduler.create_followup,
        req.source,
        req.conv_id,
        req.thread_id,
        req.remind_after,
        req.reminder_title,
        req.reminder_list,
    )
    return result


@app.delete("/followups/{fid}")
async def cancel_followup_reminder(fid: int):
    ok = await asyncio.to_thread(state.scheduler.cancel_followup, fid)
    return {"ok": ok}


# ── Approvals & Audit Log ─────────────────────────────────────────────────────
#
# Wires up mint_local_approval_lease()/_approval_decision_for_request() (which
# already gate every guarded write, see APPROVAL_ROUTE_RULES above) to an
# actual human-in-the-loop flow: a caller describes the pending action here,
# the captain decides, and only on approval does a lease get minted. Nothing
# here weakens the gate -- it is the only place outside tests that calls
# mint_local_approval_lease(), and it only does so after an explicit decision
# is recorded in the audit log.


@app.post("/approvals/request")
async def create_approval_request(req: ApprovalRequestIn):
    """Record a pending guarded action for the captain to approve/deny.

    Does NOT mint a lease. Caller polls GET /approvals/{request_id} (or is
    notified some other way) and, once state == "approved", reads the
    lease_id and supplies it as the X-Inbox-Approval-Lease header on the
    real request.
    """
    method = req.method.upper()
    if method not in APPROVAL_GUARDED_METHODS:
        raise HTTPException(400, f"{method} is not a guarded method")
    try:
        ctx = await asyncio.to_thread(_approval_context_for_action, method, req.path, req.body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    rule: ApprovalRouteRule = ctx["rule"]
    row = await asyncio.to_thread(
        state.approvals.create_request,
        method=method,
        # Store the *full* path including query string -- mint_local_approval_lease()
        # re-derives the query_hash from it on approval, so dropping the query
        # here would let the recorded request silently cover a different query
        # than the one the captain actually saw and approved.
        path=req.path,
        body=req.body,
        provider=rule.provider,
        operation=rule.operation,
        approval_class=rule.approval_class,
        executor=rule.executor,
        account_ref=ctx["account_ref"],
        resource_ref=ctx["resource_ref"],
        item_count=ctx["item_count"],
        payload_hash=ctx["payload_hash"],
        query_hash=ctx["query_hash"],
    )
    await asyncio.to_thread(
        state.approvals.log_event,
        "approval_requested",
        request_id=row["request_id"],
        method=method,
        path=ctx["request_path"],
        provider=rule.provider,
        operation=rule.operation,
        account=ctx["account_ref"],
        resource=ctx["resource_ref"],
        payload_hash=ctx["payload_hash"],
        actor=req.body.get("__actor", "") if isinstance(req.body, dict) else "",
        result="pending",
    )
    return row


@app.get("/approvals")
async def list_approval_requests(
    state_filter: str = Query("pending", alias="state"), limit: int = 100
):
    return await asyncio.to_thread(state.approvals.list_requests, state_filter or None, limit)


@app.get("/approvals/{request_id}")
async def get_approval_request(request_id: str):
    row = await asyncio.to_thread(state.approvals.get_request, request_id)
    if row is None:
        raise HTTPException(404, "approval request not found")
    return row


@app.post("/approvals/{request_id}/decide")
async def decide_approval_request(request_id: str, req: ApprovalDecisionIn):
    """Captain (or an interactive script acting on the captain's behalf)
    approves or denies a pending request. On approval, mints the real lease
    server-side from the exact recorded action -- the caller never gets to
    choose what the lease covers."""
    row = await asyncio.to_thread(state.approvals.get_request, request_id)
    if row is None:
        raise HTTPException(404, "approval request not found")
    if row["state"] != "pending":
        raise HTTPException(409, f"approval request already {row['state']}")

    lease_id = ""
    if req.approve:
        body = json.loads(row["body_json"] or "{}")
        lease_id = await asyncio.to_thread(
            mint_local_approval_lease, row["method"], row["path"], body=body
        )

    updated = await asyncio.to_thread(
        state.approvals.decide_request,
        request_id,
        approved=bool(req.approve),
        decided_by=req.decided_by,
        lease_id=lease_id,
        denial_reason=req.denial_reason,
    )
    if updated is None:
        raise HTTPException(409, "approval request was decided concurrently")

    await asyncio.to_thread(
        state.approvals.log_event,
        "approval_decided",
        request_id=request_id,
        lease_id=lease_id,
        method=row["method"],
        path=row["path"],
        provider=row["provider"],
        operation=row["operation"],
        account=row["account_ref"],
        resource=row["resource_ref"],
        payload_hash=row["payload_hash"],
        actor=req.decided_by,
        result="approved" if req.approve else "denied",
        detail={"denial_reason": req.denial_reason} if not req.approve else {},
    )
    if lease_id:
        await asyncio.to_thread(
            state.approvals.log_event,
            "lease_minted",
            request_id=request_id,
            lease_id=lease_id,
            method=row["method"],
            path=row["path"],
            provider=row["provider"],
            operation=row["operation"],
            account=row["account_ref"],
            resource=row["resource_ref"],
            payload_hash=row["payload_hash"],
            actor=req.decided_by,
            result="minted",
        )
    return updated


@app.get("/audit/log")
async def get_audit_log(limit: int = 200, event_type: str = "", request_id: str = ""):
    return await asyncio.to_thread(
        state.approvals.list_audit_log,
        limit=limit,
        event_type=event_type or None,
        request_id=request_id or None,
    )


# ── Task ↔ Message Links ─────────────────────────────────────────────────────


@app.get("/tasks/links")
async def list_task_links(
    message_id: str = "",
    message_source: str = "",
    task_id: str = "",
    task_source: str = "",
):
    if message_id and message_source:
        return await asyncio.to_thread(
            state.scheduler.links_for_message, message_id, message_source
        )
    if task_id and task_source:
        return await asyncio.to_thread(state.scheduler.links_for_task, task_id, task_source)
    raise HTTPException(400, "Must provide (message_id, message_source) OR (task_id, task_source)")


@app.post("/tasks/links")
async def create_task_link(req: TaskLinkRequest):
    result = await asyncio.to_thread(
        state.scheduler.link_task,
        req.task_id,
        req.task_source,
        req.message_id,
        req.message_source,
        req.thread_id,
        req.account,
    )
    return result


@app.delete("/tasks/links/{link_id}")
async def delete_task_link(link_id: int):
    ok = await asyncio.to_thread(state.scheduler.unlink_task, link_id)
    return {"ok": ok}


@app.post("/tasks/from-message")
async def create_task_from_message(req: TaskFromMessageRequest):
    """Create a task from a message and auto-link it."""
    task_id = ""
    if req.task_type == "google_tasks":
        _, svc = _get_tasks_service_for_account(req.account)
        # Include message reference in notes
        notes = req.notes
        if req.message_source == "gmail":
            notes = f"{notes}\n\nFrom email: {req.message_id}".strip()
        created = await asyncio.to_thread(task_create, svc, req.title, req.list_id, "", notes)
        if not (isinstance(created, dict) and created.get("ok") and created.get("task_id")):
            raise HTTPException(500, "Failed to create Google Task")
        task_id = str(created["task_id"])
    elif req.task_type == "reminders":
        notes = req.notes
        if req.message_source == "gmail":
            notes = f"{notes}\n\nFrom email: {req.message_id}".strip()
        ok = await asyncio.to_thread(reminder_create, req.title, req.list_name, "", notes, 0, False)
        if not ok:
            raise HTTPException(500, "Failed to create Reminder")
        # Reminder ids come from SQLite Z_PK — not easy to get the just-created one
        task_id = req.title  # fallback: use title as identifier
    else:
        raise HTTPException(400, f"Unknown task_type: {req.task_type}")

    # Auto-link
    link = await asyncio.to_thread(
        state.scheduler.link_task,
        task_id,
        req.task_type,
        req.message_id,
        req.message_source,
        req.thread_id,
        req.account,
    )
    return {"ok": True, "task_id": task_id, "link": link}


# ── Gemini AI ────────────────────────────────────────────────────────────────


@app.post("/ai/gemini-summarize")
async def ai_gemini_summarize(messages: list[dict]):
    result = await asyncio.to_thread(gemini_summarize, messages)
    if result is None:
        raise HTTPException(502, "Gemini summarization failed")
    return {"summary": result}


@app.post("/ai/smart-reply")
async def ai_gemini_smart_reply(messages: list[dict], num_replies: int = 3):
    replies = await asyncio.to_thread(gemini_smart_reply, messages, num_replies)
    return {"replies": replies}


@app.post("/ai/categorize")
async def ai_gemini_categorize(emails: list[dict]):
    categories = await asyncio.to_thread(gemini_categorize, emails)
    return {"categories": categories}


@app.post("/ai/digest")
async def ai_gemini_digest():
    """Generate morning digest from all sources."""
    # Gather data from all sources
    emails_raw = await _fetch_conversations("gmail", limit=20)
    emails = [
        {"name": c.name, "snippet": c.snippet, "id": c.id} for c in emails_raw if c.unread > 0
    ]

    events_raw = await asyncio.to_thread(calendar_events, state.cal_services)
    events = [
        {"summary": e.summary, "start": e.start.isoformat(), "location": e.location}
        for e in events_raw
    ]

    tasks_data = []
    if state.tasks_services:
        try:
            _, svc = _get_tasks_service_for_account("")
            tasks_raw = await asyncio.to_thread(tasks_list, svc, "@default", False, 20)
            tasks_data = [
                {"title": t.title, "due": t.due.isoformat() if t.due else ""} for t in tasks_raw
            ]
        except Exception:
            pass

    rem_raw = await asyncio.to_thread(reminders_list, limit=20)
    reminders_data = [
        {"title": r.title, "due_date": r.due_date.isoformat() if r.due_date else ""}
        for r in rem_raw
    ]

    notifs = await asyncio.to_thread(github_notifications)
    notifs_data = [{"title": n.title, "repo": n.repo, "type": n.type} for n in notifs if n.unread]

    result = await asyncio.to_thread(
        gemini_digest, emails, events, tasks_data, reminders_data, notifs_data
    )
    if result is None:
        raise HTTPException(502, "Gemini digest failed")
    return {"digest": result}


@app.post("/ai/action-items")
async def ai_gemini_action_items(messages: list[dict]):
    items = await asyncio.to_thread(gemini_extract_action_items, messages)
    return {"action_items": items}


# ── Departure Times (Google Maps) ────────────────────────────────────────────


@app.get("/calendar/departure-times")
async def get_departure_times(
    origin: str = "",
    mode: str = "driving",
    buffer_minutes: int = 10,
    lookahead_hours: int = 24,
):
    """Calculate when to leave for upcoming calendar events with locations.

    Args:
        origin: Your starting address (home/office). If empty, uses INBOX_HOME_ADDRESS env var.
        mode: "driving" | "transit" | "walking" | "bicycling"
        buffer_minutes: Extra buffer time on top of travel estimate.
        lookahead_hours: Only check events within this many hours ahead.
    """
    # Try live location first, then env var, then error
    home = origin
    if not home:
        home = await asyncio.to_thread(get_current_location)
    if not home:
        raise HTTPException(
            400,
            "No origin. Set INBOX_HOME_ADDRESS env var, grant Location Services, or pass ?origin=",
        )

    # Fetch today's events from all calendar accounts
    events = await asyncio.to_thread(calendar_events, state.cal_services)
    departures = await asyncio.to_thread(
        departure_times_for_events,
        events,
        home,
        mode,
        buffer_minutes,
        lookahead_hours,
    )
    return [
        {
            "event_summary": d.event_summary,
            "event_start": d.event_start.isoformat(),
            "event_location": d.event_location,
            "travel_minutes": d.travel_minutes,
            "departure_time": d.departure_time.isoformat(),
            "distance_text": d.distance_text,
            "duration_text": d.duration_text,
            "mode": d.mode,
        }
        for d in departures
    ]


@app.get("/maps/travel-time")
async def get_travel_time(
    origin: str,
    destination: str,
    mode: str = "driving",
    avoid: str | None = None,
    units: str = "imperial",
):
    """Get travel time between two locations.

    Args:
        avoid: "tolls", "highways", "ferries", or combo like "tolls|highways".
        units: "imperial" (miles) or "metric" (km).
    """
    result = await asyncio.to_thread(
        maps_travel_time, origin, destination, mode, None, avoid, units
    )
    if not result:
        raise HTTPException(502, "Could not get travel time — check Maps API key and addresses")
    return result


# ── WhatsApp ─────────────────────────────────────────────────────────────────


@app.get("/whatsapp/status")
async def whatsapp_status():
    """Return WhatsApp app state + Accessibility permission status."""
    from services import _whatsapp_pid

    pid = await asyncio.to_thread(_whatsapp_pid)
    trusted = await asyncio.to_thread(whatsapp_check_accessibility, False)
    return {"running": pid is not None, "pid": pid, "accessibility_granted": trusted}


@app.post("/whatsapp/launch")
async def launch_whatsapp(prompt_permission: bool = False):
    """Launch WhatsApp.app. If prompt_permission=True, also shows the macOS Accessibility dialog."""
    running = await asyncio.to_thread(whatsapp_launch, 5.0)
    trusted = await asyncio.to_thread(whatsapp_check_accessibility, prompt_permission)
    return {"running": running, "accessibility_granted": trusted}


@app.post("/whatsapp/send")
async def send_whatsapp(payload: dict):
    """Send a WhatsApp message. Body: {"chat_name": str, "text": str}."""
    chat = payload.get("chat_name", "").strip()
    text = payload.get("text", "").strip()
    if not chat or not text:
        raise HTTPException(400, "chat_name and text required")
    ok = await asyncio.to_thread(whatsapp_send, chat, text)
    if not ok:
        raise HTTPException(
            502, "send failed (app not running, chat not visible, or permission missing)"
        )
    return {"sent": True, "chat_name": chat}


@app.post("/whatsapp/scroll")
async def scroll_whatsapp(pages: int = 1):
    """Scroll the WhatsApp sidebar down N pages so more chats render."""
    done = await asyncio.to_thread(whatsapp_scroll_sidebar, pages)
    return {"pages_scrolled": done}


@app.get("/whatsapp/contacts/all", response_model=list[ConversationOut])
async def list_all_whatsapp_contacts(max_pages: int = 10):
    """Scroll the sidebar to collect all reachable chats (deduplicated)."""
    contacts = await asyncio.to_thread(whatsapp_contacts_all, max_pages)
    return [
        ConversationOut(
            id=c.id,
            name=c.name,
            source=c.source,
            snippet=c.snippet,
            unread=c.unread,
            last_ts=c.last_ts.isoformat(),
            guid=c.guid,
            is_group=c.is_group,
            members=c.members,
        )
        for c in contacts
    ]


@app.get("/whatsapp/messages/{chat_name}/full", response_model=list[MessageOut])
async def get_whatsapp_messages_full(chat_name: str, max_loads: int = 10, limit: int = 500):
    """Fetch full WhatsApp chat history via repeated 'Load more messages'."""
    messages = await asyncio.to_thread(whatsapp_thread_full, chat_name, max_loads, limit)
    return [
        MessageOut(
            sender=m.sender,
            body=m.body,
            ts=m.ts.isoformat(),
            is_me=m.is_me,
            source=m.source,
            attachments=m.attachments,
            message_id=m.message_id,
        )
        for m in messages
    ]


@app.get("/whatsapp/contacts", response_model=list[ConversationOut])
async def list_whatsapp_contacts(limit: int = 20):
    """List WhatsApp conversations via macOS Accessibility API (read-only).
    WhatsApp app must be running. Returns empty list if app is not running or AX tree inspection fails.
    """
    contacts = await asyncio.to_thread(whatsapp_contacts, limit)
    return [
        ConversationOut(
            id=c.id,
            name=c.name,
            source=c.source,
            snippet=c.snippet,
            unread=c.unread,
            last_ts=c.last_ts.isoformat(),
            guid=c.guid,
            is_group=c.is_group,
            members=c.members,
        )
        for c in contacts
    ]


@app.get("/whatsapp/messages/{chat_name}", response_model=list[MessageOut])
async def get_whatsapp_messages(chat_name: str, limit: int = 50):
    """Fetch WhatsApp messages for a conversation.
    chat_name: Name of the conversation.
    limit: Max messages to return.
    Placeholder: returns empty list pending AX tree navigation implementation.
    """
    messages = await asyncio.to_thread(whatsapp_thread, chat_name, limit)
    return [
        MessageOut(
            sender=m.sender,
            body=m.body,
            ts=m.ts.isoformat(),
            is_me=m.is_me,
            source=m.source,
            attachments=m.attachments,
            message_id=m.message_id,
        )
        for m in messages
    ]


# ── iMessage ─────────────────────────────────────────────────────────────────


def _parse_imessage_date(value: str, *, end: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(400, f"Invalid date: {value}") from exc
    if len(value) == 10:
        parsed = parsed.replace(tzinfo=UTC)
        if end:
            parsed += timedelta(days=1)
    elif parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


@app.get("/imessage", response_model=list[IMessageOut])
async def get_imessage(
    contact: str = "",
    date: str = "",
    start_date: str = "",
    end_date: str = "",
    limit: int = 100,
):
    """Read iMessages, optionally filtered by contact and ISO date range."""
    if date and (start_date or end_date):
        raise HTTPException(400, "Use date or start_date/end_date, not both")
    if limit < 1 or limit > 1000:
        raise HTTPException(400, "limit must be between 1 and 1000")

    range_start = _parse_imessage_date(date or start_date)
    range_end = _parse_imessage_date(date or end_date, end=bool(date or end_date))
    if range_start and range_end and range_start >= range_end:
        raise HTTPException(400, "start_date must be before end_date")

    messages = await asyncio.to_thread(
        imsg_messages,
        contact=contact,
        start_date=range_start,
        end_date=range_end,
        limit=limit,
    )
    return [
        IMessageOut(
            sender=str(message["sender"]),
            body=str(message["body"]),
            ts=message["ts"].isoformat(),
            is_me=bool(message["is_me"]),
            source="imessage",
            message_id=str(message["message_id"]),
            chat_id=str(message["chat_id"]),
            contact=str(message["contact"]),
        )
        for message in messages
    ]


@app.get("/imessage/links", response_model=list[IMessageLinkOut])
async def get_imessage_links(
    q: str = "x",
    contact: str = "",
    date: str = "",
    start_date: str = "",
    end_date: str = "",
    limit: int = 100,
):
    """Extract links from iMessages. Use q=x for twitter.com / x.com URLs."""
    if date and (start_date or end_date):
        raise HTTPException(400, "Use date or start_date/end_date, not both")
    if limit < 1 or limit > 1000:
        raise HTTPException(400, "limit must be between 1 and 1000")

    range_start = _parse_imessage_date(date or start_date)
    range_end = _parse_imessage_date(date or end_date, end=bool(date or end_date))
    if range_start and range_end and range_start >= range_end:
        raise HTTPException(400, "start_date must be before end_date")

    try:
        links = await asyncio.to_thread(
            imsg_links,
            link_type=q,
            contact=contact,
            start_date=range_start,
            end_date=range_end,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    return [
        IMessageLinkOut(
            url=str(item["url"]),
            message_id=str(item["message_id"]),
            chat_id=str(item["chat_id"]),
            contact=str(item["contact"]),
            sender=str(item["sender"]),
            body=str(item["body"]),
            ts=item["ts"].isoformat(),
            is_me=bool(item["is_me"]),
            source="imessage",
        )
        for item in links
    ]


@app.get("/imessage/contacts", response_model=list[ConversationOut])
async def list_imessage_contacts(limit: int = 50):
    """List iMessage contacts needing reply."""
    contacts = await asyncio.to_thread(imsg_contacts, limit)
    return [_contact_to_out(c) for c in contacts]


@app.get("/imessage/messages/{chat_id}", response_model=list[MessageOut])
async def get_imessage_messages(chat_id: str, limit: int = 50):
    """Fetch iMessage conversation thread by chat ID."""
    messages = await asyncio.to_thread(imsg_thread, chat_id, limit)
    return [_msg_to_out(m) for m in messages]


@app.post("/imessage/send")
async def send_imessage(contact_id: str, text: str):
    """Send an iMessage to a contact."""
    # contact_id would be mapped to Contact object
    # For now, this is a placeholder
    try:
        ok = await asyncio.to_thread(imsg_send, Contact(identifier=contact_id), text)
        return {"ok": ok}
    except Exception as e:
        raise HTTPException(500, f"Failed to send iMessage: {str(e)}") from e


# ── LinkedIn ─────────────────────────────────────────────────────────────────


@app.get("/linkedin/contacts", response_model=list[ConversationOut])
async def list_linkedin_contacts(limit: int = 20):
    contacts = await asyncio.to_thread(linkedin_contacts, limit)
    return [_contact_to_out(c) for c in contacts]


@app.get("/linkedin/messages/{thread_id}", response_model=list[MessageOut])
async def get_linkedin_messages(thread_id: str, limit: int = 50):
    messages = await asyncio.to_thread(linkedin_thread, thread_id, limit)
    return [_msg_to_out(m) for m in messages]


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

    acct, svc = _get_drive_service_for_account(account)
    result = await asyncio.to_thread(drive_download, svc, file_id)
    if not result:
        raise HTTPException(404, "File not found or download failed")
    content, mime_type = result
    return Response(content=content, media_type=mime_type)


@app.get("/drive/files/{file_id}", response_model=DriveFileOut)
async def get_drive_file(file_id: str, account: str = ""):
    acct, svc = _get_drive_service_for_account(account)
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

    acct, svc = _get_drive_service_for_account(account)

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
    acct, svc = _get_drive_service_for_account(req.account)
    result = await asyncio.to_thread(drive_create_folder, svc, req.name, parent_id=req.parent_id)
    if not result:
        raise HTTPException(500, "Failed to create folder")
    return _drive_to_out(result, account=acct)


@app.delete("/drive/files/{file_id}")
async def delete_drive_file(file_id: str, account: str = ""):
    acct, svc = _get_drive_service_for_account(account)
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


# ── Docs ─────────────────────────────────────────────────────────────────────


def _get_docs_service_for_account(account: str = "") -> tuple[str, object]:
    return _gacct.get_docs_service_for_account(state, account)


def _index_view_rows(view: str, limit: int) -> list[dict[str, object]]:
    if view == "actionable":
        return state.index_store.list_threads(
            limit=limit,
            actions=("reply", "review", "track"),
            newest_only=True,
            sort_mode="priority",
        )
    if view == "recent":
        return state.index_store.list_threads(
            limit=limit,
            newest_only=True,
            sort_mode="recent",
        )
    if view == "waiting-on-me":
        return state.index_store.list_threads(
            limit=limit,
            needs_reply=True,
            newest_only=True,
            sort_mode="priority",
        )
    if view == "waiting-on-others":
        return state.index_store.list_threads(
            limit=limit,
            latest_sender="Me",
            newest_only=True,
            sort_mode="recent",
        )
    if view == "waiting-on":
        return state.index_store.list_threads(
            limit=limit,
            actions=("track",),
            has_open_loop=True,
            newest_only=True,
            sort_mode="recent",
        )
    raise HTTPException(status_code=404, detail=f"Unknown index view: {view}")


INDEX_HEALTH_STALE_AFTER = timedelta(minutes=30)
INDEX_HEALTH_NO_SYNC_STATE = "no_sync_state"
INDEX_HEALTH_MISSING_CHECKPOINT = "missing_checkpoint"
INDEX_HEALTH_STALE_CHECKPOINT = "stale_checkpoint"
INDEX_HEALTH_SYNC_ERROR = "sync_error"


def _parse_index_health_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _append_index_health_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _index_sync_health_state(
    row: dict[str, Any],
    checked_at: datetime,
) -> tuple[IndexSyncHealthStateOut, datetime | None]:
    last_success_at = _parse_index_health_datetime(str(row.get("last_success_at") or ""))
    reasons: list[str] = []

    if not str(row.get("checkpoint_value") or "") or last_success_at is None:
        _append_index_health_reason(reasons, INDEX_HEALTH_MISSING_CHECKPOINT)

    last_success_age_seconds = None
    if last_success_at is not None:
        last_success_age_seconds = max(0, int((checked_at - last_success_at).total_seconds()))
        if checked_at - last_success_at > INDEX_HEALTH_STALE_AFTER:
            _append_index_health_reason(reasons, INDEX_HEALTH_STALE_CHECKPOINT)

    if str(row.get("status") or "") == "error" or str(row.get("last_error") or ""):
        _append_index_health_reason(reasons, INDEX_HEALTH_SYNC_ERROR)

    stale = any(
        reason in reasons
        for reason in (INDEX_HEALTH_MISSING_CHECKPOINT, INDEX_HEALTH_STALE_CHECKPOINT)
    )
    health_state = IndexSyncHealthStateOut(
        **row,
        last_success_age_seconds=last_success_age_seconds,
        healthy=not reasons,
        stale=stale,
        reasons=reasons,
    )
    return health_state, last_success_at


def _build_index_health(sync_states: list[dict[str, Any]]) -> IndexHealthOut:
    checked_at = datetime.now(UTC)
    health_states: list[IndexSyncHealthStateOut] = []
    successes: list[datetime] = []

    for row in sync_states:
        health_state, last_success_at = _index_sync_health_state(row, checked_at)
        health_states.append(health_state)
        if last_success_at is not None:
            successes.append(last_success_at)

    reasons: list[str] = []
    if not health_states:
        _append_index_health_reason(reasons, INDEX_HEALTH_NO_SYNC_STATE)
    for health_state in health_states:
        for reason in health_state.reasons:
            _append_index_health_reason(reasons, reason)

    newest_success_at = max(successes) if successes else None
    newest_success_age_seconds = (
        max(0, int((checked_at - newest_success_at).total_seconds()))
        if newest_success_at is not None
        else None
    )
    stale = not health_states or any(health_state.stale for health_state in health_states)

    return IndexHealthOut(
        db_path=str(state.index_store.db_path),
        healthy=bool(health_states) and not reasons,
        stale=stale,
        checked_at=checked_at.isoformat(),
        stale_after_seconds=int(INDEX_HEALTH_STALE_AFTER.total_seconds()),
        newest_success_at=newest_success_at.isoformat() if newest_success_at else None,
        newest_success_age_seconds=newest_success_age_seconds,
        reasons=reasons,
        sync_states=health_states,
    )


def _thread_source(thread: GmailThreadSummaryOut) -> str:
    return str(getattr(thread, "source", "") or "gmail")


def _thread_external_id(thread: GmailThreadSummaryOut) -> str:
    return str(getattr(thread, "latest_external_id", "") or "")


def _thread_open_loop(thread: GmailThreadSummaryOut) -> str:
    open_loop = str(getattr(thread, "open_loop", "") or "")
    if open_loop:
        return open_loop
    return thread.action_items[0] if thread.action_items else ""


def _thread_actionability(thread: GmailThreadSummaryOut) -> str:
    actionability = str(getattr(thread, "actionability", "") or "")
    if actionability:
        return actionability
    if thread.needs_reply:
        return "reply"
    return "track" if thread.action_items else ""


def _thread_urgency(thread: GmailThreadSummaryOut) -> str:
    return str(getattr(thread, "urgency", "") or "")


def _thread_ref(thread: GmailThreadSummaryOut, reason: str) -> dict[str, str]:
    return {
        "kind": "thread",
        "source": _thread_source(thread),
        "thread_id": thread.thread_id,
        "external_id": _thread_external_id(thread),
        "account": thread.owning_account,
        "reason": reason,
    }


def _task_ref(task: TaskOut, reason: str) -> dict[str, str]:
    return {
        "kind": "task",
        "source": "google_tasks",
        "id": task.id,
        "list_id": task.list_id,
        "account": task.account,
        "reason": reason,
    }


def _event_ref(event: CalendarEventOut, reason: str) -> dict[str, str]:
    return {
        "kind": "event",
        "source": "calendar",
        "id": event.event_id,
        "calendar_id": event.calendar_id,
        "account": event.account,
        "reason": reason,
    }


def _append_source_ref(refs: list[dict[str, str]], ref: dict[str, str]) -> None:
    if ref not in refs:
        refs.append(ref)


def _thread_reason(thread: GmailThreadSummaryOut) -> str:
    return (
        _thread_open_loop(thread)
        or _thread_actionability(thread)
        or ("needs_reply" if thread.needs_reply else "")
        or thread.workflow
        or "indexed_thread"
    )


def _thread_now_item(thread: GmailThreadSummaryOut, reason: str) -> dict[str, Any]:
    source = _thread_source(thread)
    actionability = _thread_actionability(thread)
    urgency = _thread_urgency(thread)
    return {
        "now_kind": "thread",
        "kind": "thread",
        "title": thread.subject or "Untitled thread",
        "source": source,
        "reason": reason,
        "ref": _thread_ref(thread, reason),
        "thread_id": thread.thread_id,
        "owning_account": thread.owning_account,
        "latest_external_id": _thread_external_id(thread),
        "participants": thread.participants,
        "last_message_at": thread.last_message_at,
        "summary": thread.summary,
        "brief": thread.brief,
        "open_loop": _thread_open_loop(thread),
        "action_items": thread.action_items,
        "needs_reply": thread.needs_reply,
        "workflow": thread.workflow,
        "actionability": actionability,
        "urgency": urgency,
        "now_meta": [
            source,
            actionability,
            urgency,
            thread.workflow,
        ],
    }


def _task_now_item(task: TaskOut) -> dict[str, Any]:
    reason = "overdue_task" if task.due else "needs_action_task"
    return {
        "now_kind": "task",
        "kind": "task",
        "title": task.title or "Untitled task",
        "source": "google_tasks",
        "reason": reason,
        "ref": _task_ref(task, reason),
        "id": task.id,
        "list_id": task.list_id,
        "list_title": task.list_title,
        "account": task.account,
        "status": task.status,
        "due": task.due,
        "has_notes": bool(task.notes),
        "workflow": task.workflow,
        "summary": "Task has notes" if task.notes else "",
        "actionability": "task",
        "now_meta": [
            "task",
            task.due or "",
            task.list_title,
            task.workflow,
        ],
    }


def _event_now_item(event: CalendarEventOut) -> dict[str, Any]:
    reason = "upcoming_event"
    return {
        "now_kind": "event",
        "kind": "event",
        "title": event.summary or "Untitled event",
        "source": "calendar",
        "reason": reason,
        "ref": _event_ref(event, reason),
        "event_id": event.event_id,
        "calendar_id": event.calendar_id,
        "account": event.account,
        "start": event.start,
        "end": event.end,
        "location": event.location,
        "has_description": bool(event.description),
        "workflow": event.workflow,
        "summary": event.location,
        "actionability": "prep",
        "now_meta": [
            "calendar",
            event.start,
            event.location,
            event.workflow,
        ],
    }


def _thread_matches_inbox_now_filters(
    thread: GmailThreadSummaryOut,
    workflow: str,
    account: str,
) -> bool:
    if workflow and thread.workflow != workflow:
        return False
    return not (account and thread.owning_account != account)


def _inbox_now_health_reasons(index_health: IndexHealthOut) -> list[str]:
    if index_health.healthy and not index_health.stale:
        return []
    if index_health.reasons:
        return [f"index:{reason}" for reason in index_health.reasons]
    return ["index:unhealthy"]


def _preflight_google_write(
    kind: str,
    account: str = "",
    folder_id: str = "",
    list_id: str = "",
    calendar_id: str = "",
    title: str = "",
) -> PreflightResult:
    """Inspect where a Google write will land without executing it."""
    return PreflightResult(
        **_gacct.preflight_google_write_payload(
            state, kind, account, folder_id, list_id, calendar_id, title
        )
    )


def _document_to_out(d) -> DocumentOut:  # type: ignore[no-untyped-def]
    return DocumentOut(
        id=d.id,
        title=d.title,
        url=d.url,
        mime_type=d.mime_type,
        account=d.account,
    )


@app.get("/docs", response_model=list[DocumentOut])
async def list_docs(q: str = "", limit: int = 20, account: str = ""):

    acct, drive_svc = _get_drive_service_for_account(account)
    docs = await asyncio.to_thread(docs_list, drive_svc, q, limit, acct)
    return [_document_to_out(d) for d in docs]


@app.post("/docs", response_model=DocumentOut)
async def create_doc(req: CreateDocumentRequest):

    acct, docs_svc = _get_docs_service_for_account(req.account)
    doc = await asyncio.to_thread(docs_create, docs_svc, req.title)
    if not doc:
        raise HTTPException(400, "Failed to create document")
    return _document_to_out(doc)


@app.get("/docs/{document_id}", response_model=DocumentOut)
async def get_doc(document_id: str, account: str = ""):

    acct, docs_svc = _get_docs_service_for_account(account)
    doc = await asyncio.to_thread(docs_get, docs_svc, document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    return _document_to_out(doc)


@app.delete("/docs/{document_id}")
async def delete_doc(document_id: str, account: str = ""):

    acct, drive_svc = _get_drive_service_for_account(account)
    ok = await asyncio.to_thread(docs_delete, drive_svc, document_id)
    return {"ok": ok}


@app.get("/docs/{document_id}/text")
async def get_doc_text(document_id: str, account: str = ""):

    acct, docs_svc = _get_docs_service_for_account(account)
    text = await asyncio.to_thread(docs_get_text, docs_svc, document_id)
    if text is None:
        raise HTTPException(400, "Failed to read document")
    return {"text": text}


@app.post("/docs/{document_id}/text")
async def insert_doc_text(document_id: str, req: InsertTextRequest, account: str = ""):

    acct, docs_svc = _get_docs_service_for_account(account)
    ok = await asyncio.to_thread(docs_insert_text, docs_svc, document_id, req.text, req.index)
    return {"ok": ok}


@app.get("/docs/{document_id}/export")
async def export_doc(document_id: str, format: str = "text/plain", account: str = ""):

    acct, drive_svc = _get_drive_service_for_account(account)
    content = await asyncio.to_thread(docs_export, drive_svc, document_id, format)
    if not content:
        raise HTTPException(400, "Failed to export document")
    # Return raw bytes with appropriate content type
    from starlette.responses import Response

    mime_type = format
    if format == "text/plain":
        mime_type = "text/plain; charset=utf-8"
    elif format == "application/pdf":
        mime_type = "application/pdf"
    elif format == "text/html":
        mime_type = "text/html; charset=utf-8"
    return Response(content=content, media_type=mime_type)


# ── Preflight ───────────────────────────────────────────────────────────────


@app.get("/preflight/google-write", response_model=PreflightResult)
async def preflight_google_write(
    kind: str,
    account: str = "",
    folder_id: str = "",
    list_id: str = "",
    calendar_id: str = "",
    title: str = "",
):
    return await asyncio.to_thread(
        _preflight_google_write, kind, account, folder_id, list_id, calendar_id, title
    )


# ── Search ───────────────────────────────────────────────────────────────────


@app.get("/connectors/status")
async def connectors_status_endpoint():
    return await asyncio.to_thread(connectors_status)


@app.get("/capabilities")
async def capability_inventory_endpoint():
    return await asyncio.to_thread(build_capability_inventory)


@app.post("/connectors/search")
async def connectors_search_endpoint(req: ConnectorSearchRequest):
    return await asyncio.to_thread(
        search_connectors,
        req.q,
        sources=req.sources,
        limit=req.limit,
    )


@app.post("/connectors/{connector_id}/sync")
async def connectors_sync_endpoint(connector_id: str, req: ConnectorSyncRequest):
    result = await asyncio.to_thread(connector_sync_plan, connector_id, execute=req.execute)
    if not result.get("ok"):
        error = result.get("error")
        status_code = (
            status.HTTP_404_NOT_FOUND
            if error == "unknown_connector"
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=result)
    return result


_GATEWAY_PARITY_MATRIX: list[dict[str, Any]] = [
    {
        "capability": "personal_data_gateway_read_proof",
        "local_api": ["POST /gateway/read-proof"],
        "mcp_tools": ["prove_personal_data_gateway_reads"],
        "account_selection": "account body parameter; blank reads loaded accounts for each source",
        "attribution": [
            "account",
            "gmail_account",
            "calendar_id",
            "event_id",
            "list_id",
            "task_id",
        ],
        "mutation_policy": "read_only; no provider mutation helpers are called",
        "canonical": True,
    },
    {
        "capability": "calendar_read",
        "local_api": [
            "GET /calendar/events",
            "GET /calendar/events/{event_id}",
            "GET /calendar/search",
        ],
        "mcp_tools": ["list_calendar_events", "get_calendar_event", "search_calendar_events"],
        "account_selection": "account query parameter; empty means first loaded/all-account read path depending endpoint",
        "attribution": ["account", "calendar_id", "event_id"],
        "mutation_policy": "read_only",
        "canonical": True,
    },
    {
        "capability": "calendar_create_update",
        "local_api": ["POST /calendar/events", "PUT /calendar/events/{event_id}"],
        "mcp_tools": ["create_calendar_event", "update_calendar_event"],
        "account_selection": "account body/query parameter plus calendar_id where applicable",
        "attribution": ["account", "calendar_id", "event_id"],
        "mutation_policy": "review_before_write: per-action approval lease required",
        "canonical": True,
    },
    {
        "capability": "gmail_multi_account_search_triage",
        "local_api": [
            "POST /gateway/gmail-readiness",
            "GET /gmail/search",
            "GET /gmail/conversations",
            "GET /inbox/needs-action",
        ],
        "mcp_tools": [
            "prove_multi_gmail_readiness",
            "search_email",
            "list_inbox_threads",
            "list_needs_action",
        ],
        "account_selection": "account query parameter; blank searches loaded accounts",
        "attribution": ["owning_account", "gmail_account", "thread_id", "message_id"],
        "mutation_policy": "read_only for readiness/search; explicit reply/modify tools are approval-gated",
        "canonical": True,
    },
    {
        "capability": "imessage_lookup",
        "local_api": [
            "GET /conversations?source=imessage",
            "GET /messages/imessage/{conv_id}",
            "POST /search with connector:imessage",
        ],
        "mcp_tools": ["list_message_threads", "get_message_thread", "search_personal_data"],
        "account_selection": "local Messages database; no cloud account selector",
        "attribution": ["source", "conv_id", "message_id", "sender", "ts"],
        "mutation_policy": "read_only for lookup; sends are approval-gated elsewhere",
        "canonical": True,
    },
    {
        "capability": "whatsapp_readiness",
        "local_api": ["GET /connectors/status", "POST /connectors/whatsapp/sync"],
        "mcp_tools": ["get_connectors_status", "plan_connector_sync"],
        "account_selection": "wacli local/session state reported by connector diagnostics",
        "attribution": ["connector", "storage", "auth_state"],
        "mutation_policy": "dry_run sync by default; execute requires approval lease",
        "canonical": True,
    },
    {
        "capability": "tasks_todos",
        "local_api": ["GET /tasks/lists", "GET /tasks", "POST /tasks", "PUT /tasks/{task_id}"],
        "mcp_tools": ["list_task_lists", "list_tasks", "create_task", "update_task"],
        "account_selection": "account query/body parameter",
        "attribution": ["account", "list_id", "task_id"],
        "mutation_policy": "review_before_write: per-action approval lease required",
        "canonical": True,
    },
    {
        "capability": "sheets_app_tracker_access",
        "local_api": [
            "GET /sheets",
            "GET /sheets/{spreadsheet_id}/values/{range_}",
            "PUT /sheets/{spreadsheet_id}/values/{range_}",
        ],
        "mcp_tools": ["list_sheets", "read_sheet_values", "update_sheet_values"],
        "account_selection": "account query/body parameter",
        "attribution": ["account", "spreadsheet_id", "range"],
        "mutation_policy": "reads are direct; writes require approval lease",
        "canonical": True,
    },
    {
        "capability": "drive_docs_access",
        "local_api": [
            "GET /drive/files",
            "GET /drive/files/{file_id}",
            "GET /docs",
            "GET /docs/{document_id}",
        ],
        "mcp_tools": ["list_drive_files", "get_drive_file", "list_docs", "get_doc"],
        "account_selection": "account query/body parameter",
        "attribution": ["account", "file_id", "document_id"],
        "mutation_policy": "reads are direct; writes/deletes require approval lease",
        "canonical": True,
    },
]


_INFISICAL_SECRET_NAMES = [
    "INBOX_GOOGLE_OAUTH_CLIENT_JSON",
    "INBOX_GITHUB_TOKEN",
    "INBOX_GOOGLE_MAPS_API_KEY",
    "INBOX_GEMINI_API_KEY",
    "INBOX_SERVER_TOKEN",
    "INBOX_MCP_TOKEN",
]


def _infisical_secret_name_gaps() -> dict[str, Any]:
    binary_path = shutil.which("infisical")
    return {
        "binary": "infisical",
        "binary_path": binary_path or "",
        "installed": binary_path is not None,
        "secret_names_only": True,
        "expected_secret_names": list(_INFISICAL_SECRET_NAMES),
        "value_policy": "never return or log secret values from this endpoint",
        "status": "check_not_run" if binary_path else "missing_cli",
        "remediation": [
            "Install Infisical CLI if this repo should hydrate local credentials from Infisical.",
            "Map the expected secret names to local files/env vars without printing values.",
            "Keep credentials.json, tokens/, and key files gitignored.",
        ],
    }


def _gateway_status_payload() -> dict[str, Any]:
    provider_payload = _provider_readiness()
    connector_payload = connectors_status()
    missing_connectors = [
        {
            "id": connector["id"],
            "binary": connector["binary"],
            "auth_state": connector["auth_state"],
            "remediation": connector.get("remediation", []),
        }
        for connector in connector_payload.get("connectors", [])
        if not connector.get("installed") or connector.get("auth_state") not in {"ok", "unknown"}
    ]
    return {
        "schema_version": "inbox.personal_data_gateway.v0",
        "canonical_gateway": "inbox_server",
        "built_in_tool_policy": "Do not rely on built-in Gmail/Calendar/Drive tools for normal operation; use local Inbox API/MCP tools first.",
        "health": {
            "status": provider_payload.status,
            "recommendations": provider_payload.recommendations,
            "api": provider_payload.api,
        },
        "parity_matrix": _GATEWAY_PARITY_MATRIX,
        "providers": [provider.model_dump() for provider in provider_payload.providers],
        "connectors": connector_payload,
        "missing_connector_diagnostics": missing_connectors,
        "infisical": _infisical_secret_name_gaps(),
        "review_before_write": {
            "required": True,
            "mechanism": "per-action X-Inbox-Approval-Lease; dry-run/proposal endpoints never execute provider mutations",
            "guarded_classes": ["external_write", "external_destructive"],
        },
    }


def _gateway_read_proof(req: GatewayReadProofRequest) -> dict[str, Any]:
    account = req.account.strip()
    gmail_limit = max(1, min(req.gmail_limit, 50))
    calendar_days = max(1, min(req.calendar_days, 30))
    calendar_limit = max(1, min(req.calendar_limit, 100))
    task_limit = max(1, min(req.task_limit, 100))
    proof: dict[str, Any] = {
        "schema_version": "inbox.personal_data_gateway.read_proof.v0",
        "canonical_gateway": "inbox_server",
        "read_only": True,
        "mutation_applied": False,
        "mutation_policy": "No provider mutation helpers are called by this proof endpoint.",
        "account_requested": account,
        "sources": {},
        "blockers": [],
    }

    source_blockers: list[str] = []

    gmail_accounts = (
        {account: state.gmail_services[account]}
        if account and account in state.gmail_services
        else ({} if account else state.gmail_services)
    )
    gmail_items: list[dict[str, Any]] = []
    gmail_errors: list[dict[str, str]] = []
    if account and not gmail_accounts:
        gmail_errors.append({"account": account, "error": "gmail_account_not_loaded"})
    elif not gmail_accounts:
        gmail_errors.append({"account": "", "error": "gmail_service_not_loaded"})
    for email, svc in gmail_accounts.items():
        try:
            contacts = gmail_search(svc, email, req.gmail_query, gmail_limit)
            gmail_items.extend(
                _contact_to_out(contact).model_dump() for contact in contacts[:gmail_limit]
            )
        except Exception as exc:
            gmail_errors.append({"account": email, "error": str(exc)})
    if gmail_errors:
        source_blockers.append("gmail_read_failed")
    proof["sources"]["gmail"] = {
        "ok": not gmail_errors,
        "operation": "gmail_list",
        "route_equivalent": "GET /gmail/search",
        "accounts": list(gmail_accounts.keys()),
        "query": req.gmail_query,
        "count": len(gmail_items[:gmail_limit]),
        "items": gmail_items[:gmail_limit],
        "errors": gmail_errors,
    }

    calendar_services = (
        {account: state.cal_services[account]}
        if account and account in state.cal_services
        else ({} if account else state.cal_services)
    )
    calendar_errors: list[dict[str, str]] = []
    calendar_items: list[dict[str, Any]] = []
    if account and not calendar_services:
        calendar_errors.append({"account": account, "error": "calendar_account_not_loaded"})
    elif not calendar_services:
        calendar_errors.append({"account": "", "error": "calendar_service_not_loaded"})
    if calendar_services:
        try:
            start_dt = datetime.now(UTC)
            end_dt = start_dt + timedelta(days=calendar_days)
            events = calendar_events(calendar_services, start_date=start_dt, end_date=end_dt)
            calendar_items = [
                _event_to_out(event).model_dump() for event in events[:calendar_limit]
            ]
        except Exception as exc:
            calendar_errors.append({"account": account, "error": str(exc)})
    if calendar_errors:
        source_blockers.append("calendar_read_failed")
    proof["sources"]["calendar"] = {
        "ok": not calendar_errors,
        "operation": "calendar_events_read",
        "route_equivalent": "GET /calendar/events",
        "accounts": list(calendar_services.keys()),
        "days": calendar_days,
        "count": len(calendar_items),
        "items": calendar_items,
        "errors": calendar_errors,
    }

    task_accounts = (
        {account: state.tasks_services[account]}
        if account and account in state.tasks_services
        else ({} if account else state.tasks_services)
    )
    task_errors: list[dict[str, str]] = []
    task_items: list[dict[str, Any]] = []
    if account and not task_accounts:
        task_errors.append({"account": account, "error": "tasks_account_not_loaded"})
    elif not task_accounts:
        task_errors.append({"account": "", "error": "tasks_service_not_loaded"})
    for email, svc in task_accounts.items():
        try:
            tasks = tasks_list(svc, req.task_list_id, False, task_limit)
            task_items.extend(_task_to_out(task, email).model_dump() for task in tasks[:task_limit])
        except Exception as exc:
            task_errors.append({"account": email, "error": str(exc)})
    if task_errors:
        source_blockers.append("tasks_read_failed")
    proof["sources"]["tasks"] = {
        "ok": not task_errors,
        "operation": "task_list_read",
        "route_equivalent": "GET /tasks",
        "accounts": list(task_accounts.keys()),
        "list_id": req.task_list_id,
        "count": len(task_items[:task_limit]),
        "items": task_items[:task_limit],
        "errors": task_errors,
    }

    proof["ok"] = not source_blockers
    proof["blockers"] = source_blockers
    return proof


def _gmail_readiness(req: GmailReadinessRequest) -> dict[str, Any]:
    requested_accounts = [account.strip() for account in req.accounts if account.strip()]
    if not requested_accounts:
        requested_accounts = sorted(state.gmail_services.keys())

    token_diag = google_auth_diagnostics(check_refresh=False)
    loaded_accounts = sorted(state.gmail_services.keys())
    account_rows: list[dict[str, Any]] = []
    blockers: list[str] = []

    for account in requested_accounts:
        svc = state.gmail_services.get(account)
        row: dict[str, Any] = {
            "account": account,
            "loaded": svc is not None,
            "readable": False,
            "profile_email": "",
            "counts": {
                "messages_total": 0,
                "threads_total": 0,
                "inbox_result_size_estimate": 0,
                "unread_inbox_result_size_estimate": 0,
            },
            "errors": [],
        }
        if svc is None:
            row["errors"].append("gmail_account_not_loaded")
            blockers.append(f"gmail_account_not_loaded:{account}")
            account_rows.append(row)
            continue

        try:
            counts = gmail_inbox_counts(svc)
            row["profile_email"] = counts.pop("profile_email", "")
            row["counts"] = counts
            row["readable"] = True
        except Exception as exc:
            row["errors"].append(str(exc) or "gmail_read_failed")
            blockers.append(f"gmail_read_failed:{account}")
        account_rows.append(row)

    missing_loaded = [
        account for account in requested_accounts if account not in state.gmail_services
    ]
    return {
        "schema_version": "inbox.multi_gmail_readiness.v0",
        "canonical_gateway": "inbox_server",
        "dry_run": True,
        "read_only": True,
        "mutation_applied": False,
        "mutation_policy": "This endpoint reads Gmail profile and inbox count metadata only; it does not send, delete, label, mark read, or mutate provider data.",
        "required_accounts": requested_accounts,
        "loaded_accounts": loaded_accounts,
        "missing_loaded_accounts": missing_loaded,
        "accounts": account_rows,
        "data_connect": {
            "products": token_diag.get("data_connect", {}),
            "gmail_native_service": "gmail:v1",
            "token_diagnostics_redacted": True,
            "token_counts": token_diag.get("counts", {}),
            "likely_causes": token_diag.get("likely_causes", []),
        },
        "ok": not blockers,
        "blockers": blockers,
        "next_fix": "Run scripts/restore_google_oauth.sh --start and authorize each missing Gmail account, then restart the Inbox server."
        if blockers
        else "Both required Gmail accounts are loaded and readable through the local Inbox gateway.",
    }


def _extract_office_location_from_hits(
    results: list[dict[str, Any]],
) -> tuple[str, dict[str, Any] | None]:
    patterns = [
        r"(?:office location|office|meet(?:ing)? at|at)\s*(?:is|:|-)?\s*([A-Z0-9][^.\n,;]{4,120})",
        r"\b(\d{2,6}\s+[A-Z][A-Za-z0-9 .'-]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way|Suite|Ste)[^.\n;]{0,80})",
    ]
    for hit in results:
        metadata_text = (
            (hit.get("metadata") or {}).get("text", "")
            if isinstance(hit.get("metadata"), dict)
            else ""
        )
        for text in (hit.get("snippet", ""), metadata_text, hit.get("title", "")):
            if not text:
                continue
            for pattern in patterns:
                match = re.search(pattern, str(text), flags=re.IGNORECASE)
                if match:
                    location = match.group(1).strip(" -:,.")
                    if location:
                        return location, hit
    return "", results[0] if results else None


def _calendar_event_snapshot(event_id: str, calendar_id: str, account: str) -> dict[str, Any]:
    if account and account not in state.cal_services:
        return {
            "found": False,
            "error": "calendar_account_not_loaded",
            "account": account,
            "event_id": event_id,
            "calendar_id": calendar_id,
        }
    try:
        acct, svc = _get_cal_service_for_account(account)
    except Exception as exc:
        return {
            "found": False,
            "error": "calendar_service_unavailable",
            "detail": str(exc),
            "account": account,
            "event_id": event_id,
            "calendar_id": calendar_id,
        }
    try:
        event = calendar_get_event(svc, event_id, calendar_id)
    except Exception as exc:
        return {
            "found": False,
            "error": "calendar_event_read_failed",
            "detail": str(exc),
            "account": acct,
            "event_id": event_id,
            "calendar_id": calendar_id,
        }
    if not event:
        return {
            "found": False,
            "error": "event_not_found",
            "account": acct,
            "event_id": event_id,
            "calendar_id": calendar_id,
        }
    return {
        "found": True,
        "account": acct,
        "event": _event_to_out(event).model_dump(),
    }


def _ahmed_office_location_dry_run(req: AhmedOfficeLocationDryRunRequest) -> dict[str, Any]:
    connector_result = search_connectors(req.query, sources=["imessage"], limit=req.limit)
    location, evidence_hit = _extract_office_location_from_hits(connector_result.get("results", []))
    event_snapshot = _calendar_event_snapshot(req.event_id, req.calendar_id, req.account)
    proposal = {
        "method": "PUT",
        "path": f"/calendar/events/{req.event_id}",
        "query": {"calendar_id": req.calendar_id, "account": req.account},
        "body": {"location": location} if location else {},
        "requires_approval_lease": True,
        "would_apply": False,
    }
    blockers: list[str] = []
    if connector_result.get("errors"):
        blockers.append("imessage_connector_search_error")
    if not location:
        blockers.append("office_location_not_found_in_imessage_results")
    if not event_snapshot.get("found"):
        blockers.append("calendar_event_not_read")
    return {
        "ok": not blockers,
        "dry_run": True,
        "workflow": "ahmed_imessage_office_location_to_calendar_update",
        "mutation_applied": False,
        "account": req.account,
        "calendar_id": req.calendar_id,
        "event_id": req.event_id,
        "imessage_search": {
            "query": req.query,
            "source": "connector:imessage",
            "limit": req.limit,
            "result_count": connector_result.get("total", 0),
            "errors": connector_result.get("errors", []),
        },
        "evidence": {"office_location": location, "hit": evidence_hit},
        "calendar_read": event_snapshot,
        "proposed_update": proposal,
        "blockers": blockers,
        "next_fix": "Install/auth imsg and load the target calendar account, then rerun this dry-run until blockers is empty."
        if blockers
        else "Review the proposed update and mint a per-action approval lease before calling PUT /calendar/events/{event_id}.",
    }


@app.get("/gateway/status")
async def gateway_status_endpoint():
    return await asyncio.to_thread(_gateway_status_payload)


@app.post("/gateway/read-proof")
async def gateway_read_proof_endpoint(req: GatewayReadProofRequest):
    return await asyncio.to_thread(_gateway_read_proof, req)


@app.post("/gateway/gmail-readiness")
async def gateway_gmail_readiness_endpoint(req: GmailReadinessRequest):
    return await asyncio.to_thread(_gmail_readiness, req)


@app.post("/gateway/dry-run/ahmed-office-location-calendar-update")
async def ahmed_office_location_calendar_update_dry_run(
    req: AhmedOfficeLocationDryRunRequest,
):
    return await asyncio.to_thread(_ahmed_office_location_dry_run, req)


@app.post("/search")
async def search_endpoint(req: SearchRequest):
    built_in_sources, connector_sources = partition_search_sources(req.sources)
    result = await asyncio.to_thread(
        search_all,
        query=req.q,
        sources=built_in_sources,
        limit=req.limit,
        gmail_services=state.gmail_services,
        cal_services=state.cal_services,
        from_addr=req.from_addr,
        before=req.before,
        after=req.after,
        has_attachment=req.has_attachment,
        is_unread=req.is_unread,
    )
    if connector_sources:
        connector_result = await asyncio.to_thread(
            search_connectors,
            req.q,
            sources=connector_sources,
            limit=req.limit,
        )
        result = merge_connector_search_results(result, connector_result, limit=req.limit)
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


@app.get("/accounts/auth-status")
async def accounts_auth_status(check_refresh: bool = False):
    return await asyncio.to_thread(google_auth_diagnostics, check_refresh)


@app.post("/accounts/add")
async def add_account():
    email = await asyncio.to_thread(add_google_account)
    if not email:
        raise HTTPException(400, "Failed to add account — no credentials.json")
    # Reload all services
    gmail, cal, drive, sheets, docs, tasks = await asyncio.to_thread(google_auth_all)
    state.gmail_services = gmail
    state.cal_services = cal
    state.drive_services = drive
    state.sheets_services = sheets
    state.docs_services = docs
    state.tasks_services = tasks
    return {"email": email}


@app.post("/accounts/reauth")
async def reauth_account(req: AccountRequest):
    if not req.email:
        raise HTTPException(400, "email is required")
    email = await asyncio.to_thread(reauth_google_account, req.email)
    if not email:
        raise HTTPException(400, "Re-auth failed")
    gmail, cal, drive, sheets, docs, tasks = await asyncio.to_thread(google_auth_all)
    state.gmail_services = gmail
    state.cal_services = cal
    state.drive_services = drive
    state.sheets_services = sheets
    state.docs_services = docs
    state.tasks_services = tasks
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


# ── Calendar (extended) ──────────────────────────────────────────────────────


def _get_cal_service_for_account(account: str = "") -> tuple[str, object]:
    return _gacct.get_cal_service_for_account(state, account)


@app.get("/calendar/calendars", response_model=list[CalendarOut])
async def list_calendars(account: str = ""):
    acct, svc = _get_cal_service_for_account(account)
    calendars = await asyncio.to_thread(calendar_list_calendars, state.cal_services)
    return calendars


@app.get("/calendar/events/{event_id}", response_model=CalendarEventOut)
async def get_event(
    event_id: str,
    calendar_id: str = "primary",
    account: str = "",
):
    acct, svc = _get_cal_service_for_account(account)
    evt = await asyncio.to_thread(calendar_get_event, svc, event_id, calendar_id)
    if not evt:
        raise HTTPException(404, "Event not found")
    return _event_to_out(evt)


@app.get("/calendar/events/{event_id}/attendees")
async def get_event_attendees(
    event_id: str,
    calendar_id: str = "primary",
    account: str = "",
):
    acct, svc = _get_cal_service_for_account(account)
    evt = await asyncio.to_thread(calendar_get_event, svc, event_id, calendar_id)
    if not evt:
        raise HTTPException(404, "Event not found")
    return {"event_id": event_id, "attendees": evt.attendees}


@app.post("/calendar/events/{event_id}/rsvp")
async def rsvp_event(
    event_id: str,
    req: RsvpRequest,
):
    acct, svc = _get_cal_service_for_account(req.account)
    ok = await asyncio.to_thread(
        calendar_rsvp_event, svc, event_id, acct, req.response, req.calendar_id
    )
    return {"ok": ok}


@app.patch("/calendar/events/{event_id}/attendees")
async def modify_attendees(
    event_id: str,
    req: ModifyAttendeesRequest,
):
    acct, svc = _get_cal_service_for_account(req.account)
    ok = await asyncio.to_thread(
        calendar_modify_attendees, svc, event_id, req.add, req.remove, req.calendar_id
    )
    return {"ok": ok}


@app.get("/calendar/events/{event_id}/instances", response_model=list[CalendarEventOut])
async def get_instances(
    event_id: str,
    calendar_id: str = "primary",
    account: str = "",
    time_min: str = "",
    time_max: str = "",
    max_results: int = 50,
):
    from datetime import datetime

    acct, svc = _get_cal_service_for_account(account)
    time_min_dt = datetime.fromisoformat(time_min) if time_min else None
    time_max_dt = datetime.fromisoformat(time_max) if time_max else None
    instances = await asyncio.to_thread(
        calendar_get_recurring_instances,
        svc,
        event_id,
        calendar_id,
        time_min_dt,
        time_max_dt,
        max_results,
    )
    return [_event_to_out(e) for e in instances]


@app.get("/calendar/search", response_model=list[CalendarEventOut])
async def search_calendar(
    q: str = "",
    attendee: str = "",
    location: str = "",
    start: str = "",
    end: str = "",
    calendar_id: str = "",
    account: str = "",
    limit: int = 50,
):
    from datetime import datetime

    # Use single account if specified, else all
    cal_svcs = (
        {account: state.cal_services[account]}
        if account and account in state.cal_services
        else state.cal_services
    )
    start_dt = datetime.fromisoformat(start) if start else None
    end_dt = datetime.fromisoformat(end) if end else None
    events = await asyncio.to_thread(
        calendar_search_events,
        cal_svcs,
        q,
        attendee,
        location,
        start_dt,
        end_dt,
        calendar_id or None,
        limit,
    )
    return [_event_to_out(e) for e in events]


@app.put("/calendar/events/{event_id}/reminders")
async def set_reminders(
    event_id: str,
    req: EventRemindersRequest,
):
    acct, svc = _get_cal_service_for_account(req.account)
    reminders_dict = {"useDefault": req.use_default}
    if not req.use_default:
        reminders_dict["overrides"] = req.overrides
    ok = await asyncio.to_thread(
        calendar_update_event, svc, event_id, reminders=reminders_dict, calendar_id=req.calendar_id
    )
    return {"ok": ok}


@app.post("/calendar/events/{event_id}/create-reminder")
async def create_event_reminder(
    event_id: str,
    list_name: str = "Reminders",
    minutes_before: int = 30,
    account: str = "",
    calendar_id: str = "primary",
):
    """Create an Apple Reminder from a calendar event.

    The reminder is due ``minutes_before`` minutes before the event start.
    """
    try:
        acct, svc = _get_cal_service_for_account(account)
        event = await asyncio.to_thread(calendar_get_event, svc, event_id, calendar_id)
        if not event:
            return {"error": "Event not found"}

        success = await asyncio.to_thread(
            calendar_event_to_reminder, event, list_name, minutes_before
        )
        return {"success": success, "reminder_created": success}
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e)}


@app.post("/calendar/freebusy")
async def get_freebusy(req: FreeBusyRequest):
    from datetime import datetime

    acct, svc = _get_cal_service_for_account(req.account)
    time_min = datetime.fromisoformat(req.time_min)
    time_max = datetime.fromisoformat(req.time_max)
    busy = await asyncio.to_thread(
        calendar_freebusy, svc, time_min, time_max, req.calendar_ids, req.timezone
    )
    return {"time_min": req.time_min, "time_max": req.time_max, "busy": busy}


@app.post("/calendar/free-slots")
async def find_free_slots(req: FreeSlotsRequest):
    from datetime import datetime

    acct, svc = _get_cal_service_for_account(req.account)
    time_min = datetime.fromisoformat(req.time_min)
    time_max = datetime.fromisoformat(req.time_max)
    slots = await asyncio.to_thread(
        calendar_find_free_slots,
        svc,
        time_min,
        time_max,
        req.calendar_ids,
        req.duration_minutes,
        req.timezone,
    )
    return {"slots": slots}


@app.post("/gmail/labels")
async def create_gmail_label(name: str, visibility: str = "labelShow", account: str = ""):
    """Create a new Gmail label."""
    try:
        acct, svc = _get_gmail_service_for_account(account)
        result = await asyncio.to_thread(gmail_label_create, svc, name, visibility)
        return result
    except Exception as e:
        return {"error": str(e)}


@app.get("/gmail/filters/audit")
async def audit_gmail_filters(account: str = ""):
    """Return read-only Gmail filter routing details for loaded accounts."""
    if account:
        acct, svc = _get_gmail_service_for_account(account)
        audits = [await asyncio.to_thread(gmail_filter_audit, svc, acct)]
    else:
        audits = [
            await asyncio.to_thread(gmail_filter_audit, svc, acct)
            for acct, svc in state.gmail_services.items()
        ]

    return {
        "accounts": audits,
        "trash_filters_count": sum(len(audit.get("trash_filters", [])) for audit in audits),
        "archive_filters_count": sum(len(audit.get("archive_filters", [])) for audit in audits),
        "triage_filters_count": sum(len(audit.get("triage_filters", [])) for audit in audits),
    }


@app.post("/calendar/conflicts")
async def check_calendar_conflicts(start: str, end: str, account: str = ""):
    """Find calendar conflicts in time range [start, end]."""
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
        acct, svc = _get_cal_service_for_account(account)
        conflicts = await asyncio.to_thread(calendar_find_conflicts, {acct: svc}, start_dt, end_dt)
        return {
            "conflicts": [
                {
                    "id": c.id,
                    "title": c.title,
                    "start": c.start,
                    "end": c.end,
                    "location": c.location or "",
                }
                for c in conflicts
            ]
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/memory/extract")
async def extract_memory_endpoint(text: str, source: str = "manual", auto_save: bool = False):
    """Extract memory entities from text and optionally save to memory store."""
    try:
        extracted = await asyncio.to_thread(ai_extract_memory, text)
        saved_count = 0

        if auto_save:
            # Auto-save extracted entities
            for person in extracted.get("people", []):
                memory_store.save_entry(
                    memory_type="person",
                    subject=person.get("name", ""),
                    content=person.get("context", ""),
                    source=source,
                    confidence=0.8,
                    metadata={"relationship": person.get("relationship", "")},
                )
                saved_count += 1

            for project in extracted.get("projects", []):
                memory_store.save_entry(
                    memory_type="project",
                    subject=project.get("name", ""),
                    content=project.get("description", ""),
                    source=source,
                    confidence=0.85,
                    metadata={"status": project.get("status", "active")},
                )
                saved_count += 1

            for commitment in extracted.get("commitments", []):
                memory_store.save_entry(
                    memory_type="commitment",
                    subject=commitment.get("text", ""),
                    content=f"Owner: {commitment.get('owner', '')}",
                    source=source,
                    confidence=0.9,
                    status="open",
                    expires_at=commitment.get("deadline", None),
                )
                saved_count += 1

        return {"extracted": extracted, "saved": saved_count}
    except Exception as e:
        return {"error": str(e)}


# ── Phase 4: Workflow tools ─────────────────────────────────────────────────


@app.get("/gmail/threads/needing-reply", response_model=list[GmailThreadSummaryOut])
async def get_threads_needing_reply(
    workflow: str = "",
    days_stale: int = 3,
    account: str = "",
    limit: int = 20,
):
    """Unread inbox threads older than days_stale days where a reply is expected."""
    acct, svc = _get_gmail_service_for_account(account)
    contacts = await asyncio.to_thread(gmail_search, svc, acct, "is:inbox", limit * 3)
    cutoff = datetime.now() - timedelta(days=days_stale)
    seen: set[str] = set()
    results: list[GmailThreadSummaryOut] = []
    for c in contacts:
        tid = c.thread_id or c.id
        if c.unread == 0 or c.last_ts > cutoff or tid in seen:
            continue
        seen.add(tid)
        ts = _contact_to_thread_summary(c)
        if workflow and ts.workflow != workflow:
            continue
        results.append(ts)
    results.sort(key=lambda t: t.rank, reverse=True)
    return results[:limit]


@app.post("/calendar/workflow-event", response_model=CalendarEventOut)
async def create_calendar_workflow_event(req: WorkflowEventRequest):
    """Create a calendar event with kind prefix in title and workflow tag in description."""
    account, svc = _get_cal_service_for_account(req.account)
    prefix = _KIND_PREFIX.get(req.kind, "")
    title = (
        f"{prefix} {req.title}".strip()
        if prefix and not req.title.startswith(prefix)
        else req.title
    )
    workflow = req.workflow or _classify_workflow(req.title)
    tag = f"#{workflow}" if workflow else ""
    description = req.description
    if tag and tag not in description:
        description = f"{description} {tag}".strip() if description else tag
    try:
        event_id = await asyncio.to_thread(
            calendar_create_event,
            svc,
            summary=title,
            start=datetime.fromisoformat(req.start),
            end=datetime.fromisoformat(req.end),
            location=req.location,
            description=description,
            all_day=False,
            attendees=req.attendees,
        )
    except Exception as e:
        raise HTTPException(500, f"Failed to create event: {str(e)}") from e
    return CalendarEventOut(
        summary=title,
        start=req.start,
        end=req.end,
        location=req.location,
        description=description,
        account=account,
        event_id=event_id or "",
        workflow=workflow,
    )


@app.get("/inbox/needs-action", response_model=NeedsActionOut)
async def get_needs_action(workflow: str = "", account: str = ""):
    """Cross-source rollup: reply-needed threads + overdue tasks + upcoming calendar events."""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    three_days_out = today + timedelta(days=3)

    threads: list[GmailThreadSummaryOut] = []
    indexed_threads = state.index_store.list_threads(
        limit=25, actionable_only=True, newest_only=True
    )
    if indexed_threads:
        for row in indexed_threads:
            if account and row.get("account") != account:
                continue
            ts = _indexed_thread_to_summary(row)
            if workflow and ts.workflow != workflow:
                continue
            threads.append(ts)
            if len(threads) >= 10:
                break

    tasks: list[TaskOut] = []
    if state.tasks_services:
        try:
            acct, svc = _get_tasks_service_for_account(account)
            raw_tasks = await asyncio.to_thread(tasks_list, svc, "@default", False, 100)
            for t in raw_tasks:
                task_out = _task_to_out(t, acct)
                if workflow and task_out.workflow != workflow:
                    continue
                if (t.due and t.due <= today) or (
                    t.status in {"needsAction", "needs_action"} and not t.due
                ):
                    tasks.append(task_out)
                if len(tasks) >= 10:
                    break
        except Exception:
            pass

    events: list[CalendarEventOut] = []
    if state.cal_services:
        try:
            cal_services = (
                {account: state.cal_services[account]}
                if account and account in state.cal_services
                else ({} if account else state.cal_services)
            )
            evts = await asyncio.to_thread(
                calendar_events,
                cal_services,
                start_date=today,
                end_date=three_days_out,
            )
            for e in evts:
                ev = _event_to_out(e)
                if account and ev.account != account:
                    continue
                if workflow and ev.workflow != workflow:
                    continue
                events.append(ev)
                if len(events) >= 10:
                    break
        except Exception:
            pass

    counts: dict[str, int] = {}
    for wf in (
        [t.workflow for t in threads] + [t.workflow for t in tasks] + [e.workflow for e in events]
    ):
        if wf:
            counts[wf] = counts.get(wf, 0) + 1

    return NeedsActionOut(threads=threads, tasks=tasks, events=events, workflow_counts=counts)


@app.get("/inbox/now", response_model=InboxNowOut)
async def get_inbox_now(workflow: str = "", account: str = "", limit: int = 20):
    """Compact read-only model for the current inbox state."""
    index_health = _build_index_health(state.index_store.list_sync_states())
    needs_action = await get_needs_action(workflow=workflow, account=account)

    source_refs: list[dict[str, str]] = []
    now_items: list[dict[str, Any]] = []
    commitments: list[dict[str, Any]] = []

    for thread in needs_action.threads[:limit]:
        reason = _thread_reason(thread)
        item = _thread_now_item(thread, reason)
        now_items.append(item)
        _append_source_ref(source_refs, item["ref"])

    for task in needs_action.tasks[:limit]:
        item = _task_now_item(task)
        now_items.append(item)
        commitments.append(item)
        _append_source_ref(source_refs, item["ref"])

    for event in needs_action.events[:limit]:
        item = _event_now_item(event)
        now_items.append(item)
        _append_source_ref(source_refs, item["ref"])

    actionable_threads = [
        _indexed_thread_to_summary(row) for row in _index_view_rows("actionable", limit)
    ]
    actionable_threads = [
        thread
        for thread in actionable_threads
        if _thread_matches_inbox_now_filters(thread, workflow, account)
    ][:limit]
    for thread in actionable_threads:
        _append_source_ref(source_refs, _thread_ref(thread, _thread_reason(thread)))

    waiting_threads = [
        _indexed_thread_to_summary(row) for row in _index_view_rows("waiting-on", limit)
    ]
    waiting_threads = [
        thread
        for thread in waiting_threads
        if _thread_matches_inbox_now_filters(thread, workflow, account)
    ][:limit]
    for thread in waiting_threads:
        reason = _thread_reason(thread)
        commitments.append(_thread_now_item(thread, reason))
        _append_source_ref(source_refs, _thread_ref(thread, reason))

    reasons = _inbox_now_health_reasons(index_health)
    if not now_items and reasons:
        reasons.append("now_empty_with_unhealthy_index")

    return InboxNowOut(
        index_health=index_health,
        reasons=reasons,
        now_items=now_items[:limit],
        actionable_threads=actionable_threads,
        waiting_threads=waiting_threads,
        commitments=commitments[:limit],
        source_refs=source_refs,
        workflow_counts=needs_action.workflow_counts,
    )


@app.get("/index/threads", response_model=IndexStatusOut)
async def get_index_threads(
    limit: int = 20, actionable_only: bool = True, newest_only: bool = True
):
    rows = state.index_store.list_threads(
        limit=limit,
        actionable_only=actionable_only,
        newest_only=newest_only,
    )
    return IndexStatusOut(
        db_path=str(state.index_store.db_path),
        threads=[_indexed_thread_to_summary(row) for row in rows],
    )


@app.get("/index/status", response_model=IndexOverviewOut)
async def get_index_status():
    return IndexOverviewOut(
        db_path=str(state.index_store.db_path),
        counts=state.index_store.index_counts(),
        sync_states=[IndexSyncStateOut(**row) for row in state.index_store.list_sync_states()],
    )


@app.get("/index/health", response_model=IndexHealthOut)
async def get_index_health():
    return _build_index_health(state.index_store.list_sync_states())


@app.get("/index/views/{view_name}", response_model=IndexedThreadListOut)
async def get_index_view(view_name: str, limit: int = 20):
    rows = _index_view_rows(view_name, limit)
    return IndexedThreadListOut(
        view=view_name,
        db_path=str(state.index_store.db_path),
        threads=[_indexed_thread_to_summary(row) for row in rows],
    )


@app.post("/index/sync/bootstrap", response_model=IndexSyncOut)
async def post_index_sync_bootstrap():
    stats = await asyncio.to_thread(index_bootstrap_sync, state.index_store)
    return IndexSyncOut(ok=True, mode="bootstrap", stats=stats)


@app.post("/index/sync/incremental", response_model=IndexSyncOut)
async def post_index_sync_incremental():
    stats = await asyncio.to_thread(index_incremental_sync, state.index_store)
    return IndexSyncOut(ok=True, mode="incremental", stats=stats)


@app.post("/drive/workflow-folder", response_model=DriveFileOut)
async def create_drive_workflow_folder(req: WorkflowFolderRequest):
    """Create a Drive folder using workflow display name and default account."""
    acct, svc = _get_drive_service_for_account(req.account)
    folder_name = req.name or _WORKFLOW_DISPLAY.get(req.workflow, req.workflow)
    result = await asyncio.to_thread(drive_create_folder, svc, folder_name, parent_id=req.parent_id)
    if not result:
        raise HTTPException(500, "Failed to create folder")
    return _drive_to_out(result, account=acct)


@app.post("/docs/workflow-doc", response_model=DocumentOut)
async def create_workflow_doc(req: WorkflowDocRequest):
    """Create a Google Doc using default account."""
    acct, docs_svc = _get_docs_service_for_account(req.account)
    doc = await asyncio.to_thread(docs_create, docs_svc, req.title)
    if not doc:
        raise HTTPException(400, "Failed to create document")
    return _document_to_out(doc)


@app.post("/sheets/workflow-sheet", response_model=SpreadsheetOut)
async def create_workflow_sheet(req: WorkflowSheetRequest):
    """Create a Google Sheet using default account."""
    acct, sheets_svc = _get_sheets_service_for_account(req.account)
    result = await asyncio.to_thread(sheets_create, sheets_svc, req.title, [])
    if not result:
        raise HTTPException(400, "Failed to create spreadsheet")
    return _spreadsheet_to_out(result, acct)


# ── Cross-silo query (gemma4-hackathon orchestrator) ──────────────────────────


class _QueryRequest(BaseModel):
    question: str
    per_silo_limit: int = 10
    use_real_model: bool = False


@app.post("/query")
async def cross_silo_query(req: _QueryRequest):
    """Natural-language cross-silo query via gemma4 orchestrator.

    Requires gemma4-hackathon installed as an editable dep:
        uv pip install -e ~/projects/gemma4-hackathon
    Returns gracefully with 503 when not installed.
    """
    try:
        import gemma4_hackathon.silos.calendar  # noqa: F401
        import gemma4_hackathon.silos.gmail  # noqa: F401
        import gemma4_hackathon.silos.imessage  # noqa: F401  trigger registration
        import gemma4_hackathon.silos.memory  # noqa: F401
        import gemma4_hackathon.silos.photos  # noqa: F401
        from gemma4_hackathon.orchestrator import Orchestrator  # type: ignore
    except ImportError as exc:
        raise HTTPException(503, f"gemma4_hackathon not installed: {exc}") from exc

    if req.use_real_model:
        from gemma4_hackathon.runtime import get_runtime  # type: ignore

        runtime = get_runtime("e4b")
    else:
        from gemma4_hackathon.fake_runtime import FakeRuntime  # type: ignore

        runtime = FakeRuntime()

    orch = Orchestrator(runtime)
    result = await asyncio.to_thread(orch.query, req.question, per_silo_limit=req.per_silo_limit)
    return {
        "question": result.question,
        "answer": result.answer,
        "plan": result.plan,
        "citations": [
            {"silo": r.silo, "id": r.id, "when": r.when.isoformat() if r.when else None}
            for r in result.retrieved
        ],
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("INBOX_SERVER_PORT", PORT))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
