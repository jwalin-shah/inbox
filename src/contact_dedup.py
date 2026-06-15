def _normalize_email(email: str) -> str:
    """Lowercase and strip an email so equality comparison is whitespace/case-insensitive."""
    return email.strip().lower()
