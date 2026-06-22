#!/usr/bin/env python3
"""Build a unified, read-only contact relationship report."""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contacts import ContactBook  # noqa: E402
from message_index_store import DEFAULT_INDEX_DB  # noqa: E402
from services import IMSG_DB, _openhuman_linkedin_db_path, google_auth_all  # noqa: E402
from src.contact_dedup import MergedContact  # noqa: E402

SCHEMA = "inbox.contact_relationships.v1"
CHANNELS = ("gmail", "imessage", "linkedin", "github")
OWN_GITHUB_LOGIN = "jwalin-shah"
AUTOMATED_RE = re.compile(
    r"(?:^|[-_.])(no-?reply|notifications?|newsletter|updates?|support|team|"
    r"mailer|marketing|hello|info|security)(?:[-_.@]|$)",
    re.IGNORECASE,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | str | int | float | None) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=UTC)
        if isinstance(value, datetime):
            parsed = value
        else:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)
    except (TypeError, ValueError, OSError):
        return None


def _display_name(name: str, identifier: str) -> str:
    cleaned = re.sub(r"\s+", " ", name).strip().strip("\"'")
    if cleaned and cleaned.lower() not in {"unknown", "me"}:
        return cleaned
    if "@" in identifier:
        return identifier.split("@", 1)[0].replace(".", " ").replace("_", " ").title()
    return identifier


def _name_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _identifier_key(value: str) -> str:
    value = value.strip().casefold()
    if "@" in value:
        return value
    digits = re.sub(r"\D", "", value)
    if len(digits) >= 7:
        return digits[-10:]
    return value


def _safe_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


@dataclass
class ChannelStats:
    interactions: int = 0
    sent: int = 0
    received: int = 0
    first_at: datetime | None = None
    last_at: datetime | None = None
    contexts: set[str] = field(default_factory=set)

    def add(
        self,
        *,
        timestamp: datetime | str | int | float | None,
        sent: bool,
        context: str = "",
    ) -> None:
        self.interactions += 1
        self.sent += int(sent)
        self.received += int(not sent)
        parsed = _as_utc(timestamp)
        if parsed:
            self.first_at = min(filter(None, (self.first_at, parsed)), default=parsed)
            self.last_at = max(filter(None, (self.last_at, parsed)), default=parsed)
        if context:
            self.contexts.add(context[:80])


@dataclass
class ContactRelationship:
    key: str
    name: str
    identifiers: set[str] = field(default_factory=set)
    channels: dict[str, ChannelStats] = field(default_factory=dict)

    def add(
        self,
        channel: str,
        *,
        identifier: str,
        timestamp: datetime | str | int | float | None,
        sent: bool,
        context: str = "",
    ) -> None:
        if identifier:
            self.identifiers.add(identifier)
        self.channels.setdefault(channel, ChannelStats()).add(
            timestamp=timestamp, sent=sent, context=context
        )

    @property
    def total(self) -> int:
        return sum(item.interactions for item in self.channels.values())

    @property
    def sent(self) -> int:
        return sum(item.sent for item in self.channels.values())

    @property
    def received(self) -> int:
        return sum(item.received for item in self.channels.values())

    @property
    def last_at(self) -> datetime | None:
        values = [item.last_at for item in self.channels.values() if item.last_at]
        return max(values) if values else None

    def preferred_channel(self) -> str:
        if not self.channels:
            return "unknown"
        return max(
            self.channels,
            key=lambda channel: (
                self.channels[channel].interactions,
                self.channels[channel].last_at or datetime.min.replace(tzinfo=UTC),
            ),
        )

    def strength(self, reference: datetime) -> tuple[int, str]:
        age_days = (
            max(0.0, (reference - self.last_at).total_seconds() / 86400)
            if self.last_at
            else 3650.0
        )
        volume = min(45.0, 12.0 * math.log10(self.total + 1))
        recency = 30.0 * math.exp(-age_days / 120)
        breadth = min(15.0, 5.0 * len(self.channels))
        reciprocity = 0.0
        if self.sent and self.received:
            reciprocity = 10.0 * min(self.sent, self.received) / max(self.sent, self.received)
        score = round(min(100.0, volume + recency + breadth + reciprocity))
        tier = "strong" if score >= 70 else "active" if score >= 45 else "weak"
        return score, tier


class RelationshipBook:
    def __init__(self, contact_book: ContactBook | None = None) -> None:
        self.contact_book = contact_book or ContactBook()
        self.contact_book.load()
        self.contacts: dict[str, ContactRelationship] = {}
        self.aliases: dict[str, str] = {}

    def add(
        self,
        channel: str,
        *,
        name: str,
        identifier: str,
        timestamp: datetime | str | int | float | None,
        sent: bool,
        context: str = "",
    ) -> None:
        identifier = identifier.strip()
        resolved = self.contact_book.resolve(identifier) if identifier else ""
        chosen_name = _display_name(resolved if resolved != identifier else name, identifier)
        identifier_alias = _identifier_key(identifier)
        name_alias = _name_key(chosen_name)
        key = self.aliases.get(identifier_alias) or self.aliases.get(name_alias)
        if not key:
            key = identifier_alias or name_alias
            if not key:
                return
            self.contacts[key] = ContactRelationship(key=key, name=chosen_name)
        contact = self.contacts[key]
        if len(chosen_name) > len(contact.name) and "@" not in chosen_name:
            contact.name = chosen_name
        for alias in (identifier_alias, name_alias):
            if alias:
                self.aliases[alias] = key
        contact.add(
            channel,
            identifier=identifier,
            timestamp=timestamp,
            sent=sent,
            context=context,
        )

    def to_merged_contacts(self) -> list[MergedContact]:
        """Export unified contacts as ``MergedContact`` objects.

        One ``MergedContact`` per ``RelationshipBook`` entry, carrying
        the merged name, email identifiers, phone identifiers, and
        the list of channels where the contact was observed.
        """
        result: list[MergedContact] = []
        for contact in self.contacts.values():
            mc = MergedContact(
                name=contact.name,
                emails={i for i in contact.identifiers if "@" in i},
                phones=[i for i in contact.identifiers if "@" not in i],
                sources=list(contact.channels),
            )
            result.append(mc)
        return result


def _source_status(available: bool, detail: str, interactions: int = 0) -> dict[str, Any]:
    return {"available": available, "detail": detail, "interactions": interactions}


def load_imessage(book: RelationshipBook) -> dict[str, Any]:
    if not IMSG_DB.exists():
        return _source_status(False, f"missing {IMSG_DB}")
    conn = sqlite3.connect(f"file:{IMSG_DB}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            """
            SELECT h.id, c.display_name, m.is_from_me,
                   m.date / 1000000000.0 + 978307200 AS ts
            FROM message m
            JOIN chat_message_join cmj ON cmj.message_id = m.rowid
            JOIN chat c ON c.rowid = cmj.chat_id
            JOIN chat_handle_join chj ON chj.chat_id = c.rowid
            JOIN handle h ON h.rowid = chj.handle_id
            WHERE m.associated_message_type = 0
              AND (SELECT COUNT(*) FROM chat_handle_join x WHERE x.chat_id = c.rowid) = 1
            """
        ).fetchall()
    finally:
        conn.close()
    for identifier, display_name, is_from_me, timestamp in rows:
        book.add(
            "imessage",
            name=display_name or "",
            identifier=identifier or "",
            timestamp=timestamp,
            sent=bool(is_from_me),
            context="direct message",
        )
    return _source_status(True, f"local Messages database ({len(rows)} direct messages)", len(rows))


def _gmail_headers(message: dict[str, Any]) -> dict[str, str]:
    return {
        str(item.get("name", "")).casefold(): str(item.get("value", ""))
        for item in message.get("payload", {}).get("headers", [])
    }


def _gmail_timestamp(message: dict[str, Any], headers: dict[str, str]) -> datetime | None:
    internal = int(message.get("internalDate", 0) or 0)
    if internal:
        return _as_utc(internal / 1000)
    try:
        return parsedate_to_datetime(headers.get("date", "")).astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _iter_gmail_messages(service: Any, limit: int) -> Iterable[dict[str, Any]]:
    remaining = limit
    page_token: str | None = None
    while remaining > 0:
        result = (
            service.users()
            .messages()
            .list(
                userId="me",
                maxResults=min(500, remaining),
                pageToken=page_token,
                includeSpamTrash=False,
            )
            .execute()
        )
        stubs = result.get("messages", [])
        for stub in stubs:
            yield (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=stub["id"],
                    format="metadata",
                    metadataHeaders=["From", "To", "Cc", "Date", "Subject"],
                )
                .execute()
            )
        remaining -= len(stubs)
        page_token = result.get("nextPageToken")
        if not page_token or not stubs:
            break


def load_gmail(book: RelationshipBook, limit_per_account: int) -> dict[str, Any]:
    try:
        gmail_services, _, _, _, _, _ = google_auth_all()
    except Exception as exc:
        return _source_status(False, f"Google auth failed: {type(exc).__name__}")
    if not gmail_services:
        return _source_status(False, "no authenticated Gmail accounts")
    own_addresses = {address.casefold() for address in gmail_services}
    count = 0
    failures: list[str] = []
    for account, service in gmail_services.items():
        try:
            for message in _iter_gmail_messages(service, limit_per_account):
                headers = _gmail_headers(message)
                from_addresses = getaddresses([headers.get("from", "")])
                sent = any(address.casefold() in own_addresses for _, address in from_addresses)
                raw_targets = [headers.get("to", ""), headers.get("cc", "")] if sent else [
                    headers.get("from", "")
                ]
                for name, address in getaddresses(raw_targets):
                    if not address or address.casefold() in own_addresses:
                        continue
                    book.add(
                        "gmail",
                        name=name,
                        identifier=address,
                        timestamp=_gmail_timestamp(message, headers),
                        sent=sent,
                        context=headers.get("subject", ""),
                    )
                    count += 1
        except Exception as exc:
            failures.append(f"{account}: {type(exc).__name__}")
    detail = f"{len(gmail_services)} account(s), {limit_per_account} messages/account scanned"
    if failures:
        detail += f"; failures: {', '.join(failures)}"
    return _source_status(count > 0, detail, count)


def load_linkedin(book: RelationshipBook) -> dict[str, Any]:
    db_path = _openhuman_linkedin_db_path()
    if not db_path:
        return _source_status(False, "local LinkedIn export/scanner DB not found")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            """
            SELECT COALESCE(t.display_name, m.sender), COALESCE(t.profile_url, m.sender_profile_url),
                   m.timestamp, m.from_me, COALESCE(m.body, '')
            FROM li_messages m
            LEFT JOIN li_threads t
              ON t.account_id = m.account_id AND t.thread_id = m.thread_id
            """
        ).fetchall()
    finally:
        conn.close()
    for name, profile_url, timestamp, from_me, body in rows:
        book.add(
            "linkedin",
            name=name or "",
            identifier=profile_url or name or "",
            timestamp=timestamp,
            sent=bool(from_me),
            context=body,
        )
    return _source_status(True, f"local LinkedIn database ({len(rows)} messages)", len(rows))


def load_github(book: RelationshipBook, limit: int) -> dict[str, Any]:
    if not shutil.which("gh"):
        return _source_status(False, "gh CLI not installed")
    query = f"involves:{OWN_GITHUB_LOGIN} -author:{OWN_GITHUB_LOGIN}"
    command = [
        "gh",
        "api",
        f"search/issues?q={query}&per_page={min(100, limit)}&sort=updated&order=desc",
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
        items = json.loads(result.stdout).get("items", [])[:limit]
    except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return _source_status(False, f"GitHub query failed: {type(exc).__name__}")
    count = 0
    for item in items:
        user = item.get("user", {})
        login = str(user.get("login", ""))
        if not login or login == OWN_GITHUB_LOGIN or login.endswith("[bot]"):
            continue
        repo = str(item.get("repository_url", "")).rsplit("/", 1)[-1]
        book.add(
            "github",
            name=login,
            identifier=f"https://github.com/{login}",
            timestamp=item.get("updated_at"),
            sent=False,
            context=f"{repo}: {item.get('title', '')}",
        )
        count += 1
    return _source_status(True, f"GitHub issue/PR search ({len(items)} items scanned)", count)


def load_index_fallback(book: RelationshipBook) -> dict[str, Any]:
    if not DEFAULT_INDEX_DB.exists():
        return _source_status(False, "message index missing")
    conn = sqlite3.connect(f"file:{DEFAULT_INDEX_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT source, sender, recipients_json, subject, created_at
            FROM items
            WHERE source IN ('gmail', 'linkedin') AND is_deleted = 0
            """
        ).fetchall()
    finally:
        conn.close()
    count = 0
    for row in rows:
        if row["sender"] and row["sender"] != "Me":
            name, address = getaddresses([row["sender"]])[0]
            book.add(
                row["source"],
                name=name,
                identifier=address or row["sender"],
                timestamp=row["created_at"],
                sent=False,
                context=row["subject"],
            )
            count += 1
    return _source_status(bool(rows), f"local message index ({len(rows)} items)", count)


def build_report(
    *,
    gmail_limit: int = 300,
    github_limit: int = 100,
    include_gmail: bool = True,
    reference: datetime | None = None,
) -> tuple[RelationshipBook, dict[str, Any]]:
    book = RelationshipBook()
    status: dict[str, Any] = {}
    status["imessage"] = load_imessage(book)
    status["linkedin"] = load_linkedin(book)
    status["github"] = load_github(book, github_limit)
    status["gmail"] = (
        load_gmail(book, gmail_limit)
        if include_gmail
        else _source_status(False, "live Gmail scan disabled")
    )
    if not status["gmail"]["available"] or not status["linkedin"]["available"]:
        fallback = load_index_fallback(book)
        status["index_fallback"] = fallback
    status["generated_at"] = (reference or _now()).isoformat(timespec="seconds")
    return book, status


def render_markdown(
    book: RelationshipBook,
    status: dict[str, Any],
    *,
    limit: int = 50,
    reference: datetime | None = None,
) -> str:
    reference = reference or _now()
    contacts = sorted(
        book.contacts.values(),
        key=lambda item: (item.strength(reference)[0], item.total),
        reverse=True,
    )
    contacts = [
        item
        for item in contacts
        if item.total > 0 and not (item.preferred_channel() == "gmail" and AUTOMATED_RE.search(" ".join(item.identifiers)))
    ][:limit]
    lines = [
        "# Contact Relationship Report",
        "",
        f"Generated: {status['generated_at']}",
        f"Schema: `{SCHEMA}`",
        "",
        "## Source Coverage",
        "",
        "| Source | Available | Interactions | Evidence |",
        "|---|---:|---:|---|",
    ]
    for channel in (*CHANNELS, "index_fallback"):
        if channel not in status:
            continue
        item = status[channel]
        lines.append(
            f"| {channel} | {'yes' if item['available'] else 'no'} | "
            f"{item['interactions']} | {_safe_cell(item['detail'])} |"
        )
    lines.extend(
        [
            "",
            "Relationship strength is a 0-100 score combining interaction volume, recency, "
            "channel breadth, and sent/received reciprocity.",
            "",
            f"## Unified Contacts ({len(contacts)})",
            "",
            "| # | Contact | Interactions | Gmail | iMessage | LinkedIn | GitHub | "
            "Preferred | Last interaction | Strength |",
            "|---:|---|---:|---:|---:|---:|---:|---|---|---|",
        ]
    )
    for index, contact in enumerate(contacts, start=1):
        score, tier = contact.strength(reference)
        counts = {channel: contact.channels.get(channel, ChannelStats()).interactions for channel in CHANNELS}
        last_at = contact.last_at.date().isoformat() if contact.last_at else "unknown"
        lines.append(
            f"| {index} | **{_safe_cell(contact.name)}** | {contact.total} | "
            f"{counts['gmail']} | {counts['imessage']} | {counts['linkedin']} | "
            f"{counts['github']} | {contact.preferred_channel()} | {last_at} | "
            f"{score} ({tier}) |"
        )
    lines.extend(["", "## Interaction History", ""])
    for contact in contacts:
        score, tier = contact.strength(reference)
        identifier_text = ", ".join(sorted(contact.identifiers)[:4])
        lines.extend(
            [
                f"### {contact.name}",
                "",
                f"- **Relationship:** {score}/100 ({tier}); {contact.total} interactions; "
                f"preferred channel `{contact.preferred_channel()}`.",
                f"- **Identifiers:** {_safe_cell(identifier_text) or 'none'}.",
            ]
        )
        for channel in CHANNELS:
            stats = contact.channels.get(channel)
            if not stats:
                continue
            first = stats.first_at.date().isoformat() if stats.first_at else "unknown"
            last = stats.last_at.date().isoformat() if stats.last_at else "unknown"
            context = "; ".join(sorted(stats.contexts)[:2]) or "direct interaction"
            lines.append(
                f"- **{channel}:** {stats.interactions} total "
                f"({stats.sent} sent / {stats.received} received), {first} to {last}; "
                f"context: {_safe_cell(context)}."
            )
        lines.append("")
    unavailable = [channel for channel in CHANNELS if not status[channel]["available"]]
    if unavailable:
        lines.extend(
            [
                "## Known Gaps",
                "",
                "Unavailable sources are reported explicitly and contribute zero interactions: "
                + ", ".join(unavailable)
                + ".",
                "",
            ]
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/contact_relationship_report.md")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--gmail-limit", type=int, default=300)
    parser.add_argument("--github-limit", type=int, default=100)
    parser.add_argument("--no-gmail", action="store_true")
    args = parser.parse_args(argv)

    book, status = build_report(
        gmail_limit=max(1, args.gmail_limit),
        github_limit=max(1, args.github_limit),
        include_gmail=not args.no_gmail,
    )
    report = render_markdown(book, status, limit=max(1, args.limit))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    shown = min(args.limit, len(book.contacts))
    print(f"Wrote {output} with {shown} unified contacts")
    return 0 if shown >= 20 else 2


if __name__ == "__main__":
    raise SystemExit(main())
