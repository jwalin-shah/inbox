from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from lifeops.action_envelope import ActionEnvelope


class OpenClawExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str]], CommandResult]


def _run(argv: Sequence[str]) -> CommandResult:
    completed = subprocess.run(list(argv), check=False, capture_output=True, text=True, timeout=600)
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


class OpenClawExecutionAdapter:
    """Narrow adapter over OpenClaw's stable agent CLI.

    Planning is always available. Live R1+ execution is deliberately refused
    until an approval/grant handoff understood by the underlying MCP executor
    exists; a local boolean must never become an Inbox write authorization.
    """

    def __init__(self, command: str = "openclaw", runner: Runner | None = None) -> None:
        self.command = command
        self.runner = runner or _run

    def build_argv(self, envelope: ActionEnvelope) -> tuple[str, ...]:
        envelope.validate()
        message = json.dumps(
            {
                "protocol": "lifeops.action-envelope.v1",
                "instruction": "Execute this capability exactly once and return structured evidence.",
                "action": envelope.to_dict(),
            },
            sort_keys=True,
        )
        return (
            self.command,
            "agent",
            "--json",
            "--session-key",
            f"lifeops:{envelope.command_id}",
            "--message",
            message,
        )

    def plan(self, envelope: ActionEnvelope) -> dict[str, Any]:
        envelope.validate()
        return {
            "status": "PLANNED",
            "command_id": envelope.command_id,
            "executor": "openclaw",
            "route": envelope.route,
            "risk": envelope.risk,
            "argv": list(self.build_argv(envelope)),
            "live_execution": False,
            "reason": "plan-only by default; no provider state was changed",
        }

    def execute(self, envelope: ActionEnvelope, *, live: bool = False) -> dict[str, Any]:
        envelope.validate()
        if not live:
            return self.plan(envelope)
        if envelope.risk != "R0":
            raise OpenClawExecutionError(
                "live R1+ execution is blocked until the underlying OpenClaw/Inbox "
                "executor accepts a server-minted grant"
            )
        result = self.runner(self.build_argv(envelope))
        if result.returncode != 0:
            raise OpenClawExecutionError(result.stderr.strip() or "OpenClaw execution failed")
        try:
            payload: Any = json.loads(result.stdout)
        except json.JSONDecodeError:
            payload = {"raw_output": result.stdout}
        return {
            "status": "EXECUTED",
            "command_id": envelope.command_id,
            "executor": "openclaw",
            "route": envelope.route,
            "verified": False,
            "provider_readback_required": True,
            "response": payload,
        }
