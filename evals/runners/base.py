from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunResult:
    output: str
    trace: list[dict[str, Any]] = field(default_factory=list)
    cost_usd: float = 0.0
    duration_ms: int = 0
    error: str | None = None


class Runner:
    name: str = "base"

    def run(self, prompt: str) -> RunResult:
        del prompt
        raise NotImplementedError
