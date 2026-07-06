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


# ---------------------------------------------------------------------------
# Utility functions — falsy input paths
# ---------------------------------------------------------------------------


def test_iso_from_ms_returns_now_for_falsy_input():
    assert "T" in message_sync._iso_from_ms(0)
    assert "T" in message_sync._iso_from_ms(None)
    assert "T" in message_sync._iso_from_ms("")


def test_iso_from_apple_seconds_returns_now_for_falsy_input():
    assert "T" in message_sync._iso_from_apple_seconds(0)
    assert "T" in message_sync._iso_from_apple_seconds(None)
    assert "T" in message_sync._iso_from_apple_seconds(0.0)


def test_iso_from_apple_seconds_returns_iso_for_truthy_value():
    # Non-zero value exercises the timestamp conversion path (line 45)
    result = message_sync._iso_from_apple_seconds(1700000000.0)
    assert "T" in result
    assert result == "2023-11-14T22:13:20+00:00"


def test_iso_from_unix_seconds_returns_now_for_falsy_input():
    assert "T" in message_sync._iso_from_unix_seconds(0)
    assert "T" in message_sync._iso_from_unix_seconds(None)
    assert "T" in message_sync._iso_from_unix_seconds("")


def test_iso_from_ms_returns_proper_iso_for_positive_value():
    result = message_sync._iso_from_ms(1700000000000)
    assert result == "2023-11-14T22:13:20+00:00"


def test_gmail_recipients_returns_empty_when_no_to_header():
    assert message_sync._gmail_recipients({}) == []
    assert message_sync._gmail_recipients({"From": "A <a@x.com>"}) == []


def test_gmail_recipients_returns_empty_when_to_header_empty():
    assert message_sync._gmail_recipients({"To": ""}) == []


# ---------------------------------------------------------------------------
# Helper error paths — AttributeError handling
# ---------------------------------------------------------------------------


def test_fetch_gmail_profile_history_id_returns_empty_on_attribute_error():
    class NoUsersService:
        pass  # no users() at all

    assert message_sync._fetch_gmail_profile_history_id(NoUsersService()) == ""


def test_gmail_history_api_returns_none_on_attribute_error():
    class NoHistoryService:
        def users(self):
            class NoHistoryUsers:
                pass  # no history() method

            return NoHistoryUsers()

    assert message_sync._gmail_history_api(NoHistoryService()) is None


# ---------------------------------------------------------------------------
# Gmail bootstrap — empty-messages break path (line 236)
# ---------------------------------------------------------------------------


def test_sync_gmail_bootstrap_breaks_on_empty_messages(tmp_path, monkeypatch):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    service = _FakeGmailService(
        list_payloads={
            "__first__": {"messages": []},
        },
        full_messages={},
        profile_payload={"historyId": "9000"},
    )
    monkeypatch.setattr(
        message_sync,
        "google_auth_all",
        lambda: ({"acct@example.com": service}, {}, {}, {}, {}, {}),
    )

    stats = message_sync.sync_gmail_bootstrap(store)
    assert stats == {"acct@example.com": 0}

    state = store.get_sync_state("gmail", "acct@example.com")
    assert state is not None
    assert state["checkpoint_type"] == message_sync.GMAIL_HISTORY_CURSOR
    assert state["checkpoint_value"] == "9000"


# ---------------------------------------------------------------------------
# Gmail incremental history — dedup + error paths
# ---------------------------------------------------------------------------


def test_sync_gmail_incremental_history_dedup_skips_duplicate_message_ids(
    tmp_path, monkeypatch
):
    """Line 332: dedup across history pages — same message ID in two pages."""
    store = MessageIndexStore(tmp_path / "index.sqlite3")
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
    # Same message ID appears in two separate history pages
    service = _FakeGmailService(
        list_payloads={},
        full_messages={
            "m1": _gmail_message("m1", 200, labels=["INBOX", "UNREAD"]),
        },
        history_payloads={
            "__first__": {
                "historyId": "9001",
                "history": [
                    {
                        "messagesAdded": [
                            {"message": {"id": "m1"}},
                        ],
                    }
                ],
                "nextPageToken": "page-2",
            },
            "page-2": {
                "historyId": "9001",
                "history": [
                    {
                        "labelsRemoved": [
                            {"message": {"id": "m1"}, "labelIds": ["UNREAD"]}
                        ],
                    }
                ],
            },
        },
    )
    monkeypatch.setattr(
        message_sync,
        "google_auth_all",
        lambda: ({"acct@example.com": service}, {}, {}, {}, {}, {}),
    )

    stats = message_sync.sync_gmail_incremental(store)
    assert stats == {"acct@example.com": 1}


def test_sync_gmail_incremental_history_records_error_and_raises(tmp_path, monkeypatch):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
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
            "m1": RuntimeError("fetch failed"),
        },
        history_payloads={
            "__first__": {
                "historyId": "9001",
                "history": [
                    {
                        "messagesAdded": [
                            {"message": {"id": "m1"}},
                        ],
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

    with pytest.raises(RuntimeError, match="fetch failed"):
        message_sync.sync_gmail_incremental(store)

    errored = store.get_sync_state("gmail", "acct@example.com")
    assert errored is not None
    assert errored["status"] == "error"
    assert "fetch failed" in errored["last_error"]


# ---------------------------------------------------------------------------
# Gmail incremental timestamp — empty-messages + error paths
# ---------------------------------------------------------------------------


def test_sync_gmail_incremental_timestamp_breaks_on_empty_messages(
    tmp_path, monkeypatch
):
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
            "__first__": {"messages": []},
        },
        full_messages={},
    )
    monkeypatch.setattr(
        message_sync,
        "google_auth_all",
        lambda: ({"acct@example.com": service}, {}, {}, {}, {}, {}),
    )

    stats = message_sync.sync_gmail_incremental(store)
    # Falls back to timestamp mode because no history cursor
    assert stats == {"acct@example.com": 0}


def test_sync_gmail_incremental_timestamp_records_error_and_raises(
    tmp_path, monkeypatch
):
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
            "__first__": RuntimeError("api error"),
        },
        full_messages={},
    )
    monkeypatch.setattr(
        message_sync,
        "google_auth_all",
        lambda: ({"acct@example.com": service}, {}, {}, {}, {}, {}),
    )

    with pytest.raises(RuntimeError, match="api error"):
        message_sync.sync_gmail_incremental(store)

    errored = store.get_sync_state("gmail", "acct@example.com")
    assert errored is not None
    assert errored["status"] == "error"
    assert "api error" in errored["last_error"]


# ---------------------------------------------------------------------------
# iMessage sync — non-empty body path (exercises _imessage_item)
# ---------------------------------------------------------------------------


def test_sync_imessage_incremental_with_non_empty_body_upserts_item(
    tmp_path, monkeypatch
):
    store = MessageIndexStore(tmp_path / "index.sqlite3")

    monkeypatch.setattr(
        message_sync,
        "_imessage_messages_after",
        lambda _last_rowid: [
            {
                "message_rowid": 1,
                "text": "Hello from iMessage",
                "ts": 0,
                "is_from_me": 1,
                "sender_id": None,
                "chat_id": 42,
            },
        ],
    )

    stats = message_sync.sync_imessage_incremental(store)
    assert stats == {"local": 1}

    state = store.get_sync_state("imessage", "local")
    assert state is not None
    assert state["checkpoint_value"] == "1"
    assert state["metadata"]["messages_processed"] == 1

    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT sender, kind FROM items WHERE external_id = '1'"
        ).fetchone()
    assert row["sender"] == "Me"
    assert row["kind"] == "imessage"


def test_sync_imessage_incremental_with_multiple_items_counts_correctly(
    tmp_path, monkeypatch
):
    store = MessageIndexStore(tmp_path / "index.sqlite3")

    monkeypatch.setattr(
        message_sync,
        "_imessage_messages_after",
        lambda _last_rowid: [
            {
                "message_rowid": 1,
                "text": "First msg",
                "ts": 0,
                "is_from_me": 0,
                "sender_id": "+15551234567",
                "chat_id": 42,
            },
            {
                "message_rowid": 2,
                "text": "Second msg",
                "ts": 0,
                "is_from_me": 1,
                "sender_id": None,
                "chat_id": 42,
            },
        ],
    )

    stats = message_sync.sync_imessage_incremental(store)
    assert stats == {"local": 2}

    with sqlite3.connect(store.db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT sender, external_id FROM items ORDER BY external_id").fetchall()
    assert rows[0]["sender"] == "+15551234567"
    assert rows[0]["external_id"] == "1"
    assert rows[1]["sender"] == "Me"
    assert rows[1]["external_id"] == "2"


def test_sync_imessage_incremental_fires_progress_update(tmp_path, monkeypatch):
    """Lines 540-549: progress update when count % IMESSAGE_PROGRESS_EVERY == 0."""
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    monkeypatch.setattr(message_sync, "IMESSAGE_PROGRESS_EVERY", 2)

    monkeypatch.setattr(
        message_sync,
        "_imessage_messages_after",
        lambda _last_rowid: [
            {
                "message_rowid": i,
                "text": f"msg {i}",
                "ts": 0,
                "is_from_me": 1,
                "sender_id": None,
                "chat_id": 42,
            }
            for i in range(1, 5)  # 4 messages, progress at 2 and 4
        ],
    )

    stats = message_sync.sync_imessage_incremental(store)
    assert stats == {"local": 4}

    state = store.get_sync_state("imessage", "local")
    assert state is not None
    assert state["checkpoint_value"] == "4"


# ---------------------------------------------------------------------------
# WhatsApp incremental — checkpoint-skip + empty-body paths
# ---------------------------------------------------------------------------


def test_sync_whatsapp_incremental_skips_already_synced_messages(
    tmp_path, monkeypatch
):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    db_path = tmp_path / "openhuman" / "workspace" / "whatsapp_data" / "whatsapp_data.db"
    _create_openhuman_whatsapp_db(db_path)
    monkeypatch.setattr(message_sync, "_openhuman_whatsapp_db_path", lambda: db_path)

    # Bootstrap first
    first = message_sync.sync_whatsapp_bootstrap(store)
    assert first == {"acct-1": 2}

    # Incremental should skip all (timestamps at or below checkpoint)
    second = message_sync.sync_whatsapp_incremental(store)
    assert second == {}


def test_sync_whatsapp_incremental_skips_empty_body_messages(
    tmp_path, monkeypatch
):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    db_path = tmp_path / "openhuman" / "workspace" / "whatsapp_data" / "whatsapp_data.db"
    _create_openhuman_whatsapp_db(db_path)

    # Add a new message with empty body after the initial data
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO wa_messages
        (account_id, chat_id, message_id, sender, from_me, body, timestamp, message_type, source, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("acct-1", "chat-1@c.us", "m3", "Alice", 0, "", 1_700_000_200, "chat", "cdp-indexeddb", 1),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(message_sync, "_openhuman_whatsapp_db_path", lambda: db_path)

    first = message_sync.sync_whatsapp_bootstrap(store)
    assert first == {"acct-1": 2}

    # Incremental should skip m3 because body is empty
    second = message_sync.sync_whatsapp_incremental(store)
    assert second == {}


# ---------------------------------------------------------------------------
# LinkedIn incremental — empty-body path
# ---------------------------------------------------------------------------


def test_sync_linkedin_incremental_skips_empty_body_messages(
    tmp_path, monkeypatch
):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    db_path = tmp_path / "openhuman" / "workspace" / "linkedin_data" / "linkedin_data.db"
    _create_openhuman_linkedin_db(db_path)

    # Add a new message with empty body
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO li_messages
        (account_id, thread_id, message_id, sender, sender_profile_url, from_me, body, timestamp, source_url, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("acct-li", "thread-1", "m3", "Alice Recruiter",
         "https://www.linkedin.com/in/alice/", 0, "",
         1_700_000_200,
         "https://www.linkedin.com/messaging/thread/thread-1/", 1),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(message_sync, "_openhuman_linkedin_db_path", lambda: db_path)

    first = message_sync.sync_linkedin_bootstrap(store)
    assert first == {"acct-li": 2}

    # Incremental should skip m3 because body is empty
    second = message_sync.sync_linkedin_incremental(store)
    assert second == {}


# ---------------------------------------------------------------------------
# OpenHuman DB — no-database paths
# ---------------------------------------------------------------------------


def test_openhuman_whatsapp_rows_returns_empty_when_no_db(monkeypatch):
    monkeypatch.setattr(message_sync, "_openhuman_whatsapp_db_path", lambda: None)
    rows = message_sync._openhuman_whatsapp_rows()
    assert rows == []


def test_openhuman_linkedin_rows_returns_empty_when_no_db(monkeypatch):
    monkeypatch.setattr(message_sync, "_openhuman_linkedin_db_path", lambda: None)
    rows = message_sync._openhuman_linkedin_rows()
    assert rows == []


# ---------------------------------------------------------------------------
# Progress-update paths — WhatsApp + LinkedIn
# ---------------------------------------------------------------------------


def test_sync_whatsapp_bootstrap_progress_update_fires_at_progress_interval(
    tmp_path, monkeypatch
):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    db_path = tmp_path / "openhuman" / "workspace" / "whatsapp_data" / "whatsapp_data.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE wa_chats (
            account_id TEXT NOT NULL, chat_id TEXT NOT NULL,
            display_name TEXT NOT NULL DEFAULT '', is_group INTEGER NOT NULL DEFAULT 0,
            last_message_ts INTEGER NOT NULL DEFAULT 0,
            message_count INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (account_id, chat_id)
        );
        CREATE TABLE wa_messages (
            account_id TEXT NOT NULL, chat_id TEXT NOT NULL,
            message_id TEXT NOT NULL, sender TEXT NOT NULL DEFAULT '',
            sender_jid TEXT, from_me INTEGER NOT NULL DEFAULT 0,
            body TEXT NOT NULL DEFAULT '', timestamp INTEGER NOT NULL DEFAULT 0,
            message_type TEXT, source TEXT NOT NULL DEFAULT '',
            ingested_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (account_id, chat_id, message_id)
        );
        """
    )
    conn.execute(
        "INSERT INTO wa_chats VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("acct-1", "chat-1@c.us", "Alice", 0, 1_700_000_100, 2, 1_700_000_100),
    )
    # Insert enough messages to trigger at least one progress update (WHATSAPP_PROGRESS_EVERY=250)
    for i in range(251):
        conn.execute(
            "INSERT INTO wa_messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("acct-1", "chat-1@c.us", f"m{i}", "Alice", None, 0, f"body{i}",
             int(1_700_000_000 + i), "chat", "cdp-indexeddb", 1),
        )
    conn.commit()
    conn.close()

    monkeypatch.setattr(message_sync, "_openhuman_whatsapp_db_path", lambda: db_path)
    stats = message_sync.sync_whatsapp_bootstrap(store)
    assert stats == {"acct-1": 251}


def test_sync_linkedin_bootstrap_progress_update_fires_at_progress_interval(
    tmp_path, monkeypatch
):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    db_path = tmp_path / "openhuman" / "workspace" / "linkedin_data" / "linkedin_data.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE li_threads (
            account_id TEXT NOT NULL, thread_id TEXT NOT NULL,
            display_name TEXT NOT NULL DEFAULT '',
            profile_url TEXT NOT NULL DEFAULT '',
            last_message_ts INTEGER NOT NULL DEFAULT 0,
            message_count INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (account_id, thread_id)
        );
        CREATE TABLE li_messages (
            account_id TEXT NOT NULL, thread_id TEXT NOT NULL,
            message_id TEXT NOT NULL, sender TEXT NOT NULL DEFAULT '',
            sender_profile_url TEXT, from_me INTEGER NOT NULL DEFAULT 0,
            body TEXT NOT NULL DEFAULT '', timestamp INTEGER NOT NULL DEFAULT 0,
            source_url TEXT, ingested_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (account_id, thread_id, message_id)
        );
        """
    )
    conn.execute(
        "INSERT INTO li_threads VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("acct-li", "thread-1", "Alice Recruiter",
         "https://www.linkedin.com/in/alice/", 1_700_000_100, 2, 1_700_000_100),
    )
    # Insert enough messages to trigger at least one progress update (LINKEDIN_PROGRESS_EVERY=250)
    for i in range(251):
        conn.execute(
            "INSERT INTO li_messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("acct-li", "thread-1", f"m{i}", "", None, 1, f"body{i}",
             int(1_700_000_000 + i),
             "https://www.linkedin.com/messaging/thread/thread-1/", 1),
        )
    conn.commit()
    conn.close()

    monkeypatch.setattr(message_sync, "_openhuman_linkedin_db_path", lambda: db_path)
    stats = message_sync.sync_linkedin_bootstrap(store)
    assert stats == {"acct-li": 251}


# ---------------------------------------------------------------------------
# Direct tests for smoke_contract + build_parser (subprocess tests only
# exercise these indirectly through CLI args)
# ---------------------------------------------------------------------------


def test_smoke_contract_returns_expected_shape():
    result = message_sync.smoke_contract()
    assert result["ok"] is True
    assert result["entrypoint"] == "message_sync.py"
    assert set(result["modes"]) == {"bootstrap", "incremental", "rebuild", "summary"}


def test_build_parser_smoke_flag():
    parser = message_sync.build_parser()
    args = parser.parse_args(["--smoke"])
    assert args.smoke is True
    assert args.mode is None


def test_build_parser_mode_argument():
    parser = message_sync.build_parser()
    args = parser.parse_args(["bootstrap"])
    assert args.mode == "bootstrap"
    assert not args.smoke


def test_build_parser_invalid_mode_raises():
    parser = message_sync.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["bogus"])


# ---------------------------------------------------------------------------
# _create_imessage_db — helper for _imessage_messages_after tests
# ---------------------------------------------------------------------------


def _create_imessage_db(db_path: Path) -> None:
    """Create a minimal iMessage chat.db for testing _imessage_messages_after."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE message (
            rowid INTEGER PRIMARY KEY,
            text TEXT,
            is_from_me INTEGER NOT NULL DEFAULT 0,
            date INTEGER NOT NULL DEFAULT 0,
            handle_id INTEGER
        );
        CREATE TABLE chat_message_join (
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL
        );
        CREATE TABLE handle (
            rowid INTEGER PRIMARY KEY,
            id TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO message (rowid, text, is_from_me, date, handle_id) VALUES (?, ?, ?, ?, ?)",
        [
            (1, "Hello from Alice", 0, 700000000000000000, 1),
            (2, "Reply to Alice", 1, 700000001000000000, None),
            (3, None, 0, 700000002000000000, 1),  # NULL text — still returned by query
        ],
    )
    conn.executemany(
        "INSERT INTO chat_message_join (chat_id, message_id) VALUES (?, ?)",
        [(42, 1), (42, 2), (42, 3)],
    )
    conn.execute("INSERT INTO handle (rowid, id) VALUES (1, '+15551234567')")
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# _imessage_messages_after — lines 471-488
# ---------------------------------------------------------------------------


def test_imessage_messages_after_db_not_exists(monkeypatch):
    """When IMSG_DB doesn't exist, returns empty list (lines 472-473)."""
    monkeypatch.setattr(message_sync, "IMSG_DB", Path("/nonexistent/chat.db"))
    result = message_sync._imessage_messages_after()
    assert result == []


def test_imessage_messages_after_no_filter(tmp_path, monkeypatch):
    """Temp iMessage DB with no last_rowid — returns messages with non-NULL text."""
    db_path = tmp_path / "chat.db"
    _create_imessage_db(db_path)
    monkeypatch.setattr(message_sync, "IMSG_DB", db_path)

    result = message_sync._imessage_messages_after()
    # Row 3 has NULL text → excluded by WHERE m.text IS NOT NULL
    assert len(result) == 2
    assert result[0]["text"] == "Hello from Alice"
    assert result[0]["message_rowid"] == 1
    assert result[0]["chat_id"] == 42
    assert result[0]["is_from_me"] == 0
    assert result[0]["sender_id"] == "+15551234567"
    # Row 2: is_from_me=1, sender_id is None (handle_id is NULL → LEFT JOIN returns NULL)
    assert result[1]["text"] == "Reply to Alice"
    assert result[1]["message_rowid"] == 2
    assert result[1]["is_from_me"] == 1
    assert result[1]["sender_id"] is None


def test_imessage_messages_after_with_last_rowid(tmp_path, monkeypatch):
    """Temp iMessage DB with last_rowid=1 — returns only messages with rowid > 1 AND non-NULL text."""
    db_path = tmp_path / "chat.db"
    _create_imessage_db(db_path)
    monkeypatch.setattr(message_sync, "IMSG_DB", db_path)

    result = message_sync._imessage_messages_after(last_rowid=1)
    # Row 2 has text, Row 3 has NULL text → only row 2 returned
    assert len(result) == 1
    assert result[0]["message_rowid"] == 2
    assert result[0]["text"] == "Reply to Alice"


def test_imessage_messages_after_no_matches(tmp_path, monkeypatch):
    """DB exists but no messages after a large last_rowid — returns empty list."""
    db_path = tmp_path / "chat.db"
    _create_imessage_db(db_path)
    monkeypatch.setattr(message_sync, "IMSG_DB", db_path)

    result = message_sync._imessage_messages_after(last_rowid=999)
    assert result == []


# ---------------------------------------------------------------------------
# _sync_imessage_from_local_store exception handling — lines 547-549
# ---------------------------------------------------------------------------


def test_sync_imessage_from_local_store_records_error_and_raises(
    tmp_path, monkeypatch
):
    """When _imessage_messages_after raises, record_sync_error is called and exception propagates."""
    store = MessageIndexStore(tmp_path / "index.sqlite3")

    monkeypatch.setattr(
        message_sync,
        "_imessage_messages_after",
        lambda _: (_ for _ in ()).throw(RuntimeError("disk full")),
    )

    with pytest.raises(RuntimeError, match="disk full"):
        message_sync.sync_imessage_incremental(store)

    # Verify error was recorded via sync state
    state = store.get_sync_state("imessage", "local")
    assert state is not None
    assert state.get("last_error") == "disk full"
    assert state["status"] == "error"


def test_sync_imessage_bootstrap_records_error_and_raises(
    tmp_path, monkeypatch
):
    """Same as above but via the bootstrap (full_sync=True) path."""
    store = MessageIndexStore(tmp_path / "index.sqlite3")

    monkeypatch.setattr(
        message_sync,
        "_imessage_messages_after",
        lambda _: (_ for _ in ()).throw(OSError("permission denied")),
    )

    with pytest.raises(OSError, match="permission denied"):
        message_sync.sync_imessage_bootstrap(store)

    state = store.get_sync_state("imessage", "local")
    assert state is not None
    assert state.get("last_error") == "permission denied"
    assert state["status"] == "error"


# ---------------------------------------------------------------------------
# bootstrap() — lines 834-852
# ---------------------------------------------------------------------------


def test_bootstrap_calls_all_four_syncs(tmp_path, monkeypatch):
    """bootstrap() invokes gmail, imessage, whatsapp, and linkedin bootstrap."""
    store = MessageIndexStore(tmp_path / "index.sqlite3")

    monkeypatch.setattr(
        message_sync, "sync_gmail_bootstrap", lambda s: {"acct@x.com": 3}
    )
    monkeypatch.setattr(
        message_sync, "sync_imessage_bootstrap", lambda s: {"local": 10}
    )
    monkeypatch.setattr(
        message_sync, "sync_whatsapp_bootstrap", lambda s: {"wa-acct": 5}
    )
    monkeypatch.setattr(
        message_sync, "sync_linkedin_bootstrap", lambda s: {"li-acct": 2}
    )

    # accept any rebuild_changed_threads call without error
    monkeypatch.setattr(message_sync, "rebuild_changed_threads", lambda s, scopes: None)

    result = message_sync.bootstrap(store)

    assert result == {
        "gmail": {"acct@x.com": 3},
        "imessage": {"local": 10},
        "whatsapp": {"wa-acct": 5},
        "linkedin": {"li-acct": 2},
    }


def test_bootstrap_skips_empty_scopes(tmp_path, monkeypatch):
    """rebuild_changed_threads only receives sources with non-zero counts."""
    store = MessageIndexStore(tmp_path / "index.sqlite3")

    monkeypatch.setattr(message_sync, "sync_gmail_bootstrap", lambda s: {})
    monkeypatch.setattr(message_sync, "sync_imessage_bootstrap", lambda s: {"local": 1})
    monkeypatch.setattr(message_sync, "sync_whatsapp_bootstrap", lambda s: {})
    monkeypatch.setattr(
        message_sync, "sync_linkedin_bootstrap", lambda s: {"li-acct": 3}
    )

    captured_scopes: list[set] = []

    def _fake_rebuild(store, scopes):
        captured_scopes.append(scopes)

    monkeypatch.setattr(message_sync, "rebuild_changed_threads", _fake_rebuild)

    result = message_sync.bootstrap(store)

    assert result["gmail"] == {}
    assert result["whatsapp"] == {}
    assert len(captured_scopes) == 1
    combined = captured_scopes[0]
    assert ("imessage", "local") in combined
    assert ("linkedin", "li-acct") in combined
    assert ("gmail", "acct@x.com") not in combined


def test_bootstrap_rebuilds_all_sources_combined(tmp_path, monkeypatch):
    """When all sources return items, rebuild_changed_threads sees all scopes."""
    store = MessageIndexStore(tmp_path / "index.sqlite3")

    monkeypatch.setattr(
        message_sync, "sync_gmail_bootstrap", lambda s: {"g1": 1, "g2": 2}
    )
    monkeypatch.setattr(
        message_sync, "sync_imessage_bootstrap", lambda s: {"local": 1}
    )
    monkeypatch.setattr(
        message_sync, "sync_whatsapp_bootstrap", lambda s: {"w1": 1}
    )
    monkeypatch.setattr(
        message_sync, "sync_linkedin_bootstrap", lambda s: {}
    )

    captured_scopes: list[set] = []
    monkeypatch.setattr(
        message_sync,
        "rebuild_changed_threads",
        lambda s, scopes: captured_scopes.append(scopes),
    )

    message_sync.bootstrap(store)

    assert len(captured_scopes) == 1
    combined = captured_scopes[0]
    assert combined == {
        ("gmail", "g1"),
        ("gmail", "g2"),
        ("imessage", "local"),
        ("whatsapp", "w1"),
    }


# ---------------------------------------------------------------------------
# print_summary — lines 876-878
# ---------------------------------------------------------------------------


def test_print_summary_with_threads(tmp_path, capsys):
    """print_summary prints ordered rows from the store."""
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    store.upsert_item(
        _indexed_item(
            source="gmail",
            account="acct@x.com",
            external_id="m1",
            thread_id="t1",
            created_at="2026-07-01T10:00:00+00:00",
            subject="Team lunch",
        )
    )
    store.upsert_item(
        _indexed_item(
            source="imessage",
            account="local",
            external_id="m2",
            thread_id="t2",
            created_at="2026-07-01T11:00:00+00:00",
            subject="Hey",
        )
    )
    store.rebuild_threads()

    message_sync.print_summary(store, limit=10)
    out = capsys.readouterr().out
    assert out != ""
    # Output contains source labels
    assert "gmail" in out or "imessage" in out


def test_print_summary_no_threads(tmp_path, capsys):
    """print_summary with empty store prints nothing."""
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    message_sync.print_summary(store, limit=10)
    out = capsys.readouterr().out
    # No threads → loop body never executes → no output
    assert out == ""


# ---------------------------------------------------------------------------
# main() — lines 907-927
# ---------------------------------------------------------------------------


def test_main_smoke_flag(capsys):
    """--smoke prints smoke contract JSON and returns 0."""
    rc = message_sync.main(["--smoke"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    data = json.loads(out)
    assert data["ok"] is True


def test_main_bootstrap_mode(tmp_path, monkeypatch, capsys):
    """main with 'bootstrap' mode calls bootstrap and prints result."""
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    monkeypatch.setattr(
        message_sync, "MessageIndexStore", lambda db_path: store
    )
    monkeypatch.setattr(
        message_sync,
        "bootstrap",
        lambda s: {"gmail": {}, "imessage": {"local": 5}, "whatsapp": {}, "linkedin": {}},
    )
    monkeypatch.setattr(message_sync, "rebuild_changed_threads", lambda s, sc: None)

    rc = message_sync.main(["bootstrap"])
    assert rc == 0
    assert "local" in capsys.readouterr().out


def test_main_incremental_mode(tmp_path, monkeypatch, capsys):
    """main with 'incremental' mode calls incremental and prints result."""
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    monkeypatch.setattr(
        message_sync, "MessageIndexStore", lambda db_path: store
    )
    monkeypatch.setattr(
        message_sync,
        "incremental",
        lambda s: {"gmail": {"acct@x.com": 1}, "imessage": {}, "whatsapp": {}, "linkedin": {}},
    )
    monkeypatch.setattr(message_sync, "rebuild_changed_threads", lambda s, sc: None)

    rc = message_sync.main(["incremental"])
    assert rc == 0
    assert "acct@x.com" in capsys.readouterr().out


def test_main_rebuild_mode(tmp_path, monkeypatch, capsys):
    """main with 'rebuild' mode calls rebuild_all_threads and prints result."""
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    monkeypatch.setattr(
        message_sync, "MessageIndexStore", lambda db_path: store
    )
    monkeypatch.setattr(message_sync, "rebuild_all_threads", lambda s: 7)

    rc = message_sync.main(["rebuild"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert "7" in out


def test_main_summary_mode(tmp_path, monkeypatch, capsys):
    """main with 'summary' mode calls print_summary."""
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    monkeypatch.setattr(
        message_sync, "MessageIndexStore", lambda db_path: store
    )
    monkeypatch.setattr(message_sync, "print_summary", lambda s, limit: None)

    rc = message_sync.main(["summary"])
    assert rc == 0


def test_main_missing_mode_without_smoke(tmp_path, monkeypatch, capsys):
    """main exits with error when no mode is given without --smoke."""
    with pytest.raises(SystemExit) as exc_info:
        message_sync.main([])
    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "mode is required" in captured.err.lower() or "error" in captured.err.lower()


def test_main_custom_db_path(tmp_path, monkeypatch, capsys):
    """--db flag is passed to MessageIndexStore."""
    db_path = tmp_path / "custom.sqlite3"
    captured_db: list[Path | None] = []

    class _CapturingStore:
        def __init__(self, p):
            captured_db.append(p)

    monkeypatch.setattr(message_sync, "MessageIndexStore", _CapturingStore)
    monkeypatch.setattr(message_sync, "print_summary", lambda s, limit: None)

    message_sync.main(["--db", str(db_path), "summary"])
    assert len(captured_db) == 1
    assert captured_db[0] == db_path


def test_main_custom_limit(tmp_path, monkeypatch):
    """--limit flag is passed to print_summary."""
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    monkeypatch.setattr(
        message_sync, "MessageIndexStore", lambda db_path: store
    )

    captured_limit: list[int] = []

    def _fake_summary(s, limit):
        captured_limit.append(limit)

    monkeypatch.setattr(message_sync, "print_summary", _fake_summary)

    message_sync.main(["--limit", "42", "summary"])
    assert captured_limit == [42]
