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
        if request.url.path == "/health":
            return await call_next(request)
        if not _is_publicly_authorized(request):
            return JSONResponse(
                {"detail": "Unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
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
            "auth_enabled": bool(_public_token()),
        }
        if extra_payload:
            payload.update(extra_payload)
        return JSONResponse(payload)

    return health


def make_mcp_app(*, mcp, health_endpoint) -> Starlette:
    return Starlette(
        routes=[
            Route("/health", endpoint=health_endpoint),
            Mount("/mcp", app=mcp.streamable_http_app()),
        ],
        middleware=[Middleware(PublicAuthMiddleware)],
    )
