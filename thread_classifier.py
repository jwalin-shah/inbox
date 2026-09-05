import math
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ThreadClassification:
    human_score: float
    noise_class: str
    topic: str
    urgency: str
    actionability: str
    needs_reply: int
    open_loop: str
    summary: str


def classify_thread(*, latest: sqlite3.Row, sender_freq: float = 0.0) -> ThreadClassification:
    subject = str(latest["subject"])
    body = str(latest["body_text"])
    sender = str(latest["sender"])

    human_score = _human_score(latest_sender=sender, latest_subject=subject, latest_body=body)
    noise_class = _noise_class(latest_sender=sender, subject=subject, body=body)
    topic = "dev" if noise_class == "dev-notification" else _topic(subject=subject, body=body)
    urgency = _urgency(subject=subject, body=body)
    actionability = _actionability(
        human_score=human_score,
        noise_class=noise_class,
        urgency=urgency,
        topic=topic,
        sender_freq=sender_freq,
    )
    # A review candidate is not evidence that the user owes the sender a reply.
    # Keep the reply queue conservative; opportunity/newsletter review belongs
    # in the review/task path until an explicit reply signal is present.
    needs_reply = int(actionability == "reply" and sender != "Me")
    open_loop = _open_loop(topic=topic, actionability=actionability, latest=latest)
    summary = _summary(latest=latest, topic=topic, actionability=actionability)

    return ThreadClassification(
        human_score=human_score,
        noise_class=noise_class,
        topic=topic,
        urgency=urgency,
        actionability=actionability,
        needs_reply=needs_reply,
        open_loop=open_loop,
        summary=summary,
    )


def sender_freq_score(reply_count: int, thread_count: int) -> float:
    if thread_count == 0:
        return 0.0
    reply_rate = reply_count / thread_count
    volume_boost = min(math.log1p(reply_count) / math.log1p(10), 1.0)
    return round(reply_rate * 0.7 + volume_boost * 0.3, 3)


def _human_score(*, latest_sender: str, latest_subject: str, latest_body: str) -> float:
    sender = latest_sender.lower()
    haystack = f"{latest_subject}\n{latest_body}".lower()
    score = 0.2
    if latest_sender and latest_sender != "Me":
        score += 0.3
    if "noreply" not in sender and "no-reply" not in sender:
        score += 0.2
    if "unsubscribe" not in haystack and "verification code" not in haystack:
        score += 0.2
    if not sender.isdigit():
        score += 0.1
    return min(score, 1.0)


def _noise_class(*, latest_sender: str, subject: str, body: str) -> str:
    haystack = f"{subject}\n{body}".lower()
    sender = latest_sender.lower()
    if _is_dev_notification(sender=sender, subject=subject):
        return "dev-notification"
    if (
        "verification code" in haystack
        or "confirmation code" in haystack
        or "security code" in haystack
        or "login code" in haystack
        or "one-time password" in haystack
        or "otp" in haystack
    ):
        return "otp"
    if "unsubscribe" in haystack or "job alert" in haystack:
        return "newsletter"
    if "appointment" in haystack or "your appt" in haystack:
        return "appointment"
    if "survey" in haystack or "thank you for your most recent visit" in haystack:
        return "survey"
    if "receipt" in haystack or "order" in haystack:
        return "receipt"
    if "login" in haystack or "security alert" in haystack:
        return "security-alert"
    if "noreply" in sender or "no-reply" in sender:
        return "automated"
    return ""


def _topic(*, subject: str, body: str) -> str:
    haystack = f"{subject}\n{body}".lower()
    if _is_dev_notification(sender="", subject=subject):
        return "dev"
    if any(token in haystack for token in ("interview", "recruit", "opportunity", "consulting")):
        return "opportunity"
    if any(token in haystack for token in ("appointment", "billing", "quest", "cvs", "health")):
        return "health-admin"
    if any(token in haystack for token in ("apartment", "tour", "lease", "housing")):
        return "housing"
    if any(
        token in haystack
        for token in (
            "login",
            "security",
            "verification",
            "confirmation code",
            "one-time password",
            "otp",
        )
    ):
        return "security"
    return "general"


def _urgency(*, subject: str, body: str) -> str:
    haystack = f"{subject}\n{body}".lower()
    if any(
        token in haystack for token in ("action required", "urgent", "today", "verify", "security")
    ):
        return "high"
    if any(token in haystack for token in ("appointment", "reply", "follow up", "opportunity")):
        return "medium"
    return "low"


def _actionability(
    *, human_score: float, noise_class: str, urgency: str, topic: str, sender_freq: float = 0.0
) -> str:
    if noise_class == "dev-notification":
        return "archive"
    if noise_class in {"otp", "receipt", "survey"}:
        return "ignore"
    if noise_class in {"newsletter", "automated"}:
        return "archive"
    if topic in {"security", "health-admin"} and urgency in {"high", "medium"}:
        return "track"
    if human_score >= 1.0 or sender_freq >= 0.5:
        return "reply"
    if topic == "opportunity":
        return "review"
    return "track"


def _open_loop(*, topic: str, actionability: str, latest: sqlite3.Row) -> str:
    if actionability == "reply":
        return f"Reply to {latest['sender'] or 'sender'}"
    if topic == "health-admin":
        return "Track appointment or billing follow-up"
    if topic == "security":
        return "Confirm whether activity was expected"
    if actionability == "review":
        return "Review opportunity details"
    return ""


def _summary(*, latest: sqlite3.Row, topic: str, actionability: str) -> str:
    title = _coalesce_str(latest["subject"]) or _coalesce_str(latest["snippet"])
    sender = _coalesce_str(latest["sender"]) or "Unknown sender"
    if title:
        return f"{sender}: {title} [{topic}/{actionability}]"
    return f"{sender} [{topic}/{actionability}]"


def _is_dev_notification(*, sender: str, subject: str) -> bool:
    sender_lower = sender.lower()
    subject_lower = subject.lower()
    if any(
        bot in sender_lower
        for bot in (
            "chatgpt-codex-connector",
            "linear-code",
            "google-labs-jules",
            "coderabbitai",
            "deepsource-io",
        )
    ):
        return True
    return "[jwalin-shah/" in subject_lower and (
        "run failed:" in subject_lower or "pr run failed:" in subject_lower
    )


def _coalesce_str(value: object) -> str:
    if value is None:
        return ""
    return str(value)
