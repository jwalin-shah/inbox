"""Provider-neutral, read-only LifeOps triage with explicit provenance."""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any

TRIAGE_CATEGORIES = (
    "reply_now",
    "task",
    "calendar",
    "waiting",
    "fyi",
    "archive",
)


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


def _item_key(item: dict[str, Any], source: str) -> str:
    ref = item.get("ref") or item.get("source_ref")
    if isinstance(ref, dict):
        parts = [
            str(ref.get(name) or "")
            for name in ("source", "kind", "thread_id", "id", "commitment_id", "capture_id")
        ]
        if any(parts):
            return ":".join(parts)
    identity = str(
        item.get("thread_id")
        or item.get("id")
        or item.get("commitment_id")
        or item.get("capture_id")
        or item.get("title")
        or item.get("subject")
        or ""
    )
    return f"{source}:{item.get('kind') or 'item'}:{identity}"


def _attribution(
    item: dict[str, Any],
    source: str,
    ref: dict[str, Any],
    retrieved_at: str,
) -> dict[str, Any]:
    """Return provenance without pretending the projection is source authority."""
    return {
        "authority": source,
        "source": source,
        "account": ref.get("account") or item.get("account") or item.get("owning_account") or "",
        "reference": ref,
        "source_timestamp": item.get("updated_at") or item.get("created_at") or item.get("start") or None,
        "retrieved_at": retrieved_at,
        "derived": True,
        "read_only": True,
        "method": "inbox_now_rule_projection",
    }


def _normalize(
    item: dict[str, Any],
    *,
    source: str,
    state: str,
    attention_class: str,
    retrieved_at: str,
) -> dict[str, Any]:
    ref = item.get("ref") or item.get("source_ref") or {}
    if not isinstance(ref, dict):
        ref = {}
    if not ref and item.get("thread_id"):
        ref = {
            "kind": "thread",
            "source": source,
            "thread_id": str(item["thread_id"]),
            "account": str(item.get("owning_account") or ""),
        }
    title = str(item.get("title") or item.get("subject") or item.get("raw_text") or "Untitled")
    return {
        "item_id": _item_key(item, source),
        "title": title,
        "source": source,
        "state": state,
        "attention_class": attention_class,
        "reason": str(item.get("reason") or item.get("next_condition") or "needs_attention"),
        "due_at": item.get("due") or item.get("start") or item.get("next_condition_at"),
        "workflow": str(item.get("workflow") or ""),
        "source_ref": ref,
        "attribution": _attribution(item, source, ref, retrieved_at),
        "details": item,
    }


def build_triage(inbox_now: dict[str, Any] | None, *, limit: int = 25) -> dict[str, Any]:
    """Build a bounded attention projection from Inbox's read-only `/inbox/now`."""
    if limit < 1:
        raise ValueError("limit must be at least 1")

    checked_at = datetime.now(UTC).isoformat()
    inbox = inbox_now or {}
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(item: dict[str, Any], *, source: str, state: str, attention_class: str) -> None:
        normalized = _normalize(
            item,
            source=source,
            state=state,
            attention_class=attention_class,
            retrieved_at=checked_at,
        )
        if normalized["item_id"] in seen:
            return
        seen.add(normalized["item_id"])
        items.append(normalized)

    for item in inbox.get("now_items", []) or []:
        if isinstance(item, dict):
            add(item, source=_source_for_item(item), state="READY_HUMAN", attention_class="now")
    for item in inbox.get("waiting_threads", []) or []:
        if isinstance(item, dict):
            add(item, source=_source_for_item(item), state="WAITING", attention_class="waiting")

    priority = {"now": 0, "waiting": 1}
    items.sort(key=lambda item: (priority.get(item["attention_class"], 9), item["due_at"] or "", item["item_id"]))
    counts = Counter(item["source"] for item in items)
    attention_items = [item for item in items if item["attention_class"] != "waiting"]
    inbox_status = "ok" if inbox_now is not None else "unavailable"
    reasons = list(inbox.get("reasons", [])) if inbox_now else ["inbox_read_failed"]

    return {
        "checked_at": checked_at,
        "read_only": True,
        "projection": "lifeops_triage_v1",
        "needs_attention": bool(attention_items),
        "message": "Nothing needs you." if not attention_items else f"{len(attention_items)} item(s) need you.",
        "items": items[:limit],
        "counts": dict(counts),
        "coverage": {
            "inbox_now": {
                "status": inbox_status,
                "read_only": True,
                "reasons": reasons,
                "read_model": inbox.get("read_model", "unavailable"),
                "index_health": inbox.get("index_health", {}),
            },
        },
        "authority_rule": "Source systems remain authoritative; this is a derived attention projection.",
    }


def _deterministic_category(item: dict[str, Any]) -> str:
    """Choose a safe fallback category from explicit source state only."""
    details = item.get("details") if isinstance(item.get("details"), dict) else item
    if details.get("needs_reply") or details.get("actionability") == "reply":
        return "reply_now"
    if item.get("attention_class") == "waiting" or item.get("state") == "WAITING":
        return "waiting"
    if item.get("source") == "calendar" or details.get("kind") == "event":
        return "calendar"
    if item.get("source") == "tasks" or details.get("kind") == "task":
        return "task"
    if details.get("actionability") in {"review", "track"} and details.get("open_loop"):
        return "task"
    return "fyi"


def _source_ref(raw: dict[str, Any], *, source: str, kind: str, account: str) -> dict[str, Any]:
    if source == "gmail":
        return {
            "kind": kind,
            "source": source,
            "thread_id": str(raw.get("thread_id") or raw.get("id") or ""),
            "account": account,
        }
    if source == "calendar":
        return {
            "kind": kind,
            "source": source,
            "id": str(raw.get("event_id") or raw.get("id") or ""),
            "calendar_id": str(raw.get("calendar_id") or "primary"),
            "account": account,
        }
    if source == "tasks":
        return {
            "kind": kind,
            "source": source,
            "id": str(raw.get("id") or ""),
            "list_id": str(raw.get("list_id") or "@default"),
            "account": account,
        }
    return {
        "kind": kind,
        "source": source,
        "id": str(raw.get("id") or raw.get("chat_id") or ""),
        "account": account,
    }


def _candidate(
    raw: dict[str, Any],
    *,
    source: str,
    kind: str,
    account: str,
    retrieved_at: str,
    title: str,
    summary: str,
    timestamp: Any = None,
    state: str = "OBSERVED",
    attention_class: str = "context",
) -> dict[str, Any]:
    ref = _source_ref(raw, source=source, kind=kind, account=account)
    item = {
        "item_id": _item_key({"ref": ref, "title": title}, source),
        "title": title or "Untitled",
        "summary": summary,
        "source": source,
        "state": state,
        "attention_class": attention_class,
        "reason": str(raw.get("reason") or raw.get("open_loop") or "observed_source_item"),
        "due_at": raw.get("due") or raw.get("start") or raw.get("last_ts") or timestamp,
        "source_ref": ref,
        "details": raw,
        "attribution": {
            "authority": source,
            "source": source,
            "account": account,
            "reference": ref,
            "source_timestamp": timestamp or raw.get("last_message_at") or raw.get("start"),
            "retrieved_at": retrieved_at,
            "derived": True,
            "read_only": True,
            "method": "lifeops_unified_triage_projection",
        },
    }
    item["category"] = _deterministic_category(item)
    return item


def build_unified_triage(
    inbox_now: dict[str, Any] | None,
    read_proof: dict[str, Any] | None,
    *,
    imessage_conversations: list[dict[str, Any]] | None = None,
    sheets: list[dict[str, Any]] | None = None,
    contacts: list[dict[str, Any]] | None = None,
    provider_health: dict[str, Any] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Combine read-only source snapshots into a bounded triage candidate set."""
    if limit < 1:
        raise ValueError("limit must be at least 1")

    checked_at = datetime.now(UTC).isoformat()
    base = build_triage(inbox_now, limit=max(limit, 25))
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(item: dict[str, Any]) -> None:
        item_id = str(item.get("item_id") or "")
        if not item_id or item_id in seen:
            return
        seen.add(item_id)
        item["category"] = _deterministic_category(item)
        items.append(item)

    for item in base.get("items", []):
        if isinstance(item, dict):
            add(item)

    proof_sources = (read_proof or {}).get("sources", {})
    for source, kind, title_key, summary_key, account_key in (
        ("gmail", "thread", "name", "snippet", "gmail_account"),
        ("calendar", "event", "summary", "description", "account"),
        ("tasks", "task", "title", "notes", "account"),
    ):
        row = proof_sources.get(source) or {}
        for raw in row.get("items", []) or []:
            if not isinstance(raw, dict):
                continue
            account = str(raw.get(account_key) or "")
            title = str(raw.get(title_key) or raw.get("subject") or "Untitled")
            if source == "gmail":
                title = f"{title}: {raw.get('snippet') or ''}".rstrip(": ")
            add(
                _candidate(
                    raw,
                    source=source,
                    kind=kind,
                    account=account,
                    retrieved_at=checked_at,
                    title=title,
                    summary=str(raw.get(summary_key) or raw.get("snippet") or title),
                    timestamp=raw.get("last_ts") or raw.get("start") or raw.get("updated"),
                )
            )

    for raw in imessage_conversations or []:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("name") or raw.get("title") or raw.get("id") or "iMessage conversation")
        add(
            _candidate(
                raw,
                source="imessage",
                kind="conversation",
                account="local",
                retrieved_at=checked_at,
                title=title,
                summary=str(raw.get("snippet") or raw.get("last_message") or title),
                timestamp=raw.get("last_ts"),
            )
        )

    items.sort(
        key=lambda item: (
            {"reply_now": 0, "task": 1, "calendar": 2, "waiting": 3, "fyi": 4, "archive": 5}.get(
                item["category"], 9
            ),
            item.get("due_at") or "",
            item["item_id"],
        )
    )

    def source_coverage(source: str) -> dict[str, Any]:
        row = proof_sources.get(source) or {}
        return {
            "status": "ok" if row.get("ok") else ("unavailable" if row else "not_checked"),
            "read_only": True,
            "accounts": list(row.get("accounts") or []),
            "count": row.get("count", 0),
            "errors": row.get("errors") or [],
        }

    sheet_rows = [row for row in (sheets or []) if isinstance(row, dict)]
    sheet_accounts = sorted({str(row.get("account")) for row in sheet_rows if row.get("account")})
    imessage_rows = [row for row in (imessage_conversations or []) if isinstance(row, dict)]
    contact_rows = [row for row in (contacts or []) if isinstance(row, dict)]
    proof_ok = bool(read_proof and read_proof.get("ok"))
    return {
        "checked_at": checked_at,
        "read_only": True,
        "projection": "lifeops_unified_triage_v1",
        "items": items[:limit],
        "counts": dict(Counter(item["category"] for item in items[:limit])),
        "coverage": {
            "gateway_read_proof": {
                "status": "ok" if proof_ok else "unavailable",
                "read_only": True,
                "mutation_applied": bool((read_proof or {}).get("mutation_applied", False)),
                "blockers": (read_proof or {}).get("blockers") or [],
            },
            "gmail": source_coverage("gmail"),
            "calendar": source_coverage("calendar"),
            "tasks": source_coverage("tasks"),
            "imessage": {
                "status": "ok" if imessage_conversations is not None else "unavailable",
                "read_only": True,
                "account": "local",
                "conversation_count": len(imessage_rows),
            },
            "sheets": {
                "status": "ok" if sheets is not None else "unavailable",
                "read_only": True,
                "spreadsheet_count": len(sheet_rows),
                "accounts": sheet_accounts,
            },
            "contacts": {
                "status": "ok" if contacts is not None else "unavailable",
                "read_only": True,
                "sample_count": len(contact_rows),
            },
            "inbox_index": base.get("coverage", {}).get("inbox_now", {}).get("index_health", {}),
            "providers": provider_health or {},
        },
        "context_sources": {
            "sheets": [
                {
                    "id": row.get("id"),
                    "title": row.get("title") or row.get("name"),
                    "account": row.get("account", ""),
                }
                for row in sheet_rows
            ],
        },
        "model": {
            "status": "not_run",
            "method": "deterministic_source_projection",
        },
        "authority_rule": "Source systems remain authoritative; categories and counts are derived, read-only projections.",
    }


def apply_model_labels(result: dict[str, Any], model_result: dict[str, Any]) -> dict[str, Any]:
    """Join validated model labels back to evidence without accepting new IDs."""
    labels = model_result.get("labels") if isinstance(model_result, dict) else {}
    labels = labels if isinstance(labels, dict) else {}
    classified = 0
    model_name = str(model_result.get("model") or "model")
    classification_method = re.sub(r"[^a-z0-9]+", "_", model_name.lower()).strip("_") or "model"
    # Preserve the established receipt name for the existing DeepSeek route
    # while allowing new routed models (for example Kimi K3) to be attributed
    # by their actual returned model name.
    if classification_method == "deepseek_deepseek_v4_pro":
        classification_method = "deepseek_v4_pro"
    for item in result.get("items", []):
        item_id = item.get("item_id")
        label = labels.get(item_id)
        guarded = bool(
            item.get("attention_class") == "waiting"
            or item.get("state") == "WAITING"
            or item.get("source") in {"calendar", "tasks"}
        )
        deterministic_category = _deterministic_category(item)
        model_category = label.get("category") if isinstance(label, dict) else None
        # Models may refine a candidate, but may not manufacture a reply
        # obligation that the source-derived projection did not establish.
        reply_promotion_blocked = model_category == "reply_now" and deterministic_category != "reply_now"
        if (
            isinstance(label, dict)
            and model_category in TRIAGE_CATEGORIES
            and not guarded
            and not reply_promotion_blocked
        ):
            item["category"] = label["category"]
            item["classification_confidence"] = label.get("confidence")
            item["classification_method"] = classification_method
            classified += 1
        else:
            item["classification_method"] = (
                "deterministic_guardrail"
                if guarded or reply_promotion_blocked
                else "deterministic_fallback"
            )
    result["counts"] = dict(Counter(item["category"] for item in result.get("items", [])))
    result["model"] = {
        **{key: value for key, value in model_result.items() if key != "labels"},
        "classified_items": classified,
    }
    return result
