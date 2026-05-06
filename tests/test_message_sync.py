import sqlite3

import pytest

import message_sync
from message_index_store import MessageIndexStore


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
                {"name": "To", "value": "acct@example.com"},
                {"name": "Subject", "value": f"Subject {message_id}"},
            ],
            "parts": [],
            "body": {"data": ""},
        },
    }


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
