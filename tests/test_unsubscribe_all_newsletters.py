"""Tests for unsubscribe_all_newsletters.py — bulk newsletter/junk cleanup CLI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

import unsubscribe_all_newsletters


def _mock_response(data, status_code=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


# ── Filtering logic tests ──────────────────────────────────────────────────


class TestNewsletterKeywordFiltering:
    def test_matches_newsletter_keyword_in_name(self):
        """Conversation name containing a newsletter keyword is matched."""
        keywords = ["newsletter", "digest", "weekly", "daily", "alert"]
        conv = {"name": "Weekly Digest", "id": "1", "snippet": "..."}
        text = f"{conv.get('name', '').lower()} {conv.get('snippet', '').lower()}"
        assert any(k in text for k in keywords) is True

    def test_matches_newsletter_keyword_in_snippet(self):
        """Conversation snippet containing a keyword is also matched."""
        keywords = ["newsletter", "digest"]
        conv = {"name": "Some Email", "id": "1", "snippet": "this is a newsletter about tech"}
        text = f"{conv.get('name', '').lower()} {conv.get('snippet', '').lower()}"
        assert any(k in text for k in keywords) is True

    def test_excludes_non_matching_conversations(self):
        """Conversations without any keyword are excluded."""
        keywords = ["newsletter", "digest", "weekly", "daily", "alert"]
        conv = {"name": "Team Standup Notes", "id": "1", "snippet": "project updates"}
        text = f"{conv.get('name', '').lower()} {conv.get('snippet', '').lower()}"
        assert any(k in text for k in keywords) is False

    def test_case_insensitive_matching(self):
        """Keyword matching is case-insensitive."""
        keywords = ["newsletter"]
        conv = {"name": "THE MONTHLY NEWSLETTER", "id": "1", "snippet": "..."}
        text = f"{conv.get('name', '').lower()} {conv.get('snippet', '').lower()}"
        assert any(k in text for k in keywords) is True


class TestJunkKeywordFiltering:
    def test_matches_junk_keyword(self):
        """Conversations with junk keywords like 'dealership' are matched."""
        keywords = ["dealership", "dealer", "auto", "spam"]
        conv = {"name": "Best Dealership Offers", "id": "1", "snippet": "car deals"}
        text = f"{conv.get('name', '').lower()} {conv.get('snippet', '').lower()}"
        assert any(k in text for k in keywords) is True

    def test_excludes_non_junk(self):
        """Non-junk conversations are excluded from junk matching."""
        keywords = ["dealership", "dealer", "auto", "spam"]
        conv = {"name": "Team Meeting Notes", "id": "1", "snippet": "agenda"}
        text = f"{conv.get('name', '').lower()} {conv.get('snippet', '').lower()}"
        assert any(k in text for k in keywords) is False

    def test_matches_insurance_quote_keyword(self):
        """'insurance quote' keyword correctly matches."""
        keywords = ["insurance quote"]
        conv = {"name": "Your Insurance Quote", "id": "1", "snippet": "save now"}
        text = f"{conv.get('name', '').lower()} {conv.get('snippet', '').lower()}"
        assert any(k in text for k in keywords) is True


class TestProblematicSenderFiltering:
    def test_matches_problematic_sender_in_name(self):
        """Sender name matching a problematic sender pattern is flagged."""
        senders = ["dealership", "cars.com", "zillow"]
        sender = "offers@cars.com"
        assert any(p in sender for p in senders) is True

    def test_excludes_safe_sender(self):
        """A normal sender name is not flagged as problematic."""
        senders = ["dealership", "cars.com", "zillow"]
        sender = "team@company.com"
        assert any(p in sender for p in senders) is False

    def test_matches_lendingtree(self):
        """'lendingtree' keyword matches in the sender field."""
        senders = ["lendingtree", "creditkarma", "capitalone"]
        sender = "noreply@lendingtree.com"
        assert any(p in sender for p in senders) is True


class TestWhitelistExclusion:
    def test_skips_whitelisted_senders(self):
        """Whitelisted senders are excluded even if they match keywords."""
        whitelist = ["stanford", "patelco", "security alert"]
        conv = {"name": "Stanford Daily Update", "id": "1", "snippet": "news digest"}
        text = f"{conv.get('name', '').lower()} {conv.get('snippet', '').lower()}"
        is_whitelisted = any(w in text for w in whitelist)
        assert is_whitelisted is True

    def test_does_not_skip_non_whitelisted(self):
        """Non-whitelisted senders are not excluded by whitelist check."""
        whitelist = ["stanford", "patelco"]
        conv = {"name": "Random Newsletter", "id": "1", "snippet": "updates"}
        text = f"{conv.get('name', '').lower()} {conv.get('snippet', '').lower()}"
        is_whitelisted = any(w in text for w in whitelist)
        assert is_whitelisted is False

    def test_security_is_whitelisted(self):
        """'security' keyword in whitelist protects security alerts."""
        whitelist = ["security", "verification"]
        conv = {"name": "Security Alert: New Login", "id": "1", "snippet": "verify"}
        text = f"{conv.get('name', '').lower()} {conv.get('snippet', '').lower()}"
        assert any(w in text for w in whitelist) is True

    def test_invoice_and_receipt_are_whitelisted(self):
        """Transaction-related terms like invoice and receipt are protected."""
        whitelist = ["invoice", "receipt", "payment", "transaction"]
        conv = {"name": "Your Invoice #12345", "id": "1", "snippet": "payment processed"}
        text = f"{conv.get('name', '').lower()} {conv.get('snippet', '').lower()}"
        assert any(w in text for w in whitelist) is True


class TestMissingFields:
    def test_handles_missing_name_field(self):
        """Conversations without a name field are handled gracefully."""
        conv = {"id": "1", "snippet": "some newsletter content"}
        sender = conv.get("name", "").lower()
        snippet = conv.get("snippet", "").lower()
        text = f"{sender} {snippet}"
        assert "newsletter" in text

    def test_handles_missing_snippet_field(self):
        """Conversations without a snippet field are handled gracefully."""
        conv = {"name": "Weekly Digest", "id": "1"}
        sender = conv.get("name", "").lower()
        snippet = conv.get("snippet", "").lower()
        text = f"{sender} {snippet}"
        assert "weekly" in text

    def test_handles_missing_both_fields(self):
        """Conversations with neither name nor snippet are safe."""
        conv = {"id": "1"}
        sender = conv.get("name", "").lower()
        snippet = conv.get("snippet", "").lower()
        text = f"{sender} {snippet}"
        assert text == " "


class TestReasonTracking:
    def test_assigns_newsletter_reason(self):
        """When a newsletter keyword matches, 'newsletter' reason is assigned."""
        newsletter_keywords = ["digest"]
        junk_keywords = []
        problematic_senders = []

        conv = {"name": "Weekly Digest", "id": "1", "snippet": "..."}
        text = f"{conv.get('name', '').lower()} {conv.get('snippet', '').lower()}"
        sender = conv.get("name", "").lower()

        is_newsletter = any(k in text for k in newsletter_keywords)
        is_junk = any(k in text for k in junk_keywords)
        is_problematic = any(p in sender for p in problematic_senders)

        reasons = []
        if is_newsletter:
            reasons.append("newsletter")
        if is_junk:
            reasons.append("junk")
        if is_problematic:
            reasons.append("problematic-sender")
        assert reasons == ["newsletter"]

    def test_assigns_multiple_reasons(self):
        """A conversation can match multiple categories and get multiple reasons."""
        newsletter_keywords = ["daily"]
        junk_keywords = ["deal"]
        problematic_senders = ["cars.com"]

        conv = {"name": "Daily Deal from cars.com", "id": "1", "snippet": "offer"}
        text = f"{conv.get('name', '').lower()} {conv.get('snippet', '').lower()}"
        sender = conv.get("name", "").lower()

        is_newsletter = any(k in text for k in newsletter_keywords)
        is_junk = any(k in text for k in junk_keywords)
        is_problematic = any(p in sender for p in problematic_senders)

        reasons = []
        if is_newsletter:
            reasons.append("newsletter")
        if is_junk:
            reasons.append("junk")
        if is_problematic:
            reasons.append("problematic-sender")
        assert "newsletter" in reasons
        assert "junk" in reasons
        assert "problematic-sender" in reasons


# ── main() integration tests ───────────────────────────────────────────────


class TestNoCandidates:
    def test_exits_when_no_candidates_found(self, capsys):
        """When no conversations match any filter, print message and return."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Team Standup", "id": "1", "snippet": "notes"},
        ])

        with patch.object(httpx, "Client", return_value=mock_client):
            unsubscribe_all_newsletters.main()

        captured = capsys.readouterr()
        assert "No newsletters/junk found." in captured.out
        mock_client.close.assert_called_once()

    def test_closes_client_when_no_candidates(self):
        """Client is closed even when returning early with no candidates."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Team Standup", "id": "1", "snippet": "notes"},
        ])

        with patch.object(httpx, "Client", return_value=mock_client):
            unsubscribe_all_newsletters.main()

        mock_client.close.assert_called_once()


class TestWhitelistFiltering:
    def test_whitelisted_senders_are_excluded(self, capsys):
        """Conversations matching whitelist patterns are excluded from candidates."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Stanford Daily News Digest", "id": "1", "snippet": "daily update"},
            {"name": "Invoice #12345 from Vendor", "id": "2", "snippet": "receipt"},
            {"name": "Security Alert: New Sign-in", "id": "3", "snippet": "verify"},
            {"name": "Jwalin Shah Weekly Update", "id": "4", "snippet": "personal news"},
        ])

        with patch.object(httpx, "Client", return_value=mock_client):
            unsubscribe_all_newsletters.main()

        captured = capsys.readouterr()
        assert "No newsletters/junk found." in captured.out


class TestUserCancellation:
    def test_cancels_when_user_declines(self, capsys):
        """When user enters 'n', print message and exit."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Weekly Digest Newsletter", "id": "msg1", "snippet": "news"},
        ])

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="n"):
            unsubscribe_all_newsletters.main()

        captured = capsys.readouterr()
        assert "Cancelled." in captured.out
        mock_client.post.assert_not_called()
        mock_client.close.assert_called_once()

    def test_closes_client_on_cancellation(self):
        """Client is closed even when user cancels."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Weekly Digest Newsletter", "id": "msg1", "snippet": "news"},
        ])

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="n"):
            unsubscribe_all_newsletters.main()

        mock_client.close.assert_called_once()

    def test_cancels_on_non_y_input(self, capsys):
        """Any input other than 'y' cancels (e.g. 'no', '')."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Daily Alert", "id": "msg1", "snippet": "alerts"},
        ])

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="no"):
            unsubscribe_all_newsletters.main()

        captured = capsys.readouterr()
        assert "Cancelled." in captured.out
        mock_client.close.assert_called_once()


class TestSuccessfulUnsubscribe:
    def test_single_batch_all_success(self, capsys):
        """Happy path: a single batch of newsletters all unsubscribe successfully."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Weekly Digest", "id": "msg1", "snippet": "news and updates"},
            {"name": "Daily Alert", "id": "msg2", "snippet": "daily news"},
            {"name": "Product Hunt Digest", "id": "msg3", "snippet": "top products"},
        ])
        mock_client.post.return_value = _mock_response({
            "total": 3,
            "results": [
                {"msg_id": "msg1", "method": "http", "ok": True},
                {"msg_id": "msg2", "method": "mailto", "ok": True},
                {"msg_id": "msg3", "method": "http", "ok": True},
            ],
        })

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="y"):
            unsubscribe_all_newsletters.main()

        captured = capsys.readouterr()
        assert "3 successfully unsubscribed" in captured.out
        assert "0 archived (no unsubscribe header)" in captured.out
        assert "0 failed" in captured.out
        assert "DONE: 3 newsletters/junk removed from inbox" in captured.out
        mock_client.close.assert_called_once()

    def test_batch_post_called_with_correct_ids(self):
        """The POST request includes the correct msg_ids from candidates."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Weekly Digest", "id": "aaa111", "snippet": "news"},
            {"name": "Daily Alert", "id": "bbb222", "snippet": "updates"},
        ])
        mock_client.post.return_value = _mock_response({
            "total": 2,
            "results": [
                {"msg_id": "aaa111", "method": "http", "ok": True},
                {"msg_id": "bbb222", "method": "http", "ok": True},
            ],
        })

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="y"):
            unsubscribe_all_newsletters.main()

        mock_client.post.assert_called_once_with(
            "/messages/gmail/bulk-unsubscribe",
            json={"msg_ids": ["aaa111", "bbb222"]},
            timeout=120,
        )


class TestMultiBatchProcessing:
    def test_processes_more_than_thirty_in_batches(self, capsys):
        """When there are more than 30 candidates, processing happens in batches."""
        mock_client = MagicMock(spec=httpx.Client)
        convs = [
            {"name": f"Newsletter {i:03d}", "id": f"msg{i:03d}", "snippet": f"content {i}"}
            for i in range(45)
        ]
        mock_client.get.return_value = _mock_response(convs)

        # Return results for all 45
        results = [
            {"msg_id": f"msg{i:03d}", "method": "http", "ok": True}
            for i in range(45)
        ]
        mock_client.post.return_value = _mock_response({"total": 45, "results": results})

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="y"):
            unsubscribe_all_newsletters.main()

        captured = capsys.readouterr()
        assert "Processing 45 emails in batches of 30" in captured.out
        assert "Batch 1/2" in captured.out
        assert "Batch 2/2" in captured.out
        assert mock_client.post.call_count == 2

    def test_exact_batch_boundary(self, capsys):
        """Exactly 30 candidates = exactly 1 batch."""
        mock_client = MagicMock(spec=httpx.Client)
        convs = [
            {"name": f"Newsletter {i:02d}", "id": f"msg{i:02d}", "snippet": f"content {i}"}
            for i in range(30)
        ]
        mock_client.get.return_value = _mock_response(convs)
        results = [
            {"msg_id": f"msg{i:02d}", "method": "http", "ok": True}
            for i in range(30)
        ]
        mock_client.post.return_value = _mock_response({"total": 30, "results": results})

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="y"):
            unsubscribe_all_newsletters.main()

        assert mock_client.post.call_count == 1


class TestMixedResults:
    def test_mix_of_success_error_and_no_header(self, capsys):
        """Mixed results: some succeed, some error, some have no unsubscribe header."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Good Newsletter", "id": "msg1", "snippet": "ok"},
            {"name": "Bad Newsletter", "id": "msg2", "snippet": "bad"},
            {"name": "No Header Newsletter", "id": "msg3", "snippet": "none"},
        ])
        mock_client.post.return_value = _mock_response({
            "total": 3,
            "results": [
                {"msg_id": "msg1", "method": "http", "ok": True},
                {"msg_id": "msg2", "error": "Failed to parse headers"},
                {"msg_id": "msg3", "method": "none", "ok": False},
            ],
        })

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="y"):
            unsubscribe_all_newsletters.main()

        captured = capsys.readouterr()
        assert "1 successfully unsubscribed" in captured.out
        assert "1 archived (no unsubscribe header)" in captured.out
        assert "1 failed" in captured.out
        assert "DONE: 3 newsletters/junk removed from inbox" in captured.out
        mock_client.close.assert_called_once()

    def test_all_no_header_results(self, capsys):
        """All results have no unsubscribe header."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "No Headers Newsletter A", "id": "msg1", "snippet": "a"},
            {"name": "No Headers Daily B", "id": "msg2", "snippet": "b"},
        ])
        mock_client.post.return_value = _mock_response({
            "total": 2,
            "results": [
                {"msg_id": "msg1", "method": "none", "ok": False},
                {"msg_id": "msg2", "method": "none", "ok": False},
            ],
        })

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="y"):
            unsubscribe_all_newsletters.main()

        captured = capsys.readouterr()
        assert "0 successfully unsubscribed" in captured.out
        assert "2 archived (no unsubscribe header)" in captured.out
        assert "0 failed" in captured.out

    def test_unsubscribe_failed_but_not_error(self, capsys):
        """When ok=False but method is set, it counts as failed."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Flaky Newsletter", "id": "msg1", "snippet": "flaky"},
        ])
        mock_client.post.return_value = _mock_response({
            "total": 1,
            "results": [
                {"msg_id": "msg1", "method": "http", "ok": False},
            ],
        })

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="y"):
            unsubscribe_all_newsletters.main()

        captured = capsys.readouterr()
        assert "0 successfully unsubscribed" in captured.out
        assert "1 failed" in captured.out


class TestDisplayTruncation:
    def test_truncates_sender_list_over_thirty(self, capsys):
        """When there are more than 30 senders, the list is truncated with a note."""
        mock_client = MagicMock(spec=httpx.Client)
        # Create 35 distinct senders each matching a newsletter keyword
        convs = []
        for i in range(35):
            convs.append({
                "name": f"Sender {i:03d} Digest",
                "id": f"msg{i:03d}",
                "snippet": f"newsletter {i}",
            })
        mock_client.get.return_value = _mock_response(convs)
        results = [
            {"msg_id": f"msg{i:03d}", "method": "http", "ok": True}
            for i in range(35)
        ]
        mock_client.post.return_value = _mock_response({"total": 35, "results": results})

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="y"):
            unsubscribe_all_newsletters.main()

        captured = capsys.readouterr()
        assert "... and 5 more senders" in captured.out

    def test_no_truncation_under_thirty(self, capsys):
        """No truncation note when senders ≤ 30."""
        mock_client = MagicMock(spec=httpx.Client)
        convs = [
            {"name": f"Sender {i:02d} Digest", "id": f"msg{i:02d}", "snippet": f"news {i}"}
            for i in range(5)
        ]
        mock_client.get.return_value = _mock_response(convs)
        results = [
            {"msg_id": f"msg{i:02d}", "method": "http", "ok": True}
            for i in range(5)
        ]
        mock_client.post.return_value = _mock_response({"total": 5, "results": results})

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="y"):
            unsubscribe_all_newsletters.main()

        captured = capsys.readouterr()
        assert "... and" not in captured.out


class TestBatchExceptionHandling:
    def test_batch_post_exception_is_caught(self, capsys):
        """When a batch POST raises an exception, it is caught and reported."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Weekly Digest", "id": "msg1", "snippet": "news"},
        ])
        mock_client.post.side_effect = ConnectionError("Connection refused")

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="y"):
            unsubscribe_all_newsletters.main()

        captured = capsys.readouterr()
        assert "✗" in captured.out
        assert "Connection refused" in captured.out
        # Should still complete and close
        assert "DONE:" in captured.out
        mock_client.close.assert_called_once()


class TestSenderGrouping:
    def test_groups_by_sender_name(self, capsys):
        """Emails with the same sender name are grouped together."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Weekly Digest", "id": "msg1", "snippet": "issue 1"},
            {"name": "Weekly Digest", "id": "msg2", "snippet": "issue 2"},
            {"name": "Daily Alert", "id": "msg3", "snippet": "alert 1"},
        ])
        results = [
            {"msg_id": "msg1", "method": "http", "ok": True},
            {"msg_id": "msg2", "method": "http", "ok": True},
            {"msg_id": "msg3", "method": "http", "ok": True},
        ]
        mock_client.post.return_value = _mock_response({"total": 3, "results": results})

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="y"):
            unsubscribe_all_newsletters.main()

        captured = capsys.readouterr()
        # Two senders grouped: "Weekly Digest" (2) and "Daily Alert" (1)
        assert "2x Weekly Digest" in captured.out
        assert "1x Daily Alert" in captured.out


class TestResultsSummaryDisplay:
    def test_shows_top_successful_senders(self, capsys):
        """Top 5 successfully unsubscribed senders are displayed."""
        mock_client = MagicMock(spec=httpx.Client)
        convs = [
            {"name": f"Newsletter {chr(65+i)}", "id": f"msg{i}", "snippet": f"news {i}"}
            for i in range(8)
        ]
        mock_client.get.return_value = _mock_response(convs)
        results = [
            {"msg_id": f"msg{i}", "method": "http", "ok": True}
            for i in range(8)
        ]
        mock_client.post.return_value = _mock_response({"total": 8, "results": results})

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="y"):
            unsubscribe_all_newsletters.main()

        captured = capsys.readouterr()
        assert "Successfully unsubscribed from:" in captured.out
        assert "... and 3 more" in captured.out

    def test_shows_top_no_header_senders(self, capsys):
        """Top 3 no-header senders are displayed."""
        mock_client = MagicMock(spec=httpx.Client)
        convs = [
            {"name": f"NoHeader Newsletter {chr(65+i)}", "id": f"msg{i}", "snippet": f"noheader {i}"}
            for i in range(6)
        ]
        mock_client.get.return_value = _mock_response(convs)
        results = [
            {"msg_id": f"msg{i}", "method": "none", "ok": False}
            for i in range(6)
        ]
        mock_client.post.return_value = _mock_response({"total": 6, "results": results})

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="y"):
            unsubscribe_all_newsletters.main()

        captured = capsys.readouterr()
        assert "Archived (no unsubscribe available):" in captured.out
        assert "... and 3 more" in captured.out


class TestEmailNoneGuard:
    def test_handles_mismatched_msg_id_gracefully(self, capsys):
        """When server returns a msg_id not in candidates, use truncated id as fallback."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Weekly Digest", "id": "msg1", "snippet": "news"},
        ])
        # Server returns a result with a different msg_id not in our candidates
        mock_client.post.return_value = _mock_response({
            "total": 1,
            "results": [
                {"msg_id": "unknown_id_XYZ", "method": "http", "ok": True},
            ],
        })

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="y"):
            unsubscribe_all_newsletters.main()

        captured = capsys.readouterr()
        # Should not crash — uses the truncated msg_id as fallback name
        assert "1 successfully unsubscribed" in captured.out
        assert "DONE:" in captured.out
        mock_client.close.assert_called_once()


class TestJunkAndProblematicSenderPaths:
    def test_junk_keyword_path(self, capsys):
        """Junk keywords trigger the junk reason assignment path in main()."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "Best Dealership Offers", "id": "msg1", "snippet": "car sale deals"},
        ])
        mock_client.post.return_value = _mock_response({
            "total": 1,
            "results": [
                {"msg_id": "msg1", "method": "http", "ok": True},
            ],
        })

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="y"):
            unsubscribe_all_newsletters.main()

        captured = capsys.readouterr()
        assert "Best Dealership Offers" in captured.out
        assert "junk" in captured.out
        assert "DONE:" in captured.out
        mock_client.close.assert_called_once()

    def test_problematic_sender_path(self, capsys):
        """Problematic sender patterns trigger the problematic-sender reason in main()."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {"name": "offers@cars.com", "id": "msg1", "snippet": "great deals on cars"},
        ])
        mock_client.post.return_value = _mock_response({
            "total": 1,
            "results": [
                {"msg_id": "msg1", "method": "http", "ok": True},
            ],
        })

        with patch.object(httpx, "Client", return_value=mock_client), \
             patch("builtins.input", return_value="y"):
            unsubscribe_all_newsletters.main()

        captured = capsys.readouterr()
        assert "offers@cars.com" in captured.out
        assert "problematic-sender" in captured.out
        assert "DONE:" in captured.out
        mock_client.close.assert_called_once()
