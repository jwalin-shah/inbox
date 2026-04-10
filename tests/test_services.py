"""Tests for services.py — pure helper functions (no external dependencies)."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

from loguru import logger

import services
from services import (
    _build_event_body,
    _clean_body,
    _clean_email_body,
    _html_to_text,
    _parse_email_address,
    _parse_time,
    parse_quick_event,
)

# ── _clean_body ─────────────────────────────────────────────────────────────


class TestCleanBody:
    def test_none_returns_empty(self):
        assert _clean_body(None) == ""

    def test_empty_string(self):
        assert _clean_body("") == ""

    def test_strips_whitespace(self):
        assert _clean_body("  hello  ") == "hello"

    def test_replaces_attachment_placeholder(self):
        result = _clean_body("Check this \ufffc out")
        assert "(attachment)" in result
        assert "\ufffc" not in result

    def test_normal_text_unchanged(self):
        assert _clean_body("Hello, world!") == "Hello, world!"


# ── _parse_email_address ────────────────────────────────────────────────────


class TestParseEmailAddress:
    def test_name_and_email(self):
        name, email = _parse_email_address("Alice Smith <alice@example.com>")
        assert name == "Alice Smith"
        assert email == "alice@example.com"

    def test_quoted_name(self):
        name, email = _parse_email_address('"Alice Smith" <alice@example.com>')
        assert name == "Alice Smith"
        assert email == "alice@example.com"

    def test_email_only_angle_brackets(self):
        name, email = _parse_email_address("<alice@example.com>")
        assert name == "alice@example.com"
        assert email == "alice@example.com"

    def test_bare_email(self):
        name, email = _parse_email_address("alice@example.com")
        assert name == "alice@example.com"
        assert email == "alice@example.com"

    def test_whitespace_handling(self):
        name, email = _parse_email_address("  Alice Smith  <alice@example.com>  ")
        assert name == "Alice Smith"
        assert email == "alice@example.com"


# ── _html_to_text ──────────────────────────────────────────────────────────


class TestHtmlToText:
    def test_strips_tags(self):
        assert "hello" in _html_to_text("<p>hello</p>")

    def test_br_to_newline(self):
        result = _html_to_text("line1<br>line2")
        assert "line1\nline2" in result

    def test_strips_style_tags(self):
        result = _html_to_text("<style>body{color:red}</style>visible")
        assert "color:red" not in result
        assert "visible" in result

    def test_strips_script_tags(self):
        result = _html_to_text("<script>alert('x')</script>visible")
        assert "alert" not in result
        assert "visible" in result

    def test_list_items(self):
        result = _html_to_text("<ul><li>one</li><li>two</li></ul>")
        assert "one" in result
        assert "two" in result

    def test_link_extraction(self):
        html = '<a href="https://example.com">Click here</a>'
        result = _html_to_text(html)
        assert "Click here" in result
        assert "https://example.com" in result

    def test_entity_decoding(self):
        assert "&" in _html_to_text("&amp;")
        assert "<" in _html_to_text("&lt;")
        assert ">" in _html_to_text("&gt;")
        assert '"' in _html_to_text("&quot;")
        assert "'" in _html_to_text("&#39;")
        assert " " in _html_to_text("&nbsp;")


# ── _clean_email_body ──────────────────────────────────────────────────────


class TestCleanEmailBody:
    def test_strips_quoted_replies(self):
        body = "Thanks!\n> Previous message\n> More quoting"
        result = _clean_email_body(body)
        assert "Thanks!" in result
        assert "Previous message" not in result

    def test_strips_on_wrote_line(self):
        body = "Sounds good\nOn Mon, Jan 1, 2025 Alice wrote:\nOld stuff"
        result = _clean_email_body(body)
        assert "Sounds good" in result
        assert "Old stuff" not in result

    def test_strips_signature_dashes(self):
        body = "Main content\n--\nSignature here"
        result = _clean_email_body(body)
        assert "Main content" in result
        assert "Signature here" not in result

    def test_strips_triple_dashes(self):
        body = "Main content\n---\nFooter"
        result = _clean_email_body(body)
        assert "Main content" in result
        assert "Footer" not in result

    def test_strips_unsubscribe(self):
        body = "Content here\nunsubscribe from this list"
        result = _clean_email_body(body)
        assert "Content here" in result
        assert "unsubscribe" not in result.lower()

    def test_strips_tracking_urls(self):
        body = "Content\nhttps://click.example.com/track/123"
        result = _clean_email_body(body)
        assert "Content" in result
        assert "track" not in result

    def test_collapses_excessive_newlines(self):
        body = "Line1\n\n\n\n\nLine2"
        result = _clean_email_body(body)
        assert "\n\n\n" not in result
        assert "Line1" in result
        assert "Line2" in result

    def test_normal_body_preserved(self):
        body = "Hey, just wanted to check in.\nLet me know!"
        result = _clean_email_body(body)
        assert "Hey, just wanted to check in." in result
        assert "Let me know!" in result


# ── _parse_time ─────────────────────────────────────────────────────────────


class TestParseTime:
    def test_24h_format(self):
        result = _parse_time("14:30")
        assert result is not None
        assert result.hour == 14
        assert result.minute == 30

    def test_12h_pm(self):
        result = _parse_time("2pm")
        assert result is not None
        assert result.hour == 14
        assert result.minute == 0

    def test_12h_am(self):
        result = _parse_time("9am")
        assert result is not None
        assert result.hour == 9

    def test_12h_with_minutes(self):
        result = _parse_time("2:30pm")
        assert result is not None
        assert result.hour == 14
        assert result.minute == 30

    def test_12pm_is_noon(self):
        result = _parse_time("12pm")
        assert result is not None
        assert result.hour == 12

    def test_12am_is_midnight(self):
        result = _parse_time("12am")
        assert result is not None
        assert result.hour == 0

    def test_invalid_returns_none(self):
        assert _parse_time("not a time") is None
        assert _parse_time("") is None

    def test_case_insensitive(self):
        result = _parse_time("3PM")
        assert result is not None
        assert result.hour == 15

    def test_with_whitespace(self):
        result = _parse_time("  3pm  ")
        assert result is not None
        assert result.hour == 15


# ── parse_quick_event ───────────────────────────────────────────────────────


class TestParseQuickEvent:
    def test_basic_time_range(self):
        result = parse_quick_event("Meeting 2pm-3pm")
        assert result["summary"] == "Meeting"
        assert result["start"].hour == 14
        assert result["end"].hour == 15
        assert result["all_day"] is False

    def test_24h_time_range(self):
        result = parse_quick_event("Standup 09:00-09:30")
        assert result["summary"] == "Standup"
        assert result["start"].hour == 9
        assert result["start"].minute == 0
        assert result["end"].hour == 9
        assert result["end"].minute == 30

    def test_with_location(self):
        result = parse_quick_event("Lunch 12pm-1pm @ Cafe Roma")
        assert result["summary"] == "Lunch"
        assert result["location"] == "Cafe Roma"

    def test_all_day_event(self):
        result = parse_quick_event("all day: Team Offsite")
        assert result["summary"] == "Team Offsite"
        assert result["all_day"] is True

    def test_all_day_with_location(self):
        result = parse_quick_event("all day: Conference @ Convention Center")
        assert result["summary"] == "Conference"
        assert result["location"] == "Convention Center"
        assert result["all_day"] is True

    def test_no_time_falls_back(self):
        result = parse_quick_event("Quick sync")
        assert result["summary"] == "Quick sync"
        # Should default to now → now+1h
        assert result["all_day"] is False
        diff = result["end"] - result["start"]
        assert diff == timedelta(hours=1)

    def test_en_dash_separator(self):
        result = parse_quick_event("Meeting 2pm\u20133pm")
        assert result["summary"] == "Meeting"
        assert result["start"].hour == 14
        assert result["end"].hour == 15

    def test_12h_with_minutes_range(self):
        result = parse_quick_event("Call 2:30pm-3:45pm")
        assert result["start"].hour == 14
        assert result["start"].minute == 30
        assert result["end"].hour == 15
        assert result["end"].minute == 45


# ── _build_event_body ──────────────────────────────────────────────────────


class TestBuildEventBody:
    def test_all_day_event(self):
        start = datetime(2025, 6, 15)
        end = datetime(2025, 6, 16)
        body = _build_event_body("Day Off", start, end, all_day=True)
        assert body["summary"] == "Day Off"
        assert body["start"] == {"date": "2025-06-15"}
        assert body["end"] == {"date": "2025-06-16"}

    def test_timed_event(self):
        start = datetime(2025, 6, 15, 14, 0).astimezone()
        end = datetime(2025, 6, 15, 15, 0).astimezone()
        body = _build_event_body("Meeting", start, end)
        assert body["summary"] == "Meeting"
        assert "dateTime" in body["start"]
        assert "dateTime" in body["end"]

    def test_with_location(self):
        start = datetime(2025, 6, 15)
        end = datetime(2025, 6, 16)
        body = _build_event_body("Event", start, end, location="Room 5", all_day=True)
        assert body["location"] == "Room 5"

    def test_with_description(self):
        start = datetime(2025, 6, 15)
        end = datetime(2025, 6, 16)
        body = _build_event_body("Event", start, end, description="Notes here", all_day=True)
        assert body["description"] == "Notes here"

    def test_no_location_omitted(self):
        start = datetime(2025, 6, 15)
        end = datetime(2025, 6, 16)
        body = _build_event_body("Event", start, end, all_day=True)
        assert "location" not in body


# ── structured logging ─────────────────────────────────────────────────────


class _FailingGmailMessages:
    def send(self, *args: Any, **kwargs: Any) -> _FailingGmailMessages:
        return self

    def execute(self) -> None:
        raise RuntimeError("gmail send exploded")


class _FailingGmailUsers:
    def messages(self) -> _FailingGmailMessages:
        return _FailingGmailMessages()


class _FailingGmailService:
    def users(self) -> _FailingGmailUsers:
        return _FailingGmailUsers()


class TestStructuredLogging:
    def test_imsg_contacts_logs_exception(self, monkeypatch, tmp_path):
        db_path = tmp_path / "chat.db"
        db_path.write_text("")
        monkeypatch.setattr(services, "IMSG_DB", db_path)

        def boom(*args: Any, **kwargs: Any) -> None:
            raise sqlite3.OperationalError("chat db exploded")

        monkeypatch.setattr(services.sqlite3, "connect", boom)
        sink = StringIO()
        sink_id = logger.add(sink, format="{message}")
        try:
            assert services.imsg_contacts() == []
        finally:
            logger.remove(sink_id)

        log_output = sink.getvalue()
        assert "imsg_contacts" in log_output
        assert "limit=30" in log_output
        assert "chat db exploded" in log_output

    def test_gmail_send_logs_exception(self):
        contact = services.Contact(
            id="msg-1",
            name="Alice",
            source="gmail",
            reply_to="alice@example.com",
            snippet="Hello",
            thread_id="thread-1",
        )
        sink = StringIO()
        sink_id = logger.add(sink, format="{message}")
        try:
            assert services.gmail_send(_FailingGmailService(), contact, "hello there") is False
        finally:
            logger.remove(sink_id)

        log_output = sink.getvalue()
        assert "gmail_send" in log_output
        assert "reply_to='alice@example.com'" in log_output
        assert "gmail send exploded" in log_output

    def test_services_has_no_silent_exception_swallowing(self):
        services_text = Path(services.__file__).read_text()

        assert re.search(r"except.*pass", services_text) is None
        assert re.search(r"except.*return\s+\[\]", services_text) is None
        assert re.search(r"except.*return\s+False", services_text) is None


class TestSqliteConnectionManagement:
    def test_notes_list_reuses_cached_connection(self, monkeypatch, tmp_path):
        db_path = tmp_path / "NoteStore.sqlite"
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE ZICCLOUDSYNCINGOBJECT (
                Z_PK INTEGER PRIMARY KEY,
                ZTITLE1 TEXT,
                ZSNIPPET TEXT,
                ZMODIFICATIONDATE1 REAL,
                ZFOLDER INTEGER,
                ZTITLE2 TEXT,
                ZMARKEDFORDELETION INTEGER
            )
            """
        )
        cur.execute(
            """
            INSERT INTO ZICCLOUDSYNCINGOBJECT
                (Z_PK, ZTITLE1, ZSNIPPET, ZMODIFICATIONDATE1, ZFOLDER, ZTITLE2, ZMARKEDFORDELETION)
            VALUES
                (1, 'Test note', 'Snippet', 60, NULL, NULL, 0)
            """
        )
        conn.commit()
        conn.close()

        services.close_sqlite_connections()
        monkeypatch.setattr(services, "NOTES_DB", db_path)

        connect_calls = 0
        real_connect = services.sqlite3.connect

        def counting_connect(*args: Any, **kwargs: Any):
            nonlocal connect_calls
            connect_calls += 1
            return real_connect(*args, **kwargs)

        monkeypatch.setattr(services.sqlite3, "connect", counting_connect)
        try:
            first = services.notes_list()
            second = services.notes_list()
        finally:
            services.close_sqlite_connections()

        assert [note.title for note in first] == ["Test note"]
        assert [note.title for note in second] == ["Test note"]
        assert connect_calls == 1

    def test_locked_sqlite_returns_empty_and_logs_warning(self, monkeypatch, tmp_path):
        db_path = tmp_path / "NoteStore.sqlite"
        db_path.write_text("")
        monkeypatch.setattr(services, "NOTES_DB", db_path)

        class _LockedCursor:
            def execute(self, *args: Any, **kwargs: Any) -> None:
                raise sqlite3.OperationalError("database is locked")

        class _LockedConnection:
            def cursor(self) -> _LockedCursor:
                return _LockedCursor()

        monkeypatch.setattr(
            services._sqlite_connections, "get_connection", lambda path: _LockedConnection()
        )
        sink = StringIO()
        sink_id = logger.add(sink, format="{message}")
        try:
            assert services.notes_list() == []
        finally:
            logger.remove(sink_id)

        log_output = sink.getvalue()
        assert "notes_list" in log_output
        assert "database is locked" in log_output

    def test_close_sqlite_connections_clears_cache(self, monkeypatch, tmp_path):
        db_path = tmp_path / "NoteStore.sqlite"
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE ZICCLOUDSYNCINGOBJECT (
                Z_PK INTEGER PRIMARY KEY,
                ZTITLE1 TEXT,
                ZSNIPPET TEXT,
                ZMODIFICATIONDATE1 REAL,
                ZFOLDER INTEGER,
                ZTITLE2 TEXT,
                ZMARKEDFORDELETION INTEGER
            )
            """
        )
        conn.commit()
        conn.close()

        services.close_sqlite_connections()
        monkeypatch.setattr(services, "NOTES_DB", db_path)

        services.notes_list()
        assert services._sqlite_connections.cached_connection_count() == 1

        services.close_sqlite_connections()

        assert services._sqlite_connections.cached_connection_count() == 0
