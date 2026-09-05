import sqlite3

from event_backfill import backfill_message_index
from event_store import RawEventStore
from message_index_store import IndexedItem, MessageIndexStore


def _item(row_id: int) -> IndexedItem:
    return IndexedItem(
        source="imessage",
        account="local",
        external_id=str(row_id),
        thread_id="thread-1",
        kind="imessage",
        created_at=f"2026-08-25T15:0{row_id}:00+00:00",
        updated_at=f"2026-08-25T15:0{row_id}:00+00:00",
        ingested_at="2026-08-25T15:30:00+00:00",
        sender="Me",
        recipients_json="[]",
        subject="",
        snippet=f"message {row_id}",
        body_text=f"message {row_id}",
        body_hash=f"hash-{row_id}",
        labels_json="[]",
        raw_pointer=f"imessage:thread-1:{row_id}",
    )


def test_message_index_backfill_resumes_and_dedupes(tmp_path):
    index_store = MessageIndexStore(tmp_path / "index.sqlite3")
    for row_id in (1, 2, 3):
        index_store.upsert_item(_item(row_id))
    event_store = RawEventStore(tmp_path / "events.sqlite3")

    first = backfill_message_index(
        index_store.db_path,
        event_store,
        source="imessage",
        batch_size=2,
        max_items=2,
    )
    second = backfill_message_index(
        index_store.db_path,
        event_store,
        source="imessage",
        batch_size=2,
    )
    third = backfill_message_index(index_store.db_path, event_store, source="imessage")

    assert first.status == "paused"
    assert first.complete is False
    assert first.inserted_this_run == 2
    assert second.status == "completed"
    assert second.inserted_this_run == 1
    assert second.processed_total == 3
    assert third.scanned_this_run == 0
    assert third.inserted_this_run == 0
    assert event_store.count(source="imessage") == 3
    state = event_store.get_backfill_state("message-index-v1:imessage:all")
    assert state["status"] == "completed"
    assert state["last_item_id"] == 3

    with sqlite3.connect(event_store.db_path) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_backfill_marks_index_provenance_as_not_raw(tmp_path):
    index_store = MessageIndexStore(tmp_path / "index.sqlite3")
    index_store.upsert_item(_item(1))
    event_store = RawEventStore(tmp_path / "events.sqlite3")

    backfill_message_index(index_store.db_path, event_store, max_items=1)

    event = event_store.list_recent(limit=1)[0]
    assert event.event_type == "message.indexed_backfill"
    assert event.provenance["raw_payload_available"] is False
    assert event.payload["indexed_item"]["external_id"] == "1"
