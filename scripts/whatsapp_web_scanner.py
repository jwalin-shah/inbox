#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
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
    / "whatsapp_data"
    / "whatsapp_data.db"
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
  const parseDataId = (dataId) => {
    const parts = String(dataId || "").split("_");
    if (parts.length >= 3 && /@(?:c|g)\.us$/.test(parts[1])) {
      return { fromMe: parts[0] === "true", chatId: parts[1], messageId: parts.slice(2).join("_") };
    }
    return { fromMe: false, chatId: "", messageId: String(dataId || "") };
  };
  const parsePrePlain = (value) => {
    const raw = String(value || "").trim();
    const match = raw.match(/^\[([^\]]+)\]\s*([^:]+):\s*/);
    return { raw, timestampText: match ? match[1] : "", sender: match ? match[2].trim() : "" };
  };
  const activeHeader =
    document.querySelector('header [title]') ||
    document.querySelector('header span[dir="auto"]') ||
    document.querySelector('header span[dir="ltr"]') ||
    document.querySelector('header');
  const activeChatName = textOf(activeHeader).split("\n")[0] || "";
  const chatFallbackId = activeChatName ? `dom:${hashText(activeChatName)}:${activeChatName}` : "dom:unknown";

  const chatRows = Array.from(
    document.querySelectorAll(
      '[aria-label="Chat list"] [role="listitem"], [data-testid="cell-frame-container"], div[role="grid"] div[role="row"]'
    )
  )
    .map((row, index) => {
      const lines = cleanLines(textOf(row));
      return {
        index,
        name: lines[0] || "",
        snippet: lines.slice(1).join(" | ").slice(0, 240),
        text: lines.join("\n").slice(0, 1000),
      };
    })
    .filter((row) => row.name);

  const messages = Array.from(document.querySelectorAll("[data-id]"))
    .map((row) => {
      const dataId = row.getAttribute("data-id") || "";
      const parsed = parseDataId(dataId);
      const preEl = row.querySelector("[data-pre-plain-text]");
      const pre = parsePrePlain(preEl ? preEl.getAttribute("data-pre-plain-text") : "");
      const spans = Array.from(row.querySelectorAll('span.selectable-text, span[dir="ltr"], span[dir="rtl"]'))
        .map(textOf)
        .filter(Boolean)
        .filter((s) => !/^\d{1,2}:\d{2}\s*(?:AM|PM)?$/i.test(s));
      const body = spans.sort((a, b) => b.length - a.length)[0] || "";
      if (!body && !pre.raw) return null;
      return {
        dataId,
        chatId: parsed.chatId || chatFallbackId,
        messageId: parsed.messageId || hashText(`${chatFallbackId}:${pre.raw}:${body}`),
        fromMe: parsed.fromMe || /^You$|^Me$/i.test(pre.sender),
        sender: pre.sender || (parsed.fromMe ? "Me" : activeChatName || "?"),
        body,
        timestampText: pre.timestampText,
        activeChatName,
      };
    })
    .filter(Boolean);

  return {
    url: location.href,
    title: document.title,
    activeChatName,
    loginRequired: /use whatsapp on your computer|link a device|qr code/i.test(document.body.innerText || ""),
    chats: chatRows,
    messages,
  };
})()
"""


def idb_scan_expression(limit: int) -> str:
    return f"""
(async () => {{
  const LIMIT = {max(int(limit), 1)};
  const jid = (value) => {{
    if (!value) return "";
    if (typeof value === "string") return value;
    if (value._serialized) return value._serialized;
    if (value.user && value.server) return `${{value.user}}@${{value.server}}`;
    return "";
  }};
  const cleanName = (value) => String(value || "").trim();
  const parseMessageId = (value) => {{
    const raw = String(value || "");
    const parts = raw.split("_");
    return {{
      raw,
      fromMe: parts[0] === "true",
      chatId: parts.length >= 3 ? parts[1] : "",
    }};
  }};
  const openDb = () => new Promise((resolve, reject) => {{
    const request = indexedDB.open("model-storage");
    request.onerror = () => reject(request.error || new Error("open model-storage failed"));
    request.onsuccess = () => resolve(request.result);
  }});
  const readStore = (db, storeName, maxRows) => new Promise((resolve) => {{
    if (!Array.from(db.objectStoreNames).includes(storeName)) {{
      resolve([]);
      return;
    }}
    const rows = [];
    const tx = db.transaction(storeName, "readonly");
    const store = tx.objectStore(storeName);
    const request = store.openCursor(null, "prev");
    request.onerror = () => resolve(rows);
    request.onsuccess = () => {{
      const cursor = request.result;
      if (!cursor || rows.length >= maxRows) {{
        resolve(rows);
        return;
      }}
      rows.push({{key: cursor.key, value: cursor.value}});
      cursor.continue();
    }};
  }});
  const textFieldNames = [
    "body",
    "text",
    "caption",
    "displayText",
    "display",
    "messageText",
    "formattedText",
    "formattedBody",
    "conversation",
    "selectedDisplayText",
    "matchedText",
    "title",
    "description",
  ];
  const textField = (value, seen = new Set(), depth = 0) => {{
    if (!value || depth > 5) return "";
    if (typeof value === "string") return value.trim();
    if (typeof value !== "object") return "";
    if (seen.has(value)) return "";
    seen.add(value);
    for (const field of textFieldNames) {{
      const text = String(value[field] || "").trim();
      if (text) return text;
    }}
    for (const field of ["message", "content", "quotedMsg", "quotedStanza", "extendedTextMessage", "pollCreationMessage"]) {{
      const text = textField(value[field], seen, depth + 1);
      if (text) return text;
    }}
    for (const nested of Object.values(value)) {{
      if (!nested || typeof nested !== "object") continue;
      const text = textField(nested, seen, depth + 1);
      if (text) return text;
    }}
    return "";
  }};

  const db = await openDb();
  try {{
    const chatNames = new Map();
    const lastMessageTs = new Map();
    const messageCounts = new Map();
    const rememberChat = (chatId, name, ts) => {{
      if (!chatId) return;
      const prior = chatNames.get(chatId) || "";
      chatNames.set(chatId, cleanName(name) || prior || chatId);
      if (Number(ts || 0) > Number(lastMessageTs.get(chatId) || 0)) {{
        lastMessageTs.set(chatId, Number(ts || 0));
      }}
    }};

    for (const row of await readStore(db, "chat", LIMIT)) {{
      const value = row.value || {{}};
      const chatId = jid(value.id) || String(row.key || "");
      const preview = value.chatlistPreview || {{}};
      rememberChat(
        chatId,
        value.name || value.formattedTitle || value.displayName || value.shortName || value.pushname || "",
        value.t || preview.t || 0
      );
    }}
    for (const row of await readStore(db, "contact", LIMIT)) {{
      const value = row.value || {{}};
      const contactId = jid(value.id) || jid(value.phoneNumber) || String(row.key || "");
      rememberChat(contactId, value.name || value.shortName || value.pushname || value.formattedName || "", 0);
    }}
    for (const row of await readStore(db, "group-metadata", LIMIT)) {{
      const value = row.value || {{}};
      const groupId = jid(value.id) || String(row.key || "");
      rememberChat(groupId, value.subject || value.name || "", 0);
    }}

    const messages = [];
    for (const row of await readStore(db, "message", LIMIT)) {{
      const value = row.value || {{}};
      const parsed = parseMessageId(value.id || row.key || "");
      const from = jid(value.from);
      const to = jid(value.to);
      const author = jid(value.author);
      const chatId = to || parsed.chatId || from;
      if (!chatId) continue;
      const timestamp = Number(value.t || value.timestamp || 0);
      const body = textField(value);
      const fromMe = Boolean(value.fromMe || parsed.fromMe);
      rememberChat(chatId, chatNames.get(chatId) || chatId, timestamp);
      messageCounts.set(chatId, Number(messageCounts.get(chatId) || 0) + 1);
      messages.push({{
        chatId,
        messageId: parsed.raw || String(row.key || ""),
        sender: fromMe ? "Me" : (author || from || chatNames.get(chatId) || "?"),
        senderJid: author || from || "",
        fromMe,
        body,
        timestamp,
        messageType: String(value.type || "chat"),
        source: "brave-cdp-idb",
      }});
    }}

    const chats = Array.from(chatNames.entries()).map(([chatId, name]) => ({{
      chatId,
      name,
      lastMessageTs: Number(lastMessageTs.get(chatId) || 0),
      messageCount: Number(messageCounts.get(chatId) || 0),
    }}));

    return {{
      url: location.href,
      title: document.title,
      loginRequired: /use whatsapp on your computer|link a device|qr code/i.test(document.body.innerText || ""),
      source: "idb",
      chats,
      messages,
    }};
  }} finally {{
    db.close();
  }}
}})()
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
        Path(os.getenv("INBOX_OPENHUMAN_WHATSAPP_DB", "")).expanduser()
        if os.getenv("INBOX_OPENHUMAN_WHATSAPP_DB")
        else DEFAULT_DB
    )


def cdp_json(cdp_url: str, path: str) -> Any:
    with urllib.request.urlopen(f"{cdp_url.rstrip('/')}{path}", timeout=5) as response:  # nosec B310
        return json.loads(response.read().decode("utf-8"))


def find_whatsapp_page(cdp_url: str) -> BrowserPage:
    pages = cdp_json(cdp_url, "/json")
    for page in pages:
        url = str(page.get("url", ""))
        if "web.whatsapp.com" in url and page.get("webSocketDebuggerUrl"):
            return BrowserPage(
                websocket_url=str(page["webSocketDebuggerUrl"]),
                url=url,
                title=str(page.get("title", "")),
            )
    raise RuntimeError(
        f"No WhatsApp Web tab found at {cdp_url}. Run scripts/open_whatsapp_scanner_browser.sh first."
    )


def open_whatsapp_tab(cdp_url: str) -> None:
    encoded_url = urllib.parse.quote("https://web.whatsapp.com/", safe=":/?&=%#")
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
        raise RuntimeError("WhatsApp scan did not return an object")
    return value


def try_evaluate_scan(conn: CdpConnection) -> dict[str, Any] | None:
    try:
        return evaluate_scan(conn)
    except RuntimeError:
        return None


def evaluate_idb_scan(conn: CdpConnection, limit: int) -> dict[str, Any]:
    result = conn.command(
        "Runtime.evaluate",
        {
            "expression": idb_scan_expression(limit),
            "returnByValue": True,
            "awaitPromise": True,
        },
    )
    value = result.get("result", {}).get("value")
    if not isinstance(value, dict):
        raise RuntimeError("WhatsApp IndexedDB scan did not return an object")
    return value


def click_visible_chat(conn: CdpConnection, index: int) -> bool:
    expression = f"""
    (() => {{
      const rows = Array.from(document.querySelectorAll(
        '[aria-label="Chat list"] [role="listitem"], [data-testid="cell-frame-container"], div[role="grid"] div[role="row"]'
      )).filter((row) => (row.innerText || '').trim());
      const row = rows[{index}];
      if (!row) return false;
      row.scrollIntoView({{block: 'center'}});
      const rect = row.getBoundingClientRect();
      return {{
        x: rect.left + Math.min(Math.max(rect.width / 2, 24), rect.width - 8),
        y: rect.top + Math.min(Math.max(rect.height / 2, 8), rect.height - 8),
      }};
    }})()
    """
    result = conn.command("Runtime.evaluate", {"expression": expression, "returnByValue": True})
    point = result.get("result", {}).get("value")
    if not isinstance(point, dict):
        return False
    x = float(point.get("x") or 0)
    y = float(point.get("y") or 0)
    if x <= 0 or y <= 0:
        return False
    conn.command("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    conn.command(
        "Input.dispatchMouseEvent",
        {
            "type": "mousePressed",
            "x": x,
            "y": y,
            "button": "left",
            "buttons": 1,
            "clickCount": 1,
        },
    )
    conn.command(
        "Input.dispatchMouseEvent",
        {
            "type": "mouseReleased",
            "x": x,
            "y": y,
            "button": "left",
            "buttons": 0,
            "clickCount": 1,
        },
    )
    return True


def scroll_chat_list(conn: CdpConnection) -> bool:
    expression = """
    (() => {
      const list =
        document.querySelector('[aria-label="Chat list"]') ||
        document.querySelector('div[role="grid"]') ||
        document.querySelector('[data-testid="chat-list"]');
      if (!list) return false;
      const before = list.scrollTop;
      list.scrollTop = before + Math.max(list.clientHeight || 700, 700);
      return list.scrollTop !== before;
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
            CREATE TABLE IF NOT EXISTS wa_chats (
                account_id TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                is_group INTEGER NOT NULL DEFAULT 0,
                last_message_ts INTEGER NOT NULL DEFAULT 0,
                message_count INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (account_id, chat_id)
            );
            CREATE TABLE IF NOT EXISTS wa_messages (
                account_id TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                sender TEXT NOT NULL DEFAULT '',
                sender_jid TEXT,
                from_me INTEGER NOT NULL DEFAULT 0,
                body TEXT NOT NULL DEFAULT '',
                timestamp INTEGER NOT NULL DEFAULT 0,
                message_type TEXT,
                source TEXT NOT NULL DEFAULT '',
                ingested_at INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (account_id, chat_id, message_id)
            );
            CREATE INDEX IF NOT EXISTS idx_wa_msg_ts ON wa_messages(account_id, chat_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_wa_msg_body ON wa_messages(account_id, body);
            """
        )


def parse_timestamp(value: str) -> int:
    text = value.strip()
    if not text:
        return utc_now_seconds()
    for fmt in ("%I:%M %p, %m/%d/%Y", "%H:%M, %m/%d/%Y", "%I:%M %p, %d/%m/%Y", "%H:%M, %d/%m/%Y"):
        try:
            return int(datetime.strptime(text, fmt).replace(tzinfo=UTC).timestamp())
        except ValueError:
            pass
    return utc_now_seconds()


MESSAGE_BODY_FIELDS = (
    "body",
    "text",
    "caption",
    "displayText",
    "display",
    "messageText",
    "formattedText",
    "formattedBody",
    "conversation",
    "selectedDisplayText",
    "matchedText",
    "title",
    "description",
)


def message_body(message: dict[str, Any]) -> str:
    nested_fields = (
        "message",
        "content",
        "quotedMsg",
        "quotedStanza",
        "extendedTextMessage",
        "pollCreationMessage",
    )

    def extract(value: Any, seen: set[int], depth: int) -> str:
        if value is None or depth > 5:
            return ""
        if isinstance(value, str):
            return value.strip()
        if not isinstance(value, dict):
            if isinstance(value, list | tuple):
                for item in value:
                    if not isinstance(item, dict | list | tuple):
                        continue
                    text = extract(item, seen, depth + 1)
                    if text:
                        return text
            return ""
        obj_id = id(value)
        if obj_id in seen:
            return ""
        seen.add(obj_id)
        for field in MESSAGE_BODY_FIELDS:
            text = extract(value.get(field), seen, depth + 1)
            if text:
                return text
        for field in nested_fields:
            text = extract(value.get(field), seen, depth + 1)
            if text:
                return text
        for item in value.values():
            if not isinstance(item, dict | list | tuple):
                continue
            text = extract(item, seen, depth + 1)
            if text:
                return text
        return ""

    for field in MESSAGE_BODY_FIELDS:
        value = message.get(field)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return extract(message, set(), 0)


def stable_message_id(message: dict[str, Any]) -> str:
    raw = str(message.get("messageId") or "")
    if raw:
        return raw
    basis = json.dumps(
        [
            message.get("chatId", ""),
            message.get("sender", ""),
            message.get("timestampText", ""),
            message_body(message),
        ],
        sort_keys=True,
    )
    return re.sub(r"[^a-zA-Z0-9_.:-]", "_", basis)[:180]


def write_scan(db_path: Path, scan: dict[str, Any], account_id: str) -> dict[str, int]:
    init_db(db_path)
    now = utc_now_seconds()
    chats_seen: dict[str, tuple[str, int]] = {}
    chat_message_counts: dict[str, int] = {}
    chat_names: dict[str, str] = {}
    scan_chats = [c for c in scan.get("chats", []) if isinstance(c, dict)]
    for chat in scan_chats:
        chat_id = str(chat.get("chatId") or "").strip()
        if not chat_id:
            continue
        display_name = str(chat.get("name") or chat.get("displayName") or chat_id)
        last_ts = int(chat.get("lastMessageTs") or 0)
        chat_names[chat_id] = display_name
        chats_seen[chat_id] = (display_name, last_ts)
        chat_message_counts[chat_id] = int(chat.get("messageCount") or 0)
    messages = [m for m in scan.get("messages", []) if isinstance(m, dict)]
    with sqlite3.connect(db_path) as conn:
        for message in messages:
            chat_id = str(message.get("chatId") or "dom:unknown")
            display_name = str(message.get("activeChatName") or chat_names.get(chat_id) or chat_id)
            timestamp = int(message.get("timestamp") or 0) or parse_timestamp(
                str(message.get("timestampText") or "")
            )
            body = message_body(message)
            message_id = stable_message_id(message)
            chats_seen[chat_id] = (
                display_name,
                max(timestamp, chats_seen.get(chat_id, ("", 0))[1]),
            )
            chat_message_counts[chat_id] = chat_message_counts.get(chat_id, 0) + 1
            conn.execute(
                """
                INSERT INTO wa_messages (
                    account_id, chat_id, message_id, sender, sender_jid, from_me, body,
                    timestamp, message_type, source, ingested_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, chat_id, message_id) DO UPDATE SET
                    sender=excluded.sender,
                    from_me=excluded.from_me,
                    body=CASE
                        WHEN excluded.body != '' THEN excluded.body
                        ELSE wa_messages.body
                    END,
                    timestamp=excluded.timestamp,
                    message_type=excluded.message_type,
                    source=excluded.source,
                    ingested_at=excluded.ingested_at
                """,
                (
                    account_id,
                    chat_id,
                    message_id,
                    str(message.get("sender") or ""),
                    str(message.get("senderJid") or "") or None,
                    1 if message.get("fromMe") else 0,
                    body,
                    timestamp,
                    str(message.get("messageType") or "chat"),
                    str(message.get("source") or scan.get("source") or "brave-cdp-dom"),
                    now,
                ),
            )
        for chat_id, (display_name, last_ts) in chats_seen.items():
            count = conn.execute(
                "SELECT COUNT(*) FROM wa_messages WHERE account_id = ? AND chat_id = ?",
                (account_id, chat_id),
            ).fetchone()[0]
            count = max(int(count or 0), int(chat_message_counts.get(chat_id, 0) or 0))
            conn.execute(
                """
                INSERT INTO wa_chats (
                    account_id, chat_id, display_name, is_group, last_message_ts, message_count, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, chat_id) DO UPDATE SET
                    display_name=excluded.display_name,
                    last_message_ts=MAX(wa_chats.last_message_ts, excluded.last_message_ts),
                    message_count=excluded.message_count,
                    updated_at=excluded.updated_at
                """,
                (
                    account_id,
                    chat_id,
                    display_name,
                    1 if chat_id.endswith("@g.us") else 0,
                    last_ts,
                    count,
                    now,
                ),
            )
        conn.commit()
    return {"chats": len(chats_seen), "messages": len(messages)}


def run_index_sync() -> None:
    from message_index_store import MessageIndexStore
    from message_sync import sync_whatsapp_incremental

    store = MessageIndexStore()
    stats = sync_whatsapp_incremental(store)
    for account, count in stats.items():
        if count:
            store.rebuild_threads(source="whatsapp", account=account)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan visible WhatsApp Web chats through Brave CDP into Inbox's WhatsApp store."
    )
    parser.add_argument("--cdp-url", default=DEFAULT_CDP_URL)
    parser.add_argument("--db", default="", help="Target whatsapp_data.db path.")
    parser.add_argument("--account-id", default="brave-cdp")
    parser.add_argument(
        "--open-tab", action="store_true", help="Open web.whatsapp.com through CDP first."
    )
    parser.add_argument(
        "--click-visible", type=int, default=0, help="Click and scan the first N visible chats."
    )
    parser.add_argument(
        "--scroll-pages",
        type=int,
        default=0,
        help="After each visible-click pass, scroll the chat list this many pages and scan again.",
    )
    parser.add_argument("--delay", type=float, default=1.0, help="Delay after clicking a chat.")
    parser.add_argument(
        "--idb", action="store_true", help="Read WhatsApp Web's IndexedDB model-storage DB."
    )
    parser.add_argument(
        "--idb-limit", type=int, default=5000, help="Maximum rows per IndexedDB store."
    )
    parser.add_argument(
        "--sync-index", action="store_true", help="Also ingest the DB into .inbox_index.sqlite3."
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.open_tab:
        open_whatsapp_tab(args.cdp_url)
        time.sleep(2)
    page = find_whatsapp_page(args.cdp_url)
    db_path = Path(args.db).expanduser() if args.db else default_db_path()
    total = {"chats": 0, "messages": 0}
    with CdpConnection(page.websocket_url, timeout=10) as conn:
        if args.idb:
            idb_scan = evaluate_idb_scan(conn, args.idb_limit)
            if idb_scan.get("loginRequired"):
                print("WhatsApp Web is not paired yet. Pair the QR code in Brave, then rerun.")
                return 2
            written = write_scan(db_path, idb_scan, args.account_id)
            total["chats"] += written["chats"]
            total["messages"] += written["messages"]
        first_scan = evaluate_scan(conn)
        if first_scan.get("loginRequired"):
            print("WhatsApp Web is not paired yet. Pair the QR code in Brave, then rerun.")
            return 2
        scans = [first_scan]
        for page in range(max(args.scroll_pages, 0) + 1):
            for index in range(max(args.click_visible, 0)):
                if not click_visible_chat(conn, index):
                    continue
                time.sleep(max(args.delay, 0))
                scan = try_evaluate_scan(conn)
                if scan:
                    scans.append(scan)
            if page < max(args.scroll_pages, 0):
                if not scroll_chat_list(conn):
                    break
                time.sleep(max(args.delay, 0))
                scan = try_evaluate_scan(conn)
                if scan:
                    scans.append(scan)
        for scan in scans:
            written = write_scan(db_path, scan, args.account_id)
            total["chats"] += written["chats"]
            total["messages"] += written["messages"]
    if args.sync_index:
        run_index_sync()
    print(json.dumps({"db_path": str(db_path), **total}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (CdpError, OSError, RuntimeError) as exc:
        print(f"whatsapp scanner failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
