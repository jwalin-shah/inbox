#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_DB = Path.home() / ".wacli" / "wacli.db"
DEFAULT_DEST_DB = (
    Path.home()
    / ".openhuman"
    / "users"
    / "local"
    / "workspace"
    / "whatsapp_data"
    / "whatsapp_data.db"
)


def init_dest_db(db_path: Path) -> None:
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
            CREATE INDEX IF NOT EXISTS idx_wa_msg_ts
                ON wa_messages(account_id, chat_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_wa_msg_body
                ON wa_messages(account_id, body);
            """
        )


def non_placeholder(value: object) -> str:
    text = str(value or "").strip()
    if text.lower() in {"", "(message)", "message"}:
        return ""
    return text


def message_body(row: sqlite3.Row) -> str:
    for key in ("text", "media_caption", "filename", "display_text"):
        value = non_placeholder(row[key])
        if value:
            return value
    return ""


def message_type(row: sqlite3.Row) -> str:
    media_type = non_placeholder(row["media_type"])
    return media_type or "chat"


def import_wacli(
    source_db: Path,
    dest_db: Path,
    *,
    account_id: str,
    dry_run: bool,
) -> dict[str, int]:
    if not source_db.exists():
        raise FileNotFoundError(f"wacli database not found: {source_db}")

    init_dest_db(dest_db)
    now = int(time.time())

    source = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    dest = sqlite3.connect(dest_db)
    try:
        chats = source.execute(
            """
            SELECT
                c.jid,
                c.kind,
                COALESCE(NULLIF(c.name, ''), c.jid) AS display_name,
                COALESCE(c.last_message_ts, 0) AS last_message_ts,
                COALESCE(m.message_count, 0) AS message_count,
                COALESCE(m.last_ts, 0) AS last_ts
            FROM chats c
            LEFT JOIN (
                SELECT chat_jid, COUNT(*) AS message_count, MAX(ts) AS last_ts
                FROM messages
                GROUP BY chat_jid
            ) m ON m.chat_jid = c.jid
            ORDER BY c.jid
            """
        ).fetchall()
        messages = source.execute(
            """
            SELECT
                chat_jid,
                chat_name,
                msg_id,
                sender_jid,
                sender_name,
                ts,
                from_me,
                text,
                display_text,
                media_type,
                media_caption,
                filename
            FROM messages
            ORDER BY chat_jid, ts, msg_id
            """
        ).fetchall()

        text_messages = 0
        if not dry_run:
            for chat in chats:
                last_ts = int(chat["last_ts"] or chat["last_message_ts"] or 0)
                dest.execute(
                    """
                    INSERT INTO wa_chats (
                        account_id, chat_id, display_name, is_group, last_message_ts,
                        message_count, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(account_id, chat_id) DO UPDATE SET
                        display_name=excluded.display_name,
                        is_group=excluded.is_group,
                        last_message_ts=MAX(wa_chats.last_message_ts, excluded.last_message_ts),
                        message_count=excluded.message_count,
                        updated_at=excluded.updated_at
                    """,
                    (
                        account_id,
                        chat["jid"],
                        chat["display_name"],
                        1 if str(chat["kind"] or "") == "group" else 0,
                        last_ts,
                        int(chat["message_count"] or 0),
                        now,
                    ),
                )

            for row in messages:
                body = message_body(row)
                if body:
                    text_messages += 1
                sender = "Me" if int(row["from_me"] or 0) else non_placeholder(row["sender_name"])
                if not sender:
                    sender = non_placeholder(row["sender_jid"]) or non_placeholder(row["chat_name"])
                dest.execute(
                    """
                    INSERT INTO wa_messages (
                        account_id, chat_id, message_id, sender, sender_jid, from_me,
                        body, timestamp, message_type, source, ingested_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(account_id, chat_id, message_id) DO UPDATE SET
                        sender=excluded.sender,
                        sender_jid=excluded.sender_jid,
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
                        row["chat_jid"],
                        row["msg_id"],
                        sender,
                        non_placeholder(row["sender_jid"]) or None,
                        int(row["from_me"] or 0),
                        body,
                        int(row["ts"] or 0),
                        message_type(row),
                        "wacli",
                        now,
                    ),
                )
            dest.commit()
        else:
            text_messages = sum(1 for row in messages if message_body(row))

        return {
            "source_chats": len(chats),
            "source_messages": len(messages),
            "source_text_messages": text_messages,
            "dry_run": 1 if dry_run else 0,
        }
    finally:
        source.close()
        dest.close()


def sync_index() -> None:
    subprocess.run(
        ["uv", "run", "python", "message_sync.py", "whatsapp-bootstrap"],
        cwd=ROOT,
        check=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import the local wacli WhatsApp archive into OpenHuman's WhatsApp store."
    )
    parser.add_argument("--source-db", type=Path, default=DEFAULT_SOURCE_DB)
    parser.add_argument("--dest-db", type=Path, default=DEFAULT_DEST_DB)
    parser.add_argument("--account-id", default="wacli")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sync-index", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    stats = import_wacli(
        args.source_db.expanduser(),
        args.dest_db.expanduser(),
        account_id=args.account_id,
        dry_run=args.dry_run,
    )
    print(stats)
    if args.sync_index and not args.dry_run:
        sync_index()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
