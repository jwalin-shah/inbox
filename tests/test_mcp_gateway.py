from __future__ import annotations

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
