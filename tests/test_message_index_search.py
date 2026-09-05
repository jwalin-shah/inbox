from __future__ import annotations

from datetime import UTC, datetime

from message_index_store import IndexedItem, MessageIndexStore


def _item(external_id: str, subject: str, body: str) -> IndexedItem:
    now = datetime.now(UTC).isoformat()
    return IndexedItem(
        source="imessage",
        account="local",
        external_id=external_id,
        thread_id=f"thread-{external_id}",
        kind="message",
        created_at=now,
        updated_at=now,
        ingested_at=now,
        sender="Harsh",
        recipients_json="[]",
        subject=subject,
        snippet=body[:100],
        body_text=body,
        body_hash=external_id,
        labels_json="[]",
        raw_pointer=f"imessage:local:{external_id}",
    )


def test_keyword_search_preserves_source_identity(tmp_path):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    store.upsert_item(_item("one", "Street play practice", "Meet at the pickup address."))
    store.upsert_item(_item("two", "Groceries", "Buy apples and milk."))

    results = store.search_items("street play", limit=10)

    assert [result["external_id"] for result in results] == ["one"]
    assert results[0]["source"] == "imessage"
    assert results[0]["raw_pointer"] == "imessage:local:one"


def test_deleted_items_are_not_returned_or_reindexed(tmp_path):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    item = _item("one", "Street play practice", "Meet at the pickup address.")
    store.upsert_item(item)
    item.is_deleted = 1
    store.upsert_item(item)

    assert store.search_items("street play") == []


def test_embedding_search_orders_by_cosine_similarity(tmp_path):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    store.upsert_item(_item("one", "Calendar", "Practice at the field."))
    store.upsert_item(_item("two", "Dinner", "Dinner reservation tonight."))
    store.upsert_embedding(item_id=1, model_id="test", content_hash="a", vector=[1.0, 0.0])
    store.upsert_embedding(item_id=2, model_id="test", content_hash="b", vector=[0.0, 1.0])

    results = store.search_embeddings([0.9, 0.1], model_id="test", limit=2)

    assert [result["external_id"] for result in results] == ["one", "two"]
    assert results[0]["semantic_score"] > results[1]["semantic_score"]
    assert store.embedding_status("test") == {"items": 2, "embedded": 2, "pending": 0}


def test_changed_message_invalidates_derived_embedding(tmp_path):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    item = _item("one", "Calendar", "Practice at the field.")
    store.upsert_item(item)
    store.upsert_embedding(item_id=1, model_id="test", content_hash="a", vector=[1.0, 0.0])

    item.body_text = "Practice moved to the gym."
    item.body_hash = "changed"
    store.upsert_item(item)

    assert store.embedding_status("test") == {"items": 1, "embedded": 0, "pending": 1}
