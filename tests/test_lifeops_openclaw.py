from __future__ import annotations

import pytest

from lifeops.action_envelope import ActionEnvelope
from lifeops.executors.openclaw import (
    CommandResult,
    OpenClawExecutionAdapter,
    OpenClawExecutionError,
)

pytestmark = pytest.mark.safe


def _envelope(risk: str = "R1") -> ActionEnvelope:
    return ActionEnvelope.create(
        capability="task.create",
        target="personal",
        inputs={"title": "Call Nathan"},
        risk=risk,
        route="openclaw/inbox_tasks_approval",
        expected_postcondition="task exists exactly once",
    )


def test_build_argv_carries_the_canonical_envelope():
    argv = OpenClawExecutionAdapter(command="openclaw-test").build_argv(_envelope())

    assert argv[:4] == ("openclaw-test", "agent", "--json", "--session-key")
    assert argv[5] == "--message"
    assert "lifeops.action-envelope.v1" in argv[6]
    assert "task.create" in argv[6]


def test_r1_live_execution_fails_before_subprocess():
    calls = []
    adapter = OpenClawExecutionAdapter(runner=lambda argv: calls.append(argv))

    with pytest.raises(OpenClawExecutionError, match=r"live R1\+ execution is blocked"):
        adapter.execute(_envelope(), live=True)
    assert calls == []


def test_r0_live_execution_returns_unverified_provider_result():
    adapter = OpenClawExecutionAdapter(
        runner=lambda _argv: CommandResult(0, '{"ok": true}', "")
    )

    result = adapter.execute(_envelope("R0"), live=True)

    assert result["status"] == "EXECUTED"
    assert result["verified"] is False
    assert result["provider_readback_required"] is True


def test_plan_never_calls_subprocess():
    calls = []
    adapter = OpenClawExecutionAdapter(runner=lambda argv: calls.append(argv))

    result = adapter.plan(_envelope())

    assert result["status"] == "PLANNED"
    assert result["live_execution"] is False
    assert calls == []
