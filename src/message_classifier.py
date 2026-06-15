import re


_VERIFICATION_KEYWORDS = re.compile(
    r"\b(?:otp|verification|verify|code|passcode|pin|security\s+code|"
    r"one[-\s]time\s+password|confirm|authentication|sign[-\s]in|login)\b",
    re.IGNORECASE,
)

_NUMERIC_CODE = re.compile(r"\b\d{4,}\b")


def _is_transactional(msg: str) -> bool:
    """Return True when the message looks transactional/verification-like.

    Heuristics:
    * Contains a verification phrase (e.g. "code", "OTP", "verify",
      "passcode", "confirm", "authentication", "sign in", "login").
    * Contains a numeric code: a standalone run of at least 4 digits, which
      covers the common length range for OTPs and short-lived tokens while
      avoiding everyday numbers like "50%" or "2024".
    """
    if not msg:
        return False
    if _VERIFICATION_KEYWORDS.search(msg):
        return True
    if _NUMERIC_CODE.search(msg):
        return True
    return False
