"""Data model for merged/deduplicated contacts across channels.

Use ``RelationshipBook.to_merged_contacts()`` to produce these from
the live contact relationship report.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MergedContact:
    """Holds the deduplicated result: canonical name, merged email set,
    preserved phone list, and source provenance."""

    name: str
    emails: set[str] = field(default_factory=set)
    phones: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Normalize emails to a set to enforce "merged email set" semantics.
        if not isinstance(self.emails, set):
            self.emails = set(self.emails)

    def add_channel(self, channel: str) -> None:
        """Record that this contact was seen on *channel*."""
        if channel not in self.sources:
            self.sources.append(channel)

    def add_email(self, email: str) -> None:
        """Add *email* if it looks like an email address."""
        if "@" in email:
            self.emails.add(email.strip().lower())
