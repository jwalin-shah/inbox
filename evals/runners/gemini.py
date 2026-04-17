import subprocess
import time

from .base import Runner, RunResult


class GeminiRunner(Runner):
    name = "gemini"

    def __init__(self, model: str | None = None):
        self.model = model

    def run(self, prompt: str) -> RunResult:
        t0 = time.time()
        cmd = ["gemini", "-y", "-p", prompt]
        if self.model:
            cmd += ["-m", self.model]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            duration_ms = int((time.time() - t0) * 1000)
            if proc.returncode != 0:
                return RunResult(output="", duration_ms=duration_ms, error=proc.stderr[:500])
            return RunResult(output=proc.stdout, duration_ms=duration_ms)
        except subprocess.TimeoutExpired:
            return RunResult(output="", duration_ms=300_000, error="timeout")
        except Exception as e:
            return RunResult(output="", duration_ms=int((time.time() - t0) * 1000), error=str(e))
