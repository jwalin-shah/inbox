from __future__ import annotations

import importlib
import sys

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from mcp_backend import InboxBackendError
from mcp_gateway import (
    MEMORY_DB_ENV,
    PublicAuthMiddleware,
    make_health_handler,
    make_memory_store,
)
from tools_registry import TOOLS

pytestmark = pytest.mark.safe


async def _ok(_request):
    return JSONResponse({"ok": True})


async def _health(_request):
    return JSONResponse({"ok": True})


def _app():
    return Starlette(
        routes=[Route("/health", _health), Route("/secure", _ok)],
        middleware=[Middleware(PublicAuthMiddleware)],
    )


def _load_readonly_mcp(monkeypatch, tmp_path):
    monkeypatch.setenv(MEMORY_DB_ENV, str(tmp_path / "memory.sqlite3"))
    sys.modules.pop("inbox_mcp_readonly", None)
    return importlib.import_module("inbox_mcp_readonly")


def test_public_auth_middleware_allows_health_without_token(monkeypatch):
    monkeypatch.setenv("INBOX_MCP_TOKEN", "secret")
    app = _app()
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200


def test_public_auth_middleware_rejects_missing_or_invalid_token(monkeypatch):
    monkeypatch.setenv("INBOX_MCP_TOKEN", "secret")
    app = _app()
    with TestClient(app) as client:
        missing = client.get("/secure")
        invalid = client.get("/secure", headers={"Authorization": "Bearer nope"})
        valid = client.get("/secure", headers={"Authorization": "Bearer secret"})
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert valid.status_code == 200


def test_make_memory_store_uses_configured_path(tmp_path, monkeypatch):
    target = tmp_path / "mem.db"
    monkeypatch.setenv(MEMORY_DB_ENV, str(target))

    store = make_memory_store()

    assert store.db_path == target


@pytest.mark.anyio
async def test_health_handler_includes_backend_and_extra_payload(monkeypatch):
    monkeypatch.setenv("INBOX_MCP_TOKEN", "secret")

    class HealthyBackend:
        async def health(self):
            return {"status": "ok"}

    class FakeStore:
        db_path = "/tmp/mem.db"

    handler = make_health_handler(
        backend=HealthyBackend(),
        memory_store=FakeStore(),
        extra_payload={"mode": "readonly"},
    )
    resp = await handler(None)
    payload = resp.body.decode("utf-8")

    assert '"status":"ok"' in payload
    assert '"mode":"readonly"' in payload
    assert '"auth_enabled":true' in payload


@pytest.mark.anyio
async def test_health_handler_handles_backend_error(monkeypatch):
    monkeypatch.delenv("INBOX_MCP_TOKEN", raising=False)

    class FailingBackend:
        async def health(self):
            raise InboxBackendError("down")

    class FakeStore:
        db_path = "/tmp/mem.db"

    handler = make_health_handler(backend=FailingBackend(), memory_store=FakeStore())
    resp = await handler(None)
    payload = resp.body.decode("utf-8")

    assert '"backend":{"status":"error","detail":"down"}' in payload
    assert '"auth_enabled":false' in payload


@pytest.mark.anyio
async def test_readonly_mcp_reads_today_daily_note(tmp_path, tmp_vault, monkeypatch):
    readonly_mcp = _load_readonly_mcp(monkeypatch, tmp_path)
    note_path = readonly_mcp.ambient_notes._today_file()
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text("# Today\nInbox note")

    result = await readonly_mcp.read_daily_note()

    assert result == {
        "ok": True,
        "path": str(note_path),
        "content": "# Today\nInbox note",
    }


@pytest.mark.anyio
async def test_readonly_mcp_reads_dated_daily_note(tmp_path, tmp_vault, monkeypatch):
    readonly_mcp = _load_readonly_mcp(monkeypatch, tmp_path)
    note_path = tmp_vault / "daily" / "2026-05-11.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text("# May 11\nDated note")

    result = await readonly_mcp.read_daily_note("2026-05-11")

    assert result == {
        "ok": True,
        "path": str(note_path),
        "content": "# May 11\nDated note",
    }


@pytest.mark.anyio
async def test_readonly_mcp_missing_dated_note_returns_empty(tmp_path, tmp_vault, monkeypatch):
    readonly_mcp = _load_readonly_mcp(monkeypatch, tmp_path)
    expected_path = tmp_vault / "daily" / "1999-01-01.md"

    result = await readonly_mcp.read_daily_note("1999-01-01")

    assert result == {"ok": False, "path": str(expected_path), "content": ""}


@pytest.mark.anyio
async def test_readonly_mcp_excludes_mutating_registry_tools(tmp_path, monkeypatch):
    readonly_mcp = _load_readonly_mcp(monkeypatch, tmp_path)

    readonly_tool_names = {tool.name for tool in await readonly_mcp.mcp.list_tools()}
    mutating_tool_names = {tool.name for tool in TOOLS if not tool.readonly}

    assert {"read_daily_note", "get_memory", "list_open_commitments"} <= readonly_tool_names
    assert readonly_tool_names.isdisjoint(mutating_tool_names)


@pytest.mark.anyio
async def test_readonly_mcp_includes_gateway_calendar_and_connector_parity_tools(
    tmp_path, monkeypatch
):
    readonly_mcp = _load_readonly_mcp(monkeypatch, tmp_path)

    readonly_tool_names = {tool.name for tool in await readonly_mcp.mcp.list_tools()}

    assert {
        "get_personal_data_gateway_status",
        "prove_personal_data_gateway_reads",
        "dry_run_ahmed_office_calendar_update",
        "list_calendar_events",
        "get_calendar_event",
        "search_calendar_events",
        "get_connectors_status",
        "search_connectors",
        "plan_connector_sync",
    } <= readonly_tool_names
    assert "create_calendar_event" not in readonly_tool_names
    assert "update_calendar_event" not in readonly_tool_names
