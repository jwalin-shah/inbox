import pytest

from capture_health import CaptureHealthRecord, CaptureHealthStore, capture_summary

pytestmark = pytest.mark.safe


def test_capture_health_store_upserts_latest_record(tmp_path):
    store = CaptureHealthStore(tmp_path / "capture.sqlite3")
    store.upsert(
        CaptureHealthRecord(
            source_id="gmail",
            account="me@example.com",
            display_name="Gmail",
            source_type="google_api",
            configured=True,
            authenticated=True,
            readable=True,
            writable=True,
            last_success_at="2026-05-19T10:00:00+00:00",
            newest_seen_id="msg-1",
            item_count=1,
            checked_at="2026-05-19T10:00:00+00:00",
        )
    )
    store.upsert(
        CaptureHealthRecord(
            source_id="gmail",
            account="me@example.com",
            display_name="Gmail",
            source_type="google_api",
            configured=True,
            authenticated=True,
            readable=False,
            writable=True,
            checked_at="2026-05-19T10:05:00+00:00",
            last_error="token expired",
        )
    )

    rows = store.list_records()

    assert len(rows) == 1
    assert rows[0]["key"] == "gmail:me@example.com"
    assert rows[0]["status"] == "error"
    assert rows[0]["last_error"] == "token expired"


def test_capture_summary_counts_statuses(tmp_path):
    store = CaptureHealthStore(tmp_path / "capture.sqlite3")
    store.upsert(
        CaptureHealthRecord(
            source_id="imessage",
            display_name="iMessage",
            source_type="local_db",
            configured=True,
            readable=True,
            checked_at="2026-05-19T10:00:00+00:00",
        )
    )
    store.upsert(
        CaptureHealthRecord(
            source_id="github",
            display_name="GitHub",
            source_type="external_api",
            configured=False,
            checked_at="2026-05-19T10:00:00+00:00",
        )
    )

    assert capture_summary(store.list_records()) == {
        "total": 2,
        "ok": 1,
        "error": 0,
        "not_configured": 1,
    }
