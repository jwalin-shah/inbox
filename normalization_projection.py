"""Read-only normalization reports for indexed communication and action work.

The index and append-only event log remain authoritative.  These projections
make account coverage and action candidates explicit without creating tasks or
changing Gmail/iMessage state.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from event_store import RawEventStore
from message_index_store import MessageIndexStore
from triage_projection import _category, _evidence, _why


def _checked_at() -> str:
    return datetime.now(UTC).isoformat()


def _candidate_id(source: str, account: str, thread_id: str) -> str:
    raw = f"{source}\x00{account}\x00{thread_id}".encode()
    return f"todo_{hashlib.sha256(raw).hexdigest()[:24]}"


def _account_rows(index_store: MessageIndexStore) -> list[dict[str, Any]]:
    with index_store._connect() as conn:  # noqa: SLF001 - same local read model
        rows = conn.execute(
            """
            SELECT source, account,
                   COUNT(*) AS item_count,
                   COUNT(DISTINCT thread_id) AS thread_count,
                   SUM(CASE WHEN is_read = 0 THEN 1 ELSE 0 END) AS unread_item_count,
                   MAX(created_at) AS latest_item_at
            FROM items
            WHERE is_deleted = 0
            GROUP BY source, account
            ORDER BY source, account
            """
        ).fetchall()
        thread_rows = conn.execute(
            """
            SELECT source, account,
                   SUM(CASE WHEN actionability = 'reply' OR needs_reply = 1 THEN 1 ELSE 0 END) AS reply_count,
                   SUM(CASE WHEN actionability IN ('review', 'track') THEN 1 ELSE 0 END) AS actionable_count,
                   SUM(CASE WHEN open_loop != '' THEN 1 ELSE 0 END) AS open_loop_count,
                   SUM(CASE WHEN urgency IN ('high', 'medium') THEN 1 ELSE 0 END) AS time_sensitive_count
            FROM threads
            GROUP BY source, account
            """
        ).fetchall()
        sync_rows = conn.execute(
            "SELECT * FROM sync_state ORDER BY source, account"
        ).fetchall()

    stats = {(str(row["source"]), str(row["account"])): dict(row) for row in rows}
    thread_stats = {(str(row["source"]), str(row["account"])): dict(row) for row in thread_rows}
    sync_stats = {(str(row["source"]), str(row["account"])): dict(row) for row in sync_rows}
    keys = sorted(set(stats) | set(sync_stats))
    result: list[dict[str, Any]] = []
    for source, account in keys:
        item = stats.get((source, account), {})
        threads = thread_stats.get((source, account), {})
        sync = sync_stats.get((source, account), {})
        status = str(sync.get("status") or "unknown")
        last_success = str(sync.get("last_success_at") or "")
        last_error = str(sync.get("last_error") or "")
        indexed = int(item.get("item_count") or 0) > 0
        healthy = status == "idle" and bool(last_success) and not last_error
        result.append(
            {
                "source": source,
                "account": account,
                "indexed": indexed,
                "item_count": int(item.get("item_count") or 0),
                "thread_count": int(item.get("thread_count") or 0),
                "unread_item_count": int(item.get("unread_item_count") or 0),
                "latest_item_at": str(item.get("latest_item_at") or ""),
                "reply_count": int(threads.get("reply_count") or 0),
                "actionable_count": int(threads.get("actionable_count") or 0),
                "open_loop_count": int(threads.get("open_loop_count") or 0),
                "time_sensitive_count": int(threads.get("time_sensitive_count") or 0),
                "sync": {
                    "status": status,
                    "last_success_at": last_success,
                    "last_full_sync_at": str(sync.get("last_full_sync_at") or ""),
                    "last_error": last_error,
                    "checkpoint_type": str(sync.get("checkpoint_type") or ""),
                },
                "coverage": "indexed_and_last_sync_healthy" if indexed and healthy else "needs_review",
            }
        )
    return result


def gmail_normalization(index_store: MessageIndexStore) -> dict[str, Any]:
    """Report local Gmail index coverage and action counts per account."""
    accounts = [row for row in _account_rows(index_store) if row["source"] == "gmail"]
    healthy = bool(accounts) and all(row["coverage"] == "indexed_and_last_sync_healthy" for row in accounts)
    return {
        "checked_at": _checked_at(),
        "read_only": True,
        "projection": "gmail_normalization_v1",
        "accounts": accounts,
        "account_count": len(accounts),
        "complete": healthy,
        "coverage_basis": "local_message_index_and_sync_state",
        "not_proven": [
            "provider-side mailbox completeness beyond the recorded sync checkpoint",
            "that every candidate is already represented in Google Tasks",
        ],
        "authority_rule": "Gmail remains the source authority; this is a derived local report.",
    }


def todo_candidates(
    index_store: MessageIndexStore,
    event_store: RawEventStore,
    *,
    source: str = "",
    account: str = "",
    category: str = "",
    limit: int = 100,
) -> dict[str, Any]:
    """Return deduplicated, attributable action candidates without writes."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if category and category not in {"reply_now", "task", "calendar", "waiting"}:
        raise ValueError("category must be one of: reply_now, task, calendar, waiting")
    rows = index_store.list_threads(
        limit=max(limit * 8, 200),
        source=source or None,
        account=account or None,
        actionable_only=True,
        sort_mode="priority",
    )
    candidates: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    checked_at = _checked_at()
    for typed in rows:
        item_category, signals, confidence = _category(typed)
        if item_category not in {"reply_now", "task", "calendar", "waiting"}:
            continue
        if category and category != item_category:
            continue
        evidence = _evidence(typed, event_store)
        source_name = str(typed.get("source") or "")
        account_name = str(typed.get("account") or "")
        thread_id = str(typed.get("thread_id") or "")
        candidate = {
            "candidate_id": _candidate_id(source_name, account_name, thread_id),
            "status": "needs_task_reconciliation",
            "task_match": "not_checked",
            "category": item_category,
            "confidence": confidence,
            "title": str(typed.get("latest_subject") or typed.get("latest_snippet") or "Follow up")[:240],
            "suggested_task_title": str(typed.get("open_loop") or typed.get("latest_subject") or typed.get("latest_snippet") or "Follow up")[:240],
            "notes": _why(item_category, typed, signals),
            "signals": signals,
            "source": source_name,
            "account": account_name,
            "thread_id": thread_id,
            "sender": str(typed.get("latest_sender") or ""),
            "last_message_at": str(typed.get("latest_item_at") or ""),
            "topic": str(typed.get("topic") or "general"),
            "open_loop": str(typed.get("open_loop") or ""),
            "evidence": evidence,
            "proposed_task_payload": {
                "title": str(typed.get("open_loop") or typed.get("latest_subject") or typed.get("latest_snippet") or "Follow up")[:240],
                "notes": f"LifeOps candidate { _candidate_id(source_name, account_name, thread_id) }. Source: {source_name}/{account_name}/{thread_id}.",
                "source": source_name,
                "account": account_name,
                "thread_id": thread_id,
            },
            "attribution": {
                "authority": source_name or "message_index",
                "source": source_name,
                "account": account_name,
                "reference": evidence,
                "source_timestamp": typed.get("latest_item_at"),
                "retrieved_at": checked_at,
                "derived": True,
                "read_only": True,
                "method": "inbox_todo_candidates_v1",
            },
        }
        candidates.append(candidate)
        counts[item_category] += 1
    order = {"reply_now": 0, "calendar": 1, "task": 2, "waiting": 3}
    candidates.sort(key=lambda item: (order[item["category"]], item["last_message_at"] or ""))
    bounded = candidates[:limit]
    return {
        "checked_at": checked_at,
        "read_only": True,
        "projection": "inbox_todo_candidates_v1",
        "items": bounded,
        "counts": dict(counts),
        "returned_count": len(bounded),
        "filters": {"source": source, "account": account, "category": category},
        "task_recording": {
            "status": "proposal_only",
            "automatic_creation": False,
            "next_step": "Read current Tasks, reconcile this candidate, then use the exact proposed_task_payload with an approval-gated task proposal if it is still missing.",
        },
        "coverage": {
            "read_model": "message_index.threads",
            "evidence_store": str(event_store.db_path),
            "source_db": str(index_store.db_path),
            "provider_calls": False,
        },
        "authority_rule": "Source systems and the append-only event log remain authoritative; candidates require review before task creation.",
    }


def _normalise_title(value: object) -> str:
    import re

    text = re.sub(r"^\s*(?:\[[^\]]+\]\s*)+", "", str(value or "").lower())
    return " ".join(re.findall(r"[a-z0-9]+", text))


_TASK_MATCH_STOPWORDS = {
    "a", "an", "and", "at", "for", "from", "in", "is", "it", "my", "of",
    "on", "or", "re", "the", "to", "up", "with", "your",
}


def _meaningful_title_tokens(value: object) -> set[str]:
    return {
        token
        for token in _normalise_title(value).split()
        if token not in _TASK_MATCH_STOPWORDS and len(token) > 2
    }


def _task_duplicate_groups(task_rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Return exact and conservative near-duplicate task groups.

    This is intentionally a report-only projection.  Tasks are only compared
    within the same account, and near-duplicates must share at least three
    meaningful title tokens with an overlap of at least 80% of the shorter
    title.  Short or generic titles therefore remain ungrouped unless their
    normalized titles are exactly equal.
    """
    parent = list(range(len(task_rows)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    normalized: list[str] = [_normalise_title(task.get("title")) for task in task_rows]
    tokens: list[set[str]] = [_meaningful_title_tokens(task.get("title")) for task in task_rows]
    exact: dict[tuple[str, str], int] = {}
    for index, task in enumerate(task_rows):
        key = (str(task.get("account") or ""), normalized[index])
        if key[1] and key in exact:
            union(exact[key], index)
        elif key[1]:
            exact[key] = index

    for left in range(len(task_rows)):
        left_account = str(task_rows[left].get("account") or "")
        if len(tokens[left]) < 3:
            continue
        for right in range(left + 1, len(task_rows)):
            if left_account != str(task_rows[right].get("account") or ""):
                continue
            if normalized[left] == normalized[right] or len(tokens[right]) < 3:
                continue
            overlap = len(tokens[left] & tokens[right])
            if overlap >= 3 and overlap / min(len(tokens[left]), len(tokens[right])) >= 0.8:
                union(left, right)

    grouped: dict[int, list[dict[str, Any]]] = {}
    for index, task in enumerate(task_rows):
        grouped.setdefault(find(index), []).append(task)
    return [group for group in grouped.values() if len(group) > 1]


def reconcile_tasks(
    candidate_report: dict[str, Any],
    tasks_by_account: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Match existing tasks to candidates conservatively without provider writes."""
    candidates = list(candidate_report.get("items") or [])
    task_rows = [task for tasks in tasks_by_account.values() for task in tasks]
    matched_task_ids: set[str] = set()
    candidate_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        account = str(candidate.get("account") or "")
        candidate_id = str(candidate.get("candidate_id") or "")
        variants = {
            _normalise_title(candidate.get("suggested_task_title")),
            _normalise_title(candidate.get("title")),
            _normalise_title(candidate.get("open_loop")),
        }
        variants.discard("")
        account_tasks = [task for task in task_rows if str(task.get("account") or "") == account]
        exact: list[dict[str, Any]] = []
        possible: list[dict[str, Any]] = []
        for task in account_tasks:
            notes = str(task.get("notes") or "")
            title = _normalise_title(task.get("title"))
            if (candidate_id and candidate_id in notes) or (title and title in variants):
                exact.append(task)
            elif title and any(
                len(_meaningful_title_tokens(task.get("title"))) >= 2
                and len(_meaningful_title_tokens(variant)) >= 2
                and len(
                    _meaningful_title_tokens(task.get("title"))
                    & _meaningful_title_tokens(variant)
                ) >= 2
                and (
                    len(
                        _meaningful_title_tokens(task.get("title"))
                        & _meaningful_title_tokens(variant)
                    )
                    / min(
                        len(_meaningful_title_tokens(task.get("title"))),
                        len(_meaningful_title_tokens(variant)),
                    )
                    >= 0.6
                )
                for variant in variants
            ):
                possible.append(task)
        if exact:
            status = "matched"
            matches = exact
        elif possible:
            status = "possible_match"
            matches = possible
        else:
            status = "missing"
            matches = []
        matched_task_ids.update(str(task.get("id") or "") for task in matches)
        candidate_rows.append(
            {
                **candidate,
                "task_status": status,
                "matched_task_ids": [str(task.get("id") or "") for task in matches],
                "task_match_confidence": 1.0 if exact else 0.7 if possible else 0.0,
            }
        )

    duplicate_groups = _task_duplicate_groups(task_rows)

    return {
        "checked_at": _checked_at(),
        "read_only": True,
        "projection": "inbox_task_reconciliation_v1",
        "candidates": candidate_rows,
        "candidate_counts": dict(Counter(row["task_status"] for row in candidate_rows)),
        "tasks": task_rows,
        "task_count": len(task_rows),
        "accounts": {
            account: {
                "task_count": len(tasks),
                "candidate_count": sum(1 for row in candidate_rows if row.get("account") == account),
                "matched_task_count": sum(
                    1 for row in candidate_rows if row.get("account") == account and row["task_status"] == "matched"
                ),
                "missing_candidate_count": sum(
                    1 for row in candidate_rows if row.get("account") == account and row["task_status"] == "missing"
                ),
            }
            for account, tasks in sorted(tasks_by_account.items())
        },
        "duplicate_task_groups": [
            [
                {"id": str(task.get("id") or ""), "account": task.get("account"), "title": task.get("title")}
                for task in group
            ]
            for group in duplicate_groups
        ],
        "unmatched_existing_task_count": sum(
            1 for task in task_rows if str(task.get("id") or "") not in matched_task_ids
        ),
        "coverage": {
            "candidate_projection": candidate_report.get("projection"),
            "candidate_limit": candidate_report.get("returned_count"),
            "tasks_provider_read": True,
            "provider_writes": False,
        },
        "authority_rule": "Google Tasks and source messages remain authoritative; matches are conservative derived suggestions.",
    }
