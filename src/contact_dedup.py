"""Contact deduplication helpers."""

from __future__ import annotations


def _emails_match(entry_a: dict, entry_b: dict) -> bool:
    """Return True iff the two entries share at least one normalized email address.

    Emails are normalized by stripping surrounding whitespace and lowercasing
    for case-insensitive comparison. Entries may omit the ``emails`` key or
    supply a non-iterable value; missing or empty email lists never match.
    """
    emails_a = entry_a.get("emails") or []
    emails_b = entry_b.get("emails") or []

    set_a = {str(email).strip().lower() for email in emails_a if email}
    set_b = {str(email).strip().lower() for email in emails_b if email}

    return bool(set_a & set_b)
