"""Tests for organize_inbox.py — smart inbox organization CLI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import organize_inbox

# ── main() integration tests ──────────────────────────────────────────────


class TestMainNoAuth:
    def test_exits_early_when_no_gmail_accounts(self, capsys):
        """When google_auth_all returns empty gmail dict, print error and return 1."""
        with patch.object(
            organize_inbox, "google_auth_all", return_value=({}, {}, {}, {}, {}, {})
        ):
            result = organize_inbox.main()

        captured = capsys.readouterr()
        assert "No Gmail accounts authenticated" in captured.out
        assert result == 1

    def test_no_gmail_accounts_is_zero_return(self):
        """Empty gmail_svcs is falsy (empty dict)."""
        with patch.object(
            organize_inbox, "google_auth_all", return_value=({}, {}, {}, {}, {}, {})
        ):
            result = organize_inbox.main()
        assert result == 1


class TestMainLabelDoesNotExist:
    def test_skips_label_not_in_existing_labels(self, capsys):
        """Label from LABEL_QUERIES not in existing_labels is skipped."""
        mock_service = MagicMock()
        with patch.object(
            organize_inbox,
            "google_auth_all",
            return_value=({"account@example.com": mock_service}, {}, {}, {}, {}, {}),
        ), patch.object(
            organize_inbox,
            "gmail_labels",
            return_value=[{"id": "Label_1", "name": "Finance", "type": "user"}],
        ), patch.object(
            organize_inbox, "gmail_search"
        ) as mock_search:
            organize_inbox.main()

        captured = capsys.readouterr()
        # Finance exists, others don't
        assert "Newsletters" in captured.out
        assert "label does not exist" in captured.out
        assert "Jobs" in captured.out
        assert "Promotions" in captured.out
        # Finance was the only one that existed
        mock_search.assert_called_once()
        # Verify the search was for Finance (the only label that existed)
        call_q = mock_search.call_args[1]["q"]
        assert "invoice" in call_q  # Finance query is about invoices/receipts/etc.


class TestMainNoConversationsFound:
    def test_reports_zero_matched_when_search_empty(self, capsys):
        """When gmail_search returns empty list, print '0 emails matched'."""
        mock_service = MagicMock()
        with patch.object(
            organize_inbox,
            "google_auth_all",
            return_value=({"account@example.com": mock_service}, {}, {}, {}, {}, {}),
        ), patch.object(
            organize_inbox,
            "gmail_labels",
            return_value=[
                {"id": "Label_1", "name": "Finance", "type": "user"},
            ],
        ), patch.object(
            organize_inbox, "gmail_search", return_value=[]
        ), patch.object(
            organize_inbox, "gmail_batch_modify"
        ) as mock_modify:
            organize_inbox.main()

        captured = capsys.readouterr()
        assert "Finance: 0 emails matched" in captured.out
        mock_modify.assert_not_called()


class TestMainConversationsWithoutMessageId:
    def test_skips_convos_without_message_id(self, capsys):
        """Conversations that don't have message_id are filtered out."""
        mock_service = MagicMock()
        with patch.object(
            organize_inbox,
            "google_auth_all",
            return_value=({"account@example.com": mock_service}, {}, {}, {}, {}, {}),
        ), patch.object(
            organize_inbox,
            "gmail_labels",
            return_value=[
                {"id": "Label_1", "name": "Newsletters", "type": "user"},
            ],
        ), patch.object(
            organize_inbox,
            "gmail_search",
            return_value=[
                {"message_id": None},
                {"name": "No ID"},
            ],
        ), patch.object(
            organize_inbox, "gmail_batch_modify"
        ) as mock_modify:
            organize_inbox.main()

        captured = capsys.readouterr()
        # No valid msg_ids, so batch_modify never called
        mock_modify.assert_not_called()
        # Summary still prints
        assert "Total emails tagged:" in captured.out


class TestMainSuccessfulTagging:
    def test_tags_emails_and_reports_success(self, capsys):
        """Happy path: search finds conversations, batch_modify succeeds."""
        mock_service = MagicMock()
        with patch.object(
            organize_inbox,
            "google_auth_all",
            return_value=({"account@example.com": mock_service}, {}, {}, {}, {}, {}),
        ), patch.object(
            organize_inbox,
            "gmail_labels",
            return_value=[
                {"id": "Label_1", "name": "Newsletters", "type": "user"},
                {"id": "Label_2", "name": "Finance", "type": "user"},
            ],
        ), patch.object(
            organize_inbox,
            "gmail_search",
            return_value=[
                {"message_id": "msg1", "name": "Weekly Digest"},
                {"message_id": "msg2", "name": "Daily Alert"},
            ],
        ), patch.object(
            organize_inbox, "gmail_batch_modify", return_value=True
        ) as mock_modify:
            result = organize_inbox.main()

        captured = capsys.readouterr()
        # Both labels processed
        assert mock_modify.call_count == 2
        assert "Newsletters: ✓ tagged 2 emails" in captured.out
        assert "Finance: ✓ tagged 2 emails" in captured.out
        # Summary
        assert "Total emails tagged: 4" in captured.out
        assert result == 0

    def test_returns_zero_on_success(self):
        """Successful run returns 0."""
        mock_service = MagicMock()
        with patch.object(
            organize_inbox,
            "google_auth_all",
            return_value=({"account@example.com": mock_service}, {}, {}, {}, {}, {}),
        ), patch.object(
            organize_inbox,
            "gmail_labels",
            return_value=[
                {"id": "Label_1", "name": "Newsletters", "type": "user"},
            ],
        ), patch.object(
            organize_inbox,
            "gmail_search",
            return_value=[{"message_id": "msg1", "name": "Test"}],
        ), patch.object(
            organize_inbox, "gmail_batch_modify", return_value=True
        ):
            result = organize_inbox.main()
        assert result == 0


class TestMainBatchModifyFails:
    def test_reports_batch_modify_failure(self, capsys):
        """When batch_modify returns False, report failure."""
        mock_service = MagicMock()
        with patch.object(
            organize_inbox,
            "google_auth_all",
            return_value=({"account@example.com": mock_service}, {}, {}, {}, {}, {}),
        ), patch.object(
            organize_inbox,
            "gmail_labels",
            return_value=[
                {"id": "Label_1", "name": "Finance", "type": "user"},
            ],
        ), patch.object(
            organize_inbox,
            "gmail_search",
            return_value=[{"message_id": "msg1", "name": "Invoice"}],
        ), patch.object(
            organize_inbox, "gmail_batch_modify", return_value=False
        ):
            organize_inbox.main()

        captured = capsys.readouterr()
        assert "Finance: ✗ batch modify failed" in captured.out
        # Total should still be 0 since stats weren't updated
        assert "Total emails tagged: 0" in captured.out


class TestMainSearchException:
    def test_catches_exception_during_search(self, capsys):
        """When gmail_search raises, catch and print the error."""
        mock_service = MagicMock()
        with patch.object(
            organize_inbox,
            "google_auth_all",
            return_value=({"account@example.com": mock_service}, {}, {}, {}, {}, {}),
        ), patch.object(
            organize_inbox,
            "gmail_labels",
            return_value=[
                {"id": "Label_1", "name": "Jobs", "type": "user"},
            ],
        ), patch.object(
            organize_inbox,
            "gmail_search",
            side_effect=ValueError("search failed"),
        ):
            organize_inbox.main()

        captured = capsys.readouterr()
        assert "Jobs: ✗" in captured.out
        assert "search failed" in captured.out


class TestMainBatchModifyException:
    def test_catches_exception_during_batch_modify(self, capsys):
        """When batch_modify raises, catch and print the error."""
        mock_service = MagicMock()
        with patch.object(
            organize_inbox,
            "google_auth_all",
            return_value=({"account@example.com": mock_service}, {}, {}, {}, {}, {}),
        ), patch.object(
            organize_inbox,
            "gmail_labels",
            return_value=[
                {"id": "Label_1", "name": "Promotions", "type": "user"},
            ],
        ), patch.object(
            organize_inbox,
            "gmail_search",
            return_value=[{"message_id": "msg1", "name": "Deal"}],
        ), patch.object(
            organize_inbox,
            "gmail_batch_modify",
            side_effect=RuntimeError("network error"),
        ):
            organize_inbox.main()

        captured = capsys.readouterr()
        assert "Promotions: ✗" in captured.out
        assert "network error" in captured.out


class TestMainSummary:
    def test_summary_only_shows_labels_with_positive_count(self, capsys):
        """Summary only lists labels that had at least one email tagged."""
        mock_service = MagicMock()

        def mock_search(service, account, q="", limit=1000):
            # Only Newsletter query returns results; others return empty
            if "newsletter" in q:
                return [{"message_id": "msg1", "name": "Digest"}]
            return []

        with patch.object(
            organize_inbox,
            "google_auth_all",
            return_value=({"account@example.com": mock_service}, {}, {}, {}, {}, {}),
        ), patch.object(
            organize_inbox,
            "gmail_labels",
            return_value=[
                {"id": "L1", "name": "Newsletters", "type": "user"},
                {"id": "L2", "name": "Finance", "type": "user"},
            ],
        ), patch.object(
            organize_inbox, "gmail_search", side_effect=mock_search
        ), patch.object(
            organize_inbox, "gmail_batch_modify", return_value=True
        ):
            organize_inbox.main()

        captured = capsys.readouterr()
        # Newsletter should appear in summary
        assert "Newsletters: 1" in captured.out
        # Finance had 0 matches, should not appear in summary
        assert "Finance:" not in captured.out.split("=== Summary ===")[1]
        assert "Total emails tagged: 1" in captured.out

    def test_summary_includes_section_header(self, capsys):
        """Summary section header is always printed."""
        mock_service = MagicMock()
        with patch.object(
            organize_inbox,
            "google_auth_all",
            return_value=({"account@example.com": mock_service}, {}, {}, {}, {}, {}),
        ), patch.object(
            organize_inbox,
            "gmail_labels",
            return_value=[
                {"id": "L1", "name": "Newsletters", "type": "user"},
            ],
        ), patch.object(
            organize_inbox, "gmail_search", return_value=[]
        ):
            organize_inbox.main()

        captured = capsys.readouterr()
        assert "=== Summary ===" in captured.out
        assert "Total emails tagged: 0" in captured.out

    def test_summary_sorts_labels_alphabetically(self, capsys):
        """Labels in the summary are sorted alphabetically."""
        mock_service = MagicMock()

        # Return results for all labels
        def mock_search(service, account, q="", limit=1000):
            return [{"message_id": "msg1", "name": "Test"}]

        with patch.object(
            organize_inbox,
            "google_auth_all",
            return_value=({"account@example.com": mock_service}, {}, {}, {}, {}, {}),
        ), patch.object(
            organize_inbox,
            "gmail_labels",
            return_value=[
                {"id": "L1", "name": "Finance", "type": "user"},
                {"id": "L2", "name": "Jobs", "type": "user"},
                {"id": "L3", "name": "Newsletters", "type": "user"},
            ],
        ), patch.object(
            organize_inbox, "gmail_search", side_effect=mock_search
        ), patch.object(
            organize_inbox, "gmail_batch_modify", return_value=True
        ):
            organize_inbox.main()

        captured = capsys.readouterr()
        summary_section = captured.out.split("=== Summary ===")[1]
        finance_pos = summary_section.index("Finance")
        jobs_pos = summary_section.index("Jobs")
        newsletters_pos = summary_section.index("Newsletters")
        # Alphabetical: Finance < Jobs < Newsletters
        assert finance_pos < jobs_pos < newsletters_pos


class TestMainAccountDisplay:
    def test_prints_account_name(self, capsys):
        """The account email is printed at the start."""
        mock_service = MagicMock()
        with patch.object(
            organize_inbox,
            "google_auth_all",
            return_value=({"user@gmail.com": mock_service}, {}, {}, {}, {}, {}),
        ), patch.object(
            organize_inbox,
            "gmail_labels",
            return_value=[
                {"id": "L1", "name": "Newsletters", "type": "user"},
            ],
        ), patch.object(
            organize_inbox, "gmail_search", return_value=[]
        ):
            organize_inbox.main()

        captured = capsys.readouterr()
        assert "Using account: user@gmail.com" in captured.out

    def test_prints_existing_labels_count(self, capsys):
        """The count of existing labels is printed."""
        mock_service = MagicMock()
        with patch.object(
            organize_inbox,
            "google_auth_all",
            return_value=({"user@gmail.com": mock_service}, {}, {}, {}, {}, {}),
        ), patch.object(
            organize_inbox,
            "gmail_labels",
            return_value=[
                {"id": "L1", "name": "Newsletters", "type": "user"},
                {"id": "L2", "name": "Finance", "type": "user"},
                {"id": "L3", "name": "Jobs", "type": "user"},
            ],
        ), patch.object(
            organize_inbox, "gmail_search", return_value=[]
        ):
            organize_inbox.main()

        captured = capsys.readouterr()
        assert "Found 3 existing labels" in captured.out


class TestMainMixedResults:
    def test_mixed_success_failure_across_labels(self, capsys):
        """One label succeeds, one fails batch_modify, one has exception."""
        mock_service = MagicMock()

        def mock_search(service, account, q="", limit=1000):
            if "newsletter" in q:
                return [{"message_id": "msg1", "name": "Digest"}]
            if "invoice" in q:
                return [{"message_id": "msg2", "name": "Invoice"}]
            if "CATEGORY_PROMOTIONS" in q:
                return [{"message_id": "msg3", "name": "Deal"}]
            return []

        def mock_modify(service, msg_ids, add_label_ids=None, remove_label_ids=None):
            label_id = (add_label_ids or [None])[0]
            if label_id == "L1":  # Newsletters — success
                return True
            if label_id == "L2":  # Finance — fail
                return False
            if label_id == "L3":  # Promotions — exception
                raise RuntimeError("connection lost")
            return True

        with patch.object(
            organize_inbox,
            "google_auth_all",
            return_value=({"account@example.com": mock_service}, {}, {}, {}, {}, {}),
        ), patch.object(
            organize_inbox,
            "gmail_labels",
            return_value=[
                {"id": "L1", "name": "Newsletters", "type": "user"},
                {"id": "L2", "name": "Finance", "type": "user"},
                {"id": "L3", "name": "Promotions", "type": "user"},
            ],
        ), patch.object(
            organize_inbox, "gmail_search", side_effect=mock_search
        ), patch.object(
            organize_inbox, "gmail_batch_modify", side_effect=mock_modify
        ):
            result = organize_inbox.main()

        captured = capsys.readouterr()
        assert "Newsletters: ✓ tagged 1 emails" in captured.out
        assert "Finance: ✗ batch modify failed" in captured.out
        assert "Promotions: ✗ connection lost" in captured.out
        assert "Total emails tagged: 1" in captured.out
        assert result == 0

    def test_jobs_label_not_present(self, capsys):
        """Jobs label doesn't exist, skipped entirely."""
        mock_service = MagicMock()
        with patch.object(
            organize_inbox,
            "google_auth_all",
            return_value=({"account@example.com": mock_service}, {}, {}, {}, {}, {}),
        ), patch.object(
            organize_inbox,
            "gmail_labels",
            return_value=[
                {"id": "L1", "name": "Newsletters", "type": "user"},
            ],
        ), patch.object(
            organize_inbox, "gmail_search", return_value=[]
        ):
            organize_inbox.main()

        captured = capsys.readouterr()
        assert "Finance: ⊘ label does not exist" in captured.out
        assert "Jobs: ⊘ label does not exist" in captured.out
        assert "Promotions: ⊘ label does not exist" in captured.out


class TestMainGmailSearchParams:
    def test_passes_limit_1000_to_search(self, capsys):
        """gmail_search is called with limit=1000."""
        mock_service = MagicMock()
        with patch.object(
            organize_inbox,
            "google_auth_all",
            return_value=({"account@example.com": mock_service}, {}, {}, {}, {}, {}),
        ), patch.object(
            organize_inbox,
            "gmail_labels",
            return_value=[
                {"id": "L1", "name": "Newsletters", "type": "user"},
            ],
        ), patch.object(
            organize_inbox, "gmail_search", return_value=[]
        ) as mock_search:
            organize_inbox.main()

        # Verify limit=1000 was passed
        mock_search.assert_called_once()
        assert mock_search.call_args[1].get("limit") == 1000

    def test_passes_account_to_search(self, capsys):
        """gmail_search is called with the correct account."""
        mock_service = MagicMock()
        with patch.object(
            organize_inbox,
            "google_auth_all",
            return_value=({"user@gmail.com": mock_service}, {}, {}, {}, {}, {}),
        ), patch.object(
            organize_inbox,
            "gmail_labels",
            return_value=[
                {"id": "L1", "name": "Newsletters", "type": "user"},
            ],
        ), patch.object(
            organize_inbox, "gmail_search", return_value=[]
        ) as mock_search:
            organize_inbox.main()

        mock_search.assert_called_once()
        assert mock_search.call_args[0][1] == "user@gmail.com"


class TestMainMultipleAccounts:
    def test_uses_first_account_when_multiple_authed(self, capsys):
        """When multiple accounts exist, uses the first one."""
        mock_svc1 = MagicMock()
        mock_svc2 = MagicMock()
        with patch.object(
            organize_inbox,
            "google_auth_all",
            return_value=(
                {"first@example.com": mock_svc1, "second@example.com": mock_svc2},
                {}, {}, {}, {}, {},
            ),
        ), patch.object(
            organize_inbox,
            "gmail_labels",
            return_value=[
                {"id": "L1", "name": "Newsletters", "type": "user"},
            ],
        ), patch.object(
            organize_inbox, "gmail_search", return_value=[]
        ) as mock_search:
            organize_inbox.main()

        captured = capsys.readouterr()
        # Uses first account
        assert "Using account: first@example.com" in captured.out
        mock_search.assert_called_once()
        assert mock_search.call_args[0][1] == "first@example.com"
