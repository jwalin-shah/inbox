from __future__ import annotations

from pathlib import Path


def agents_root() -> Path:
    return Path(__file__).resolve().parent.parent


def profiles_dir() -> Path:
    return agents_root() / "profiles"


def prompts_dir() -> Path:
    return agents_root() / "prompts"


def sessions_dir() -> Path:
    path = agents_root() / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = agents_root() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def codex_home_dir() -> Path:
    path = agents_root() / "codex_home"
    path.mkdir(parents=True, exist_ok=True)
    return path
