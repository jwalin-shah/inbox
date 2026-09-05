from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "verify_lifeops_worker_stdio.py"
SPEC = importlib.util.spec_from_file_location("verify_lifeops_worker_stdio", MODULE_PATH)
assert SPEC and SPEC.loader
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)


def test_validate_tools_requires_exact_restricted_worker_set() -> None:
    result = verifier._validate_tools(
        {
            "tools": [
                {"name": "evidence_packet", "annotations": {"read_only_hint": True}},
                {"name": "system_audit", "annotations": {"read_only_hint": True}},
            ]
        }
    )

    assert result == {
        "tool_count": 2,
        "tools": ["evidence_packet", "system_audit"],
    }


def test_validate_tools_rejects_an_added_tool() -> None:
    with pytest.raises(verifier.VerificationError, match="tool set changed"):
        verifier._validate_tools(
            {
                "tools": [
                    {"name": "evidence_packet", "annotations": {"read_only_hint": True}},
                    {"name": "system_audit", "annotations": {"read_only_hint": True}},
                    {"name": "create_task", "annotations": {"read_only_hint": False}},
                ]
            }
        )


def test_structured_content_accepts_mcp_text_fallback() -> None:
    assert verifier._structured_content(
        {"content": [{"type": "text", "text": '{"read_only": true}'}]}
    ) == {"read_only": True}
