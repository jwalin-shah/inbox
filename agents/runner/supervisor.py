from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .paths import codex_home_dir, logs_dir
from .profiles import build_system_prompt, load_profile
from .result_types import SessionRecord, SessionStep, SupervisorResult
from .session_store import SessionStore


class Supervisor:
    def __init__(
        self,
        store: SessionStore | None = None,
        repo_root: Path | None = None,
        executable: str = "codex",
    ) -> None:
        self.store = store or SessionStore()
        self.repo_root = repo_root or Path(__file__).resolve().parents[2]
        self.executable = executable

    def start_session(self, profile_name: str, goal: str) -> SessionRecord:
        load_profile(profile_name)
        record = self.store.create(profile_name=profile_name, goal=goal)
        bootstrap_prompt = build_system_prompt(
            profile_name=profile_name,
            goal=goal,
            session_id=record.session_id,
        )
        self.store.append_step(
            record.session_id,
            SessionStep(
                summary="session initialized",
                details={"prompt_preview": bootstrap_prompt[:240]},
            ),
        )
        return self.store.load(record.session_id)

    def record_step(self, session_id: str, summary: str, **details: object) -> SessionRecord:
        return self.store.append_step(
            session_id,
            SessionStep(summary=summary, details=dict(details)),
        )

    def finish_session(
        self, session_id: str, success: bool, final_message: str
    ) -> SupervisorResult:
        record = self.store.finalize(
            session_id=session_id,
            success=success,
            final_message=final_message,
        )
        return SupervisorResult(
            session_id=record.session_id,
            success=success,
            message=final_message,
        )

    def run_codex_exec(
        self,
        profile_name: str,
        goal: str,
        context_text: str = "",
        timeout_seconds: int = 180,
    ) -> SupervisorResult:
        profile = load_profile(profile_name)
        record = self.start_session(profile_name=profile_name, goal=goal)
        prompt = build_system_prompt(
            profile_name=profile_name,
            goal=goal,
            session_id=record.session_id,
        )
        if context_text.strip():
            prompt = f"{prompt}\n\nContext:\n{context_text.strip()}"

        output_path = logs_dir() / f"{record.session_id}.last_message.txt"
        command = self._build_codex_command(profile=profile, prompt=prompt, output_path=output_path)
        self.record_step(
            record.session_id,
            "starting codex exec",
            command=command,
            output_path=str(output_path),
        )

        completed = subprocess.run(
            command,
            cwd=self.repo_root,
            env=self._build_env(),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )

        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        final_message = (
            output_path.read_text(encoding="utf-8").strip() if output_path.exists() else ""
        )
        success = completed.returncode == 0 and bool(final_message)
        if not final_message:
            final_message = stderr or stdout or "Codex returned no final message."

        self.record_step(
            record.session_id,
            "codex exec finished",
            returncode=completed.returncode,
            stdout_tail=stdout[-1200:],
            stderr_tail=stderr[-1200:],
        )
        result = self.finish_session(
            record.session_id,
            success=success,
            final_message=final_message,
        )
        result.command = command
        result.output_path = str(output_path)
        return result

    def _build_codex_command(self, profile, prompt: str, output_path: Path) -> list[str]:
        script_path = self.repo_root / profile.mcp_script
        overrides = [
            "mcp_servers={}",
            f"mcp_servers.{profile.mcp_server_name}.command={self._toml_string('uv')}",
            f"mcp_servers.{profile.mcp_server_name}.args={self._toml_array(['run', 'python', script_path.name])}",
            f"mcp_servers.{profile.mcp_server_name}.cwd={self._toml_string(str(self.repo_root))}",
        ]
        server_url = os.environ.get("INBOX_SERVER_URL", "http://127.0.0.1:9849")
        overrides.append(
            f"mcp_servers.{profile.mcp_server_name}.env.INBOX_SERVER_URL={self._toml_string(server_url)}"
        )
        token = os.environ.get("INBOX_SERVER_TOKEN", "").strip()
        if token:
            overrides.append(
                f"mcp_servers.{profile.mcp_server_name}.env.INBOX_SERVER_TOKEN={self._toml_string(token)}"
            )

        command = [
            self.executable,
            "exec",
            "--color",
            "never",
            "-C",
            str(self.repo_root),
            "-s",
            profile.sandbox_mode,
            "--output-last-message",
            str(output_path),
        ]
        for override in overrides:
            command.extend(["-c", override])
        command.append(prompt)
        return command

    def _build_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.setdefault("UV_CACHE_DIR", "/tmp/uv-cache")  # nosec: B108 - intentional shared dev cache
        env.setdefault("CODEX_HOME", str(codex_home_dir()))
        return env

    @staticmethod
    def _toml_string(value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    def _toml_array(self, values: list[str]) -> str:
        return "[" + ", ".join(self._toml_string(v) for v in values) + "]"
