import sqlite3

from thread_classifier import classify_thread


def _row(sender: str, subject: str = "", body_text: str = "", snippet: str = "") -> sqlite3.Row:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE items (sender TEXT, subject TEXT, body_text TEXT, snippet TEXT)")
    conn.execute(
        "INSERT INTO items(sender, subject, body_text, snippet) VALUES (?, ?, ?, ?)",
        (sender, subject, body_text, snippet),
    )
    return conn.execute("SELECT * FROM items").fetchone()


def test_classify_thread_preserves_otp_ignore_behavior():
    latest = _row("22395", body_text="Your verification code is: 995228")
    classification = classify_thread(latest=latest)
    assert classification.noise_class == "otp"
    assert classification.actionability == "ignore"


def test_classify_thread_routes_direct_human_asks_to_reply():
    latest = _row(
        "Recruiter",
        subject="Interview follow up",
        body_text="Would you be open to a short call tomorrow?",
    )
    classification = classify_thread(latest=latest)
    assert classification.actionability == "reply"
    assert classification.needs_reply == 1


def test_classify_thread_archives_newsletter_noise():
    latest = _row(
        "jobs@example.com",
        subject="Weekly digest",
        body_text="View in browser. Manage preferences or unsubscribe from this newsletter.",
    )
    classification = classify_thread(latest=latest)
    assert classification.noise_class == "newsletter"
    assert classification.actionability == "archive"


def test_classify_thread_archives_short_acknowledgements():
    latest = _row("Alice", subject="Re: Plan", body_text="Thanks, sounds good.")
    classification = classify_thread(latest=latest)
    assert classification.noise_class == "low-value-ack"
    assert classification.actionability == "archive"


def test_classify_thread_does_not_archive_ack_with_request():
    latest = _row("Alice", subject="Re: Plan", body_text="Thanks. Can you send the notes?")
    classification = classify_thread(latest=latest)
    assert classification.noise_class == ""
    assert classification.actionability == "reply"
