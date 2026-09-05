import sqlite3

from event_store import RawEvent, RawEventStore
from message_index_store import IndexedItem
from message_sync import _append_raw_message_event


def test_raw_event_store_is_append_only_and_idempotent(tmp_path):
    store = RawEventStore(tmp_path / "events.sqlite3")
    event = RawEvent.create(
        event_id="evt_test_1",
        source="manual",
        source_object_id="capture-1",
        observed_at="2026-08-25T15:00:00+00:00",
        occurred_at="2026-08-25T14:59:00+00:00",
        event_type="manual.capture",
        payload={"text": "Nathan said 100 drones may cost $6 each."},
        provenance={"channel": "test"},
        confidence=0.7,
    )

    stored, inserted = store.append(event)
    duplicate, duplicate_inserted = store.append(event)

    assert inserted is True
    assert duplicate_inserted is False
    assert duplicate.event_id == stored.event_id == "evt_test_1"
    assert store.count() == 1
    assert store.get("evt_test_1").to_dict()["payload"]["text"].startswith("Nathan")
    assert not hasattr(store, "update")
    assert not hasattr(store, "delete")

    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_raw_event_store_keeps_changed_observations_as_distinct_events(tmp_path):
    store = RawEventStore(tmp_path / "events.sqlite3")
    for event_id, text in (("evt_a", "first"), ("evt_b", "second")):
        store.append(
            RawEvent.create(
                event_id=event_id,
                source="gmail",
                source_object_id="message-1",
                observed_at="2026-08-25T15:00:00+00:00",
                occurred_at="2026-08-25T14:59:00+00:00",
                event_type="message.received",
                payload={"text": text},
            )
        )

    events = store.list_recent(source="gmail", event_type="message.received")
    assert [event.payload["text"] for event in events] == ["second", "first"]
    assert store.count(source="gmail") == 2


def test_message_sync_can_emit_a_provenance_bound_raw_event(tmp_path):
    store = RawEventStore(tmp_path / "events.sqlite3")
    item = IndexedItem(
        source="imessage",
        account="local",
        external_id="27631",
        thread_id="27",
        kind="imessage",
        created_at="2026-08-25T14:58:20+00:00",
        updated_at="2026-08-25T14:58:20+00:00",
        ingested_at="2026-08-25T15:00:00+00:00",
        sender="Me",
        recipients_json="[]",
        subject="",
        snippet="Yes I meant 10 cents",
        body_text="Yes I meant 10 cents",
        body_hash="hash",
        labels_json="[]",
        raw_pointer="imessage:27:27631",
    )

    _append_raw_message_event(store, item, {"message_rowid": 27631, "text": item.body_text})

    event = store.list_recent(limit=1)[0]
    assert event.source_object_id == "local:27631"
    assert event.content_ref == "imessage:27:27631"
    assert event.provenance == {"adapter": "message_sync", "source": "imessage"}
