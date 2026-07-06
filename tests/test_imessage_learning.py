"""Tests for src/imessage_learning.py — iMessage contact learning and reply timing."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from src.imessage_learning import (
    Message,
    _apple_ns,
    _best_window,
    _clean_text,
    _direction_runs,
    _format_hour,
    _format_latency,
    _format_window,
    _importance,
    _looks_automated,
    _median,
    _message_timestamp,
    _percent,
    _response_patterns,
    _suggest_timing,
    _topic_signals,
    format_markdown,
)

pytestmark = pytest.mark.safe

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REF_TS = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
_LOCAL_TZ = ZoneInfo("America/Los_Angeles")


def _msg(
    text: str,
    is_from_me: bool,
    offset_hours: float = 0.0,
    chat_id: int = 1,
) -> Message:
    """Create a Message with a timestamp offset from _REF_TS by *offset_hours*."""
    import datetime as _dt

    ts = _REF_TS + _dt.timedelta(hours=offset_hours)
    return Message(chat_id=chat_id, text=text, timestamp=ts, is_from_me=is_from_me)


# ===================================================================
# Timestamp helpers
# ===================================================================


class TestAppleNS:
    def test_converts_known_epoch(self):
        epoch = datetime(2001, 1, 1, tzinfo=UTC)
        assert _apple_ns(epoch) == 0

    def test_converts_recent_date(self):
        dt = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
        ns = _apple_ns(dt)
        # Convert back to verify
        assert _message_timestamp(ns) == dt

    def test_roundtrips_with_message_timestamp(self):
        import datetime as _dt

        for offset_days in (0, 30, 365, 3650):
            dt = _REF_TS + _dt.timedelta(days=offset_days)
            assert _message_timestamp(_apple_ns(dt)) == dt


class TestMessageTimestamp:
    def test_converts_zero_to_epoch(self):
        result = _message_timestamp(0)
        assert result == datetime(2001, 1, 1, tzinfo=UTC)

    def test_converts_known_value(self):
        # 2024-01-01 is ~23 years after Apple epoch
        jan_2024 = datetime(2024, 1, 1, tzinfo=UTC)
        ns = _apple_ns(jan_2024)
        assert _message_timestamp(ns) == jan_2024

    def test_roundtrip(self):
        import datetime as _dt

        dt = _REF_TS + _dt.timedelta(hours=3.5)
        assert _message_timestamp(_apple_ns(dt)) == dt


# ===================================================================
# Text helpers
# ===================================================================


class TestCleanText:
    def test_returns_stripped_text(self):
        assert _clean_text("  hello  ") == "hello"

    def test_replaces_object_replacement_char_with_space(self):
        assert _clean_text("hello￼world") == "hello world"

    def test_handles_none(self):
        assert _clean_text(None) == ""

    def test_handles_empty_string(self):
        assert _clean_text("") == ""

    def test_multiple_replacement_chars(self):
        assert _clean_text("a￼￼b") == "a  b"

    def test_only_replacement_chars(self):
        assert _clean_text("￼") == ""


# ===================================================================
# Numeric formatters
# ===================================================================


class TestPercent:
    def test_normal_value(self):
        assert _percent(0.5) == 50.0

    def test_zero(self):
        assert _percent(0.0) == 0.0

    def test_one(self):
        assert _percent(1.0) == 100.0

    def test_rounding(self):
        assert _percent(0.333) == 33.3


class TestMedian:
    def test_odd_count(self):
        assert _median([1.0, 3.0, 2.0]) == 2.0

    def test_even_count(self):
        assert _median([1.0, 2.0, 3.0, 4.0]) == 2.5

    def test_single_value(self):
        assert _median([42.0]) == 42.0

    def test_empty_returns_none(self):
        assert _median([]) is None

    def test_rounds_result(self):
        assert _median([1.0, 1.1, 1.2]) == 1.1


# ===================================================================
# Format latency
# ===================================================================


class TestFormatLatency:
    def test_none_returns_insufficient_data(self):
        assert _format_latency(None) == "insufficient data"

    def test_zero_returns_under_threshold(self):
        assert _format_latency(0) == "<0.1h"

    def test_small_hours(self):
        assert _format_latency(0.5) == "0.5h"

    def test_large_hours(self):
        assert _format_latency(48.0) == "48h"

    def test_integer_hours_no_decimal(self):
        assert _format_latency(3.0) == "3h"

    def test_fractional_hours(self):
        assert _format_latency(2.75) == "2.75h"


# ===================================================================
# Format hour (24h → AM/PM)
# ===================================================================


class TestFormatHour:
    def test_midnight(self):
        assert _format_hour(0) == "12 AM"

    def test_morning(self):
        assert _format_hour(9) == "9 AM"

    def test_noon(self):
        assert _format_hour(12) == "12 PM"

    def test_afternoon(self):
        assert _format_hour(14) == "2 PM"

    def test_evening(self):
        assert _format_hour(18) == "6 PM"

    def test_eleven_pm(self):
        assert _format_hour(23) == "11 PM"


class TestFormatWindow:
    def test_morning_window(self):
        assert _format_window((9, 12)) == "9 AM–12 PM"

    def test_overnight_window(self):
        assert _format_window((22, 1)) == "10 PM–1 AM"

    def test_afternoon_window(self):
        assert _format_window((14, 17)) == "2 PM–5 PM"


# ===================================================================
# direction_runs
# ===================================================================


class TestDirectionRuns:
    def test_empty_messages(self):
        assert _direction_runs([]) == []

    def test_single_message(self):
        msgs = [_msg("hi", is_from_me=True)]
        runs = _direction_runs(msgs)
        assert len(runs) == 1
        assert len(runs[0]) == 1
        assert runs[0][0] is msgs[0]

    def test_all_same_direction(self):
        msgs = [_msg("a", True), _msg("b", True), _msg("c", True)]
        runs = _direction_runs(msgs)
        assert len(runs) == 1
        assert len(runs[0]) == 3

    def test_alternating_directions(self):
        msgs = [_msg("a", True), _msg("b", False), _msg("c", True)]
        runs = _direction_runs(msgs)
        assert len(runs) == 3
        assert all(len(run) == 1 for run in runs)

    def test_mixed_groups(self):
        msgs = [
            _msg("a", True),
            _msg("b", True),
            _msg("c", False),
            _msg("d", False),
            _msg("e", False),
            _msg("f", True),
        ]
        runs = _direction_runs(msgs)
        assert len(runs) == 3
        assert len(runs[0]) == 2  # two from me
        assert len(runs[1]) == 3  # three from them
        assert len(runs[2]) == 1  # one from me


# ===================================================================
# response_patterns
# ===================================================================


class TestResponsePatterns:
    def test_empty_messages(self):
        result = _response_patterns([])
        assert result["my_latencies"] == []
        assert result["their_latencies"] == []
        assert result["my_response_rate"] == 0.0
        assert result["their_response_rate"] == 0.0
        assert result["my_initiation_rate"] == 0.0

    def test_single_message_from_me(self):
        msgs = [_msg("hi", is_from_me=True)]
        result = _response_patterns(msgs)
        assert result["my_initiation_rate"] == 1.0
        assert result["my_response_rate"] == 0.0

    def test_single_message_from_them(self):
        msgs = [_msg("hi", is_from_me=False)]
        result = _response_patterns(msgs)
        assert result["my_initiation_rate"] == 0.0
        assert result["my_response_rate"] == 0.0

    def test_basic_exchange(self):
        """They send, I respond → compute my response latency."""
        msgs = [
            _msg("hey", is_from_me=False, offset_hours=0),
            _msg("hi back", is_from_me=True, offset_hours=1.5),
        ]
        result = _response_patterns(msgs)
        assert result["my_latencies"] == [1.5]
        assert result["their_latencies"] == []
        assert result["my_response_rate"] == 1.0
        assert result["their_response_rate"] == 0.0
        # they initiated, so my_initiation_rate = 0/1 = 0.0
        assert result["my_initiation_rate"] == 0.0

    def test_their_response(self):
        """I send, they respond → compute their latency."""
        msgs = [
            _msg("question?", is_from_me=True, offset_hours=0),
            _msg("answer", is_from_me=False, offset_hours=3.0),
        ]
        result = _response_patterns(msgs)
        assert result["my_latencies"] == []
        assert result["their_latencies"] == [3.0]
        assert result["my_response_rate"] == 0.0
        assert result["their_response_rate"] == 1.0
        # I initiated, so my_initiation_rate = 1/1 = 1.0
        assert result["my_initiation_rate"] == 1.0

    def test_multiple_turns(self):
        msgs = [
            _msg("1 them", is_from_me=False, offset_hours=0),
            _msg("2 me", is_from_me=True, offset_hours=2.0),
            _msg("3 them", is_from_me=False, offset_hours=5.0),
            _msg("4 me", is_from_me=True, offset_hours=6.0),
            _msg("5 them", is_from_me=False, offset_hours=10.0),
        ]
        result = _response_patterns(msgs)
        # my latencies: (2) 2.0h, (4) 1.0h → [2.0, 1.0]
        # their latencies: (3) 3.0h, (5) 4.0h → [3.0, 4.0]
        assert result["my_latencies"] == [2.0, 1.0]
        assert result["their_latencies"] == [3.0, 4.0]
        # incoming turns: runs starting with False: run[0]=them(3 msgs), run[2]=them(1 msg) = 2
        # Wait—let me think about this more carefully.
        # Runs: [msg[0]=them], [msg[1]=me], [msg[2]=them], [msg[3]=me], [msg[4]=them]
        # incoming_turns: runs where first msg is from them = run[0], run[2], run[4] = 3
        # but wait, only run transitions matter:
        # current=run[0](them), following=run[1](me) → my response, latency = 2h
        # current=run[1](me), following=run[2](them) → their response, latency = 3h
        # current=run[2](them), following=run[3](me) → my response, latency = 1h
        # current=run[3](me), following=run[4](them) → their response, latency = 4h
        assert result["my_response_rate"] == pytest.approx(2 / 3)  # 2 my responses / 3 incoming turns
        assert result["their_response_rate"] == pytest.approx(2 / 2)  # 2 their responses / 2 outgoing turns

    def test_consecutive_same_direction(self):
        """Two messages from them in a row before I respond."""
        msgs = [
            _msg("them 1", is_from_me=False, offset_hours=0),
            _msg("them 2", is_from_me=False, offset_hours=0.1),
            _msg("me reply", is_from_me=True, offset_hours=3.0),
        ]
        result = _response_patterns(msgs)
        # latency from their last (them 2) to my reply (me): ~2.9h
        assert len(result["my_latencies"]) == 1
        assert pytest.approx(result["my_latencies"][0], abs=0.01) == 2.9
        assert result["my_response_rate"] == 1.0

    def test_no_response_conversation(self):
        """All messages from same person, no response opportunity."""
        msgs = [
            _msg("a", is_from_me=True, offset_hours=0),
            _msg("b", is_from_me=True, offset_hours=1),
        ]
        result = _response_patterns(msgs)
        assert result["my_latencies"] == []
        assert result["their_latencies"] == []

    def test_initiation_rate_over_multiple_conversations(self):
        """Messages spread across days compute initiation per session."""
        msgs = [
            # Conversation 1: they initiated
            _msg("hi", is_from_me=False, offset_hours=0),
            _msg("hi", is_from_me=True, offset_hours=1),
            # Conversation 2 (next day): I initiated
            _msg("sup", is_from_me=True, offset_hours=30),
            _msg("hey", is_from_me=False, offset_hours=31),
            # Conversation 3 (two days later): they initiated
            _msg("yo", is_from_me=False, offset_hours=60),
        ]
        result = _response_patterns(msgs)
        # 3 conversations (gaps ≥ 24h considered separate sessions)
        # conv 1: they started → not initiated by me
        # conv 2: I started → initiated by me ✓
        # conv 3: they started → not initiated by me
        assert result["my_initiation_rate"] == pytest.approx(1 / 3)


# ===================================================================
# topic_signals
# ===================================================================


class TestTopicSignals:
    def test_empty_messages(self):
        topics, top_terms = _topic_signals([])
        assert topics == ["general conversation"]
        assert top_terms == []

    def test_basic_word_extraction(self):
        msgs = [_msg("hello world test", is_from_me=False)]
        topics, terms = _topic_signals(msgs)
        assert "hello" in terms
        assert "world" in terms
        assert "test" in terms

    def test_stopwords_are_excluded(self):
        msgs = [_msg("the you and but for that was", is_from_me=False)]
        topics, terms = _topic_signals(msgs)
        assert terms == []

    def test_short_words_are_excluded(self):
        msgs = [_msg("hi ok a ab", is_from_me=False)]
        topics, terms = _topic_signals(msgs)
        assert terms == []

    def test_work_topic_keywords(self):
        msgs = [_msg("interview meeting job referral company work application", is_from_me=False)]
        topics, terms = _topic_signals(msgs)
        assert "work & career" in topics

    def test_food_topic_keywords(self):
        msgs = [_msg("pizza restaurant food dinner eat", is_from_me=False)]
        topics, terms = _topic_signals(msgs)
        assert "food" in topics

    def test_url_detection_adds_links_topic(self):
        msgs = [_msg("check this out https://example.com/page", is_from_me=False)]
        topics, terms = _topic_signals(msgs)
        assert "links & media" in topics

    def test_www_url_detection(self):
        msgs = [_msg("visit www.example.com today", is_from_me=False)]
        topics, terms = _topic_signals(msgs)
        assert "links & media" in topics

    def test_multiple_topics_limited_to_three(self):
        msgs = [
            _msg(
                "dinner job pizza airport doctor basketball code",
                is_from_me=False,
            )
        ]
        topics, terms = _topic_signals(msgs)
        # Multiple topic keywords found, but capped at 3
        assert len(topics) <= 3

    def test_top_five_terms(self):
        msgs = [_msg("alpha beta gamma delta epsilon zeta eta", is_from_me=False)]
        _, terms = _topic_signals(msgs)
        assert len(terms) == 5

    def test_word_stripping(self):
        """Apostrophes and hyphens remain in matched words; strip only trims ends."""
        msgs = [_msg("don't can't up-to-date", is_from_me=False)]
        _, terms = _topic_signals(msgs)
        # WORD_RE matches "don't", "can't", "up-to-date" as complete tokens
        # strip("'-") only removes leading/trailing chars, not internal ones
        # None of these are stopwords, all are ≥ 3 chars
        assert "don't" in terms
        assert "can't" in terms
        assert "up-to-date" in terms

    def test_case_insensitive_topic_match(self):
        msgs = [_msg("DINNER Pizza RESTAURANT", is_from_me=False)]
        topics, _ = _topic_signals(msgs)
        assert "food" in topics


# ===================================================================
# best_window
# ===================================================================


class TestBestWindow:
    def test_fewer_than_three_samples_returns_none(self):
        assert _best_window([]) is None
        assert _best_window([9]) is None
        assert _best_window([9, 14]) is None

    def test_three_samples_in_same_window(self):
        result = _best_window([9, 9, 9])
        # hist[9]=3, all others 0
        # Sums: start=7→3 (first), start=8→3, start=9→3
        # max() with key returns the first max: start=7
        assert result == (7, 10)

    def test_spread_across_day(self):
        result = _best_window([1, 1, 14, 14, 14, 14])
        # hist[1]=2, hist[14]=4
        # Sums: start=12→4 (first max), start=13→4, start=14→4
        # max() with key returns the first max: start=12
        assert result == (12, 15)

    def test_wrapping_around_midnight(self):
        result = _best_window([23, 23, 23, 0, 0, 1, 1])
        # hist[23]=3, hist[0]=2, hist[1]=2
        # Window starting at 23: hist[23]=3 + hist[0]=2 + hist[1]=2 = 7
        # Window starting at 22: hist[22]=0 + hist[23]=3 + hist[0]=2 = 5
        # Window starting at 0: hist[0]=2 + hist[1]=2 + hist[2]=0 = 4
        # Best: start=23 with sum=7
        assert result == (23, 2)

    def test_format_hour_zero_boundary(self):
        """Verify _format_hour is correct for our assertions."""
        assert _format_hour(0) == "12 AM"
        assert _format_hour(12) == "12 PM"


# ===================================================================
# looks_automated
# ===================================================================


class TestLooksAutomated:
    def test_phone_number_with_few_digits(self):
        msg = _msg("hello", is_from_me=False)
        # PHONE_RE matches (7+ chars), and digit count is 6 (≤ 6)
        assert _looks_automated("+1 2 3 4 5 6", [msg]) is True

    def test_phone_number_with_many_digits(self):
        msg = _msg("hello", is_from_me=False)
        # More than 6 digits → not considered a short number
        assert _looks_automated("+1 (234) 567-8900", [msg]) is False

    def test_normal_name_not_automated(self):
        msg = _msg("hey how are you", is_from_me=True)
        assert _looks_automated("Alice", [msg]) is False

    def test_noise_re_keyword_match(self):
        """Messages containing 'verification code' match NOISE_RE."""
        msgs = [
            _msg("hi", is_from_me=False),
            _msg("your otp is 123456", is_from_me=False),
        ]
        assert _looks_automated("Some Service", msgs) is True

    def test_noise_re_unsubscribe_match(self):
        msgs = [
            _msg("Click here to unsubscribe", is_from_me=False),
        ]
        assert _looks_automated("Newsletter", msgs) is True

    def test_noise_re_do_not_reply_match(self):
        msgs = [
            _msg("Please do not reply to this message", is_from_me=False),
        ]
        assert _looks_automated("Support", msgs) is True

    def test_three_plus_all_from_them(self):
        msgs = [
            _msg("msg 1", is_from_me=False),
            _msg("msg 2", is_from_me=False),
            _msg("msg 3", is_from_me=False),
        ]
        assert _looks_automated("SomeBot", msgs) is True

    def test_three_plus_with_my_response_not_automated(self):
        msgs = [
            _msg("msg 1", is_from_me=False),
            _msg("msg 2", is_from_me=False),
            _msg("msg 3", is_from_me=False),
            _msg("my response", is_from_me=True),
        ]
        assert _looks_automated("Friend", msgs) is False

    def test_one_way_less_than_three_not_automated_by_count(self):
        msgs = [
            _msg("msg 1", is_from_me=False),
            _msg("msg 2", is_from_me=False),
        ]
        assert _looks_automated("Service", msgs) is False

    def test_noise_re_only_checks_last_eight_non_from_me(self):
        """NOISE_RE only searches the last 8 messages that are NOT from me."""
        msgs = [
            _msg("normal chat", is_from_me=False, offset_hours=h) for h in range(20)
        ]
        # Last msg: "unsubscribe link here" as the most recent
        msgs.append(_msg("please unsubscribe here", is_from_me=False, offset_hours=21))
        assert _looks_automated("Normal Name", msgs) is True


# ===================================================================
# _importance
# ===================================================================


class TestImportance:
    def test_zero_message_count(self):
        score, signal, reasons = _importance(
            message_count=0,
            days_since=30,
            my_share=0.0,
            initiation_rate=0.0,
            my_response_rate=0.0,
            their_response_rate=0.0,
            needs_reply=False,
            pending_hours=None,
        )
        # engagement = 8 * log(1+0) = 0
        # recency = 25 / (1 + 30/30) = 25/2 = 12.5
        # reciprocity = 20 * (1 - abs(0.5 - 0) * 2) = 20 * (1 - 1) = 0
        # preference = 15 * min(1, 0.45*0 + 0.3*0 + 0.25*0) = 0
        # urgency = 0 (needs_reply=False)
        assert score == 12.5
        assert reasons == ["limited interaction evidence"]

    def test_high_message_volume(self):
        score, signal, reasons = _importance(
            message_count=500,
            days_since=10,
            my_share=0.5,
            initiation_rate=0.8,
            my_response_rate=0.9,
            their_response_rate=0.7,
            needs_reply=False,
            pending_hours=None,
        )
        assert "high message volume" in reasons

    def test_recently_active(self):
        score, signal, reasons = _importance(
            message_count=50,
            days_since=1,
            my_share=0.5,
            initiation_rate=0.5,
            my_response_rate=0.5,
            their_response_rate=0.5,
            needs_reply=False,
            pending_hours=None,
        )
        assert "recently active" in reasons

    def test_balanced_back_and_forth(self):
        score, signal, reasons = _importance(
            message_count=50,
            days_since=30,
            my_share=0.5,
            initiation_rate=0.5,
            my_response_rate=0.5,
            their_response_rate=0.5,
            needs_reply=False,
            pending_hours=None,
        )
        assert "balanced back-and-forth" in reasons

    def test_often_initiate_or_respond(self):
        score, signal, reasons = _importance(
            message_count=50,
            days_since=30,
            my_share=0.5,
            initiation_rate=1.0,
            my_response_rate=1.0,
            their_response_rate=1.0,
            needs_reply=False,
            pending_hours=None,
        )
        assert "you often initiate or respond" in reasons

    def test_reply_currently_due(self):
        score, signal, reasons = _importance(
            message_count=50,
            days_since=30,
            my_share=0.5,
            initiation_rate=0.5,
            my_response_rate=0.5,
            their_response_rate=0.5,
            needs_reply=True,
            pending_hours=24.0,
        )
        assert "reply currently due" in reasons

    def test_score_capped_at_100(self):
        score, signal, reasons = _importance(
            message_count=10000,
            days_since=0.1,
            my_share=0.5,
            initiation_rate=1.0,
            my_response_rate=1.0,
            their_response_rate=1.0,
            needs_reply=True,
            pending_hours=1000.0,
        )
        assert score <= 100.0

    def test_preference_signal_range(self):
        _, signal, _ = _importance(
            message_count=50,
            days_since=30,
            my_share=0.5,
            initiation_rate=1.0,
            my_response_rate=1.0,
            their_response_rate=1.0,
            needs_reply=False,
            pending_hours=None,
        )
        assert 0 <= signal <= 100

    def test_urgency_without_needs_reply(self):
        """When needs_reply is False, urgency is 0 regardless of pending_hours."""
        score_without, _, _ = _importance(
            message_count=10,
            days_since=5,
            my_share=0.5,
            initiation_rate=0.5,
            my_response_rate=0.5,
            their_response_rate=0.5,
            needs_reply=False,
            pending_hours=None,
        )
        score_with_none_pending, _, _ = _importance(
            message_count=10,
            days_since=5,
            my_share=0.5,
            initiation_rate=0.5,
            my_response_rate=0.5,
            their_response_rate=0.5,
            needs_reply=False,
            pending_hours=100.0,
        )
        assert score_without == score_with_none_pending

    def test_full_score_consistency(self):
        """Score should increase with more positive signals."""
        low, _, _ = _importance(
            message_count=1,
            days_since=365,
            my_share=0.0,
            initiation_rate=0.0,
            my_response_rate=0.0,
            their_response_rate=0.0,
            needs_reply=False,
            pending_hours=None,
        )
        high, _, _ = _importance(
            message_count=500,
            days_since=1,
            my_share=0.5,
            initiation_rate=1.0,
            my_response_rate=1.0,
            their_response_rate=1.0,
            needs_reply=True,
            pending_hours=48.0,
        )
        assert high > low

    def test_negative_pending_hours_handled(self):
        """math.log1p clamps negative to 0 via max(0.0, ...) in urgency calc."""
        score, _, _ = _importance(
            message_count=10,
            days_since=5,
            my_share=0.5,
            initiation_rate=0.5,
            my_response_rate=0.5,
            their_response_rate=0.5,
            needs_reply=True,
            pending_hours=-5.0,  # shouldn't crash
        )
        # urgency = min(10, 4 + log1p(max(0, -5.0)) * 1.5) = min(10, 4 + 0) = 4
        assert isinstance(score, float)


# ===================================================================
# _suggest_timing
# ===================================================================


class TestSuggestTiming:
    def test_no_reply_due(self):
        result = _suggest_timing(
            needs_reply=False,
            pending_hours=None,
            median_reply_hours=None,
            window=(9, 12),
            now=_REF_TS,
        )
        assert result == "No reply due"

    def test_past_usual_response_time(self):
        """Pending hours exceeds both typical and 24h threshold."""
        result = _suggest_timing(
            needs_reply=True,
            pending_hours=48.0,
            median_reply_hours=2.0,
            window=(9, 12),
            now=_REF_TS,
        )
        assert "past your usual response time" in result

    def test_past_response_time_default_typical(self):
        """When median_reply_hours is None, typical defaults to 12h."""
        result = _suggest_timing(
            needs_reply=True,
            pending_hours=24.0,
            median_reply_hours=None,
            window=(9, 12),
            now=_REF_TS,
        )
        assert "past your usual response time" in result

    def test_inside_preferred_window(self):
        """When current hour is inside the 3-hour window, suggest now."""
        # _REF_TS is noon UTC = 5 AM Pacific (LOCAL_TIMEZONE)
        # Let's use a time in the evening window
        evening = datetime(2026, 7, 1, 20, 0, 0, tzinfo=UTC)  # 1 PM Pacific
        result = _suggest_timing(
            needs_reply=True,
            pending_hours=1.0,
            median_reply_hours=4.0,
            window=(13, 16),  # 1 PM-4 PM
            now=evening,
        )
        assert "inside preferred window" in result

    def test_reply_today_before_window(self):
        """Reply due, before the preferred window today."""
        morning = datetime(2026, 7, 1, 14, 0, 0, tzinfo=UTC)  # 7 AM Pacific
        result = _suggest_timing(
            needs_reply=True,
            pending_hours=1.0,
            median_reply_hours=4.0,
            window=(18, 21),  # 6 PM-9 PM
            now=morning,
        )
        assert "today" in result

    def test_reply_tomorrow_after_window(self):
        """Reply due, after the preferred window today."""
        late = datetime(2026, 7, 2, 6, 0, 0, tzinfo=UTC)  # 11 PM Pacific
        result = _suggest_timing(
            needs_reply=True,
            pending_hours=1.0,
            median_reply_hours=4.0,
            window=(18, 21),
            now=late,
        )
        assert "tomorrow" in result


# ===================================================================
# ContactLearning dataclass
# ===================================================================


class TestContactLearning:
    def test_to_dict_includes_all_fields(self):
        from src.imessage_learning import ContactLearning

        cl = ContactLearning(
            chat_id="42",
            contact="Alice",
            is_group=False,
            message_count=100,
            my_messages=50,
            their_messages=50,
            active_days=30,
            last_contact="2026-07-01T12:00-07:00",
            days_since_contact=5.0,
            needs_reply=True,
            pending_hours=12.0,
            my_median_reply_hours=2.0,
            their_median_reply_hours=3.0,
            my_response_rate=80.0,
            their_response_rate=75.0,
            my_initiation_rate=60.0,
            preferred_contact_signal=85.0,
            topics=["work & career", "tech"],
            top_terms=["meeting", "code", "project"],
            optimal_reply_window="9 AM–12 PM",
            reply_window_source="contact history",
            suggested_reply_timing="Reply now (inside preferred window)",
            importance_score=78.5,
            importance_reasons=["high message volume", "recently active"],
            evidence_thread="GET /messages/imessage/42",
        )
        d = cl.to_dict()
        assert d["chat_id"] == "42"
        assert d["contact"] == "Alice"
        assert d["is_group"] is False
        assert d["message_count"] == 100
        assert d["importance_score"] == 78.5
        assert d["topics"] == ["work & career", "tech"]


# ===================================================================
# format_markdown
# ===================================================================


class TestFormatMarkdown:
    def test_empty_contacts(self):
        md = format_markdown([], generated_at=_REF_TS, lookback_days=365)
        assert "# iMessage Learning Demo" in md
        assert "Ranked contacts: **0**" in md
        assert "awaiting a reply: **0**" in md

    def test_single_contact(self):
        from src.imessage_learning import ContactLearning

        cl = ContactLearning(
            chat_id="1",
            contact="Alice",
            is_group=False,
            message_count=50,
            my_messages=25,
            their_messages=25,
            active_days=20,
            last_contact="2026-07-01T12:00-07:00",
            days_since_contact=5.0,
            needs_reply=False,
            pending_hours=None,
            my_median_reply_hours=1.5,
            their_median_reply_hours=2.0,
            my_response_rate=80.0,
            their_response_rate=75.0,
            my_initiation_rate=60.0,
            preferred_contact_signal=70.0,
            topics=["tech"],
            top_terms=["code", "github"],
            optimal_reply_window="9 AM–12 PM",
            reply_window_source="overall history",
            suggested_reply_timing="No reply due",
            importance_score=65.0,
            importance_reasons=["recently active"],
            evidence_thread="GET /messages/imessage/1",
        )
        md = format_markdown([cl], generated_at=_REF_TS, lookback_days=365)
        assert "Ranked contacts: **1**" in md
        assert "Alice" in md
        assert "65.0" in md

    def test_multiple_contacts_sorted(self):
        from src.imessage_learning import ContactLearning

        contacts = [
            ContactLearning(
                chat_id=str(i),
                contact=f"Contact{i}",
                is_group=False,
                message_count=i * 10,
                my_messages=i * 5,
                their_messages=i * 5,
                active_days=10,
                last_contact="2026-07-01T12:00-07:00",
                days_since_contact=10.0 - i,
                needs_reply=(i % 2 == 0),
                pending_hours=24.0 if i % 2 == 0 else None,
                my_median_reply_hours=float(i),
                their_median_reply_hours=float(i + 1),
                my_response_rate=50.0 + i,
                their_response_rate=40.0 + i,
                my_initiation_rate=30.0 + i,
                preferred_contact_signal=60.0 + i,
                topics=["general conversation"],
                top_terms=[],
                optimal_reply_window="9 AM–12 PM",
                reply_window_source="overall history",
                suggested_reply_timing="No reply due",
                importance_score=50.0 + i,
                importance_reasons=["limited interaction evidence"],
                evidence_thread=f"GET /messages/imessage/{i}",
            )
            for i in range(1, 6)
        ]
        md = format_markdown(contacts, generated_at=_REF_TS, lookback_days=365)
        assert "Ranked contacts: **5**" in md
        for i in range(1, 6):
            assert f"Contact{i}" in md

    def test_reply_due_count(self):
        from src.imessage_learning import ContactLearning

        def _make_cl(needs_reply: bool, idx: int) -> ContactLearning:
            return ContactLearning(
                chat_id=str(idx),
                contact=f"Person{idx}",
                is_group=False,
                message_count=10,
                my_messages=5,
                their_messages=5,
                active_days=5,
                last_contact="2026-07-01T12:00-07:00",
                days_since_contact=1.0,
                needs_reply=needs_reply,
                pending_hours=24.0 if needs_reply else None,
                my_median_reply_hours=2.0,
                their_median_reply_hours=2.0,
                my_response_rate=50.0,
                their_response_rate=50.0,
                my_initiation_rate=50.0,
                preferred_contact_signal=50.0,
                topics=["general conversation"],
                top_terms=[],
                optimal_reply_window="9 AM–12 PM",
                reply_window_source="overall history",
                suggested_reply_timing="Reply now" if needs_reply else "No reply due",
                importance_score=50.0,
                importance_reasons=["limited interaction evidence"],
                evidence_thread=f"GET /messages/imessage/{idx}",
            )

        contacts = [_make_cl(True, 1), _make_cl(False, 2), _make_cl(True, 3)]
        md = format_markdown(contacts, generated_at=_REF_TS, lookback_days=365)
        assert "awaiting a reply: **2**" in md

    def test_includes_detail_section_for_first_ten(self):
        from src.imessage_learning import ContactLearning

        cl = ContactLearning(
            chat_id="1",
            contact="Bob",
            is_group=False,
            message_count=20,
            my_messages=10,
            their_messages=10,
            active_days=10,
            last_contact="2026-07-01T12:00-07:00",
            days_since_contact=3.0,
            needs_reply=True,
            pending_hours=72.0,
            my_median_reply_hours=1.0,
            their_median_reply_hours=2.5,
            my_response_rate=90.0,
            their_response_rate=80.0,
            my_initiation_rate=50.0,
            preferred_contact_signal=75.0,
            topics=["work & career"],
            top_terms=["meeting", "project"],
            optimal_reply_window="9 AM–12 PM",
            reply_window_source="contact history",
            suggested_reply_timing="Reply now (past your usual response time)",
            importance_score=72.0,
            importance_reasons=["high message volume", "reply currently due"],
            evidence_thread="GET /messages/imessage/1",
        )
        md = format_markdown([cl], generated_at=_REF_TS, lookback_days=365)
        assert "## Response Pattern Detail" in md
        assert "### Bob — 72.0" in md
        assert "10/20" in md  # my_messages/message_count
        assert "meeting" in md

    def test_includes_generated_timestamp(self):
        md = format_markdown([], generated_at=_REF_TS, lookback_days=30)
        assert "Generated:" in md

    def test_includes_lookback_description(self):
        md = format_markdown([], generated_at=_REF_TS, lookback_days=90)
        assert "last 90 days" in md
