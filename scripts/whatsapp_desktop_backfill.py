#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

from whatsapp_web_scanner import default_db_path, run_index_sync, write_scan  # noqa: E402

from services import (  # noqa: E402
    whatsapp_accessibility_contacts,
    whatsapp_accessibility_thread,
    whatsapp_contacts_all,
    whatsapp_thread_full,
)


def _message_id(chat_id: str, sender: str, body: str, ts: int) -> str:
    basis = f"{chat_id}:{sender}:{body}:{ts}"
    return "desktop:" + "".join(ch if ch.isalnum() or ch in "_.:-" else "_" for ch in basis)[:180]


def build_scan(max_pages: int, max_chats: int, max_loads: int, limit: int) -> dict:
    contacts = whatsapp_contacts_all(max_pages=max_pages)
    if not contacts:
        contacts = whatsapp_accessibility_contacts(limit=max_chats)
    selected = contacts[:max_chats]
    messages = []
    chats = []
    for contact in selected:
        chat_id = contact.guid or contact.id or contact.name
        chats.append(
            {
                "chatId": chat_id,
                "name": contact.name,
                "lastMessageTs": int(contact.last_ts.timestamp()) if contact.last_ts else 0,
                "messageCount": 0,
            }
        )
        if max_loads > 0:
            thread = whatsapp_thread_full(contact.name, max_loads=max_loads, limit=limit)
        else:
            thread = whatsapp_accessibility_thread(contact.name, limit=limit)
        for msg in thread:
            ts = int(msg.ts.timestamp()) if msg.ts else 0
            body = msg.body.strip()
            if not body:
                continue
            messages.append(
                {
                    "chatId": chat_id,
                    "messageId": _message_id(chat_id, msg.sender, body, ts),
                    "sender": msg.sender,
                    "senderJid": "",
                    "fromMe": msg.is_me,
                    "body": body,
                    "timestamp": ts,
                    "messageType": "chat",
                    "source": "whatsapp-desktop-ax",
                    "activeChatName": contact.name,
                }
            )
    return {
        "source": "whatsapp-desktop-ax",
        "chats": chats,
        "messages": messages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill WhatsApp Desktop visible chats via AX.")
    parser.add_argument("--db", default="", help="Target whatsapp_data.db path.")
    parser.add_argument("--account-id", default="brave-cdp")
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--max-chats", type=int, default=25)
    parser.add_argument("--max-loads", type=int, default=0)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--sync-index", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db).expanduser() if args.db else default_db_path()
    scan = build_scan(args.max_pages, args.max_chats, args.max_loads, args.limit)
    written = write_scan(db_path, scan, args.account_id)
    if args.sync_index:
        run_index_sync()
    print(json.dumps({"db_path": str(db_path), **written}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
