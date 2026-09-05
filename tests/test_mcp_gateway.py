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
from oauth_gateway import READ_SCOPE, WRITE_SCOPE, _conn, _token
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


def test_public_auth_middleware_allows_when_no_token_configured(monkeypatch):
    """When no INBOX_MCP_TOKEN is set, auth is disabled — all requests pass."""
    monkeypatch.delenv("INBOX_MCP_TOKEN", raising=False)
    app = _app()
    with TestClient(app) as client:
        resp = client.get("/secure")
    assert resp.status_code == 200


def test_public_auth_middleware_requires_bearer_when_oauth_is_configured(monkeypatch):
    monkeypatch.delenv("INBOX_MCP_TOKEN", raising=False)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "google-client")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "google-secret")
    app = _app()
    with TestClient(app) as client:
        resp = client.get("/secure")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == (
        'Bearer resource_metadata="http://testserver/.well-known/oauth-protected-resource/mcp", '
        'scope="inbox.read"'
    )


def test_oauth_discovery_registration_and_scoped_bearer(monkeypatch, tmp_path):
    monkeypatch.setenv("INBOX_OAUTH_DB", str(tmp_path / "oauth.sqlite3"))
    monkeypatch.setenv("INBOX_OAUTH_SECRET", "test-secret")
    app = _app()
    app.routes.extend([
        Route("/.well-known/oauth-authorization-server", __import__("oauth_gateway").metadata),
        Route("/oauth/register", __import__("oauth_gateway").register, methods=["POST"]),
    ])
    with TestClient(app) as client:
        discovery = client.get("/.well-known/oauth-authorization-server")
        registration = client.post("/oauth/register", json={"redirect_uris": ["https://gemini.example/callback"]})
        read = client.get("/secure", headers={"Authorization": f"Bearer {_token('client', [READ_SCOPE])}"})
        denied = client.get("/secure", headers={"Authorization": f"Bearer {_token('client', [])}"})
        write = client.get("/secure", headers={"Authorization": f"Bearer {_token('client', [WRITE_SCOPE])}", "X-Inbox-Write": "true"})
    assert discovery.status_code == 200
    assert discovery.json()["code_challenge_methods_supported"] == ["S256"]
    assert registration.status_code == 201
    assert read.status_code == 200
    assert denied.status_code == 403
    assert write.status_code == 200


def test_token_exchange_uses_google_pkce_verifier_separately(monkeypatch, tmp_path):
    import oauth_gateway

    monkeypatch.setenv("INBOX_OAUTH_DB", str(tmp_path / "oauth.sqlite3"))
    monkeypatch.setenv("INBOX_OAUTH_SECRET", "test-secret")
    monkeypatch.setenv("INBOX_PUBLIC_BASE_URL", "https://gateway.example")
    gemini_verifier = "gemini-verifier"
    google_verifier = "google-verifier"
    code = "broker-code"
    with _conn() as conn:
        conn.execute(
            "INSERT INTO clients VALUES (?,?,?)",
            ("client", "client-secret", "https://client.example/callback"),
        )
        conn.execute(
            "INSERT INTO codes VALUES (?,?,?,?,?,?,0)",
            (
                code,
                "client",
                "https://client.example/callback",
                oauth_gateway._b64(__import__("hashlib").sha256(gemini_verifier.encode()).digest()),
                __import__("json").dumps(
                    {"scopes": [READ_SCOPE], "google_code": "google-code", "google_verifier": google_verifier}
                ),
                2_000_000_000,
            ),
        )

    seen = {}

    def fake_exchange(provider_code, redirect_uri, verifier):
        seen.update(provider_code=provider_code, redirect_uri=redirect_uri, verifier=verifier)
        return {"refresh_token": "refresh"}

    monkeypatch.setattr(oauth_gateway, "_google_exchange", fake_exchange)
    app = Starlette(routes=[Route("/oauth/token", oauth_gateway.token, methods=["POST"])])
    with TestClient(app) as client:
        response = client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "client",
                "client_secret": "client-secret",
                "code": code,
                "redirect_uri": "https://client.example/callback",
                "code_verifier": gemini_verifier,
            },
        )

    assert response.status_code == 200
    assert seen == {
        "provider_code": "google-code",
        "redirect_uri": "https://gateway.example/oauth/callback",
        "verifier": google_verifier,
    }
    assert response.json()["refresh_token"] == "refresh"


def test_static_gemini_client_can_start_authorization(monkeypatch, tmp_path):
    import oauth_gateway

    monkeypatch.setenv("INBOX_OAUTH_DB", str(tmp_path / "oauth.sqlite3"))
    monkeypatch.setenv("INBOX_GEMINI_MCP_CLIENT_ID", "gemini-static")
    monkeypatch.setenv("INBOX_GEMINI_MCP_CLIENT_SECRET", "gemini-static-secret")
    redirect_uri = "https://oauth-redirect.googleusercontent.com/r/user_bound_custom-mcp-test"
    monkeypatch.setenv("INBOX_GEMINI_MCP_REDIRECT_URI", redirect_uri)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "google-client")
    monkeypatch.setenv("INBOX_PUBLIC_BASE_URL", "https://gateway.example")
    app = Starlette(routes=[Route("/oauth/authorize", oauth_gateway.authorize)])
    app.state.oauth_states = {}
    with TestClient(app) as client:
        response = client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": "gemini-static",
                "redirect_uri": redirect_uri,
                "scope": READ_SCOPE,
                "state": "gemini-state",
                "code_challenge": "challenge",
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
    assert response.status_code == 307
    assert "accounts.google.com" in response.headers["location"]
    assert len(app.state.oauth_states) == 1


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
