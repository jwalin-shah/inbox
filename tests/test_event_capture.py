"""POST /events/capture adversarial fixtures. No Bridge, no spawn, no MCP server."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from event_store import MAX_PAYLOAD_BYTES, EventStore

ROOT = Path(__file__).resolve().parents[1]


def _valid_body(**overrides) -> dict:
    body = {
        "source": "manual",
        "source_object_id": "capture-1",
        "observed_at": "2026-09-05T18:00:00+00:00",
        "occurred_at": "2026-09-05T17:59:00+00:00",
        "event_type": "manual.capture",
        "payload": {"text": "Nathan said 100 drones may cost $6 each."},
        "provenance": {"source_ref": "manual:test/capture-1"},
    }
    body.update(overrides)
    return body


@pytest.fixture
def client(tmp_path):
    import inbox_server

    mock_ambient = MagicMock()
    mock_ambient.is_running = False
    mock_dictation = MagicMock()
    mock_dictation.is_running = False
    mock_dictation.available = True

    fake_state = inbox_server.ServerState()
    fake_state.ambient = mock_ambient
    fake_state.dictation = mock_dictation
    fake_state.event_store = EventStore(tmp_path / "events.sqlite3")

    runtime = inbox_server.InboxServerRuntime(
        server_state=fake_state,
        init_contacts_func=lambda: 0,
        google_auth_func=inbox_server._empty_google_services,
        start_scheduler=False,
        ambient_autostart=False,
    )

    with (
        patch.dict(os.environ, {"INBOX_SERVER_TOKEN": "", "INBOX_TEST_MODE": "1"}, clear=False),
        TestClient(inbox_server.create_app(runtime), raise_server_exceptions=False) as c,
    ):
        yield c, fake_state


def test_malformed_event_is_error(client):
    http, _ = client
    response = http.post(
        "/events/capture",
        content=b"{not-json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json().get("result", "error") == "error" or "detail" in response.json()


def test_missing_provenance_is_error(client):
    http, _ = client
    body = _valid_body()
    del body["provenance"]
    response = http.post("/events/capture", json=body)
    assert response.status_code == 422
    payload = response.json()
    assert payload.get("result", "error") == "error" or "detail" in payload


def test_exact_duplicate_retry_is_already_exists(client):
    http, state = client
    body = _valid_body()
    first = http.post("/events/capture", json=body)
    second = http.post("/events/capture", json=body)
    assert first.status_code == 201
    assert first.json()["result"] == "created"
    assert second.status_code == 200
    assert second.json()["result"] == "already_exists"
    assert first.json()["event"]["event_id"] == second.json()["event"]["event_id"]
    assert state.event_store.count() == 1


def test_conflicting_same_id_payload_is_error(client):
    http, state = client
    first = http.post("/events/capture", json=_valid_body())
    event_id = first.json()["event"]["event_id"]
    second = http.post(
        "/events/capture",
        json=_valid_body(event_id=event_id, payload={"text": "other payload"}),
    )
    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["result"] == "error"
    assert state.event_store.count() == 1


def test_idempotency_key_payload_digest_mismatch_is_error(client):
    http, state = client
    response = http.post(
        "/events/capture",
        json=_valid_body(event_id="evt_deadbeefdeadbeefdeadbeefdeadbeef"),
    )
    assert response.status_code == 422
    assert response.json()["result"] == "error"
    assert state.event_store.count() == 0


def test_oversized_payload_is_error(client):
    http, _ = client
    response = http.post(
        "/events/capture",
        json=_valid_body(payload={"text": "x" * (MAX_PAYLOAD_BYTES + 1)}),
    )
    assert response.status_code in {413, 422}
    assert response.json().get("result", "error") == "error" or "detail" in response.json()


def test_interrupted_repeated_request_is_idempotent(client):
    http, state = client
    body = _valid_body(source_object_id="retry-1")
    first = http.post("/events/capture", json=body)
    # Dropped HTTP response: client repeats the same request.
    repeat = http.post("/events/capture", json=body)
    assert first.json()["result"] == "created"
    assert repeat.json()["result"] == "already_exists"
    assert state.event_store.count() == 1


def test_malformed_untrusted_source_locator_is_error(client):
    http, _ = client
    response = http.post(
        "/events/capture",
        json=_valid_body(provenance={"source_ref": "https://evil.example/steal"}),
    )
    assert response.status_code == 422
    assert response.json().get("result", "error") == "error" or "detail" in response.json()


def test_capture_is_not_approval_gated(client):
    import inbox_server

    http, _ = client
    assert inbox_server._approval_rule_for_request("POST", "/events/capture") is None
    response = http.post("/events/capture", json=_valid_body())
    assert response.status_code == 201
    assert "X-Inbox-Approval-Lease" not in response.request.headers


def test_capture_route_does_not_call_bridge_or_spawn():
    server = (ROOT / "inbox_server.py").read_text()
    start = server.index('@app.post("/events/capture"')
    end = server.index("@app.", start + 10)
    handler = server[start:end].lower()
    assert "bridge" not in handler
    assert "spawn" not in handler
    assert "subprocess" not in handler


def test_capture_does_not_start_mcp_or_set_spawn_flag(client):
    http, _ = client
    http.post("/events/capture", json=_valid_body())
    assert os.getenv("INBOX_CONTROL_PLANE_SPAWN", "0") == "0"
    assert not (ROOT / "mcp_server.py").read_text().count("events/capture")


def test_same_key_same_digest_replays_original_http_receipt(client):
    http, state = client
    body = _valid_body()
    first = http.post("/events/capture", json=body)
    second = http.post("/events/capture", json=body)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.status_code != 403
    assert first.json()["event"] == second.json()["event"]
    assert first.json()["event"]["payload"] == body["payload"]
    assert first.json()["event"]["provenance"] == body["provenance"]
    assert state.event_store.count() == 1


def test_same_key_different_digest_is_409_not_403_and_does_not_overwrite(client):
    http, state = client
    first = http.post("/events/capture", json=_valid_body())
    original = first.json()["event"]
    conflict = http.post(
        "/events/capture",
        json=_valid_body(
            event_id=original["event_id"],
            payload={"text": "other payload"},
        ),
    )
    assert conflict.status_code == 409
    assert conflict.status_code != 403
    assert conflict.json()["result"] == "error"
    assert conflict.json()["event"] is None
    stored = state.event_store.get(original["event_id"])
    assert stored is not None
    assert stored.payload == original["payload"]
    assert state.event_store.count() == 1


def test_http_correction_creates_history_without_mutating_original(client):
    http, state = client
    first = http.post("/events/capture", json=_valid_body())
    original_id = first.json()["event"]["event_id"]
    correction = http.post(
        "/events/capture",
        json=_valid_body(payload={"text": "later correction"}),
    )
    assert first.status_code == 201
    assert correction.status_code == 201
    assert correction.json()["event"]["event_id"] != original_id
    assert state.event_store.count() == 2
    assert state.event_store.get(original_id).payload == first.json()["event"]["payload"]


def test_capture_handler_has_no_approval_lookup_or_provider_call():
    import ast

    server = (ROOT / "inbox_server.py").read_text()
    tree = ast.parse(server)
    capture_fn = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "capture_event"
    )
    called: set[str] = set()
    for node in ast.walk(capture_fn):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute):
                called.add(func.attr)
    assert "mint_local_approval_lease" not in called
    assert "_approval_decision_for_request" not in called
    assert "gmail_compose_send" not in called
    assert "sheets_values_update" not in called
    assert "spawn" not in called
