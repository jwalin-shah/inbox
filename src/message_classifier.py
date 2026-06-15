import re

_PROMOTIONAL_PATTERN = re.compile(
    r"\d+\s*%\s*off"           # e.g. "50% off", "20 % off"
    r"|\bpercent[\s-]+off\b"   # "percent off" or "percent-off"
    r"|\bsale\b"               # sale
    r"|\bdiscount\w*\b"        # discount, discounts, discounted
    r"|\boffer\w*\b"           # offer, offers, offered
    r"|\bdeal\w*\b",           # deal, deals
    re.IGNORECASE,
)


def _is_promotional(msg: str) -> bool:
    """Return True when *msg* looks like marketing/promotional content.

    Heuristics: percent-off patterns, sale, discount, offer, deal.
    """
    if not isinstance(msg, str) or not msg:
        return False
    return bool(_PROMOTIONAL_PATTERN.search(msg))
