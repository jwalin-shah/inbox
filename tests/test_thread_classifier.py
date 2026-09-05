import sqlite3

from thread_classifier import _coalesce_str, _topic, classify_thread


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


def test_classify_thread_newsletter_noise_class():
    """Covers _noise_class returning 'newsletter' (line 88)."""
    latest = _row("newsletter@example.com", body_text="Click here to unsubscribe")
    classification = classify_thread(latest=latest)
    assert classification.noise_class == "newsletter"
    assert classification.actionability == "archive"
    assert classification.needs_reply == 0


def test_classify_thread_review_is_not_a_reply_obligation():
    latest = _row(
        "opportunity@example.com",
        subject="Persona AI seed opportunity",
        body_text="A new opportunity you may want to review.",
    )
    classification = classify_thread(latest=latest)
    assert classification.actionability == "review"
    assert classification.needs_reply == 0


def test_classify_thread_appointment_noise_class():
    """Covers _noise_class returning 'appointment' (line 90)."""
    latest = _row("doctor@example.com", body_text="Your appointment is confirmed")
    classification = classify_thread(latest=latest)
    assert classification.noise_class == "appointment"


def test_classify_thread_survey_noise_class():
    """Covers _noise_class returning 'survey' (line 92)."""
    latest = _row("survey@example.com", body_text="Please take our survey")
    classification = classify_thread(latest=latest)
    assert classification.noise_class == "survey"
    assert classification.actionability == "ignore"


def test_classify_thread_receipt_noise_class():
    """Covers _noise_class returning 'receipt' (line 94)."""
    latest = _row("orders@example.com", body_text="Your receipt from Amazon")
    classification = classify_thread(latest=latest)
    assert classification.noise_class == "receipt"
    assert classification.actionability == "ignore"


def test_classify_thread_security_alert_noise_class():
    """Covers _noise_class returning 'security-alert' (line 96)."""
    latest = _row("alerts@example.com", body_text="New login detected from new device")
    classification = classify_thread(latest=latest)
    assert classification.noise_class == "security-alert"


def test_topic_returns_dev_for_pr_run_failed_subject():
    """Covers _topic returning 'dev' (line 105) via _is_dev_notification subject fallback."""
    result = _topic(subject="[jwalin-shah/repo] PR run failed: tests", body="")
    assert result == "dev"


def test_classify_thread_housing_topic():
    """Covers _topic returning 'housing' (line 111)."""
    latest = _row("leasing@example.com", body_text="Your apartment tour is scheduled")
    classification = classify_thread(latest=latest)
    assert classification.topic == "housing"


def test_classify_thread_high_urgency():
    """Covers _urgency returning 'high' (line 132)."""
    latest = _row("manager@example.com", body_text="Action required: please respond today")
    classification = classify_thread(latest=latest)
    assert classification.urgency == "high"


def test_coalesce_str_returns_empty_for_none():
    """Covers _coalesce_str returning '' for None input (line 197)."""
    assert _coalesce_str(None) == ""


def test_coalesce_str_handles_non_none_values():
    """Verify _coalesce_str stringifies non-None values correctly."""
    assert _coalesce_str("hello") == "hello"
    assert _coalesce_str(42) == "42"
