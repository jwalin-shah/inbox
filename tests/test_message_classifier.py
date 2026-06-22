"""Tests for :mod:`src.message_classifier`."""

from src.message_classifier import is_promotional


def test_is_promotional_percent_off():
    assert is_promotional("50% off everything!")


def test_is_promotional_percent_with_space():
    assert is_promotional("20 % off selected items")


def test_is_promotional_percent_off_variant():
    assert is_promotional("Summer percent-off sale")


def test_is_promotional_sale_keyword():
    assert is_promotional("Big sale this weekend")


def test_is_promotional_discount():
    assert is_promotional("Exclusive discount for members")


def test_is_promotional_offers():
    assert is_promotional("Special offer just for you")


def test_is_promotional_deals():
    assert is_promotional("Hot deals today only")


def test_is_not_promotional_plain_text():
    assert not is_promotional("Hey, are we still on for lunch?")


def test_is_not_promotional_meeting_invite():
    assert not is_promotional("Team standup at 10am tomorrow")


def test_is_not_promotional_empty_string():
    assert not is_promotional("")


def test_is_not_promotional_noneish():
    assert not is_promotional("")

def test_is_not_promotional_none():
    assert not is_promotional(None)  # type: ignore[arg-type]