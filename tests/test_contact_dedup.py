"""Tests for :mod:`src.contact_dedup`."""

from src.contact_dedup import MergedContact


def test_merged_contact_defaults():
    mc = MergedContact(name="Alice")
    assert mc.name == "Alice"
    assert mc.emails == set()
    assert mc.phones == []
    assert mc.sources == []


def test_merged_contact_with_emails():
    mc = MergedContact(name="Bob", emails={"bob@example.com", "BOB@WORK.COM"})
    assert "bob@example.com" in mc.emails
    # __post_init__ doesn't lower — preserves as given, but add_email does
    assert "bob@work.com" not in mc.emails


def test_merged_contact_add_channel():
    mc = MergedContact(name="Carol")
    mc.add_channel("gmail")
    mc.add_channel("imessage")
    assert mc.sources == ["gmail", "imessage"]
    # add_channel is idempotent for re-add
    mc.add_channel("gmail")
    assert mc.sources == ["gmail", "imessage"]


def test_merged_contact_add_email():
    mc = MergedContact(name="Dave")
    mc.add_email("dave@example.com")
    mc.add_email("  DAVE@WORK.COM  ")
    assert "dave@example.com" in mc.emails
    assert "dave@work.com" in mc.emails


def test_merged_contact_add_email_ignores_non_email():
    mc = MergedContact(name="Eve")
    mc.add_email("+1-555-0100")
    assert len(mc.emails) == 0


def test_merged_contact_phones_list():
    mc = MergedContact(name="Frank", phones=["+1-555-0100", "+1-555-0101"])
    assert mc.phones == ["+1-555-0100", "+1-555-0101"]


def test_merged_contact_normalizes_emails_from_list():
    """__post_init__ converts a list of emails into a set."""
    mc = MergedContact(name="Grace", emails=["grace@example.com", "grace@work.com"])
    assert isinstance(mc.emails, set)
    assert mc.emails == {"grace@example.com", "grace@work.com"}