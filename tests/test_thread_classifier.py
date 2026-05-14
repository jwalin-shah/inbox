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


def test_classify_thread_treats_confirmation_codes_as_otp():
    latest = _row("Infisical", subject="Infisical confirmation code: 230016")
    classification = classify_thread(latest=latest)
    assert classification.noise_class == "otp"
    assert classification.topic == "security"
    assert classification.actionability == "ignore"


def test_classify_thread_suppresses_dev_notifications():
    latest = _row(
        "chatgpt-codex-connector[bot]",
        subject="Re: [jwalin-shah/physics] MAX-259: Validate rover physics parameters (PR #287)",
    )
    classification = classify_thread(latest=latest)
    assert classification.noise_class == "dev-notification"
    assert classification.topic == "dev"
    assert classification.actionability == "archive"
