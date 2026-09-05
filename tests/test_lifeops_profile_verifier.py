from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "verify_lifeops_profile_stdio.py"
SPEC = importlib.util.spec_from_file_location("verify_lifeops_profile_stdio", MODULE_PATH)
assert SPEC and SPEC.loader
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)


def _tool(name: str, read_only: bool = True) -> dict:
    return {"name": name, "annotations": {"read_only_hint": read_only}}


def test_validate_tools_requires_core_read_surface() -> None:
    result = verifier.validate_tools(
        {"tools": [_tool(name) for name in verifier.REQUIRED_READ_TOOLS]}
    )

    assert result["tool_count"] == len(verifier.REQUIRED_READ_TOOLS)
    assert result["forbidden_tools_present"] == []
    assert result["non_read_only_tools"] == []


def test_validate_tools_rejects_approval_tool() -> None:
    tools = [_tool(name) for name in verifier.REQUIRED_READ_TOOLS]
    tools.append(_tool("approve_pending_action", read_only=False))

    with pytest.raises(verifier.VerificationError, match="forbidden write tools"):
        verifier.validate_tools({"tools": tools})


def test_validate_tools_rejects_missing_annotation() -> None:
    tools = [_tool(name) for name in verifier.REQUIRED_READ_TOOLS]
    tools[0] = {"name": tools[0]["name"], "annotations": {}}

    with pytest.raises(verifier.VerificationError, match="non-read-only tools"):
        verifier.validate_tools({"tools": tools})
