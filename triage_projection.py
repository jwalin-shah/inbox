"""Read-only, evidence-backed triage projection for indexed messages.

The message index remains the operational read model and the event log remains
the evidence authority.  This module only derives a bounded review queue; it
does not label, archive, reply to, or otherwise mutate a source.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from event_store import RawEventStore
from message_index_store import MessageIndexStore

TRIAGE_CATEGORIES = ("reply_now", "task", "calendar", "waiting", "fyi", "archive")

_CALENDAR_RE = re.compile(
    r"\b(?:today|tomorrow|tonight|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday|appointment|practice|pickup|pick up|meeting|call|event|"
    r"at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b",
    re.IGNORECASE,
)
_TASK_RE = re.compile(
    r"\b(?:please|can you|could you|need to|remember to|send|review|confirm|"
    r"approve|complete|submit|schedule|call|follow up|follow-up|buy|bring)\b",
    re.IGNORECASE,
)


def _text(row: dict[str, Any]) -> str:
    return "\n".join(
        str(row.get(key) or "")
        for key in ("latest_subject", "latest_snippet", "summary", "open_loop", "topic")
    ).strip()


def _source_object_id(row: dict[str, Any]) -> str:
    return f"{row.get('account') or ''}:{row.get('latest_external_id') or ''}"


def _category(row: dict[str, Any]) -> tuple[str, list[str], float]:
    actionability = str(row.get("actionability") or "")
    noise = str(row.get("noise_class") or "")
    urgency = str(row.get("urgency") or "")
    latest_sender = str(row.get("latest_sender") or "")
    text = _text(row)
    signals: list[str] = []

    if actionability in {"archive", "ignore"} or noise in {
        "dev-notification",
        "newsletter",
        "automated",
        "otp",
        "survey",
    }:
        signals.append(f"source_classifier:{actionability or noise}")
        return "archive", signals, 0.98

    request_from_other = latest_sender != "Me" and bool(
        re.search(r"\b(?:can you|could you|would you|please|let me know|confirm)\b", text, re.IGNORECASE)
    )
    if bool(row.get("needs_reply")) or actionability == "reply" or request_from_other:
        signals.append("needs_reply")
        if request_from_other and actionability != "reply":
            signals.append("direct_request_language")
        if urgency:
            signals.append(f"urgency:{urgency}")
        return "reply_now", signals, 0.97

    if latest_sender == "Me" and (actionability == "track" or row.get("open_loop")):
        signals.append("latest_message_from_me")
        signals.append("open_loop" if row.get("open_loop") else "track_actionability")
        return "waiting", signals, 0.91

    if noise == "appointment" or _CALENDAR_RE.search(text):
        signals.append("commitment_or_time_signal")
        if urgency:
            signals.append(f"urgency:{urgency}")
        return "calendar", signals, 0.89

    if actionability in {"review", "track"} or _TASK_RE.search(text):
        signals.append(f"actionability:{actionability or 'task_language'}")
        if row.get("open_loop"):
            signals.append("open_loop")
        return "task", signals, 0.84

    if row.get("is_read") == 0 or int(row.get("unread_count") or 0) > 0:
        signals.append("unread")
        return "fyi", signals, 0.72

    return "fyi", ["no_action_signal"], 0.68


def _why(category: str, row: dict[str, Any], signals: list[str]) -> str:
    topic = str(row.get("topic") or "general")
    sender = str(row.get("latest_sender") or "unknown sender")
    if category == "reply_now":
        return f"{sender} appears to be waiting for your reply."
    if category == "calendar":
        return f"This mentions a time-bound commitment or appointment ({topic})."
    if category == "task":
        return f"This contains an open loop or action signal ({topic})."
    if category == "waiting":
        return "You were the latest sender and the thread still has an open loop."
    if category == "archive":
        return "The source classifier marked this as automated, newsletter, security-code, or other low-actionability traffic."
    return "No reliable action signal was found; keep it as context until more evidence arrives."


def _evidence(
    row: dict[str, Any],
    event_store: RawEventStore,
) -> dict[str, Any]:
    source = str(row.get("source") or "")
    object_id = _source_object_id(row)
    events = event_store.list_for_source_object(source, object_id, limit=10)
    content_ref = ""
    if source == "gmail":
        content_ref = f"gmail:{row.get('account') or ''}:{row.get('latest_external_id') or ''}"
    elif source == "imessage":
        content_ref = f"imessage:{row.get('thread_id') or ''}:{row.get('latest_external_id') or ''}"
    return {
        "source": source,
        "account": str(row.get("account") or ""),
        "thread_id": str(row.get("thread_id") or ""),
        "external_id": str(row.get("latest_external_id") or ""),
        "content_ref": content_ref,
        "event_ids": [event.event_id for event in events],
        "raw_payload_available": any(
            bool(event.provenance.get("raw_payload_available", True))
            for event in events
        ),
    }


def triage_message_threads(
    index_store: MessageIndexStore,
    event_store: RawEventStore,
    *,
    source: str = "",
    account: str = "",
    category: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Build a bounded message triage queue without performing provider calls."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if offset < 0:
        raise ValueError("offset must be non-negative")
    if category and category not in TRIAGE_CATEGORIES:
        raise ValueError(f"category must be one of: {', '.join(TRIAGE_CATEGORIES)}")

    rows = index_store.list_threads(
        limit=max(offset + limit * 4, 100),
        source=source or None,
        account=account or None,
        newest_only=False,
        sort_mode="priority",
    )
    checked_at = datetime.now(UTC).isoformat()
    items: list[dict[str, Any]] = []
    for row in rows:
        typed = dict(row)
        item_category, signals, confidence = _category(typed)
        if category and item_category != category:
            continue
        evidence = _evidence(typed, event_store)
        items.append(
            {
                "item_id": f"{typed.get('source')}:{typed.get('account')}:{typed.get('thread_id')}",
                "category": item_category,
                "usefulness": "high" if item_category in {"reply_now", "task", "calendar"} else "medium" if item_category == "waiting" else "low",
                "confidence": confidence,
                "why_it_matters": _why(item_category, typed, signals),
                "signals": signals,
                "source": typed.get("source"),
                "account": typed.get("account"),
                "thread_id": typed.get("thread_id"),
                "title": typed.get("latest_subject") or typed.get("latest_snippet") or "Untitled thread",
                "summary": typed.get("summary") or typed.get("latest_snippet") or "",
                "sender": typed.get("latest_sender") or "",
                "last_message_at": typed.get("latest_item_at") or "",
                "topic": typed.get("topic") or "general",
                "urgency": typed.get("urgency") or "low",
                "actionability": typed.get("actionability") or "",
                "open_loop": typed.get("open_loop") or "",
                "unread_count": int(typed.get("unread_count") or 0),
                "message_count": int(typed.get("message_count") or 0),
                "evidence": evidence,
                "attribution": {
                    "authority": str(typed.get("source") or "message_index"),
                    "source": typed.get("source"),
                    "account": typed.get("account"),
                    "reference": evidence,
                    "source_timestamp": typed.get("latest_item_at"),
                    "retrieved_at": checked_at,
                    "derived": True,
                    "read_only": True,
                    "method": "inbox_message_triage_v1",
                },
            }
        )

    order = {"reply_now": 0, "calendar": 1, "task": 2, "waiting": 3, "fyi": 4, "archive": 5}
    # Keep the category priority deterministic, but show the freshest evidence
    # first within each category.  An ascending timestamp here made the first
    # page of a bounded review queue start with the stalest reply/task items.
    items.sort(key=lambda item: item["last_message_at"] or "", reverse=True)
    items.sort(key=lambda item: order[item["category"]])
    bounded = items[offset : offset + limit]
    return {
        "checked_at": checked_at,
        "read_only": True,
        "projection": "inbox_message_triage_v1",
        "items": bounded,
        "counts": dict(Counter(item["category"] for item in items)),
        "returned_count": len(bounded),
        "filters": {"source": source, "account": account, "category": category},
        "coverage": {
            "read_model": "message_index.threads",
            "evidence_store": str(event_store.db_path),
            "source_db": str(index_store.db_path),
            "provider_calls": False,
            "candidate_threads_scanned": len(rows),
            "candidate_items": len(items),
            "page_offset": offset,
            "page_limit": limit,
        },
        "authority_rule": "Source systems and the append-only event log remain authoritative; this is a derived review queue.",
    }
