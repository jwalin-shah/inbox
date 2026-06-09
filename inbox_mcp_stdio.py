"""
Local stdio MCP entrypoint for Inbox.

Use this for local MCP-capable clients like Claude Code, Cursor, Gemini CLI,
and any other client that prefers spawning a subprocess over calling the HTTP
MCP gateway directly.

Uses inbox_mcp_factory.build_mcp(for_http=False) so that HTTP-specific FastMCP
settings (stateless_http, json_response) are not applied in stdio mode.
"""

from __future__ import annotations

from inbox_mcp_factory import build_mcp

_mcp, _backend, _memory_store = build_mcp(readonly=False, for_http=False)


def main() -> None:
    _mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
