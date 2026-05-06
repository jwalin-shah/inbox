import asyncio
import inspect

from tools_registry import TOOLS, register_all


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
    assert registered == readonly_names
    assert all(name not in registered for name in ("create_sheet", "append_sheet_rows"))


def test_confirm_param_is_added_only_for_confirm_tools():
    mcp = DummyMCP()
    register_all(mcp, DummyBackend(), readonly_only=False)

    handlers = {fn.__name__: fn for fn in mcp._handlers}
    create_sheet_params = inspect.signature(handlers["create_sheet"]).parameters
    list_sheets_params = inspect.signature(handlers["list_sheets"]).parameters

    assert "confirm" in create_sheet_params
    assert "confirm" not in list_sheets_params


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
