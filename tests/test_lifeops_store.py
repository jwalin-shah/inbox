from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from lifeops_store import LifeOpsStore

pytestmark = pytest.mark.safe


def _extraction(*, action_items=None, commitments=None):
    return {
        "people": [],
        "projects": [],
        "commitments": commitments or [],
        "action_items": action_items or [],
    }


def test_capture_is_durable_when_extraction_fails(tmp_path):
    store = LifeOpsStore(tmp_path / "lifeops.sqlite3")
    capture = store.create_capture("I need to call Yadel.", source="chatgpt")

    def broken_extractor(_text):
        raise RuntimeError("extractor unavailable")

    result = store.process_capture(capture["capture_id"], broken_extractor)

    assert result["capture"]["capture_id"].startswith("cap_")
    assert result["capture"]["raw_text"] == "I need to call Yadel."
    assert result["capture"]["processing_state"] == "FAILED"
    assert "extractor unavailable" in result["capture"]["processing_error"]
    assert result["commitments"] == []


def test_capture_projects_action_and_attention_query(tmp_path):
    store = LifeOpsStore(tmp_path / "lifeops.sqlite3")
    capture = store.create_capture("I need to call Yadel.", source="chatgpt")

    result = store.process_capture(
        capture["capture_id"],
        lambda _text: _extraction(action_items=["Call Yadel"]),
    )

    assert result["capture"]["processing_state"] == "PROCESSED"
    assert len(result["commitments"]) == 1
    commitment = result["commitments"][0]
    assert commitment["commitment_id"].startswith("com_")
    assert commitment["capture_id"] == capture["capture_id"]
    assert commitment["owner"] == "YOU"
    assert commitment["state"] == "READY_HUMAN"
    assert commitment["next_condition"] == "next reasonable available context"

    attention = store.what_needs_me()
    assert attention["needs_attention"] is True
    assert attention["items"][0]["commitment_id"] == commitment["commitment_id"]


def test_processing_is_idempotent_and_done_is_not_resurfaced(tmp_path):
    store = LifeOpsStore(tmp_path / "lifeops.sqlite3")
    capture = store.create_capture("Call Yadel", source="test")
    calls = 0

    def extractor(_text):
        nonlocal calls
        calls += 1
        return _extraction(action_items=["Call Yadel"])

    first = store.process_capture(capture["capture_id"], extractor)
    second = store.process_capture(capture["capture_id"], extractor)
    assert calls == 1
    assert second["commitments"][0]["commitment_id"] == first["commitments"][0]["commitment_id"]

    completed = store.complete_commitment(first["commitments"][0]["commitment_id"])
    assert completed["state"] == "DONE"
    assert store.what_needs_me()["message"] == "Nothing needs you."


def test_list_open_commitments_includes_not_due_and_excludes_done(tmp_path):
    store = LifeOpsStore(tmp_path / "lifeops.sqlite3")
    first = store.create_capture("Plan project", source="test")
    result = store.process_capture(
        first["capture_id"],
        lambda _text: _extraction(
            commitments=[{"text": "Plan project", "owner": "YOU"}]
        ),
    )
    open_items = store.list_open_commitments()
    assert [item["commitment_id"] for item in open_items] == [
        result["commitments"][0]["commitment_id"]
    ]
    store.complete_commitment(result["commitments"][0]["commitment_id"])
    assert store.list_open_commitments() == []


def test_expired_waiting_condition_surfaces(tmp_path):
    store = LifeOpsStore(tmp_path / "lifeops.sqlite3")
    capture = store.create_capture("Wait for Anuj", source="test")
    deadline = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    result = store.process_capture(
        capture["capture_id"],
        lambda _text: _extraction(
            commitments=[
                {
                    "text": "Follow up with Anuj",
                    "owner": "Anuj",
                    "deadline": deadline,
                }
            ]
        ),
    )

    assert result["commitments"][0]["state"] == "WAITING"
    attention = store.what_needs_me()
    assert attention["needs_attention"] is True
    assert attention["items"][0]["owner"] == "Anuj"


def test_capture_rejects_empty_text(tmp_path):
    store = LifeOpsStore(tmp_path / "lifeops.sqlite3")
    with pytest.raises(ValueError, match="must not be empty"):
        store.create_capture("   ")
