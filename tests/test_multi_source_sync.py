"""Tests for src/multi_source_sync.py — unified contact profile builder."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.contact_relationship_sync import ChannelStats, ContactRelationship
from src.imessage_learning import ContactLearning
from src.multi_source_sync import (
    CommunicationPreferences,
    InteractionHistory,
    UnifiedContactProfile,
    _history,
    _is_person,
    _iso,
    _learning_by_name,
    _name_key,
    _payload,
    _preferences,
    _safe_cell,
    render_markdown,
)

pytestmark = pytest.mark.safe

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _contact(
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


def _stats(
    interactions: int = 0,
    sent: int = 0,
    received: int = 0,
    first_at: datetime | None = None,
    last_at: datetime | None = None,
    contexts: set[str] | None = None,
) -> ChannelStats:
    stats = ChannelStats(
        interactions=interactions,
        sent=sent,
        received=received,
    )
    stats.first_at = first_at
    stats.last_at = last_at
    stats.contexts = contexts or set()
    return stats


def _learning(**overrides: object) -> ContactLearning:
    """Minimal ContactLearning with defaults suitable for _preferences tests."""
    defaults: dict[str, object] = {
        "chat_id": "chat1",
        "contact": "Alice",
        "is_group": False,
        "message_count": 100,
        "my_messages": 50,
        "their_messages": 50,
        "active_days": 30,
        "last_contact": "2026-01-01T00:00:00+00:00",
        "days_since_contact": 180.0,
        "needs_reply": False,
        "pending_hours": None,
        "my_median_reply_hours": 2.5,
        "their_median_reply_hours": 4.0,
        "my_response_rate": 0.9,
        "their_response_rate": 0.85,
        "my_initiation_rate": 0.3,
        "preferred_contact_signal": 0.8,
        "topics": ["lunch", "work"],
        "top_terms": ["meeting", "project"],
        "optimal_reply_window": "same-day",
        "reply_window_source": "median",
        "suggested_reply_timing": "reply within 24h",
        "importance_score": 0.75,
        "importance_reasons": ["frequent contact"],
        "evidence_thread": "Latest messages show...",
    }
    defaults.update(overrides)
    return ContactLearning(**{k: v for k, v in defaults.items() if k != "overrides"})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _iso
# ---------------------------------------------------------------------------


class TestIso:
    def test_datetime_with_tz(self):
        dt = datetime(2026, 1, 15, 12, 30, 0, tzinfo=UTC)
        assert _iso(dt) == "2026-01-15T12:30:00+00:00"

    def test_datetime_naive_converts_to_utc(self):
        dt = datetime(2026, 1, 15, 12, 30, 0)
        result = _iso(dt)
        assert result is not None
        assert "2026-01-15" in result

    def test_none_returns_none(self):
        assert _iso(None) is None


# ---------------------------------------------------------------------------
# _name_key
# ---------------------------------------------------------------------------


class TestNameKey:
    def test_simple_name(self):
        assert _name_key("Alice") == "alice"

    def test_strips_special_characters(self):
        assert _name_key("Dr. Alice (Work)") == "dralicework"

    def test_mixed_case_and_spaces(self):
        assert _name_key("  Bob MARLEY  ") == "bobmarley"


# ---------------------------------------------------------------------------
# _safe_cell
# ---------------------------------------------------------------------------


class TestSafeCell:
    def test_plain_string(self):
        assert _safe_cell("hello") == "hello"

    def test_escapes_pipe(self):
        assert _safe_cell("a|b") == "a\\|b"

    def test_replaces_newline_with_space(self):
        assert _safe_cell("line1\nline2") == "line1 line2"

    def test_strips_whitespace(self):
        assert _safe_cell("  padded  ") == "padded"

    def test_non_string_input(self):
        assert _safe_cell(42) == "42"


# ---------------------------------------------------------------------------
# _is_person
# ---------------------------------------------------------------------------


class TestIsPerson:
    def test_zero_interactions_is_not_person(self):
        c = _contact("bot", "Bot", channels={"gmail": _stats(interactions=0)})
        assert not _is_person(c)

    def test_negative_total_is_not_person(self):
        # total property sums channel interactions; 0 interactions = total 0
        c = _contact("empty", "Empty")
        assert not _is_person(c)

    def test_gmail_automated_sender_is_not_person(self):
        # AUTOMATED_RE matches when the keyword is at position 0 followed by
        # a boundary char like @ — "no-reply@example.com" matches ^ no-?reply @
        c = _contact(
            "news",
            "no-reply@example.com",
            channels={"gmail": _stats(interactions=5)},
        )
        assert not _is_person(c)

    def test_gmail_notifications_sender_is_not_person(self):
        c = _contact(
            "notif",
            "notifications@github.com",
            identifiers={"notifications@github.com"},
            channels={"gmail": _stats(interactions=10)},
        )
        assert not _is_person(c)

    def test_gmail_newsletter_sender_is_not_person(self):
        c = _contact(
            "nl",
            "newsletter@company.com",
            identifiers={"newsletter@company.com"},
            channels={"gmail": _stats(interactions=3)},
        )
        assert not _is_person(c)

    def test_gmail_real_person_is_person(self):
        c = _contact(
            "alice",
            "Alice",
            identifiers={"alice@gmail.com"},
            channels={"gmail": _stats(interactions=20)},
        )
        assert _is_person(c)

    def test_imessage_person_is_person(self):
        c = _contact(
            "bob",
            "Bob",
            identifiers={"+15551234567"},
            channels={"imessage": _stats(interactions=15)},
        )
        assert _is_person(c)

    def test_no_identifiers_gmail_with_automated_name(self):
        # AUTOMATED_RE matches when the keyword appears at position 0 followed
        # by a boundary char or end-of-string.  Since the search string is
        # f"{name} {identifiers}", an empty-identifier contact produces a
        # trailing space, so we use an email-as-name pattern that ends with @.
        c = _contact(
            "support",
            "support@company.com",
            identifiers=set(),
            channels={"gmail": _stats(interactions=2)},
        )
        assert not _is_person(c)


# ---------------------------------------------------------------------------
# _learning_by_name
# ---------------------------------------------------------------------------


class TestLearningByName:
    def test_empty_list(self):
        assert _learning_by_name([]) == {}

    def test_single_entry(self):
        rows = [_learning(contact="Alice", message_count=50)]
        result = _learning_by_name(rows)
        assert "alice" in result
        assert result["alice"].message_count == 50

    def test_duplicate_name_keeps_higher_count(self):
        rows = [
            _learning(contact="Alice", message_count=30),
            _learning(contact="Alice", message_count=80),
            _learning(contact="Alice", message_count=50),
        ]
        result = _learning_by_name(rows)
        assert len(result) == 1
        assert result["alice"].message_count == 80

    def test_different_names(self):
        rows = [
            _learning(contact="Alice", message_count=50),
            _learning(contact="Bob", message_count=30),
            _learning(contact="Charlie", message_count=70),
        ]
        result = _learning_by_name(rows)
        assert len(result) == 3
        assert result["alice"].message_count == 50
        assert result["bob"].message_count == 30
        assert result["charlie"].message_count == 70

    def test_normalized_name_keys(self):
        """Names that normalize to the same key are deduplicated."""
        # _name_key("Dr. Alice") = "dralice", _name_key("dr alice") = "dralice"
        rows = [
            _learning(contact="Dr. Alice", message_count=40),
            _learning(contact="dr alice", message_count=60),
        ]
        result = _learning_by_name(rows)
        assert len(result) == 1
        assert "dralice" in result
        assert result["dralice"].message_count == 60


# ---------------------------------------------------------------------------
# _preferences
# ---------------------------------------------------------------------------


class TestPreferences:
    dt = datetime(2026, 7, 1, tzinfo=UTC)

    def test_with_learning_data(self):
        c = _contact(
            "alice",
            "Alice",
            channels={"gmail": _stats(interactions=20, sent=10, received=10)},
        )
        learning = _learning(
            contact="Alice",
            optimal_reply_window="same-day",
            my_median_reply_hours=2.5,
            my_response_rate=0.9,
            my_initiation_rate=0.3,
            topics=["lunch", "work"],
        )
        prefs = _preferences(c, learning)
        assert prefs.preferred_channel == "gmail"
        assert prefs.preferred_channel_confidence == 1.0
        assert prefs.optimal_reply_window == "same-day"
        assert prefs.median_reply_hours == 2.5
        assert prefs.response_rate == 0.9
        assert prefs.initiation_rate == 0.3
        assert prefs.common_topics == ["lunch", "work"]
        assert "iMessage response history" in prefs.basis

    def test_without_learning_data(self):
        c = _contact(
            "bob",
            "Bob",
            channels={"imessage": _stats(interactions=10, sent=5, received=5)},
        )
        prefs = _preferences(c, None)
        assert prefs.preferred_channel == "imessage"
        assert prefs.preferred_channel_confidence == 1.0
        assert prefs.optimal_reply_window is None
        assert prefs.median_reply_hours is None
        assert prefs.response_rate is None
        assert prefs.initiation_rate is None
        assert prefs.common_topics == []
        assert "insufficient response-timing evidence" in prefs.basis

    def test_zero_interactions_confidence(self):
        c = _contact("empty", "Empty")
        prefs = _preferences(c, None)
        assert prefs.preferred_channel_confidence == 0.0
        assert prefs.preferred_channel == "unknown"

    def test_multi_channel_prefers_highest_interactions(self):
        c = _contact(
            "multi",
            "Multi",
            channels={
                "gmail": _stats(interactions=5),
                "imessage": _stats(interactions=50),
                "linkedin": _stats(interactions=3),
            },
        )
        prefs = _preferences(c, None)
        assert prefs.preferred_channel == "imessage"
        assert prefs.preferred_channel_confidence == pytest.approx(50 / 58, abs=0.01)

    def test_partial_confidence_with_multiple_channels(self):
        c = _contact(
            "partial",
            "Partial",
            channels={
                "gmail": _stats(interactions=30),
                "imessage": _stats(interactions=10),
            },
        )
        prefs = _preferences(c, None)
        assert prefs.preferred_channel == "gmail"
        assert prefs.preferred_channel_confidence == 0.75


# ---------------------------------------------------------------------------
# _history
# ---------------------------------------------------------------------------


class TestHistory:
    dt1 = datetime(2026, 1, 1, tzinfo=UTC)
    dt2 = datetime(2026, 6, 1, tzinfo=UTC)
    dt3 = datetime(2026, 3, 15, tzinfo=UTC)

    def test_no_channels(self):
        c = _contact("empty", "Empty")
        assert _history(c) == []

    def test_single_channel(self):
        c = _contact(
            "alice",
            "Alice",
            channels={
                "gmail": _stats(
                    interactions=20,
                    sent=10,
                    received=10,
                    first_at=self.dt1,
                    last_at=self.dt2,
                    contexts={"work", "personal"},
                )
            },
        )
        rows = _history(c)
        assert len(rows) == 1
        assert rows[0].channel == "gmail"
        assert rows[0].interactions == 20
        assert rows[0].sent == 10
        assert rows[0].received == 10
        assert rows[0].first_at is not None
        assert rows[0].last_at is not None

    def test_multi_channel_sorted_by_last_at_desc(self):
        c = _contact(
            "multi",
            "Multi",
            channels={
                "gmail": _stats(
                    interactions=10, last_at=self.dt1
                ),
                "imessage": _stats(
                    interactions=50, last_at=self.dt2
                ),
                "linkedin": _stats(
                    interactions=5, last_at=self.dt3
                ),
            },
        )
        rows = _history(c)
        assert len(rows) == 3
        # Sorted by last_at descending: imessage (Jun), linkedin (Mar), gmail (Jan)
        assert rows[0].channel == "imessage"
        assert rows[1].channel == "linkedin"
        assert rows[2].channel == "gmail"

    def test_channel_with_none_timestamps(self):
        c = _contact(
            "partial",
            "Partial",
            channels={
                "gmail": _stats(interactions=5),
            },
        )
        rows = _history(c)
        assert len(rows) == 1
        assert rows[0].first_at is None
        assert rows[0].last_at is None

    def test_recent_contexts_truncated_to_three(self):
        c = _contact(
            "chatty",
            "Chatty",
            channels={
                "imessage": _stats(
                    interactions=10,
                    contexts={"topic1", "topic2", "topic3", "topic4", "topic5"},
                ),
            },
        )
        rows = _history(c)
        assert len(rows[0].recent_contexts) == 3


# ---------------------------------------------------------------------------
# _payload
# ---------------------------------------------------------------------------


class TestPayload:
    def test_empty_profiles(self):
        metadata = {"schema": "test.v1", "generated_at": "2026-01-01T00:00:00+00:00"}
        result = _payload([], metadata)
        assert result["contacts"] == []
        assert result["schema"] == "test.v1"

    def test_single_profile(self):
        profile = UnifiedContactProfile(
            contact_id="alice",
            name="Alice",
            identifiers=["alice@example.com"],
            sources=["gmail"],
            total_interactions=50,
            first_interaction_at="2026-01-01T00:00:00+00:00",
            last_interaction_at="2026-06-01T00:00:00+00:00",
            relationship_score=75,
            relationship_tier="strong",
            communication_preferences=CommunicationPreferences(
                preferred_channel="gmail",
                preferred_channel_confidence=1.0,
                optimal_reply_window="same-day",
                median_reply_hours=2.0,
                response_rate=0.9,
                initiation_rate=0.3,
                common_topics=["work"],
                basis="channel volume plus iMessage response history",
            ),
            interaction_history=[
                InteractionHistory(
                    channel="gmail",
                    interactions=50,
                    sent=25,
                    received=25,
                    first_at="2026-01-01T00:00:00+00:00",
                    last_at="2026-06-01T00:00:00+00:00",
                    recent_contexts=["work"],
                )
            ],
        )
        metadata = {"schema": "test.v1", "generated_at": "2026-01-01T00:00:00+00:00"}
        result = _payload([profile], metadata)
        assert len(result["contacts"]) == 1
        assert result["contacts"][0]["contact_id"] == "alice"
        assert result["contacts"][0]["name"] == "Alice"


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------


def _make_profile(
    contact_id: str = "alice",
    name: str = "Alice",
    sources: list[str] | None = None,
    total_interactions: int = 50,
    last_interaction_at: str | None = "2026-06-01T00:00:00+00:00",
) -> UnifiedContactProfile:
    return UnifiedContactProfile(
        contact_id=contact_id,
        name=name,
        identifiers=["alice@example.com"],
        sources=sources or ["gmail"],
        total_interactions=total_interactions,
        first_interaction_at="2026-01-01T00:00:00+00:00",
        last_interaction_at=last_interaction_at,
        relationship_score=75,
        relationship_tier="strong",
        communication_preferences=CommunicationPreferences(
            preferred_channel="gmail",
            preferred_channel_confidence=1.0,
            optimal_reply_window="same-day",
            median_reply_hours=2.0,
            response_rate=0.9,
            initiation_rate=0.3,
            common_topics=["work"],
            basis="channel volume plus iMessage response history",
        ),
        interaction_history=[
            InteractionHistory(
                channel="gmail",
                interactions=50,
                sent=25,
                received=25,
                first_at="2026-01-01T00:00:00+00:00",
                last_at="2026-06-01T00:00:00+00:00",
                recent_contexts=["work"],
            )
        ],
    )


class TestRenderMarkdown:
    def test_empty_profiles(self):
        metadata = {
            "schema": "test.v1",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "profile_count": 0,
            "cross_channel_profile_count": 0,
            "source_status": {
                "gmail": {"available": True, "interactions": 0, "detail": "no data"},
            },
        }
        output = render_markdown([], metadata)
        assert "# Unified Contact View" in output
        assert "Profiles: **0**" in output
        assert "## Profile Detail" in output

    def test_single_profile(self):
        metadata = {
            "schema": "test.v1",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "profile_count": 1,
            "cross_channel_profile_count": 0,
            "source_status": {
                "gmail": {"available": True, "interactions": 50, "detail": "ok"},
            },
        }
        output = render_markdown([_make_profile()], metadata)
        assert "### Alice" in output
        assert "Alice" in output
        assert "gmail" in output

    def test_multiple_profiles(self):
        metadata = {
            "schema": "test.v1",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "profile_count": 2,
            "cross_channel_profile_count": 1,
            "source_status": {
                "gmail": {"available": True, "interactions": 100, "detail": "ok"},
                "imessage": {"available": True, "interactions": 200, "detail": "ok"},
            },
        }
        profiles = [
            _make_profile("alice", "Alice"),
            _make_profile("bob", "Bob", sources=["gmail", "imessage"], total_interactions=100),
        ]
        output = render_markdown(profiles, metadata)
        assert "### Alice" in output
        assert "### Bob" in output
        assert "Profiles: **2**" in output
        assert "spanning multiple channels" in output

    def test_source_status_renders_unavailable(self):
        metadata = {
            "schema": "test.v1",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "profile_count": 0,
            "cross_channel_profile_count": 0,
            "source_status": {
                "gmail": {"available": False, "interactions": 0, "detail": "auth failed"},
            },
        }
        output = render_markdown([], metadata)
        assert "| gmail | no | 0 | auth failed |" in output

    def test_profile_with_pipe_in_name_escaped(self):
        metadata = {
            "schema": "test.v1",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "profile_count": 1,
            "cross_channel_profile_count": 0,
            "source_status": {},
        }
        profile = _make_profile("test", "Company | Division")
        output = render_markdown([profile], metadata)
        assert "Company \\| Division" in output

    def test_common_topics_rendered(self):
        metadata = {
            "schema": "test.v1",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "profile_count": 1,
            "cross_channel_profile_count": 0,
            "source_status": {},
        }
        output = render_markdown([_make_profile()], metadata)
        assert "**Common topics:** work" in output

    def test_profile_without_topics_no_common_topics_line(self):
        metadata = {
            "schema": "test.v1",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "profile_count": 1,
            "cross_channel_profile_count": 0,
            "source_status": {},
        }
        profile = _make_profile()
        # Override common_topics to empty
        profile = UnifiedContactProfile(
            contact_id=profile.contact_id,
            name=profile.name,
            identifiers=profile.identifiers,
            sources=profile.sources,
            total_interactions=profile.total_interactions,
            first_interaction_at=profile.first_interaction_at,
            last_interaction_at=profile.last_interaction_at,
            relationship_score=profile.relationship_score,
            relationship_tier=profile.relationship_tier,
            communication_preferences=CommunicationPreferences(
                preferred_channel="gmail",
                preferred_channel_confidence=1.0,
                optimal_reply_window="same-day",
                median_reply_hours=2.0,
                response_rate=0.9,
                initiation_rate=0.3,
                common_topics=[],
                basis="test",
            ),
            interaction_history=profile.interaction_history,
        )
        output = render_markdown([profile], metadata)
        assert "**Common topics:**" not in output

    def test_profile_with_unknown_reply_window(self):
        metadata = {
            "schema": "test.v1",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "profile_count": 1,
            "cross_channel_profile_count": 0,
            "source_status": {},
        }
        profile = _make_profile()
        profile = UnifiedContactProfile(
            contact_id=profile.contact_id,
            name=profile.name,
            identifiers=profile.identifiers,
            sources=profile.sources,
            total_interactions=profile.total_interactions,
            first_interaction_at=profile.first_interaction_at,
            last_interaction_at=profile.last_interaction_at,
            relationship_score=profile.relationship_score,
            relationship_tier=profile.relationship_tier,
            communication_preferences=CommunicationPreferences(
                preferred_channel="gmail",
                preferred_channel_confidence=1.0,
                optimal_reply_window=None,
                median_reply_hours=None,
                response_rate=None,
                initiation_rate=None,
                common_topics=[],
                basis="test",
            ),
            interaction_history=profile.interaction_history,
        )
        output = render_markdown([profile], metadata)
        assert "unknown" in output  # "window unknown" and "reply hours unknown"
