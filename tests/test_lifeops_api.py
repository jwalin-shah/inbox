from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from memory_store import MemoryStore

pytestmark = pytest.mark.safe


@pytest.fixture
def life_client(tmp_path, monkeypatch):
    import inbox_server

    memory = MemoryStore(tmp_path / "lifeops.sqlite3")
    monkeypatch.setattr(inbox_server, "memory_store", memory)
    runtime = inbox_server.InboxServerRuntime(
        server_state=inbox_server.ServerState(),
        init_contacts_func=lambda: 0,
        google_auth_func=inbox_server._empty_google_services,
        start_scheduler=False,
        ambient_autostart=False,
    )
    with TestClient(inbox_server.create_app(runtime), raise_server_exceptions=False) as client:
        yield client


def test_api_capture_attention_and_complete(life_client, monkeypatch):
    import inbox_server

    monkeypatch.setattr(
        inbox_server,
        "ai_extract_memory",
        lambda _text: {"commitments": [], "action_items": ["Call Yadel"]},
    )

    captured = life_client.post(
        "/life/capture",
        json={"text": "I need to call Yadel.", "source": "chatgpt"},
        headers={
            "X-Inbox-Approval-Lease": inbox_server.mint_local_approval_lease(
                "POST",
                "/life/capture",
                body={"text": "I need to call Yadel.", "source": "chatgpt"},
            )
        },
    )
    assert captured.status_code == 200
    payload = captured.json()
    assert payload["capture"]["processing_state"] == "PROCESSED"
    commitment = payload["commitments"][0]

    attention = life_client.get("/life/what-needs-me")
    assert attention.status_code == 200
    assert attention.json()["items"][0]["commitment_id"] == commitment["commitment_id"]

    completed = life_client.post(
        f"/life/commitments/{commitment['commitment_id']}/complete",
        headers={
            "X-Inbox-Approval-Lease": inbox_server.mint_local_approval_lease(
                "POST",
                f"/life/commitments/{commitment['commitment_id']}/complete",
            )
        },
    )
    assert completed.status_code == 200
    assert completed.json()["state"] == "DONE"
    assert life_client.get("/life/what-needs-me").json()["message"] == "Nothing needs you."


def test_api_capture_failure_returns_durable_failed_capture(life_client, monkeypatch):
    import inbox_server

    def broken_extractor(_text):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(inbox_server, "ai_extract_memory", broken_extractor)

    response = life_client.post(
        "/life/capture",
        json={"text": "Call Yadel"},
        headers={
            "X-Inbox-Approval-Lease": inbox_server.mint_local_approval_lease(
                "POST", "/life/capture", body={"text": "Call Yadel"}
            )
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["capture"]["processing_state"] == "FAILED"
    assert payload["capture"]["raw_text"] == "Call Yadel"
    assert "model unavailable" in payload["capture"]["processing_error"]


def test_api_rejects_empty_capture(life_client):
    import inbox_server

    response = life_client.post(
        "/life/capture",
        json={"text": "   "},
        headers={
            "X-Inbox-Approval-Lease": inbox_server.mint_local_approval_lease(
                "POST", "/life/capture", body={"text": "   "}
            )
        },
    )
    assert response.status_code == 400
