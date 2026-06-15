def _normalize(msg: str) -> str:
    """Lowercase and strip surrounding whitespace from a message.

    Used as a preprocessing step so downstream keyword/regex checks
    are case-insensitive and ignore leading/trailing whitespace such
    as spaces, tabs, and newlines.
    """
    return msg.lower().strip()
