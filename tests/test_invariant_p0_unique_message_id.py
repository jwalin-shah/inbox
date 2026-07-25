"""P0 Invariant 4.1: Unique message ID.

Tensor equation:
    forall message: has(unique_id)
    and not exists message2: (message2.unique_id == message.unique_id) and (message2 != message)

Every message across all sources must have a unique (source, account, external_id)
tuple. The MessageIndexStore enforces this via a UNIQUE constraint on the items
table. Duplicate insertions are either silently merged (upsert_item) or rejected
(insert_item_if_absent).

The invariant also requires that no duplicate IDs exist in the index after any
sync operation — i.e., every message has exactly one row.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from message_index_store import IndexedItem, MessageIndexStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _item(
    *,
    source: str = "gmail",
    account: str = "a@example.com",
    external_id: str = "msg-1",
    thread_id: str = "thread-1",
    sender: str = "Alice",
    subject: str = "Hello",
    body: str = "World",
    created_at: str = "2026-04-18T00:00:00+00:00",
    is_read: int = 0,
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
        sender=sender,
        recipients_json="[]",
        subject=subject,
        snippet=subject or body[:50],
        body_text=body,
        body_hash=f"hash-{external_id}",
        labels_json="[]",
        raw_pointer=f"{source}:{external_id}",
        is_deleted=0,
        is_read=is_read,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestInvariantP0UniqueMessageId:
    """Invariant 4.1: Every message has a unique (source, account, external_id)."""

    # ── insert_item_if_absent path ───────────────────────────────────────

    def test_insert_item_if_absent_returns_true_for_new(self, tmp_path: Path) -> None:
        """insert_item_if_absent returns True when inserting a new item."""
        store = MessageIndexStore(tmp_path / "index.sqlite3")
        item = _item(external_id="new-msg")

        result = store.insert_item_if_absent(item)

        assert result is True, "First insert of a unique ID should return True"

    def test_insert_item_if_absent_returns_false_for_duplicate(
        self, tmp_path: Path
    ) -> None:
        """insert_item_if_absent returns False when the ID already exists.

        This is the core of the invariant: the store must reject duplicate
        IDs and signal that the item already existed.
        """
        store = MessageIndexStore(tmp_path / "index.sqlite3")
        item = _item(external_id="dup-msg")

        first = store.insert_item_if_absent(item)
        second = store.insert_item_if_absent(item)

        assert first is True, "First insert should succeed"
        assert second is False, "Duplicate insert MUST return False"

    def test_insert_item_if_absent_does_not_update_on_duplicate(
        self, tmp_path: Path
    ) -> None:
        """insert_item_if_absent preserves the original data on duplicate.

        Using ON CONFLICT DO NOTHING, the original subject should remain.
        """
        store = MessageIndexStore(tmp_path / "index.sqlite3")
        original = _item(external_id="dup-msg", subject="Original")
        duplicate = _item(external_id="dup-msg", subject="Modified")

        store.insert_item_if_absent(original)
        store.insert_item_if_absent(duplicate)

        store.rebuild_threads()
        rows = store.list_threads(limit=10)
        assert rows[0]["latest_subject"] == "Original"

    # ── upsert_item path (idempotent, merges on conflict) ────────────────

    def test_upsert_item_is_idempotent(self, tmp_path: Path) -> None:
        """upsert_item with the same ID twice produces exactly one row."""
        store = MessageIndexStore(tmp_path / "index.sqlite3")
        item = _item(external_id="idempotent-msg")

        store.upsert_item(item)
        store.upsert_item(item)

        with store._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        assert count == 1, "Duplicate upsert must not create extra rows"

    def test_upsert_item_updates_on_conflict(self, tmp_path: Path) -> None:
        """upsert_item replaces the existing row on duplicate ID.

        This is the expected behavior for sync operations: the new data
        replaces the old, but the row count stays the same.
        """
        store = MessageIndexStore(tmp_path / "index.sqlite3")
        original = _item(external_id="update-msg", subject="Original")
        updated = _item(external_id="update-msg", subject="Updated")

        store.upsert_item(original)
        store.upsert_item(updated)
        store.rebuild_threads()

        rows = store.list_threads(limit=10)
        assert rows[0]["latest_subject"] == "Updated"

        with store._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        assert count == 1, "upsert on existing ID must not create extra rows"

    # ── Database-level constraint ────────────────────────────────────────

    def test_database_has_unique_constraint(self, tmp_path: Path) -> None:
        """The items table enforces a UNIQUE constraint on (source, account, external_id).

        This constraint is the last line of defense against duplicate IDs.
        The CREATE TABLE statement includes UNIQUE(source, account, external_id).
        We verify this by checking the CREATE TABLE SQL in sqlite_master.
        """
        store = MessageIndexStore(tmp_path / "index.sqlite3")
        with store._connect() as conn:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND tbl_name='items'"
            ).fetchone()
        create_sql = row[0] if row else ""
        assert "UNIQUE" in create_sql.upper(), (
            "items table must have a UNIQUE constraint. "
            f"CREATE TABLE SQL: {create_sql}"
        )
        assert "source" in create_sql, (
            "UNIQUE constraint must include source. "
            f"CREATE TABLE SQL: {create_sql}"
        )
        assert "account" in create_sql, (
            "UNIQUE constraint must include account. "
            f"CREATE TABLE SQL: {create_sql}"
        )
        assert "external_id" in create_sql, (
            "UNIQUE constraint must include external_id. "
            f"CREATE TABLE SQL: {create_sql}"
        )

    # ── Cross-source uniqueness ──────────────────────────────────────────

    def test_different_sources_can_have_same_external_id(self, tmp_path: Path) -> None:
        """Different sources can share the same external_id (they have different source fields).

        The uniqueness is per (source, account, external_id), not global.
        """
        store = MessageIndexStore(tmp_path / "index.sqlite3")
        gmail_item = _item(source="gmail", external_id="42")
        imessage_item = _item(source="imessage", account="local", external_id="42")

        store.upsert_item(gmail_item)
        store.upsert_item(imessage_item)

        with store._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        assert count == 2, "Different sources with same external_id must coexist"

    def test_different_accounts_can_have_same_external_id(self, tmp_path: Path) -> None:
        """Different accounts under the same source can share the same external_id."""
        store = MessageIndexStore(tmp_path / "index.sqlite3")
        acct1 = _item(account="a@example.com", external_id="99")
        acct2 = _item(account="b@example.com", external_id="99")

        store.upsert_item(acct1)
        store.upsert_item(acct2)

        with store._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        assert count == 2, "Different accounts with same external_id must coexist"

    # ── No duplicate rows after sync operations ──────────────────────────

    def test_no_duplicate_messages_after_sync_like_operations(self, tmp_path: Path) -> None:
        """After repeated sync-like operations, the item count is exact.

        This simulates what happens during a real sync: the same message
        may be fetched multiple times, but the store must not create
        duplicate rows.
        """
        store = MessageIndexStore(tmp_path / "index.sqlite3")

        # Simulate a bootstrap sync that inserts 5 items
        for i in range(5):
            store.upsert_item(_item(external_id=f"sync-msg-{i}"))

        # Simulate an incremental sync that re-fetches some of the same messages
        store.upsert_item(_item(external_id="sync-msg-0", subject="Updated"))
        store.upsert_item(_item(external_id="sync-msg-2", subject="Also updated"))
        store.insert_item_if_absent(_item(external_id="sync-msg-4"))

        with store._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]

        # The count must be exactly 5 — no duplicates created
        assert count == 5, (
            f"Expected exactly 5 items after sync operations, got {count}. "
            f"Duplicate rows violate Invariant 4.1."
        )

    def test_unique_constraint_rejects_duplicate_via_direct_sql(self, tmp_path: Path) -> None:
        """Direct SQL insertion of a duplicate must raise IntegrityError.

        This tests the database-level enforcement, not just the application
        layer. If someone bypasses the store and inserts directly, the
        constraint must still catch it.
        """
        db_path = tmp_path / "index.sqlite3"
        store = MessageIndexStore(db_path)
        store.upsert_item(_item(external_id="direct-test"))

        # Direct SQL insertion bypassing the store — must raise IntegrityError
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint"):
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    """
                    INSERT INTO items (source, account, external_id, thread_id, kind,
                        created_at, updated_at, ingested_at, sender, recipients_json,
                        subject, snippet, body_text, body_hash, labels_json, raw_pointer,
                        is_deleted, is_read)
                    VALUES ('gmail', 'a@example.com', 'direct-test', 't1', 'email',
                        '2026-04-18T00:00:00', '2026-04-18T00:00:00', '2026-04-18T00:00:00',
                        'Me', '[]', 'Dup', '', '', 'hash', '[]', '',
                        0, 0)
                    """
                )

        # Verify the original row is intact
        with store._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        assert count == 1, (
            "The UNIQUE constraint must prevent duplicate rows"
        )

    def test_index_counts_are_accurate_after_duplicate_handling(self, tmp_path: Path) -> None:
        """index_counts() returns the correct item count after duplicate handling.

        This validates that the application-level dedup logic is working
        correctly — the reported counts match the actual rows.
        """
        store = MessageIndexStore(tmp_path / "index.sqlite3")

        # Insert 5 unique items
        for i in range(5):
            store.upsert_item(_item(external_id=f"count-msg-{i}"))

        # Try to insert duplicates
        for i in range(5):
            store.insert_item_if_absent(_item(external_id=f"count-msg-{i}"))

        counts = store.index_counts()
        assert counts["items"] == 5, (
            f"Expected 5 items after duplicate insertion, got {counts['items']}"
        )