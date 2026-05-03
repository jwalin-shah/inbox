from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.safe


def test_test_mode_blocks_live_writes(monkeypatch):
    monkeypatch.setenv("INBOX_TEST_MODE", "1")

    from inbox_test_mode import LiveWriteBlocked, assert_live_writes_allowed

    with pytest.raises(LiveWriteBlocked, match="send email"):
        assert_live_writes_allowed("send email")


def test_test_mode_uses_configured_test_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOX_TEST_MODE", "1")
    monkeypatch.setenv("INBOX_TEST_DATA_DIR", str(tmp_path))

    from inbox_test_mode import test_data_dir

    assert test_data_dir() == tmp_path


def test_agent_safe_pytest_markers_are_registered(pytestconfig):
    marker_lines = pytestconfig.getini("markers")

    for marker in ["safe", "integration", "local_data", "slow", "live_write"]:
        assert any(line.startswith(f"{marker}:") for line in marker_lines)


def test_agent_testing_docs_define_safe_commands_and_opt_in_warnings():
    docs = Path("docs/TESTING_FOR_AGENTS.md").read_text()

    assert "INBOX_TEST_MODE=1 uv run pytest -m safe" in docs
    assert "uv run ruff check ." in docs
    assert "uv run pyright" in docs
    assert "Do not run live-write tests unless explicitly instructed" in docs
