from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "import_wacli_to_openhuman.py"
SPEC = importlib.util.spec_from_file_location("import_wacli_to_openhuman", SCRIPT)
assert SPEC and SPEC.loader
import_wacli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(import_wacli)


def create_wacli_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE chats (
                jid TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                name TEXT,
                last_message_ts INTEGER
            );
            CREATE TABLE messages (
                chat_jid TEXT NOT NULL,
                chat_name TEXT,
                msg_id TEXT NOT NULL,
                sender_jid TEXT,
                sender_name TEXT,
                ts INTEGER,
                from_me INTEGER,
                text TEXT,
                display_text TEXT,
                media_type TEXT,
                media_caption TEXT,
                filename TEXT
            );
            INSERT INTO chats VALUES ('123@s.whatsapp.net', 'dm', 'Nitin', 100);
            INSERT INTO messages VALUES (
                '123@s.whatsapp.net', 'Nitin', 'm1', '123@s.whatsapp.net', 'Nitin',
                100, 0, 'real body', '(message)', '', '', ''
            );
            INSERT INTO messages VALUES (
                '123@s.whatsapp.net', 'Nitin', 'm2', 'me', 'me',
                101, 1, '', '(message)', '', '', ''
            );
            INSERT INTO messages VALUES (
                '123@s.whatsapp.net', 'Nitin', 'm3', 'me', 'me',
                102, 1, '', 'Sent image', 'image', '', ''
            );
            """
        )


def test_import_wacli_upserts_chats_and_filters_placeholders(tmp_path: Path):
    source_db = tmp_path / "wacli.db"
    dest_db = tmp_path / "whatsapp_data.db"
    create_wacli_db(source_db)

    stats = import_wacli.import_wacli(source_db, dest_db, account_id="wacli-test", dry_run=False)

    assert stats == {
        "source_chats": 1,
        "source_messages": 3,
        "source_text_messages": 2,
        "dry_run": 0,
    }
    with sqlite3.connect(dest_db) as conn:
        chat = conn.execute("SELECT account_id, chat_id, display_name FROM wa_chats").fetchone()
        bodies = conn.execute(
            "SELECT message_id, body, message_type FROM wa_messages ORDER BY message_id"
        ).fetchall()

    assert chat == ("wacli-test", "123@s.whatsapp.net", "Nitin")
    assert bodies == [
        ("m1", "real body", "chat"),
        ("m2", "", "chat"),
        ("m3", "Sent image", "image"),
    ]
