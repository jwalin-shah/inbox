#!/usr/bin/env python3
"""Learn contact importance and reply timing from the local iMessage history."""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contacts import ContactBook  # noqa: E402
from services import IMSG_DB  # noqa: E402

SCHEMA = "inbox.imessage_learning.v0"
DEFAULT_LOOKBACK_DAYS = 365
DEFAULT_LIMIT = 25
LOCAL_TIMEZONE = ZoneInfo("America/Los_Angeles")

WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]{2,}")
URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
PHONE_RE = re.compile(r"^\+?\d[\d\s().-]{6,}$")
NOISE_RE = re.compile(
    r"(verification code|security code|one[- ]time|do not reply|unsubscribe|"
    r"appointment reminder|your otp|recruiting department|remote job openings)",
    re.IGNORECASE,
)
STOPWORDS = frozenset(
    {
        "about",
        "after",
        "again",
        "also",
        "and",
        "are",
        "been",
        "but",
        "can",
        "come",
        "could",
        "did",
        "doing",
        "for",
        "from",
        "get",
        "going",
        "good",
        "got",
        "had",
        "has",
        "have",
        "hey",
        "how",
        "just",
        "know",
        "like",
        "lol",
        "lmao",
        "make",
        "maybe",
        "more",
        "not",
        "now",
        "okay",
        "one",
        "our",
        "out",
        "really",
        "see",
        "she",
        "should",
        "some",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "they",
        "think",
        "this",
        "too",
        "want",
        "was",
        "way",
        "what",
        "when",
        "where",
        "which",
        "who",
        "will",
        "with",
        "would",
        "yeah",
        "yes",
        "you",
        "your",
    }
)
TOPIC_KEYWORDS: dict[str, frozenset[str]] = {
    "plans & social": frozenset(
        {"dinner", "drinks", "hang", "lunch", "meet", "party", "plans", "restaurant", "weekend"}
    ),
    "work & career": frozenset(
        {"application", "career", "company", "interview", "job", "meeting", "offer", "referral", "work"}
    ),
    "family": frozenset({"aunt", "birthday", "cousin", "dad", "family", "mom", "parents", "uncle"}),
    "travel": frozenset(
        {"airport", "drive", "flight", "hotel", "park", "road", "trip", "vacation", "visit"}
    ),
    "health": frozenset(
        {"appointment", "doctor", "health", "hospital", "insurance", "medicine", "therapy"}
    ),
    "food": frozenset(
        {"breakfast", "cook", "dinner", "eat", "food", "lunch", "pizza", "restaurant"}
    ),
    "sports & games": frozenset(
        {"basketball", "board", "fantasy", "football", "game", "golf", "play", "team"}
    ),
    "tech": frozenset(
        {"ai", "app", "code", "github", "iphone", "laptop", "model", "software", "tech"}
    ),
}

MESSAGE_SQL = """
SELECT
    cmj.chat_id,
    c.guid,
    c.display_name,
    m.text,
    m.date,
    m.is_from_me
FROM message m
JOIN chat_message_join cmj ON cmj.message_id = m.rowid
JOIN chat c ON c.rowid = cmj.chat_id
WHERE m.date >= ?
  AND m.item_type = 0
  AND m.is_system_message = 0
  AND m.associated_message_type = 0
  AND COALESCE(m.is_spam, 0) = 0
ORDER BY cmj.chat_id, m.date, m.rowid
"""


@dataclass(frozen=True)
class Message:
    chat_id: int
    text: str
    timestamp: datetime
    is_from_me: bool


@dataclass
class ContactLearning:
    chat_id: str
    contact: str
    is_group: bool
    message_count: int
    my_messages: int
    their_messages: int
    active_days: int
    last_contact: str
    days_since_contact: float
    needs_reply: bool
    pending_hours: float | None
    my_median_reply_hours: float | None
    their_median_reply_hours: float | None
    my_response_rate: float
    their_response_rate: float
    my_initiation_rate: float
    preferred_contact_signal: float
    topics: list[str]
    top_terms: list[str]
    optimal_reply_window: str
    reply_window_source: str
    suggested_reply_timing: str
    importance_score: float
    importance_reasons: list[str]
    evidence_thread: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _apple_ns(dt: datetime) -> int:
    return int((dt.timestamp() - 978307200) * 1_000_000_000)


def _message_timestamp(value: int) -> datetime:
    seconds = value / 1_000_000_000 + 978307200
    return datetime.fromtimestamp(seconds, tz=UTC)


def _clean_text(text: str | None) -> str:
    return (text or "").replace("\ufffc", " ").strip()


def _percent(value: float) -> float:
    return round(value * 100, 1)


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def _format_latency(value: float | None) -> str:
    if value is None:
        return "insufficient data"
    if value == 0:
        return "<0.1h"
    return f"{value:g}h"


def _members(conn: sqlite3.Connection, chat_id: int) -> list[str]:
    return [
        row[0]
        for row in conn.execute(
            """
            SELECT h.id
            FROM handle h
            JOIN chat_handle_join chj ON chj.handle_id = h.rowid
            WHERE chj.chat_id = ?
            ORDER BY h.id
            """,
            (chat_id,),
        )
    ]


def _contact_name(
    display_name: str | None,
    guid: str,
    member_ids: list[str],
    book: ContactBook,
) -> str:
    if display_name and display_name.strip():
        return display_name.strip()
    names = [book.resolve(member) or member for member in member_ids]
    if len(names) > 1:
        shown = ", ".join(names[:3])
        return shown if len(names) <= 3 else f"{shown} +{len(names) - 3}"
    if names:
        return names[0]
    identifier = guid.split(";")[-1]
    return book.resolve(identifier) or identifier


def _looks_automated(name: str, messages: list[Message]) -> bool:
    if PHONE_RE.match(name) and len(re.sub(r"\D", "", name)) <= 6:
        return True
    sample = " ".join(message.text for message in messages[-8:] if not message.is_from_me)
    if NOISE_RE.search(sample):
        return True
    return len(messages) >= 3 and not any(message.is_from_me for message in messages)


def _direction_runs(messages: list[Message]) -> list[list[Message]]:
    runs: list[list[Message]] = []
    for message in messages:
        if not runs or runs[-1][-1].is_from_me != message.is_from_me:
            runs.append([message])
        else:
            runs[-1].append(message)
    return runs


def _response_patterns(messages: list[Message]) -> dict[str, Any]:
    runs = _direction_runs(messages)
    my_latencies: list[float] = []
    their_latencies: list[float] = []
    incoming_turns = sum(not run[0].is_from_me for run in runs)
    outgoing_turns = sum(run[0].is_from_me for run in runs)
    my_responses = 0
    their_responses = 0

    for current, following in zip(runs, runs[1:], strict=False):
        hours = (following[0].timestamp - current[-1].timestamp).total_seconds() / 3600
        if hours < 0:
            continue
        if not current[0].is_from_me and following[0].is_from_me:
            my_responses += 1
            my_latencies.append(hours)
        elif current[0].is_from_me and not following[0].is_from_me:
            their_responses += 1
            their_latencies.append(hours)

    initiated = 0
    conversations = 0
    previous: Message | None = None
    for message in messages:
        if previous is None or (message.timestamp - previous.timestamp).total_seconds() >= 24 * 3600:
            conversations += 1
            initiated += int(message.is_from_me)
        previous = message

    return {
        "my_latencies": my_latencies,
        "their_latencies": their_latencies,
        "my_response_rate": my_responses / incoming_turns if incoming_turns else 0.0,
        "their_response_rate": their_responses / outgoing_turns if outgoing_turns else 0.0,
        "my_initiation_rate": initiated / conversations if conversations else 0.0,
    }


def _topic_signals(messages: list[Message]) -> tuple[list[str], list[str]]:
    words: Counter[str] = Counter()
    topic_counts: Counter[str] = Counter()
    for message in messages:
        for raw_word in WORD_RE.findall(message.text.lower()):
            word = raw_word.strip("'-")
            if word in STOPWORDS or len(word) < 3:
                continue
            words[word] += 1
            for topic, keywords in TOPIC_KEYWORDS.items():
                if word in keywords:
                    topic_counts[topic] += 1
        if URL_RE.search(message.text):
            topic_counts["links & media"] += 1
    topics = [name for name, _ in topic_counts.most_common(3)]
    return topics or ["general conversation"], [word for word, _ in words.most_common(5)]


def _best_window(hours: Iterable[int]) -> tuple[int, int] | None:
    histogram = Counter(hours)
    if sum(histogram.values()) < 3:
        return None
    best_start = max(range(24), key=lambda start: sum(histogram[(start + step) % 24] for step in range(3)))
    return best_start, (best_start + 3) % 24


def _format_hour(hour: int) -> str:
    suffix = "AM" if hour < 12 else "PM"
    shown = hour % 12 or 12
    return f"{shown} {suffix}"


def _format_window(window: tuple[int, int]) -> str:
    return f"{_format_hour(window[0])}–{_format_hour(window[1])}"


def _suggest_timing(
    *,
    needs_reply: bool,
    pending_hours: float | None,
    median_reply_hours: float | None,
    window: tuple[int, int],
    now: datetime,
) -> str:
    if not needs_reply:
        return "No reply due"
    typical = median_reply_hours if median_reply_hours is not None else 12.0
    if pending_hours is not None and pending_hours >= max(typical, 24.0):
        return "Reply now (past your usual response time)"
    local_now = now.astimezone(LOCAL_TIMEZONE)
    start = window[0]
    if start <= local_now.hour < start + 3:
        return "Reply now (inside preferred window)"
    if local_now.hour < start:
        return f"Reply today around {_format_hour(start)}"
    return f"Reply tomorrow around {_format_hour(start)}"


def _importance(
    *,
    message_count: int,
    days_since: float,
    my_share: float,
    initiation_rate: float,
    my_response_rate: float,
    their_response_rate: float,
    needs_reply: bool,
    pending_hours: float | None,
) -> tuple[float, float, list[str]]:
    engagement = min(30.0, 8.0 * math.log1p(message_count))
    recency = 25.0 / (1.0 + days_since / 30.0)
    reciprocity = 20.0 * (1.0 - min(1.0, abs(0.5 - my_share) * 2.0))
    preference = 15.0 * min(
        1.0,
        0.45 * initiation_rate + 0.3 * my_response_rate + 0.25 * their_response_rate,
    )
    urgency = 0.0
    if needs_reply:
        urgency = min(10.0, 4.0 + math.log1p(max(0.0, pending_hours or 0.0)) * 1.5)
    score = round(min(100.0, engagement + recency + reciprocity + preference + urgency), 1)
    preference_signal = round(preference / 15.0 * 100, 1)

    reasons: list[str] = []
    if engagement >= 22:
        reasons.append("high message volume")
    if recency >= 18:
        reasons.append("recently active")
    if reciprocity >= 15:
        reasons.append("balanced back-and-forth")
    if preference >= 9:
        reasons.append("you often initiate or respond")
    if needs_reply:
        reasons.append("reply currently due")
    return score, preference_signal, reasons or ["limited interaction evidence"]


def learn_imessage_contacts(
    *,
    now: datetime | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    limit: int = DEFAULT_LIMIT,
    db_path: Path = IMSG_DB,
    book: ContactBook | None = None,
) -> list[ContactLearning]:
    """Build ranked, read-only contact learning from local iMessage history."""
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    if not db_path.exists():
        return []

    contact_book = book or ContactBook()
    contact_book.load()
    cutoff = _apple_ns(reference) - lookback_days * 24 * 3600 * 1_000_000_000

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(MESSAGE_SQL, (cutoff,)).fetchall()
        grouped: dict[int, list[Message]] = defaultdict(list)
        metadata: dict[int, tuple[str, str | None]] = {}
        for chat_id, guid, display_name, text, date, is_from_me in rows:
            body = _clean_text(text)
            if not body:
                continue
            grouped[chat_id].append(
                Message(
                    chat_id=chat_id,
                    text=body,
                    timestamp=_message_timestamp(date),
                    is_from_me=bool(is_from_me),
                )
            )
            metadata[chat_id] = (guid, display_name)

        global_hours = [
            message.timestamp.astimezone(LOCAL_TIMEZONE).hour
            for messages in grouped.values()
            for message in messages
            if message.is_from_me
        ]
        global_window = _best_window(global_hours) or (18, 21)
        results: list[ContactLearning] = []

        for chat_id, messages in grouped.items():
            guid, display_name = metadata[chat_id]
            member_ids = _members(conn, chat_id)
            name = _contact_name(display_name, guid, member_ids, contact_book)
            if _looks_automated(name, messages):
                continue

            pattern = _response_patterns(messages)
            my_messages = sum(message.is_from_me for message in messages)
            their_messages = len(messages) - my_messages
            if not my_messages or not their_messages:
                continue

            last_message = messages[-1]
            days_since = max(
                0.0, (reference - last_message.timestamp).total_seconds() / (24 * 3600)
            )
            needs_reply = not last_message.is_from_me
            pending_hours = round(days_since * 24, 1) if needs_reply else None
            topics, top_terms = _topic_signals(messages)
            my_share = my_messages / len(messages)
            score, preference_signal, reasons = _importance(
                message_count=len(messages),
                days_since=days_since,
                my_share=my_share,
                initiation_rate=pattern["my_initiation_rate"],
                my_response_rate=pattern["my_response_rate"],
                their_response_rate=pattern["their_response_rate"],
                needs_reply=needs_reply,
                pending_hours=pending_hours,
            )

            contact_hours = [
                message.timestamp.astimezone(LOCAL_TIMEZONE).hour
                for message in messages
                if message.is_from_me
            ]
            contact_window = _best_window(contact_hours)
            window = contact_window or global_window
            median_reply = _median(pattern["my_latencies"])
            results.append(
                ContactLearning(
                    chat_id=str(chat_id),
                    contact=name,
                    is_group=len(member_ids) > 1,
                    message_count=len(messages),
                    my_messages=my_messages,
                    their_messages=their_messages,
                    active_days=len({message.timestamp.date() for message in messages}),
                    last_contact=last_message.timestamp.astimezone(LOCAL_TIMEZONE).isoformat(
                        timespec="minutes"
                    ),
                    days_since_contact=round(days_since, 1),
                    needs_reply=needs_reply,
                    pending_hours=pending_hours,
                    my_median_reply_hours=median_reply,
                    their_median_reply_hours=_median(pattern["their_latencies"]),
                    my_response_rate=_percent(pattern["my_response_rate"]),
                    their_response_rate=_percent(pattern["their_response_rate"]),
                    my_initiation_rate=_percent(pattern["my_initiation_rate"]),
                    preferred_contact_signal=preference_signal,
                    topics=topics,
                    top_terms=top_terms,
                    optimal_reply_window=_format_window(window),
                    reply_window_source="contact history" if contact_window else "overall history",
                    suggested_reply_timing=_suggest_timing(
                        needs_reply=needs_reply,
                        pending_hours=pending_hours,
                        median_reply_hours=median_reply,
                        window=window,
                        now=reference,
                    ),
                    importance_score=score,
                    importance_reasons=reasons,
                    evidence_thread=f"GET /messages/imessage/{chat_id}",
                )
            )
    finally:
        conn.close()

    results.sort(
        key=lambda row: (row.importance_score, row.needs_reply, row.message_count),
        reverse=True,
    )
    return results[:limit]


def format_markdown(
    contacts: list[ContactLearning],
    *,
    generated_at: datetime,
    lookback_days: int,
) -> str:
    reply_due = sum(contact.needs_reply for contact in contacts)
    lines = [
        "# iMessage Learning Demo",
        "",
        f"Generated: {generated_at.astimezone(LOCAL_TIMEZONE).isoformat(timespec='seconds')}",
        "",
        (
            f"Read-only analysis of the last {lookback_days} days. Importance combines message "
            "volume (30%), recency (25%), reciprocity (20%), inferred preference (15%), "
            "and reply urgency (10%)."
        ),
        "",
        "## Summary",
        "",
        f"- Ranked contacts: **{len(contacts)}**",
        f"- Important contacts currently awaiting a reply: **{reply_due}**",
        "- Reply windows use each contact's outgoing-message history when at least 3 samples exist.",
        "",
        "## Contact Importance + Reply Windows",
        "",
        "| Score | Contact | Messages | Reply pattern | Topics | Optimal window | Suggested timing |",
        "|------:|---------|---------:|---------------|--------|----------------|------------------|",
    ]
    for contact in contacts:
        my_latency = f"{_format_latency(contact.my_median_reply_hours)} median"
        topics = ", ".join(contact.topics)
        source = "contact" if contact.reply_window_source == "contact history" else "overall"
        lines.append(
            f"| **{contact.importance_score:.1f}** | **{contact.contact}** | "
            f"{contact.message_count} | {my_latency}; {contact.my_response_rate:.0f}% response | "
            f"{topics} | {contact.optimal_reply_window} ({source}) | "
            f"{contact.suggested_reply_timing} |"
        )

    lines.extend(["", "## Response Pattern Detail", ""])
    for contact in contacts[:10]:
        reasons = ", ".join(contact.importance_reasons)
        terms = ", ".join(contact.top_terms) or "none"
        lines.extend(
            [
                f"### {contact.contact} — {contact.importance_score:.1f}",
                "",
                (
                    f"- Pattern: you sent {contact.my_messages}/{contact.message_count} messages; "
                    f"you initiated {contact.my_initiation_rate:.0f}% of conversation sessions."
                ),
                (
                    f"- Latency: your median {_format_latency(contact.my_median_reply_hours)}; "
                    f"their median {_format_latency(contact.their_median_reply_hours)}."
                ),
                (
                    f"- Preference signal: {contact.preferred_contact_signal:.1f}/100; "
                    f"importance reasons: {reasons}."
                ),
                f"- Topic terms: {terms}.",
                f"- Timing: {contact.suggested_reply_timing}; `{contact.evidence_thread}`.",
                "",
            ]
        )
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Learn iMessage contact importance and optimal reply timing."
    )
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", metavar="PATH")
    parser.add_argument("--now", help="ISO timestamp override for deterministic output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    now = (
        datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        if args.now
        else datetime.now(UTC)
    )
    contacts = learn_imessage_contacts(
        now=now,
        lookback_days=args.lookback_days,
        limit=args.limit,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "generated_at": now.isoformat(),
                    "contacts": [contact.to_dict() for contact in contacts],
                },
                indent=2,
            )
        )
    else:
        print(format_markdown(contacts, generated_at=now, lookback_days=args.lookback_days))

    if args.markdown:
        path = Path(args.markdown)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            format_markdown(contacts, generated_at=now, lookback_days=args.lookback_days),
            encoding="utf-8",
        )
        print(f"\nWrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
