import sqlite3

from message_index_store import MessageIndexStore
from scripts import linkedin_web_scanner


def test_write_scan_creates_openhuman_shaped_linkedin_db(tmp_path):
    db_path = tmp_path / "linkedin_data.db"
    scan = {
        "url": "https://www.linkedin.com/messaging/thread/thread-1/",
        "chats": [
            {
                "threadId": "thread-1",
                "displayName": "Alice Recruiter",
                "profileUrl": "https://www.linkedin.com/in/alice/",
                "lastMessageTs": 1_700_000_100,
                "messageCount": 4,
            }
        ],
        "messages": [
            {
                "threadId": "thread-1",
                "messageId": "m1",
                "sender": "Alice Recruiter",
                "senderProfileUrl": "https://www.linkedin.com/in/alice/",
                "fromMe": False,
                "body": "Can you chat tomorrow?",
                "timestamp": 1_700_000_000,
                "sourceUrl": "https://www.linkedin.com/messaging/thread/thread-1/",
            },
            {
                "threadId": "thread-1",
                "messageId": "m2",
                "sender": "Me",
                "fromMe": True,
                "body": "Yes, afternoon works.",
                "timestamp": 1_700_000_100,
            },
        ],
    }

    written = linkedin_web_scanner.write_scan(db_path, scan, "acct")

    assert written == {"threads": 1, "messages": 2}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        thread = conn.execute("SELECT * FROM li_threads").fetchone()
        messages = conn.execute("SELECT * FROM li_messages ORDER BY timestamp").fetchall()
    finally:
        conn.close()
    assert thread["display_name"] == "Alice Recruiter"
    assert thread["profile_url"] == "https://www.linkedin.com/in/alice/"
    assert thread["message_count"] == 6
    assert [row["body"] for row in messages] == [
        "Can you chat tomorrow?",
        "Yes, afternoon works.",
    ]
    assert messages[1]["from_me"] == 1


def test_scanned_linkedin_db_can_sync_into_inbox_index(tmp_path, monkeypatch):
    db_path = tmp_path / "linkedin_data.db"
    linkedin_web_scanner.write_scan(
        db_path,
        {
            "messages": [
                {
                    "threadId": "thread-1",
                    "messageId": "m1",
                    "sender": "Alice Recruiter",
                    "fromMe": False,
                    "body": "Can you chat tomorrow?",
                    "timestamp": 1_700_000_000,
                    "activeChatName": "Alice Recruiter",
                }
            ]
        },
        "acct",
    )
    monkeypatch.setattr("message_sync._openhuman_linkedin_db_path", lambda: db_path)
    store = MessageIndexStore(tmp_path / "index.sqlite3")

    from message_sync import sync_linkedin_incremental

    stats = sync_linkedin_incremental(store)
    store.rebuild_threads(source="linkedin", account="acct")

    assert stats == {"acct": 1}
    rows = [
        row
        for row in store.list_threads(limit=5, sort_mode="recent")
        if row["source"] == "linkedin" and row["account"] == "acct"
    ]
    assert len(rows) == 1
    assert rows[0]["latest_subject"] == "Alice Recruiter"
    assert rows[0]["latest_snippet"] == "Can you chat tomorrow?"


def test_write_scan_uses_sender_when_active_name_is_generic(tmp_path):
    db_path = tmp_path / "linkedin_data.db"
    linkedin_web_scanner.write_scan(
        db_path,
        {
            "messages": [
                {
                    "threadId": "thread-1",
                    "messageId": "m1",
                    "sender": "Alice Recruiter",
                    "fromMe": False,
                    "body": "Can you chat tomorrow?",
                    "timestamp": 1_700_000_000,
                    "activeChatName": "Conversation List",
                }
            ]
        },
        "acct",
    )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        thread = conn.execute("SELECT * FROM li_threads").fetchone()
    finally:
        conn.close()
    assert thread["display_name"] == "Alice Recruiter"


def test_write_scan_uses_counterparty_when_active_name_is_self(tmp_path, monkeypatch):
    db_path = tmp_path / "linkedin_data.db"
    monkeypatch.setattr(
        linkedin_web_scanner,
        "SELF_THREAD_NAMES",
        {"me", "you", "jwalin shah"},
    )
    linkedin_web_scanner.write_scan(
        db_path,
        {
            "messages": [
                {
                    "threadId": "thread-1",
                    "messageId": "m1",
                    "sender": "Jwalin Shah",
                    "fromMe": False,
                    "body": "My message",
                    "timestamp": 1_700_000_000,
                    "activeChatName": "Jwalin Shah",
                },
                {
                    "threadId": "thread-1",
                    "messageId": "m2",
                    "sender": "Alice Recruiter",
                    "fromMe": False,
                    "body": "Can you chat tomorrow?",
                    "timestamp": 1_700_000_100,
                    "activeChatName": "Jwalin Shah",
                },
            ]
        },
        "acct",
    )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        thread = conn.execute("SELECT * FROM li_threads").fetchone()
    finally:
        conn.close()
    assert thread["display_name"] == "Alice Recruiter"
