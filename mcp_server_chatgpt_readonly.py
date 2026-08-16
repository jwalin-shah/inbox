"""Curated read-only Inbox MCP app for a future ChatGPT custom app.

This intentionally does not expose the full Inbox mutation registry. It is
safe to place behind an authenticated HTTPS MCP tunnel once one is configured.
"""

from __future__ import annotations

import os

from inbox_mcp_factory import build_mcp
from mcp_gateway import make_health_handler, make_mcp_app

mcp, backend, memory_store = build_mcp(readonly=True, for_http=True)
health = make_health_handler(
    backend=backend,
    memory_store=memory_store,
    extra_payload={"app": "inbox-chatgpt-readonly", "read_only": True},
)
app = make_mcp_app(mcp=mcp, health_endpoint=health)


def main() -> None:
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("INBOX_MCP_HOST", "127.0.0.1"),
        port=int(os.getenv("INBOX_MCP_PORT", "8001")),
        log_level="info",
    )


if __name__ == "__main__":
    main()
