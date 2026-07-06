"""Tests for src/contact_relationship_sync.py — contact relationship report builder."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from email.utils import formatdate
from unittest.mock import MagicMock, patch

import pytest

from contacts import ContactBook
from src.contact_relationship_sync import (
    AUTOMATED_RE,
    ChannelStats,
    ContactRelationship,
    RelationshipBook,
    _gmail_headers,
    _gmail_timestamp,
    _identifier_key,
    _source_status,
    load_github,
    load_imessage,
    load_index_fallback,
    load_linkedin,
    render_markdown,
)

pytestmark = pytest.mark.safe


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_relationship(
    key: str = "alice",
    name: str = "Alice",
    identifiers: set[str] | None = None,
    channels: dict[str, ChannelStats] | None = None,
) -> ContactRelationship:
    return ContactRelationship(
        key=key,
        name=name,
        identifiers=identifiers or set(),
        channels=channels or {},
    )


def _make_stats(
    interactions: int = 0,
    sent: int = 0,
    received: int = 0,
) -> ChannelStats:
    s = ChannelStats()
    s.interactions = interactions
    s.sent = sent
    s.received = received
    return s


# ---------------------------------------------------------------------------
# _source_status
# ---------------------------------------------------------------------------


class TestSourceStatus:
    def test_available(self):
        result = _source_status(True, "ok", 42)
        assert result == {"available": True, "detail": "ok", "interactions": 42}

    def test_unavailable_zero(self):
        result = _source_status(False, "missing", 0)
        assert result == {"available": False, "detail": "missing", "interactions": 0}

    def test_default_interactions(self):
        result = _source_status(True, "present")
        assert result == {"available": True, "detail": "present", "interactions": 0}


# ---------------------------------------------------------------------------
# _identifier_key
# ---------------------------------------------------------------------------


class TestIdentifierKey:
    def test_email_preserved(self):
        assert _identifier_key("Alice@Example.com") == "alice@example.com"

    def test_phone_last_10_digits(self):
        assert _identifier_key("+1 (555) 123-4567") == "5551234567"

    def test_short_digits_preserved(self):
        assert _identifier_key("42") == "42"

    def test_stripped(self):
        assert _identifier_key("  test  ") == "test"


# ---------------------------------------------------------------------------
# _gmail_headers
# ---------------------------------------------------------------------------


class TestGmailHeaders:
    def test_empty_message(self):
        assert _gmail_headers({}) == {}

    def test_no_payload(self):
        assert _gmail_headers({"payload": {}}) == {}

    def test_normal_headers(self):
        msg = {
            "payload": {
                "headers": [
                    {"name": "From", "value": "alice@example.com"},
                    {"name": "Subject", "value": "Hello"},
                    {"name": "Date", "value": "Mon, 1 Jan 2024 00:00:00 +0000"},
                ]
            }
        }
        result = _gmail_headers(msg)
        assert result == {
            "from": "alice@example.com",
            "subject": "Hello",
            "date": "Mon, 1 Jan 2024 00:00:00 +0000",
        }

    def test_missing_name_or_value(self):
        msg = {
            "payload": {
                "headers": [
                    {"name": "", "value": "orphan"},
                    {"name": "OnlyName"},
                ]
            }
        }
        result = _gmail_headers(msg)
        assert result == {"": "orphan", "onlyname": ""}

    def test_casefold_keys(self):
        msg = {
            "payload": {
                "headers": [
                    {"name": "FROM", "value": "bob@test.com"},
                ]
            }
        }
        result = _gmail_headers(msg)
        assert "from" in result
        assert result["from"] == "bob@test.com"


# ---------------------------------------------------------------------------
# _gmail_timestamp
# ---------------------------------------------------------------------------


class TestGmailTimestamp:
    def test_internal_date(self):
        msg = {"internalDate": "1704067200000"}  # 2024-01-01T00:00:00 UTC in ms
        result = _gmail_timestamp(msg, {})
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 1
        assert result.tzinfo == UTC

    def test_internal_date_zero_skipped(self):
        msg = {"internalDate": "0"}
        with patch("src.contact_relationship_sync.parsedate_to_datetime",
                   side_effect=TypeError):
            result = _gmail_timestamp(msg, {})
        assert result is None

    def test_fallback_to_date_header(self):
        ts = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
        date_str = formatdate(ts.timestamp(), usegmt=True)
        result = _gmail_timestamp({}, {"date": date_str})
        assert result is not None
        assert result.year == 2024
        assert result.month == 6
        assert result.day == 15

    def test_invalid_date_header(self):
        result = _gmail_timestamp({}, {"date": "not-a-date"})
        assert result is None

    def test_empty_input(self):
        result = _gmail_timestamp({}, {})
        assert result is None

    def test_internal_date_as_int(self):
        msg = {"internalDate": 1704067200000}
        result = _gmail_timestamp(msg, {})
        assert result is not None
        assert result.year == 2024


# ---------------------------------------------------------------------------
# AUTOMATED_RE
# ---------------------------------------------------------------------------


class TestAutomatedRE:
    @pytest.mark.parametrize(
        "candidate,expected",
        [
            ("no-reply@example.com", True),
            ("notifications@github.com", True),
            ("newsletter@company.com", True),
            ("updates@service.io", True),
            ("support@help.org", True),
            ("team@startup.com", True),
            ("mailer@lists.example.com", True),
            ("marketing@brand.co", True),
            ("hello@product.com", True),
            ("info@business.net", True),
            ("security@alerts.com", True),
            ("noreply@test.com", True),
            ("no-reply.example@corp.com", True),
            # Non-matches
            ("alice@example.com", False),
            ("bob.smith@company.com", False),
            ("jwalin@personal.com", False),
            ("", False),
        ],
    )
    def test_patterns(self, candidate, expected):
        assert bool(AUTOMATED_RE.search(candidate)) == expected

    def test_case_insensitive(self):
        assert AUTOMATED_RE.search("NO-REPLY@example.com")
        assert AUTOMATED_RE.search("Newsletter@company.com")
        assert AUTOMATED_RE.search("INFO@business.net")

    def test_boundary_chars(self):
        # Must have boundary char (^-_.) before or after
        assert AUTOMATED_RE.search("prefix.no-reply@test.com")  # dot before
        # "noreply" at string start matches ^ boundary
        assert AUTOMATED_RE.search("noreply")  # ^ start + $ end = boundaries
        # Without proper boundary char, middle-of-word doesn't match
        assert not AUTOMATED_RE.search("xnoreply@test.com")  # word prefix, no boundary

    def test_dot_prefix(self):
        assert AUTOMATED_RE.search("something.no-reply@test.com")


# ---------------------------------------------------------------------------
# RelationshipBook.to_merged_contacts
# ---------------------------------------------------------------------------


class TestRelationshipBookToMergedContacts:
    def test_empty_book(self):
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {}
        result = book.to_merged_contacts()
        assert result == []

    def test_single_contact_email(self):
        contact = _make_relationship(
            key="alice",
            name="Alice",
            identifiers={"alice@example.com"},
            channels={"gmail": _make_stats(10, 5, 5)},
        )
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {"alice": contact}
        result = book.to_merged_contacts()
        assert len(result) == 1
        assert result[0].name == "Alice"
        assert result[0].emails == {"alice@example.com"}
        assert result[0].phones == []
        assert result[0].sources == ["gmail"]

    def test_single_contact_phone(self):
        contact = _make_relationship(
            key="bob",
            name="Bob",
            identifiers={"+15551234567"},
            channels={"imessage": _make_stats(5, 2, 3)},
        )
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {"bob": contact}
        result = book.to_merged_contacts()
        assert len(result) == 1
        assert result[0].emails == set()
        assert result[0].phones == ["+15551234567"]
        assert result[0].sources == ["imessage"]

    def test_mixed_identifiers(self):
        contact = _make_relationship(
            key="charlie",
            name="Charlie",
            identifiers={"charlie@example.com", "+15559876543"},
            channels={"gmail": _make_stats(5), "imessage": _make_stats(3)},
        )
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {"charlie": contact}
        result = book.to_merged_contacts()
        assert len(result) == 1
        assert result[0].emails == {"charlie@example.com"}
        assert result[0].phones == ["+15559876543"]
        assert set(result[0].sources) == {"gmail", "imessage"}

    def test_multiple_contacts(self):
        a = _make_relationship(key="a", name="A", channels={"gmail": _make_stats()})
        b = _make_relationship(key="b", name="B", channels={"github": _make_stats()})
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {"a": a, "b": b}
        result = book.to_merged_contacts()
        assert len(result) == 2
        names = {c.name for c in result}
        assert names == {"A", "B"}


# ---------------------------------------------------------------------------
# load_imessage
# ---------------------------------------------------------------------------


class TestLoadImessage:
    def test_db_missing(self):
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {}
        book.aliases = {}
        with patch("src.contact_relationship_sync.IMSG_DB") as mock_db:
            mock_db.exists.return_value = False
            result = load_imessage(book)
        assert result["available"] is False
        assert "missing" in result["detail"]

    def test_empty_results(self, monkeypatch):
        """Imsg db exists but query returns no rows."""
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {}
        book.aliases = {}

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []

        mock_db = MagicMock()
        mock_db.exists.return_value = True

        with patch("src.contact_relationship_sync.IMSG_DB", mock_db), \
             patch("src.contact_relationship_sync.sqlite3") as mock_sql:
            mock_sql.connect.return_value = mock_conn
            result = load_imessage(book)

        assert result["available"] is True
        assert result["interactions"] == 0

    def test_normal_results(self, monkeypatch):
        """Imsg db returns rows which get added to book."""
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {}
        book.aliases = {}
        # Need a minimal add() to avoid ContactBook.load() side effects
        book.contact_book = MagicMock(spec=ContactBook)
        book.contact_book.resolve.return_value = ""

        rows = [
            ("+15551234567", "Alice", 0, 1704067200.0),  # not from me
            ("bob@example.com", "Bob", 1, 1704153600.0),   # from me
        ]
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = rows

        mock_db = MagicMock()
        mock_db.exists.return_value = True

        with patch("src.contact_relationship_sync.IMSG_DB", mock_db), \
             patch("src.contact_relationship_sync.sqlite3") as mock_sql:
            mock_sql.connect.return_value = mock_conn
            result = load_imessage(book)

        assert result["available"] is True
        assert result["interactions"] == 2
        mock_conn.close.assert_called_once()

    def test_empty_display_name_and_identifier(self, monkeypatch):
        """Rows with empty/None display_name and identifier are handled."""
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {}
        book.aliases = {}
        book.contact_book = MagicMock(spec=ContactBook)
        book.contact_book.resolve.return_value = ""

        rows = [("", None, 0, 1704067200.0)]
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = rows

        mock_db = MagicMock()
        mock_db.exists.return_value = True

        with patch("src.contact_relationship_sync.IMSG_DB", mock_db), \
             patch("src.contact_relationship_sync.sqlite3") as mock_sql:
            mock_sql.connect.return_value = mock_conn
            result = load_imessage(book)

        assert result["available"] is True

    def test_many_rows(self, monkeypatch):
        """Large result set — all rows processed."""
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {}
        book.aliases = {}
        book.contact_book = MagicMock(spec=ContactBook)
        book.contact_book.resolve.return_value = ""

        rows = [(f"+1555000{i:04d}", f"Contact{i}", i % 2, 1704067200.0 + i)
                for i in range(100)]
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = rows

        mock_db = MagicMock()
        mock_db.exists.return_value = True

        with patch("src.contact_relationship_sync.IMSG_DB", mock_db), \
             patch("src.contact_relationship_sync.sqlite3") as mock_sql:
            mock_sql.connect.return_value = mock_conn
            result = load_imessage(book)

        assert result["interactions"] == 100


# ---------------------------------------------------------------------------
# load_linkedin
# ---------------------------------------------------------------------------


class TestLoadLinkedin:
    def test_db_not_found(self):
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {}
        book.aliases = {}
        with patch("src.contact_relationship_sync._openhuman_linkedin_db_path", return_value=None):
            result = load_linkedin(book)
        assert result["available"] is False
        assert "not found" in result["detail"]

    def test_empty_results(self):
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {}
        book.aliases = {}

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []

        with patch("src.contact_relationship_sync._openhuman_linkedin_db_path", return_value="/fake/li.db"), \
             patch("src.contact_relationship_sync.sqlite3") as mock_sql:
            mock_sql.connect.return_value = mock_conn
            result = load_linkedin(book)

        assert result["available"] is True
        assert result["interactions"] == 0

    def test_normal_results(self):
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {}
        book.aliases = {}
        book.contact_book = MagicMock(spec=ContactBook)
        book.contact_book.resolve.return_value = ""

        rows = [
            ("Alice", "https://linkedin.com/in/alice", "2024-01-01T00:00:00Z", 0, "Hi there"),
            ("Bob", "https://linkedin.com/in/bob", "2024-01-02T00:00:00Z", 1, "Thanks"),
        ]
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = rows

        with patch("src.contact_relationship_sync._openhuman_linkedin_db_path", return_value="/fake/li.db"), \
             patch("src.contact_relationship_sync.sqlite3") as mock_sql:
            mock_sql.connect.return_value = mock_conn
            result = load_linkedin(book)

        assert result["available"] is True
        assert result["interactions"] == 2

    def test_null_name_fallback_to_sender(self):
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {}
        book.aliases = {}
        book.contact_book = MagicMock(spec=ContactBook)
        book.contact_book.resolve.return_value = ""

        rows = [(None, None, "2024-01-01T00:00:00Z", 0, "")]
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = rows

        with patch("src.contact_relationship_sync._openhuman_linkedin_db_path", return_value="/fake/li.db"), \
             patch("src.contact_relationship_sync.sqlite3") as mock_sql:
            mock_sql.connect.return_value = mock_conn
            result = load_linkedin(book)

        # Should not crash; empty identifiers may produce no contacts
        assert result["available"] is True


# ---------------------------------------------------------------------------
# load_index_fallback
# ---------------------------------------------------------------------------


class TestLoadIndexFallback:
    def test_db_missing(self):
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {}
        book.aliases = {}
        with patch("src.contact_relationship_sync.DEFAULT_INDEX_DB") as mock_db:
            mock_db.exists.return_value = False
            result = load_index_fallback(book)
        assert result["available"] is False
        assert "missing" in result["detail"]

    def test_empty_results(self):
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {}
        book.aliases = {}

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []

        mock_db = MagicMock()
        mock_db.exists.return_value = True

        with patch("src.contact_relationship_sync.DEFAULT_INDEX_DB", mock_db), \
             patch("src.contact_relationship_sync.sqlite3") as mock_sql:
            mock_sql.connect.return_value = mock_conn
            result = load_index_fallback(book)

        assert result["available"] is False  # bool(empty rows) = False
        assert result["interactions"] == 0

    def test_normal_results(self):
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {}
        book.aliases = {}
        book.contact_book = MagicMock(spec=ContactBook)
        book.contact_book.resolve.return_value = ""

        rows = [
            {"source": "gmail", "sender": "Alice <alice@example.com>", "recipients_json": "[]",
             "subject": "Hello", "created_at": "2024-01-01T00:00:00Z"},
            {"source": "linkedin", "sender": "Bob <bob@linkedin.com>", "recipients_json": "[]",
             "subject": "Hi", "created_at": "2024-01-02T00:00:00Z"},
        ]
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = rows

        mock_db = MagicMock()
        mock_db.exists.return_value = True

        with patch("src.contact_relationship_sync.DEFAULT_INDEX_DB", mock_db), \
             patch("src.contact_relationship_sync.sqlite3") as mock_sql:
            mock_sql.connect.return_value = mock_conn
            result = load_index_fallback(book)

        assert result["available"] is True
        assert result["interactions"] == 2

    def test_skips_me_sender(self):
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {}
        book.aliases = {}
        book.contact_book = MagicMock(spec=ContactBook)
        book.contact_book.resolve.return_value = ""

        rows = [
            {"source": "gmail", "sender": "Me", "recipients_json": "[]",
             "subject": "Sent by me", "created_at": "2024-01-01T00:00:00Z"},
            {"source": "gmail", "sender": "Alice <alice@example.com>", "recipients_json": "[]",
             "subject": "From Alice", "created_at": "2024-01-02T00:00:00Z"},
        ]
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = rows

        mock_db = MagicMock()
        mock_db.exists.return_value = True

        with patch("src.contact_relationship_sync.DEFAULT_INDEX_DB", mock_db), \
             patch("src.contact_relationship_sync.sqlite3") as mock_sql:
            mock_sql.connect.return_value = mock_conn
            result = load_index_fallback(book)

        # Only Alice should be counted; "Me" is skipped
        assert result["interactions"] == 1


# ---------------------------------------------------------------------------
# load_github
# ---------------------------------------------------------------------------


class TestLoadGithub:
    def test_gh_not_installed(self):
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {}
        book.aliases = {}
        with patch("src.contact_relationship_sync.shutil.which", return_value=None):
            result = load_github(book, limit=100)
        assert result["available"] is False
        assert "not installed" in result["detail"]

    def test_subprocess_error(self):
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {}
        book.aliases = {}
        with patch("src.contact_relationship_sync.shutil.which", return_value="/usr/bin/gh"), \
             patch("src.contact_relationship_sync.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "gh")
            result = load_github(book, limit=100)
        assert result["available"] is False
        assert "GitHub query failed" in result["detail"]

    def test_json_decode_error(self):
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {}
        book.aliases = {}
        with patch("src.contact_relationship_sync.shutil.which", return_value="/usr/bin/gh"), \
             patch("src.contact_relationship_sync.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="not json", spec=["stdout"])
            result = load_github(book, limit=100)
        assert result["available"] is False
        assert "GitHub query failed" in result["detail"]

    def test_empty_items(self):
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {}
        book.aliases = {}
        with patch("src.contact_relationship_sync.shutil.which", return_value="/usr/bin/gh"), \
             patch("src.contact_relationship_sync.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=json.dumps({"items": []}), spec=["stdout"])
            result = load_github(book, limit=100)
        assert result["available"] is True
        assert result["interactions"] == 0

    def test_normal_results(self):
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {}
        book.aliases = {}
        book.contact_book = MagicMock(spec=ContactBook)
        book.contact_book.resolve.return_value = ""

        items = [
            {
                "user": {"login": "contributor1"},
                "repository_url": "https://api.github.com/repos/owner/repo",
                "updated_at": "2024-01-01T00:00:00Z",
                "title": "Fix bug",
            },
            {
                "user": {"login": "contributor2"},
                "repository_url": "https://api.github.com/repos/owner/other",
                "updated_at": "2024-01-02T00:00:00Z",
                "title": "Add feature",
            },
        ]
        with patch("src.contact_relationship_sync.shutil.which", return_value="/usr/bin/gh"), \
             patch("src.contact_relationship_sync.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=json.dumps({"items": items}), spec=["stdout"])
            result = load_github(book, limit=100)
        assert result["available"] is True
        assert result["interactions"] == 2

    def test_skips_self_and_bots(self):
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {}
        book.aliases = {}
        book.contact_book = MagicMock(spec=ContactBook)
        book.contact_book.resolve.return_value = ""

        items = [
            {"user": {"login": "jwalin-shah"}, "repository_url": "...", "updated_at": "...", "title": "Mine"},
            {"user": {"login": "dependabot[bot]"}, "repository_url": "...", "updated_at": "...", "title": "Bump"},
            {"user": {"login": "real-person"}, "repository_url": "https://api.github.com/repos/o/r", "updated_at": "2024-01-01T00:00:00Z", "title": "PR"},
        ]
        with patch("src.contact_relationship_sync.shutil.which", return_value="/usr/bin/gh"), \
             patch("src.contact_relationship_sync.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=json.dumps({"items": items}), spec=["stdout"])
            result = load_github(book, limit=100)
        assert result["interactions"] == 1  # only real-person

    def test_limit_applied(self):
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {}
        book.aliases = {}
        book.contact_book = MagicMock(spec=ContactBook)
        book.contact_book.resolve.return_value = ""

        items = [
            {"user": {"login": f"user{i}"}, "repository_url": f"https://api.github.com/repos/o/r{i}", "updated_at": "2024-01-01T00:00:00Z", "title": f"Issue {i}"}
            for i in range(10)
        ]
        with patch("src.contact_relationship_sync.shutil.which", return_value="/usr/bin/gh"), \
             patch("src.contact_relationship_sync.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=json.dumps({"items": items}), spec=["stdout"])
            result = load_github(book, limit=3)
        assert result["interactions"] == 3

    def test_missing_login_skipped(self):
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {}
        book.aliases = {}

        items = [
            {"user": {}, "repository_url": "...", "updated_at": "...", "title": "No login"},
        ]
        with patch("src.contact_relationship_sync.shutil.which", return_value="/usr/bin/gh"), \
             patch("src.contact_relationship_sync.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=json.dumps({"items": items}), spec=["stdout"])
            result = load_github(book, limit=100)
        assert result["interactions"] == 0


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------


class TestRenderMarkdown:
    def _book_with_contacts(self, *relationships: ContactRelationship) -> RelationshipBook:
        book = RelationshipBook.__new__(RelationshipBook)
        book.contacts = {r.key: r for r in relationships}
        book.aliases = {}
        return book

    def _status(self, **overrides) -> dict:
        base = {
            "imessage": _source_status(True, "ok", 10),
            "gmail": _source_status(True, "ok", 50),
            "linkedin": _source_status(False, "missing", 0),
            "github": _source_status(True, "ok", 5),
            "generated_at": "2024-01-01T00:00:00+00:00",
        }
        base.update(overrides)
        return base

    def test_basic_rendering(self):
        contact = _make_relationship(
            key="alice",
            name="Alice",
            identifiers={"alice@example.com"},
            channels={"gmail": _make_stats(10, 5, 5)},
        )
        book = self._book_with_contacts(contact)
        status = self._status()
        ref = datetime(2024, 1, 1, tzinfo=UTC)

        output = render_markdown(book, status, limit=50, reference=ref)
        assert "# Contact Relationship Report" in output
        assert "Alice" in output
        assert "gmail" in output
        assert "Generated:" in output

    def test_empty_contacts(self):
        book = self._book_with_contacts()
        status = self._status()
        output = render_markdown(book, status)
        assert "## Unified Contacts (0)" in output

    def test_automated_sender_filtered(self):
        # A contact whose only identifier matches AUTOMATED_RE is filtered
        contact = _make_relationship(
            key="noreply",
            name="No Reply",
            identifiers={"no-reply@example.com"},
            channels={"gmail": _make_stats(10, 0, 10)},
        )
        book = self._book_with_contacts(contact)
        status = self._status()
        output = render_markdown(book, status)
        # The no-reply contact's channel is gmail (preferred), and it matches AUTOMATED_RE,
        # so it should be filtered from the rendering
        assert "No Reply" not in output

    def test_multiple_contacts_sorted(self):
        # Create contacts with different strengths — higher strength first
        alice = _make_relationship(
            key="alice", name="Alice",
            channels={"gmail": _make_stats(100, 50, 50)},
        )
        bob = _make_relationship(
            key="bob", name="Bob",
            channels={"gmail": _make_stats(5, 2, 3)},
        )
        book = self._book_with_contacts(alice, bob)
        status = self._status()
        ref = datetime(2024, 1, 1, tzinfo=UTC)
        output = render_markdown(book, status, limit=50, reference=ref)

        # Alice (more interactions) should appear before Bob
        alice_pos = output.index("Alice")
        bob_pos = output.index("Bob")
        assert alice_pos < bob_pos

    def test_limit(self):
        contacts = [
            _make_relationship(
                key=f"c{i}", name=f"Contact{i}",
                channels={"gmail": _make_stats(i + 1, i + 1, 0)},
            )
            for i in range(10)
        ]
        book = self._book_with_contacts(*contacts)
        status = self._status()
        output = render_markdown(book, status, limit=3, reference=datetime(2024, 1, 1, tzinfo=UTC))

        # Only top 3 should appear (the ones with highest interactions: Contact9, Contact8, Contact7)
        assert "Contact9" in output
        assert "Contact8" in output
        assert "Contact7" in output
        assert "Contact0" not in output  # lowest interactions, should be cut

    def test_unavailable_channel(self):
        status = self._status(
            gmail=_source_status(False, "auth failed", 0),
            linkedin=_source_status(False, "missing", 0),
        )
        contact = _make_relationship(
            key="alice", name="Alice",
            channels={"imessage": _make_stats(5, 2, 3)},
        )
        book = self._book_with_contacts(contact)
        output = render_markdown(book, status)
        assert "Known Gaps" in output
        assert "gmail" in output
        assert "linkedin" in output

    def test_all_available_no_gaps(self):
        status = self._status(
            imessage=_source_status(True, "ok", 10),
            gmail=_source_status(True, "ok", 50),
            linkedin=_source_status(True, "ok", 5),
            github=_source_status(True, "ok", 5),
        )
        contact = _make_relationship(
            key="alice", name="Alice",
            channels={"gmail": _make_stats(10, 5, 5)},
        )
        book = self._book_with_contacts(contact)
        output = render_markdown(book, status)
        assert "Known Gaps" not in output

    def test_index_fallback_in_source_coverage(self):
        status = self._status()
        status["index_fallback"] = _source_status(True, "from index", 30)
        contact = _make_relationship(
            key="alice", name="Alice",
            channels={"gmail": _make_stats(10, 5, 5)},
        )
        book = self._book_with_contacts(contact)
        output = render_markdown(book, status)
        assert "index_fallback" in output

    def test_interaction_history_section(self):
        contact = _make_relationship(
            key="alice", name="Alice",
            identifiers={"alice@example.com"},
            channels={"gmail": _make_stats(10, 5, 5)},
        )
        book = self._book_with_contacts(contact)
        status = self._status()
        output = render_markdown(book, status)
        assert "## Interaction History" in output
        assert "Alice" in output

    def test_safe_cell_escaping(self):
        contact = _make_relationship(
            key="pipe",
            name="Name|With|Pipes",
            channels={"gmail": _make_stats(1, 1, 0)},
        )
        book = self._book_with_contacts(contact)
        status = self._status()
        output = render_markdown(book, status)
        # Pipes should be escaped in markdown cells
        assert "Name\\|With\\|Pipes" in output

    def test_contact_with_no_interactions_filtered(self):
        contact = _make_relationship(
            key="zero", name="Zero",
            channels={"gmail": _make_stats(0, 0, 0)},
        )
        book = self._book_with_contacts(contact)
        status = self._status()
        output = render_markdown(book, status)
        assert "Zero" not in output
