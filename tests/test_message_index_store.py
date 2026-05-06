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
