from __future__ import annotations

import os
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def gas_client() -> Iterator[TestClient]:
    import inbox_server

    mock_ambient = MagicMock()
    mock_ambient.is_running = False
    mock_dictation = MagicMock()
    mock_dictation.is_running = False
    mock_dictation.available = True

    fake_state = inbox_server.ServerState()
    fake_state.ambient = mock_ambient
    fake_state.dictation = mock_dictation

    runtime = inbox_server.InboxServerRuntime(
        server_state=fake_state,
        init_contacts_func=lambda: 0,
        google_auth_func=inbox_server._empty_google_services,
        start_scheduler=False,
        ambient_autostart=False,
    )

    with (
        patch.dict(os.environ, {"INBOX_SERVER_TOKEN": ""}, clear=False),
        patch.dict(os.environ, {"GOOGLE_CLOUD_API_KEY": "", "GOOGLE_MAPS_API_KEY": ""}, clear=False),
        TestClient(inbox_server.create_app(runtime), raise_server_exceptions=False) as client,
    ):
        yield client


def test_find_best_gas_endpoint_degrades_without_key(gas_client: TestClient) -> None:
    resp = gas_client.get("/gas/find-best", params={"origin": "37.5,-121.9"})
    assert resp.status_code == 200
    body = resp.json()
    # No API key configured → provider returns no stations → structured no-data result.
    assert body["status"] == "NO_PRICE_DATA"
    assert body["recommended"] is None
    assert body["metadata"]["price_provider"] == "google_places"


def test_gas_nearby_endpoint_degrades_without_key(gas_client: TestClient) -> None:
    resp = gas_client.get(
        "/gas/nearby", params={"latitude": 37.5, "longitude": -121.9}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NO_PRICE_DATA"