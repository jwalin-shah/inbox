from __future__ import annotations

import os
from pathlib import Path
from secrets import compare_digest
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from mcp_backend import InboxBackend, InboxBackendError
from memory_store import MemoryStore
from oauth_gateway import (
    READ_SCOPE,
    WRITE_SCOPE,
    authorize,
    callback,
    metadata,
    protected_resource,
    register,
    token,
    validate_bearer,
)

MCP_TOKEN_ENV = "INBOX_MCP_TOKEN"  # nosec: B105 - env var name, not a hardcoded credential
MEMORY_DB_ENV = "INBOX_MEMORY_DB"


def make_backend() -> InboxBackend:
    return InboxBackend()


def make_memory_store() -> MemoryStore:
    db_env = os.getenv(MEMORY_DB_ENV)
    db_path = Path(db_env).expanduser() if db_env else None
    return MemoryStore(db_path)


def _public_token() -> str:
    return os.getenv(MCP_TOKEN_ENV, "").strip()


def _oauth_configured() -> bool:
    return bool(
        (
            os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
            and os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
        )
        or (
            os.getenv("INBOX_GEMINI_MCP_CLIENT_ID", "").strip()
            and os.getenv("INBOX_GEMINI_MCP_CLIENT_SECRET", "").strip()
        )
    )


def _resource_challenge(request: Request, scope: str = READ_SCOPE) -> str:
    base = os.getenv("INBOX_PUBLIC_BASE_URL", str(request.base_url).rstrip("/")).rstrip("/")
    return f'Bearer resource_metadata="{base}/.well-known/oauth-protected-resource/mcp", scope="{scope}"'


def _is_publicly_authorized(request: Request) -> bool:
    token = _public_token()
    if not token:
        return True

    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        provided = auth_header[7:].strip()
        return bool(provided) and compare_digest(provided, token)
    return False


class PublicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health" or request.url.path.startswith("/.well-known/") or request.url.path.startswith("/oauth/"):
            return await call_next(request)
        oauth_identity = validate_bearer(request)
        if oauth_identity:
            _, scopes = oauth_identity
            required = WRITE_SCOPE if request.headers.get("x-inbox-write", "").lower() == "true" else READ_SCOPE
            if required not in scopes:
                return JSONResponse({"detail": "insufficient_scope", "required_scope": required}, status_code=403, headers={"WWW-Authenticate": _resource_challenge(request, required)})
            return await call_next(request)
        if (_oauth_configured() and not oauth_identity) or not _is_publicly_authorized(request):
            return JSONResponse(
                {"detail": "Unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": _resource_challenge(request)},
            )
        return await call_next(request)


def make_health_handler(
    *,
    backend: InboxBackend,
    memory_store: MemoryStore,
    extra_payload: dict[str, Any] | None = None,
):
    async def health(_request: Request) -> JSONResponse:
        try:
            backend_health = await backend.health()
        except InboxBackendError as exc:
            backend_health = {"status": "error", "detail": str(exc)}

        payload: dict[str, Any] = {
            "status": "ok",
            "mcp_path": "/mcp",
            "backend": backend_health,
            "memory_db": str(memory_store.db_path),
            "auth_enabled": bool(_public_token()) or _oauth_configured(),
        }
        if extra_payload:
            payload.update(extra_payload)
        return JSONResponse(payload)

    return health


def make_mcp_app(*, mcp, health_endpoint) -> Starlette:
    mcp_http_app = mcp.streamable_http_app()
    app = Starlette(
        routes=[
            Route("/health", endpoint=health_endpoint),
            Route("/.well-known/oauth-authorization-server", metadata),
            Route("/.well-known/oauth-protected-resource", protected_resource),
            Route("/.well-known/oauth-protected-resource/mcp", protected_resource),
            Route("/oauth/register", register, methods=["POST"]),
            Route("/oauth/authorize", authorize, methods=["GET"]),
            Route("/oauth/callback", callback, methods=["GET"], name="oauth_callback"),
            Route("/oauth/token", token, methods=["POST"]),
            # FastMCP's streamable app already owns the /mcp route. Mounting
            # it at /mcp would produce /mcp/mcp and a redirect/404 to clients.
            Mount("/", app=mcp_http_app),
        ],
        middleware=[Middleware(PublicAuthMiddleware)],
        lifespan=mcp_http_app.router.lifespan_context,
    )
    app.state.oauth_states = {}
    return app
