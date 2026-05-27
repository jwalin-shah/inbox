import sqlite3

from message_index_store import MessageIndexStore
from scripts import whatsapp_web_scanner


def test_write_scan_creates_openhuman_shaped_whatsapp_db(tmp_path):
    db_path = tmp_path / "whatsapp_data.db"
    scan = {
        "messages": [
            {
                "chatId": "chat-1@c.us",
                "messageId": "m1",
                "sender": "Alice",
                "fromMe": False,
                "body": "hello",
                "timestampText": "4:53 AM, 7/5/2025",
                "activeChatName": "Alice",
            },
            {
                "chatId": "chat-1@c.us",
                "messageId": "m2",
                "sender": "Me",
                "fromMe": True,
                "body": "reply",
                "timestampText": "4:54 AM, 7/5/2025",
                "activeChatName": "Alice",
            },
        ]
    }

    written = whatsapp_web_scanner.write_scan(db_path, scan, "acct")

    assert written == {"chats": 1, "messages": 2}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        chat = conn.execute("SELECT * FROM wa_chats").fetchone()
        messages = conn.execute("SELECT * FROM wa_messages ORDER BY timestamp").fetchall()
    finally:
        conn.close()
    assert chat["display_name"] == "Alice"
    assert chat["message_count"] == 2
    assert [row["body"] for row in messages] == ["hello", "reply"]
    assert messages[1]["from_me"] == 1


def test_scanned_db_can_sync_into_inbox_index(tmp_path, monkeypatch):
    db_path = tmp_path / "whatsapp_data.db"
    whatsapp_web_scanner.write_scan(
        db_path,
        {
            "messages": [
                {
                    "chatId": "chat-1@c.us",
                    "messageId": "m1",
                    "sender": "Alice",
                    "fromMe": False,
                    "body": "hello",
                    "timestampText": "4:53 AM, 7/5/2025",
                    "activeChatName": "Alice",
                }
            ]
        },
        "acct",
    )
    monkeypatch.setattr("message_sync._openhuman_whatsapp_db_path", lambda: db_path)
    store = MessageIndexStore(tmp_path / "index.sqlite3")

    from message_sync import sync_whatsapp_incremental

    stats = sync_whatsapp_incremental(store)
    store.rebuild_threads(source="whatsapp", account="acct")

    assert stats == {"acct": 1}
    rows = [
        row
        for row in store.list_threads(limit=5, sort_mode="recent")
        if row["source"] == "whatsapp" and row["account"] == "acct"
    ]
    assert len(rows) == 1
    assert rows[0]["latest_subject"] == "Alice"
    assert rows[0]["latest_snippet"] == "hello"


def test_write_scan_preserves_existing_body_when_later_scan_is_empty(tmp_path):
    db_path = tmp_path / "whatsapp_data.db"
    first_scan = {
        "messages": [
            {
                "chatId": "chat-1@c.us",
                "messageId": "m1",
                "sender": "Alice",
                "fromMe": False,
                "body": "captured body",
                "timestamp": 1760000000,
                "activeChatName": "Alice",
            }
        ]
    }
    empty_rescan = {
        "messages": [
            {
                "chatId": "chat-1@c.us",
                "messageId": "m1",
                "sender": "Alice",
                "fromMe": False,
                "body": "",
                "timestamp": 1760000100,
                "activeChatName": "Alice",
            }
        ]
    }

    whatsapp_web_scanner.write_scan(db_path, first_scan, "acct")
    whatsapp_web_scanner.write_scan(db_path, empty_rescan, "acct")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        message = conn.execute("SELECT * FROM wa_messages").fetchone()
    finally:
        conn.close()
    assert message["body"] == "captured body"
    assert message["timestamp"] == 1760000100


def test_write_scan_uses_alternate_message_text_fields(tmp_path):
    db_path = tmp_path / "whatsapp_data.db"
    scan = {
        "messages": [
            {
                "chatId": "chat-1@c.us",
                "messageId": "text-field",
                "sender": "Alice",
                "text": "from text",
            },
            {
                "chatId": "chat-1@c.us",
                "messageId": "caption-field",
                "sender": "Alice",
                "caption": "from caption",
            },
            {
                "chatId": "chat-1@c.us",
                "messageId": "display-field",
                "sender": "Alice",
                "displayText": "from display",
            },
        ]
    }

    whatsapp_web_scanner.write_scan(db_path, scan, "acct")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        messages = conn.execute(
            "SELECT message_id, body FROM wa_messages ORDER BY message_id"
        ).fetchall()
    finally:
        conn.close()
    assert [(row["message_id"], row["body"]) for row in messages] == [
        ("caption-field", "from caption"),
        ("display-field", "from display"),
        ("text-field", "from text"),
    ]


def test_write_scan_extracts_nested_indexeddb_message_text(tmp_path):
    db_path = tmp_path / "whatsapp_data.db"
    scan = {
        "source": "brave-cdp-idb",
        "messages": [
            {
                "chatId": "chat-1@c.us",
                "messageId": "nested-conversation",
                "sender": "Alice",
                "message": {"conversation": "from nested conversation"},
            },
            {
                "chatId": "chat-1@c.us",
                "messageId": "nested-extended",
                "sender": "Alice",
                "content": {
                    "extendedTextMessage": {"text": "from nested extended text"},
                },
            },
        ],
    }

    whatsapp_web_scanner.write_scan(db_path, scan, "acct")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        messages = conn.execute(
            "SELECT message_id, body FROM wa_messages ORDER BY message_id"
        ).fetchall()
    finally:
        conn.close()
    assert [(row["message_id"], row["body"]) for row in messages] == [
        ("nested-conversation", "from nested conversation"),
        ("nested-extended", "from nested extended text"),
    ]


def test_write_scan_accepts_indexeddb_chat_metadata(tmp_path):
    db_path = tmp_path / "whatsapp_data.db"
    scan = {
        "source": "brave-cdp-idb",
        "chats": [
            {
                "chatId": "chat-1@c.us",
                "name": "Alice",
                "lastMessageTs": 1760000000,
                "messageCount": 12,
            },
            {
                "chatId": "group-1@g.us",
                "name": "Project Group",
                "lastMessageTs": 1760000100,
                "messageCount": 0,
            },
        ],
        "messages": [
            {
                "chatId": "chat-1@c.us",
                "messageId": "false_chat-1@c.us_msg-1",
                "sender": "Alice",
                "senderJid": "alice@c.us",
                "fromMe": False,
                "body": "",
                "timestamp": 1760000000,
                "messageType": "chat",
                "source": "brave-cdp-idb",
            }
        ],
    }

    written = whatsapp_web_scanner.write_scan(db_path, scan, "acct")

    assert written == {"chats": 2, "messages": 1}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        chats = conn.execute("SELECT * FROM wa_chats ORDER BY chat_id").fetchall()
        message = conn.execute("SELECT * FROM wa_messages").fetchone()
    finally:
        conn.close()
    assert [(row["chat_id"], row["display_name"], row["message_count"]) for row in chats] == [
        ("chat-1@c.us", "Alice", 13),
        ("group-1@g.us", "Project Group", 0),
    ]
    assert chats[1]["is_group"] == 1
    assert message["source"] == "brave-cdp-idb"
    assert message["sender_jid"] == "alice@c.us"
