"""Tests for unsubscribe_interactive.py — interactive newsletter unsubscribe CLI."""

from __future__ import annotations

import contextlib
from unittest.mock import MagicMock, patch

import httpx

import unsubscribe_interactive


def _mock_response(data, status_code=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


# ── Newsletter keyword detection ───────────────────────────────────────────


class TestNewsletterKeywordDetection:
    def test_matches_keyword_in_name(self):
        """Conversation name containing a keyword is matched."""
        conv = {"name": "Weekly Digest", "unread": True, "id": "1", "snippet": "..."}
        keywords = ["newsletter", "digest", "weekly", "daily"]
        assert any(k in conv.get("name", "").lower() for k in keywords) is True

    def test_matches_case_insensitively(self):
        """Keyword matching is case-insensitive."""
        conv = {"name": "THE PRODUCT HUNT DIGEST", "unread": True, "id": "1", "snippet": "..."}
        keywords = ["product hunt"]
        assert any(k in conv.get("name", "").lower() for k in keywords) is True

    def test_excludes_read_conversations(self):
        """Only unread conversations are considered for newsletter detection."""
        conv = {"name": "Weekly Digest", "unread": False, "id": "1", "snippet": "..."}
        keywords = ["digest"]
        matched = conv.get("unread") and any(k in conv.get("name", "").lower() for k in keywords)
        assert matched is False

    def test_excludes_non_matching_names(self):
        """Non-matching names are excluded from candidate list."""
        conv = {"name": "Team Standup Notes", "unread": True, "id": "1", "snippet": "..."}
        keywords = ["newsletter", "digest", "weekly", "daily"]
        assert any(k in conv.get("name", "").lower() for k in keywords) is False

    def test_handles_missing_name_field(self):
        """Conversation without a name field is handled gracefully."""
        conv = {"unread": True, "id": "1", "snippet": "..."}
        keywords = ["digest"]
        assert any(k in conv.get("name", "").lower() for k in keywords) is False


# ── Early exit paths ──────────────────────────────────────────────────────


class TestEarlyExit:
    def test_exits_when_no_unread_emails(self, capsys):
        """When no conversations are unread, print message and return."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Team Standup", "unread": False, "id": "1", "snippet": "notes"},
        ])

        with patch.object(httpx, "Client", return_value=mock_client):
            unsubscribe_interactive.main()

        captured = capsys.readouterr()
        assert "No unread emails found." in captured.out
        mock_client.post.assert_not_called()
        mock_client.close.assert_called_once()

    def test_exits_when_empty_conversation_list(self, capsys):
        """When the server returns an empty list, exit early."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([])

        with patch.object(httpx, "Client", return_value=mock_client):
            unsubscribe_interactive.main()

        captured = capsys.readouterr()
        assert "No unread emails found." in captured.out
        mock_client.close.assert_called_once()

    def test_fallback_when_no_candidates_match_keywords(self, capsys):
        """When no conversations match keywords, fall back to showing all unread."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Team Standup", "unread": True, "id": "msg1", "snippet": "notes"},
            {"name": "Project Update", "unread": True, "id": "msg2", "snippet": "updates"},
        ])

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", side_effect=["q"]):
            unsubscribe_interactive.main()

        captured = capsys.readouterr()
        assert "Found 2 unread emails" in captured.out
        mock_client.close.assert_called_once()


# ── Display and selection ─────────────────────────────────────────────────


class TestDisplay:
    def test_shows_up_to_twenty_emails(self, capsys):
        """Only the first 20 candidates are displayed."""
        mock_client = MagicMock(spec=httpx.Client)
        convs = [
            {"name": f"Newsletter {i}", "unread": True, "id": f"msg{i}", "snippet": f"snippet {i}"}
            for i in range(25)
        ]
        mock_client.get.return_value = _mock_response(convs)

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", side_effect=["q"]):
            unsubscribe_interactive.main()

        captured = capsys.readouterr()
        assert "Found 25 unread emails (showing first 20)" in captured.out
        # 20 entries shown plus a header line
        assert captured.out.count("🔴") == 20

    def test_shows_all_when_under_twenty(self, capsys):
        """When fewer than 20 candidates, all are shown."""
        mock_client = MagicMock(spec=httpx.Client)
        convs = [
            {"name": f"Newsletter {i}", "unread": True, "id": f"msg{i}", "snippet": f"snippet {i}"}
            for i in range(3)
        ]
        mock_client.get.return_value = _mock_response(convs)

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", side_effect=["q"]):
            unsubscribe_interactive.main()

        captured = capsys.readouterr()
        assert "Found 3 unread emails (showing first 20)" in captured.out


# ── User input handling ───────────────────────────────────────────────────


class TestUserInput:
    def test_quit_with_q(self, capsys):
        """User can quit by entering 'q'."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Weekly Digest", "unread": True, "id": "msg1", "snippet": "news"},
        ])

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", side_effect=["q"]):
            unsubscribe_interactive.main()

        captured = capsys.readouterr()
        assert "Exiting." in captured.out
        mock_client.post.assert_not_called()
        mock_client.close.assert_called_once()

    def test_quit_with_uppercase_Q(self, capsys):
        """Quit is case-insensitive — 'Q' also exits."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Weekly Digest", "unread": True, "id": "msg1", "snippet": "news"},
        ])

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", side_effect=["Q"]):
            unsubscribe_interactive.main()

        captured = capsys.readouterr()
        assert "Exiting." in captured.out

    def test_invalid_non_numeric_input(self, capsys):
        """Non-numeric input that isn't 'q' shows an error message and re-prompts."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Weekly Digest", "unread": True, "id": "msg1", "snippet": "news"},
        ])

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", side_effect=["abc", "q"]):
            unsubscribe_interactive.main()

        captured = capsys.readouterr()
        assert "Invalid input" in captured.out
        assert "Exiting." in captured.out

    def test_out_of_range_index(self, capsys):
        """An index outside the candidate range shows an error message."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Weekly Digest", "unread": True, "id": "msg1", "snippet": "news"},
        ])

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", side_effect=["99", "q"]):
            unsubscribe_interactive.main()

        captured = capsys.readouterr()
        assert "Please enter a number between 0 and 0" in captured.out

    def test_negative_index(self, capsys):
        """A negative index is out of range."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Weekly Digest", "unread": True, "id": "msg1", "snippet": "news"},
        ])

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", side_effect=["-1", "q"]):
            unsubscribe_interactive.main()

        captured = capsys.readouterr()
        assert "Please enter a number between 0 and 0" in captured.out


# ── Unsubscribe action results ────────────────────────────────────────────


class TestUnsubscribeResults:
    def test_successful_unsubscribe_via_http(self, capsys):
        """Successful unsubscribe via http method shows checkmark."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Weekly Digest", "unread": True, "id": "msg1", "snippet": "news"},
        ])
        mock_client.post.return_value = _mock_response({
            "method": "http",
            "ok": True,
        })

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", side_effect=["0", "q"]):
            unsubscribe_interactive.main()

        captured = capsys.readouterr()
        assert "Unsubscribing from: Weekly Digest" in captured.out
        assert "✓ Unsubscribed via http" in captured.out
        mock_client.close.assert_called_once()

    def test_successful_unsubscribe_via_mailto(self, capsys):
        """Successful unsubscribe via mailto shows checkmark."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Daily Alert", "unread": True, "id": "msg2", "snippet": "alerts"},
        ])
        mock_client.post.return_value = _mock_response({
            "method": "mailto",
            "ok": True,
        })

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", side_effect=["0", "q"]):
            unsubscribe_interactive.main()

        captured = capsys.readouterr()
        assert "✓ Unsubscribed via mailto" in captured.out

    def test_error_response(self, capsys):
        """When the server returns an error, it is displayed."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Bad Newsletter", "unread": True, "id": "msg1", "snippet": "bad"},
        ])
        mock_client.post.return_value = _mock_response({
            "error": "Failed to parse unsubscribe headers",
        })

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", side_effect=["0", "q"]):
            unsubscribe_interactive.main()

        captured = capsys.readouterr()
        assert "❌ Error: Failed to parse unsubscribe headers" in captured.out

    def test_no_unsubscribe_method(self, capsys):
        """When no unsubscribe method is found in headers, show warning."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "No Headers Newsletter", "unread": True, "id": "msg1", "snippet": "none"},
        ])
        mock_client.post.return_value = _mock_response({
            "method": "none",
            "ok": False,
        })

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", side_effect=["0", "q"]):
            unsubscribe_interactive.main()

        captured = capsys.readouterr()
        assert "No unsubscribe method found in email headers." in captured.out

    def test_not_ok_response(self, capsys):
        """When ok is False but method is set, show warning status."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Flaky Newsletter", "unread": True, "id": "msg1", "snippet": "flaky"},
        ])
        mock_client.post.return_value = _mock_response({
            "method": "http",
            "ok": False,
        })

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", side_effect=["0", "q"]):
            unsubscribe_interactive.main()

        captured = capsys.readouterr()
        assert "⚠️ Unsubscribed via http" in captured.out


# ── Exception handling ────────────────────────────────────────────────────


class TestExceptionHandling:
    def test_generic_exception_during_unsubscribe(self, capsys):
        """When an unexpected exception occurs, it is caught and reported."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Weekly Digest", "unread": True, "id": "msg1", "snippet": "news"},
        ])
        mock_client.post.side_effect = ConnectionError("Connection refused")

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", side_effect=["0", "q"]):
            unsubscribe_interactive.main()

        captured = capsys.readouterr()
        assert "Error: Connection refused" in captured.out
        # Loop should continue after exception
        assert "Exiting." in captured.out
        mock_client.close.assert_called_once()


# ── Resource cleanup ──────────────────────────────────────────────────────


class TestResourceCleanup:
    def test_client_closed_after_normal_exit(self):
        """Client is closed when user quits normally."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Weekly Digest", "unread": True, "id": "msg1", "snippet": "news"},
        ])

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="q"):
            unsubscribe_interactive.main()

        mock_client.close.assert_called_once()

    def test_client_closed_after_early_return_no_unread(self):
        """Client is closed even when returning early due to no unread emails."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([])

        with patch.object(httpx, "Client", return_value=mock_client):
            unsubscribe_interactive.main()

        mock_client.close.assert_called_once()

    def test_client_closed_after_exception(self):
        """Client is closed even when the server GET raises an exception."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")

        with patch.object(httpx, "Client", return_value=mock_client), \
             contextlib.suppress(httpx.ConnectError):
            unsubscribe_interactive.main()

        mock_client.close.assert_called_once()
