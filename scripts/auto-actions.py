#!/usr/bin/env python3
"""
Auto-Actions Worker

Autonomous agent operations:
1. Auto-archive low-signal emails (score 1-2)
2. Auto-log job rejections to sheet
3. (Draft + calendar creation require full message bodies - added in phase 2)

Usage:
  python3 auto-actions.py                 # Run all actions
  python3 auto-actions.py --dry-run       # Preview without executing
  python3 auto-actions.py --archive-only  # Archive only
  python3 auto-actions.py --log-only      # Log rejections only
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
import subprocess
import re

# Config defaults
CONFIG = {
    "archive": {"enabled": True, "min_score": 1, "max_score": 2},
    "logging": {"enabled": True, "rejection_keywords": ["reject", "unfortunately", "not moving forward", "decided not", "passing"]},
}

def load_config():
    """Load auto-actions config (future: from ~/.inbox/auto-actions.yml)"""
    return CONFIG

def log_action(action_type, details):
    """Log every action to ~/.inbox/ledger"""
    ledger_path = Path.home() / ".inbox" / "ledger"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().isoformat() + "Z"
    log_line = f"{timestamp}  action={action_type}  {details}\n"

    with open(ledger_path, "a") as f:
        f.write(log_line)

def curl(method, endpoint, data=None):
    """Make HTTP request to inbox server"""
    url = f"http://localhost:9849{endpoint}"
    cmd = ["curl", "-s"]

    if method.upper() == "POST":
        cmd.extend(["-X", "POST", "-H", "Content-Type: application/json"])
        if data:
            cmd.extend(["-d", json.dumps(data)])
    elif method.upper() == "GET":
        pass
    else:
        raise ValueError(f"Unsupported method: {method}")

    cmd.append(url)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"curl failed: {result.stderr}")

    if not result.stdout:
        return {}

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise Exception(f"Invalid JSON response: {result.stdout[:200]}")

def get_conversations():
    """Fetch unread Gmail conversations"""
    try:
        conversations = curl("GET", "/conversations?source=gmail&limit=100")
        return [c for c in conversations if c.get("unread", 0) > 0]
    except Exception as e:
        print(f"ERROR: Failed to fetch conversations: {e}")
        sys.exit(1)

def score_conversation(conv):
    """Score conversation 1-5 based on sender patterns"""
    # Load priority senders from config
    priority_senders = {
        "tierra@cerebras.net": 5,
        "jack@jackandjill.ai": 5,
        "apply@ycombinator.com": 5,
        "dave@jobs.bandana.com": 5,
    }

    sender = conv.get("reply_to", "").lower()

    # Check priority senders
    if sender in priority_senders:
        return priority_senders[sender]

    # Check for company domains in priority list
    if any(domain in sender for domain in ["cerebras", "anthropic", "waymo", "openai"]):
        return 5

    # Check for recruitment/job keywords
    name = conv.get("name", "").lower()
    snippet = conv.get("snippet", "").lower()
    text = f"{name} {snippet}"

    job_keywords = ["interview", "screen", "offer", "rejection", "reject", "unfortunate", "role", "position", "hiring"]
    if any(kw in text for kw in job_keywords):
        return 4

    # Newsletter/notification domains = low signal
    low_signal_domains = ["newsletter", "noreply", "notifications", "github", "gmail", "notification", "no-reply"]
    if any(domain in sender for domain in low_signal_domains):
        return 1

    # Default to medium
    return 3

def is_rejection(conv):
    """Check if conversation is a job rejection"""
    rejection_keywords = CONFIG["logging"]["rejection_keywords"]

    snippet = conv.get("snippet", "").lower()
    name = conv.get("name", "").lower()
    text = f"{name} {snippet}"

    return any(kw in text for kw in rejection_keywords)

def extract_job_info(conv):
    """Extract company and role from conversation"""
    name = conv.get("name", "")
    snippet = conv.get("snippet", "")

    # Try to extract company from sender domain
    sender = conv.get("reply_to", "")
    company = "Unknown"

    if "@" in sender:
        domain = sender.split("@")[1].split(".")[0]
        company = domain.capitalize()

    # Try to find company in name or snippet
    if "reject" in snippet.lower() or "unfortunate" in snippet.lower():
        # This is likely a rejection email
        for word in name.split():
            if len(word) > 2:
                company = word
                break

    role = snippet.split(",")[0][:50] if "," in snippet else "Unknown"

    return company[:30], role[:50]

def action_archive(conversations, dry_run=False):
    """Auto-archive low-signal threads (score 1-2)"""
    config = load_config()
    if not config["archive"]["enabled"]:
        return 0

    to_archive = [
        c for c in conversations
        if score_conversation(c) <= config["archive"]["max_score"]
    ]

    if not to_archive:
        return 0

    if dry_run:
        print(f"[DRY RUN] Would archive {len(to_archive)} threads")
        for c in to_archive[:3]:
            score = score_conversation(c)
            print(f"  (score {score}) {c['name']}: {c['snippet'][:50]}")
        if len(to_archive) > 3:
            print(f"  ... and {len(to_archive) - 3} more")
        return len(to_archive)

    # Archive via API
    thread_ids = [c["thread_id"] for c in to_archive]

    try:
        curl("POST", "/gmail/batch-modify", {
            "msg_ids": thread_ids,
            "remove_label_ids": ["INBOX"],
            "add_label_ids": ["Triage/Archived"],
        })

        log_action("auto_archive", f"count={len(to_archive)}  reason=low_signal")
        return len(to_archive)
    except Exception as e:
        print(f"ERROR: Archive failed: {e}")
        return 0

def action_log_rejections(conversations, dry_run=False):
    """Auto-log job rejections"""
    config = load_config()
    if not config["logging"]["enabled"]:
        return 0

    rejections = []
    for conv in conversations:
        if is_rejection(conv):
            company, role = extract_job_info(conv)
            rejections.append({
                "date": datetime.utcnow().strftime("%Y-%m-%d"),
                "company": company,
                "role": role,
                "status": "rejected",
                "notes": conv["snippet"][:100],
            })

    if not rejections:
        return 0

    if dry_run:
        print(f"[DRY RUN] Would log {len(rejections)} rejections")
        for r in rejections:
            print(f"  {r['company']}: {r['role']}")
        return len(rejections)

    # Log to Google Sheet (if configured)
    sheet_id = os.getenv("JWALIN_JOB_TRACKER_SHEET_ID")
    if sheet_id:
        try:
            for rejection in rejections:
                curl("POST", f"/sheets/{sheet_id}/values/Rejections/append", {
                    "values": [[
                        rejection["date"],
                        rejection["company"],
                        rejection["role"],
                        rejection["status"],
                        rejection["notes"],
                    ]],
                })

            log_action("auto_log_rejections", f"count={len(rejections)}")
            return len(rejections)
        except Exception as e:
            print(f"WARNING: Failed to log rejections to sheet: {e}")
            # Don't fail completely, just log the error
            log_action("auto_log_rejections", f"count={len(rejections)}  error=sheet_unavailable")
            return len(rejections)
    else:
        # Just log locally
        log_action("auto_log_rejections", f"count={len(rejections)}  note=sheet_id_not_configured")
        return len(rejections)

def show_summary(archived, logged):
    """Show what actions were taken"""
    print("\n## Auto-Actions Complete — " + datetime.utcnow().strftime("%m/%d %H:%M"))
    print()

    if archived > 0:
        print(f"✓ Archived: {archived} emails (low-signal)")
    if logged > 0:
        print(f"✓ Logged: {logged} rejections to job tracker")

    if archived == 0 and logged == 0:
        print("No actions needed.")

    print()

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Auto-actions agent")
    parser.add_argument("--dry-run", action="store_true", help="Preview without executing")
    parser.add_argument("--archive-only", action="store_true", help="Only archive")
    parser.add_argument("--log-only", action="store_true", help="Only log rejections")
    args = parser.parse_args()

    # Fetch conversations
    try:
        conversations = get_conversations()
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    if not conversations:
        print("No unread conversations")
        return

    archived = 0
    logged = 0

    # Run actions
    if not args.log_only:
        archived = action_archive(conversations, dry_run=args.dry_run)

    if not args.archive_only:
        logged = action_log_rejections(conversations, dry_run=args.dry_run)

    # Show summary
    show_summary(archived, logged)

if __name__ == "__main__":
    main()
