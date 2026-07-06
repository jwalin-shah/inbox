from __future__ import annotations

import importlib
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


def test_services_resolve_local_data_paths_under_test_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOX_TEST_MODE", "1")
    monkeypatch.setenv("INBOX_TEST_DATA_DIR", str(tmp_path))

    import services

    services = importlib.reload(services)
    try:
        assert tmp_path / "token.json" == services.TOKEN_FILE
        assert tmp_path / "tokens" == services.TOKENS_DIR
        assert tmp_path / "Library/Messages/chat.db" == services.IMSG_DB
        assert tmp_path / "config/inbox/notifications.json" == services.NOTIFICATION_CONFIG_PATH
        assert tmp_path / "config/inbox/favorites.json" == services.FAVORITES_FILE
        assert tmp_path / "config/inbox/voice.json" == services.VOICE_CONFIG_PATH
    finally:
        monkeypatch.delenv("INBOX_TEST_MODE", raising=False)
        monkeypatch.delenv("INBOX_TEST_DATA_DIR", raising=False)
        importlib.reload(services)


def test_google_auth_all_creates_missing_test_data_parent(tmp_path, monkeypatch):
    configured = tmp_path / "missing" / "nested"
    monkeypatch.setenv("INBOX_TEST_MODE", "1")
    monkeypatch.setenv("INBOX_TEST_DATA_DIR", str(configured))

    import services

    services = importlib.reload(services)
    try:
        assert services.google_auth_all() == ({}, {}, {}, {}, {}, {})
        assert configured / "tokens" == services.TOKENS_DIR
        assert services.TOKENS_DIR.is_dir()
    finally:
        monkeypatch.delenv("INBOX_TEST_MODE", raising=False)
        monkeypatch.delenv("INBOX_TEST_DATA_DIR", raising=False)
        importlib.reload(services)


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


def test_test_data_dir_defaults_to_tempdir_when_not_configured(monkeypatch):
    monkeypatch.delenv("INBOX_TEST_DATA_DIR", raising=False)

    from inbox_test_mode import test_data_dir

    result = test_data_dir()
    assert result.name == "inbox-test-data"
    assert "inbox-test-data" in str(result)


def test_test_now_returns_none_when_not_in_test_mode(monkeypatch):
    monkeypatch.delenv("INBOX_TEST_MODE", raising=False)

    from inbox_test_mode import test_now

    assert test_now() is None


def test_test_now_returns_env_value_when_test_mode_active(monkeypatch):
    monkeypatch.setenv("INBOX_TEST_MODE", "1")
    monkeypatch.setenv("INBOX_TEST_NOW", "2026-07-06T12:00:00")

    from inbox_test_mode import test_now

    assert test_now() == "2026-07-06T12:00:00"


def test_test_now_returns_none_when_env_empty_in_test_mode(monkeypatch):
    monkeypatch.setenv("INBOX_TEST_MODE", "1")
    monkeypatch.delenv("INBOX_TEST_NOW", raising=False)

    from inbox_test_mode import test_now

    assert test_now() is None
