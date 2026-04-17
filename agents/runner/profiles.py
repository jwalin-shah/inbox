from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .paths import profiles_dir, prompts_dir


@dataclass(frozen=True, slots=True)
class AgentProfile:
    name: str
    access_mode: str
    sandbox_mode: str
    mcp_server_name: str
    mcp_script: str
    profile_path: Path
    instructions: str


_PROFILE_MAP: dict[str, str] = {
    "readonly": "readonly.md",
    "write": "write.md",
}


def load_profile(name: str) -> AgentProfile:
    try:
        filename = _PROFILE_MAP[name]
    except KeyError as exc:
        raise ValueError(f"unknown profile: {name}") from exc

    profile_path = profiles_dir() / filename
    instructions = profile_path.read_text(encoding="utf-8").strip()
    access_mode = "readonly" if name == "readonly" else "write"
    sandbox_mode = "read-only" if name == "readonly" else "workspace-write"
    mcp_server_name = "inbox_readonly" if name == "readonly" else "inbox"
    mcp_script = "inbox_mcp_readonly_stdio.py" if name == "readonly" else "inbox_mcp_stdio.py"
    return AgentProfile(
        name=name,
        access_mode=access_mode,
        sandbox_mode=sandbox_mode,
        mcp_server_name=mcp_server_name,
        mcp_script=mcp_script,
        profile_path=profile_path,
        instructions=instructions,
    )


def build_system_prompt(
    profile_name: str, goal: str | None = None, session_id: str | None = None
) -> str:
    profile = load_profile(profile_name)
    system_template = (prompts_dir() / "system.txt").read_text(encoding="utf-8")
    rendered = system_template.format(
        profile_name=profile.name,
        access_mode=profile.access_mode,
        profile_instructions=profile.instructions,
    ).strip()

    if goal is None or session_id is None:
        return rendered

    task_template = (prompts_dir() / "task_brief.txt").read_text(encoding="utf-8")
    task_prompt = task_template.format(goal=goal, session_id=session_id).strip()
    return f"{rendered}\n\n{task_prompt}"
