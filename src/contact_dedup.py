from difflib import SequenceMatcher


def _fuzzy_name_score(name_a: str, name_b: str) -> float:
    a = name_a.lower().strip()
    b = name_b.lower().strip()
    return SequenceMatcher(None, a, b).ratio()
