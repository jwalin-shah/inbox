from dataclasses import dataclass
from datetime import date
from typing import List


@dataclass
class DigestSection:
    contact: str
    count: int
    excerpt: str


@dataclass
class Digest:
    today: date
    sections: List[DigestSection]
