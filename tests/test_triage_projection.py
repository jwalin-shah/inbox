from event_store import RawEvent, RawEventStore
from message_index_store import IndexedItem, MessageIndexStore
from normalization_projection import (
    _task_duplicate_groups,
    gmail_normalization,
    reconcile_tasks,
    todo_candidates,
)
from triage_projection import triage_message_threads


def _item(*, external_id: str, sender: str, subject: str, body: str, is_read: int = 0) -> IndexedItem:
    return IndexedItem(
        source="imessage",
        account="local",
        external_id=external_id,
        thread_id=external_id,
        kind="imessage",
        created_at="2026-08-25T15:00:00+00:00",
        updated_at="2026-08-25T15:00:00+00:00",
        ingested_at="2026-08-25T15:01:00+00:00",
        sender=sender,
        recipients_json="[]",
        subject=subject,
        snippet=body,
        body_text=body,
        body_hash=external_id,
        labels_json="[]",
        raw_pointer=f"imessage:{external_id}:{external_id}",
        is_read=is_read,
    )


def test_message_triage_returns_categories_reasons_and_evidence(tmp_path):
    index = MessageIndexStore(tmp_path / "index.sqlite3")
    events = RawEventStore(tmp_path / "events.sqlite3")
    index.upsert_item(_item(external_id="reply", sender="Harsh", subject="Pickup", body="Can you confirm pickup at 5:40?"))
    index.upsert_item(_item(external_id="wait", sender="Me", subject="Practice", body="I will send the address tomorrow."))
    index.rebuild_threads()
    events.append(
        RawEvent.create(
            source="imessage",
            source_object_id="local:reply",
            observed_at="2026-08-25T15:01:00+00:00",
            occurred_at="2026-08-25T15:00:00+00:00",
            event_type="message.observed",
            content_ref="imessage:reply:reply",
            payload={"text": "Can you confirm pickup at 5:40?"},
        )
    )

    result = triage_message_threads(index, events, limit=10)

    by_id = {item["thread_id"]: item for item in result["items"]}
    assert by_id["reply"]["category"] == "reply_now"
    assert by_id["reply"]["usefulness"] == "high"
    assert by_id["reply"]["evidence"]["event_ids"]
    assert by_id["wait"]["category"] == "waiting"
    assert by_id["reply"]["attribution"]["read_only"] is True


def test_message_triage_rejects_unknown_category(tmp_path):
    index = MessageIndexStore(tmp_path / "index.sqlite3")
    events = RawEventStore(tmp_path / "events.sqlite3")

    try:
        triage_message_threads(index, events, category="send_it")
    except ValueError as exc:
        assert "category must be one of" in str(exc)
    else:
        raise AssertionError("unknown category was accepted")


def test_message_triage_filters_source_before_bounded_page(tmp_path):
    index = MessageIndexStore(tmp_path / "index.sqlite3")
    events = RawEventStore(tmp_path / "events.sqlite3")
    for number in range(150):
        item = _item(
            external_id=f"gmail-{number}",
            sender="Sender",
            subject="Email",
            body="Please review this.",
            is_read=0,
        )
        item.source = "gmail"
        item.account = "me@example.com"
        index.upsert_item(item)
    item = _item(external_id="imessage-only", sender="Friend", subject="Practice", body="Can you confirm tomorrow at 5:40?")
    index.upsert_item(item)
    index.rebuild_threads()

    result = triage_message_threads(index, events, source="imessage", limit=10)

    assert result["returned_count"] == 1
    assert result["items"][0]["source"] == "imessage"


def test_message_triage_supports_review_pages(tmp_path):
    index = MessageIndexStore(tmp_path / "index.sqlite3")
    events = RawEventStore(tmp_path / "events.sqlite3")
    for number in range(6):
        index.upsert_item(
            _item(
                external_id=f"message-{number}",
                sender="Sender",
                subject=f"Please review {number}",
                body="Please review this.",
            )
        )
    index.rebuild_threads()

    first = triage_message_threads(index, events, limit=2, offset=0)
    second = triage_message_threads(index, events, limit=2, offset=2)

    assert first["returned_count"] == 2
    assert second["returned_count"] == 2
    assert {item["thread_id"] for item in first["items"]}.isdisjoint(
        {item["thread_id"] for item in second["items"]}
    )
    assert second["coverage"]["page_offset"] == 2


def test_message_triage_shows_freshest_item_first_within_category(tmp_path):
    index = MessageIndexStore(tmp_path / "index.sqlite3")
    events = RawEventStore(tmp_path / "events.sqlite3")
    older = _item(
        external_id="older",
        sender="Sender",
        subject="Please review older",
        body="Please review this.",
    )
    older.created_at = "2026-08-25T10:00:00+00:00"
    older.updated_at = "2026-08-25T10:00:00+00:00"
    newer = _item(
        external_id="newer",
        sender="Sender",
        subject="Please review newer",
        body="Please review this.",
    )
    newer.created_at = "2026-08-25T12:00:00+00:00"
    newer.updated_at = "2026-08-25T12:00:00+00:00"
    index.upsert_item(older)
    index.upsert_item(newer)
    index.rebuild_threads()

    result = triage_message_threads(index, events, limit=10)

    assert [item["thread_id"] for item in result["items"][:2]] == ["newer", "older"]


def test_gmail_normalization_reports_each_account_and_sync_health(tmp_path):
    index = MessageIndexStore(tmp_path / "index.sqlite3")
    events = RawEventStore(tmp_path / "events.sqlite3")
    for account in ("one@example.com", "two@example.com", "three@example.com"):
        item = _item(
            external_id=account,
            sender="Sender",
            subject="Please review",
            body="Please review this and confirm.",
        )
        item.source = "gmail"
        item.account = account
        index.upsert_item(item)
        index.set_sync_state(
            source="gmail",
            account=account,
            checkpoint_type="history_id",
            checkpoint_value="h1",
        )
    index.rebuild_threads(source="gmail")

    result = gmail_normalization(index)

    assert result["account_count"] == 3
    assert result["complete"] is True
    assert {row["account"] for row in result["accounts"]} == {
        "one@example.com",
        "two@example.com",
        "three@example.com",
    }
    assert all(row["coverage"] == "indexed_and_last_sync_healthy" for row in result["accounts"])
    assert events.count() == 0


def test_todo_candidates_are_deduplicated_and_proposal_only(tmp_path):
    index = MessageIndexStore(tmp_path / "index.sqlite3")
    events = RawEventStore(tmp_path / "events.sqlite3")
    first = _item(
        external_id="gmail-1",
        sender="Harsh",
        subject="Pickup",
        body="Can you confirm pickup at 5:40?",
    )
    first.source = "gmail"
    first.account = "me@example.com"
    second = _item(
        external_id="gmail-2",
        sender="Me",
        subject="Resume",
        body="I will send the resume tomorrow.",
    )
    second.source = "gmail"
    second.account = "me@example.com"
    index.upsert_item(first)
    index.upsert_item(second)
    index.rebuild_threads(source="gmail")

    result = todo_candidates(index, events, source="gmail", limit=10)

    assert result["returned_count"] == 2
    assert len({item["candidate_id"] for item in result["items"]}) == 2
    assert {item["category"] for item in result["items"]} == {"reply_now", "waiting"}
    assert result["task_recording"]["automatic_creation"] is False
    assert all(item["evidence"]["source"] == "gmail" for item in result["items"])


def test_task_reconciliation_matches_existing_task_and_reports_missing(tmp_path):
    index = MessageIndexStore(tmp_path / "index.sqlite3")
    events = RawEventStore(tmp_path / "events.sqlite3")
    item = _item(
        external_id="gmail-1",
        sender="Harsh",
        subject="Confirm pickup",
        body="Can you confirm pickup?",
    )
    item.source = "gmail"
    item.account = "me@example.com"
    index.upsert_item(item)
    index.rebuild_threads(source="gmail")
    candidates = todo_candidates(index, events, source="gmail", limit=10)

    result = reconcile_tasks(
        candidates,
        {
            "me@example.com": [
                {
                    "id": "task-1",
                    "title": "Confirm pickup",
                    "notes": "",
                    "account": "me@example.com",
                },
                {
                    "id": "task-2",
                    "title": "Unrelated task",
                    "notes": "",
                    "account": "me@example.com",
                },
            ]
        },
    )

    assert result["candidate_counts"]["matched"] == 1
    assert result["unmatched_existing_task_count"] == 1
    assert result["duplicate_task_groups"] == []


def test_task_duplicate_groups_include_conservative_near_duplicates():
    groups = _task_duplicate_groups(
        [
            {
                "id": "task-1",
                "account": "me@example.com",
                "title": "Reach out to Vincent at OpenClaw Foundation about a job",
            },
            {
                "id": "task-2",
                "account": "me@example.com",
                "title": "Reach out to Vincent at the OpenClaw Foundation about a job",
            },
            {
                "id": "task-3",
                "account": "other@example.com",
                "title": "Reach out to Vincent at the OpenClaw Foundation about a job",
            },
            {"id": "task-4", "account": "me@example.com", "title": "Call mom"},
        ]
    )

    assert [[task["id"] for task in group] for group in groups] == [["task-1", "task-2"]]


def test_task_duplicate_groups_do_not_merge_short_or_generic_variants():
    groups = _task_duplicate_groups(
        [
            {"id": "task-1", "account": "me@example.com", "title": "Review status"},
            {"id": "task-2", "account": "me@example.com", "title": "Review project status"},
        ]
    )

    assert groups == []
