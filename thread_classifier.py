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
    haystack = f"{subject}\n{body}"

    human_score = _human_score(latest_sender=sender, latest_subject=subject, latest_body=body)
    noise_class = _noise_class(latest_sender=sender, subject=subject, body=body)
    topic = _topic(subject=subject, body=body)
    urgency = _urgency(subject=subject, body=body)
    direct_request = _has_direct_request(haystack)
    actionability = _actionability(
        human_score=human_score,
        noise_class=noise_class,
        urgency=urgency,
        topic=topic,
        latest_sender=sender,
        direct_request=direct_request,
        sender_freq=sender_freq,
    )
    needs_reply = int(actionability in {"reply", "review"} and sender != "Me")
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
    score = 0.15
    if latest_sender and latest_sender != "Me":
        score += 0.25
    if "noreply" not in sender and "no-reply" not in sender:
        score += 0.2
    if "unsubscribe" not in haystack and "verification code" not in haystack:
        score += 0.15
    if not sender.isdigit():
        score += 0.1
    return min(score, 1.0)


def _noise_class(*, latest_sender: str, subject: str, body: str) -> str:
    haystack = f"{subject}\n{body}".lower()
    sender = latest_sender.lower()
    if "verification code" in haystack or "otp" in haystack:
        return "otp"
    if any(
        token in haystack
        for token in (
            "unsubscribe",
            "job alert",
            "manage preferences",
            "view in browser",
            "weekly digest",
            "daily digest",
            "newsletter",
            "promotion",
            "limited time",
            "webinar",
        )
    ):
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
    if _is_low_value_ack(haystack):
        return "low-value-ack"
    return ""


def _topic(*, subject: str, body: str) -> str:
    haystack = f"{subject}\n{body}".lower()
    if any(token in haystack for token in ("interview", "recruit", "opportunity", "consulting")):
        return "opportunity"
    if any(token in haystack for token in ("appointment", "billing", "quest", "cvs", "health")):
        return "health-admin"
    if any(token in haystack for token in ("apartment", "tour", "lease", "housing")):
        return "housing"
    if any(token in haystack for token in ("login", "security", "verification")):
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
    *,
    human_score: float,
    noise_class: str,
    urgency: str,
    topic: str,
    latest_sender: str,
    direct_request: bool,
    sender_freq: float = 0.0,
) -> str:
    if noise_class in {"otp", "receipt", "survey"}:
        return "ignore"
    if noise_class in {"newsletter", "automated", "low-value-ack"}:
        return "archive"
    if latest_sender == "Me":
        return "track" if topic in {"security", "health-admin", "opportunity"} else "archive"
    if topic in {"security", "health-admin"} and urgency in {"high", "medium"}:
        return "track"
    if direct_request and human_score >= 0.6:
        return "reply"
    if sender_freq >= 0.5 and human_score >= 0.6:
        return "reply"
    if topic == "opportunity":
        return "review"
    if urgency == "high" and human_score >= 0.6:
        return "review"
    return "track"


def _has_direct_request(text: str) -> bool:
    haystack = text.lower()
    request_tokens = (
        "can you",
        "could you",
        "would you",
        "please",
        "let me know",
        "confirm",
        "reply",
        "respond",
        "send",
        "review",
        "schedule",
        "available",
        "availability",
        "open to",
    )
    return any(token in haystack for token in request_tokens)


def _is_low_value_ack(haystack: str) -> bool:
    compact = " ".join(haystack.split())
    if len(compact) > 120:
        return False
    if _has_direct_request(compact):
        return False
    return any(
        phrase in compact
        for phrase in (
            "thanks",
            "thank you",
            "got it",
            "sounds good",
            "looks good",
            "ok",
            "okay",
        )
    )


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


def _coalesce_str(value: object) -> str:
    if value is None:
        return ""
    return str(value)
