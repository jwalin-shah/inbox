#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

HOME = Path.home()
DEFAULT_BASE_URL = "http://127.0.0.1:9849"
RAYCAST_ENV = HOME / ".config" / "raycast" / "inbox-workflows.env"
DEFAULT_OUT_DIR = HOME / "Documents" / "inbox-briefs"
EVENING_PLAN_CUTOFF_HOUR = 18

ROUTINE_EVENT_TITLES = {
    "daily meditation",
    "take medicine",
    "midday reset",
    "daily exercise",
    "evening reset",
}

LOCK_WORDS = {
    "cerebras",
    "consulting",
    "cvs",
    "echeck",
    "echeck-in",
    "golden gate",
    "gitguardian",
    "insurance",
    "mychart",
    "psychiatry",
    "quest",
    "secret leak",
    "settlement",
    "stanford",
    "tensor",
    "venmo",
    "video visit",
}

ACTION_GROUPS = {
    "stanford_visit": ("stanford", "video visit"),
    "cvs_insurance": ("cvs", "insurance"),
    "stanford_insurance": ("stanford", "insurance"),
    "quest_blood": ("quest", "blood"),
    "golden_gate_sleep": ("golden gate", "sleep"),
    "tensor": ("tensor",),
    "cerebras": ("cerebras",),
}

ACTION_GROUP_LABELS = {
    "stanford_visit": "Stanford visit",
    "cvs_insurance": "CVS / insurance",
    "stanford_insurance": "Stanford insurance",
    "quest_blood": "Quest blood work",
    "golden_gate_sleep": "Golden Gate Sleep",
    "tensor": "Tensor",
    "cerebras": "Cerebras",
}

AUTOMATION_NOISE_TERMS = {
    "chatgpt-codex-connector",
    "coderabbitai",
    "deepsource",
    "github",
    "google-labs-jules",
    "linear",
    "notifications@github.com",
    "pr run failed",
    "run failed:",
}


class ReviewError(RuntimeError):
    pass


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def workflow_env() -> tuple[str, str]:
    file_values = parse_env_file(RAYCAST_ENV)
    base_url = (
        os.environ.get("INBOX_SERVER_URL")
        or file_values.get("INBOX_SERVER_URL")
        or DEFAULT_BASE_URL
    ).rstrip("/")
    token = os.environ.get("INBOX_SERVER_TOKEN") or file_values.get("INBOX_SERVER_TOKEN") or ""
    return base_url, token


def request_json(
    base_url: str,
    path: str,
    token: str | None = None,
    params: dict[str, Any] | None = None,
    *,
    method: str = "GET",
    timeout: float = 60,
) -> Any:
    url = f"{base_url}{path}"
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        url = f"{url}?{urllib.parse.urlencode(clean)}"
    req = urllib.request.Request(url, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:  # nosec B310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[-500:]
        raise ReviewError(f"{method} {path} failed with HTTP {exc.code}: {detail}") from exc
    except TimeoutError as exc:
        raise ReviewError(f"{method} {path} timed out after {timeout:g}s") from exc
    except urllib.error.URLError as exc:
        raise ReviewError(f"Cannot reach Inbox server at {base_url}: {exc.reason}") from exc


def optional_json(
    base_url: str,
    path: str,
    token: str | None = None,
    params: dict[str, Any] | None = None,
    *,
    method: str = "GET",
    timeout: float = 60,
    default: Any = None,
) -> Any:
    try:
        return request_json(base_url, path, token, params, method=method, timeout=timeout)
    except ReviewError:
        return default


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def compact(value: Any, limit: int = 110) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def parse_dt(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo:
        return parsed.astimezone().replace(tzinfo=None)
    return parsed


def due_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    if len(value) >= 10:
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            pass
    parsed = parse_dt(value)
    return parsed.date() if parsed else None


def due_label(value: str | None, today: dt.date) -> str:
    due = due_date(value)
    if not due:
        return "no due date"
    if due < today:
        return f"overdue {due.isoformat()}"
    if due == today:
        return "due today"
    return f"due {due.isoformat()}"


def event_time(event: dict[str, Any]) -> str:
    start = parse_dt(event.get("start"))
    end = parse_dt(event.get("end"))
    if event.get("all_day"):
        return "all day"
    if start and end:
        return f"{start:%-I:%M %p}-{end:%-I:%M %p}"
    if start:
        return f"{start:%-I:%M %p}"
    return "time unknown"


def operating_date(now: dt.datetime) -> tuple[dt.date, str]:
    if now.hour >= EVENING_PLAN_CUTOFF_HOUR:
        return now.date() + dt.timedelta(days=1), "Tomorrow"
    return now.date(), "Today"


def action_text(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(key) or "")
        for key in ("title", "notes", "snippet", "name", "workflow", "summary")
    ).lower()


def is_automation_noise(item: dict[str, Any]) -> bool:
    text = action_text(item)
    return any(term in text for term in AUTOMATION_NOISE_TERMS)


def action_group(item: dict[str, Any]) -> str:
    text = action_text(item)
    for key, needles in ACTION_GROUPS.items():
        if all(needle in text for needle in needles):
            return key
    return compact(item.get("title") or item.get("snippet") or item.get("name") or "item", 70)


def action_score(item: dict[str, Any], today: dt.date, due_key: str = "") -> int:
    text = action_text(item)
    score = 0
    due = due_date(item.get(due_key)) if due_key else None
    if due:
        if due == today:
            score += 70
        elif due < today:
            score += 35
    if item.get("flagged"):
        score += 15
    if str(item.get("workflow") or "").lower() in {"medical", "legal", "job_hunt"}:
        score += 20
    score += sum(12 for word in LOCK_WORDS if word in text)
    if int(item.get("unread") or 0):
        score += 8
    return score


def item_html(title: str, meta: str = "", desc: str = "", badge: str = "") -> str:
    badge_html = f'<span class="badge">{esc(badge)}</span>' if badge else ""
    return (
        '<li class="item">'
        f"<div><strong>{esc(title)}</strong>{badge_html}<p>{esc(desc)}</p></div>"
        f"<span>{esc(meta)}</span>"
        "</li>"
    )


def section(title: str, body: str, klass: str = "") -> str:
    return f'<section class="section {klass}"><h2>{esc(title)}</h2>{body}</section>'


def collect_review_data(
    base_url: str,
    token: str,
    now: dt.datetime,
    target_date: dt.date,
    refresh_index: bool,
) -> dict[str, Any]:
    health = request_json(base_url, "/health", timeout=15)
    index_health_before = optional_json(base_url, "/index/health", token, timeout=15, default={})
    sync_result = None
    if refresh_index and index_health_before and not index_health_before.get("healthy", False):
        sync_result = optional_json(
            base_url,
            "/index/sync/incremental",
            token,
            method="POST",
            timeout=90,
            default=None,
        )
    index_health = optional_json(base_url, "/index/health", token, timeout=15, default={})
    return {
        "health": health,
        "auth": request_json(
            base_url, "/accounts/auth-status", token, {"check_refresh": "true"}, timeout=30
        ),
        "index_health": index_health or index_health_before,
        "sync_result": sync_result,
        "calendar": request_json(
            base_url, "/calendar/events", token, {"date": target_date.isoformat()}, timeout=120
        ),
        "gmail": request_json(
            base_url, "/conversations", token, {"source": "gmail", "limit": 60}, timeout=90
        ),
        "imessage": request_json(
            base_url, "/conversations", token, {"source": "imessage", "limit": 30}, timeout=60
        ),
        "reminders": request_json(
            base_url,
            "/reminders",
            token,
            {"show_completed": "false", "limit": "100"},
            timeout=60,
        ),
        "tasks": optional_json(base_url, "/tasks", token, timeout=60, default=[]),
        "filters": optional_json(base_url, "/gmail/filters/audit", token, timeout=60, default={}),
        "archived": optional_json(
            base_url,
            "/gmail/search",
            token,
            {"q": "newer_than:1d -in:inbox -in:trash -in:spam", "limit": 20},
            timeout=60,
            default=[],
        ),
        "github": optional_json(
            base_url, "/github/notifications", token, {"all": "false"}, timeout=60, default=[]
        ),
        "generated_at": now,
        "target_date": target_date,
    }


def build_lock_items(data: dict[str, Any], today: dt.date) -> list[tuple[str, str, str, str, str]]:
    candidates: list[tuple[int, str, str, str, str, str, str]] = []
    for reminder in data["reminders"]:
        score = action_score(reminder, today, "due_date")
        if score:
            candidates.append(
                (
                    score,
                    action_group(reminder),
                    "Reminder",
                    reminder.get("title", ""),
                    due_label(reminder.get("due_date"), today),
                    reminder.get("notes", ""),
                    reminder.get("list_name", ""),
                )
            )
    for task in data["tasks"]:
        score = action_score(task, today, "due")
        if score:
            candidates.append(
                (
                    score,
                    action_group(task),
                    "Task",
                    task.get("title", ""),
                    due_label(task.get("due"), today),
                    task.get("notes", ""),
                    task.get("workflow") or task.get("list_title", ""),
                )
            )
    for conv in data["gmail"]:
        score = action_score(conv, today)
        if score >= 20 and not is_automation_noise(conv):
            candidates.append(
                (
                    score,
                    action_group(conv),
                    "Email",
                    f"{conv.get('name', '')} - {conv.get('snippet', '')}",
                    "recent inbox",
                    conv.get("reply_to", ""),
                    conv.get("gmail_account", ""),
                )
            )
    seen: set[str] = set()
    lock_items: list[tuple[str, str, str, str, str]] = []
    for _, group, kind, title, meta, desc, badge in sorted(
        candidates, key=lambda item: (-item[0], item[1])
    ):
        if group in seen:
            continue
        seen.add(group)
        group_label = ACTION_GROUP_LABELS.get(group, group)
        lock_items.append((kind, title, meta, desc, badge or group_label))
        if len(lock_items) >= 7:
            break
    return lock_items


def build_html(data: dict[str, Any], base_url: str, now: dt.datetime, target_label: str) -> str:
    today = now.date()
    target_date = data["target_date"]
    calendar = data["calendar"]
    commitments = [
        event
        for event in calendar
        if str(event.get("summary", "")).strip().lower() not in ROUTINE_EVENT_TITLES
    ]
    routine = [
        event
        for event in calendar
        if str(event.get("summary", "")).strip().lower() in ROUTINE_EVENT_TITLES
    ]
    lock_items = build_lock_items(data, today)
    gmail_accounts = Counter(item.get("gmail_account") for item in data["gmail"])
    unread_gmail = sum(int(item.get("unread") or 0) for item in data["gmail"])
    unread_imessage = sum(int(item.get("unread") or 0) for item in data["imessage"])
    overdue_reminders = [
        item
        for item in data["reminders"]
        if (due_date(item.get("due_date")) or dt.date.max) < today
    ]
    overdue_tasks = [
        item for item in data["tasks"] if (due_date(item.get("due")) or dt.date.max) < today
    ]
    archived_candidates = [
        item
        for item in data["archived"]
        if action_score(item, today) >= 20 and not is_automation_noise(item)
    ]
    filter_data = data.get("filters") or {}
    auth_counts = data.get("auth", {}).get("counts", {})
    index_health = data.get("index_health") or {}

    dupe_sources: dict[str, set[str]] = {}
    for reminder in data["reminders"]:
        dupe_sources.setdefault(action_group(reminder), set()).add("Reminder")
    for task in data["tasks"]:
        dupe_sources.setdefault(action_group(task), set()).add("Task")
    duplicates = [key for key, sources in dupe_sources.items() if len(sources) > 1]

    metrics = [
        (
            "Connected accounts",
            len(data["health"].get("gmail_accounts", [])),
            "Gmail, Calendar, Drive, Sheets available",
        ),
        (
            "Auth health",
            "OK" if auth_counts.get("refresh_failed", 0) == 0 else "Check",
            f"{auth_counts.get('tokens_present', 0)} token(s), {auth_counts.get('missing_scopes', 0)} missing scope(s)",
        ),
        (
            "Index",
            "Fresh" if index_health.get("healthy") else "Stale",
            f"newest sync {int(index_health.get('newest_success_age_seconds') or 0) // 60}m ago",
        ),
        (
            "Gmail unread",
            unread_gmail,
            f"sampled across {len(gmail_accounts)} account(s)",
        ),
        ("iMessage unread", unread_imessage, "sampled unread threads"),
        (
            "Backlog",
            len(data["reminders"]) + len(data["tasks"]),
            f"{len(overdue_reminders)} overdue reminder(s), {len(overdue_tasks)} overdue task(s)",
        ),
        (
            "Trash filters",
            filter_data.get("trash_filters_count", 0),
            "old filters that bypass archive review",
        ),
        (
            "Archived watch",
            len(archived_candidates),
            f"important-looking from {len(data['archived'])} recent archived",
        ),
    ]
    metric_html = (
        '<div class="metrics">'
        + "".join(
            f'<div class="metric"><span>{esc(label)}</span><strong>{esc(value)}</strong><p>{esc(note)}</p></div>'
            for label, value, note in metrics
        )
        + "</div>"
    )

    current_packet = [
        (
            "1",
            "Finish Stanford prep",
            "Read the video visit instructions, complete eCheck-in, and have the visit link ready.",
        ),
        (
            "2",
            "Write three questions",
            "Golden Gate Sleep follow-up, Stanford video visit, and what to do next for Quest/CVS.",
        ),
        (
            "3",
            "After the appointment",
            "Update the medical tasks: CVS, Stanford Insurance, Alameda Alliance, Quest blood work.",
        ),
    ]
    packet_html = (
        '<ol class="packet">'
        + "".join(
            f"<li><span>{esc(num)}</span><div><strong>{esc(title)}</strong><p>{esc(desc)}</p></div></li>"
            for num, title, desc in current_packet
        )
        + "</ol>"
    )

    lock_html = (
        '<ul class="items">'
        + "".join(
            item_html(title, meta, desc, f"{kind} · {badge}" if badge else kind)
            for kind, title, meta, desc, badge in lock_items
        )
        + "</ul>"
    )

    commitments_html = (
        '<ol class="timeline">'
        + "".join(
            (
                f"<li><time>{esc(event_time(event))}</time><div>"
                f"<strong>{esc(event.get('summary'))}</strong>"
                f"<p>{esc(compact(event.get('location') or event.get('account'), 120))}</p>"
                "</div></li>"
            )
            for event in commitments
        )
        + "</ol>"
        if commitments
        else '<p class="empty">No hard commitments found.</p>'
    )

    routine_html = (
        '<ul class="compact-list">'
        + "".join(
            f"<li><span>{esc(event_time(event))}</span>{esc(event.get('summary'))}</li>"
            for event in routine
        )
        + "</ul>"
        if routine
        else '<p class="empty">No routine blocks found.</p>'
    )

    reminders_html = "".join(
        item_html(
            reminder.get("title", ""),
            due_label(reminder.get("due_date"), today),
            reminder.get("notes", ""),
            reminder.get("list_name", ""),
        )
        for reminder in sorted(
            data["reminders"],
            key=lambda item: (due_date(item.get("due_date")) or dt.date.max, item.get("title", "")),
        )[:10]
    )
    tasks_html = "".join(
        item_html(
            task.get("title", ""),
            due_label(task.get("due"), today),
            task.get("notes", ""),
            task.get("workflow") or task.get("list_title", ""),
        )
        for task in sorted(
            data["tasks"],
            key=lambda item: (due_date(item.get("due")) or dt.date.max, item.get("title", "")),
        )[:10]
    )
    backlog_html = (
        '<div class="split"><div><h3>Reminders</h3><ul class="items">'
        + reminders_html
        + '</ul></div><div><h3>Tasks</h3><ul class="items">'
        + tasks_html
        + "</ul></div></div>"
    )

    mail_html = (
        '<ul class="items">'
        + "".join(
            item_html(
                f"{item.get('name', '')} - {compact(item.get('snippet'), 90)}",
                item.get("gmail_account", ""),
                item.get("reply_to", ""),
                "Unread" if int(item.get("unread") or 0) else "Recent",
            )
            for item in data["gmail"][:12]
        )
        + "</ul>"
    )

    imessage_html = (
        '<ul class="items">'
        + "".join(
            item_html(
                item.get("name") or item.get("id"),
                "unread" if int(item.get("unread") or 0) else "recent",
                compact(item.get("snippet"), 110),
                "iMessage",
            )
            for item in data["imessage"][:8]
        )
        + "</ul>"
    )

    routing_rows: list[str] = []
    for account in filter_data.get("accounts", []):
        for filt in account.get("trash_filters", [])[:3]:
            routing_rows.append(
                item_html(
                    str(filt.get("criteria")),
                    account.get("account", ""),
                    "Existing Gmail filter sends this to Trash.",
                    "Trash",
                )
            )
            if len(routing_rows) >= 6:
                break
        if len(routing_rows) >= 6:
            break
    routing_html = '<ul class="items">' + "".join(routing_rows) + "</ul>"

    audit_html = '<ul class="items">'
    audit_html += item_html(
        "Daily archived-mail scan",
        f"{len(archived_candidates)} candidate(s)",
        "Recent archived mail is checked for important-looking items. Automation noise is ignored.",
        "Read-only",
    )
    audit_html += item_html(
        "Task/reminder duplicate cleanup",
        f"{len(duplicates)} possible group(s)",
        ", ".join(ACTION_GROUP_LABELS.get(item, item) for item in duplicates[:6])
        or "No obvious duplicates.",
        "Cleanup",
    )
    audit_html += item_html(
        "Gmail Trash filter decision",
        f"{filter_data.get('trash_filters_count', 0)} filter(s)",
        "Safer default is Triage label + archive, but this should be approved before changing live Gmail settings.",
        "Decision",
    )
    audit_html += item_html(
        "Calendar UI policy",
        "not changed",
        "Inbox de-dupes shared calendars locally. Google Calendar visibility has not been changed.",
        "Decision",
    )
    audit_html += "</ul>"

    changed_html = (
        '<ul class="items">'
        + "".join(
            item_html(title, "", desc, badge)
            for title, badge, desc in [
                (
                    "Auth diagnostics",
                    "Done",
                    "Three Google accounts are visible and refreshable; auth failures now have a concrete endpoint.",
                ),
                (
                    "Calendar de-duplication",
                    "Done",
                    "Inbox collapses duplicate shared-calendar events and skips unselected calendars locally.",
                ),
                (
                    "Operating brief",
                    "Done",
                    "Tomorrow-aware after 6 PM with freshness, Lock In, Backlog Health, Archived Watch, and Routing Watch.",
                ),
                (
                    "Filter audit",
                    "Done",
                    "Read-only audit shows archive, triage, and Trash filters across accounts.",
                ),
                (
                    "Durable HTML review",
                    "New",
                    "This page now comes from scripts/inbox_operating_review.py instead of a one-off command.",
                ),
            ]
        )
        + "</ul>"
    )

    next_html = (
        '<ol class="next">'
        + "".join(
            f"<li>{esc(item)}</li>"
            for item in [
                "Finish the Stanford prep packet now.",
                "After Stanford, clean the medical backlog: CVS, Stanford Insurance, Alameda Alliance, Quest.",
                "Approve or reject converting old Trash filters to safer Triage/Noise + archive rules.",
                "Run one task/reminder reconciliation pass and remove duplicates instead of letting overdue become background noise.",
                "Keep adding future Gmail filters only after Archived Watch remains clean.",
            ]
        )
        + "</ol>"
    )

    css = """
:root { color-scheme: light; --ink:#17211b; --muted:#5d6a62; --line:#d9e0da; --paper:#f6f8f5; --panel:#fff; --accent:#17624f; --accent-soft:#e7f1ed; --amber:#9b5f00; --red:#a33a32; --blue:#315f9e; }
* { box-sizing: border-box; }
body { margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--paper); color: var(--ink); letter-spacing: 0; }
header { padding: 34px 44px 22px; border-bottom: 1px solid var(--line); background: #fff; }
header h1 { margin: 0 0 8px; font-size: 34px; line-height: 1.08; font-weight: 760; }
header p { margin: 0; color: var(--muted); font-size: 14px; }
main { max-width: 1320px; margin: 0 auto; padding: 24px; }
.metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 24px; }
.metric { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; min-height: 112px; }
.metric span { display: block; color: var(--muted); font-size: 12px; text-transform: uppercase; font-weight: 740; }
.metric strong { display: block; margin-top: 8px; font-size: 27px; line-height: 1.1; }
.metric p { margin: 8px 0 0; color: var(--muted); font-size: 13px; }
.grid { display: grid; grid-template-columns: minmax(0, 1.18fr) minmax(360px, .82fr); gap: 18px; align-items: start; }
.section { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 18px; margin-bottom: 18px; }
.section h2 { margin: 0 0 14px; font-size: 18px; }
.section h3 { margin: 0 0 10px; font-size: 12px; color: var(--muted); text-transform: uppercase; }
.now { border-color: #b8d8cc; background: linear-gradient(180deg, #fff, #f4fbf8); }
.items, .compact-list, .timeline, .next, .packet { list-style: none; margin: 0; padding: 0; }
.item { display: flex; justify-content: space-between; gap: 18px; padding: 12px 0; border-top: 1px solid #edf1ed; }
.item:first-child { border-top: 0; padding-top: 0; }
.item strong { font-size: 14px; }
.item p { margin: 5px 0 0; color: var(--muted); font-size: 13px; line-height: 1.35; }
.item > span { flex: 0 0 auto; color: var(--muted); font-size: 12px; max-width: 180px; text-align: right; }
.badge { display: inline-block; margin-left: 8px; padding: 2px 7px; border: 1px solid var(--line); border-radius: 999px; color: var(--accent); font-size: 11px; font-weight: 740; vertical-align: 1px; }
.packet li { display: grid; grid-template-columns: 30px 1fr; gap: 12px; padding: 12px 0; border-top: 1px solid #dce9e3; }
.packet li:first-child { border-top: 0; padding-top: 0; }
.packet span { width: 28px; height: 28px; border-radius: 999px; background: var(--accent); color: #fff; display: grid; place-items: center; font-size: 13px; font-weight: 800; }
.packet strong { font-size: 15px; }
.packet p { margin: 4px 0 0; color: var(--muted); font-size: 13px; }
.timeline li { display: grid; grid-template-columns: 124px 1fr; gap: 14px; padding: 12px 0; border-top: 1px solid #edf1ed; }
.timeline li:first-child { border-top: 0; padding-top: 0; }
time { font-size: 13px; color: var(--blue); font-weight: 740; }
.timeline strong { font-size: 14px; }
.timeline p { margin: 5px 0 0; color: var(--muted); font-size: 13px; }
.compact-list li { display: flex; justify-content: space-between; border-top: 1px solid #edf1ed; padding: 9px 0; font-size: 14px; }
.compact-list li:first-child { border-top: 0; padding-top: 0; }
.compact-list span { color: var(--muted); font-size: 13px; }
.split { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.next { counter-reset: step; }
.next li { counter-increment: step; position: relative; padding: 12px 0 12px 36px; border-top: 1px solid #edf1ed; font-size: 14px; line-height: 1.4; }
.next li:first-child { border-top: 0; }
.next li::before { content: counter(step); position: absolute; left: 0; top: 10px; width: 22px; height: 22px; border-radius: 999px; background: var(--accent); color: #fff; display: grid; place-items: center; font-size: 12px; font-weight: 800; }
.empty { color: var(--muted); margin: 0; }
.warn h2 { color: var(--amber); }
.risk h2 { color: var(--red); }
@media (max-width: 960px) { header { padding: 24px 20px; } main { padding: 14px; } .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } .grid, .split { grid-template-columns: 1fr; } .timeline li { grid-template-columns: 1fr; gap: 4px; } .item { display: block; } .item > span { display: block; text-align: left; margin-top: 6px; } }
@media (max-width: 560px) { .metrics { grid-template-columns: 1fr; } header h1 { font-size: 28px; } }
"""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Inbox Operating Review</title>
<style>{css}</style>
</head>
<body>
<header>
  <h1>Inbox Operating Review</h1>
  <p>Generated {esc(now.strftime("%A, %B %-d, %Y at %-I:%M %p"))} · Operating date {esc(target_label)}, {esc(target_date.strftime("%A, %B %-d, %Y"))} · Source {esc(base_url)}</p>
</header>
<main>
  {metric_html}
  <div class="grid">
    <div>
      {section("Current Packet", packet_html, "now")}
      {section("What To Do Next", next_html)}
      {section("Lock In", lock_html)}
      {section("Commitments", commitments_html)}
      {section("Backlog", backlog_html)}
      {section("Recent Gmail", mail_html)}
    </div>
    <div>
      {section("What We Have Now", changed_html)}
      {section("Routine", routine_html)}
      {section("Routing Risks", routing_html, "risk")}
      {section("Daily Audit", audit_html, "warn")}
      {section("iMessage Sample", imessage_html)}
    </div>
  </div>
</main>
</body>
</html>
"""


def write_review(html_doc: str, out_dir: Path, now: dt.datetime) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{now:%Y%m%d-%H%M%S}-inbox-operating-review.html"
    path.write_text(html_doc, encoding="utf-8")
    return path


def open_file(path: Path) -> None:
    subprocess.run(["open", str(path)], check=False)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a read-only Inbox operating review HTML."
    )
    parser.add_argument("--base-url", default="")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--open", action="store_true", help="Open the generated HTML file.")
    parser.add_argument(
        "--no-refresh-index",
        action="store_true",
        help="Do not trigger local incremental index sync when the index is stale.",
    )
    args = parser.parse_args()

    env_base_url, token = workflow_env()
    base_url = (args.base_url or env_base_url).rstrip("/")
    now = dt.datetime.now()
    target_date, target_label = operating_date(now)
    data = collect_review_data(
        base_url,
        token,
        now,
        target_date,
        refresh_index=not args.no_refresh_index,
    )
    html_doc = build_html(data, base_url, now, target_label)
    path = write_review(html_doc, args.out_dir, now)
    print(path)
    if args.open:
        open_file(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
