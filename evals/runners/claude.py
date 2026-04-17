import json
import subprocess
import time

from .base import Runner, RunResult


class ClaudeRunner(Runner):
    name = "claude"

    def __init__(self, model: str = "claude-opus-4-7"):
        self.model = model

    def run(self, prompt: str) -> RunResult:
        t0 = time.time()
        try:
            proc = subprocess.run(
                [
                    "claude",
                    "--dangerously-skip-permissions",
                    "--model",
                    self.model,
                    "--output-format",
                    "json",
                    "-p",
                    prompt,
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )
            duration_ms = int((time.time() - t0) * 1000)
            if proc.returncode != 0:
                return RunResult(output="", duration_ms=duration_ms, error=proc.stderr)
            data = json.loads(proc.stdout)
            return RunResult(
                output=data.get("result", ""),
                trace=data.get("messages", []),
                cost_usd=data.get("total_cost_usd", 0.0),
                duration_ms=duration_ms,
            )
        except subprocess.TimeoutExpired:
            return RunResult(output="", duration_ms=300_000, error="timeout")
        except Exception as e:
            return RunResult(output="", duration_ms=int((time.time() - t0) * 1000), error=str(e))
