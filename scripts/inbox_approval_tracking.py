#!/usr/bin/env python3
"""Dry-run inbox MCP approval workflow for job applications, auto-responses, and labels.

This command intentionally stops at reviewable proposals. It does not call Gmail,
Sheets, iMessage, or connector CLIs, and it has no live write path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCHEMA_VERSION = "inbox.approval_tracking.v0"
DEFAULT_NOW = "2026-06-05T12:00:00-07:00"
DEFAULT_JOB_LABEL = "Jobs"
DEFAULT_SHEET_RANGE = "Sheet1!A:F"

APPLICATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("rejection", re.compile(
        r"\b(not moving forward|decided not|unfortunately|not a fit|no ideal fit|"
        r"not proceed|not successful|not advancing|will not proceed|"
        r"regarding your application|thank you from|following up from)\b",
        re.I,
    )),
    ("paused", re.compile(r"\b(pausing our hiring|position closed|hiring paused)\b", re.I)),
    ("interview", re.compile(r"\b(interview|phone screen|next steps|scheduling|calendar invite)\b", re.I)),
    ("offer", re.compile(r"\b(offer letter|congratulations|pleased to offer)\b", re.I)),
    ("application_confirmation", re.compile(
        r"\b(application to|received your application|your application (?:at|to|for))\b",
        re.I,
    )),
)

JOB_LABEL_PATTERN = re.compile(
    r'\b("job opportunity"|interview|linkedin|hiring|recruiter|career|'
    r"application to|regarding your application|thank you from|"
    r"following up from|not moving forward|phone screen)\b",
    re.I,
)

AUTO_RESPONSE_PATTERN = re.compile(
    r"\b(can you|could you|please confirm|please reply|let me know|"
    r"available|follow up|next steps|confirm|question)\b",
    re.I,
)

LOW_SIGNAL_SENDER_PATTERN = re.compile(
    r"\b(newsletter|noreply|no-reply|notifications?|github|mailer-daemon)\b",
    re.I,
)

EXCLUDED_APPLICATION_SENDERS = re.compile(
    r"\b(luma|eventbrite|category ventures|theory ventures|founders bay|cerebral valley)\b",
    re.I,
)

STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "the",
    "to",
    "your",
}


def _now(value: str | None = None) -> datetime:
    raw = value or DEFAULT_NOW
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 1 and token not in STOPWORDS
    }


def _similar(left: str, right: str) -> bool:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens)
    return overlap / max(1, min(len(left_tokens), len(right_tokens))) >= 0.5


def _message_text(message: dict[str, Any]) -> str:
    return " ".join(
        str(message.get(key, ""))
        for key in ("subject", "title", "snippet", "body", "name")
        if message.get(key)
    )


def _sender_ref(message: dict[str, Any]) -> str:
    for key in ("reply_to", "sender", "from", "email"):
        value = str(message.get(key) or "").strip()
        if value:
            return value.lower()
    return ""


def _source_ref(item: dict[str, Any], fallback_source: str) -> str:
    source = str(item.get("source") or fallback_source)
    item_id = str(item.get("id") or item.get("thread_id") or item.get("message_id") or "")
    if not item_id:
        item_id = _stable_id("item", json.dumps(item, sort_keys=True))
    return f"{source}:{item_id}"


def _evidence_for(item: dict[str, Any], fallback_source: str) -> dict[str, Any]:
    text = _message_text(item)
    thread_id = str(item.get("thread_id") or item.get("id") or "")
    return {
        "id": _source_ref(item, fallback_source),
        "source": str(item.get("source") or fallback_source),
        "source_id": thread_id,
        "title": str(item.get("subject") or item.get("title") or item.get("name") or ""),
        "timestamp": str(item.get("timestamp") or item.get("date") or ""),
        "url": str(item.get("url") or item.get("link") or ""),
        "snippet": text[:240],
        "account": str(item.get("account") or item.get("gmail_account") or ""),
    }


def _extract_company(message: dict[str, Any]) -> str:
    explicit = str(message.get("company") or "").strip()
    if explicit:
        return explicit

    subject = str(message.get("subject") or message.get("title") or "")
    for pattern in (
        r"application (?:to|at|for) (.+?)(?:$|[,.])",
        r"update from (.+?)(?:$|[,.])",
        r"thank you from (.+?)(?:$|[,.])",
        r"following up from (.+?)(?:$|[,.])",
        r"your (.+?) application",
    ):
        match = re.search(pattern, subject, re.I)
        if match:
            return match.group(1).strip()[:80]

    sender = _sender_ref(message)
    if "@" in sender:
        domain = sender.split("@", 1)[1].split(".", 1)[0]
        if domain and domain not in {"gmail", "googlemail", "linkedin"}:
            return domain.replace("-", " ").title()

    name = str(message.get("name") or "").strip()
    if name and not LOW_SIGNAL_SENDER_PATTERN.search(name):
        return name.split()[0][:80]
    return "Unknown"


def _extract_role(message: dict[str, Any]) -> str:
    explicit = str(message.get("role") or "").strip()
    if explicit:
        return explicit

    subject = str(message.get("subject") or message.get("title") or "")
    for pattern in (
        r"application for (.+?) at ",
        r"your (.+?) application",
        r"role:\s*(.+?)(?:$|[,.])",
    ):
        match = re.search(pattern, subject, re.I)
        if match:
            return match.group(1).strip()[:120]

    snippet = str(message.get("snippet") or message.get("body") or "")
    if snippet:
        return snippet.split(".", 1)[0][:120]
    return "Unknown"


def _classify_application(message: dict[str, Any]) -> str | None:
    text = _message_text(message)
    sender = _sender_ref(message)
    if not text:
        return None
    if EXCLUDED_APPLICATION_SENDERS.search(text) or EXCLUDED_APPLICATION_SENDERS.search(sender):
        return None
    if not JOB_LABEL_PATTERN.search(text):
        return None
    for label, pattern in APPLICATION_PATTERNS:
        if pattern.search(text):
            return label
    return None


def _approval_block(*, mode: str = "explicit_review_before_write") -> dict[str, Any]:
    return {
        "required": True,
        "mode": mode,
        "server_lease_required": True,
        "mcp_confirm_required": True,
    }


def _proposal(
    *,
    kind: str,
    workflow: str,
    action_id: str,
    route: dict[str, str],
    payload: dict[str, Any],
    evidence_ids: list[str],
    notes: str = "",
) -> dict[str, Any]:
    return {
        "id": _stable_id("proposal", workflow, kind, action_id),
        "workflow": workflow,
        "kind": kind,
        "action_id": action_id,
        "route": route,
        "payload": payload,
        "approval": _approval_block(),
        "execute": False,
        "evidence_ids": evidence_ids,
        "notes": notes,
    }


def _tracker_match(
    company: str,
    role: str,
    tracker_rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    company_norm = company.lower()
    role_norm = role.lower()
    for row in tracker_rows:
        row_company = str(row.get("company") or "").lower()
        row_role = str(row.get("role") or "").lower()
        if not row_company:
            continue
        if row_company not in company_norm and company_norm not in row_company:
            continue
        if role_norm != "unknown" and row_role and not _similar(role, str(row.get("role") or "")):
            continue
        return row
    return None


def _application_items(
    messages: list[dict[str, Any]],
    tracker_rows: list[dict[str, Any]],
    sheet_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    reconciliation: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []

    for message in messages:
        outcome = _classify_application(message)
        if not outcome:
            continue
        evidence_item = _evidence_for(message, "gmail")
        evidence.append(evidence_item)
        company = _extract_company(message)
        role = _extract_role(message)
        item_id = _stable_id("application", evidence_item["id"], outcome, company, role)
        tracker_row = _tracker_match(company, role, tracker_rows)
        state = "new"
        reason = "untracked_application_signal"
        notes = ""

        if tracker_row:
            tracker_status = str(tracker_row.get("status") or "").lower()
            if tracker_status in {"rejected", "closed", "paused", "offer", "interviewing"}:
                state = "already_logged"
                reason = f"tracker_status_{tracker_status}"
            elif outcome == "rejection" and tracker_status in {"submitted", "needs_manual_form_retry"}:
                state = "status_conflict"
                reason = "rejection_email_with_nonterminal_tracker_status"
                notes = "Verify submission state before marking rejected."
            else:
                state = "already_logged"
                reason = "tracker_row_present"

        item = {
            "id": item_id,
            "workflow": "application_tracking",
            "outcome": outcome,
            "company": company,
            "role": role,
            "state": state,
            "evidence_ids": [evidence_item["id"]],
            "tracker_row_id": str(tracker_row.get("id") or "") if tracker_row else "",
        }
        items.append(item)
        reconciliation.append(
            {
                "action_id": item_id,
                "workflow": "application_tracking",
                "state": state,
                "reason": reason,
                "matched_tracker_row": str(tracker_row.get("id") or "") if tracker_row else "",
            }
        )

        if state not in {"new", "status_conflict"}:
            continue
        if not sheet_id:
            reconciliation[-1]["proposal_blocked"] = "missing_sheet_id"
            continue

        status_map = {
            "rejection": "rejected",
            "paused": "paused",
            "interview": "interviewing",
            "offer": "offer",
            "application_confirmation": "applied",
        }
        proposals.append(
            _proposal(
                kind="log_application",
                workflow="application_tracking",
                action_id=item_id,
                route={
                    "method": "POST",
                    "path": f"/sheets/{sheet_id}/values/{DEFAULT_SHEET_RANGE}/append",
                },
                payload={
                    "values": [[
                        evidence_item["timestamp"][:10] if evidence_item["timestamp"] else "",
                        company,
                        role,
                        status_map.get(outcome, outcome),
                        f"Evidence: {evidence_item['id']}; outcome={outcome}",
                    ]],
                    "account": evidence_item.get("account", ""),
                },
                evidence_ids=[evidence_item["id"]],
                notes=notes,
            )
        )

    return items, reconciliation, proposals, evidence


def _auto_response_score(message: dict[str, Any]) -> int:
    explicit = message.get("score")
    if isinstance(explicit, int):
        return explicit
    if message.get("needs_reply"):
        return 4
    text = _message_text(message)
    sender = _sender_ref(message)
    if LOW_SIGNAL_SENDER_PATTERN.search(sender) or LOW_SIGNAL_SENDER_PATTERN.search(text):
        return 1
    if _classify_application(message) == "rejection":
        return 2
    if AUTO_RESPONSE_PATTERN.search(text):
        return 4
    return 3


def _auto_response_items(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    reconciliation: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []

    for message in messages:
        score = _auto_response_score(message)
        if score < 4:
            continue
        if _classify_application(message) == "rejection":
            continue

        evidence_item = _evidence_for(message, str(message.get("source") or "gmail"))
        evidence.append(evidence_item)
        item_id = _stable_id("auto_response", evidence_item["id"], str(score))
        draft_hint = str(message.get("draft_hint") or "").strip()
        if not draft_hint:
            draft_hint = "[Draft reply required after human review]"

        item = {
            "id": item_id,
            "workflow": "auto_response_tracking",
            "score": score,
            "sender": _sender_ref(message) or str(message.get("name") or ""),
            "state": "pending_draft",
            "evidence_ids": [evidence_item["id"]],
        }
        items.append(item)
        reconciliation.append(
            {
                "action_id": item_id,
                "workflow": "auto_response_tracking",
                "state": "pending_draft",
                "reason": "high_signal_thread_needs_reply",
            }
        )

        thread_id = str(message.get("thread_id") or message.get("id") or "")
        account = str(message.get("account") or message.get("gmail_account") or "")
        source = str(message.get("source") or "gmail")
        if source == "imessage":
            route = {"method": "POST", "path": "/messages/send"}
            payload = {
                "source": "imessage",
                "conv_id": str(message.get("conv_id") or message.get("id") or ""),
                "text": draft_hint,
            }
        else:
            route = {"method": "POST", "path": "/messages/gmail/reply"}
            payload = {
                "thread_id": thread_id,
                "body": draft_hint,
                "account": account,
            }

        proposals.append(
            _proposal(
                kind="draft_reply",
                workflow="auto_response_tracking",
                action_id=item_id,
                route=route,
                payload=payload,
                evidence_ids=[evidence_item["id"]],
                notes="Auto-response draft requires explicit approval before send.",
            )
        )

    return items, reconciliation, proposals, evidence


def _message_label_names(message: dict[str, Any]) -> set[str]:
    labels = message.get("labels") or message.get("label_names") or []
    if isinstance(labels, str):
        labels = [labels]
    return {str(label) for label in labels}


def _label_job_email_items(
    messages: list[dict[str, Any]],
    labels: dict[str, str],
    job_label_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    reconciliation: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    label_id = labels.get(job_label_name, "")

    for message in messages:
        text = _message_text(message)
        if not JOB_LABEL_PATTERN.search(text):
            continue
        evidence_item = _evidence_for(message, "gmail")
        evidence.append(evidence_item)
        item_id = _stable_id("label_job", evidence_item["id"])
        existing_labels = _message_label_names(message)
        if job_label_name in existing_labels:
            state = "already_labeled"
            reason = "jobs_label_present"
        else:
            state = "needs_label"
            reason = "job_signal_without_jobs_label"

        item = {
            "id": item_id,
            "workflow": "label_job_emails",
            "label": job_label_name,
            "state": state,
            "evidence_ids": [evidence_item["id"]],
        }
        items.append(item)
        reconciliation.append(
            {
                "action_id": item_id,
                "workflow": "label_job_emails",
                "state": state,
                "reason": reason,
            }
        )

        if state != "needs_label":
            continue
        if not label_id:
            reconciliation[-1]["proposal_blocked"] = f"missing_label_id_for_{job_label_name}"
            continue

        msg_id = str(message.get("message_id") or message.get("id") or "")
        account = str(message.get("account") or message.get("gmail_account") or "")
        proposals.append(
            _proposal(
                kind="label_job_email",
                workflow="label_job_emails",
                action_id=item_id,
                route={"method": "POST", "path": "/gmail/batch-modify"},
                payload={
                    "msg_ids": [msg_id] if msg_id else [],
                    "add_label_ids": [label_id],
                    "remove_label_ids": [],
                    "account": account,
                },
                evidence_ids=[evidence_item["id"]],
                notes="Label-only proposal; does not archive or delete.",
            )
        )

    return items, reconciliation, proposals, evidence


def _source_statuses(payload: dict[str, Any]) -> list[dict[str, Any]]:
    configured = payload.get("sources")
    if isinstance(configured, list) and configured:
        return [dict(source) for source in configured if isinstance(source, dict)]

    statuses = [
        {
            "id": "gmail",
            "kind": "connector",
            "state": "configured_external_connector",
            "writes": "review_before_write_only",
        },
        {
            "id": "google_sheets",
            "kind": "connector",
            "state": "configured_external_connector",
            "writes": "review_before_write_only",
        },
    ]
    for connector_id, binary in (("gog", "gog"), ("imsg", "imsg"), ("wacli", "wacli")):
        statuses.append(
            {
                "id": connector_id,
                "kind": "future_cli",
                "state": "installed" if shutil.which(binary) else "not_installed",
                "writes": "deferred_until_explicit_approval_adapter",
            }
        )
    return statuses


def build_report(
    payload: dict[str, Any],
    *,
    now: str | None = None,
    workflows: set[str] | None = None,
) -> dict[str, Any]:
    generated_at = _now(now).astimezone(UTC).isoformat()
    enabled = workflows or {
        "application_tracking",
        "auto_response_tracking",
        "label_job_emails",
    }
    messages = list(payload.get("gmail") or payload.get("messages") or payload.get("inbox") or [])
    tracker_rows = list(payload.get("tracker_rows") or [])
    labels = dict(payload.get("labels") or {})
    sheet_id = str(payload.get("sheet_id") or payload.get("job_tracker_sheet_id") or "")
    job_label_name = str(payload.get("job_label") or DEFAULT_JOB_LABEL)

    workflow_reports: dict[str, Any] = {}
    all_items: list[dict[str, Any]] = []
    all_reconciliation: list[dict[str, Any]] = []
    all_proposals: list[dict[str, Any]] = []
    all_evidence: list[dict[str, Any]] = []

    if "application_tracking" in enabled:
        items, reconciliation, proposals, evidence = _application_items(
            messages,
            tracker_rows,
            sheet_id,
        )
        workflow_reports["application_tracking"] = {
            "items": len(items),
            "proposals": len(proposals),
            "new_or_conflict": sum(1 for item in items if item["state"] in {"new", "status_conflict"}),
        }
        all_items.extend(items)
        all_reconciliation.extend(reconciliation)
        all_proposals.extend(proposals)
        all_evidence.extend(evidence)

    if "auto_response_tracking" in enabled:
        items, reconciliation, proposals, evidence = _auto_response_items(messages)
        workflow_reports["auto_response_tracking"] = {
            "items": len(items),
            "proposals": len(proposals),
            "pending_drafts": len(items),
        }
        all_items.extend(items)
        all_reconciliation.extend(reconciliation)
        all_proposals.extend(proposals)
        all_evidence.extend(evidence)

    if "label_job_emails" in enabled:
        items, reconciliation, proposals, evidence = _label_job_email_items(
            messages,
            labels,
            job_label_name,
        )
        workflow_reports["label_job_emails"] = {
            "items": len(items),
            "proposals": len(proposals),
            "needs_label": sum(1 for item in items if item["state"] == "needs_label"),
        }
        all_items.extend(items)
        all_reconciliation.extend(reconciliation)
        all_proposals.extend(proposals)
        all_evidence.extend(evidence)

    deduped_evidence = {item["id"]: item for item in all_evidence}

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "dry_run": True,
        "invariants": {
            "provider_calls": False,
            "connector_binaries_executed": False,
            "external_mutations": False,
            "review_before_write": True,
        },
        "sources": _source_statuses(payload),
        "workflows": workflow_reports,
        "summary": {
            "messages_scanned": len(messages),
            "tracked_items": len(all_items),
            "proposed_changes": len(all_proposals),
            "application_items": workflow_reports.get("application_tracking", {}).get("items", 0),
            "auto_response_items": workflow_reports.get("auto_response_tracking", {}).get("items", 0),
            "label_job_items": workflow_reports.get("label_job_emails", {}).get("items", 0),
        },
        "tracked_items": all_items,
        "reconciliation": all_reconciliation,
        "proposed_changes": all_proposals,
        "evidence": list(deduped_evidence.values()),
    }


def load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def format_text(report: dict[str, Any]) -> str:
    lines = [
        "Inbox MCP Approval Tracking v0",
        f"Dry run: {report['dry_run']} | external mutations: {report['invariants']['external_mutations']}",
        (
            f"Messages scanned: {report['summary']['messages_scanned']} | "
            f"Tracked items: {report['summary']['tracked_items']} | "
            f"Proposed changes: {report['summary']['proposed_changes']}"
        ),
        "",
        "Workflows:",
    ]
    for workflow, stats in report["workflows"].items():
        lines.append(f"  {workflow}: {json.dumps(stats, sort_keys=True)}")

    lines.extend(["", "Sources:"])
    for source in report["sources"]:
        lines.append(f"  {source['id']}: {source['state']}")

    lines.extend(["", "Tracked items:"])
    if not report["tracked_items"]:
        lines.append("  none")
    for item in report["tracked_items"]:
        label = item.get("outcome") or item.get("label") or item.get("sender") or item.get("workflow")
        lines.append(f"  - [{item['state']}] {item['workflow']} :: {label} ({', '.join(item['evidence_ids'])})")

    lines.extend(["", "Review-before-write proposals:"])
    if not report["proposed_changes"]:
        lines.append("  none")
    for proposal in report["proposed_changes"]:
        route = proposal["route"]
        lines.append(
            f"  - {proposal['workflow']} :: {proposal['kind']} via {route['method']} {route['path']} "
            f"approval_required={proposal['approval']['required']} execute={proposal['execute']}"
        )
        lines.append(f"    payload: {json.dumps(proposal['payload'], sort_keys=True)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize application, auto-response, and job-label workflows "
            "and emit reviewable MCP approval proposals."
        )
    )
    parser.add_argument("--fixture", type=Path, help="Local JSON fixture to summarize.")
    parser.add_argument("--now", default=None, help="Stable ISO timestamp for generated_at.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    parser.add_argument(
        "--workflow",
        action="append",
        choices=["application_tracking", "auto_response_tracking", "label_job_emails"],
        help="Limit output to one workflow (repeatable).",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Reserved for a future human-approved adapter; v0 refuses execution.",
    )
    args = parser.parse_args(argv)

    if args.execute:
        print(
            "Refusing --execute: v0 only emits dry-run proposals requiring explicit review.",
            file=sys.stderr,
        )
        return 2

    payload = load_fixture(args.fixture) if args.fixture else {}
    workflows = set(args.workflow) if args.workflow else None
    report = build_report(payload, now=args.now, workflows=workflows)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
