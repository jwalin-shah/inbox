import asyncio
import inspect

import pytest

from tools_registry import TOOLS, register_all

INDEX_TOOL_NAMES = {
    "get_index_health",
    "get_index_status",
    "list_index_view",
    "list_needs_action",
}
INVENTORY_TOOL_NAMES = {"get_capability_inventory"}


class DummyMCP:
    def __init__(self):
        self._handlers = []

    def tool(self):
        def decorator(fn):
            self._handlers.append(fn)
            return fn

        return decorator


class DummyBackend:
    async def _request(self, method, path, params=None, json=None):
        return {
            "method": method,
            "path": path,
            "params": params,
            "json": json,
        }


def _handlers():
    mcp = DummyMCP()
    register_all(mcp, DummyBackend(), readonly_only=False)
    return {fn.__name__: fn for fn in mcp._handlers}


def test_create_sheet_and_append_rows_are_confirm_gated():
    by_name = {tool.name: tool for tool in TOOLS}
    assert by_name["create_sheet"].confirm is True
    assert by_name["append_sheet_rows"].confirm is True


def test_all_mutating_tools_require_confirm():
    missing_confirm = [tool.name for tool in TOOLS if not tool.readonly and not tool.confirm]
    assert missing_confirm == []


def test_readonly_registration_preserved():
    mcp = DummyMCP()
    registered = register_all(mcp, DummyBackend(), readonly_only=True)

    readonly_names = [tool.name for tool in TOOLS if tool.readonly]
    write_names = [tool.name for tool in TOOLS if not tool.readonly]
    assert registered == readonly_names
    assert all(name not in registered for name in write_names)


def test_readonly_registration_includes_index_tools():
    mcp = DummyMCP()
    registered = register_all(mcp, DummyBackend(), readonly_only=True)

    assert set(registered) >= INDEX_TOOL_NAMES
    assert set(registered) >= INVENTORY_TOOL_NAMES


def test_index_tools_are_readonly_and_do_not_require_confirm():
    tools_by_name = {tool.name: tool for tool in TOOLS}
    handlers = _handlers()

    for name in INDEX_TOOL_NAMES | INVENTORY_TOOL_NAMES:
        assert tools_by_name[name].readonly is True
        assert tools_by_name[name].confirm is False
        assert "confirm" not in inspect.signature(handlers[name]).parameters


def test_confirm_param_is_added_only_for_confirm_tools():
    mcp = DummyMCP()
    register_all(mcp, DummyBackend(), readonly_only=False)

    handlers = {fn.__name__: fn for fn in mcp._handlers}
    mismatches = []
    for tool in TOOLS:
        params = inspect.signature(handlers[tool.name]).parameters
        if ("confirm" in params) != tool.confirm:
            mismatches.append(tool.name)

    assert mismatches == []


def test_registry_handler_signatures_include_required_tool_params():
    handlers = _handlers()
    missing = []
    optional_marked_required = []

    for tool in TOOLS:
        signature_params = inspect.signature(handlers[tool.name]).parameters
        for param in tool.params:
            if param.name not in signature_params:
                missing.append(f"{tool.name}.{param.name}")
                continue
            signature_param = signature_params[param.name]
            if (
                param.default is not inspect.Parameter.empty
                and signature_param.default is inspect.Parameter.empty
            ):
                optional_marked_required.append(f"{tool.name}.{param.name}")

    assert missing == []
    assert optional_marked_required == []


def test_index_health_status_and_needs_action_dispatch_to_compact_routes():
    handlers = _handlers()

    health = asyncio.run(handlers["get_index_health"]())
    status = asyncio.run(handlers["get_index_status"]())
    needs_action = asyncio.run(
        handlers["list_needs_action"](
            workflow="job_hunt",
            account="me@example.com",
        )
    )

    assert health == {
        "method": "GET",
        "path": "/index/health",
        "params": None,
        "json": None,
    }
    assert status == {
        "method": "GET",
        "path": "/index/status",
        "params": None,
        "json": None,
    }
    assert needs_action == {
        "method": "GET",
        "path": "/inbox/needs-action",
        "params": {"workflow": "job_hunt", "account": "me@example.com"},
        "json": None,
    }


def test_capability_inventory_dispatches_to_readonly_route():
    handlers = _handlers()

    result = asyncio.run(handlers["get_capability_inventory"]())

    assert result == {
        "method": "GET",
        "path": "/capabilities",
        "params": None,
        "json": None,
    }


def test_personal_data_gateway_read_proof_dispatches_to_readonly_body_route():
    handlers = _handlers()

    result = asyncio.run(
        handlers["prove_personal_data_gateway_reads"](
            account="me@example.com",
            gmail_limit=2,
            calendar_limit=3,
            task_limit=4,
        )
    )

    assert result == {
        "method": "POST",
        "path": "/gateway/read-proof",
        "params": None,
        "json": {
            "account": "me@example.com",
            "gmail_limit": 2,
            "calendar_limit": 3,
            "task_limit": 4,
        },
    }


def test_multi_gmail_readiness_dispatches_to_readonly_body_route():
    handlers = _handlers()

    result = asyncio.run(
        handlers["prove_multi_gmail_readiness"](
            accounts=["jwalinshah13@gmail.com", "jshah1331@gmail.com"],
        )
    )

    assert result == {
        "method": "POST",
        "path": "/gateway/gmail-readiness",
        "params": None,
        "json": {
            "accounts": ["jwalinshah13@gmail.com", "jshah1331@gmail.com"],
        },
    }


def test_index_view_dispatches_to_named_index_route():
    handlers = _handlers()

    result = asyncio.run(
        handlers["list_index_view"](
            view_name="waiting-on-me",
            limit=7,
        )
    )

    assert result == {
        "method": "GET",
        "path": "/index/views/waiting-on-me",
        "params": {"limit": 7},
        "json": None,
    }


def test_sheet_path_params_are_encoded_and_query_params_remain_query_values():
    handlers = _handlers()

    result = asyncio.run(
        handlers["read_sheet_values"](
            spreadsheet_id="sheet 1/abc",
            range_="Tab One!A1:B/2",
            account="acct/one two",
        )
    )

    assert result["path"] == "/sheets/sheet%201%2Fabc/values/Tab%20One%21A1%3AB%2F2"
    assert result["params"] == {"account": "acct/one two"}
    assert result["json"] is None


def test_chat_path_params_are_encoded_and_limit_remains_query_value():
    handlers = _handlers()

    result = asyncio.run(
        handlers["get_message_thread"](
            conv_id="chat/with spaces#frag?x=1",
            limit=25,
        )
    )

    assert result["path"] == "/messages/imessage/chat%2Fwith%20spaces%23frag%3Fx%3D1"
    assert result["params"] == {"limit": 25}
    assert result["json"] is None


def test_confirm_gated_tool_raises_when_confirm_not_true():
    """Calling a confirm-gated tool without confirm=True must raise ValueError."""
    handlers = _handlers()

    with pytest.raises(ValueError, match="requires explicit confirmation"):
        asyncio.run(
            handlers["send_imessage"](
                conv_id="chat/with spaces",
                text="hello / raw",
            )
        )


def test_confirm_gated_tool_raises_when_confirm_explicitly_false():
    """Calling a confirm-gated tool with confirm=False must raise ValueError."""
    handlers = _handlers()

    with pytest.raises(ValueError, match="requires explicit confirmation"):
        asyncio.run(
            handlers["send_imessage"](
                conv_id="chat/with spaces",
                text="hello / raw",
                confirm=False,
            )
        )


def test_body_params_are_not_url_encoded():
    handlers = _handlers()

    result = asyncio.run(
        handlers["send_imessage"](
            conv_id="chat/with spaces",
            text="hello / raw",
            confirm=True,
        )
    )

    assert result["path"] == "/messages/send"
    assert result["params"] is None
    assert result["json"] == {
        "source": "imessage",
        "conv_id": "chat/with spaces",
        "text": "hello / raw",
    }
