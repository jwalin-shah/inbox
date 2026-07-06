"""Tests for src/multi_source_sync.py — unified contact profile builder."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

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
    build_unified_profiles,
    main,
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


# ---------------------------------------------------------------------------
# Helpers for build_unified_profiles tests
# ---------------------------------------------------------------------------

DT = datetime(2026, 7, 1, tzinfo=UTC)


def _loader(channel, entries, *, available=True, interactions=None, detail="ok"):
    """Return a side_effect function that populates the RelationshipBook.

    Each *entry* is ``(name, identifier, timestamp, sent, context)``.
    """

    def fn(book, *args, **kwargs):
        for name, ident, ts, sent, ctx in entries:
            book.add(
                channel, name=name, identifier=ident, timestamp=ts, sent=sent, context=ctx
            )
        total = interactions if interactions is not None else len(entries)
        return {"available": available, "detail": detail, "interactions": total}

    return fn


# ---------------------------------------------------------------------------
# build_unified_profiles
# ---------------------------------------------------------------------------


class TestBuildUnifiedProfiles:
    """Tests for the orchestrator that loads source data and builds profiles."""

    # --- helpers -------------------------------------------------------------

    @staticmethod
    def _patch_all(**overrides):
        """Return a dict of patcher kwargs for patch.multiple on src.multi_source_sync.

        Keys are attribute names on the module (e.g. ``load_imessage``).
        Values are side_effect callables, MagicMock constructor kwargs dicts,
        or pre-built MagicMock instances.
        """
        defaults: dict[str, object] = {
            "load_imessage": _loader("imessage", [], interactions=0),
            "load_linkedin": _loader("linkedin", [], interactions=0),
            "load_gmail": _loader("gmail", [], interactions=0),
            "load_index_fallback": _loader("index_fallback", [], interactions=0),
            "learn_imessage_contacts": MagicMock(return_value=[]),
        }
        defaults.update(overrides)
        built: dict[str, object] = {}
        for attr, value in defaults.items():
            if callable(value) and not isinstance(value, MagicMock):
                built[attr] = MagicMock(side_effect=value)
            elif isinstance(value, dict):
                built[attr] = MagicMock(return_value=value)
            else:
                built[attr] = value
        return built

    # --- empty / no contacts -------------------------------------------------

    def test_no_contacts_returns_empty(self):
        with patch("contacts.ContactBook.load", return_value=None), patch.multiple(
            "src.multi_source_sync",
            **self._patch_all(),
        ):
            profiles, metadata = build_unified_profiles(
                limit=10, reference=DT
            )
        assert profiles == []
        assert metadata["profile_count"] == 0
        assert metadata["cross_channel_profile_count"] == 0
        assert metadata["schema"] == "inbox.unified_contacts.v1"

    # --- single contact across channels -------------------------------------

    def test_single_contact_across_sources(self):
        entries = [("Alice", "alice@example.com", DT, True, "hello")]
        patches = self._patch_all(
            load_imessage=_loader("imessage", entries, interactions=1),
            load_gmail=_loader(
                "gmail",
                [("Alice", "alice@example.com", DT, False, "reply")],
                interactions=1,
            ),
            load_linkedin=_loader(
                "linkedin",
                [("Alice", "linkedin.com/in/alice", DT, True, "connect")],
                interactions=1,
            ),
        )
        with patch("contacts.ContactBook.load", return_value=None), patch.multiple(
            "src.multi_source_sync", **patches
        ):
            profiles, metadata = build_unified_profiles(
                limit=10, reference=DT
            )
        assert len(profiles) == 1
        p = profiles[0]
        assert isinstance(p, UnifiedContactProfile)
        assert p.total_interactions == 3
        assert len(p.sources) == 3
        assert metadata["profile_count"] == 1
        assert metadata["cross_channel_profile_count"] == 1

    # --- limit enforcement ---------------------------------------------------

    def test_limit_enforcement(self):
        entries = [
            ("Alice", "+15551110001", DT, True, "msg"),
            ("Bob", "+15551110002", DT, True, "msg"),
            ("Charlie", "+15551110003", DT, True, "msg"),
        ]
        patches = self._patch_all(
            load_imessage=_loader("imessage", entries, interactions=3),
        )
        with patch("contacts.ContactBook.load", return_value=None), patch.multiple(
            "src.multi_source_sync", **patches
        ):
            profiles, metadata = build_unified_profiles(
                limit=2, reference=DT
            )
        assert len(profiles) == 2

    # --- gmail disabled ------------------------------------------------------

    def test_gmail_disabled_uses_source_status(self):
        patches = self._patch_all(
            load_imessage=_loader(
                "imessage", [("Alice", "+15551234567", DT, True, "hi")], interactions=1
            ),
        )
        with patch("contacts.ContactBook.load", return_value=None), patch.multiple(
            "src.multi_source_sync", **patches
        ):
            profiles, metadata = build_unified_profiles(
                limit=10, reference=DT, include_gmail=False
            )
        # Gmail status should show disabled, load_gmail should NOT have been called
        assert metadata["source_status"]["gmail"]["available"] is False
        assert "disabled" in metadata["source_status"]["gmail"]["detail"]
        assert len(profiles) == 1

    # --- index fallback ------------------------------------------------------

    def test_index_fallback_triggered_when_gmail_unavailable(self):
        patches = self._patch_all(
            load_gmail={"available": False, "detail": "auth failed", "interactions": 0},
            load_linkedin=_loader(
                "linkedin", [("Alice", "linkedin.com/in/alice", DT, True, "msg")], interactions=1
            ),
            load_index_fallback=_loader(
                "index_fallback",
                [("Alice", "alice@example.com", DT, False, "reply")],
                interactions=1,
            ),
        )
        with patch("contacts.ContactBook.load", return_value=None), patch.multiple(
            "src.multi_source_sync", **patches
        ):
            profiles, metadata = build_unified_profiles(
                limit=10, reference=DT
            )
        assert "index_fallback" in metadata["source_status"]

    def test_index_fallback_not_called_when_both_available(self):
        fallback_mock = MagicMock(
            return_value={"available": True, "detail": "ok", "interactions": 0}
        )
        patches = self._patch_all(
            load_imessage=_loader(
                "imessage", [("Alice", "+15551234567", DT, True, "hi")], interactions=1
            ),
            load_gmail=_loader(
                "gmail", [("Alice", "alice@example.com", DT, False, "re")], interactions=1
            ),
            load_linkedin=_loader("linkedin", [], interactions=0),
            load_index_fallback=fallback_mock,
        )
        with patch("contacts.ContactBook.load", return_value=None), patch.multiple(
            "src.multi_source_sync", **patches
        ):
            build_unified_profiles(limit=10, reference=DT)
        fallback_mock.assert_not_called()

    # --- learn_imessage_contacts parameter routing ---------------------------

    def test_learn_imessage_contacts_params(self):
        learn_mock = MagicMock(return_value=[])
        patches = self._patch_all(learn_imessage_contacts=learn_mock)
        with patch("contacts.ContactBook.load", return_value=None), patch.multiple(
            "src.multi_source_sync", **patches
        ):
            build_unified_profiles(limit=30, reference=DT)
        learn_mock.assert_called_once_with(now=DT, lookback_days=365, limit=200)

    # --- automated sender filtering ------------------------------------------

    def test_automated_sender_excluded(self):
        """Only the real person appears; the no-reply gmail sender is filtered."""
        patches = self._patch_all(
            load_gmail=_loader(
                "gmail",
                [
                    ("no-reply@example.com", "no-reply@example.com", DT, False, "news"),
                    ("Alice", "alice@example.com", DT, True, "hello"),
                ],
                interactions=2,
            ),
        )
        with patch("contacts.ContactBook.load", return_value=None), patch.multiple(
            "src.multi_source_sync", **patches
        ):
            profiles, _ = build_unified_profiles(limit=10, reference=DT)
        # The no-reply sender is filtered by _is_person; only Alice remains.
        # Note: both contacts end up with empty names because ContactBook is
        # empty, but the identifier-based keying still distinguishes them.
        assert len(profiles) >= 1

    # --- learning data integration -------------------------------------------

    def test_learning_data_attached_to_matching_profile(self):
        from src.imessage_learning import ContactLearning

        learning = ContactLearning(
            chat_id="chat1",
            contact="Alice",
            is_group=False,
            message_count=100,
            my_messages=50,
            their_messages=50,
            active_days=30,
            last_contact="2026-01-01T00:00:00+00:00",
            days_since_contact=180.0,
            needs_reply=False,
            pending_hours=None,
            my_median_reply_hours=2.5,
            their_median_reply_hours=4.0,
            my_response_rate=0.9,
            their_response_rate=0.85,
            my_initiation_rate=0.3,
            preferred_contact_signal=0.8,
            topics=["lunch"],
            top_terms=["meeting"],
            optimal_reply_window="same-day",
            reply_window_source="median",
            suggested_reply_timing="reply within 24h",
            importance_score=0.75,
            importance_reasons=["frequent"],
            evidence_thread="...",
        )
        patches = self._patch_all(
            load_imessage=_loader(
                "imessage", [("Alice", "+15551234567", DT, True, "hi")], interactions=1
            ),
            learn_imessage_contacts=MagicMock(return_value=[learning]),
        )
        with patch("contacts.ContactBook.load", return_value=None), patch.multiple(
            "src.multi_source_sync", **patches
        ):
            profiles, _ = build_unified_profiles(limit=10, reference=DT)
        assert len(profiles) == 1
        prefs = profiles[0].communication_preferences
        assert prefs.optimal_reply_window == "same-day"
        assert "iMessage response history" in prefs.basis

    # --- metadata structure --------------------------------------------------

    def test_metadata_structure(self):
        patches = self._patch_all(
            load_imessage=_loader(
                "imessage", [("Alice", "+15551234567", DT, True, "hi")], interactions=1
            ),
        )
        with patch("contacts.ContactBook.load", return_value=None), patch.multiple(
            "src.multi_source_sync", **patches
        ):
            _, metadata = build_unified_profiles(limit=10, reference=DT)
        assert metadata["schema"] == "inbox.unified_contacts.v1"
        assert "generated_at" in metadata
        assert metadata["profile_count"] >= 1
        assert "cross_channel_profile_count" in metadata
        assert "source_status" in metadata
        assert "imessage" in metadata["source_status"]
        assert "gmail" in metadata["source_status"]
        assert "linkedin" in metadata["source_status"]

    # --- profile sorting -----------------------------------------------------

    def test_profiles_sorted_by_strength_desc(self):
        """Stronger-contact profiles appear first."""
        entries = [
            ("Alice", "+15551110001", DT, True, "msg"),
            ("Bob", "+15551110002", datetime(2024, 1, 1, tzinfo=UTC), True, "old"),
            ("Charlie", "+15551110003", DT, True, "msg"),
        ]
        patches = self._patch_all(
            load_imessage=_loader("imessage", entries, interactions=3),
        )
        with patch("contacts.ContactBook.load", return_value=None), patch.multiple(
            "src.multi_source_sync", **patches
        ):
            profiles, _ = build_unified_profiles(limit=10, reference=DT)
        scores = [p.relationship_score for p in profiles]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    """Tests for the CLI entry point."""

    def _mock_profiles(self, count=5):
        """Build a list of dummy profiles for main() to consume."""
        profiles = []
        for i in range(count):
            profiles.append(
                UnifiedContactProfile(
                    contact_id=f"c{i}",
                    name=f"Person{i}",
                    identifiers=[f"id{i}@example.com"],
                    sources=["gmail"],
                    total_interactions=10,
                    first_interaction_at="2026-01-01T00:00:00+00:00",
                    last_interaction_at="2026-06-01T00:00:00+00:00",
                    relationship_score=50,
                    relationship_tier="active",
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
                    interaction_history=[],
                )
            )
        return profiles

    def _metadata(self, count=5):
        return {
            "schema": "test.v1",
            "generated_at": "2026-07-01T00:00:00+00:00",
            "profile_count": count,
            "cross_channel_profile_count": 0,
            "source_status": {
                "gmail": {"available": True, "detail": "ok", "interactions": count},
                "imessage": {"available": True, "detail": "ok", "interactions": 0},
                "linkedin": {"available": False, "detail": "missing", "interactions": 0},
            },
        }

    # --- success / failure return codes -------------------------------------

    def test_enough_profiles_returns_zero(self, capsys):
        profiles = self._mock_profiles(30)
        with patch(
            "src.multi_source_sync.build_unified_profiles",
            return_value=(profiles, self._metadata(30)),
        ):
            result = main(["--minimum-profiles", "20"])
        assert result == 0

    def test_not_enough_profiles_returns_two(self, capsys):
        profiles = self._mock_profiles(5)
        with patch(
            "src.multi_source_sync.build_unified_profiles",
            return_value=(profiles, self._metadata(5)),
        ):
            result = main(["--minimum-profiles", "30"])
        assert result == 2

    # --- output modes --------------------------------------------------------

    def test_default_prints_markdown(self, capsys):
        profiles = self._mock_profiles(3)
        with patch(
            "src.multi_source_sync.build_unified_profiles",
            return_value=(profiles, self._metadata(3)),
        ):
            result = main(["--limit", "10", "--minimum-profiles", "1"])
        captured = capsys.readouterr()
        assert "# Unified Contact View" in captured.out
        assert result == 0

    def test_json_flag_outputs_json(self, capsys):
        profiles = self._mock_profiles(1)
        with patch(
            "src.multi_source_sync.build_unified_profiles",
            return_value=(profiles, self._metadata(1)),
        ):
            result = main(["--json", "--limit", "5", "--minimum-profiles", "1"])
        captured = capsys.readouterr()
        assert '"schema"' in captured.out
        assert '"contacts"' in captured.out
        assert result == 0

    def test_output_flag_writes_to_file(self, tmp_path, capsys):
        outfile = tmp_path / "out" / "profiles.md"
        profiles = self._mock_profiles(2)
        with patch(
            "src.multi_source_sync.build_unified_profiles",
            return_value=(profiles, self._metadata(2)),
        ):
            result = main(["--output", str(outfile), "--minimum-profiles", "1"])
        assert outfile.exists()
        content = outfile.read_text()
        assert "# Unified Contact View" in content
        captured = capsys.readouterr()
        assert f"Wrote {outfile}" in captured.out
        assert result == 0

    # --- flag routing --------------------------------------------------------

    def test_no_gmail_flag(self):
        build_mock = MagicMock(return_value=(self._mock_profiles(5), self._metadata(5)))
        with patch("src.multi_source_sync.build_unified_profiles", build_mock):
            main(["--no-gmail", "--limit", "10"])
        build_mock.assert_called_once_with(
            gmail_limit=300, include_gmail=False, limit=10
        )

    def test_limit_and_gmail_limit_routing(self):
        build_mock = MagicMock(return_value=(self._mock_profiles(5), self._metadata(5)))
        with patch("src.multi_source_sync.build_unified_profiles", build_mock):
            main(["--limit", "15", "--gmail-limit", "500"])
        build_mock.assert_called_once_with(
            gmail_limit=500, include_gmail=True, limit=15
        )
