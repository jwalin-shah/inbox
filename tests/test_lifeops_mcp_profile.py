from __future__ import annotations

from types import SimpleNamespace

import lifeops_mcp


def _tool(name: str, read_only_hint: bool | None) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        annotations=SimpleNamespace(read_only_hint=read_only_hint),
    )


def test_read_only_profile_fails_closed_from_tool_annotations() -> None:
    tools = [
        _tool("life_context", True),
        _tool("search", True),
        _tool("propose_create_task", False),
        _tool("capture_observation", None),
    ]

    allowed = lifeops_mcp._allowed_tools_for_profile("read_only", tools)

    assert allowed == {"life_context", "search"}


def test_read_only_profile_does_not_allow_approval_tools() -> None:
    tools = [
        _tool("approve_pending_action", False),
        _tool("execute_approved_action", False),
        _tool("verify_approved_action", True),
    ]

    allowed = lifeops_mcp._allowed_tools_for_profile("read_only", tools)

    assert "approve_pending_action" not in allowed
    assert "execute_approved_action" not in allowed
    assert allowed == {"verify_approved_action"}


def test_server_discovery_card_is_honest_about_legacy_protocol() -> None:
    response = lifeops_mcp._server_discovery_response("discover-1")

    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "discover-1"
    result = response["result"]
    assert result["resultType"] == "complete"
    assert result["supportedVersions"] == ["2025-06-18"]
    assert result["capabilities"] == {"tools": {}}
    assert result["_meta"]["io.modelcontextprotocol/serverInfo"] == {
        "name": "LifeOps",
        "version": "1.27.0",
    }
