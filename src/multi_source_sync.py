#!/usr/bin/env python3
"""Create unified Gmail, iMessage, and LinkedIn contact profiles."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.contact_relationship_sync import (  # noqa: E402
    AUTOMATED_RE,
    ChannelStats,
    ContactRelationship,
    RelationshipBook,
    _source_status,
    load_gmail,
    load_imessage,
    load_index_fallback,
    load_linkedin,
)
from src.imessage_learning import ContactLearning, learn_imessage_contacts  # noqa: E402

SCHEMA = "inbox.unified_contacts.v1"
CONTACT_CHANNELS = ("gmail", "imessage", "linkedin")


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat(timespec="seconds") if value else None


def _name_key(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _safe_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _is_person(contact: ContactRelationship) -> bool:
    if contact.total <= 0:
        return False
    identifiers = " ".join(contact.identifiers)
    return not (
        contact.preferred_channel() == "gmail"
        and AUTOMATED_RE.search(f"{contact.name} {identifiers}")
    )


@dataclass(frozen=True)
class InteractionHistory:
    channel: str
    interactions: int
    sent: int
    received: int
    first_at: str | None
    last_at: str | None
    recent_contexts: list[str]


@dataclass(frozen=True)
class CommunicationPreferences:
    preferred_channel: str
    preferred_channel_confidence: float
    optimal_reply_window: str | None
    median_reply_hours: float | None
    response_rate: float | None
    initiation_rate: float | None
    common_topics: list[str]
    basis: str


@dataclass(frozen=True)
class UnifiedContactProfile:
    contact_id: str
    name: str
    identifiers: list[str]
    sources: list[str]
    total_interactions: int
    first_interaction_at: str | None
    last_interaction_at: str | None
    relationship_score: int
    relationship_tier: str
    communication_preferences: CommunicationPreferences
    interaction_history: list[InteractionHistory]


def _learning_by_name(rows: list[ContactLearning]) -> dict[str, ContactLearning]:
    learned: dict[str, ContactLearning] = {}
    for row in rows:
        key = _name_key(row.contact)
        current = learned.get(key)
        if key and (current is None or row.message_count > current.message_count):
            learned[key] = row
    return learned


def _preferences(
    contact: ContactRelationship,
    learning: ContactLearning | None,
) -> CommunicationPreferences:
    preferred = contact.preferred_channel()
    preferred_count = contact.channels.get(preferred, ChannelStats()).interactions
    confidence = round(preferred_count / contact.total, 3) if contact.total else 0.0
    if learning:
        return CommunicationPreferences(
            preferred_channel=preferred,
            preferred_channel_confidence=confidence,
            optimal_reply_window=learning.optimal_reply_window,
            median_reply_hours=learning.my_median_reply_hours,
            response_rate=learning.my_response_rate,
            initiation_rate=learning.my_initiation_rate,
            common_topics=learning.topics,
            basis="channel volume plus iMessage response history",
        )
    return CommunicationPreferences(
        preferred_channel=preferred,
        preferred_channel_confidence=confidence,
        optimal_reply_window=None,
        median_reply_hours=None,
        response_rate=None,
        initiation_rate=None,
        common_topics=[],
        basis="channel volume; insufficient response-timing evidence",
    )


def _history(contact: ContactRelationship) -> list[InteractionHistory]:
    rows = []
    for channel in CONTACT_CHANNELS:
        stats = contact.channels.get(channel)
        if not stats:
            continue
        rows.append(
            InteractionHistory(
                channel=channel,
                interactions=stats.interactions,
                sent=stats.sent,
                received=stats.received,
                first_at=_iso(stats.first_at),
                last_at=_iso(stats.last_at),
                recent_contexts=sorted(stats.contexts)[:3],
            )
        )
    return sorted(rows, key=lambda row: row.last_at or "", reverse=True)


def build_unified_profiles(
    *,
    gmail_limit: int = 300,
    include_gmail: bool = True,
    limit: int = 50,
    reference: datetime | None = None,
) -> tuple[list[UnifiedContactProfile], dict[str, Any]]:
    """Load source histories and return ranked, read-only unified profiles."""
    now = reference or datetime.now(UTC)
    book = RelationshipBook()
    status: dict[str, Any] = {
        "imessage": load_imessage(book),
        "linkedin": load_linkedin(book),
        "gmail": (
            load_gmail(book, gmail_limit)
            if include_gmail
            else _source_status(False, "live Gmail scan disabled")
        ),
    }
    if not status["gmail"]["available"] or not status["linkedin"]["available"]:
        status["index_fallback"] = load_index_fallback(book)
    status["generated_at"] = now.isoformat(timespec="seconds")
    learning = _learning_by_name(
        learn_imessage_contacts(now=now, lookback_days=365, limit=max(200, limit * 3))
    )
    contacts = [contact for contact in book.contacts.values() if _is_person(contact)]
    contacts.sort(
        key=lambda contact: (contact.strength(now)[0], contact.total),
        reverse=True,
    )

    profiles = []
    for contact in contacts[:limit]:
        score, tier = contact.strength(now)
        channel_history = _history(contact)
        first_values = [row.first_at for row in channel_history if row.first_at]
        last_values = [row.last_at for row in channel_history if row.last_at]
        profiles.append(
            UnifiedContactProfile(
                contact_id=contact.key,
                name=contact.name,
                identifiers=sorted(contact.identifiers),
                sources=[row.channel for row in channel_history],
                total_interactions=contact.total,
                first_interaction_at=min(first_values) if first_values else None,
                last_interaction_at=max(last_values) if last_values else None,
                relationship_score=score,
                relationship_tier=tier,
                communication_preferences=_preferences(
                    contact,
                    learning.get(_name_key(contact.name)),
                ),
                interaction_history=channel_history,
            )
        )

    source_status = {
        channel: status[channel]
        for channel in (*CONTACT_CHANNELS, "index_fallback")
        if channel in status
    }
    metadata = {
        "schema": SCHEMA,
        "generated_at": now.isoformat(timespec="seconds"),
        "profile_count": len(profiles),
        "cross_channel_profile_count": sum(len(profile.sources) > 1 for profile in profiles),
        "source_status": source_status,
    }
    return profiles, metadata


def render_markdown(
    profiles: list[UnifiedContactProfile],
    metadata: dict[str, Any],
) -> str:
    lines = [
        "# Unified Contact View",
        "",
        f"Generated: {metadata['generated_at']}",
        f"Schema: `{metadata['schema']}`",
        f"Profiles: **{metadata['profile_count']}**",
        f"Profiles spanning multiple channels: **{metadata['cross_channel_profile_count']}**",
        "",
        "## Source Coverage",
        "",
        "| Source | Available | Interactions | Evidence |",
        "|---|---:|---:|---|",
    ]
    for source, status in metadata["source_status"].items():
        lines.append(
            f"| {source} | {'yes' if status['available'] else 'no'} | "
            f"{status['interactions']} | {_safe_cell(status['detail'])} |"
        )
    lines.extend(
        [
            "",
            "## Contacts",
            "",
            "| # | Contact | Sources | Interactions | Preferred channel | Reply window | "
            "Last interaction | Relationship |",
            "|---:|---|---|---:|---|---|---|---|",
        ]
    )
    for index, profile in enumerate(profiles, start=1):
        preferences = profile.communication_preferences
        lines.append(
            f"| {index} | **{_safe_cell(profile.name)}** | "
            f"{', '.join(profile.sources)} | {profile.total_interactions} | "
            f"{preferences.preferred_channel} ({preferences.preferred_channel_confidence:.0%}) | "
            f"{preferences.optimal_reply_window or 'unknown'} | "
            f"{profile.last_interaction_at or 'unknown'} | "
            f"{profile.relationship_score} ({profile.relationship_tier}) |"
        )

    lines.extend(["", "## Profile Detail", ""])
    for profile in profiles:
        preferences = profile.communication_preferences
        lines.extend(
            [
                f"### {profile.name}",
                "",
                f"- **Identifiers:** {_safe_cell(', '.join(profile.identifiers)) or 'none'}.",
                f"- **Communication preference:** `{preferences.preferred_channel}` "
                f"({preferences.preferred_channel_confidence:.0%} of observed interactions); "
                f"{preferences.basis}.",
                f"- **Reply pattern:** window {preferences.optimal_reply_window or 'unknown'}; "
                f"median reply hours "
                f"{preferences.median_reply_hours if preferences.median_reply_hours is not None else 'unknown'}; "
                f"response rate "
                f"{f'{preferences.response_rate:.0f}%' if preferences.response_rate is not None else 'unknown'}.",
            ]
        )
        if preferences.common_topics:
            lines.append(f"- **Common topics:** {', '.join(preferences.common_topics)}.")
        for history in profile.interaction_history:
            contexts = "; ".join(history.recent_contexts[:2]) or "direct interaction"
            lines.append(
                f"- **{history.channel} history:** {history.interactions} interactions "
                f"({history.sent} sent / {history.received} received), "
                f"{history.first_at or 'unknown'} to {history.last_at or 'unknown'}; "
                f"context: {_safe_cell(contexts)}."
            )
        lines.append("")
    return "\n".join(lines)


def _payload(
    profiles: list[UnifiedContactProfile],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {**metadata, "contacts": [asdict(profile) for profile in profiles]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--minimum-profiles", type=int, default=20)
    parser.add_argument("--gmail-limit", type=int, default=300)
    parser.add_argument("--no-gmail", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    profiles, metadata = build_unified_profiles(
        gmail_limit=max(1, args.gmail_limit),
        include_gmail=not args.no_gmail,
        limit=max(1, args.limit),
    )
    rendered = (
        json.dumps(_payload(profiles, metadata), indent=2)
        if args.json
        else render_markdown(profiles, metadata)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
        print(f"Wrote {args.output} with {len(profiles)} unified profiles")
    else:
        print(rendered)
    return 0 if len(profiles) >= max(1, args.minimum_profiles) else 2


if __name__ == "__main__":
    raise SystemExit(main())
