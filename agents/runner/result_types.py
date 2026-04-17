from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class SessionStep:
    summary: str
    created_at: str = field(default_factory=utc_now)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SessionRecord:
    session_id: str
    profile_name: str
    goal: str
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    status: str = "active"
    steps: list[SessionStep] = field(default_factory=list)
    final_message: str | None = None


@dataclass(slots=True)
class SupervisorResult:
    session_id: str
    success: bool
    message: str
    command: list[str] = field(default_factory=list)
    output_path: str | None = None
