"""Provider-neutral read-only Life Ops triage projection."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any


def _source_for_item(item: dict[str, Any]) -> str:
    source = str(item.get("source") or "").strip()
    if source:
        return source
    ref = item.get("ref")
    if isinstance(ref, dict):
        return str(ref.get("source") or "unknown")
    if item.get("thread_id"):
        return "gmail"
    return "unknown"


def _key(item: dict[str, Any]) -> str:
    ref = item.get("ref") or item.get("source_ref")
    if isinstance(ref, dict):
        parts = [
            str(ref.get(name) or "")
            for name in ("source", "kind", "thread_id", "id", "commitment_id", "capture_id")
        ]
        if any(parts):
            return ":".join(parts)
    source = _source_for_item(item)
    kind = str(item.get("kind") or ("thread" if item.get("thread_id") else ""))
    identity = str(
        item.get("thread_id")
        or item.get("id")
        or item.get("commitment_id")
        or item.get("capture_id")
        or item.get("title")
        or item.get("subject")
        or item.get("raw_text")
        or ""
    )
    if source or kind or identity:
        return f"{source}:{kind}:{identity}"
    return ":".join(
        str(item.get(name) or "")
        for name in ("source", "kind", "commitment_id", "capture_id", "title")
    )


def _normalize(item: dict[str, Any], *, source: str, state: str, attention_class: str) -> dict[str, Any]:
    ref = item.get("ref") or item.get("source_ref") or {}
    if not ref and item.get("thread_id"):
        ref = {
            "kind": "thread",
            "source": source,
            "thread_id": str(item["thread_id"]),
            "account": str(item.get("owning_account") or ""),
        }
    if not item.get("kind") and item.get("thread_id"):
        item = {**item, "kind": "thread"}
    return {
        "item_id": _key(item),
        "title": str(item.get("title") or item.get("subject") or item.get("raw_text") or "Untitled"),
        "source": source,
        "state": state,
        "attention_class": attention_class,
        "reason": str(item.get("reason") or item.get("next_condition") or "needs_attention"),
        "due_at": item.get("due") or item.get("start") or item.get("next_condition_at"),
        "workflow": str(item.get("workflow") or ""),
        "source_ref": ref,
        "details": item,
    }


def merge_triage(
    inbox_now: dict[str, Any] | None,
    life_attention: dict[str, Any],
    *,
    limit: int = 25,
) -> dict[str, Any]:
    """Merge Inbox's current read model with local Life Ops state.

    This is a projection only. It does not copy or mutate Gmail, Calendar,
    Tasks, or any other source authority.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")

    checked_at = datetime.now(UTC).isoformat()
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(item: dict[str, Any], *, source: str, state: str, attention_class: str) -> None:
        normalized = _normalize(
            item,
            source=source,
            state=state,
            attention_class=attention_class,
        )
        item_key = normalized["item_id"]
        if item_key in seen:
            return
        seen.add(item_key)
        items.append(normalized)

    inbox = inbox_now or {}
    for item in inbox.get("now_items", []) or []:
        if isinstance(item, dict):
            add(item, source=_source_for_item(item), state="READY_HUMAN", attention_class="now")
    for item in inbox.get("waiting_threads", []) or []:
        if isinstance(item, dict):
            add(item, source=_source_for_item(item), state="WAITING", attention_class="waiting")

    for item in life_attention.get("items", []) or []:
        if isinstance(item, dict):
            add(
                item,
                source="lifeops",
                state=str(item.get("state") or "REVIEW"),
                attention_class="commitment",
            )
    for item in life_attention.get("capture_failures", []) or []:
        if isinstance(item, dict):
            add(item, source="lifeops", state="REVIEW", attention_class="capture_failure")

    priority = {"capture_failure": 0, "commitment": 1, "now": 2, "waiting": 3}
    items.sort(key=lambda item: (priority.get(item["attention_class"], 9), item["due_at"] or "", item["item_id"]))
    counts = Counter(item["source"] for item in items)
    attention_items = [item for item in items if item["attention_class"] != "waiting"]
    source_health = {
        "inbox": {
            "status": "ok" if inbox_now is not None else "unavailable",
            "read_only": True,
            "reasons": list(inbox.get("reasons", [])) if inbox_now else ["inbox_read_failed"],
        },
        "lifeops": {"status": "ok", "read_only": True, "reasons": []},
    }
    return {
        "checked_at": checked_at,
        "read_only": True,
        "needs_attention": bool(attention_items),
        "message": "Nothing needs you." if not attention_items else f"{len(attention_items)} item(s) need you.",
        "items": items[:limit],
        "counts": dict(counts),
        "source_health": source_health,
        "inbox_read_model": inbox.get("read_model", "unavailable"),
        "workflow_counts": dict(inbox.get("workflow_counts", {})),
    }
