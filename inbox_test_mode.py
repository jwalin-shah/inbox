"""Agent-safe test mode helpers."""

from __future__ import annotations

import os
from pathlib import Path

TEST_MODE_ENV = "INBOX_TEST_MODE"
TEST_DATA_DIR_ENV = "INBOX_TEST_DATA_DIR"
TEST_NOW_ENV = "INBOX_TEST_NOW"


class LiveWriteBlocked(RuntimeError):
    """Raised when a live write is attempted while safe test mode is enabled."""


def is_test_mode() -> bool:
    return os.environ.get(TEST_MODE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def assert_live_writes_allowed(action: str) -> None:
    if is_test_mode():
        raise LiveWriteBlocked(f"Live write blocked in INBOX_TEST_MODE: {action}")


def test_data_dir() -> Path:
    configured = os.environ.get(TEST_DATA_DIR_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(".inbox-test-data").resolve()


def test_now() -> str | None:
    if not is_test_mode():
        return None
    return os.environ.get(TEST_NOW_ENV, "").strip() or None
