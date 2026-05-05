"""Gmail thread triage: workflow classification, action extraction, ranking, summaries."""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any, cast

from pydantic import BaseModel

from services import Contact, ThreadSummary

# ── API models (also used by inbox_server response_model) ────────────────────


class GmailThreadSummaryOut(BaseModel):
    thread_id: str
    owning_account: str
    participants: list[str]
    subject: str
    last_message_at: str
    labels: list[str]
    summary: str
    action_items: list[str]
    needs_reply: bool
    workflow: str
    message_count: int
    rank: float = 0.0
    brief: str = ""
    rich_data: dict[str, str] = {}


class ThreadBriefOut(BaseModel):
    thread_id: str
    brief: str
    rank: float
    workflow: str
    needs_reply: bool


# ── Workflow keywords / display ──────────────────────────────────────────────

WORKFLOW_KEYWORDS: dict[str, list[str]] = {
    "job_hunt": [
        "recruiter",
        "hiring",
        "offer letter",
        "interview",
        "application",
        "linkedin",
        "resume",
        "salary",
        "compensation",
        "candidate",
        "onboarding",
        "job description",
        "cover letter",
        "job offer",
    ],
    "legal": [
        "attorney",
        "legal counsel",
        "contract",
        "lawsuit",
        "court",
        "settlement",
        "nda",
        "litigation",
        "subpoena",
        "non-disclosure",
    ],
    "medical": [
        "appointment",
        "prescription",
        "insurance claim",
        "clinic",
        "hospital",
        "lab result",
        "diagnosis",
        "patient",
        "referral",
        "copay",
        "doctor",
        "medical",
    ],
    "finance": [
        "invoice",
        "payment due",
        "tax return",
        "bank statement",
        "investment",
        "reimbursement",
        "payroll",
        "billing",
        "receipt",
        "w-2",
        "1099",
    ],
    "personal_admin": [
        "dmv",
        "renew",
        "renewal",
        "license plate",
        "utility bill",
        "lease",
        "landlord",
        "visa application",
        "passport",
    ],
}

WORKFLOW_DISPLAY: dict[str, str] = {
    "job_hunt": "Job Hunt",
    "legal": "Legal",
    "medical": "Medical",
    "finance": "Finance",
    "personal_admin": "Personal Admin",
}

KIND_PREFIX: dict[str, str] = {
    "interview": "[Interview]",
    "deadline": "[Deadline]",
    "meeting": "[Meeting]",
}

_ACTION_ITEM_RE = re.compile(
    r"(?:please\s+\w[\w\s,]{5,80}|"
    r"can you\s+\w[\w\s,]{5,80}|"
    r"could you\s+\w[\w\s,]{5,80}|"
    r"(?:Review|Send|Complete|Submit|Sign|Confirm|Approve|Update|Schedule|Respond|Reply|Attach|Forward)"
    r"\s+\w[\w\s,]{3,80})"
    r"[.!?]?",
    re.IGNORECASE,
)

_RICH_PATTERNS: dict[str, dict[str, re.Pattern]] = {
    "job_hunt": {
        "company": re.compile(
            r"(?:at|from|with|@)\s+([A-Z][A-Za-z0-9&\s\-]{1,40}?)(?:\s+(?:Inc|LLC|Corp|Ltd|Co)\.?)?"
            r"(?=[,\s]|$)",
            re.IGNORECASE,
        ),
        "role": re.compile(
            r"(?:position|role|opening|opportunity|for)\s*[:\-]?\s*([A-Za-z][A-Za-z\s]{4,50}?)"
            r"(?=\s+(?:at|with|role|position)|[,\.]|$)",
            re.IGNORECASE,
        ),
    },
    "finance": {
        "amount": re.compile(r"\$\s*[\d,]+(?:\.\d{2})?"),
        "due_date": re.compile(
            r"due\s+(?:on\s+|by\s+)?([A-Za-z]+\s+\d{1,2}(?:,\s*\d{4})?|\d{1,2}[\/-]\d{1,2}(?:[\/-]\d{2,4})?)",
            re.IGNORECASE,
        ),
    },
    "legal": {
        "ref": re.compile(
            r"(?:agreement|contract|nda|case)\s+(?:no\.?\s*)?([A-Z0-9\-]{3,20})",
            re.IGNORECASE,
        ),
    },
    "medical": {
        "appointment": re.compile(
            r"(?:appointment|visit|scheduled)\s+(?:for\s+|on\s+)?([A-Za-z]+\s+\d{1,2}(?:,\s*\d{4})?|\d{1,2}[\/-]\d{1,2})",
            re.IGNORECASE,
        ),
    },
}


def classify_workflow(text: str) -> str:
    lower = text.lower()
    for workflow, keywords in WORKFLOW_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return workflow
    return ""


def extract_action_items(body: str) -> list[str]:
    matches = _ACTION_ITEM_RE.findall(body)
    seen: set[str] = set()
    items: list[str] = []
    for m in matches:
        cleaned = m.strip()[:120]
        key = cleaned.lower()[:40]
        if key not in seen and cleaned:
            seen.add(key)
            items.append(cleaned)
    return items[:5]


def extract_rich_data(workflow: str, text: str) -> dict[str, str]:
    patterns = _RICH_PATTERNS.get(workflow, {})
    result: dict[str, str] = {}
    for key, pat in patterns.items():
        m = pat.search(text)
        if m:
            result[key] = (m.group(1) if m.lastindex else m.group(0)).strip()
    return result


def rank_thread(
    last_message_at_iso: str,
    needs_reply: bool,
    has_action_items: bool,
    workflow: str,
    message_count: int,
) -> float:
    """Score a thread — higher = fresher, more actionable, has workflow."""
    try:
        last = datetime.fromisoformat(last_message_at_iso)
        days_old = max(0.0, (datetime.now() - last).total_seconds() / 86400)
        score = 2.0 * math.exp(-days_old / 7)
    except Exception:
        score = 0.0
    if needs_reply:
        score += 1.0
    if has_action_items:
        score += 0.5
    if workflow:
        score += 0.3
    if message_count > 1:
        score += 0.2
    return round(score, 4)


def contact_to_thread_summary(c: Contact) -> GmailThreadSummaryOut:
    """Build a lightweight GmailThreadSummaryOut from a Contact (no full thread fetch)."""
    wf = classify_workflow(c.snippet)
    nr = c.unread > 0
    last_iso = c.last_ts.isoformat()
    rank = rank_thread(last_iso, nr, False, wf, 0)
    sender = c.name or "Unknown"
    brief_parts = [f"{sender} \u00b7 {c.snippet[:60].rstrip()}"]
    if nr:
        brief_parts.append("[needs reply]")
    if wf:
        brief_parts.append(f"[{wf}]")
    return GmailThreadSummaryOut(
        thread_id=c.thread_id or c.id,
        owning_account=c.gmail_account,
        participants=[c.name],
        subject=c.snippet,
        last_message_at=last_iso,
        labels=[],
        summary=c.snippet,
        action_items=[],
        needs_reply=nr,
        workflow=wf,
        message_count=0,
        rank=rank,
        brief=" ".join(brief_parts),
        rich_data=extract_rich_data(wf, c.snippet),
    )


def indexed_thread_to_summary(row: dict[str, object]) -> GmailThreadSummaryOut:
    subject = str(row.get("latest_subject", "") or row.get("latest_snippet", "") or "")
    summary = str(row.get("summary", "") or subject)
    workflow = classify_workflow(f"{subject}\n{summary}")
    needs_reply = bool(row.get("needs_reply"))
    action_items = [str(row["open_loop"])] if row.get("open_loop") else []
    last_message_at = str(row.get("latest_item_at", ""))
    rank = rank_thread(
        last_message_at,
        needs_reply,
        bool(action_items),
        workflow,
        int(cast(Any, row.get("message_count", 0)) or 0),
    )
    sender = str(row.get("latest_sender", "") or "Unknown")
    brief_parts = [f"{sender} · {summary[:60].rstrip()}"]
    if needs_reply:
        brief_parts.append("[needs reply]")
    if workflow:
        brief_parts.append(f"[{workflow}]")
    rich_text = "\n".join(
        part
        for part in [
            subject,
            summary,
            str(row.get("open_loop", "")),
            str(row.get("topic", "")),
        ]
        if part
    )
    _pj = row.get("participants_json", [])
    _participants = [str(p) for p in _pj] if isinstance(_pj, list) else []
    return GmailThreadSummaryOut(
        thread_id=str(row.get("thread_id", "")),
        owning_account=str(row.get("account", "")),
        participants=_participants,
        subject=subject,
        last_message_at=last_message_at,
        labels=[],
        summary=summary,
        action_items=action_items,
        needs_reply=needs_reply,
        workflow=workflow,
        message_count=int(cast(Any, row.get("message_count", 0)) or 0),
        rank=rank,
        brief=" ".join(brief_parts),
        rich_data=extract_rich_data(workflow, rich_text),
    )


def thread_summary_to_out(ts: ThreadSummary, label_map: dict[str, str]) -> GmailThreadSummaryOut:
    labels = [label_map.get(lid, lid) for lid in ts.label_ids if not lid.startswith("CATEGORY_")]
    text = f"{ts.subject} {ts.body_text}"
    workflow = classify_workflow(text)
    needs_reply = not ts.last_sender_is_me
    action_items = extract_action_items(ts.body_text)
    last_iso = ts.last_message_at.isoformat()
    rank = rank_thread(last_iso, needs_reply, bool(action_items), workflow, ts.message_count)
    sender = ts.participants[0] if ts.participants else "Unknown"
    brief_parts = [f"{sender} \u00b7 {ts.subject[:60].rstrip()}"]
    if needs_reply:
        brief_parts.append("[needs reply]")
    if workflow:
        brief_parts.append(f"[{workflow}]")
    return GmailThreadSummaryOut(
        thread_id=ts.thread_id,
        owning_account=ts.owning_account,
        participants=ts.participants,
        subject=ts.subject,
        last_message_at=last_iso,
        labels=labels,
        summary=ts.last_message_body[:300].strip(),
        action_items=action_items,
        needs_reply=needs_reply,
        workflow=workflow,
        message_count=ts.message_count,
        rank=rank,
        brief=" ".join(brief_parts),
        rich_data=extract_rich_data(workflow, text),
    )
