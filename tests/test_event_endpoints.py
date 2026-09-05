from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from event_backfill import BackfillResult
from event_store import RawEventStore


@pytest.fixture()
def client(tmp_path):
    with (
        patch.dict("os.environ", {"INBOX_SERVER_TOKEN": ""}, clear=False),
        patch("inbox_server.init_contacts", return_value=0),
        patch("inbox_server.google_auth_all", return_value=({}, {}, {}, {}, {}, {})),
        patch("inbox_server.load_voice_config", return_value={"ambient_autostart": False}),
    ):
        from inbox_server import app, state
        from services import AmbientService, DictationService

        state.gmail_services = {}
        state.cal_services = {}
        state.drive_services = {}
        state.sheets_services = {}
        state.docs_services = {}
        state.tasks_services = {}
        state.event_store = RawEventStore(tmp_path / "events.sqlite3")
        state.ambient = AmbientService(on_note=lambda raw, summary: None)
        state.dictation = DictationService()
        with TestClient(app) as test_client:
            yield test_client


def test_source_registry_is_static_and_does_not_probe_providers(client):
    response = client.get("/sources/registry")

    assert response.status_code == 200
    data = response.json()
    sources = {source["source_id"]: source for source in data["sources"]}
    assert sources["gmail"]["lifecycle"] == "live"
    assert sources["linkedin"]["lifecycle"] == "blocked"
    assert sources["manual"]["capture_modes"] == ["manual"]
    assert sources["sensors"]["lifecycle"] == "planned"


def test_capture_event_round_trips_provenance_and_is_idempotent(client):
    body = {
        "source": "manual",
        "source_object_id": "capture-1",
        "observed_at": "2026-08-25T15:00:00+00:00",
        "occurred_at": "2026-08-25T14:59:00+00:00",
        "event_type": "manual.capture",
        "content": "Nathan said 100 drones may cost $6 each.",
        "provenance": {"channel": "test"},
        "confidence": 0.7,
    }

    first = client.post("/events/capture", json=body)
    second = client.post("/events/capture", json=body)

    assert first.status_code == second.status_code == 200
    assert first.json()["inserted"] is True
    assert second.json()["inserted"] is False
    event = first.json()["event"]
    assert event["provenance"] == {"source": "manual", "channel": "test"}
    assert event["payload"] == {"text": body["content"]}

    listed = client.get("/events?source=manual&limit=10")
    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    assert listed.json()["events"][0]["event_id"] == event["event_id"]

    fetched = client.get(f"/events/{event['event_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["source_object_id"] == "capture-1"


def test_capture_event_requires_content_or_payload(client):
    response = client.post("/events/capture", json={"source": "manual"})

    assert response.status_code == 422


def test_backfill_endpoint_returns_resumable_job_receipt(client):
    result = BackfillResult(
        job_name="message-index-v1:all:all",
        source="",
        account="",
        status="paused",
        scanned_this_run=10,
        inserted_this_run=10,
        duplicate_this_run=0,
        processed_total=10,
        last_item_id=10,
        complete=False,
        event_db_path="events.sqlite3",
        index_db_path="index.sqlite3",
    )
    with patch("inbox_server.backfill_message_index", return_value=result):
        response = client.post("/events/backfill/index", json={"max_items": 10})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["result"]["status"] == "paused"
