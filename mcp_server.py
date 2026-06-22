"""
MCP gateway for Inbox.

This server is the public assistant-facing layer. It talks to the private
local inbox REST server and exposes a smaller, safer tool surface over MCP.

Run:
    uv run python mcp_server.py

Environment:
    INBOX_MCP_TOKEN      Optional bearer token for the public MCP endpoint.
    INBOX_SERVER_URL     Private inbox server URL (defaults to localhost:9849).
    INBOX_SERVER_TOKEN   Bearer token for the private inbox server, if enabled.
    INBOX_MEMORY_DB      Optional path for the local memory store sqlite file.
"""

from __future__ import annotations

from inbox_mcp_factory import build_mcp
from mcp_gateway import make_health_handler, make_mcp_app

mcp, backend, memory_store = build_mcp(readonly=False, for_http=True)

health = make_health_handler(backend=backend, memory_store=memory_store)

app = make_mcp_app(mcp=mcp, health_endpoint=health)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
