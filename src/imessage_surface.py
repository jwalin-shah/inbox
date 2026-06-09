#!/usr/bin/env python3
"""Surface iMessage contacts needing replies and inactive threads (14+ days).

Read-only by default. Sending requires ``--confirm``.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contacts import ContactBook  # noqa: E402
from service_models import ATTACHMENT_PLACEHOLDER, Contact  # noqa: E402
from services import IMSG_DB, imsg_send, imsg_thread, init_contacts  # noqa: E402

SCHEMA = "inbox.imessage_contact_surface.v0"
DEFAULT_STALE_DAYS = 14
DEFAULT_RECENT_DAYS = 7
DEFAULT_SCAN_LIMIT = 500

TAPBACK_RE = re.compile(
    r"^(Liked|Loved|Emphasized|Disliked|Laughed at|Questioned)\b",
    re.IGNORECASE,
)
SHORT_CODE_RE = re.compile(r"^\d{4,6}$")
PHONE_RE = re.compile(r"^\+?\d[\d\s().-]{6,}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CODE_RE = re.compile(r"^\d{4,8}$")
AUTOMATED_SENDER_RE = re.compile(
    r"(verification|security code|one[- ]time|do not reply|no[- ]reply|"
    r"automated message|unsubscribe)",
    re.IGNORECASE,
)
AUTOMATED_NAMES = frozenset(
    {
        "google",
        "apple",
        "amazon",
        "venmo",
        "paypal",
        "chase",
        "wells fargo",
        "bank of america",
        "cvs",
        "walgreens",
        "doordash",
        "uber",
        "lyft",
    }
)

CHAT_SUMMARY_SQL = """
WITH eligible AS (
    SELECT
        cmj.chat_id,
        m.rowid,
        m.text,
        m.date,
        m.is_from_me,
        m.is_read
    FROM chat_message_join cmj
    JOIN message m ON cmj.message_id = m.rowid
    WHERE m.item_type = 0
      AND m.is_system_message = 0
      AND m.associated_message_type = 0
      AND COALESCE(m.is_spam, 0) = 0
),
ranked AS (
    SELECT
        eligible.*,
        ROW_NUMBER() OVER (
            PARTITION BY chat_id
            ORDER BY date DESC, rowid DESC
        ) AS rank
    FROM eligible
),
stats AS (
    SELECT
        chat_id,
        COUNT(*) AS interaction_count,
        SUM(CASE WHEN is_from_me = 1 THEN 1 ELSE 0 END) AS sent_count,
        SUM(CASE WHEN is_from_me = 0 THEN 1 ELSE 0 END) AS received_count,
        COUNT(DISTINCT date(date / 1000000000 + 978307200, 'unixepoch')) AS active_days,
        SUM(CASE WHEN is_read = 0 AND is_from_me = 0 THEN 1 ELSE 0 END) AS unread
    FROM eligible
    GROUP BY chat_id
)
SELECT
    c.rowid,
    c.guid,
    c.display_name,
    latest.text,
    latest.date / 1000000000 + 978307200 AS ts,
    stats.unread,
    latest.is_from_me,
    stats.interaction_count,
    stats.sent_count,
    stats.received_count,
    stats.active_days
FROM chat c
JOIN ranked latest ON c.rowid = latest.chat_id AND latest.rank = 1
JOIN stats ON c.rowid = stats.chat_id
ORDER BY latest.date DESC
LIMIT ?
"""


def _clean_body(text: str | None) -> str:
    if not text:
        return ""
    return text.replace(ATTACHMENT_PLACEHOLDER, "(attachment)").strip()


def _age_label(delta: timedelta) -> str:
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return f"{int(hours * 60)}m"
    if hours < 48:
        return f"{int(hours)}h" if hours < 24 else f"{int(hours // 24)}d"
    days = int(hours // 24)
    return f"{days}d"


def _markdown_cell(value: str) -> str:
    return value.replace("|", r"\|").replace("\r", " ").replace("\n", " ")


def _is_phone_like(value: str) -> bool:
    value = value.strip()
    if not value:
        return False
    if PHONE_RE.match(value):
        return True
    digits = re.sub(r"\D", "", value)
    return len(digits) >= 7 and digits == re.sub(r"\D", "", value)


def _name_resolved(name: str, display_name: str, members: list[str]) -> bool:
    if display_name and display_name.strip():
        return True
    if _is_phone_like(name):
        return False
    if EMAIL_RE.match(name):
        return False
    if name.lower() in AUTOMATED_NAMES:
        return False
    if members and all(_is_phone_like(m) or EMAIL_RE.match(m) for m in members):
        return False
    return bool(name.strip())


def _is_noise(body: str, name: str) -> bool:
    cleaned = _clean_body(body)
    lowered_name = name.lower()
    return (
        not cleaned
        or cleaned == "(attachment)"
        or bool(TAPBACK_RE.match(cleaned))
        or bool(CODE_RE.match(cleaned))
        or bool(AUTOMATED_SENDER_RE.search(cleaned))
        or lowered_name in AUTOMATED_NAMES
        or bool(SHORT_CODE_RE.match(name.strip()))
    )


def _urgency(*, unread: int, age_hours: float, name_resolved: bool) -> int:
    score = 0
    if unread:
        score += 3
    if age_hours <= 24:
        score += 2
    elif age_hours <= 72:
        score += 1
    if name_resolved:
        score += 1
    return min(5, max(1, score))


@dataclass
class ThreadSurface:
    chat_id: str
    name: str
    display_name: str
    members: list[str]
    is_group: bool
    unread: int
    last_ts: datetime
    age_hours: float
    age_label: str
    snippet: str
    interaction_count: int
    sent_count: int
    received_count: int
    active_days: int
    name_resolved: bool
    needs_reply: bool
    urgency: int
    evidence_thread: str
    last_sender: str = "them"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["last_ts"] = self.last_ts.replace(tzinfo=None).isoformat(timespec="seconds")
        return payload


@dataclass
class SurfaceReport:
    schema: str = SCHEMA
    generated_at: str = ""
    stale_threshold_days: int = DEFAULT_STALE_DAYS
    recent_threshold_days: int = DEFAULT_RECENT_DAYS
    summary: dict[str, int | str] = field(default_factory=dict)
    recent_actionable_needs_reply: list[ThreadSurface] = field(default_factory=list)
    stale_needs_reply: list[ThreadSurface] = field(default_factory=list)
    inactive_contacts: list[ThreadSurface] = field(default_factory=list)
    phone_ambiguous_needs_reply: list[ThreadSurface] = field(default_factory=list)
    waiting_on_others: list[ThreadSurface] = field(default_factory=list)
    excluded_noise: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "generated_at": self.generated_at,
            "stale_threshold_days": self.stale_threshold_days,
            "recent_threshold_days": self.recent_threshold_days,
            "summary": self.summary,
            "recent_actionable_needs_reply": [row.to_dict() for row in self.recent_actionable_needs_reply],
            "stale_needs_reply": [row.to_dict() for row in self.stale_needs_reply],
            "inactive_contacts": [row.to_dict() for row in self.inactive_contacts],
            "phone_ambiguous_needs_reply": [row.to_dict() for row in self.phone_ambiguous_needs_reply],
            "waiting_on_others": [row.to_dict() for row in self.waiting_on_others],
            "excluded_noise": self.excluded_noise,
        }


def _chat_display_name(
    *,
    display_name: str | None,
    guid: str,
    member_ids: list[str],
    member_names: list[str],
    book: ContactBook,
) -> str:
    if display_name and display_name.strip():
        return display_name.strip()
    is_group = len(member_ids) > 1
    if is_group:
        shown = member_names[:3]
        name = ", ".join(shown)
        if len(member_names) > 3:
            name += f" +{len(member_names) - 3}"
        return name
    if member_names:
        return member_names[0]
    return book.resolve(guid.split(";")[-1]) or guid.split(";")[-1]


def _load_chat_rows(limit: int) -> list[tuple[Any, ...]]:
    if not IMSG_DB.exists():
        return []
    conn = sqlite3.connect(f"file:{IMSG_DB}?mode=ro", uri=True)
    try:
        return conn.execute(CHAT_SUMMARY_SQL, (limit,)).fetchall()
    finally:
        conn.close()


def scan_imessage_contacts(
    *,
    now: datetime | None = None,
    limit: int = DEFAULT_SCAN_LIMIT,
    stale_days: int = DEFAULT_STALE_DAYS,
    recent_days: int = DEFAULT_RECENT_DAYS,
    book: ContactBook | None = None,
) -> SurfaceReport:
    """Scan local iMessage threads and classify reply / inactivity signals."""
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)

    contact_book = book or ContactBook()
    contact_book.load()

    rows = _load_chat_rows(limit)
    conn = sqlite3.connect(f"file:{IMSG_DB}?mode=ro", uri=True) if IMSG_DB.exists() else None

    report = SurfaceReport(
        generated_at=reference.astimezone().isoformat(timespec="seconds"),
        stale_threshold_days=stale_days,
        recent_threshold_days=recent_days,
    )

    try:
        for (
            chat_id,
            guid,
            display_name,
            text,
            ts,
            unread,
            is_from_me,
            interaction_count,
            sent_count,
            received_count,
            active_days,
        ) in rows:
            member_ids: list[str] = []
            if conn is not None:
                member_ids = [
                    row[0]
                    for row in conn.execute(
                        """
                        SELECT h.id
                        FROM handle h
                        JOIN chat_handle_join chj ON h.rowid = chj.handle_id
                        WHERE chj.chat_id = ?
                        """,
                        (chat_id,),
                    ).fetchall()
                ]
            member_names = [contact_book.resolve(member_id) or member_id for member_id in member_ids]
            is_group = len(member_ids) > 1
            name = _chat_display_name(
                display_name=display_name,
                guid=guid,
                member_ids=member_ids,
                member_names=member_names,
                book=contact_book,
            )
            body = _clean_body(text)
            snippet = body[:60]
            last_ts = datetime.fromtimestamp(ts, tz=UTC) if ts else reference
            age = reference - last_ts.astimezone(UTC)
            age_hours = age.total_seconds() / 3600
            resolved = _name_resolved(name, display_name or "", member_names)

            if _is_noise(body, name):
                report.excluded_noise += 1
                continue

            needs_reply = not bool(is_from_me)
            row = ThreadSurface(
                chat_id=str(chat_id),
                name=name,
                display_name=(display_name or "").strip(),
                members=member_names,
                is_group=is_group,
                unread=int(unread or 0),
                last_ts=last_ts,
                age_hours=round(age_hours, 1),
                age_label=_age_label(age),
                snippet=snippet,
                interaction_count=int(interaction_count or 0),
                sent_count=int(sent_count or 0),
                received_count=int(received_count or 0),
                active_days=int(active_days or 0),
                name_resolved=resolved,
                needs_reply=needs_reply,
                urgency=_urgency(unread=int(unread or 0), age_hours=age_hours, name_resolved=resolved),
                evidence_thread=f"GET /messages/imessage/{chat_id}",
                last_sender="Me" if is_from_me else "them",
            )

            if age_hours >= stale_days * 24:
                report.inactive_contacts.append(row)

            if not needs_reply:
                report.waiting_on_others.append(row)
                continue

            if age_hours <= recent_days * 24:
                report.recent_actionable_needs_reply.append(row)

            if resolved:
                if age_hours >= stale_days * 24:
                    report.stale_needs_reply.append(row)
            elif age_hours >= stale_days * 24:
                report.phone_ambiguous_needs_reply.append(row)
    finally:
        if conn is not None:
            conn.close()

    for bucket in (
        report.recent_actionable_needs_reply,
        report.stale_needs_reply,
        report.phone_ambiguous_needs_reply,
        report.inactive_contacts,
        report.waiting_on_others,
    ):
        bucket.sort(key=lambda item: (-item.urgency, -item.unread, -item.last_ts.timestamp()))

    report.summary = {
        "contacts_scanned": len(rows),
        "recent_actionable_needs_reply": len(report.recent_actionable_needs_reply),
        "stale_needs_reply": len(report.stale_needs_reply),
        "phone_ambiguous_needs_reply": len(report.phone_ambiguous_needs_reply),
        "inactive_contacts": len(report.inactive_contacts),
        "waiting_on_others": len(report.waiting_on_others),
        "excluded_noise": report.excluded_noise,
        "interactions_scanned": sum(
            row.interaction_count
            for row in (
                report.recent_actionable_needs_reply
                + report.stale_needs_reply
                + report.phone_ambiguous_needs_reply
                + report.waiting_on_others
            )
        ),
        "method": "read_only_local_imessage_sqlite",
    }
    return report


def format_markdown(report: SurfaceReport) -> str:
    """Render a human-readable surface report."""
    lines = [
        "# iMessage Contact Surface",
        "",
        f"Generated: {report.generated_at}",
        "",
        "Read-only scan of iMessage threads. Reply requires explicit `--confirm`.",
        "",
        "## Summary",
        "",
        "| Tier | Count | Meaning |",
        "|------|------:|---------|",
        f"| **Recent actionable** (≤{report.recent_threshold_days}d) | "
        f"**{report.summary.get('recent_actionable_needs_reply', 0)}** | "
        "Threads where you owe a reply soon |",
        f"| Stale needs reply (≥{report.stale_threshold_days}d) | "
        f"{report.summary.get('stale_needs_reply', 0)} | Named contacts waiting on you |",
        f"| Phone / ambiguous | {report.summary.get('phone_ambiguous_needs_reply', 0)} | "
        "Unresolved numbers needing reply |",
        f"| Inactive (≥{report.stale_threshold_days}d silence) | "
        f"{report.summary.get('inactive_contacts', 0)} | Last activity ≥{report.stale_threshold_days} days ago |",
        f"| Waiting on others | {report.summary.get('waiting_on_others', 0)} | You sent the last message |",
        f"| Excluded noise | {report.summary.get('excluded_noise', 0)} | "
        "Tapbacks, codes, automated senders |",
        "",
    ]

    def _table(title: str, rows: list[ThreadSurface], *, include_urgency: bool = False) -> None:
        if not rows:
            return
        lines.extend([f"## {title}", ""])
        if include_urgency:
            lines.append(
                "| Urgency | Unread | Age | Contact | Interactions | Sent / received | "
                "Active days | Last message | Last date | Thread |"
            )
            lines.append(
                "|--------:|-------:|-----|---------|-------------:|----------------:|"
                "------------:|--------------|-----------|--------|"
            )
            for row in rows:
                lines.append(
                    f"| {row.urgency} | {row.unread} | {row.age_label} | "
                    f"{_markdown_cell(row.name)} | "
                    f"{row.interaction_count} | {row.sent_count} / {row.received_count} | "
                    f"{row.active_days} | {_markdown_cell(row.snippet)} | "
                    f"{row.last_ts.strftime('%Y-%m-%d %H:%M')} | "
                    f"`{row.evidence_thread}` |"
                )
        else:
            lines.append(
                "| Unread | Age | Contact | Interactions | Sent / received | Active days | "
                "Last message | Last date | Thread |"
            )
            lines.append(
                "|-------:|-----|---------|-------------:|----------------:|------------:|"
                "--------------|-----------|--------|"
            )
            for row in rows:
                lines.append(
                    f"| {row.unread} | {row.age_label} | {_markdown_cell(row.name)} | "
                    f"{row.interaction_count} | {row.sent_count} / {row.received_count} | "
                    f"{row.active_days} | {_markdown_cell(row.snippet)} | "
                    f"{row.last_ts.strftime('%Y-%m-%d %H:%M')} | `{row.evidence_thread}` |"
                )
        lines.append("")

    _table("Recent Actionable — Reply Now", report.recent_actionable_needs_reply, include_urgency=True)
    _table(f"Stale Needs Reply (≥{report.stale_threshold_days}d)", report.stale_needs_reply)
    _table("Phone / Ambiguous", report.phone_ambiguous_needs_reply)
    _table(f"Inactive Contacts (≥{report.stale_threshold_days}d)", report.inactive_contacts)

    actionable = report.recent_actionable_needs_reply[:5] + report.stale_needs_reply[:5]
    if actionable:
        lines.extend(["## Quick Reply", ""])
        for index, row in enumerate(actionable[:8], start=1):
            note = "unread" if row.unread else "review thread"
            lines.append(
                f"{index}. **{_markdown_cell(row.name)}** - {row.age_label}, {note}, "
                f"{row.interaction_count} interactions"
            )
            lines.append(
                f"   - History: `uv run python src/imessage_surface.py thread {row.chat_id}`"
            )
            lines.append(
                "   - Draft: "
                f"`uv run python src/imessage_surface.py reply {row.chat_id} \"Your reply\"`"
            )
            lines.append("   - Send only after review: add `--confirm`")
        lines.append("")

    return "\n".join(lines)


def _lookup_contact(chat_id: str, book: ContactBook) -> Contact | None:
    rows = _load_chat_rows(DEFAULT_SCAN_LIMIT)
    for row in rows:
        if str(row[0]) != str(chat_id):
            continue
        (
            _,
            guid,
            display_name,
            text,
            ts,
            unread,
            _is_from_me,
            _interaction_count,
            _sent_count,
            _received_count,
            _active_days,
        ) = row
        conn = sqlite3.connect(f"file:{IMSG_DB}?mode=ro", uri=True)
        try:
            member_ids = [
                item[0]
                for item in conn.execute(
                    """
                    SELECT h.id
                    FROM handle h
                    JOIN chat_handle_join chj ON h.rowid = chj.handle_id
                    WHERE chj.chat_id = ?
                    """,
                    (row[0],),
                ).fetchall()
            ]
        finally:
            conn.close()
        member_names = [book.resolve(member_id) or member_id for member_id in member_ids]
        name = _chat_display_name(
            display_name=display_name,
            guid=guid,
            member_ids=member_ids,
            member_names=member_names,
            book=book,
        )
        return Contact(
            id=str(row[0]),
            name=name,
            source="imessage",
            snippet=_clean_body(text)[:60],
            unread=int(unread or 0),
            last_ts=datetime.fromtimestamp(ts, tz=UTC) if ts else datetime.now(UTC),
            guid=guid,
            is_group=len(member_ids) > 1,
            members=member_names,
        )
    return None


def show_thread(chat_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    messages = imsg_thread(chat_id, limit=limit)
    return [
        {
            "sender": message.sender,
            "body": message.body,
            "ts": message.ts.isoformat(),
            "is_me": message.is_me,
        }
        for message in messages
    ]


def quick_reply(chat_id: str, text: str, *, confirm: bool = False) -> dict[str, Any]:
    if not confirm:
        return {
            "ok": False,
            "dry_run": True,
            "chat_id": chat_id,
            "text": text,
            "message": "Pass --confirm to send via Messages.app",
        }
    init_contacts()
    book = ContactBook()
    book.load()
    contact = _lookup_contact(chat_id, book)
    if contact is None:
        return {"ok": False, "error": f"chat_id {chat_id} not found"}
    ok = imsg_send(contact, text)
    return {"ok": ok, "chat_id": chat_id, "contact": contact.name, "text": text}


def _print_thread(chat_id: str, limit: int) -> int:
    rows = show_thread(chat_id, limit=limit)
    if not rows:
        print(f"No messages for chat {chat_id}")
        return 1
    for row in rows:
        prefix = "Me" if row["is_me"] else row["sender"]
        print(f"[{row['ts']}] {prefix}: {row['body']}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Surface iMessage contacts needing replies.")
    subparsers = parser.add_subparsers(dest="command")

    scan = subparsers.add_parser("scan", help="Scan threads and print actionable contacts")
    scan.add_argument("--limit", type=int, default=DEFAULT_SCAN_LIMIT)
    scan.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS)
    scan.add_argument("--recent-days", type=int, default=DEFAULT_RECENT_DAYS)
    scan.add_argument("--json", action="store_true", help="Emit JSON instead of markdown")
    scan.add_argument("--markdown", metavar="PATH", help="Write markdown report to PATH")
    scan.add_argument("--now", default="", help="ISO timestamp override for deterministic output")

    thread = subparsers.add_parser("thread", help="Show recent messages for a chat")
    thread.add_argument("chat_id")
    thread.add_argument("--limit", type=int, default=20)

    reply = subparsers.add_parser("reply", help="Quick-reply to a chat (requires --confirm)")
    reply.add_argument("chat_id")
    reply.add_argument("text")
    reply.add_argument("--confirm", action="store_true", help="Actually send the iMessage")

    parser.set_defaults(command="scan")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "thread":
        return _print_thread(args.chat_id, args.limit)

    if args.command == "reply":
        result = quick_reply(args.chat_id, args.text, confirm=args.confirm)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") or result.get("dry_run") else 1

    init_contacts()
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else None
    report = scan_imessage_contacts(
        now=now,
        limit=args.limit,
        stale_days=args.stale_days,
        recent_days=args.recent_days,
    )

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_markdown(report))

    if args.markdown:
        path = Path(args.markdown)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(format_markdown(report), encoding="utf-8")
        print(f"\nWrote {path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
