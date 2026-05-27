#!/usr/bin/env python3
"""This tool automates LinkedIn DOM scraping via CDP and may violate LinkedIn's User Agreement §8.2. For personal-data export from your own account only. Disabled by default; set INBOX_ENABLE_LINKEDIN_SCRAPER=1 to enable."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(REPO_ROOT))

from track_data_export_browser import CdpConnection, CdpError  # noqa: E402

DEFAULT_CDP_URL = "http://127.0.0.1:9223"
DEFAULT_DB = (
    Path.home()
    / ".openhuman"
    / "users"
    / "local"
    / "workspace"
    / "linkedin_data"
    / "linkedin_data.db"
)

SCAN_JS = r"""
(() => {
  const textOf = (el) => (el && el.innerText ? el.innerText.trim() : "");
  const cleanLines = (text) => text.split(/\n+/).map((s) => s.trim()).filter(Boolean);
  const hashText = (text) => {
    let h = 2166136261;
    for (let i = 0; i < text.length; i += 1) {
      h ^= text.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return (h >>> 0).toString(16);
  };
  const normalizeUrl = (href) => {
    if (!href) return "";
    try { return new URL(href, location.href).toString().split("?")[0]; }
    catch (_err) { return String(href); }
  };
  const threadIdFromUrl = (url) => {
    const match = String(url || location.href).match(/\/messaging\/thread\/([^/?#]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  };
  const activeHeader =
    document.querySelector(".msg-entity-lockup__entity-title") ||
    document.querySelector(".msg-thread__link-to-profile") ||
    document.querySelector('[data-test-conversation-header]') ||
    document.querySelector("main header h2:not(.visually-hidden)") ||
    document.querySelector("main h2:not(.visually-hidden)") ||
    document.querySelector("main header");
  const activeName = (textOf(activeHeader).split("\n")[0] || "").trim();
  const activeProfileUrl = normalizeUrl(
    (activeHeader && activeHeader.querySelector('a[href*="/in/"]') || document.querySelector('main a[href*="/in/"]'))?.href
  );
  const activeThreadId = threadIdFromUrl(location.href) || `dom:${hashText(activeName || location.href)}`;

  const chatRows = Array.from(
    document.querySelectorAll(
      'a[href*="/messaging/thread/"], li.msg-conversation-listitem, [data-control-name="conversation_card"]'
    )
  )
    .map((row, index) => {
      const link = row.matches && row.matches("a") ? row : row.querySelector('a[href*="/messaging/thread/"]');
      const url = normalizeUrl(link ? link.href : "");
      const lines = cleanLines(textOf(row));
      const name = lines[0] || (link ? textOf(link) : "");
      return {
        index,
        threadId: threadIdFromUrl(url) || (name ? `dom:${hashText(name)}` : ""),
        displayName: name,
        profileUrl: normalizeUrl(row.querySelector('a[href*="/in/"]')?.href || ""),
        sourceUrl: url,
        text: lines.join("\n").slice(0, 1000),
      };
    })
    .filter((row) => row.threadId && row.displayName);

  const messageNodes = Array.from(
    document.querySelectorAll(
      'main li.msg-s-message-list__event, main [data-event-urn], main .msg-s-message-group__meta, main .msg-s-event-listitem'
    )
  );
  const messages = messageNodes
    .map((row) => {
      const lines = cleanLines(textOf(row));
      const bodyNode =
        row.querySelector(".msg-s-event-listitem__body") ||
        row.querySelector(".msg-s-message-group__message") ||
        row.querySelector('[dir="auto"]');
      const body = textOf(bodyNode) || lines.slice(1).join("\n");
      if (!body) return null;
      const senderNode =
        row.querySelector(".msg-s-message-group__name") ||
        row.querySelector(".msg-s-message-group__profile-link") ||
        row.querySelector('a[href*="/in/"]');
      const sender = textOf(senderNode).split("\n")[0] || "";
      const profileUrl = normalizeUrl(row.querySelector('a[href*="/in/"]')?.href || "");
      const messageId =
        row.getAttribute("data-event-urn") ||
        row.getAttribute("data-urn") ||
        `${activeThreadId}:${hashText([sender, body, lines.join("|")].join("|"))}`;
      const className = String(row.className || "");
      return {
        threadId: activeThreadId,
        messageId,
        sender: sender || (className.includes("msg-s-message-list__event--own") ? "Me" : activeName || "?"),
        senderProfileUrl: profileUrl,
        fromMe: className.includes("msg-s-message-list__event--own") || /(^|\n)(You|Me)(\n|$)/i.test(textOf(row)),
        body,
        timestampText: lines.find((line) => /\d{1,2}:\d{2}|am|pm|yesterday|today|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec/i.test(line)) || "",
        sourceUrl: location.href,
        activeChatName: activeName,
        activeProfileUrl,
      };
    })
    .filter(Boolean);

  return {
    url: location.href,
    title: document.title,
    activeChatName: activeName,
    activeProfileUrl,
    loginRequired: /sign in|join linkedin|email or phone|password/i.test(document.body.innerText || "") && !/messaging/i.test(location.href),
    chats: chatRows,
    messages,
  };
})()
"""


@dataclass
class BrowserPage:
    websocket_url: str
    url: str
    title: str


def utc_now_seconds() -> int:
    return int(datetime.now(UTC).timestamp())


def default_db_path() -> Path:
    return (
        Path(os.getenv("INBOX_OPENHUMAN_LINKEDIN_DB", "")).expanduser()
        if os.getenv("INBOX_OPENHUMAN_LINKEDIN_DB")
        else DEFAULT_DB
    )


def cdp_json(cdp_url: str, path: str) -> Any:
    with urllib.request.urlopen(f"{cdp_url.rstrip('/')}{path}", timeout=5) as response:  # nosec B310
        return json.loads(response.read().decode("utf-8"))


def find_linkedin_page(cdp_url: str) -> BrowserPage:
    pages = cdp_json(cdp_url, "/json")
    for page in pages:
        url = str(page.get("url", ""))
        if "linkedin.com/messaging" in url and page.get("webSocketDebuggerUrl"):
            return BrowserPage(
                websocket_url=str(page["webSocketDebuggerUrl"]),
                url=url,
                title=str(page.get("title", "")),
            )
    raise RuntimeError(
        f"No LinkedIn Messaging tab found at {cdp_url}. Open https://www.linkedin.com/messaging/ first."
    )


def open_linkedin_tab(cdp_url: str) -> None:
    encoded_url = urllib.parse.quote("https://www.linkedin.com/messaging/", safe=":/?&=%#")
    request = urllib.request.Request(f"{cdp_url.rstrip('/')}/json/new?{encoded_url}", method="PUT")
    with urllib.request.urlopen(request, timeout=5) as response:  # nosec B310
        response.read()


def evaluate_scan(conn: CdpConnection) -> dict[str, Any]:
    result = conn.command(
        "Runtime.evaluate",
        {
            "expression": SCAN_JS,
            "returnByValue": True,
            "awaitPromise": True,
        },
    )
    value = result.get("result", {}).get("value")
    if not isinstance(value, dict):
        raise RuntimeError("LinkedIn scan did not return an object")
    return value


def click_visible_thread(conn: CdpConnection, index: int) -> bool:
    expression = f"""
    (() => {{
      const rows = Array.from(document.querySelectorAll(
        'a[href*="/messaging/thread/"], li.msg-conversation-listitem, [data-control-name="conversation_card"]'
      )).filter((row) => {{
        const rect = row.getBoundingClientRect();
        return (row.innerText || '').trim() &&
          rect.width > 20 &&
          rect.height > 20 &&
          rect.bottom > 120 &&
          rect.top < window.innerHeight - 20;
      }});
      const row = rows[{index}];
      if (!row) return false;
      const rect = row.getBoundingClientRect();
      return {{
        x: Math.round(rect.left + Math.min(rect.width * 0.5, 180)),
        y: Math.round(rect.top + rect.height * 0.5),
      }};
    }})()
    """
    result = conn.command("Runtime.evaluate", {"expression": expression, "returnByValue": True})
    point = result.get("result", {}).get("value")
    if not isinstance(point, dict):
        return False
    x = int(point.get("x") or 0)
    y = int(point.get("y") or 0)
    if not x or not y:
        return False
    conn.command("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    conn.command(
        "Input.dispatchMouseEvent",
        {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1},
    )
    conn.command(
        "Input.dispatchMouseEvent",
        {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1},
    )
    return True


def scroll_thread_list(conn: CdpConnection) -> bool:
    expression = """
    (() => {
      const candidates = [
        document.querySelector('.msg-conversations-container__conversations-list'),
        document.querySelector('.msg-conversations-container__conversations-list-container'),
        document.querySelector('ul.msg-conversations-container__conversations-list'),
        document.querySelector('[aria-label*="conversation" i]'),
      ].filter(Boolean);
      const scrollers = candidates.concat(Array.from(document.querySelectorAll('aside, section, div')))
        .filter((el) => el && el.scrollHeight > el.clientHeight + 100)
        .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight));
      const el = scrollers[0];
      if (!el) return false;
      const before = el.scrollTop;
      el.scrollTop = Math.min(el.scrollHeight, el.scrollTop + Math.max(el.clientHeight * 0.85, 500));
      return el.scrollTop !== before;
    })()
    """
    result = conn.command("Runtime.evaluate", {"expression": expression, "returnByValue": True})
    return bool(result.get("result", {}).get("value"))


def scroll_active_thread(conn: CdpConnection) -> bool:
    expression = """
    (() => {
      const candidates = [
        document.querySelector('.msg-s-message-list--scroll-buffer'),
        document.querySelector('.msg-s-message-list'),
        document.querySelector('main .scrollable'),
      ].filter(Boolean);
      const scrollers = candidates.concat(Array.from(document.querySelectorAll('main div')))
        .filter((el) => el && el.scrollHeight > el.clientHeight + 80)
        .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight));
      const el = scrollers[0];
      if (!el) return false;
      const before = el.scrollTop;
      el.scrollTop = Math.max(0, el.scrollTop - Math.max(el.clientHeight * 0.9, 500));
      return el.scrollTop !== before;
    })()
    """
    result = conn.command("Runtime.evaluate", {"expression": expression, "returnByValue": True})
    return bool(result.get("result", {}).get("value"))


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS li_threads (
                account_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                profile_url TEXT NOT NULL DEFAULT '',
                last_message_ts INTEGER NOT NULL DEFAULT 0,
                message_count INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (account_id, thread_id)
            );
            CREATE TABLE IF NOT EXISTS li_messages (
                account_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                sender TEXT NOT NULL DEFAULT '',
                sender_profile_url TEXT,
                from_me INTEGER NOT NULL DEFAULT 0,
                body TEXT NOT NULL DEFAULT '',
                timestamp INTEGER NOT NULL DEFAULT 0,
                source_url TEXT,
                ingested_at INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (account_id, thread_id, message_id)
            );
            CREATE INDEX IF NOT EXISTS idx_li_msg_ts ON li_messages(account_id, thread_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_li_msg_body ON li_messages(account_id, body);
            """
        )


def parse_timestamp(value: Any) -> int:
    if isinstance(value, int):
        return value
    text = str(value or "").strip()
    if not text:
        return utc_now_seconds()
    if text.isdigit():
        return int(text)
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except ValueError:
        pass
    for fmt in ("%b %d, %Y, %I:%M %p", "%b %d, %Y", "%m/%d/%Y, %I:%M %p", "%m/%d/%Y"):
        try:
            return int(datetime.strptime(text, fmt).replace(tzinfo=UTC).timestamp())
        except ValueError:
            pass
    return utc_now_seconds()


def stable_message_id(message: dict[str, Any]) -> str:
    raw = str(message.get("messageId") or message.get("message_id") or "")
    if raw:
        return raw
    basis = json.dumps(
        [
            message.get("threadId") or message.get("thread_id") or "",
            message.get("sender", ""),
            message.get("timestamp") or message.get("timestampText") or "",
            message.get("body", ""),
        ],
        sort_keys=True,
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


GENERIC_THREAD_NAMES = {"conversation list", "messaging", "linkedin messaging", "messages"}
SELF_THREAD_NAMES = {
    name.strip().lower()
    for name in os.environ.get("INBOX_SELF_NAMES", "me,you").split(",")
    if name.strip()
}


def useful_thread_name(name: str) -> bool:
    normalized = " ".join(str(name or "").strip().lower().split())
    return bool(normalized) and normalized not in GENERIC_THREAD_NAMES


def useful_counterparty_name(name: str) -> bool:
    normalized = " ".join(str(name or "").strip().lower().split())
    return useful_thread_name(name) and normalized not in SELF_THREAD_NAMES


def write_scan(db_path: Path, scan: dict[str, Any], account_id: str) -> dict[str, int]:
    init_db(db_path)
    now = utc_now_seconds()
    threads_seen: dict[str, tuple[str, str, int]] = {}
    thread_message_counts: dict[str, int] = {}
    thread_names: dict[str, str] = {}
    thread_profile_urls: dict[str, str] = {}
    scan_threads = [c for c in scan.get("chats", []) if isinstance(c, dict)]
    for thread in scan_threads:
        thread_id = str(thread.get("threadId") or thread.get("thread_id") or "").strip()
        if not thread_id:
            continue
        display_name = str(thread.get("displayName") or thread.get("name") or thread_id)
        profile_url = str(thread.get("profileUrl") or thread.get("profile_url") or "")
        last_ts = int(thread.get("lastMessageTs") or thread.get("last_message_ts") or 0)
        thread_names[thread_id] = display_name
        thread_profile_urls[thread_id] = profile_url
        threads_seen[thread_id] = (display_name, profile_url, last_ts)
        thread_message_counts[thread_id] = int(thread.get("messageCount") or 0)
    messages = [m for m in scan.get("messages", []) if isinstance(m, dict)]
    counterparties: dict[str, str] = {}
    for message in messages:
        thread_id = str(message.get("threadId") or message.get("thread_id") or "dom:unknown")
        sender = str(message.get("sender") or "")
        if useful_counterparty_name(sender):
            counterparties.setdefault(thread_id, sender)
    with sqlite3.connect(db_path) as conn:
        for message in messages:
            thread_id = str(message.get("threadId") or message.get("thread_id") or "dom:unknown")
            raw_display_name = str(
                message.get("activeChatName") or thread_names.get(thread_id) or ""
            )
            sender = str(message.get("sender") or "")
            display_name = raw_display_name
            if not useful_counterparty_name(display_name):
                display_name = counterparties.get(thread_id) or thread_id
            profile_url = str(
                message.get("activeProfileUrl") or thread_profile_urls.get(thread_id) or ""
            )
            timestamp = int(message.get("timestamp") or 0) or parse_timestamp(
                message.get("timestampText") or ""
            )
            body = str(message.get("body") or "")
            message_id = stable_message_id(message)
            threads_seen[thread_id] = (
                display_name,
                profile_url,
                max(timestamp, threads_seen.get(thread_id, ("", "", 0))[2]),
            )
            thread_message_counts[thread_id] = thread_message_counts.get(thread_id, 0) + 1
            conn.execute(
                """
                INSERT INTO li_messages (
                    account_id, thread_id, message_id, sender, sender_profile_url, from_me,
                    body, timestamp, source_url, ingested_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, thread_id, message_id) DO UPDATE SET
                    sender=excluded.sender,
                    sender_profile_url=excluded.sender_profile_url,
                    from_me=excluded.from_me,
                    body=excluded.body,
                    timestamp=excluded.timestamp,
                    source_url=excluded.source_url,
                    ingested_at=excluded.ingested_at
                """,
                (
                    account_id,
                    thread_id,
                    message_id,
                    sender,
                    str(message.get("senderProfileUrl") or message.get("sender_profile_url") or "")
                    or None,
                    1 if message.get("fromMe") or message.get("from_me") else 0,
                    body,
                    timestamp,
                    str(
                        message.get("sourceUrl")
                        or message.get("source_url")
                        or scan.get("url")
                        or ""
                    )
                    or None,
                    now,
                ),
            )
        for thread_id, (display_name, profile_url, last_ts) in threads_seen.items():
            count = conn.execute(
                "SELECT COUNT(*) FROM li_messages WHERE account_id = ? AND thread_id = ?",
                (account_id, thread_id),
            ).fetchone()[0]
            count = max(int(count or 0), int(thread_message_counts.get(thread_id, 0) or 0))
            conn.execute(
                """
                INSERT INTO li_threads (
                    account_id, thread_id, display_name, profile_url,
                    last_message_ts, message_count, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, thread_id) DO UPDATE SET
                    display_name=excluded.display_name,
                    profile_url=excluded.profile_url,
                    last_message_ts=MAX(li_threads.last_message_ts, excluded.last_message_ts),
                    message_count=excluded.message_count,
                    updated_at=excluded.updated_at
                """,
                (account_id, thread_id, display_name, profile_url, last_ts, count, now),
            )
        conn.commit()
    return {"threads": len(threads_seen), "messages": len(messages)}


def run_index_sync() -> None:
    from message_index_store import MessageIndexStore
    from message_sync import sync_linkedin_incremental

    store = MessageIndexStore()
    stats = sync_linkedin_incremental(store)
    for account, count in stats.items():
        if count:
            store.rebuild_threads(source="linkedin", account=account)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan visible LinkedIn Messaging threads through Brave CDP into Inbox's LinkedIn store."
    )
    parser.add_argument("--cdp-url", default=DEFAULT_CDP_URL)
    parser.add_argument("--db", default="", help="Target linkedin_data.db path.")
    parser.add_argument("--account-id", default="brave-cdp")
    parser.add_argument(
        "--open-tab", action="store_true", help="Open linkedin.com/messaging through CDP first."
    )
    parser.add_argument(
        "--click-visible", type=int, default=0, help="Click and scan the first N visible threads."
    )
    parser.add_argument(
        "--scroll-pages",
        type=int,
        default=0,
        help="Scroll the LinkedIn conversation list and scan/click visible threads after each page.",
    )
    parser.add_argument(
        "--scroll-active-pages",
        type=int,
        default=0,
        help="Scroll the currently open conversation upward and scan after each page.",
    )
    parser.add_argument("--delay", type=float, default=1.0, help="Delay after clicking a thread.")
    parser.add_argument(
        "--sync-index", action="store_true", help="Also ingest the DB into .inbox_index.sqlite3."
    )
    return parser.parse_args()


def main() -> int:
    if not os.environ.get("INBOX_ENABLE_LINKEDIN_SCRAPER"):
        print(
            "LinkedIn scraper disabled. Set INBOX_ENABLE_LINKEDIN_SCRAPER=1 to enable. See ToS notice in module docstring.",
            file=sys.stderr,
        )
        sys.exit(2)
    args = parse_args()
    if args.open_tab:
        open_linkedin_tab(args.cdp_url)
        time.sleep(2)
    page = find_linkedin_page(args.cdp_url)
    db_path = Path(args.db).expanduser() if args.db else default_db_path()
    total = {"threads": 0, "messages": 0}
    clicked = 0
    scrolls = 0
    with CdpConnection(page.websocket_url, timeout=10) as conn:
        first_scan = evaluate_scan(conn)
        if first_scan.get("loginRequired"):
            print("LinkedIn is not signed in. Sign in through Brave, then rerun.")
            return 2
        scans = [first_scan]
        for _active_page in range(max(args.scroll_active_pages, 0)):
            if not scroll_active_thread(conn):
                break
            time.sleep(max(args.delay, 0))
            scans.append(evaluate_scan(conn))
        for _page in range(max(args.scroll_pages, 0) + 1):
            for index in range(max(args.click_visible, 0)):
                if click_visible_thread(conn, index):
                    clicked += 1
                    time.sleep(max(args.delay, 0))
                    for _active_page in range(max(args.scroll_active_pages, 0)):
                        if not scroll_active_thread(conn):
                            break
                        time.sleep(max(args.delay, 0))
                        scans.append(evaluate_scan(conn))
                    scans.append(evaluate_scan(conn))
            if not scroll_thread_list(conn):
                break
            scrolls += 1
            time.sleep(max(args.delay, 0))
            scans.append(evaluate_scan(conn))
        for scan in scans:
            written = write_scan(db_path, scan, args.account_id)
            total["threads"] += written["threads"]
            total["messages"] += written["messages"]
    if args.sync_index:
        run_index_sync()
    print(
        json.dumps(
            {"clicked": clicked, "db_path": str(db_path), "scrolls": scrolls, **total},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (CdpError, OSError, RuntimeError) as exc:
        print(f"linkedin scanner failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
