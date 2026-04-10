"""
Data access layer for Inbox — iMessage, Gmail, Calendar, Notes, Audio, LLM.
All data fetching, auth, mutation, audio, and LLM logic lives here.
"""

from __future__ import annotations

import base64
import mimetypes
import re
import shutil
import sqlite3
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import BaseModel as PydanticBaseModel

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from loguru import logger

from contacts import ContactBook

# ── Config ────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
CREDS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "token.json"  # legacy single-account path
TOKENS_DIR = BASE_DIR / "tokens"
IMSG_DB = Path.home() / "Library/Messages/chat.db"
NOTES_DB = Path.home() / "Library/Group Containers/group.com.apple.notes/NoteStore.sqlite"
REMINDERS_DIR = (
    Path.home() / "Library/Group Containers/group.com.apple.reminders/Container_v1/Stores"
)
APPLE_EPOCH = datetime(2001, 1, 1)

GITHUB_TOKEN_FILE = BASE_DIR / "github_token.txt"

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
]

ATTACHMENT_PLACEHOLDER = "\ufffc"

# Global contact book
_contacts = ContactBook()


def init_contacts() -> int:
    """Load the contact book. Returns number of contacts loaded."""
    return _contacts.load()


# ── Data models ───────────────────────────────────────────────────────────────


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


# ── Helpers ──────────────────────────────────────────────────────────────────


def _clean_body(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace(ATTACHMENT_PLACEHOLDER, "(attachment)")
    return text.strip()


def _parse_email_address(raw: str) -> tuple[str, str]:
    m = re.match(r"^(.*?)\s*<([^>]+)>\s*$", raw.strip())
    if m:
        return m.group(1).strip().strip('"') or m.group(2), m.group(2).strip()
    return raw.strip(), raw.strip()


def _format_log_context(**context: object) -> str:
    formatted: list[str] = []
    for key, value in context.items():
        if value is None:
            continue
        if isinstance(value, str) and len(value) > 120:
            value = f"{value[:117]}..."
        formatted.append(f"{key}={value!r}")
    return ", ".join(formatted)


def _log_service_failure(function_name: str, **context: object) -> None:
    context_str = _format_log_context(**context)
    message = f"{function_name} failed"
    if context_str:
        message = f"{message} ({context_str})"
    logger.exception(message)


# ── Credential helpers ───────────────────────────────────────────────────────


def _load_creds(token_path: Path) -> Credentials | None:
    try:
        creds = Credentials.from_authorized_user_file(str(token_path))
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                token_path.write_text(creds.to_json())
            else:
                return None
        return creds
    except Exception:  # logged below
        _log_service_failure("_load_creds", token_path=str(token_path))
        return None


def google_auth_all() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    """Auth all accounts from tokens/ dir. Returns (gmail_svcs, cal_svcs, drive_svcs)."""
    TOKENS_DIR.mkdir(exist_ok=True)

    # Migrate legacy token.json — if it's missing scopes, re-auth
    if TOKEN_FILE.exists() and not any(TOKENS_DIR.glob("*.json")):
        creds = _load_creds(TOKEN_FILE)
        if creds:
            token_scopes = set(creds.scopes or [])
            needed = set(GOOGLE_SCOPES)
            if needed.issubset(token_scopes):
                # Has all scopes, just migrate
                shutil.copy2(TOKEN_FILE, TOKENS_DIR / "migrated.json")
            else:
                # Missing scopes — re-auth automatically
                if CREDS_FILE.exists():
                    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), GOOGLE_SCOPES)
                    new_creds = flow.run_local_server(port=0)
                    svc = build("gmail", "v1", credentials=new_creds)
                    email = svc.users().getProfile(userId="me").execute().get("emailAddress", "")
                    dest = TOKENS_DIR / f"{email}.json"
                    dest.write_text(new_creds.to_json())

    gmail_svcs: dict[str, object] = {}
    cal_svcs: dict[str, object] = {}
    drive_svcs: dict[str, object] = {}

    for token_path in sorted(TOKENS_DIR.glob("*.json")):
        creds = _load_creds(token_path)
        if not creds:
            continue

        try:
            gmail_svc = build("gmail", "v1", credentials=creds)
            profile = gmail_svc.users().getProfile(userId="me").execute()
            email = profile.get("emailAddress", token_path.stem)
            gmail_svcs[email] = gmail_svc

            expected = TOKENS_DIR / f"{email}.json"
            if token_path != expected and not expected.exists():
                token_path.rename(expected)
        except Exception:  # logged below
            _log_service_failure("google_auth_all.gmail_service", token_path=str(token_path))
            continue

        try:
            cal_svc = build("calendar", "v3", credentials=creds)
            cal_svc.calendarList().list(maxResults=1).execute()
            cal_svcs[email] = cal_svc
        except Exception:  # logged below
            _log_service_failure("google_auth_all.calendar_service", email=email)

        try:
            drive_svc = build("drive", "v3", credentials=creds)
            drive_svcs[email] = drive_svc
        except Exception:  # logged below
            _log_service_failure("google_auth_all.drive_service", email=email)

    return gmail_svcs, cal_svcs, drive_svcs


def add_google_account() -> str | None:
    TOKENS_DIR.mkdir(exist_ok=True)
    if not CREDS_FILE.exists():
        return None
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), GOOGLE_SCOPES)
    creds = flow.run_local_server(port=0)
    svc = build("gmail", "v1", credentials=creds)
    email = svc.users().getProfile(userId="me").execute().get("emailAddress", "")
    token_path = TOKENS_DIR / f"{email}.json"
    token_path.write_text(creds.to_json())
    return email


def reauth_google_account(email: str) -> str | None:
    token_path = TOKENS_DIR / f"{email}.json"
    if token_path.exists():
        token_path.unlink()
    return add_google_account()


# ── iMessage ─────────────────────────────────────────────────────────────────


def imsg_contacts(limit: int = 30) -> list[Contact]:
    if not IMSG_DB.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{IMSG_DB}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                c.rowid, c.guid, c.display_name,
                last_msg.text, last_msg.ts, last_msg.unread
            FROM chat c
            JOIN (
                SELECT
                    cmj.chat_id, m.text,
                    m.date / 1000000000 + 978307200 as ts,
                    SUM(CASE WHEN m.is_read=0 AND m.is_from_me=0
                        THEN 1 ELSE 0 END) as unread
                FROM chat_message_join cmj
                JOIN message m ON cmj.message_id = m.rowid
                WHERE m.rowid IN (
                    SELECT MAX(m2.rowid) FROM message m2
                    JOIN chat_message_join cmj2 ON m2.rowid = cmj2.message_id
                    GROUP BY cmj2.chat_id
                )
                GROUP BY cmj.chat_id
            ) last_msg ON c.rowid = last_msg.chat_id
            ORDER BY last_msg.ts DESC LIMIT ?
        """,
            (limit,),
        )
        chat_rows = cur.fetchall()

        contacts = []
        for chat_id, guid, display_name, text, ts, unread in chat_rows:
            cur.execute(
                """
                SELECT h.id FROM handle h
                JOIN chat_handle_join chj ON h.rowid = chj.handle_id
                WHERE chj.chat_id = ?
            """,
                (chat_id,),
            )
            member_ids = [r[0] for r in cur.fetchall()]
            member_names = [_contacts.resolve(m) for m in member_ids]
            is_group = len(member_ids) > 1

            if display_name and display_name.strip():
                name = display_name.strip()
            elif is_group:
                shown = member_names[:3]
                name = ", ".join(shown)
                if len(member_names) > 3:
                    name += f" +{len(member_names) - 3}"
            elif member_names:
                name = member_names[0]
            else:
                name = guid.split(";")[-1]

            contacts.append(
                Contact(
                    id=str(chat_id),
                    name=name,
                    source="imessage",
                    snippet=_clean_body(text)[:60],
                    unread=unread or 0,
                    last_ts=datetime.fromtimestamp(ts) if ts else datetime.now(),
                    guid=guid,
                    is_group=is_group,
                    members=member_names,
                )
            )

        conn.close()
        return contacts
    except Exception:  # logged below
        _log_service_failure("imsg_contacts", limit=limit, db_path=str(IMSG_DB))
        return []


def imsg_thread(chat_id: str, limit: int = 50) -> list[Msg]:
    if not IMSG_DB.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{IMSG_DB}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT m.text, m.is_from_me,
                   m.date / 1000000000 + 978307200 as ts,
                   h.id as sender_id
            FROM message m
            JOIN chat_message_join cmj ON m.rowid = cmj.message_id
            LEFT JOIN handle h ON m.handle_id = h.rowid
            WHERE cmj.chat_id = ?
            ORDER BY m.rowid DESC LIMIT ?
        """,
            (int(chat_id), limit),
        )
        rows = cur.fetchall()
        conn.close()

        msgs = []
        for text, is_me, ts, sender_id in reversed(rows):
            body = _clean_body(text)
            if not body:
                continue
            sender = "Me" if is_me else (_contacts.resolve(sender_id or "") or sender_id or "?")
            msgs.append(
                Msg(
                    sender=sender,
                    body=body,
                    ts=datetime.fromtimestamp(ts) if ts else datetime.now(),
                    is_me=bool(is_me),
                    source="imessage",
                )
            )
        return msgs
    except Exception:  # logged below
        _log_service_failure("imsg_thread", chat_id=chat_id, limit=limit, db_path=str(IMSG_DB))
        return []


def imsg_send(contact: Contact, text: str) -> bool:
    safe_text = text.replace("\\", "\\\\").replace('"', '\\"')

    if contact.is_group:
        script = f'''
        tell application "Messages"
            set targetChat to (first chat whose id is "{contact.guid}")
            send "{safe_text}" to targetChat
        end tell
        '''
    else:
        try:
            conn = sqlite3.connect(f"file:{IMSG_DB}?mode=ro", uri=True)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT h.id FROM handle h
                JOIN chat_handle_join chj ON h.rowid = chj.handle_id
                WHERE chj.chat_id = ? LIMIT 1
            """,
                (int(contact.id),),
            )
            row = cur.fetchone()
            conn.close()
            recipient = row[0] if row else contact.guid.split(";")[-1]
        except Exception:  # logged below
            _log_service_failure(
                "imsg_send.lookup_recipient",
                contact_id=contact.id,
                guid=contact.guid,
                is_group=contact.is_group,
            )
            recipient = contact.guid.split(";")[-1]

        script = f'''
        tell application "Messages"
            set targetService to (1st service whose service type = iMessage)
            send "{safe_text}" to buddy "{recipient}" of targetService
        end tell
        '''

    result = subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
    return result.returncode == 0


# ── Gmail ────────────────────────────────────────────────────────────────────


def _extract_parts(payload: dict) -> tuple[str, str]:
    plain = ""
    html = ""

    def _walk(part: dict) -> None:
        nonlocal plain, html
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data", "")
        if mime == "text/plain" and data and not plain:
            plain = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        elif mime == "text/html" and data and not html:
            html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        for sub in part.get("parts", []):
            _walk(sub)

    _walk(payload)
    return plain, html


def _html_to_text(html: str) -> str:
    text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|tr|li|h[1-6])>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<(p|div|tr|h[1-6])[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "  • ", text, flags=re.IGNORECASE)
    text = re.sub(
        r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
        r"\2 (\1)",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#39;", "'", text)
    text = re.sub(r"&#\d+;", "", text)
    text = re.sub(r"&\w+;", "", text)
    return text


def _decode_body(payload: dict) -> str:
    plain, html = _extract_parts(payload)
    if plain:
        return _clean_email_body(plain.strip())
    if html:
        return _clean_email_body(_html_to_text(html).strip())
    return ""


def _clean_email_body(body: str) -> str:
    lines = body.split("\n")
    cleaned: list[str] = []
    for line in lines:
        if re.match(r"^On .+ wrote:\s*$", line):
            break
        if line.strip().startswith(">"):
            continue
        if line.strip() == "--":
            break
        if line.strip() == "---":
            break
        if re.match(
            r"^\s*(unsubscribe|view in browser|view this email)",
            line,
            re.IGNORECASE,
        ):
            continue
        if re.match(
            r"^\s*https?://\S*(track|click|unsubscribe|list-manage)",
            line,
            re.IGNORECASE,
        ):
            continue
        cleaned.append(line)

    result = "\n".join(cleaned).strip()
    result = re.sub(r"\n{3,}", "\n\n", result)
    result = re.sub(r"[ \t]{3,}", "  ", result)
    return result


def gmail_contacts(service, account_email: str, limit: int = 20) -> list[Contact]:
    try:
        result = (
            service.users()
            .messages()
            .list(userId="me", labelIds=["INBOX"], maxResults=limit)
            .execute()
        )
        messages = result.get("messages", [])
        contacts = []
        seen_threads: set[str] = set()
        for m in messages:
            thread_id = m.get("threadId", m["id"])
            if thread_id in seen_threads:
                continue
            msg = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=m["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date", "Message-ID"],
                )
                .execute()
            )
            headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
            raw_from = headers.get("From", "Unknown")
            display_name, email_addr = _parse_email_address(raw_from)
            subject = headers.get("Subject", "(no subject)")
            msg_id_header = headers.get("Message-ID", "")
            seen_threads.add(thread_id)
            unread = "UNREAD" in msg.get("labelIds", [])
            ts_ms = int(msg.get("internalDate", 0))
            msg_ts = datetime.fromtimestamp(ts_ms / 1000) if ts_ms else datetime.now()
            contacts.append(
                Contact(
                    id=m["id"],
                    name=display_name,
                    source="gmail",
                    snippet=subject[:60],
                    unread=1 if unread else 0,
                    last_ts=msg_ts,
                    reply_to=email_addr,
                    thread_id=thread_id,
                    message_id_header=msg_id_header,
                    gmail_account=account_email,
                )
            )
        return contacts
    except Exception:  # logged below
        _log_service_failure("gmail_contacts", account_email=account_email, limit=limit)
        return []


def gmail_thread(service, msg_id: str, thread_id: str = "") -> list[Msg]:
    try:
        tid = thread_id or msg_id
        thread = service.users().threads().get(userId="me", id=tid, format="full").execute()
        msgs = []
        me_email = service.users().getProfile(userId="me").execute().get("emailAddress", "")
        for i, m in enumerate(thread.get("messages", [])):
            headers = {h["name"]: h["value"] for h in m["payload"]["headers"]}
            raw_from = headers.get("From", "Unknown")
            display_name, email_addr = _parse_email_address(raw_from)
            subject = headers.get("Subject", "")
            to_raw = headers.get("To", "")
            body = _decode_body(m["payload"])
            ts_ms = int(m.get("internalDate", 0))
            ts = datetime.fromtimestamp(ts_ms / 1000) if ts_ms else datetime.now()
            is_me = me_email.lower() in email_addr.lower()
            sender = "Me" if is_me else display_name
            if body:
                if i == 0 and subject:
                    body = f"Subject: {subject}\nTo: {to_raw}\n{'─' * 30}\n\n{body}"
                msgs.append(
                    Msg(
                        sender=sender,
                        body=body,
                        ts=ts,
                        is_me=is_me,
                        source="gmail",
                    )
                )
        return msgs
    except Exception:  # logged below
        _log_service_failure("gmail_thread", msg_id=msg_id, thread_id=thread_id or msg_id)
        return []


def gmail_send(service, contact: Contact, body: str) -> bool:
    msg = MIMEText(body)
    msg["to"] = contact.reply_to
    msg["subject"] = f"Re: {contact.snippet}"
    if contact.message_id_header:
        msg["In-Reply-To"] = contact.message_id_header
        msg["References"] = contact.message_id_header
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    send_body: dict = {"raw": raw}
    if contact.thread_id:
        send_body["threadId"] = contact.thread_id
    try:
        service.users().messages().send(userId="me", body=send_body).execute()
        return True
    except Exception:  # logged below
        _log_service_failure(
            "gmail_send",
            reply_to=contact.reply_to,
            thread_id=contact.thread_id,
            body_length=len(body),
        )
        return False


# ── Calendar ─────────────────────────────────────────────────────────────────


def calendar_events(
    cal_services: dict[str, object], date: datetime | None = None
) -> list[CalendarEvent]:
    """Fetch events for a given day from all accounts."""
    now = (date or datetime.now()).astimezone()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    events: list[CalendarEvent] = []
    for email, svc in cal_services.items():
        try:
            cal_list = svc.calendarList().list().execute()  # type: ignore[attr-defined]
            for cal_entry in cal_list.get("items", []):
                cal_id = cal_entry["id"]
                result = (
                    svc.events()  # type: ignore[attr-defined]
                    .list(
                        calendarId=cal_id,
                        timeMin=start_of_day.isoformat(),
                        timeMax=end_of_day.isoformat(),
                        singleEvents=True,
                        orderBy="startTime",
                    )
                    .execute()
                )

                for item in result.get("items", []):
                    start_raw = item.get("start", {})
                    end_raw = item.get("end", {})

                    all_day = "date" in start_raw
                    if all_day:
                        start_dt = datetime.strptime(start_raw["date"], "%Y-%m-%d")
                        end_dt = datetime.strptime(end_raw["date"], "%Y-%m-%d")
                    else:
                        start_dt = datetime.fromisoformat(start_raw.get("dateTime", ""))
                        end_dt = datetime.fromisoformat(end_raw.get("dateTime", ""))

                    events.append(
                        CalendarEvent(
                            summary=item.get("summary", "(No title)"),
                            start=start_dt,
                            end=end_dt,
                            location=item.get("location", ""),
                            description=item.get("description", ""),
                            account=email,
                            all_day=all_day,
                            event_id=item.get("id", ""),
                            calendar_id=cal_id,
                        )
                    )
        except Exception:  # logged below
            _log_service_failure(
                "calendar_events.account",
                account=email,
                date=start_of_day.date().isoformat(),
            )
            continue

    events.sort(key=lambda e: (not e.all_day, e.start))
    return events


def _build_event_body(
    summary: str,
    start: datetime,
    end: datetime,
    location: str = "",
    description: str = "",
    all_day: bool = False,
) -> dict:
    body: dict = {"summary": summary}
    if all_day:
        body["start"] = {"date": start.strftime("%Y-%m-%d")}
        body["end"] = {"date": end.strftime("%Y-%m-%d")}
    else:
        tz = start.astimezone().tzinfo
        tz_name = str(tz) if tz else "America/Los_Angeles"
        body["start"] = {
            "dateTime": start.astimezone().isoformat(),
            "timeZone": tz_name,
        }
        body["end"] = {
            "dateTime": end.astimezone().isoformat(),
            "timeZone": tz_name,
        }
    if location:
        body["location"] = location
    if description:
        body["description"] = description
    return body


def calendar_create_event(
    cal_service,
    summary: str,
    start: datetime,
    end: datetime,
    location: str = "",
    description: str = "",
    all_day: bool = False,
    calendar_id: str = "primary",
) -> str | None:
    try:
        body = _build_event_body(summary, start, end, location, description, all_day)
        result = cal_service.events().insert(calendarId=calendar_id, body=body).execute()
        return result.get("id")
    except Exception:  # logged below
        _log_service_failure(
            "calendar_create_event",
            summary=summary,
            calendar_id=calendar_id,
            all_day=all_day,
        )
        return None


def calendar_update_event(
    cal_service,
    event_id: str,
    summary: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    location: str | None = None,
    description: str | None = None,
    calendar_id: str = "primary",
) -> bool:
    try:
        existing = cal_service.events().get(calendarId=calendar_id, eventId=event_id).execute()
        if summary is not None:
            existing["summary"] = summary
        if start is not None:
            all_day = "date" in existing.get("start", {})
            if all_day:
                existing["start"] = {"date": start.strftime("%Y-%m-%d")}
            else:
                existing["start"] = {"dateTime": start.astimezone().isoformat()}
        if end is not None:
            all_day = "date" in existing.get("end", {})
            if all_day:
                existing["end"] = {"date": end.strftime("%Y-%m-%d")}
            else:
                existing["end"] = {"dateTime": end.astimezone().isoformat()}
        if location is not None:
            existing["location"] = location
        if description is not None:
            existing["description"] = description
        cal_service.events().update(
            calendarId=calendar_id, eventId=event_id, body=existing
        ).execute()
        return True
    except Exception:  # logged below
        _log_service_failure(
            "calendar_update_event",
            event_id=event_id,
            calendar_id=calendar_id,
            summary=summary,
        )
        return False


def calendar_delete_event(cal_service, event_id: str, calendar_id: str = "primary") -> bool:
    try:
        cal_service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        return True
    except Exception:  # logged below
        _log_service_failure(
            "calendar_delete_event",
            event_id=event_id,
            calendar_id=calendar_id,
        )
        return False


# ── Notes ────────────────────────────────────────────────────────────────────


def notes_list(limit: int = 50) -> list[Note]:
    """List recent Apple Notes from SQLite."""
    if not NOTES_DB.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{NOTES_DB}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                n.Z_PK,
                n.ZTITLE1,
                n.ZSNIPPET,
                n.ZMODIFICATIONDATE1,
                COALESCE(f.ZTITLE2, '') as folder
            FROM ZICCLOUDSYNCINGOBJECT n
            LEFT JOIN ZICCLOUDSYNCINGOBJECT f
                ON n.ZFOLDER = f.Z_PK
            WHERE n.ZTITLE1 IS NOT NULL
            AND (n.ZMARKEDFORDELETION IS NULL OR n.ZMARKEDFORDELETION = 0)
            ORDER BY n.ZMODIFICATIONDATE1 DESC
            LIMIT ?
        """,
            (limit,),
        )
        rows = cur.fetchall()
        conn.close()

        notes = []
        for pk, title, snippet, mod_date, folder in rows:
            ts = APPLE_EPOCH + timedelta(seconds=mod_date) if mod_date else datetime.now()
            notes.append(
                Note(
                    id=str(pk),
                    title=title or "(Untitled)",
                    snippet=(snippet or "")[:100],
                    modified=ts,
                    folder=folder or "",
                )
            )
        return notes
    except Exception:  # logged below
        _log_service_failure("notes_list", limit=limit, db_path=str(NOTES_DB))
        return []


def note_body(title: str) -> str:
    """Get full note body via AppleScript."""
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
    tell application "Notes"
        try
            set theNote to first note whose name is "{safe_title}"
            return plaintext of theNote
        on error
            return ""
        end try
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=10,
            text=True,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:  # logged below
        _log_service_failure("note_body", title=title)
        return ""


# ── Quick event parser ───────────────────────────────────────────────────────


def _parse_time(s: str) -> datetime | None:
    s = s.strip().lower()
    now = datetime.now()
    m = re.match(r"^(\d{1,2}):(\d{2})$", s)
    if m:
        return now.replace(
            hour=int(m.group(1)),
            minute=int(m.group(2)),
            second=0,
            microsecond=0,
        )
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$", s)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        if m.group(3) == "pm" and hour != 12:
            hour += 12
        elif m.group(3) == "am" and hour == 12:
            hour = 0
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return None


def parse_quick_event(text: str) -> dict:
    """Parse quick event format: Title HH:MM-HH:MM @ Location"""
    location = ""
    if " @ " in text:
        text, location = text.rsplit(" @ ", 1)

    if text.lower().startswith("all day:"):
        summary = text[8:].strip()
        now = datetime.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return {
            "summary": summary,
            "start": start,
            "end": end,
            "location": location,
            "all_day": True,
        }

    time_pattern = (
        r"(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*[-–]\s*"
        r"(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*$"
    )
    m = re.search(time_pattern, text, re.IGNORECASE)
    if m:
        summary = text[: m.start()].strip()
        start = _parse_time(m.group(1))
        end = _parse_time(m.group(2))
        if start and end:
            return {
                "summary": summary,
                "start": start,
                "end": end,
                "location": location,
                "all_day": False,
            }

    now = datetime.now().replace(second=0, microsecond=0)
    return {
        "summary": text,
        "start": now,
        "end": now + timedelta(hours=1),
        "location": location,
        "all_day": False,
    }


# ── Apple Reminders ─────────────────────────────────────────────────────────


def _reminders_dbs() -> list[Path]:
    """Find all non-empty Reminders SQLite databases."""
    if not REMINDERS_DIR.exists():
        return []
    dbs = []
    for p in sorted(REMINDERS_DIR.glob("Data-*.sqlite")):
        try:
            conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            count = conn.execute("SELECT COUNT(*) FROM ZREMCDREMINDER").fetchone()[0]
            conn.close()
            if count > 0:
                dbs.append(p)
        except Exception:  # logged below
            _log_service_failure("_reminders_dbs", db_path=str(p))
            continue
    return dbs


def reminders_lists() -> list[dict[str, str | int]]:
    """List all reminder lists with item counts."""
    lists: list[dict[str, str | int]] = []
    seen_names: set[str] = set()
    for db_path in _reminders_dbs():
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT l.ZNAME, COUNT(r.Z_PK)
                FROM ZREMCDBASELIST l
                LEFT JOIN ZREMCDREMINDER r ON r.ZLIST = l.Z_PK
                    AND (r.ZMARKEDFORDELETION IS NULL OR r.ZMARKEDFORDELETION = 0)
                    AND r.ZCOMPLETED = 0
                WHERE (l.ZMARKEDFORDELETION IS NULL OR l.ZMARKEDFORDELETION = 0)
                    AND l.ZNAME IS NOT NULL
                GROUP BY l.ZNAME
                ORDER BY l.ZNAME
            """
            )
            for name, count in cur.fetchall():
                if name and name not in seen_names:
                    seen_names.add(name)
                    lists.append({"name": name, "incomplete_count": count})
            conn.close()
        except Exception:  # logged below
            _log_service_failure("reminders_lists", db_path=str(db_path))
            continue
    return lists


def reminders_list(
    list_name: str | None = None,
    show_completed: bool = False,
    limit: int = 100,
) -> list[Reminder]:
    """List reminders, optionally filtered by list name."""
    reminders: list[Reminder] = []
    for db_path in _reminders_dbs():
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cur = conn.cursor()
            query = """
                SELECT
                    r.Z_PK, r.ZTITLE, r.ZCOMPLETED, r.ZFLAGGED, r.ZPRIORITY,
                    r.ZDUEDATE, r.ZNOTES, r.ZCREATIONDATE,
                    COALESCE(l.ZNAME, '') as list_name
                FROM ZREMCDREMINDER r
                LEFT JOIN ZREMCDBASELIST l ON r.ZLIST = l.Z_PK
                WHERE (r.ZMARKEDFORDELETION IS NULL OR r.ZMARKEDFORDELETION = 0)
            """
            params: list = []
            if not show_completed:
                query += " AND r.ZCOMPLETED = 0"
            if list_name:
                query += " AND l.ZNAME = ?"
                params.append(list_name)
            query += " ORDER BY r.ZDUEDATE IS NULL, r.ZDUEDATE ASC, r.ZCREATIONDATE DESC LIMIT ?"
            params.append(limit)

            cur.execute(query, params)
            for (
                pk,
                title,
                completed,
                flagged,
                priority,
                due,
                notes,
                created,
                lname,
            ) in cur.fetchall():
                due_dt = (APPLE_EPOCH + timedelta(seconds=due)) if due else None
                created_dt = (APPLE_EPOCH + timedelta(seconds=created)) if created else None
                reminders.append(
                    Reminder(
                        id=str(pk),
                        title=title or "(Untitled)",
                        completed=bool(completed),
                        list_name=lname,
                        due_date=due_dt,
                        notes=notes or "",
                        priority=priority or 0,
                        flagged=bool(flagged),
                        creation_date=created_dt,
                    )
                )
            conn.close()
        except Exception:  # logged below
            _log_service_failure(
                "reminders_list",
                db_path=str(db_path),
                list_name=list_name,
                show_completed=show_completed,
                limit=limit,
            )
            continue
    return reminders


def reminder_complete(title: str) -> bool:
    """Mark a reminder as complete via AppleScript."""
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
    tell application "Reminders"
        try
            set theReminder to (first reminder whose name is "{safe_title}" and completed is false)
            set completed of theReminder to true
            return "ok"
        on error
            return "fail"
        end try
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script], capture_output=True, timeout=10, text=True
        )
        return result.returncode == 0 and "ok" in result.stdout
    except Exception:  # logged below
        _log_service_failure("reminder_complete", title=title)
        return False


def reminder_create(
    title: str,
    list_name: str = "Reminders",
    due_date: str = "",
    notes: str = "",
) -> bool:
    """Create a new reminder via AppleScript."""
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    safe_notes = notes.replace("\\", "\\\\").replace('"', '\\"')
    safe_list = list_name.replace("\\", "\\\\").replace('"', '\\"')

    props = f'name:"{safe_title}"'
    if notes:
        props += f', body:"{safe_notes}"'

    # Build due date clause
    due_clause = ""
    if due_date:
        due_clause = f"""
            set dStr to "{due_date}"
            set due date of theReminder to date dStr
        """

    script = f'''
    tell application "Reminders"
        try
            set targetList to list "{safe_list}"
        on error
            set targetList to default list
        end try
        set theReminder to make new reminder in targetList with properties {{{props}}}
        {due_clause}
        return "ok"
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script], capture_output=True, timeout=10, text=True
        )
        return result.returncode == 0 and "ok" in result.stdout
    except Exception:  # logged below
        _log_service_failure(
            "reminder_create",
            title=title,
            list_name=list_name,
            due_date=due_date,
            notes_present=bool(notes),
        )
        return False


# ── GitHub ──────────────────────────────────────────────────────────────────

_GITHUB_API = "https://api.github.com"


def _github_token() -> str | None:
    """Get GitHub token — tries gh CLI first, then falls back to file."""
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:  # logged below
        _log_service_failure("_github_token", token_file=str(GITHUB_TOKEN_FILE))
    if GITHUB_TOKEN_FILE.exists():
        return GITHUB_TOKEN_FILE.read_text().strip()
    return None


def _github_headers() -> dict[str, str]:
    token = _github_token()
    if not token:
        return {}
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def github_notifications(all_notifs: bool = False) -> list[GitHubNotification]:
    """Fetch GitHub notifications."""
    headers = _github_headers()
    if not headers:
        return []
    try:
        params = {"all": "true"} if all_notifs else {}
        resp = httpx.get(f"{_GITHUB_API}/notifications", headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        notifs = []
        for n in resp.json():
            subject = n.get("subject", {})
            repo = n.get("repository", {}).get("full_name", "")
            updated = n.get("updated_at", "")
            ts = (
                datetime.fromisoformat(updated.replace("Z", "+00:00"))
                if updated
                else datetime.now()
            )
            # Build a web URL from the API URL
            api_url = subject.get("url", "")
            web_url = ""
            if api_url:
                web_url = api_url.replace("api.github.com/repos", "github.com").replace(
                    "/pulls/", "/pull/"
                )
            notifs.append(
                GitHubNotification(
                    id=n.get("id", ""),
                    title=subject.get("title", ""),
                    repo=repo,
                    type=subject.get("type", ""),
                    reason=n.get("reason", ""),
                    unread=n.get("unread", False),
                    updated_at=ts,
                    url=web_url,
                )
            )
        return notifs
    except Exception:  # logged below
        _log_service_failure("github_notifications", all_notifs=all_notifs)
        return []


def github_mark_read(notification_id: str) -> bool:
    """Mark a single GitHub notification as read."""
    headers = _github_headers()
    if not headers:
        return False
    try:
        resp = httpx.patch(
            f"{_GITHUB_API}/notifications/threads/{notification_id}",
            headers=headers,
            timeout=10,
        )
        return resp.status_code in (200, 205)
    except Exception:  # logged below
        _log_service_failure("github_mark_read", notification_id=notification_id)
        return False


def github_mark_all_read() -> bool:
    """Mark all GitHub notifications as read."""
    headers = _github_headers()
    if not headers:
        return False
    try:
        resp = httpx.put(
            f"{_GITHUB_API}/notifications",
            headers=headers,
            json={"last_read_at": datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%SZ")},
            timeout=10,
        )
        return resp.status_code in (200, 202, 205)
    except Exception:  # logged below
        _log_service_failure("github_mark_all_read")
        return False


def github_pulls(repo: str | None = None) -> list[dict]:
    """Fetch pull requests assigned to or requesting review from the user."""
    headers = _github_headers()
    if not headers:
        return []
    try:
        # Search for PRs involving the authenticated user
        query = "is:pr is:open review-requested:@me"
        if repo:
            query += f" repo:{repo}"
        resp = httpx.get(
            f"{_GITHUB_API}/search/issues",
            headers=headers,
            params={"q": query, "sort": "updated", "per_page": "30"},
            timeout=15,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return [
            {
                "id": item["id"],
                "number": item["number"],
                "title": item["title"],
                "repo": item.get("repository_url", "").split("/repos/")[-1],
                "user": item.get("user", {}).get("login", ""),
                "state": item["state"],
                "url": item["html_url"],
                "updated_at": item["updated_at"],
            }
            for item in items
        ]
    except Exception:  # logged below
        _log_service_failure("github_pulls", repo=repo)
        return []


# ── Google Drive ────────────────────────────────────────────────────────────


def drive_files(
    drive_service,
    query: str = "",
    limit: int = 20,
    shared_with_me: bool = False,
) -> list[DriveFile]:
    """List files from Google Drive."""
    try:
        q_parts = []
        if shared_with_me:
            q_parts.append("sharedWithMe = true")
        if query:
            q_parts.append(f"name contains '{query}'")
        q_parts.append("trashed = false")
        q = " and ".join(q_parts)

        result = (
            drive_service.files()
            .list(
                q=q,
                pageSize=limit,
                fields="files(id, name, mimeType, modifiedTime, size, shared, webViewLink, parents)",
                orderBy="modifiedTime desc",
            )
            .execute()
        )
        files = []
        for f in result.get("files", []):
            mod = f.get("modifiedTime", "")
            ts = datetime.fromisoformat(mod.replace("Z", "+00:00")) if mod else datetime.now()
            files.append(
                DriveFile(
                    id=f["id"],
                    name=f.get("name", ""),
                    mime_type=f.get("mimeType", ""),
                    modified=ts,
                    size=int(f.get("size", 0)),
                    shared=f.get("shared", False),
                    web_link=f.get("webViewLink", ""),
                    parents=f.get("parents", []),
                )
            )
        return files
    except Exception:  # logged below
        _log_service_failure(
            "drive_files",
            query=query,
            limit=limit,
            shared_with_me=shared_with_me,
        )
        return []


def drive_upload(
    drive_service,
    file_path: str,
    folder_id: str = "",
    name: str = "",
) -> DriveFile | None:
    """Upload a file to Google Drive."""
    from googleapiclient.http import MediaFileUpload

    p = Path(file_path)
    if not p.exists():
        return None
    try:
        mime_type = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        metadata: dict = {"name": name or p.name}
        if folder_id:
            metadata["parents"] = [folder_id]

        media = MediaFileUpload(str(p), mimetype=mime_type, resumable=True)
        result = (
            drive_service.files()
            .create(
                body=metadata,
                media_body=media,
                fields="id, name, mimeType, modifiedTime, size, webViewLink",
            )
            .execute()
        )
        mod = result.get("modifiedTime", "")
        ts = datetime.fromisoformat(mod.replace("Z", "+00:00")) if mod else datetime.now()
        return DriveFile(
            id=result["id"],
            name=result.get("name", ""),
            mime_type=result.get("mimeType", ""),
            modified=ts,
            size=int(result.get("size", 0)),
            web_link=result.get("webViewLink", ""),
        )
    except Exception:  # logged below
        _log_service_failure(
            "drive_upload",
            file_path=file_path,
            folder_id=folder_id,
            name=name or p.name,
        )
        return None


def drive_create_folder(drive_service, name: str, parent_id: str = "") -> DriveFile | None:
    """Create a folder in Google Drive."""
    try:
        metadata: dict = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            metadata["parents"] = [parent_id]
        result = (
            drive_service.files()
            .create(body=metadata, fields="id, name, mimeType, modifiedTime, webViewLink")
            .execute()
        )
        mod = result.get("modifiedTime", "")
        ts = datetime.fromisoformat(mod.replace("Z", "+00:00")) if mod else datetime.now()
        return DriveFile(
            id=result["id"],
            name=result.get("name", ""),
            mime_type=result.get("mimeType", ""),
            modified=ts,
            web_link=result.get("webViewLink", ""),
        )
    except Exception:  # logged below
        _log_service_failure("drive_create_folder", name=name, parent_id=parent_id)
        return None


def drive_delete(drive_service, file_id: str) -> bool:
    """Delete (trash) a file from Google Drive."""
    try:
        drive_service.files().update(fileId=file_id, body={"trashed": True}).execute()
        return True
    except Exception:  # logged below
        _log_service_failure("drive_delete", file_id=file_id)
        return False


def drive_get(drive_service, file_id: str) -> DriveFile | None:
    """Get metadata for a single Drive file."""
    try:
        f = (
            drive_service.files()
            .get(
                fileId=file_id,
                fields="id, name, mimeType, modifiedTime, size, shared, webViewLink, parents",
            )
            .execute()
        )
        mod = f.get("modifiedTime", "")
        ts = datetime.fromisoformat(mod.replace("Z", "+00:00")) if mod else datetime.now()
        return DriveFile(
            id=f["id"],
            name=f.get("name", ""),
            mime_type=f.get("mimeType", ""),
            modified=ts,
            size=int(f.get("size", 0)),
            shared=f.get("shared", False),
            web_link=f.get("webViewLink", ""),
            parents=f.get("parents", []),
        )
    except Exception:  # logged below
        _log_service_failure("drive_get", file_id=file_id)
        return None


# ── Whisper / Audio Config ──────────────────────────────────────────────────

# MLX Whisper for chunk-based ambient transcription
MLX_WHISPER_MODEL = "mlx-community/whisper-base.en-mlx"

# whisper-stream C++ binary for real-time dictation
WHISPER_STREAM_BIN = "/opt/homebrew/bin/whisper-stream"
WHISPER_STREAM_MODEL = (
    "/opt/homebrew/Cellar/whisper-cpp/1.8.4/share/whisper-cpp/ggml-base.en-q8_0.bin"
)

# Audio settings
SAMPLE_RATE = 16000
CHUNK_SECS = 5  # ambient: transcribe every N seconds
SILENCE_RMS_THRESHOLD = 0.01  # skip chunks below this RMS

# Vocabulary prompt — biases whisper toward these technical terms
VOCAB_PROMPT = (
    "Claude Code, mlx-lm, mlx-whisper, Outlines, Qwen, Textual, "
    "Ghostty, Raycast, AeroSpace, sketchybar, FastAPI, inbox"
)


def whisper_stream_available() -> bool:
    """Check if the whisper-stream binary and model are available."""
    return Path(WHISPER_STREAM_BIN).exists() and Path(WHISPER_STREAM_MODEL).exists()


# ── Ambient Service ─────────────────────────────────────────────────────────

MIN_CHUNK_WORDS = 10
FLUSH_INTERVAL = 60  # seconds between extraction passes


class AmbientService:
    """Background ambient transcription service."""

    def __init__(self, on_note: Callable[[str, str | None], None]):
        self._on_note = on_note
        self._buffer: list[str] = []
        self._buffer_lock = threading.Lock()
        self._running = False
        self._capture_thread: threading.Thread | None = None
        self._flush_thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @is_running.setter
    def is_running(self, value: bool) -> None:
        self._running = value

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._capture_thread.start()
        self._flush_thread.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._process_buffer()

    def _capture_loop(self) -> None:
        import mlx_whisper
        import numpy as np
        import sounddevice as sd

        while self._running:
            try:
                audio = sd.rec(
                    int(CHUNK_SECS * SAMPLE_RATE),
                    samplerate=SAMPLE_RATE,
                    channels=1,
                    dtype="float32",
                )
                sd.wait()

                if not self._running:
                    break

                audio_flat = audio.flatten()
                rms = float(np.sqrt(np.mean(audio_flat**2)))
                if rms < SILENCE_RMS_THRESHOLD:
                    continue

                result = mlx_whisper.transcribe(
                    audio_flat, path_or_hf_repo=MLX_WHISPER_MODEL, language="en"
                )
                text = result.get("text", "").strip()  # type: ignore[union-attr]
                if text:
                    with self._buffer_lock:
                        self._buffer.append(text)

            except Exception:  # logged below
                _log_service_failure(
                    "AmbientService._capture_loop",
                    chunk_secs=CHUNK_SECS,
                    sample_rate=SAMPLE_RATE,
                )
                time.sleep(1)

    def _flush_loop(self) -> None:
        while self._running:
            time.sleep(FLUSH_INTERVAL)
            if self._running:
                self._process_buffer()

    def _process_buffer(self) -> None:
        with self._buffer_lock:
            if not self._buffer:
                return
            chunk = " ".join(self._buffer)
            self._buffer.clear()

        if len(chunk.split()) < MIN_CHUNK_WORDS:
            return

        summary = None
        try:
            summary = extract_summary(chunk)
        except Exception:  # logged below
            _log_service_failure(
                "AmbientService._process_buffer",
                chunk_words=len(chunk.split()),
            )

        self._on_note(chunk, summary)


# ── Dictation Service ───────────────────────────────────────────────────────


def _type_text(text: str) -> None:
    """Inject text at current cursor position via macOS CGEvent."""
    import Quartz

    src = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)  # type: ignore[attr-defined]
    for char in text:
        down = Quartz.CGEventCreateKeyboardEvent(src, 0, True)  # type: ignore[attr-defined]
        up = Quartz.CGEventCreateKeyboardEvent(src, 0, False)  # type: ignore[attr-defined]
        Quartz.CGEventKeyboardSetUnicodeString(down, 1, char)  # type: ignore[attr-defined]
        Quartz.CGEventKeyboardSetUnicodeString(up, 1, char)  # type: ignore[attr-defined]
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)  # type: ignore[attr-defined]
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)  # type: ignore[attr-defined]
        time.sleep(0.001)


def _clean_line(line: str) -> str:
    """Strip whisper-stream ANSI codes and timestamp markers."""
    line = re.sub(r"\x1b\[[0-9;]*m", "", line)
    line = re.sub(r"\[\d+:\d+:\d+\.\d+ --> \d+:\d+:\d+\.\d+\s*\]", "", line)
    return line.strip()


class DictationService:
    """Background dictation service — streams ASR to keyboard."""

    def __init__(self) -> None:
        self._running = False
        self._available: bool | None = None
        self._thread: threading.Thread | None = None
        self._proc: subprocess.Popen | None = None  # type: ignore[type-arg]
        self._last_text = ""

    @property
    def is_running(self) -> bool:
        return self._running

    @is_running.setter
    def is_running(self, value: bool) -> None:
        self._running = value

    @property
    def available(self) -> bool:
        return whisper_stream_available() if self._available is None else self._available

    @available.setter
    def available(self, value: bool) -> None:
        self._available = value

    def start(self) -> None:
        if self._running:
            return
        if not self.available:
            raise RuntimeError(f"whisper-stream not found at {WHISPER_STREAM_BIN}")
        self._running = True
        self._last_text = ""
        self._thread = threading.Thread(target=self._stream_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._proc:
            self._proc.terminate()
            self._proc = None

    def _stream_loop(self) -> None:
        self._proc = subprocess.Popen(
            [
                WHISPER_STREAM_BIN,
                "-m",
                WHISPER_STREAM_MODEL,
                "--language",
                "en",
                "--step",
                "500",
                "--length",
                "5000",
                "--keep",
                "200",
                "--prompt",
                VOCAB_PROMPT,
                "--no-timestamps",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )

        try:
            assert self._proc.stdout is not None
            for raw_line in self._proc.stdout:
                if not self._running:
                    break

                text = _clean_line(raw_line)
                if not text:
                    continue

                if text.startswith(self._last_text):
                    new_part = text[len(self._last_text) :].lstrip()
                elif self._last_text and self._last_text in text:
                    new_part = text[text.index(self._last_text) + len(self._last_text) :].lstrip()
                else:
                    new_part = text

                if new_part:
                    _type_text(new_part + " ")

                self._last_text = text

        except Exception:  # logged below
            _log_service_failure(
                "DictationService._stream_loop",
                binary_path=WHISPER_STREAM_BIN,
                model_path=WHISPER_STREAM_MODEL,
            )
        finally:
            if self._proc:
                self._proc.terminate()
                self._proc = None
            self._running = False


# ── LLM Engine ──────────────────────────────────────────────────────────────

MLX_MODEL = "mlx-community/Qwen3.5-0.8B-MLX-4bit"

_llm_lock = threading.Lock()
_llm_model: object | None = None
_llm_tokenizer: object | None = None


def _ensure_llm_loaded() -> None:
    """Load model + tokenizer once. Thread-safe."""
    global _llm_model, _llm_tokenizer
    if _llm_model is not None:
        return
    with _llm_lock:
        if _llm_model is not None:
            return
        import mlx_lm

        _llm_model, _llm_tokenizer = mlx_lm.load(MLX_MODEL)[:2]  # type: ignore[assignment]


def get_outlines_model() -> object:
    """Return an Outlines-wrapped model for constrained generation."""
    _ensure_llm_loaded()
    import outlines

    return outlines.models.mlxlm(MLX_MODEL)  # type: ignore[attr-defined]


def llm_complete(prompt: str, max_tokens: int = 64, temperature: float = 0.7) -> str:
    """Free-form text completion. Used for autocomplete suggestions."""
    _ensure_llm_loaded()
    import mlx_lm
    from mlx_lm.sample_utils import make_sampler

    return mlx_lm.generate(
        _llm_model,  # type: ignore[arg-type]
        _llm_tokenizer,  # type: ignore[arg-type]
        prompt=prompt,
        max_tokens=max_tokens,
        sampler=make_sampler(temp=temperature),
    )


def generate_json(prompt: str, schema: type[PydanticBaseModel]) -> PydanticBaseModel:
    """Generate constrained JSON matching a Pydantic schema. Used for extraction."""
    import outlines

    model = get_outlines_model()
    generator = outlines.generate.json(model, schema)  # type: ignore[attr-defined]
    return generator(prompt)


def llm_is_loaded() -> bool:
    """Check if the LLM model is loaded."""
    return _llm_model is not None


def llm_warmup() -> None:
    """Pre-load the model."""
    _ensure_llm_loaded()


# ── LLM Extraction ─────────────────────────────────────────────────────────

try:
    from pydantic import BaseModel as _PydanticBase
except ImportError:  # fallback for test environments without pydantic
    _PydanticBase = object  # type: ignore[assignment, misc]

EXTRACT_PROMPT = (
    "Extract structured information from this spoken note. "
    "key_points: main ideas stated. action_items: things to do. topics: subjects mentioned. "
    "Use empty lists if nothing relevant.\n\nText: {text}"
)


class Extraction(_PydanticBase):  # type: ignore[misc]
    key_points: list[str]
    action_items: list[str]
    topics: list[str]


def extract(text: str) -> Extraction:
    """Extract key points, action items, and topics from transcript text."""
    return generate_json(EXTRACT_PROMPT.format(text=text), Extraction)  # type: ignore[return-value]


def extract_summary(text: str) -> str | None:
    """Extract and format as a single-line summary. Returns None if nothing useful."""
    result = extract(text)
    parts = []
    if result.key_points:
        parts.append("; ".join(result.key_points))
    if result.action_items:
        parts.append("\u2192 " + "; ".join(result.action_items))
    return " | ".join(parts) if parts else None


# ── LLM Autocomplete ───────────────────────────────────────────────────────

AUTOCOMPLETE_PROMPT = """\
Complete the user's reply naturally. Output ONLY the completion text, nothing else.

Recent messages:
{context}

User is typing: {draft}"""

REPLY_PROMPT = """\
Suggest a brief reply to the last message. Output ONLY the reply text, nothing else.

Conversation:
{context}

Received: {last_message}

Reply:"""


def build_context(messages: list[dict], max_messages: int = 6) -> str:  # type: ignore[type-arg]
    """Format recent messages into context string."""
    recent = messages[-max_messages:]
    lines = []
    for msg in recent:
        sender = msg.get("sender", "?")
        body = msg.get("body", "").strip()
        if len(body) > 200:
            body = body[:200] + "..."
        lines.append(f"{sender}: {body}")
    return "\n".join(lines)


def autocomplete(
    draft: str = "",
    messages: list[dict] | None = None,  # type: ignore[type-arg]
    max_tokens: int = 32,
    temperature: float = 0.5,
    mode: str = "complete",
) -> str | None:
    """Suggest a completion or reply for the draft text."""
    if mode not in ("complete", "reply"):
        raise ValueError(f"Invalid mode: {mode!r}. Must be 'complete' or 'reply'.")

    if mode == "complete":
        if len(draft.strip()) < 3:
            return None
        context = build_context(messages) if messages else ""
        prompt = AUTOCOMPLETE_PROMPT.format(context=context, draft=draft)
        result = llm_complete(prompt, max_tokens=max_tokens, temperature=temperature)
        result = result.strip()
        return result if result else None

    # reply mode
    if not messages:
        return None
    last = messages[-1]
    last_body = last.get("body", "").strip()
    if not last_body:
        return None
    context = build_context(messages[:-1]) if len(messages) > 1 else ""
    prompt = REPLY_PROMPT.format(context=context, last_message=last_body)
    result = llm_complete(prompt, max_tokens=max_tokens, temperature=temperature)
    result = result.strip()
    return result if result else None
