from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RISKS = frozenset({"R0", "R1", "R2", "R3", "R4"})
_SECRET_MARKERS = frozenset({"api_key", "authorization", "password", "secret", "token"})


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _contains_secret_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if any(marker in normalized for marker in _SECRET_MARKERS):
                return True
            if _contains_secret_key(child):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_secret_key(child) for child in value)
    return False


@dataclass(frozen=True)
class ActionEnvelope:
    """The provider-neutral unit LifeOps routes and traces.

    This object contains intent and routing metadata only. Provider credentials
    and approval leases never belong in it.
    """

    intent_id: str
    command_id: str
    capability: str
    target: str
    inputs: dict[str, Any]
    risk: str
    route: str
    expected_postcondition: str
    created_at: str

    @classmethod
    def create(
        cls,
        *,
        capability: str,
        target: str,
        inputs: dict[str, Any],
        risk: str,
        route: str,
        expected_postcondition: str,
        intent_id: str | None = None,
        command_id: str | None = None,
    ) -> ActionEnvelope:
        envelope = cls(
            intent_id=intent_id or _new_id("intent"),
            command_id=command_id or _new_id("cmd"),
            capability=capability,
            target=target,
            inputs=dict(inputs),
            risk=risk,
            route=route,
            expected_postcondition=expected_postcondition,
            created_at=_now(),
        )
        envelope.validate()
        return envelope

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ActionEnvelope:
        required = {
            "intent_id",
            "command_id",
            "capability",
            "target",
            "inputs",
            "risk",
            "route",
            "expected_postcondition",
            "created_at",
        }
        missing = sorted(required - set(payload))
        if missing:
            raise ValueError(f"action envelope missing fields: {', '.join(missing)}")
        envelope = cls(
            intent_id=str(payload["intent_id"]),
            command_id=str(payload["command_id"]),
            capability=str(payload["capability"]),
            target=str(payload["target"]),
            inputs=dict(payload["inputs"]),
            risk=str(payload["risk"]),
            route=str(payload["route"]),
            expected_postcondition=str(payload["expected_postcondition"]),
            created_at=str(payload["created_at"]),
        )
        envelope.validate()
        return envelope

    def validate(self) -> None:
        for field_name in (
            "intent_id",
            "command_id",
            "capability",
            "target",
            "route",
            "expected_postcondition",
            "created_at",
        ):
            if not getattr(self, field_name).strip():
                raise ValueError(f"action envelope {field_name} must not be empty")
        if self.risk not in RISKS:
            raise ValueError(f"action envelope risk must be one of {sorted(RISKS)}")
        if not isinstance(self.inputs, dict):
            raise ValueError("action envelope inputs must be an object")
        if _contains_secret_key(self.inputs):
            raise ValueError("action envelope inputs must not contain secret-looking fields")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "intent_id": self.intent_id,
            "command_id": self.command_id,
            "capability": self.capability,
            "target": self.target,
            "inputs": self.inputs,
            "risk": self.risk,
            "route": self.route,
            "expected_postcondition": self.expected_postcondition,
            "created_at": self.created_at,
        }


def default_trace_path() -> Path:
    return Path(os.getenv("LIFEOPS_TRACE_PATH", "state/lifeops-traces.jsonl")).expanduser()


class TraceStore:
    """Append-only local action trace storage; it never calls a provider."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_trace_path()

    def append(self, envelope: ActionEnvelope, result: dict[str, Any]) -> dict[str, Any]:
        record = {
            "command_id": envelope.command_id,
            "recorded_at": _now(),
            "envelope": envelope.to_dict(),
            "result": result,
        }
        if _contains_secret_key(result):
            raise ValueError("action trace result must not contain secret-looking fields")
        existing = self.get(envelope.command_id)
        if existing is not None:
            raise ValueError(f"action trace already exists: {envelope.command_id}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    def get(self, command_id: str) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("command_id") == command_id:
                    return record
        return None
