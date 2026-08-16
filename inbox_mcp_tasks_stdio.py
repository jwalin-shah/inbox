"""Approval-gated Google Tasks MCP surface.

This intentionally exposes only task reads plus create/complete operations.
Every mutation still requires the explicit ``confirm=True`` argument enforced
by the shared registry.
"""

from __future__ import annotations

from inbox_mcp_factory import build_mcp

TASK_TOOLS = {
    "list_task_lists",
    "list_tasks",
    "create_task",
    "complete_task",
}


def main() -> None:
    mcp, _backend, _memory_store = build_mcp(
        readonly=False, for_http=False, include_names=TASK_TOOLS
    )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
