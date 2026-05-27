import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import message_sync
from message_index_store import IndexedItem, MessageIndexStore

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_runtime_output_defaults_are_gitignored():
    from message_index_store import DEFAULT_INDEX_DB

    ignored_paths = [
        DEFAULT_INDEX_DB.relative_to(REPO_ROOT),
        Path(f"{DEFAULT_INDEX_DB.relative_to(REPO_ROOT)}-wal"),
        Path(f"{DEFAULT_INDEX_DB.relative_to(REPO_ROOT)}-shm"),
        Path(".inbox_memory.sqlite3-wal"),
        Path(".inbox_scheduler.sqlite3-shm"),
        Path(".inbox_runtime/message-sync/run.json"),
        Path(".factory/runtime/validation/run.json"),
        Path(".factory/outputs/validation/run.json"),
        Path(".factory/runs/local-run.json"),
        Path(".factory/missions/local-run.json"),
    ]
    result = subprocess.run(
        ["git", "check-ignore", "--stdin"],
        cwd=REPO_ROOT,
        input="\n".join(str(path) for path in ignored_paths),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.splitlines() == [str(path) for path in ignored_paths]


class _FakeRequest:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeMessagesApi:
    def __init__(self, list_payloads, full_messages):
        self._list_payloads = list_payloads
        self._full_messages = full_messages

    def list(self, *, pageToken=None, **_kwargs):
        key = pageToken or "__first__"
        return _FakeRequest(self._list_payloads[key])

    def get(self, *, id, **_kwargs):
        return _FakeRequest(self._full_messages[id])


class _FakeHistoryApi:
    def __init__(self, history_payloads):
        self._history_payloads = history_payloads

    def list(self, *, pageToken=None, **_kwargs):
        key = pageToken or "__first__"
        return _FakeRequest(self._history_payloads[key])


class _FakeUsersApi:
    def __init__(
        self, list_payloads, full_messages, *, profile_payload=None, history_payloads=None
    ):
        self._messages_api = _FakeMessagesApi(list_payloads, full_messages)
        self._profile_payload = profile_payload
        self._history_payloads = history_payloads

    def messages(self):
        return self._messages_api

    def getProfile(self, **_kwargs):
        return _FakeRequest(self._profile_payload or {})

    def history(self):
        if self._history_payloads is None:
            raise AttributeError("history unavailable")
        return _FakeHistoryApi(self._history_payloads)


class _FakeGmailService:
    def __init__(
        self,
        list_payloads,
        full_messages,
        *,
        profile_payload=None,
        history_payloads=None,
    ):
        self._users_api = _FakeUsersApi(
            list_payloads,
            full_messages,
            profile_payload=profile_payload,
            history_payloads=history_payloads,
        )

    def users(self):
        return self._users_api


def _gmail_message(
    message_id: str,
    internal_date: int,
    *,
    thread_id: str | None = None,
    labels: list[str] | None = None,
    to_header: str = "acct@example.com",
):
    return {
        "id": message_id,
        "threadId": thread_id or message_id,
        "internalDate": str(internal_date),
        "snippet": f"snippet-{message_id}",
        "labelIds": labels or ["INBOX"],
        "payload": {
            "headers": [
                {"name": "From", "value": "Sender <sender@example.com>"},
                {"name": "To", "value": to_header},
                {"name": "Subject", "value": f"Subject {message_id}"},
            ],
            "parts": [],
            "body": {"data": ""},
        },
    }


def _indexed_item(
    *,
    source: str,
    account: str,
    external_id: str,
    thread_id: str,
    created_at: str,
    subject: str,
) -> IndexedItem:
    return IndexedItem(
        source=source,
        account=account,
        external_id=external_id,
        thread_id=thread_id,
        kind="email" if source == "gmail" else "imessage",
        created_at=created_at,
        updated_at=created_at,
        ingested_at=created_at,
        sender="Sender",
        recipients_json="[]",
        subject=subject,
        snippet=subject,
        body_text=subject,
        body_hash=f"hash-{external_id}",
        labels_json="[]",
        raw_pointer=f"{source}:{account}:{external_id}",
        is_deleted=0,
        is_read=1,
    )


def _thread_rows(store: MessageIndexStore) -> dict[tuple[str, str, str], sqlite3.Row]:
    with store._connect() as conn:
        rows = conn.execute("SELECT * FROM threads").fetchall()
    return {(str(row["source"]), str(row["account"]), str(row["thread_id"])): row for row in rows}


def test_message_sync_cli_smoke_is_no_secret_success_path():
    result = subprocess.run(
        [sys.executable, "message_sync.py", "--smoke"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "entrypoint": "message_sync.py",
        "modes": ["bootstrap", "incremental", "rebuild", "summary"],
        "ok": True,
    }


def test_message_sync_cli_bad_input_fails_clearly():
    result = subprocess.run(
        [sys.executable, "message_sync.py", "bogus"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "invalid choice: 'bogus'" in result.stderr


def test_sync_gmail_bootstrap_resumes_from_saved_page_token(tmp_path, monkeypatch):
    store = MessageIndexStore(tmp_path / "index.sqlite3")

    first_run_service = _FakeGmailService(
        list_payloads={
            "__first__": {
                "messages": [{"id": "m1"}, {"id": "m2"}],
                "nextPageToken": "page-2",
            },
            "page-2": RuntimeError("network dropped"),
        },
        full_messages={
            "m1": _gmail_message("m1", 300),
            "m2": _gmail_message("m2", 200),
        },
    )
    monkeypatch.setattr(
        message_sync,
        "google_auth_all",
        lambda: ({"acct@example.com": first_run_service}, {}, {}, {}, {}, {}),
    )

    with pytest.raises(RuntimeError, match="network dropped"):
        message_sync.sync_gmail_bootstrap(store)

    errored = store.get_sync_state("gmail", "acct@example.com")
    assert errored is not None
    assert errored["status"] == "error"
    assert errored["checkpoint_value"] == "300"
    assert errored["metadata"]["bootstrap_page_token"] == "page-2"

    second_run_service = _FakeGmailService(
        list_payloads={
            "page-2": {
                "messages": [{"id": "m3"}],
            },
        },
        full_messages={
            "m3": _gmail_message("m3", 100),
        },
    )
    monkeypatch.setattr(
        message_sync,
        "google_auth_all",
        lambda: ({"acct@example.com": second_run_service}, {}, {}, {}, {}, {}),
    )

    stats = message_sync.sync_gmail_bootstrap(store)
    assert stats == {"acct@example.com": 1}

    resumed = store.get_sync_state("gmail", "acct@example.com")
    assert resumed is not None
    assert resumed["status"] == "idle"
    assert resumed["last_full_sync_at"] != ""
    assert resumed["metadata"]["bootstrap_page_token"] == ""

    with sqlite3.connect(store.db_path) as conn:
        row_count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    assert row_count == 3


def test_sync_gmail_bootstrap_records_history_cursor(tmp_path, monkeypatch):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    service = _FakeGmailService(
        list_payloads={
            "__first__": {
                "messages": [{"id": "m1"}],
            },
        },
        full_messages={
            "m1": _gmail_message("m1", 300),
        },
        profile_payload={"historyId": "9000"},
    )
    monkeypatch.setattr(
        message_sync,
        "google_auth_all",
        lambda: ({"acct@example.com": service}, {}, {}, {}, {}, {}),
    )

    stats = message_sync.sync_gmail_bootstrap(store)
    assert stats == {"acct@example.com": 1}

    state = store.get_sync_state("gmail", "acct@example.com")
    assert state is not None
    assert state["checkpoint_type"] == message_sync.GMAIL_HISTORY_CURSOR
    assert state["checkpoint_value"] == "9000"
    assert state["metadata"]["cursor_mode"] == "history"
    assert state["metadata"]["history_id"] == "9000"
    assert state["metadata"]["timestamp_checkpoint_ms"] == "300"


def test_sync_gmail_bootstrap_parses_quoted_recipient_commas(tmp_path, monkeypatch):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    service = _FakeGmailService(
        list_payloads={
            "__first__": {
                "messages": [{"id": "m1"}],
            },
        },
        full_messages={
            "m1": _gmail_message(
                "m1",
                300,
                to_header='"Doe, Jane" <jane@example.com>, Bob <bob@example.com>',
            ),
        },
    )
    monkeypatch.setattr(
        message_sync,
        "google_auth_all",
        lambda: ({"acct@example.com": service}, {}, {}, {}, {}, {}),
    )

    stats = message_sync.sync_gmail_bootstrap(store)
    assert stats == {"acct@example.com": 1}

    with sqlite3.connect(store.db_path) as conn:
        recipients_json = conn.execute(
            "SELECT recipients_json FROM items WHERE external_id = 'm1'"
        ).fetchone()[0]
    assert json.loads(recipients_json) == ["jane@example.com", "bob@example.com"]


def test_sync_gmail_bootstrap_does_not_double_count_or_rewrite_items_on_resume(
    tmp_path, monkeypatch
):
    store = MessageIndexStore(tmp_path / "index.sqlite3")

    first_run_service = _FakeGmailService(
        list_payloads={
            "__first__": {
                "messages": [{"id": "m1"}, {"id": "m2"}],
                "nextPageToken": "page-2",
            },
            "page-2": {
                "messages": [{"id": "m2"}, {"id": "m3"}],
            },
        },
        full_messages={
            "m1": _gmail_message("m1", 300),
            "m2": _gmail_message("m2", 250),
            "m3": RuntimeError("interrupted while fetching m3"),
        },
    )
    monkeypatch.setattr(
        message_sync,
        "google_auth_all",
        lambda: ({"acct@example.com": first_run_service}, {}, {}, {}, {}, {}),
    )

    with pytest.raises(RuntimeError, match="interrupted while fetching m3"):
        message_sync.sync_gmail_bootstrap(store)

    interrupted = store.get_sync_state("gmail", "acct@example.com")
    assert interrupted is not None
    assert interrupted["status"] == "error"
    assert interrupted["metadata"]["bootstrap_page_token"] == "page-2"

    with sqlite3.connect(store.db_path) as conn:
        interrupted_count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        existing_m2_ingested_at = conn.execute(
            "SELECT ingested_at FROM items WHERE external_id = 'm2'"
        ).fetchone()[0]
    assert interrupted_count == 2

    second_run_service = _FakeGmailService(
        list_payloads={
            "page-2": {
                "messages": [{"id": "m2"}, {"id": "m3"}],
            }
        },
        full_messages={
            "m2": _gmail_message("m2", 250),
            "m3": _gmail_message("m3", 200),
        },
    )
    monkeypatch.setattr(
        message_sync,
        "google_auth_all",
        lambda: ({"acct@example.com": second_run_service}, {}, {}, {}, {}, {}),
    )

    stats = message_sync.sync_gmail_bootstrap(store)
    assert stats == {"acct@example.com": 1}

    resumed = store.get_sync_state("gmail", "acct@example.com")
    assert resumed is not None
    assert resumed["status"] == "idle"
    assert resumed["metadata"]["bootstrap_page_token"] == ""
    assert resumed["last_full_sync_at"] != ""

    with sqlite3.connect(store.db_path) as conn:
        finished_count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        resumed_m2_ingested_at = conn.execute(
            "SELECT ingested_at FROM items WHERE external_id = 'm2'"
        ).fetchone()[0]
    assert finished_count == 3
    assert resumed_m2_ingested_at == existing_m2_ingested_at


def test_sync_gmail_incremental_uses_history_for_new_and_changed_messages(tmp_path, monkeypatch):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    store.upsert_item(
        message_sync._gmail_item(
            "acct@example.com",
            _gmail_message("m1", 100, labels=["INBOX", "UNREAD"]),
        )
    )
    store.set_sync_state(
        source="gmail",
        account="acct@example.com",
        checkpoint_type=message_sync.GMAIL_HISTORY_CURSOR,
        checkpoint_value="9000",
        status="idle",
        metadata={
            "cursor_mode": "history",
            "history_id": "9000",
            "timestamp_checkpoint_ms": "100",
        },
    )
    service = _FakeGmailService(
        list_payloads={},
        full_messages={
            "m1": _gmail_message("m1", 100, labels=["INBOX"]),
            "m2": _gmail_message("m2", 200, labels=["INBOX", "UNREAD"]),
        },
        history_payloads={
            "__first__": {
                "historyId": "9001",
                "history": [
                    {
                        "labelsRemoved": [{"message": {"id": "m1"}, "labelIds": ["UNREAD"]}],
                        "messagesAdded": [{"message": {"id": "m2"}}],
                    }
                ],
            }
        },
    )
    monkeypatch.setattr(
        message_sync,
        "google_auth_all",
        lambda: ({"acct@example.com": service}, {}, {}, {}, {}, {}),
    )

    stats = message_sync.sync_gmail_incremental(store)
    assert stats == {"acct@example.com": 2}

    state = store.get_sync_state("gmail", "acct@example.com")
    assert state is not None
    assert state["checkpoint_type"] == message_sync.GMAIL_HISTORY_CURSOR
    assert state["checkpoint_value"] == "9001"
    assert state["metadata"]["cursor_mode"] == "history"
    assert state["metadata"]["timestamp_checkpoint_ms"] == "200"

    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        existing = conn.execute(
            "SELECT is_read, labels_json FROM items WHERE external_id = 'm1'"
        ).fetchone()
        inserted = conn.execute(
            "SELECT is_read, labels_json FROM items WHERE external_id = 'm2'"
        ).fetchone()
    assert existing["is_read"] == 1
    assert '"UNREAD"' not in existing["labels_json"]
    assert inserted["is_read"] == 0


def test_sync_gmail_incremental_falls_back_without_history_cursor(tmp_path, monkeypatch):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    store.set_sync_state(
        source="gmail",
        account="acct@example.com",
        checkpoint_type=message_sync.GMAIL_TIMESTAMP_CURSOR,
        checkpoint_value="100",
        status="idle",
        metadata={},
    )
    service = _FakeGmailService(
        list_payloads={
            "__first__": {
                "messages": [{"id": "m2"}, {"id": "m1"}],
            },
        },
        full_messages={
            "m2": _gmail_message("m2", 200),
            "m1": _gmail_message("m1", 100),
        },
    )
    monkeypatch.setattr(
        message_sync,
        "google_auth_all",
        lambda: ({"acct@example.com": service}, {}, {}, {}, {}, {}),
    )

    stats = message_sync.sync_gmail_incremental(store)
    assert stats == {"acct@example.com": 1}

    state = store.get_sync_state("gmail", "acct@example.com")
    assert state is not None
    assert state["checkpoint_type"] == message_sync.GMAIL_TIMESTAMP_CURSOR
    assert state["checkpoint_value"] == "200"
    assert state["metadata"]["cursor_mode"] == "timestamp_fallback"
    assert state["metadata"]["fallback_reason"] == "missing_history_cursor"
    assert state["metadata"]["timestamp_checkpoint_ms"] == "200"


def test_sync_imessage_incremental_advances_checkpoint_for_skipped_rows(tmp_path, monkeypatch):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    store.set_sync_state(
        source="imessage",
        account="local",
        checkpoint_type="rowid",
        checkpoint_value="10",
        full_sync=False,
        status="idle",
        metadata={},
    )

    monkeypatch.setattr(
        message_sync,
        "_imessage_messages_after",
        lambda _last_rowid: [
            {
                "message_rowid": 11,
                "text": "",
                "ts": 0,
                "is_from_me": 0,
                "sender_id": "a",
                "chat_id": 1,
            },
            {
                "message_rowid": 12,
                "text": "\N{OBJECT REPLACEMENT CHARACTER}",
                "ts": 0,
                "is_from_me": 0,
                "sender_id": "a",
                "chat_id": 1,
            },
        ],
    )

    stats = message_sync.sync_imessage_incremental(store)
    assert stats == {"local": 0}

    state = store.get_sync_state("imessage", "local")
    assert state is not None
    assert state["checkpoint_value"] == "12"

    with sqlite3.connect(store.db_path) as conn:
        row_count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    assert row_count == 0


def test_sync_imessage_bootstrap_advances_checkpoint_for_skipped_rows(tmp_path, monkeypatch):
    store = MessageIndexStore(tmp_path / "index.sqlite3")

    monkeypatch.setattr(
        message_sync,
        "_imessage_messages_after",
        lambda _last_rowid: [
            {
                "message_rowid": 1,
                "text": "",
                "ts": 0,
                "is_from_me": 1,
                "sender_id": None,
                "chat_id": 1,
            },
            {
                "message_rowid": 2,
                "text": "\N{OBJECT REPLACEMENT CHARACTER}",
                "ts": 0,
                "is_from_me": 1,
                "sender_id": None,
                "chat_id": 1,
            },
        ],
    )

    stats = message_sync.sync_imessage_bootstrap(store)
    assert stats == {"local": 0}

    state = store.get_sync_state("imessage", "local")
    assert state is not None
    assert state["checkpoint_value"] == "2"


def test_sync_imessage_incremental_can_be_disabled_for_sandboxed_runners(tmp_path, monkeypatch):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    store.set_sync_state(
        source="imessage",
        account="local",
        checkpoint_type="rowid",
        checkpoint_value="42",
        full_sync=False,
        status="error",
        last_error="unable to open database file",
        metadata={},
    )
    monkeypatch.setenv("INBOX_DISABLE_IMESSAGE_SYNC", "1")
    monkeypatch.setattr(
        message_sync,
        "_imessage_messages_after",
        lambda _last_rowid: (_ for _ in ()).throw(AssertionError("should not read chat.db")),
    )

    stats = message_sync.sync_imessage_incremental(store)

    assert stats == {"local": 0}
    state = store.get_sync_state("imessage", "local")
    assert state is not None
    assert state["status"] == "idle"
    assert state["last_error"] == ""
    assert state["checkpoint_value"] == "42"
    assert state["metadata"]["disabled"] is True


def _create_openhuman_whatsapp_db(db_path):
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE wa_chats (
            account_id TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            display_name TEXT NOT NULL DEFAULT '',
            is_group INTEGER NOT NULL DEFAULT 0,
            last_message_ts INTEGER NOT NULL DEFAULT 0,
            message_count INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (account_id, chat_id)
        );
        CREATE TABLE wa_messages (
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
        """
    )
    conn.execute(
        """
        INSERT INTO wa_chats
        (account_id, chat_id, display_name, is_group, last_message_ts, message_count, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("acct-1", "chat-1@c.us", "Alice", 0, 1_700_000_100, 2, 1_700_000_100),
    )
    conn.executemany(
        """
        INSERT INTO wa_messages
        (account_id, chat_id, message_id, sender, from_me, body, timestamp, message_type, source, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "acct-1",
                "chat-1@c.us",
                "m1",
                "Alice",
                0,
                "first",
                1_700_000_000,
                "chat",
                "cdp-indexeddb",
                1,
            ),
            (
                "acct-1",
                "chat-1@c.us",
                "m2",
                "me",
                1,
                "second",
                1_700_000_100,
                "chat",
                "cdp-indexeddb",
                1,
            ),
        ],
    )
    conn.commit()
    conn.close()


def _create_openhuman_linkedin_db(db_path):
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE li_threads (
            account_id TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            display_name TEXT NOT NULL DEFAULT '',
            profile_url TEXT NOT NULL DEFAULT '',
            last_message_ts INTEGER NOT NULL DEFAULT 0,
            message_count INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (account_id, thread_id)
        );
        CREATE TABLE li_messages (
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
        """
    )
    conn.execute(
        """
        INSERT INTO li_threads
        (account_id, thread_id, display_name, profile_url, last_message_ts, message_count, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "acct-li",
            "thread-1",
            "Alice Recruiter",
            "https://www.linkedin.com/in/alice/",
            1_700_000_100,
            2,
            1_700_000_100,
        ),
    )
    conn.executemany(
        """
        INSERT INTO li_messages
        (account_id, thread_id, message_id, sender, sender_profile_url, from_me, body, timestamp, source_url, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "acct-li",
                "thread-1",
                "m1",
                "Alice Recruiter",
                "https://www.linkedin.com/in/alice/",
                0,
                "Can you chat tomorrow?",
                1_700_000_000,
                "https://www.linkedin.com/messaging/thread/thread-1/",
                1,
            ),
            (
                "acct-li",
                "thread-1",
                "m2",
                "",
                None,
                1,
                "Yes, afternoon works.",
                1_700_000_100,
                "https://www.linkedin.com/messaging/thread/thread-1/",
                1,
            ),
        ],
    )
    conn.commit()
    conn.close()


def test_sync_whatsapp_bootstrap_indexes_openhuman_store(tmp_path, monkeypatch):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    db_path = tmp_path / "openhuman" / "workspace" / "whatsapp_data" / "whatsapp_data.db"
    _create_openhuman_whatsapp_db(db_path)
    monkeypatch.setattr(message_sync, "_openhuman_whatsapp_db_path", lambda: db_path)

    stats = message_sync.sync_whatsapp_bootstrap(store)
    rebuilt = store.rebuild_threads(source="whatsapp", account="acct-1")

    assert stats == {"acct-1": 2}
    assert rebuilt == 1
    state = store.get_sync_state("whatsapp", "acct-1")
    assert state is not None
    assert state["checkpoint_type"] == "unixTimestamp"
    assert state["checkpoint_value"] == "1700000100"
    rows = _thread_rows(store)
    thread = rows[("whatsapp", "acct-1", "chat-1@c.us")]
    assert thread["latest_external_id"] == "m2"
    assert thread["latest_subject"] == "Alice"


def test_sync_linkedin_bootstrap_indexes_openhuman_store(tmp_path, monkeypatch):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    db_path = tmp_path / "openhuman" / "workspace" / "linkedin_data" / "linkedin_data.db"
    _create_openhuman_linkedin_db(db_path)
    monkeypatch.setattr(message_sync, "_openhuman_linkedin_db_path", lambda: db_path)

    stats = message_sync.sync_linkedin_bootstrap(store)
    rebuilt = store.rebuild_threads(source="linkedin", account="acct-li")

    assert stats == {"acct-li": 2}
    assert rebuilt == 1
    state = store.get_sync_state("linkedin", "acct-li")
    assert state is not None
    assert state["checkpoint_type"] == "unixTimestamp"
    assert state["checkpoint_value"] == "1700000100"
    rows = _thread_rows(store)
    thread = rows[("linkedin", "acct-li", "thread-1")]
    assert thread["latest_external_id"] == "m2"
    assert thread["latest_subject"] == "Alice Recruiter"


def test_sync_linkedin_incremental_returns_empty_when_no_new_messages(tmp_path, monkeypatch):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    db_path = tmp_path / "openhuman" / "workspace" / "linkedin_data" / "linkedin_data.db"
    _create_openhuman_linkedin_db(db_path)
    monkeypatch.setattr(message_sync, "_openhuman_linkedin_db_path", lambda: db_path)

    first = message_sync.sync_linkedin_incremental(store)
    assert first == {"acct-li": 2}

    second = message_sync.sync_linkedin_incremental(store)
    assert second == {}


def test_incremental_rebuilds_only_changed_gmail_account(tmp_path, monkeypatch):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    store.upsert_item(
        _indexed_item(
            source="gmail",
            account="acct@example.com",
            external_id="gmail-a-1",
            thread_id="gmail-a-thread",
            created_at="2026-04-18T00:00:00+00:00",
            subject="Old Gmail A",
        )
    )
    store.upsert_item(
        _indexed_item(
            source="gmail",
            account="other@example.com",
            external_id="gmail-b-1",
            thread_id="gmail-b-thread",
            created_at="2026-04-18T00:00:00+00:00",
            subject="Old Gmail B",
        )
    )
    store.upsert_item(
        _indexed_item(
            source="imessage",
            account="local",
            external_id="imsg-1",
            thread_id="imsg-thread",
            created_at="2026-04-18T00:00:00+00:00",
            subject="Old iMessage",
        )
    )
    store.rebuild_threads()
    with store._connect() as conn:
        conn.execute("UPDATE threads SET updated_at = 'sentinel'")

    def fake_gmail_incremental(sync_store: MessageIndexStore) -> dict[str, int]:
        sync_store.upsert_item(
            _indexed_item(
                source="gmail",
                account="acct@example.com",
                external_id="gmail-a-2",
                thread_id="gmail-a-thread",
                created_at="2026-04-18T01:00:00+00:00",
                subject="New Gmail A",
            )
        )
        return {"acct@example.com": 1, "other@example.com": 0}

    monkeypatch.setattr(message_sync, "sync_gmail_incremental", fake_gmail_incremental)
    monkeypatch.setattr(message_sync, "sync_imessage_incremental", lambda _store: {"local": 0})
    monkeypatch.setattr(message_sync, "sync_whatsapp_incremental", lambda _store: {})
    monkeypatch.setattr(message_sync, "sync_linkedin_incremental", lambda _store: {})

    result = message_sync.incremental(store)

    assert result == {
        "gmail": {"acct@example.com": 1, "other@example.com": 0},
        "imessage": {"local": 0},
        "whatsapp": {},
        "linkedin": {},
    }
    rows = _thread_rows(store)
    assert len(rows) == 3
    changed = rows[("gmail", "acct@example.com", "gmail-a-thread")]
    untouched_gmail = rows[("gmail", "other@example.com", "gmail-b-thread")]
    untouched_imessage = rows[("imessage", "local", "imsg-thread")]
    assert changed["latest_external_id"] == "gmail-a-2"
    assert changed["latest_subject"] == "New Gmail A"
    assert changed["updated_at"] != "sentinel"
    assert untouched_gmail["latest_external_id"] == "gmail-b-1"
    assert untouched_gmail["updated_at"] == "sentinel"
    assert untouched_imessage["latest_external_id"] == "imsg-1"
    assert untouched_imessage["updated_at"] == "sentinel"


def test_incremental_rebuilds_only_changed_imessage_scope(tmp_path, monkeypatch):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    store.upsert_item(
        _indexed_item(
            source="gmail",
            account="acct@example.com",
            external_id="gmail-1",
            thread_id="gmail-thread",
            created_at="2026-04-18T00:00:00+00:00",
            subject="Old Gmail",
        )
    )
    store.upsert_item(
        _indexed_item(
            source="imessage",
            account="local",
            external_id="imsg-1",
            thread_id="imsg-thread",
            created_at="2026-04-18T00:00:00+00:00",
            subject="Old iMessage",
        )
    )
    store.rebuild_threads()
    with store._connect() as conn:
        conn.execute("UPDATE threads SET updated_at = 'sentinel'")

    def fake_imessage_incremental(sync_store: MessageIndexStore) -> dict[str, int]:
        sync_store.upsert_item(
            _indexed_item(
                source="imessage",
                account="local",
                external_id="imsg-2",
                thread_id="imsg-thread",
                created_at="2026-04-18T01:00:00+00:00",
                subject="New iMessage",
            )
        )
        return {"local": 1}

    monkeypatch.setattr(
        message_sync, "sync_gmail_incremental", lambda _store: {"acct@example.com": 0}
    )
    monkeypatch.setattr(message_sync, "sync_imessage_incremental", fake_imessage_incremental)
    monkeypatch.setattr(message_sync, "sync_whatsapp_incremental", lambda _store: {})
    monkeypatch.setattr(message_sync, "sync_linkedin_incremental", lambda _store: {})

    result = message_sync.incremental(store)

    assert result == {
        "gmail": {"acct@example.com": 0},
        "imessage": {"local": 1},
        "whatsapp": {},
        "linkedin": {},
    }
    rows = _thread_rows(store)
    assert len(rows) == 2
    untouched_gmail = rows[("gmail", "acct@example.com", "gmail-thread")]
    changed_imessage = rows[("imessage", "local", "imsg-thread")]
    assert untouched_gmail["latest_external_id"] == "gmail-1"
    assert untouched_gmail["updated_at"] == "sentinel"
    assert changed_imessage["latest_external_id"] == "imsg-2"
    assert changed_imessage["latest_subject"] == "New iMessage"
    assert changed_imessage["updated_at"] != "sentinel"


def test_incremental_records_source_error_and_continues(tmp_path, monkeypatch):
    store = MessageIndexStore(tmp_path / "index.sqlite3")

    def fake_gmail_incremental(sync_store: MessageIndexStore) -> dict[str, int]:
        sync_store.upsert_item(
            _indexed_item(
                source="gmail",
                account="acct@example.com",
                external_id="gmail-1",
                thread_id="gmail-thread",
                created_at="2026-04-18T01:00:00+00:00",
                subject="New Gmail",
            )
        )
        return {"acct@example.com": 1}

    monkeypatch.setattr(message_sync, "sync_gmail_incremental", fake_gmail_incremental)
    monkeypatch.setattr(
        message_sync,
        "sync_imessage_incremental",
        lambda _store: (_ for _ in ()).throw(OSError("messages db unavailable")),
    )
    monkeypatch.setattr(message_sync, "sync_whatsapp_incremental", lambda _store: {})
    monkeypatch.setattr(message_sync, "sync_linkedin_incremental", lambda _store: {})

    result = message_sync.incremental(store)

    assert result == {
        "gmail": {"acct@example.com": 1},
        "imessage": {},
        "whatsapp": {},
        "linkedin": {},
    }
    assert store.get_sync_state("imessage", "local")["status"] == "error"
    rows = _thread_rows(store)
    assert rows[("gmail", "acct@example.com", "gmail-thread")]["latest_subject"] == "New Gmail"


def test_rebuild_all_threads_preserves_global_repair_path(tmp_path):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    store.upsert_item(
        _indexed_item(
            source="gmail",
            account="acct@example.com",
            external_id="gmail-1",
            thread_id="gmail-thread",
            created_at="2026-04-18T00:00:00+00:00",
            subject="Gmail",
        )
    )

    rebuilt = message_sync.rebuild_all_threads(store)

    assert rebuilt == 1
    rows = _thread_rows(store)
    assert list(rows) == [("gmail", "acct@example.com", "gmail-thread")]
