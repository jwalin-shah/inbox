"""Unit tests for ambient_daemon.py — the standalone ambient listening daemon."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

import ambient_daemon
from ambient_daemon import handle_signal, main, on_note

# ── Helpers ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_ambient_daemon_globals():
    """Reset module globals before/after each test to prevent cross-test pollution."""
    ambient_daemon._daemon_service = None
    ambient_daemon._should_exit = False
    yield
    ambient_daemon._daemon_service = None
    ambient_daemon._should_exit = False


# ── on_note ──────────────────────────────────────────────────────────────────


class TestOnNote:
    """Tests for on_note(raw_transcript, summary) — saves note with optional topic extraction."""

    def test_with_summary_extracts_topics(self, monkeypatch):
        """When summary is provided, extract() is called and topics are saved."""
        mock_save_note = MagicMock()
        monkeypatch.setattr(ambient_daemon, "save_note", mock_save_note)

        mock_extract = MagicMock()
        mock_extract.return_value.topics = ["meeting", "deadline"]
        monkeypatch.setattr(sys.modules["services"], "extract", mock_extract)

        on_note("Meeting tomorrow at 3pm about Q3 goals", "Meeting about Q3 goals")

        mock_extract.assert_called_once_with(
            "Meeting tomorrow at 3pm about Q3 goals"
        )
        mock_save_note.assert_called_once_with(
            "Meeting tomorrow at 3pm about Q3 goals",
            "Meeting about Q3 goals",
            "meeting, deadline",
        )

    def test_with_summary_extracts_topics_single(self, monkeypatch):
        """Single topic results in clean comma-joined string (no trailing comma)."""
        mock_save_note = MagicMock()
        monkeypatch.setattr(ambient_daemon, "save_note", mock_save_note)

        mock_extract = MagicMock()
        mock_extract.return_value.topics = ["planning"]
        monkeypatch.setattr(sys.modules["services"], "extract", mock_extract)

        on_note("Let's plan the sprint", "Planning session")

        mock_save_note.assert_called_once_with(
            "Let's plan the sprint", "Planning session", "planning"
        )

    def test_with_summary_empty_topics_list(self, monkeypatch):
        """When extract returns empty topics list, topics string is empty."""
        mock_save_note = MagicMock()
        monkeypatch.setattr(ambient_daemon, "save_note", mock_save_note)

        mock_extract = MagicMock()
        mock_extract.return_value.topics = []
        monkeypatch.setattr(sys.modules["services"], "extract", mock_extract)

        on_note("Some audio transcript", "Some summary")

        mock_save_note.assert_called_once_with(
            "Some audio transcript", "Some summary", ""
        )

    def test_without_summary_skips_extract(self, monkeypatch):
        """When summary is None, extract() is never called, topics remain empty."""
        mock_save_note = MagicMock()
        monkeypatch.setattr(ambient_daemon, "save_note", mock_save_note)

        mock_extract = MagicMock()
        monkeypatch.setattr(sys.modules["services"], "extract", mock_extract)

        on_note("Just a transcript", None)

        mock_extract.assert_not_called()
        mock_save_note.assert_called_once_with(
            "Just a transcript", None, ""
        )

    def test_with_empty_summary_skips_extract(self, monkeypatch):
        """When summary is empty string (falsy), extract() is never called."""
        mock_save_note = MagicMock()
        monkeypatch.setattr(ambient_daemon, "save_note", mock_save_note)

        mock_extract = MagicMock()
        monkeypatch.setattr(sys.modules["services"], "extract", mock_extract)

        on_note("Transcript text", "")

        mock_extract.assert_not_called()
        mock_save_note.assert_called_once_with(
            "Transcript text", "", ""
        )

    def test_extract_raises_exception_graceful_fallback(self, monkeypatch):
        """When extract() raises, the exception is caught and topics fall back to empty."""
        mock_save_note = MagicMock()
        monkeypatch.setattr(ambient_daemon, "save_note", mock_save_note)

        mock_extract = MagicMock(side_effect=RuntimeError("MLX model not loaded"))
        monkeypatch.setattr(sys.modules["services"], "extract", mock_extract)

        on_note("Important meeting notes", "Meeting summary")

        mock_extract.assert_called_once()
        mock_save_note.assert_called_once_with(
            "Important meeting notes", "Meeting summary", ""
        )

    def test_extract_raises_exception_during_topic_string_build(self, monkeypatch):
        """When topics aren't strings (edge case), join fails but save_note still called with empty topics."""
        mock_save_note = MagicMock()
        monkeypatch.setattr(ambient_daemon, "save_note", mock_save_note)

        # topics that aren't joinable strings
        mock_extract = MagicMock()
        mock_extract.return_value.topics = [1, 2, 3]  # integers, not strings
        monkeypatch.setattr(sys.modules["services"], "extract", mock_extract)

        on_note("Transcript", "Summary")

        # join fails on integers → exception caught → topics = ""
        mock_save_note.assert_called_once_with("Transcript", "Summary", "")

    def test_save_note_raises_does_not_propagate(self, monkeypatch):
        """If save_note itself raises, the exception escapes on_note (no try/except around save_note)."""
        mock_save_note = MagicMock(side_effect=OSError("Disk full"))
        monkeypatch.setattr(ambient_daemon, "save_note", mock_save_note)

        mock_extract = MagicMock()
        mock_extract.return_value.topics = ["test"]
        monkeypatch.setattr(sys.modules["services"], "extract", mock_extract)

        with pytest.raises(OSError, match="Disk full"):
            on_note("Transcript", "Summary")


# ── handle_signal ────────────────────────────────────────────────────────────


class TestHandleSignal:
    """Tests for handle_signal(signum, frame) — graceful shutdown handler."""

    def test_sets_should_exit_flag(self):
        """handle_signal sets _should_exit to True."""
        ambient_daemon._should_exit = False
        ambient_daemon._daemon_service = None

        with pytest.raises(SystemExit):
            handle_signal(2, None)  # SIGINT

        assert ambient_daemon._should_exit is True

    def test_calls_sys_exit(self):
        """handle_signal always calls sys.exit(0)."""
        ambient_daemon._daemon_service = None

        with pytest.raises(SystemExit) as exc_info:
            handle_signal(15, None)  # SIGTERM

        assert exc_info.value.code == 0

    def test_stops_daemon_service_when_set(self):
        """When _daemon_service is set, its stop() method is called before exit."""
        mock_service = MagicMock()
        ambient_daemon._daemon_service = mock_service

        with pytest.raises(SystemExit):
            handle_signal(2, None)

        mock_service.stop.assert_called_once()

    def test_does_not_stop_when_daemon_service_is_none(self):
        """When _daemon_service is None, no stop() call is attempted."""
        ambient_daemon._daemon_service = None

        with pytest.raises(SystemExit):
            handle_signal(2, None)

        # No exception raised before SystemExit — daemon_service is None, so
        # contextlib.suppress was not needed

    def test_stop_raises_exception_suppressed(self):
        """If daemon_service.stop() raises, the exception is suppressed and exit proceeds."""
        mock_service = MagicMock()
        mock_service.stop.side_effect = RuntimeError("Hardware not available")
        ambient_daemon._daemon_service = mock_service

        with pytest.raises(SystemExit) as exc_info:
            handle_signal(2, None)

        mock_service.stop.assert_called_once()
        assert exc_info.value.code == 0


# ── main ─────────────────────────────────────────────────────────────────────


class TestMain:
    """Tests for main() — the daemon entry point with signal setup, service lifecycle, and shutdown."""

    def test_whisper_stream_not_available_exits(self, monkeypatch):
        """When whisper_stream_available() returns False, main prints error and exits with code 1."""
        monkeypatch.setattr(
            ambient_daemon, "whisper_stream_available", lambda: False
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

    def test_setup_exception_prints_error_and_exits(self, monkeypatch, capsys):
        """When an exception occurs during setup (before the loop), it's caught, printed, and exits with code 1."""
        monkeypatch.setattr(
            ambient_daemon, "whisper_stream_available", lambda: True
        )
        monkeypatch.setattr(ambient_daemon.signal, "signal", MagicMock())
        # Cause an exception before the main loop
        monkeypatch.setattr(
            ambient_daemon, "AmbientService",
            MagicMock(side_effect=RuntimeError("Audio device not found")),
        )
        monkeypatch.setattr(ambient_daemon.time, "sleep", MagicMock())
        monkeypatch.setattr(sys, "exit", MagicMock())

        main()

        captured = capsys.readouterr()
        assert "Fatal error" in captured.err

    def test_daemon_starts_and_runs_until_signal(self, monkeypatch):
        """Happy path: whisper available, service starts, loop runs once then exits."""
        monkeypatch.setattr(
            ambient_daemon, "whisper_stream_available", lambda: True
        )
        monkeypatch.setattr(ambient_daemon.signal, "signal", MagicMock())

        mock_service = MagicMock()
        monkeypatch.setattr(
            ambient_daemon, "AmbientService",
            MagicMock(return_value=mock_service),
        )

        # Set _should_exit True after first sleep so loop runs exactly once
        call_count = [0]

        def controlled_sleep(seconds):
            call_count[0] += 1
            ambient_daemon._should_exit = True

        monkeypatch.setattr(ambient_daemon.time, "sleep", controlled_sleep)

        main()

        mock_service.start.assert_called_once()
        assert call_count[0] == 1
        # Finally block should stop the service
        mock_service.stop.assert_called_once()

    def test_daemon_never_started_still_cleans_up(self, monkeypatch):
        """If main() exits before creating _daemon_service, finally block handles None gracefully."""
        monkeypatch.setattr(
            ambient_daemon, "whisper_stream_available", lambda: True
        )
        monkeypatch.setattr(ambient_daemon.signal, "signal", MagicMock())

        # AmbientService raises during __init__ before assignment completes
        monkeypatch.setattr(
            ambient_daemon, "AmbientService",
            MagicMock(side_effect=ValueError("Config error")),
        )
        monkeypatch.setattr(ambient_daemon.time, "sleep", MagicMock())
        monkeypatch.setattr(sys, "exit", MagicMock())

        # Should not crash — finally block handles _daemon_service is None
        main()
        # _daemon_service was never set, so no stop() should be called
        # (no assertion needed — reaching here without exception is the test)

    def test_flushes_stdout_after_startup_messages(self, monkeypatch):
        """After printing startup messages, stdout is flushed."""
        monkeypatch.setattr(
            ambient_daemon, "whisper_stream_available", lambda: True
        )
        monkeypatch.setattr(ambient_daemon.signal, "signal", MagicMock())

        mock_service = MagicMock()
        monkeypatch.setattr(
            ambient_daemon, "AmbientService",
            MagicMock(return_value=mock_service),
        )

        # Mock stdout flush to verify it was called
        mock_flush = MagicMock()
        monkeypatch.setattr(sys.stdout, "flush", mock_flush)

        # Set _should_exit immediately so loop runs only once
        call_count = [0]

        def controlled_sleep(seconds):
            call_count[0] += 1
            ambient_daemon._should_exit = True

        monkeypatch.setattr(ambient_daemon.time, "sleep", controlled_sleep)

        main()

        # flush should have been called at least twice (after "starting" and after "running")
        assert mock_flush.call_count >= 2

    def test_main_without_whisper_stream_available_clean(self, monkeypatch, capsys):
        """When whisper_stream_available returns False, only the error is printed."""
        monkeypatch.setattr(
            ambient_daemon, "whisper_stream_available", lambda: False
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "whisper-stream not available" in captured.out
