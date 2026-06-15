from dataclasses import dataclass
from typing import List


@dataclass
class DigestSection:
    contact: str
    count: int
    content: str


def sort_sections_by_priority(sections: List[DigestSection]) -> List[DigestSection]:
    return sorted(sections, key=lambda s: (-s.count, s.contact))
