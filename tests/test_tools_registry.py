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
