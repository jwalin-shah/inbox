from __future__ import annotations

from lifeops.triage import merge_triage


def test_merge_triage_deduplicates_inbox_now_and_keeps_waiting_separate():
    result = merge_triage(
        {
            "read_model": "inbox_now",
            "reasons": [],
            "workflow_counts": {"job": 1},
            "now_items": [
                {"kind": "task", "source": "google_tasks", "title": "Call Yadel", "ref": {"id": "t1"}},
            ],
            "commitments": [
                {"kind": "task", "source": "google_tasks", "title": "Call Yadel", "ref": {"id": "t1"}},
            ],
            "waiting_threads": [
                {"thread_id": "g1", "subject": "Waiting on reply", "owning_account": "local"},
            ],
        },
        {
            "items": [
                {"commitment_id": "c1", "title": "Submit application", "state": "READY_HUMAN"},
            ],
            "capture_failures": [],
        },
    )

    assert [item["title"] for item in result["items"]] == [
        "Submit application",
        "Call Yadel",
        "Waiting on reply",
    ]
    assert result["counts"] == {"lifeops": 1, "google_tasks": 1, "gmail": 1}
    assert result["needs_attention"] is True
    assert result["items"][2]["source"] == "gmail"
    assert result["items"][2]["source_ref"]["thread_id"] == "g1"


def test_merge_triage_surfaces_capture_failures_when_inbox_is_unavailable():
    result = merge_triage(
        None,
        {
            "items": [],
            "capture_failures": [
                {"capture_id": "cap1", "raw_text": "Call Yadel", "processing_error": "model unavailable"}
            ],
        },
    )

    assert result["items"][0]["attention_class"] == "capture_failure"
    assert result["source_health"]["inbox"]["status"] == "unavailable"
