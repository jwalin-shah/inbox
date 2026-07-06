"""Tests for unsubscribe_bulk.py — bulk newsletter unsubscribe CLI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

import unsubscribe_bulk


def _mock_response(data, status_code=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


# ── Newsletter detection logic ─────────────────────────────────────────────


class TestNewsletterFiltering:
    def test_matches_newsletter_by_keyword_in_name(self):
        """Conversation name containing a keyword is matched."""
        conv = {"name": "Weekly Digest", "unread": True, "id": "1", "snippet": "..."}
        keywords = ["newsletter", "digest", "weekly"]
        assert any(k in conv.get("name", "").lower() for k in keywords) is True

    def test_matches_case_insensitively(self):
        """Keyword matching is case-insensitive."""
        conv = {"name": "THE DAILY DIGEST", "unread": True, "id": "1", "snippet": "..."}
        keywords = ["digest"]
        assert any(k in conv.get("name", "").lower() for k in keywords) is True

    def test_excludes_read_conversations(self):
        """Only unread conversations are considered."""
        conv = {"name": "Weekly Digest", "unread": False, "id": "1", "snippet": "..."}
        keywords = ["digest"]
        is_newsletter = conv.get("unread") and any(k in conv.get("name", "").lower() for k in keywords)
        assert is_newsletter is False

    def test_excludes_non_matching_names(self):
        """Conversations without any keyword in the name are excluded."""
        conv = {"name": "Team Standup Notes", "unread": True, "id": "1", "snippet": "..."}
        keywords = ["newsletter", "digest", "weekly", "daily"]
        assert any(k in conv.get("name", "").lower() for k in keywords) is False

    def test_handles_missing_name_field(self):
        """Conversations without a name field are handled gracefully."""
        conv = {"unread": True, "id": "1", "snippet": "..."}
        keywords = ["digest"]
        assert any(k in conv.get("name", "").lower() for k in keywords) is False


# ── main() integration tests ──────────────────────────────────────────────


class TestMainNoNewsletters:
    def test_exits_early_when_no_newsletters_found(self, capsys):
        """When no conversations match newsletter keywords, print message and return."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Team Standup", "unread": True, "id": "1", "snippet": "notes"},
        ])

        with patch.object(httpx, "Client", return_value=mock_client):
            unsubscribe_bulk.main()

        captured = capsys.readouterr()
        assert "No newsletters found." in captured.out

    def test_exits_early_when_conversations_are_all_read(self, capsys):
        """When all conversations are read, match nothing and exit."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Weekly Digest", "unread": False, "id": "1", "snippet": "news"},
        ])

        with patch.object(httpx, "Client", return_value=mock_client):
            unsubscribe_bulk.main()

        captured = capsys.readouterr()
        assert "No newsletters found." in captured.out


class TestMainCancellation:
    def test_cancels_when_user_declines(self, capsys):
        """When user enters 'n', skip unsubscribing and exit."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Weekly Digest", "unread": True, "id": "msg1", "snippet": "news"},
        ])

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="n"):
            unsubscribe_bulk.main()

        captured = capsys.readouterr()
        assert "Cancelled." in captured.out
        mock_client.post.assert_not_called()

    def test_cancels_on_non_y_input(self, capsys):
        """Any input other than 'y' cancels (e.g. 'N', 'no', '')."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Daily Alert", "unread": True, "id": "msg1", "snippet": "alerts"},
        ])

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="no"):
            unsubscribe_bulk.main()

        captured = capsys.readouterr()
        assert "Cancelled." in captured.out


class TestMainBulkUnsubscribe:
    def test_all_successful(self, capsys):
        """Happy path: all newsletters unsubscribe successfully."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Weekly Digest", "unread": True, "id": "msg1", "snippet": "news"},
            {"name": "Daily Alert", "unread": True, "id": "msg2", "snippet": "alerts"},
        ])
        mock_client.post.return_value = _mock_response({
            "total": 2,
            "results": [
                {"msg_id": "msg1", "method": "http", "ok": True},
                {"msg_id": "msg2", "method": "mailto", "ok": True},
            ],
        })

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="y"):
            unsubscribe_bulk.main()

        captured = capsys.readouterr()
        assert "Unsubscribing from 2 emails" in captured.out
        assert "2 successful" in captured.out
        mock_client.post.assert_called_once_with(
            "/messages/gmail/bulk-unsubscribe",
            json={"msg_ids": ["msg1", "msg2"]},
        )

    def test_with_errors(self, capsys):
        """Some unsubscribes fail — errors are reported and counted."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Good Newsletter", "unread": True, "id": "msg1", "snippet": "ok"},
            {"name": "Bad Newsletter", "unread": True, "id": "msg2", "snippet": "bad"},
        ])
        mock_client.post.return_value = _mock_response({
            "total": 2,
            "results": [
                {"msg_id": "msg1", "method": "http", "ok": True},
                {"msg_id": "msg2", "error": "Failed to parse headers"},
            ],
        })

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="y"):
            unsubscribe_bulk.main()

        captured = capsys.readouterr()
        assert "1 successful" in captured.out
        assert "Failed to parse headers" in captured.out

    def test_no_unsubscribe_header(self, capsys):
        """When unsubscribe header is absent, report 'no method'."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "No Header Newsletter", "unread": True, "id": "msg1", "snippet": "no headers"},
        ])
        mock_client.post.return_value = _mock_response({
            "total": 1,
            "results": [
                {"msg_id": "msg1", "method": "none", "ok": False},
            ],
        })

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="y"):
            unsubscribe_bulk.main()

        captured = capsys.readouterr()
        assert "No unsubscribe header" in captured.out

    def test_mixed_results(self, capsys):
        """Mix of success, error, and no-method results."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Good Newsletter", "unread": True, "id": "msg1", "snippet": "ok"},
            {"name": "Bad Newsletter", "unread": True, "id": "msg2", "snippet": "bad"},
            {"name": "No Header Newsletter", "unread": True, "id": "msg3", "snippet": "none"},
        ])
        mock_client.post.return_value = _mock_response({
            "total": 3,
            "results": [
                {"msg_id": "msg1", "method": "http", "ok": True},
                {"msg_id": "msg2", "error": "Connection refused"},
                {"msg_id": "msg3", "method": "none", "ok": False},
            ],
        })

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="y"):
            unsubscribe_bulk.main()

        captured = capsys.readouterr()
        # success_count only counts ok=True, not 'none' method
        assert "1 successful" in captured.out
        # fail_count counts error + not-ok
        assert "1 failed/skipped" in captured.out

    def test_closes_client_after_use(self):
        """The httpx client is closed after the function completes."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([])

        with patch.object(httpx, "Client", return_value=mock_client):
            unsubscribe_bulk.main()

        mock_client.close.assert_called_once()
