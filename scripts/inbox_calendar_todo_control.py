#!/usr/bin/env python3
"""Dry-run inbox/calendar/todo control surface.

This command intentionally stops at reviewable proposals. It does not call
Gmail, Calendar, Tasks, or connector CLIs, and it has no live write path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCHEMA_VERSION = "inbox.calendar_todo_control.v0"
DEFAULT_NOW = "2026-06-05T12:00:00-07:00"
ACTION_RE = re.compile(
    r"\b(please|can you|could you|need you to|follow up|send|schedule|review|call|book|hold)\b",
    re.IGNORECASE,
)
ISO_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
ISO_TIME_RANGE_RE = re.compile(
    r"\b(20\d{2}-\d{2}-\d{2})[ T](\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})\b"
)
STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "by",
    "can",
    "could",
    "for",
    "i",
    "me",
    "please",
    "the",
    "to",
    "you",
}


def _now(value: str | None = None) -> datetime:
    raw = value or DEFAULT_NOW
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _clean_title(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip(" .")
    text = re.sub(r"^(please|can you|could you|need you to)\s+", "", text, flags=re.I)
    text = re.sub(r"\s+by\s+20\d{2}-\d{2}-\d{2}.*$", "", text, flags=re.I)
    text = re.sub(r"\s+on\s+20\d{2}-\d{2}-\d{2}.*$", "", text, flags=re.I)
    text = re.sub(
        r"\s+20\d{2}-\d{2}-\d{2}\s+\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2}.*$",
        "",
        text,
        flags=re.I,
    )
    return text[:160] or "Untitled action"


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 1 and token not in STOPWORDS
    }


def _similar(left: str, right: str) -> bool:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens)
    return overlap / max(1, min(len(left_tokens), len(right_tokens))) >= 0.6


def _parse_due(text: str) -> str:
    match = ISO_DATE_RE.search(text)
    return match.group(1) if match else ""


def _parse_hold(text: str) -> dict[str, str] | None:
    match = ISO_TIME_RANGE_RE.search(text)
    if not match:
        return None
    date, start, end = match.groups()
    return {"start": f"{date}T{start}:00", "end": f"{date}T{end}:00"}


def _message_text(message: dict[str, Any]) -> str:
    return " ".join(
        str(message.get(key, ""))
        for key in ("subject", "title", "snippet", "body")
        if message.get(key)
    )


def _action_text(message: dict[str, Any]) -> str:
    for key in ("action_title", "snippet", "body", "subject", "title"):
        value = str(message.get(key) or "")
        if value and ACTION_RE.search(value):
            return value
    return _message_text(message)


def _source_ref(item: dict[str, Any], fallback_source: str) -> str:
    source = str(item.get("source") or fallback_source)
    item_id = str(item.get("id") or _stable_id("item", json.dumps(item, sort_keys=True)))
    return f"{source}:{item_id}"


def _evidence_for(item: dict[str, Any], fallback_source: str) -> dict[str, Any]:
    text = _message_text(item) or str(item.get("title") or item.get("summary") or "")
    return {
        "id": _source_ref(item, fallback_source),
        "source": str(item.get("source") or fallback_source),
        "source_id": str(item.get("id") or ""),
        "title": str(item.get("subject") or item.get("title") or item.get("summary") or ""),
        "timestamp": str(item.get("timestamp") or item.get("updated") or item.get("start") or ""),
        "url": str(item.get("url") or item.get("link") or ""),
        "snippet": text[:240],
    }


def _extract_actionable(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evidence: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    seen: set[str] = set()

    for message in messages:
        text = _message_text(message)
        if not text or not ACTION_RE.search(text):
            continue
        evidence_item = _evidence_for(message, "inbox")
        evidence.append(evidence_item)
        hold = _parse_hold(text)
        due = _parse_due(text)
        title_source = _action_text(message)
        title = _clean_title(title_source)
        fingerprint = " ".join(sorted(_tokens(title)))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        actions.append(
            {
                "id": _stable_id("action", evidence_item["id"], title),
                "title": title,
                "kind": "calendar_hold" if hold else "task",
                "due": due,
                "hold": hold,
                "state": "new",
                "evidence_ids": [evidence_item["id"]],
            }
        )
    return actions, evidence


def _active_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        task
        for task in tasks
        if str(task.get("status", "needsAction")).lower() not in {"completed", "done"}
    ]


def _reconcile(
    actions: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    calendar_events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    proposed: list[dict[str, Any]] = []
    reconciliation: list[dict[str, Any]] = []
    active_tasks = _active_tasks(tasks)

    for action in actions:
        matching_task = next(
            (task for task in active_tasks if _similar(action["title"], str(task.get("title", "")))),
            None,
        )
        if matching_task:
            action["state"] = "already_tracked"
            reconciliation.append(
                {
                    "action_id": action["id"],
                    "state": "already_tracked",
                    "matched": _source_ref(matching_task, "task"),
                    "reason": "similar_active_task",
                }
            )
            continue

        if action["kind"] == "calendar_hold":
            hold = action["hold"] or {}
            matching_event = next(
                (
                    event
                    for event in calendar_events
                    if str(event.get("start", "")).startswith(str(hold.get("start", ""))[:16])
                    or _similar(action["title"], str(event.get("summary", "")))
                ),
                None,
            )
            if matching_event:
                action["state"] = "already_scheduled"
                reconciliation.append(
                    {
                        "action_id": action["id"],
                        "state": "already_scheduled",
                        "matched": _source_ref(matching_event, "calendar"),
                        "reason": "similar_calendar_event",
                    }
                )
                continue
            proposed.append(_proposal("calendar_hold", action))
            reconciliation.append(
                {"action_id": action["id"], "state": "proposal_pending", "reason": "no_matching_event"}
            )
        else:
            proposed.append(_proposal("create_task", action))
            reconciliation.append(
                {"action_id": action["id"], "state": "proposal_pending", "reason": "no_matching_task"}
            )

    return actions, reconciliation, proposed


def _proposal(kind: str, action: dict[str, Any]) -> dict[str, Any]:
    if kind == "calendar_hold":
        payload = {
            "summary": action["title"],
            "start": (action.get("hold") or {}).get("start", ""),
            "end": (action.get("hold") or {}).get("end", ""),
            "description": f"Evidence: {', '.join(action['evidence_ids'])}",
        }
        route = {"method": "POST", "path": "/calendar/events"}
    else:
        payload = {
            "title": action["title"],
            "due": action.get("due", ""),
            "notes": f"Evidence: {', '.join(action['evidence_ids'])}",
        }
        route = {"method": "POST", "path": "/tasks"}

    return {
        "id": _stable_id("proposal", kind, action["id"]),
        "kind": kind,
        "action_id": action["id"],
        "route": route,
        "payload": payload,
        "approval": {
            "required": True,
            "mode": "explicit_review_before_write",
            "server_lease_required": True,
        },
        "execute": False,
        "evidence_ids": action["evidence_ids"],
    }


def _source_statuses(payload: dict[str, Any]) -> list[dict[str, Any]]:
    configured = payload.get("sources")
    if isinstance(configured, list) and configured:
        return [dict(source) for source in configured if isinstance(source, dict)]

    statuses = [
        {
            "id": "gmail",
            "kind": "connector",
            "state": "configured_external_connector",
            "writes": "review_before_write_only",
        },
        {
            "id": "google_calendar",
            "kind": "connector",
            "state": "configured_external_connector",
            "writes": "review_before_write_only",
        },
        {
            "id": "google_tasks",
            "kind": "connector",
            "state": "configured_external_connector",
            "writes": "review_before_write_only",
        },
    ]
    for connector_id, binary in (("gog", "gog"), ("imsg", "imsg"), ("wacli", "wacli")):
        statuses.append(
            {
                "id": connector_id,
                "kind": "future_cli",
                "state": "installed" if shutil.which(binary) else "not_installed",
                "writes": "deferred_until_explicit_approval_adapter",
            }
        )
    return statuses


def build_report(payload: dict[str, Any], *, now: str | None = None) -> dict[str, Any]:
    generated_at = _now(now).astimezone(UTC).isoformat()
    inbox_messages = list(payload.get("inbox") or payload.get("messages") or [])
    tasks = list(payload.get("tasks") or [])
    calendar_events = list(payload.get("calendar") or payload.get("calendar_events") or [])
    actions, inbox_evidence = _extract_actionable(inbox_messages)
    task_evidence = [_evidence_for(task, "task") for task in tasks]
    calendar_evidence = [_evidence_for(event, "calendar") for event in calendar_events]
    actions, reconciliation, proposed = _reconcile(actions, tasks, calendar_events)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "dry_run": True,
        "invariants": {
            "provider_calls": False,
            "connector_binaries_executed": False,
            "external_mutations": False,
            "review_before_write": True,
        },
        "sources": _source_statuses(payload),
        "summary": {
            "inbox_messages": len(inbox_messages),
            "active_tasks": len(_active_tasks(tasks)),
            "calendar_events": len(calendar_events),
            "actionable_items": len(actions),
            "proposed_changes": len(proposed),
        },
        "actionable_items": actions,
        "reconciliation": reconciliation,
        "proposed_changes": proposed,
        "evidence": [*inbox_evidence, *task_evidence, *calendar_evidence],
    }


def load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def format_text(report: dict[str, Any]) -> str:
    lines = [
        "Inbox/Calendar/Todo Control Surface v0",
        f"Dry run: {report['dry_run']} | external mutations: {report['invariants']['external_mutations']}",
        (
            f"Actionable: {report['summary']['actionable_items']} | "
            f"Proposed changes: {report['summary']['proposed_changes']}"
        ),
        "",
        "Sources:",
    ]
    for source in report["sources"]:
        lines.append(f"  {source['id']}: {source['state']}")

    lines.append("")
    lines.append("Actionable items:")
    for item in report["actionable_items"]:
        evidence = ", ".join(item["evidence_ids"])
        lines.append(f"  - [{item['state']}] {item['title']} ({evidence})")

    lines.append("")
    lines.append("Review-before-write proposals:")
    if not report["proposed_changes"]:
        lines.append("  none")
    for proposal in report["proposed_changes"]:
        route = proposal["route"]
        lines.append(
            f"  - {proposal['kind']} via {route['method']} {route['path']} "
            f"approval_required={proposal['approval']['required']} execute={proposal['execute']}"
        )
        lines.append(f"    payload: {json.dumps(proposal['payload'], sort_keys=True)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarize actionable inbox/calendar/todo items and propose reviewable writes."
    )
    parser.add_argument("--fixture", type=Path, help="Local JSON fixture to summarize.")
    parser.add_argument("--now", default=None, help="Stable ISO timestamp for generated_at.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Reserved for a future human-approved adapter; v0 refuses execution.",
    )
    args = parser.parse_args(argv)

    if args.execute:
        print(
            "Refusing --execute: v0 only emits dry-run proposals requiring explicit review.",
            file=sys.stderr,
        )
        return 2

    payload = load_fixture(args.fixture) if args.fixture else {}
    report = build_report(payload, now=args.now)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
