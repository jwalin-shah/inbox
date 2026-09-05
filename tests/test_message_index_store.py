import sqlite3

from message_index_store import IndexedItem, MessageIndexStore


def _item(
    *,
    source: str,
    account: str,
    external_id: str,
    thread_id: str,
    sender: str,
    subject: str = "",
    body: str = "",
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


def test_upsert_item_replaces_existing_row(tmp_path):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    original = _item(
        source="gmail",
        account="a@example.com",
        external_id="m1",
        thread_id="t1",
        sender="Recruiter",
        subject="Initial",
    )
    updated = _item(
        source="gmail",
        account="a@example.com",
        external_id="m1",
        thread_id="t1",
        sender="Recruiter",
        subject="Updated subject",
    )

    store.upsert_item(original)
    store.upsert_item(updated)
    store.rebuild_threads()

    rows = store.list_threads(limit=5)
    assert len(rows) == 1
    assert rows[0]["latest_subject"] == "Updated subject"


def test_rebuild_threads_marks_human_reply_as_actionable(tmp_path):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    store.upsert_item(
        _item(
            source="gmail",
            account="a@example.com",
            external_id="m1",
            thread_id="t1",
            sender="Me",
            subject="Reaching out",
            created_at="2026-04-18T00:00:00+00:00",
            is_read=1,
        )
    )
    store.upsert_item(
        _item(
            source="gmail",
            account="a@example.com",
            external_id="m2",
            thread_id="t1",
            sender="Mehak Bhatia",
            subject="Consulting opportunity",
            body="Would you be open to a short call?",
            created_at="2026-04-18T01:00:00+00:00",
            is_read=0,
        )
    )

    store.rebuild_threads()
    rows = store.list_threads(limit=5, actionable_only=True)
    assert len(rows) == 1
    assert rows[0]["actionability"] == "reply"
    assert rows[0]["needs_reply"] == 1
    assert rows[0]["topic"] == "opportunity"


def test_rebuild_threads_classifies_otp_as_ignore(tmp_path):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    store.upsert_item(
        _item(
            source="imessage",
            account="local",
            external_id="1",
            thread_id="chat-1",
            sender="22395",
            body="Your verification code is: 995228",
        )
    )

    store.rebuild_threads()
    rows = store.list_threads(limit=5)
    assert len(rows) == 1
    assert rows[0]["noise_class"] == "otp"
    assert rows[0]["actionability"] == "ignore"


def test_rebuild_threads_uses_frequent_human_sender_stats(tmp_path):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    sender = "5551234567"
    store.upsert_item(
        _item(
            source="imessage",
            account="local",
            external_id="h1-me",
            thread_id="history-1",
            sender="Me",
            body="Following up from earlier.",
            created_at="2026-04-17T00:00:00+00:00",
            is_read=1,
        )
    )
    store.upsert_item(
        _item(
            source="imessage",
            account="local",
            external_id="h1-them",
            thread_id="history-1",
            sender=sender,
            body="Thanks.",
            created_at="2026-04-17T01:00:00+00:00",
            is_read=1,
        )
    )
    store.upsert_item(
        _item(
            source="imessage",
            account="local",
            external_id="h2-me",
            thread_id="history-2",
            sender="Me",
            body="Can you send that over?",
            created_at="2026-04-17T02:00:00+00:00",
            is_read=1,
        )
    )
    store.upsert_item(
        _item(
            source="imessage",
            account="local",
            external_id="h2-them",
            thread_id="history-2",
            sender=sender,
            body="Will do.",
            created_at="2026-04-17T03:00:00+00:00",
            is_read=1,
        )
    )
    store.upsert_item(
        _item(
            source="imessage",
            account="local",
            external_id="current",
            thread_id="current-thread",
            sender=sender,
            body="Quick FYI for later.",
            created_at="2026-04-18T00:00:00+00:00",
            is_read=0,
        )
    )

    store.rebuild_threads()

    rows = store.list_threads(limit=10)
    current = next(row for row in rows if row["thread_id"] == "current-thread")
    human_score = current["human_score"]
    assert isinstance(human_score, float)
    assert human_score < 1.0
    assert current["actionability"] == "reply"
    assert current["needs_reply"] == 1
    with store._connect() as conn:
        stats = conn.execute("SELECT * FROM sender_stats WHERE email = ?", (sender,)).fetchone()
    assert stats["thread_count"] == 3
    assert stats["reply_count"] == 2


def test_rebuild_threads_does_not_promote_high_volume_automated_sender(tmp_path):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    sender = "no-reply@example.com"
    for index in range(12):
        store.upsert_item(
            _item(
                source="gmail",
                account="a@example.com",
                external_id=f"auto-{index}",
                thread_id=f"auto-thread-{index}",
                sender=sender,
                subject="Account update",
                body="This is an automated notification.",
                created_at=f"2026-04-18T00:{index:02d}:00+00:00",
                is_read=0,
            )
        )

    store.rebuild_threads()

    rows = store.list_threads(limit=20)
    assert rows
    assert {row["noise_class"] for row in rows} == {"automated"}
    assert {row["actionability"] for row in rows} == {"archive"}
    assert {row["needs_reply"] for row in rows} == {0}
    with store._connect() as conn:
        stats = conn.execute("SELECT * FROM sender_stats WHERE email = ?", (sender,)).fetchone()
    assert stats["thread_count"] == 12
    assert stats["reply_count"] == 0


def test_rebuild_threads_sender_stats_are_deterministic(tmp_path):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    store.upsert_item(
        _item(
            source="gmail",
            account="a@example.com",
            external_id="m1",
            thread_id="t1",
            sender="Me",
            subject="Hello",
            created_at="2026-04-18T00:00:00+00:00",
            is_read=1,
        )
    )
    store.upsert_item(
        _item(
            source="gmail",
            account="a@example.com",
            external_id="m2",
            thread_id="t1",
            sender="Alex",
            subject="Re: Hello",
            created_at="2026-04-18T01:00:00+00:00",
            is_read=0,
        )
    )

    store.rebuild_threads()
    with store._connect() as conn:
        first = [dict(row) for row in conn.execute("SELECT * FROM sender_stats").fetchall()]
    store.rebuild_threads()
    with store._connect() as conn:
        second = [dict(row) for row in conn.execute("SELECT * FROM sender_stats").fetchall()]

    assert second == first


def test_sync_state_tracks_status_and_metadata(tmp_path):
    store = MessageIndexStore(tmp_path / "index.sqlite3")

    store.mark_sync_started(
        source="gmail",
        account="a@example.com",
        checkpoint_type="internalDateMs",
        checkpoint_value="100",
        metadata={"bootstrap_page_token": "page-2", "messages_processed": 25},
    )
    running = store.get_sync_state("gmail", "a@example.com")
    assert running is not None
    assert running["status"] == "running"
    assert running["metadata"]["bootstrap_page_token"] == "page-2"

    store.set_sync_state(
        source="gmail",
        account="a@example.com",
        checkpoint_type="internalDateMs",
        checkpoint_value="200",
        full_sync=True,
        status="idle",
        metadata={"bootstrap_page_token": "", "messages_processed": 50},
    )

    states = store.list_sync_states()
    assert len(states) == 1
    assert states[0]["status"] == "idle"
    assert states[0]["checkpoint_value"] == "200"
    assert states[0]["metadata"]["messages_processed"] == 50


def test_running_sync_does_not_advance_last_success_at(tmp_path):
    store = MessageIndexStore(tmp_path / "index.sqlite3")

    store.mark_sync_started(
        source="gmail",
        account="a@example.com",
        checkpoint_type="internalDateMs",
        checkpoint_value="100",
    )
    running = store.get_sync_state("gmail", "a@example.com")
    assert running is not None
    assert running["last_success_at"] == ""

    store.set_sync_state(
        source="gmail",
        account="a@example.com",
        checkpoint_type="internalDateMs",
        checkpoint_value="200",
        status="idle",
    )
    successful = store.get_sync_state("gmail", "a@example.com")
    assert successful is not None
    assert successful["last_success_at"] != ""
    last_success_at = successful["last_success_at"]

    store.update_sync_progress(
        source="gmail",
        account="a@example.com",
        checkpoint_type="internalDateMs",
        checkpoint_value="300",
        metadata={"messages_processed": 1},
    )
    still_running = store.get_sync_state("gmail", "a@example.com")
    assert still_running is not None
    assert still_running["status"] == "running"
    assert still_running["last_success_at"] == last_success_at


def test_list_threads_supports_waiting_on_and_recent_views(tmp_path):
    import datetime

    now = datetime.datetime.now(datetime.UTC)
    t1 = now.isoformat()
    t2 = (now + datetime.timedelta(hours=1)).isoformat()
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    store.upsert_item(
        _item(
            source="gmail",
            account="a@example.com",
            external_id="r1",
            thread_id="reply-thread",
            sender="Recruiter",
            subject="Interview tomorrow",
            body="Can you confirm your availability?",
            created_at=t1,
            is_read=0,
        )
    )
    store.upsert_item(
        _item(
            source="gmail",
            account="a@example.com",
            external_id="t1",
            thread_id="track-thread",
            sender="Billing",
            subject="Billing follow up",
            body="Your billing case is under review and we will get back to you soon.",
            created_at=t2,
            is_read=1,
        )
    )
    store.rebuild_threads()

    waiting = store.list_threads(
        limit=10,
        actions=("track",),
        has_open_loop=True,
        newest_only=True,
        sort_mode="recent",
    )
    assert len(waiting) == 1
    assert waiting[0]["thread_id"] == "track-thread"

    recent = store.list_threads(limit=10, newest_only=True, sort_mode="recent")
    assert [row["thread_id"] for row in recent] == ["track-thread", "reply-thread"]


def test_upsert_item_is_idempotent(tmp_path):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    item = _item(
        source="gmail",
        account="a@example.com",
        external_id="m1",
        thread_id="t1",
        sender="Me",
        subject="Hello",
    )
    store.upsert_item(item)
    store.upsert_item(item)

    with store._connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        assert count == 1
        row = conn.execute("SELECT * FROM items").fetchone()
        assert row["external_id"] == "m1"
        assert row["subject"] == "Hello"


def test_rebuild_threads_is_idempotent(tmp_path):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    item = _item(
        source="gmail",
        account="a@example.com",
        external_id="m1",
        thread_id="t1",
        sender="Me",
        subject="Hello",
    )
    store.upsert_item(item)

    store.rebuild_threads()
    store.rebuild_threads()

    with store._connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
        assert count == 1
        row = conn.execute("SELECT * FROM threads").fetchone()
        assert row["thread_id"] == "t1"


def test_rebuild_threads_handles_many_threads_without_expression_depth_failure(tmp_path):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    for index in range(1100):
        store.upsert_item(
            _item(
                source="gmail",
                account="a@example.com",
                external_id=f"m{index}",
                thread_id=f"t{index}",
                sender="Sender",
                subject=f"Thread {index}",
            )
        )

    rebuilt = store.rebuild_threads(source="gmail", account="a@example.com")

    assert rebuilt == 1100
    with store._connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM threads WHERE source = ? AND account = ?",
            ("gmail", "a@example.com"),
        ).fetchone()[0]
        assert count == 1100


def test_list_threads_can_filter_by_latest_sender(tmp_path):
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    store.upsert_item(
        _item(
            source="gmail",
            account="a@example.com",
            external_id="m1",
            thread_id="waiting-on-other",
            sender="Me",
            subject="Following up",
        )
    )
    store.upsert_item(
        _item(
            source="gmail",
            account="a@example.com",
            external_id="m2",
            thread_id="waiting-on-me",
            sender="Recruiter",
            subject="Can you reply?",
        )
    )
    store.rebuild_threads()

    rows = store.list_threads(limit=10, latest_sender="Me", sort_mode="recent")

    assert [row["thread_id"] for row in rows] == ["waiting-on-other"]


def test_set_sync_state_is_idempotent(tmp_path):
    store = MessageIndexStore(tmp_path / "index.sqlite3")

    metadata = {"key": "value"}

    store.set_sync_state(
        source="gmail",
        account="a@example.com",
        checkpoint_type="internalDateMs",
        checkpoint_value="12345",
        status="idle",
        metadata=metadata,
    )

    store.set_sync_state(
        source="gmail",
        account="a@example.com",
        checkpoint_type="internalDateMs",
        checkpoint_value="12345",
        status="idle",
        metadata=metadata,
    )

    states = store.list_sync_states()
    assert len(states) == 1
    assert states[0]["checkpoint_value"] == "12345"
    assert states[0]["metadata"] == metadata


# ── index_counts ──────────────────────────────────────────────────────────────


def test_index_counts_returns_item_and_thread_counts(tmp_path):
    """index_counts() returns accurate counts of items and threads."""
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    store.upsert_item(
        _item(
            source="gmail",
            account="a@example.com",
            external_id="m1",
            thread_id="t1",
            sender="Alice",
        )
    )
    store.upsert_item(
        _item(
            source="gmail",
            account="a@example.com",
            external_id="m2",
            thread_id="t2",
            sender="Bob",
        )
    )
    store.rebuild_threads()

    counts = store.index_counts()

    assert counts == {"items": 2, "threads": 2}


def test_index_counts_on_empty_store(tmp_path):
    """index_counts() returns zeros for an empty store."""
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    counts = store.index_counts()
    assert counts == {"items": 0, "threads": 0}


# ── _migrate_schema ──────────────────────────────────────────────────────────


def test_migrate_schema_adds_missing_columns_to_existing_sync_state(tmp_path):
    """_migrate_schema adds status, last_run_started_at, and metadata_json columns
    to a pre-existing sync_state table that lacks them."""
    db_path = tmp_path / "index.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE sync_state (
            source TEXT NOT NULL,
            account TEXT NOT NULL,
            checkpoint_type TEXT NOT NULL,
            checkpoint_value TEXT NOT NULL DEFAULT '',
            last_success_at TEXT NOT NULL DEFAULT '',
            last_full_sync_at TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (source, account)
        )
        """
    )
    conn.commit()
    conn.close()

    # Opening the store should trigger _migrate_schema to add all three columns
    store = MessageIndexStore(db_path)

    with store._connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(sync_state)")}
    assert "status" in columns
    assert "last_run_started_at" in columns
    assert "metadata_json" in columns


# ── rebuild_threads: empty-group deletion branches ───────────────────────────


def test_rebuild_threads_empty_scoped_deletes_source_and_account_threads(tmp_path):
    """When no items match the source+account filter, grouped is empty and the
    elif source-and-account branch deletes threads for that scope (line 552-553)."""
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    # Add imessage items only — no gmail/x items exist
    store.upsert_item(
        _item(
            source="imessage",
            account="local",
            external_id="i1",
            thread_id="chat-1",
            sender="Alice",
        )
    )
    store.rebuild_threads()  # builds 1 thread for imessage

    # Rebuild with a gmail scope that has no items — triggers empty-group path
    rebuilt = store.rebuild_threads(source="gmail", account="x@example.com")

    assert rebuilt == 0


def test_rebuild_threads_empty_scoped_deletes_source_only_threads(tmp_path):
    """When no items match the source-only filter, the elif source branch runs
    DELETE FROM threads WHERE source = ? (line 556-557)."""
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    store.upsert_item(
        _item(
            source="imessage",
            account="local",
            external_id="i1",
            thread_id="chat-1",
            sender="Alice",
        )
    )
    store.rebuild_threads()

    rebuilt = store.rebuild_threads(source="gmail")

    assert rebuilt == 0


def test_rebuild_threads_empty_scoped_deletes_account_only_threads(tmp_path):
    """When no items match the account-only filter, the elif account branch runs
    DELETE FROM threads WHERE account = ? (line 558-559)."""
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    store.upsert_item(
        _item(
            source="gmail",
            account="a@example.com",
            external_id="i1",
            thread_id="chat-1",
            sender="Alice",
        )
    )
    store.rebuild_threads()

    rebuilt = store.rebuild_threads(account="nonexistent")

    assert rebuilt == 0


def test_rebuild_threads_empty_scoped_deletes_all_threads(tmp_path):
    """When the items table is empty and no filter is specified, grouped is empty
    and the else branch runs DELETE FROM threads (line 560-561)."""
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    # No items added at all

    rebuilt = store.rebuild_threads()

    assert rebuilt == 0


# ── list_threads: needs_reply filter ─────────────────────────────────────────


def test_list_threads_filters_by_needs_reply_true(tmp_path):
    """list_threads(needs_reply=True) returns only threads where needs_reply=1,
    exercising the needs_reply predicate branch (lines 587-588)."""
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    # Thread that generates needs_reply=1 (Me sent, then external sender replied)
    store.upsert_item(
        _item(
            source="gmail",
            account="a@example.com",
            external_id="r1-me",
            thread_id="reply-thread",
            sender="Me",
            subject="Hello",
            created_at="2026-04-18T00:00:00+00:00",
            is_read=1,
        )
    )
    store.upsert_item(
        _item(
            source="gmail",
            account="a@example.com",
            external_id="r1-them",
            thread_id="reply-thread",
            sender="Recruiter",
            subject="Re: Hello",
            body="Can you follow up?",
            created_at="2026-04-18T01:00:00+00:00",
            is_read=0,
        )
    )
    # Thread that generates needs_reply=0 (automated sender)
    store.upsert_item(
        _item(
            source="gmail",
            account="a@example.com",
            external_id="a1",
            thread_id="auto-thread",
            sender="no-reply@newsletter.com",
            subject="Weekly digest",
            created_at="2026-04-18T02:00:00+00:00",
            is_read=0,
        )
    )
    store.rebuild_threads()

    reply_rows = store.list_threads(limit=10, needs_reply=True)

    assert len(reply_rows) == 1
    assert reply_rows[0]["thread_id"] == "reply-thread"


def test_list_threads_filters_by_needs_reply_false(tmp_path):
    """list_threads(needs_reply=False) returns only threads where needs_reply=0."""
    store = MessageIndexStore(tmp_path / "index.sqlite3")
    store.upsert_item(
        _item(
            source="gmail",
            account="a@example.com",
            external_id="r1-me",
            thread_id="reply-thread",
            sender="Me",
            subject="Hello",
            created_at="2026-04-18T00:00:00+00:00",
            is_read=1,
        )
    )
    store.upsert_item(
        _item(
            source="gmail",
            account="a@example.com",
            external_id="r1-them",
            thread_id="reply-thread",
            sender="Recruiter",
            subject="Re: Hello",
            body="Can you follow up?",
            created_at="2026-04-18T01:00:00+00:00",
            is_read=0,
        )
    )
    store.upsert_item(
        _item(
            source="gmail",
            account="a@example.com",
            external_id="a1",
            thread_id="auto-thread",
            sender="no-reply@newsletter.com",
            subject="Weekly digest",
            created_at="2026-04-18T02:00:00+00:00",
            is_read=0,
        )
    )
    store.rebuild_threads()

    no_reply_rows = store.list_threads(limit=10, needs_reply=False)

    thread_ids = {row["thread_id"] for row in no_reply_rows}
    assert "auto-thread" in thread_ids
    assert "reply-thread" not in thread_ids
