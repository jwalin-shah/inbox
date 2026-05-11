"""
Read-only MCP surface for Inbox.

Use this for cloud agents or less-trusted clients that should be able to search
and read data but not mutate inbox state.
"""

from __future__ import annotations

import os

import ambient_notes
from tools_registry import register_all as _register_registry_tools

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - runtime-only path
    raise RuntimeError(
        "The 'mcp' package is required to run inbox_mcp_readonly.py. Install dependencies with: uv sync"
    ) from exc


from mcp_gateway import make_backend, make_health_handler, make_mcp_app, make_memory_store

DEFAULT_HTTP_PORT = 8001


backend = make_backend()
memory_store = make_memory_store()
mcp = FastMCP(
    "Inbox Personal Assistant (Read Only)",
    stateless_http=True,
    json_response=True,
)


health = make_health_handler(
    backend=backend,
    memory_store=memory_store,
    extra_payload={"mode": "readonly"},
)


@mcp.tool()
async def read_daily_note(date: str = "") -> dict:
    """Read today's daily note or a specific YYYY-MM-DD note if present."""
    path = ambient_notes._today_file() if not date else ambient_notes.DAILY_DIR / f"{date}.md"
    if not path.exists():
        return {"ok": False, "path": str(path), "content": ""}
    return {"ok": True, "path": str(path), "content": path.read_text(encoding="utf-8")}


@mcp.tool()
async def get_memory(
    query: str = "",
    memory_type: str = "",
    subject: str = "",
    status: str = "",
    limit: int = 10,
) -> list[dict]:
    """Retrieve structured memory entries for people, projects, preferences, or commitments."""
    return memory_store.query_entries(
        query=query,
        memory_type=memory_type,
        subject=subject,
        status=status,
        limit=limit,
    )


@mcp.tool()
async def list_open_commitments(limit: int = 25) -> list[dict]:
    """List open commitment memory entries."""
    return memory_store.list_open_commitments(limit=limit)


_register_registry_tools(mcp, backend, readonly_only=True)


app = make_mcp_app(mcp=mcp, health_endpoint=health)


def main() -> None:
    import uvicorn

    port = int(os.getenv("INBOX_MCP_READONLY_PORT", str(DEFAULT_HTTP_PORT)))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
