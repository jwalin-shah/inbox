#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_DB = ROOT / ".inbox_index.sqlite3"
WA_DB = (
    Path.home()
    / ".openhuman"
    / "users"
    / "local"
    / "workspace"
    / "whatsapp_data"
    / "whatsapp_data.db"
)
LI_DB = (
    Path.home()
    / ".openhuman"
    / "users"
    / "local"
    / "workspace"
    / "linkedin_data"
    / "linkedin_data.db"
)


def scalar(db: Path, sql: str) -> int:
    if not db.exists():
        return 0
    with sqlite3.connect(db) as conn:
        value = conn.execute(sql).fetchone()[0]
    return int(value or 0)


def main() -> int:
    report = {
        "whatsapp": {
            "source_chats": scalar(WA_DB, "SELECT COUNT(*) FROM wa_chats"),
            "source_chats_with_message_rows": scalar(
                WA_DB, "SELECT COUNT(DISTINCT chat_id) FROM wa_messages"
            ),
            "source_chats_with_text": scalar(
                WA_DB,
                "SELECT COUNT(DISTINCT chat_id) FROM wa_messages WHERE LENGTH(TRIM(body)) > 0",
            ),
            "source_text_messages": scalar(
                WA_DB, "SELECT COUNT(*) FROM wa_messages WHERE LENGTH(TRIM(body)) > 0"
            ),
            "indexed_threads": scalar(
                INDEX_DB, "SELECT COUNT(*) FROM threads WHERE source = 'whatsapp'"
            ),
            "indexed_messages": scalar(
                INDEX_DB, "SELECT COUNT(*) FROM items WHERE source = 'whatsapp'"
            ),
        },
        "linkedin": {
            "source_threads": scalar(LI_DB, "SELECT COUNT(*) FROM li_threads"),
            "source_threads_with_message_rows": scalar(
                LI_DB, "SELECT COUNT(DISTINCT thread_id) FROM li_messages"
            ),
            "source_threads_with_text": scalar(
                LI_DB,
                "SELECT COUNT(DISTINCT thread_id) FROM li_messages WHERE LENGTH(TRIM(body)) > 0",
            ),
            "source_text_messages": scalar(
                LI_DB, "SELECT COUNT(*) FROM li_messages WHERE LENGTH(TRIM(body)) > 0"
            ),
            "indexed_threads": scalar(
                INDEX_DB, "SELECT COUNT(*) FROM threads WHERE source = 'linkedin'"
            ),
            "indexed_messages": scalar(
                INDEX_DB, "SELECT COUNT(*) FROM items WHERE source = 'linkedin'"
            ),
        },
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
