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


class _FakeUsersApi:
    def __init__(self, list_payloads, full_messages):
        self._messages_api = _FakeMessagesApi(list_payloads, full_messages)

    def messages(self):
        return self._messages_api


class _FakeGmailService:
    def __init__(self, list_payloads, full_messages):
        self._users_api = _FakeUsersApi(list_payloads, full_messages)

    def users(self):
        return self._users_api


def _gmail_message(message_id: str, internal_date: int, *, thread_id: str | None = None):
    return {
        "id": message_id,
        "threadId": thread_id or message_id,
        "internalDate": str(internal_date),
        "snippet": f"snippet-{message_id}",
        "labelIds": ["INBOX"],
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
