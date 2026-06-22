"""X/Twitter link extraction helpers for iMessage text."""

from __future__ import annotations

import re

_X_LINK_RE = re.compile(
    r"https?://(?:www\.)?(?:twitter\.com|x\.com)/[^\s<>\"']+",
    re.IGNORECASE,
)
_X_LINK_BARE_RE = re.compile(
    r"(?:^|[\s(])((?:www\.)?(?:twitter\.com|x\.com)/[^\s<>\"']+)",
    re.IGNORECASE,
)


def strip_url_trailing_punct(url: str) -> str:
    return url.rstrip(".,;:!?)>'\"")


def extract_x_links(text: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for match in _X_LINK_RE.finditer(text):
        url = strip_url_trailing_punct(match.group(0))
        if url not in seen:
            seen.add(url)
            links.append(url)
    for match in _X_LINK_BARE_RE.finditer(text):
        url = strip_url_trailing_punct(match.group(1))
        if not url.lower().startswith("http"):
            url = f"https://{url}"
        if url not in seen:
            seen.add(url)
            links.append(url)
    return links
