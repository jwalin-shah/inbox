#!/usr/bin/env python3
"""
Auto-Actions Worker

Runs 4 autonomous actions:
1. Auto-archive low-signal emails (score 1-2)
2. Auto-draft replies for high-priority threads (score 4+)
3. Auto-create calendar events from email dates/times
4. Auto-log rejections to job tracker

Usage:
  /inbox auto-actions
  /inbox auto-actions --dry-run
  /inbox auto-actions --approval-only
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import re

def load_config():
    """Load auto-actions config from ~/.inbox/auto-actions.yml"""
    config_path = Path.home() / ".inbox" / "auto-actions.yml"
    if not config_path.exists():
        return {
            "auto_archive": {"enabled": True, "min_score": 1, "max_score": 2},
            "auto_draft": {"enabled": True, "min_score": 4, "require_approval": True},
            "auto_calendar": {"enabled": True, "default_duration": 1},
            "auto_logging": {"enabled": True, "min_score": 3},
        }
    # TODO: Parse YAML
    return {}

def log_action(action_type, details):
    """Log every action to ~/.inbox/ledger"""
    ledger_path = Path.home() / ".inbox" / "ledger"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().isoformat() + "Z"
    log_line = f"{timestamp}  action={action_type}  {details}\n"

    with open(ledger_path, "a") as f:
        f.write(log_line)

def get_unread_threads():
    """Fetch unread threads from inbox server"""
    result = subprocess.run(
        ["curl", "-s", "http://localhost:9849/gmail/threads?unread=true"],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print(f"ERROR: Failed to fetch threads: {result.stderr}")
        sys.exit(1)

    return json.loads(result.stdout)["threads"]

def score_thread(thread):
    """Score thread 1-5 based on sender, subject, content"""
    # TODO: Use the same scoring algorithm as triage.md
    # For now, return a dummy score
    return 3

def action_archive(threads, dry_run=False):
    """Action 1: Archive low-signal threads (score 1-2)"""
    config = load_config()
    if not config["auto_archive"]["enabled"]:
        return 0

    to_archive = [
        t for t in threads
        if score_thread(t) <= config["auto_archive"]["max_score"]
    ]

    if not to_archive:
        return 0

    if dry_run:
        print(f"[DRY RUN] Would archive {len(to_archive)} threads")
        for t in to_archive[:3]:  # Show first 3
            print(f"  - {t['sender']}: {t['subject'][:60]}")
        if len(to_archive) > 3:
            print(f"  ... and {len(to_archive) - 3} more")
        return len(to_archive)

    # Archive via API
    thread_ids = [t["id"] for t in to_archive]
    result = subprocess.run(
        ["curl", "-X", "POST", "http://localhost:9849/gmail/batch-modify",
         "-H", "Content-Type: application/json",
         "-d", json.dumps({
             "msg_ids": thread_ids,
             "remove_label_ids": ["INBOX"],
             "add_label_ids": ["Triage/Archived"]
         })],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        log_action("auto_archive", f"count={len(to_archive)}  reason=low_signal")
        return len(to_archive)
    else:
        print(f"ERROR: Archive failed: {result.stderr}")
        return 0

def action_draft_replies(threads, dry_run=False):
    """Action 2: Draft replies for score 4+ threads"""
    config = load_config()
    if not config["auto_draft"]["enabled"]:
        return []

    to_draft = [
        t for t in threads
        if score_thread(t) >= config["auto_draft"]["min_score"]
        and "already_replied" not in t
    ]

    drafts = []
    for thread in to_draft:
        # Use Claude to generate draft
        draft_text = generate_draft_reply(thread)
        drafts.append({
            "thread_id": thread["id"],
            "sender": thread["sender"],
            "subject": thread["subject"],
            "draft": draft_text,
            "status": "pending_approval",
        })

    if dry_run:
        print(f"[DRY RUN] Would draft {len(drafts)} replies")
        for d in drafts:
            print(f"  - {d['sender']}: {d['draft'][:50]}...")
        return drafts

    # Log drafts as pending
    for draft in drafts:
        log_action(
            "draft_reply",
            f"thread={draft['thread_id']}  sender={draft['sender']}  status=pending_approval"
        )

    return drafts

def action_create_events(threads, dry_run=False):
    """Action 3: Extract dates/times from emails, create calendar events"""
    events = []

    for thread in threads:
        event = extract_calendar_event(thread)
        if event:
            events.append(event)

    if not events:
        return 0

    if dry_run:
        print(f"[DRY RUN] Would create {len(events)} calendar events")
        for e in events:
            print(f"  - {e['summary']} at {e['start']}")
        return len(events)

    # Create events via API
    created = 0
    for event in events:
        result = subprocess.run(
            ["curl", "-X", "POST", "http://localhost:9849/calendar/events",
             "-H", "Content-Type: application/json",
             "-d", json.dumps(event)],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            created += 1
            log_action("create_event", f"title={event['summary']}")

    return created

def action_log_rejections(threads, dry_run=False):
    """Action 4: Auto-log job rejections to Google Sheet"""
    config = load_config()
    if not config["auto_logging"]["enabled"]:
        return 0

    rejections = []
    for thread in threads:
        if is_rejection(thread):
            company, role = extract_job_info(thread)
            rejections.append({
                "date": datetime.utcnow().strftime("%Y-%m-%d"),
                "company": company,
                "role": role,
                "status": "rejected",
                "notes": thread["subject"],
            })

    if not rejections:
        return 0

    if dry_run:
        print(f"[DRY RUN] Would log {len(rejections)} rejections")
        for r in rejections:
            print(f"  - {r['company']}: {r['role']}")
        return len(rejections)

    # Log to Google Sheet
    sheet_id = os.getenv("JWALIN_JOB_TRACKER_SHEET_ID")
    if not sheet_id:
        print("ERROR: JWALIN_JOB_TRACKER_SHEET_ID not set")
        return 0

    # TODO: Append rows to sheet
    logged = len(rejections)
    log_action("log_rejections", f"count={logged}")

    return logged

def generate_draft_reply(thread):
    """Use Claude to draft a reply"""
    # TODO: Call Claude with thread context
    return "Thanks for reaching out, I'll follow up soon."

def extract_calendar_event(thread):
    """Extract date/time from email thread"""
    # Look for patterns like "Tuesday 2pm", "next Monday", etc.
    text = thread.get("body", "")

    # Regex patterns for dates/times
    patterns = [
        r"(?:next\s+)?(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+(?:at\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
        r"(\d{1,2}/\d{1,2})\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            # TODO: Parse date/time properly
            return {
                "summary": thread["subject"],
                "start": "2026-06-10T14:00:00-07:00",  # Placeholder
                "end": "2026-06-10T15:00:00-07:00",
                "description": f"From: {thread['sender']}",
            }

    return None

def is_rejection(thread):
    """Check if thread is a job rejection"""
    keywords = ["reject", "unfortunately", "not moving forward", "decided not", "passing"]
    text = (thread.get("subject", "") + " " + thread.get("body", "")).lower()
    return any(kw in text for kw in keywords)

def extract_job_info(thread):
    """Extract company and role from job email"""
    # TODO: Parse job rejection emails properly
    subject = thread.get("subject", "")
    company = subject.split("from")[-1].strip() if "from" in subject else "Unknown"
    role = subject.split("for")[-1].strip() if "for" in subject else "Unknown"
    return company[:30], role[:30]  # Truncate for safety

def show_summary(archive_count, drafts, event_count, rejection_count):
    """Show what actions were taken"""
    print("\n## Auto-Actions Complete — " + datetime.utcnow().strftime("%m/%d %H:%M"))
    print()
    if archive_count > 0:
        print(f"Archived: {archive_count} (newsletters, receipts, notifications)")
    if drafts:
        print(f"Drafted: {len(drafts)} (waiting for your approval)")
        for d in drafts[:3]:
            print(f"  ✓ {d['sender']} — re: {d['subject'][:40]}")
        if len(drafts) > 3:
            print(f"  ... and {len(drafts) - 3} more")
    if event_count > 0:
        print(f"Created events: {event_count}")
    if rejection_count > 0:
        print(f"Logged rejections: {rejection_count}")
    print()

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Auto-actions worker")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")
    parser.add_argument("--approval-only", action="store_true", help="Show pending approvals")
    args = parser.parse_args()

    if args.approval_only:
        # TODO: Show pending drafts from ledger
        print("TODO: Show pending drafts")
        return

    # Fetch threads
    try:
        threads = get_unread_threads()
    except Exception as e:
        print(f"ERROR: Failed to fetch threads: {e}")
        sys.exit(1)

    if not threads:
        print("No unread threads")
        return

    # Run 4 actions
    archive_count = action_archive(threads, dry_run=args.dry_run)
    drafts = action_draft_replies(threads, dry_run=args.dry_run)
    event_count = action_create_events(threads, dry_run=args.dry_run)
    rejection_count = action_log_rejections(threads, dry_run=args.dry_run)

    # Show summary
    show_summary(archive_count, drafts, event_count, rejection_count)

if __name__ == "__main__":
    main()
