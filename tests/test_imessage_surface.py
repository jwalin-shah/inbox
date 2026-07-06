"""Tests for src/imessage_surface.py — iMessage contact surface scanning."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from src.imessage_surface import (
    DEFAULT_RECENT_DAYS,
    DEFAULT_STALE_DAYS,
    SurfaceReport,
    ThreadSurface,
    _age_label,
    _build_parser,
    _chat_display_name,
    _clean_body,
    _is_noise,
    _is_phone_like,
    _markdown_cell,
    _name_resolved,
    _urgency,
    format_markdown,
)

pytestmark = pytest.mark.safe

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REF_TS = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)


def _make_surface(**kwargs) -> ThreadSurface:
    defaults = dict(
        chat_id="1",
        name="Alice",
        display_name="Alice Johnson",
        members=["alice@example.com"],
        is_group=False,
        unread=2,
        last_ts=_REF_TS - timedelta(hours=3),
        age_hours=3.0,
        age_label="3h",
        snippet="Hey, are you coming?",
        interaction_count=42,
        sent_count=20,
        received_count=22,
        active_days=10,
        name_resolved=True,
        needs_reply=True,
        urgency=5,
        evidence_thread="GET /messages/imessage/1",
        last_sender="them",
    )
    defaults.update(kwargs)
    return ThreadSurface(**defaults)


def _make_report(**kwargs) -> SurfaceReport:
    defaults = dict(
        generated_at="2026-07-01T12:00:00-07:00",
        stale_threshold_days=14,
        recent_threshold_days=7,
    )
    defaults.update(kwargs)
    return SurfaceReport(**defaults)


# ===================================================================
# _clean_body
# ===================================================================


class TestCleanBody:
    def test_returns_empty_for_none(self):
        assert _clean_body(None) == ""

    def test_returns_empty_for_empty_string(self):
        assert _clean_body("") == ""

    def test_passes_through_normal_text(self):
        assert _clean_body("Hello world") == "Hello world"

    def test_replaces_attachment_placeholder(self):
        from service_models import ATTACHMENT_PLACEHOLDER

        assert _clean_body(ATTACHMENT_PLACEHOLDER) == "(attachment)"

    def test_strips_whitespace(self):
        assert _clean_body("  hello  ") == "hello"


# ===================================================================
# _age_label
# ===================================================================


class TestAgeLabel:
    def test_under_one_hour_shows_minutes(self):
        assert _age_label(timedelta(minutes=30)) == "30m"
        assert _age_label(timedelta(minutes=59)) == "59m"

    def test_between_one_and_48_hours_shows_hours(self):
        assert _age_label(timedelta(hours=1)) == "1h"
        assert _age_label(timedelta(hours=23)) == "23h"

    def test_over_24_under_48_shows_one_day(self):
        assert _age_label(timedelta(hours=24)) == "1d"
        assert _age_label(timedelta(hours=36)) == "1d"
        assert _age_label(timedelta(hours=47)) == "1d"

    def test_over_48_hours_shows_days(self):
        assert _age_label(timedelta(days=2)) == "2d"
        assert _age_label(timedelta(days=30)) == "30d"
        assert _age_label(timedelta(days=365)) == "365d"

    def test_zero_shows_zero_minutes(self):
        assert _age_label(timedelta(seconds=0)) == "0m"


# ===================================================================
# _markdown_cell
# ===================================================================


class TestMarkdownCell:
    def test_escapes_pipe_character(self):
        assert _markdown_cell("a|b") == r"a\|b"

    def test_replaces_newline_with_space(self):
        assert _markdown_cell("line1\nline2") == "line1 line2"

    def test_replaces_carriage_return_with_space(self):
        assert _markdown_cell("col1\rcol2") == "col1 col2"

    def test_handles_multiple_special_chars(self):
        assert _markdown_cell("a|b\nc\rd|e") == r"a\|b c d\|e"

    def test_no_special_chars_passes_through(self):
        assert _markdown_cell("plain text") == "plain text"


# ===================================================================
# _is_phone_like
# ===================================================================


class TestIsPhoneLike:
    def test_empty_string_is_not_phone(self):
        assert _is_phone_like("") is False
        assert _is_phone_like("  ") is False

    def test_standard_us_phone(self):
        assert _is_phone_like("+1 (555) 123-4567") is True

    def test_e164_format(self):
        assert _is_phone_like("+14155551234") is True

    def test_plain_digits_only(self):
        assert _is_phone_like("4155551234") is True

    def test_digits_with_spaces_dashes_dots_parens(self):
        assert _is_phone_like("415-555-1234") is True
        assert _is_phone_like("(415) 555 1234") is True
        assert _is_phone_like("415.555.1234") is True

    def test_seven_digits_minimum(self):
        assert _is_phone_like("5551234") is True  # 7 digits

    def test_six_digits_is_not_phone(self):
        assert _is_phone_like("555123") is False  # only 6 digits

    def test_name_is_not_phone(self):
        assert _is_phone_like("Alice") is False
        assert _is_phone_like("John Smith") is False
        assert _is_phone_like("ABC-1234") is False  # only 4 digits

    def test_whitespace_trimmed(self):
        assert _is_phone_like("  +14155551234  ") is True


# ===================================================================
# _name_resolved
# ===================================================================


class TestNameResolved:
    def test_display_name_resolves(self):
        assert _name_resolved("+14155551234", "Alice", []) is True

    def test_empty_display_name_is_not_resolved(self):
        assert _name_resolved("+14155551234", "", []) is False
        assert _name_resolved("+14155551234", "   ", []) is False

    def test_phone_like_name_is_not_resolved(self):
        assert _name_resolved("+14155551234", "", []) is False

    def test_email_name_is_not_resolved(self):
        assert _name_resolved("alice@example.com", "", []) is False

    def test_automated_name_is_not_resolved(self):
        assert _name_resolved("google", "", []) is False
        assert _name_resolved("Amazon", "", []) is False

    def test_plain_name_resolves(self):
        assert _name_resolved("Alice", "", []) is True

    def test_all_phone_members_not_resolved(self):
        assert _name_resolved("Chat Group", "", ["+14155551234", "+14155556789"]) is False

    def test_all_email_members_not_resolved(self):
        assert _name_resolved("Chat Group", "", ["a@b.com", "c@d.com"]) is False

    def test_mixed_members_with_name_resolves(self):
        assert _name_resolved("Chat Group", "", ["Alice", "+14155551234"]) is True

    def test_empty_name_not_resolved(self):
        assert _name_resolved("", "", []) is False


# ===================================================================
# _is_noise
# ===================================================================


class TestIsNoise:
    def test_empty_body_is_noise(self):
        assert _is_noise("", "Alice") is True

    def test_attachment_only_is_noise(self):
        assert _is_noise("(attachment)", "Alice") is True

    def test_tapback_is_noise(self):
        assert _is_noise("Liked an image", "Alice") is True
        assert _is_noise("Loved a message", "Alice") is True
        assert _is_noise("Emphasized an image", "Alice") is True
        assert _is_noise("Disliked a message", "Alice") is True
        assert _is_noise("Laughed at an image", "Alice") is True
        assert _is_noise("Questioned an image", "Alice") is True

    def test_short_code_is_noise(self):
        assert _is_noise("1234", "Alice") is True
        assert _is_noise("567890", "Alice") is True

    def test_automated_sender_body_is_noise(self):
        assert _is_noise("Your verification code is 123456", "Alice") is True
        assert _is_noise("This is an automated message", "Alice") is True
        assert _is_noise("Do not reply to this message", "Alice") is True

    def test_automated_sender_name_is_noise(self):
        assert _is_noise("Hello!", "google") is True
        assert _is_noise("Hello!", "Apple") is True  # case-insensitive
        assert _is_noise("Hello!", "Chase") is True

    def test_short_code_name_is_noise(self):
        assert _is_noise("Hello!", "123456") is True

    def test_normal_message_is_not_noise(self):
        assert _is_noise("Hey, when are we meeting?", "Alice") is False

    def test_normal_body_with_automated_name_is_noise(self):
        # Name check still applies
        assert _is_noise("whatever", "Doordash") is True

    def test_body_with_attachment_placeholder_alone(self):
        from service_models import ATTACHMENT_PLACEHOLDER
        assert _is_noise(ATTACHMENT_PLACEHOLDER, "Alice") is True


# ===================================================================
# _urgency
# ===================================================================


class TestUrgency:
    def test_max_urgency(self):
        # unread=3, age <= 24h = 2, resolved = 1 → capped at 5
        assert _urgency(unread=1, age_hours=1, name_resolved=True) == 5

    def test_min_urgency(self):
        assert _urgency(unread=0, age_hours=100, name_resolved=False) == 1

    def test_urgency_capped_at_five(self):
        assert _urgency(unread=10, age_hours=0.5, name_resolved=True) == 5

    def test_unread_alone_gives_three(self):
        # unread=3, age hours>72=0, not resolved=0 → max(1, 3) = 3
        assert _urgency(unread=1, age_hours=100, name_resolved=False) == 3

    def test_age_within_24_gives_two(self):
        # no unread, age≤24=2, not resolved → max(1, 2) = 2
        assert _urgency(unread=0, age_hours=1, name_resolved=False) == 2

    def test_age_24_to_72_gives_one(self):
        # no unread, 24<age≤72=1, not resolved → max(1, 1) = 1
        assert _urgency(unread=0, age_hours=48, name_resolved=False) == 1

    def test_age_over_72_gives_nothing(self):
        # no unread, age>72=0, not resolved → max(1, 0) = 1
        assert _urgency(unread=0, age_hours=100, name_resolved=False) == 1

    def test_age_exactly_24(self):
        # no unread, age≤24=2 → max(1, 2) = 2
        assert _urgency(unread=0, age_hours=24, name_resolved=False) == 2

    def test_age_exactly_72(self):
        # no unread, age≤72=1 → max(1, 1) = 1
        assert _urgency(unread=0, age_hours=72, name_resolved=False) == 1

    def test_name_resolved_adds_one(self):
        # no unread=0, age>72=0, resolved=1 → max(1, 1) = 1
        assert _urgency(unread=0, age_hours=100, name_resolved=True) == 1

    def test_all_combinations(self):
        # unread + age24 + resolved = 3+2+1 = 6, capped to 5
        assert _urgency(unread=2, age_hours=6, name_resolved=True) == 5
        # unread + age72 + not resolved = 3+1+0 = 4
        assert _urgency(unread=2, age_hours=48, name_resolved=False) == 4
        # age24 + resolved = 0+2+1 = 3
        assert _urgency(unread=0, age_hours=12, name_resolved=True) == 3
        # unread=0, age≥72, resolved=1 → max(1,1) = 1
        assert _urgency(unread=0, age_hours=80, name_resolved=True) == 1


# ===================================================================
# _chat_display_name
# ===================================================================


class TestChatDisplayName:
    @pytest.fixture
    def book(self):
        """Mock ContactBook that resolves known IDs."""
        book = MagicMock()
        book.resolve.side_effect = lambda x: {
            "alice@example.com": "Alice",
            "bob@example.com": "Bob",
        }.get(x)
        return book

    def test_uses_display_name_when_present(self, book):
        name = _chat_display_name(
            display_name="Family Chat",
            guid="iMessage;+123",
            member_ids=["alice@example.com", "bob@example.com"],
            member_names=["Alice", "Bob"],
            book=book,
        )
        assert name == "Family Chat"

    def test_falls_back_to_group_members(self, book):
        name = _chat_display_name(
            display_name=None,
            guid="iMessage;+123",
            member_ids=["alice@example.com", "bob@example.com"],
            member_names=["Alice", "Bob"],
            book=book,
        )
        assert name == "Alice, Bob"

    def test_truncates_group_with_more_than_three_members(self, book):
        name = _chat_display_name(
            display_name=None,
            guid="iMessage;+123",
            member_ids=["a@b.com", "c@d.com", "e@f.com", "g@h.com"],
            member_names=["Alice", "Bob", "Carol", "Dave"],
            book=book,
        )
        assert name == "Alice, Bob, Carol +1"

    def test_uses_single_member_name(self, book):
        name = _chat_display_name(
            display_name=None,
            guid="iMessage;+123",
            member_ids=["alice@example.com"],
            member_names=["Alice"],
            book=book,
        )
        assert name == "Alice"

    def test_falls_back_to_contact_book_resolve(self, book):
        name = _chat_display_name(
            display_name=None,
            guid="iMessage;alice@example.com",
            member_ids=["alice@example.com"],
            member_names=[],
            book=book,
        )
        assert name == "Alice"

    def test_falls_back_to_guid_last_part(self, book):
        name = _chat_display_name(
            display_name=None,
            guid="iMessage;+15551234567",
            member_ids=["+15551234567"],
            member_names=[],
            book=book,
        )
        assert name == "+15551234567"

    def test_empty_display_name_no_members(self, book):
        name = _chat_display_name(
            display_name="",
            guid="iMessage;+15551234567",
            member_ids=["+15551234567"],
            member_names=[],
            book=book,
        )
        assert name == "+15551234567"


# ===================================================================
# ThreadSurface
# ===================================================================


class TestThreadSurface:
    def test_to_dict_includes_all_fields(self):
        ts = _REF_TS
        row = ThreadSurface(
            chat_id="42",
            name="Alice",
            display_name="Alice Johnson",
            members=["alice@example.com"],
            is_group=False,
            unread=3,
            last_ts=ts,
            age_hours=5.5,
            age_label="5h",
            snippet="Hey there",
            interaction_count=10,
            sent_count=4,
            received_count=6,
            active_days=5,
            name_resolved=True,
            needs_reply=True,
            urgency=4,
            evidence_thread="GET /messages/imessage/42",
            last_sender="them",
        )
        d = row.to_dict()
        assert d["chat_id"] == "42"
        assert d["name"] == "Alice"
        assert d["unread"] == 3
        assert d["age_hours"] == 5.5
        assert d["snippet"] == "Hey there"
        assert d["urgency"] == 4
        assert d["last_sender"] == "them"
        # last_ts is ISO format without timezone
        assert "T" in d["last_ts"]
        assert d["last_ts"].endswith(":00")

    def test_default_last_sender(self):
        row = ThreadSurface(
            chat_id="1",
            name="Bob",
            display_name="",
            members=[],
            is_group=False,
            unread=0,
            last_ts=_REF_TS,
            age_hours=1.0,
            age_label="1h",
            snippet="",
            interaction_count=1,
            sent_count=1,
            received_count=0,
            active_days=1,
            name_resolved=False,
            needs_reply=False,
            urgency=1,
            evidence_thread="GET /messages/imessage/1",
        )
        assert row.last_sender == "them"

    def test_last_sender_me(self):
        row = ThreadSurface(
            chat_id="1",
            name="Bob",
            display_name="",
            members=[],
            is_group=False,
            unread=0,
            last_ts=_REF_TS,
            age_hours=1.0,
            age_label="1h",
            snippet="",
            interaction_count=1,
            sent_count=1,
            received_count=0,
            active_days=1,
            name_resolved=False,
            needs_reply=False,
            urgency=1,
            evidence_thread="GET /messages/imessage/1",
            last_sender="Me",
        )
        assert row.last_sender == "Me"


# ===================================================================
# SurfaceReport
# ===================================================================


class TestSurfaceReport:
    def test_to_dict_with_no_rows(self):
        report = _make_report()
        d = report.to_dict()
        assert d["schema"] == "inbox.imessage_contact_surface.v0"
        assert d["generated_at"] == "2026-07-01T12:00:00-07:00"
        assert d["stale_threshold_days"] == 14
        assert d["recent_threshold_days"] == 7
        assert d["summary"] == {}
        assert d["recent_actionable_needs_reply"] == []
        assert d["stale_needs_reply"] == []
        assert d["inactive_contacts"] == []
        assert d["phone_ambiguous_needs_reply"] == []

    def test_to_dict_includes_rows(self):
        report = _make_report()
        row = _make_surface()
        report.recent_actionable_needs_reply = [row]
        report.stale_needs_reply = [_make_surface(chat_id="2", name="Bob")]
        d = report.to_dict()
        assert len(d["recent_actionable_needs_reply"]) == 1
        assert d["recent_actionable_needs_reply"][0]["name"] == "Alice"
        assert len(d["stale_needs_reply"]) == 1

    def test_to_dict_includes_excluded_noise(self):
        report = _make_report()
        report.excluded_noise = 5
        d = report.to_dict()
        assert d["excluded_noise"] == 5

    def test_default_field_values(self):
        report = SurfaceReport()
        assert report.schema == "inbox.imessage_contact_surface.v0"
        assert report.stale_threshold_days == DEFAULT_STALE_DAYS
        assert report.recent_threshold_days == DEFAULT_RECENT_DAYS
        assert report.recent_actionable_needs_reply == []
        assert report.stale_needs_reply == []
        assert report.inactive_contacts == []
        assert report.phone_ambiguous_needs_reply == []
        assert report.waiting_on_others == []
        assert report.excluded_noise == 0


# ===================================================================
# format_markdown
# ===================================================================


class TestFormatMarkdown:
    def test_empty_report(self):
        report = _make_report()
        text = format_markdown(report)
        assert "# iMessage Contact Surface" in text
        assert "## Summary" in text
        assert "Recent actionable" in text
        assert "Stale needs reply" in text

    def test_includes_generated_at(self):
        report = _make_report(generated_at="2026-07-01T12:00:00-07:00")
        text = format_markdown(report)
        assert "2026-07-01T12:00:00-07:00" in text

    def test_summary_table_has_all_tiers(self):
        report = _make_report()
        report.summary = {
            "recent_actionable_needs_reply": 3,
            "stale_needs_reply": 2,
            "phone_ambiguous_needs_reply": 1,
            "inactive_contacts": 4,
            "waiting_on_others": 1,
            "excluded_noise": 5,
        }
        text = format_markdown(report)
        assert "**3**" in text
        assert "Stale needs reply" in text
        assert "Phone / ambiguous" in text
        assert "Inactive" in text
        assert "Waiting on others" in text
        assert "Excluded noise" in text

    def test_recent_actionable_table_has_urgency(self):
        report = _make_report()
        report.recent_actionable_needs_reply = [_make_surface()]
        text = format_markdown(report)
        # Urgency column only for recent actionable
        lines = text.split("\n")
        # Find the Recent Actionable section
        in_section = False
        for line in lines:
            if "Recent Actionable" in line and "###" not in line:
                in_section = True
            if in_section and "Urgency" in line:
                assert "Unread" in line
                assert "Age" in line
                break

    def test_other_buckets_no_urgency_column(self):
        report = _make_report()
        report.stale_needs_reply = [_make_surface()]
        text = format_markdown(report)
        # Stale section should NOT have urgency column
        lines = text.split("\n")
        in_stale = False
        for line in lines:
            if "Stale Needs Reply" in line:
                in_stale = True
            if in_stale and "|" in line and "---" not in line and "Unread" in line and "Age" in line:
                assert "Urgency" not in line
                break

    def test_quick_reply_section_with_actionable(self):
        report = _make_report()
        report.recent_actionable_needs_reply = [
            _make_surface(chat_id=str(i), name=f"Person{i}") for i in range(6)
        ]
        report.stale_needs_reply = [
            _make_surface(chat_id=str(i + 10), name=f"Stale{i}") for i in range(4)
        ]
        text = format_markdown(report)
        assert "## Quick Reply" in text
        # Should include first 5 recent + first 5 stale, capped at 8
        assert "Person0" in text
        assert "Stale0" in text

    def test_markdown_cell_escaping_in_table(self):
        report = _make_report()
        report.recent_actionable_needs_reply = [
            _make_surface(name="a|b", snippet="c\nd", chat_id="1")
        ]
        text = format_markdown(report)
        # Pipe should be escaped
        assert r"a\|b" in text
        # Newline should become space
        assert "c d" in text

    def test_no_quick_reply_when_no_actionable(self):
        report = _make_report()
        text = format_markdown(report)
        assert "Quick Reply" not in text

    def test_inactive_contacts_section(self):
        report = _make_report(stale_threshold_days=14)
        report.inactive_contacts = [
            _make_surface(chat_id="99", name="Inactive Person", unread=0)
        ]
        text = format_markdown(report)
        assert "Inactive Contacts" in text
        assert "Inactive Person" in text

    def test_waiting_on_others_no_dedicated_section(self):
        # waiting_on_others appears in the summary table but gets no ## section
        report = _make_report()
        report.summary = {"waiting_on_others": 3}
        report.waiting_on_others = [_make_surface(chat_id="50", name="Waiting")]
        text = format_markdown(report)
        # Should appear in summary table
        assert "Waiting on others" in text
        # Should NOT have a dedicated ## Waiting on others section
        assert "## Waiting on others" not in text

    def test_missing_summary_keys_handled(self):
        report = _make_report()
        report.summary = {}  # empty dict, no keys
        text = format_markdown(report)
        # .get with default 0 should work
        assert "Recent actionable" in text

    def test_timezone_aware_datetime_formatting(self):
        tz = UTC  # equivalent to UTC for formatting purposes
        report = _make_report()
        row = _make_surface(last_ts=datetime(2026, 7, 1, 10, 30, tzinfo=tz))
        report.recent_actionable_needs_reply = [row]
        text = format_markdown(report)
        assert "2026-07-01 10:30" in text

    def test_phone_ambiguous_section(self):
        report = _make_report()
        report.phone_ambiguous_needs_reply = [
            _make_surface(name="+15551234567", name_resolved=False, chat_id="5")
        ]
        text = format_markdown(report)
        assert "Phone / Ambiguous" in text
        assert "+15551234567" in text


# ===================================================================
# _build_parser
# ===================================================================


class TestBuildParser:
    def test_default_command_is_scan(self):
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.command == "scan"

    def test_scan_subcommand(self):
        parser = _build_parser()
        args = parser.parse_args(["scan", "--json"])
        assert args.command == "scan"
        assert args.json is True
        assert args.limit == 500

    def test_scan_with_custom_params(self):
        parser = _build_parser()
        args = parser.parse_args(
            ["scan", "--limit", "100", "--stale-days", "30", "--recent-days", "10"]
        )
        assert args.limit == 100
        assert args.stale_days == 30
        assert args.recent_days == 10

    def test_scan_markdown_output_path(self):
        parser = _build_parser()
        args = parser.parse_args(["scan", "--markdown", "/tmp/report.md"])
        assert args.markdown == "/tmp/report.md"

    def test_scan_now_override(self):
        parser = _build_parser()
        args = parser.parse_args(["scan", "--now", "2026-01-01T00:00:00Z"])
        assert args.now == "2026-01-01T00:00:00Z"

    def test_thread_subcommand(self):
        parser = _build_parser()
        args = parser.parse_args(["thread", "42"])
        assert args.command == "thread"
        assert args.chat_id == "42"
        assert args.limit == 20

    def test_thread_with_custom_limit(self):
        parser = _build_parser()
        args = parser.parse_args(["thread", "42", "--limit", "50"])
        assert args.chat_id == "42"
        assert args.limit == 50

    def test_reply_subcommand(self):
        parser = _build_parser()
        args = parser.parse_args(["reply", "42", "Hello there"])
        assert args.command == "reply"
        assert args.chat_id == "42"
        assert args.text == "Hello there"
        assert args.confirm is False

    def test_reply_with_confirm(self):
        parser = _build_parser()
        args = parser.parse_args(["reply", "42", "Hello", "--confirm"])
        assert args.confirm is True
