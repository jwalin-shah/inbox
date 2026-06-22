"""
Local stdio entrypoint for the read-only Inbox MCP surface.

Uses inbox_mcp_factory.build_mcp(readonly=True, for_http=False) so that
HTTP-specific FastMCP settings are not applied in stdio mode.
"""

from __future__ import annotations

from inbox_mcp_factory import build_mcp

_mcp, _backend, _memory_store = build_mcp(readonly=True, for_http=False)


def main() -> None:
    _mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
