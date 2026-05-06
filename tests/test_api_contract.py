from __future__ import annotations

import os
import re
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.routing import Match
from starlette.types import Scope

from inbox_client import InboxClient
from tools_registry import TOOLS

_PATH_PARAM_RE = re.compile(r"{([^}:]+)(?::[^}]+)?}")
_SAMPLE_PATH_VALUES = {
    "range_": "Sheet1!A1:B2",
}


def _sample_path(template: str) -> str:
    return _PATH_PARAM_RE.sub(
        lambda match: _SAMPLE_PATH_VALUES.get(match.group(1), "sample"),
        template,
    )


def _has_route(app: FastAPI, *, method: str, path: str) -> bool:
    scope: Scope = {
        "type": "http",
        "method": method,
        "path": path,
        "root_path": "",
        "headers": [],
        "query_string": b"",
    }
    for route in app.router.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            return True
    return False


@pytest.fixture
def api_client() -> Iterator[TestClient]:
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
        TestClient(inbox_server.create_app(runtime), raise_server_exceptions=False) as client,
    ):
        yield client


def test_mcp_tool_paths_route_to_fastapi_endpoints():
    import inbox_server

    missing = [
        f"{tool.name}: {tool.method} {tool.path} -> {_sample_path(tool.path)}"
        for tool in TOOLS
        if not _has_route(
            inbox_server.app,
            method=tool.method,
            path=_sample_path(tool.path),
        )
    ]

    assert missing == []


def test_inbox_client_index_status_matches_server_endpoint_shape(api_client: TestClient):
    import inbox_server

    inbox_server.state.index_store.index_counts = MagicMock(return_value={"items": 3, "threads": 2})
    inbox_server.state.index_store.list_sync_states = MagicMock(return_value=[])

    client = InboxClient.__new__(InboxClient)
    client._client = api_client

    result = client.index_status()

    assert result["db_path"].endswith(".inbox_index.sqlite3")
    assert result["counts"] == {"items": 3, "threads": 2}
    assert result["sync_states"] == []
