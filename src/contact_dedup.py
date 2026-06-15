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
