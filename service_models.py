"""Stable, pure data models shared by services and callers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

ATTACHMENT_PLACEHOLDER = "\ufffc"


@dataclass
class Contact:
    id: str
    name: str
    source: str  # "imessage" | "gmail"
    snippet: str = ""
    unread: int = 0
    last_ts: datetime = field(default_factory=datetime.now)
    guid: str = ""
    is_group: bool = False
    members: list[str] = field(default_factory=list)
    reply_to: str = ""
    thread_id: str = ""
    message_id_header: str = ""
    gmail_account: str = ""


@dataclass
class Msg:
    sender: str
    body: str
    ts: datetime
    is_me: bool
    source: str
    attachments: list[dict[str, str | int]] = field(default_factory=list)
    message_id: str = ""  # Gmail message ID, empty for iMessage


@dataclass
class CalendarEvent:
    summary: str
    start: datetime
    end: datetime
    location: str = ""
    description: str = ""
    account: str = ""
    all_day: bool = False
    event_id: str = ""
    calendar_id: str = ""
    attendees: list[dict[str, str]] = field(default_factory=list)
    recurrence: list[str] = field(default_factory=list)
    reminders: dict = field(default_factory=dict)
    recurring_event_id: str = ""


@dataclass
class Note:
    id: str
    title: str
    snippet: str
    modified: datetime
    folder: str = ""


@dataclass
class Reminder:
    id: str
    title: str
    completed: bool
    list_name: str = ""
    due_date: datetime | None = None
    notes: str = ""
    priority: int = 0
    flagged: bool = False
    creation_date: datetime | None = None


@dataclass
class GoogleTask:
    id: str
    title: str
    status: str  # "needsAction" | "completed"
    list_id: str
    list_title: str
    due: datetime | None = None
    notes: str = ""
    completed: datetime | None = None


@dataclass
class GitHubNotification:
    id: str
    title: str
    repo: str
    type: str  # "PullRequest", "Issue", "Release", etc.
    reason: str  # "review_requested", "mention", "subscribed", etc.
    unread: bool
    updated_at: datetime
    url: str = ""


@dataclass
class DriveFile:
    id: str
    name: str
    mime_type: str
    modified: datetime
    size: int = 0
    shared: bool = False
    web_link: str = ""
    parents: list[str] = field(default_factory=list)
    account: str = ""


@dataclass
class SheetTab:
    sheet_id: int
    title: str
    index: int
    row_count: int
    col_count: int


@dataclass
class Spreadsheet:
    id: str
    title: str
    url: str
    sheets: list[SheetTab] = field(default_factory=list)
    account: str = ""


@dataclass
class Document:
    id: str
    title: str
    url: str
    mime_type: str = "application/vnd.google-apps.document"
    account: str = ""


@dataclass
class ThreadSummary:
    thread_id: str
    owning_account: str
    participants: list[str]
    subject: str
    last_message_at: datetime
    label_ids: list[str]
    body_text: str
    last_message_body: str
    last_sender_is_me: bool
    message_count: int


@dataclass(frozen=True)
class ApprovalGateDecision:
    provider: str
    operation: str
    approval_class: str
    executor: str
    can_execute: bool
    reason: str
    target_resource: str = ""
    account: str = ""
    item_count: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ApprovalLease:
    lease_id: str
    method: str
    path: str
    provider: str
    operation: str
    approval_class: str
    executor: str
    account_ref: str
    resource_ref: str
    item_count: int
    payload_hash: str
    query_hash: str
    not_after: datetime
    nonce: str
    allowed_uses: int = 1
    spent: bool = False
