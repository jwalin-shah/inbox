"""
Read-only MCP surface for Inbox.

Use this for cloud agents or less-trusted clients that should be able to search
and read data but not mutate inbox state.
"""

from __future__ import annotations

import os

import ambient_notes  # kept for test-suite access via module attribute
from inbox_mcp_factory import build_mcp
from mcp_gateway import make_health_handler, make_mcp_app

DEFAULT_HTTP_PORT = 8001

mcp, backend, memory_store = build_mcp(readonly=True, for_http=True)

health = make_health_handler(
    backend=backend,
    memory_store=memory_store,
    extra_payload={"mode": "readonly"},
)

app = make_mcp_app(mcp=mcp, health_endpoint=health)


def main() -> None:
    import uvicorn

    port = int(os.getenv("INBOX_MCP_READONLY_PORT", str(DEFAULT_HTTP_PORT)))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
