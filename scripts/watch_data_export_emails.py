#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from request_personal_data_exports import better_status

from inbox_client import InboxClient

DEFAULT_STATE_PATH = Path.home() / ".local/state/inbox/data-export-email-watch.json"
DEFAULT_ENV_PATH = Path.home() / ".config/raycast/inbox-workflows.env"
EXPORT_QUERY = (
    '("ready to download" OR "ready for download" OR "Your data is ready for download" OR '
    '"download request is complete" OR "download from Data & Privacy" OR '
    '"download your data" OR "data export" OR "Google data" OR "Takeout" OR '
    '"Archive of Google data scheduled" OR "Scheduled Archive of Google Data started" OR '
    '"preparing your data for download" OR '
    '"information transfer to Google Drive is in progress" OR '
    '"archive is ready" OR "download your information")'
)


@dataclass(frozen=True)
class ProviderPattern:
    key: str
    terms: tuple[str, ...]


PROVIDER_PATTERNS: tuple[ProviderPattern, ...] = (
    ProviderPattern("linkedin", ("linkedin", "professional community")),
    ProviderPattern("google", ("google data", "takeout", "google takeout")),
    ProviderPattern("openai", ("openai", "chatgpt")),
    ProviderPattern("claude", ("anthropic", "claude")),
    ProviderPattern("apple", ("apple", "icloud")),
    ProviderPattern("meta", ("facebook", "instagram", "meta")),
    ProviderPattern("github", ("github",)),
    ProviderPattern("x", ("x archive", "twitter archive", "x data", "twitter data")),
    ProviderPattern("spotify", ("spotify",)),
    ProviderPattern("netflix", ("netflix",)),
    ProviderPattern("amazon", ("amazon",)),
    ProviderPattern("uber", ("uber",)),
    ProviderPattern("tiktok", ("tiktok",)),
    ProviderPattern("reddit", ("reddit",)),
)

READY_TERMS = (
    "ready to download",
    "archive is ready",
    "data is ready",
    "available to download",
    "download your files",
    "download your information",
    "download request is complete",
    "download from data & privacy",
    "your google data is ready",
    "copy of your information is ready",
)

CONFIRMATION_TERMS = (
    "request received",
    "preparing",
    "we're preparing",
    "we are preparing",
    "scheduled archive of google data started",
    "archive of google data scheduled",
    "preparing your data for download",
    "information transfer to google drive is in progress",
    "data export has started",
    "export requested",
    "data request",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Watch Gmail for personal-data export ready/download emails."
    )
    parser.add_argument("--once", action="store_true", help="Run once and exit.")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Poll until --max-minutes elapses or the process is stopped.",
    )
    parser.add_argument(
        "--newer-than",
        default="30d",
        help="Gmail newer_than window, for example 7d or 30d.",
    )
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--interval-seconds", type=int, default=600)
    parser.add_argument("--max-minutes", type=int, default=0)
    parser.add_argument("--notify", action="store_true", help="Send a macOS notification.")
    parser.add_argument(
        "--include-seen",
        action="store_true",
        help="Print already-seen matching emails too.",
    )
    parser.add_argument(
        "--state-path",
        default=str(DEFAULT_STATE_PATH),
        help="Path for local seen-message state.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON results.",
    )
    return parser.parse_args()


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def seen_ids_from_state(state: dict[str, Any]) -> set[str]:
    if isinstance(state.get("seen_ids"), list):
        return {str(item) for item in state["seen_ids"]}
    return set()


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    path.write_text(json.dumps(state, indent=2, sort_keys=True))


def classify_provider(text: str) -> str:
    haystack = text.lower()
    for pattern in PROVIDER_PATTERNS:
        if any(term in haystack for term in pattern.terms):
            return pattern.key
    return "unknown"


def normalize_result(item: dict[str, Any], seen: set[str]) -> dict[str, str | bool]:
    title = str(item.get("title") or "")
    snippet = str(item.get("snippet") or "").replace("\n", " ").strip()
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    sender = str(metadata.get("from") or "")
    message_id = str(item.get("id") or "")
    provider = classify_provider(f"{sender} {title} {snippet}")
    return {
        "id": message_id,
        "provider": provider,
        "timestamp": str(item.get("timestamp") or ""),
        "title": title,
        "snippet": snippet[:240],
        "is_new": message_id not in seen,
    }


def classify_email_status(hit: dict[str, str | bool]) -> str:
    text = f"{hit.get('title', '')} {hit.get('snippet', '')}".lower()
    if any(term in text for term in READY_TERMS):
        return "ready_email_seen"
    if any(term in text for term in CONFIRMATION_TERMS):
        return "confirmation_email_seen"
    return "export_email_seen"


def update_provider_status(state: dict[str, Any], hits: list[dict[str, str | bool]]) -> None:
    providers = state.setdefault("providers", {})
    for hit in hits:
        provider_key = str(hit.get("provider") or "unknown")
        if provider_key == "unknown":
            continue
        provider = providers.setdefault(provider_key, {})
        new_status = classify_email_status(hit)
        old_status = str(provider.get("status") or "not_started")
        requested_at = str(provider.get("requested_at") or "")
        hit_timestamp = str(hit.get("timestamp") or "")
        if requested_at and hit_timestamp and hit_timestamp < requested_at:
            continue
        status = better_status(old_status, new_status)
        provider["status"] = status
        current_timestamp = str(provider.get("last_email_at") or "")
        if status == new_status and hit_timestamp >= current_timestamp:
            provider.update(
                {
                    "last_email_at": hit_timestamp,
                    "last_email_title": hit.get("title") or "",
                    "last_email_snippet": hit.get("snippet") or "",
                }
            )
        events = provider.setdefault("email_events", [])
        if isinstance(events, list):
            event = {
                "id": hit.get("id") or "",
                "timestamp": hit.get("timestamp") or "",
                "title": hit.get("title") or "",
                "status": new_status,
            }
            existing_ids = {str(item.get("id") or "") for item in events if isinstance(item, dict)}
            if event["id"] not in existing_ids:
                events.append(event)
                events.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
                del events[10:]


def find_export_emails(client: InboxClient, newer_than: str, limit: int) -> list[dict[str, Any]]:
    query = f"{EXPORT_QUERY} newer_than:{newer_than}"
    data = client.search(query, sources=["gmail"], limit=limit)
    return filter_export_hits([normalize_result(item, set()) for item in data.get("results", [])])


def filter_export_hits(hits: list[dict[str, str | bool]]) -> list[dict[str, str | bool]]:
    return [hit for hit in hits if str(hit.get("provider") or "unknown") != "unknown"]


def notify(hit_count: int) -> None:
    title = "Inbox data exports"
    body = f"{hit_count} export download email(s) found"
    script = f'display notification "{body}" with title "{title}"'
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)


def print_hits(hits: list[dict[str, Any]], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(hits, indent=2, sort_keys=True))
        return
    if not hits:
        print("No matching export emails found.")
        return
    for hit in hits:
        marker = "NEW" if hit["is_new"] else "seen"
        print(f"[{marker}] {hit['provider']} {hit['timestamp']} {hit['title']}")
        snippet = str(hit.get("snippet") or "")
        if snippet:
            print(f"      {snippet}")


def poll_once(
    args: argparse.Namespace, client: InboxClient, state: dict[str, Any]
) -> dict[str, Any]:
    seen = seen_ids_from_state(state)
    query = f"{EXPORT_QUERY} newer_than:{args.newer_than}"
    data = client.search(query, sources=["gmail"], limit=args.limit)
    hits = filter_export_hits([normalize_result(item, seen) for item in data.get("results", [])])
    printable = hits if args.include_seen else [hit for hit in hits if hit["is_new"]]
    print_hits(printable, as_json=args.json)

    new_ids = {str(hit["id"]) for hit in hits if hit["is_new"] and hit["id"]}
    if new_ids and args.notify:
        notify(len(new_ids))
    update_provider_status(state, hits)
    state["seen_ids"] = sorted(seen | {str(hit["id"]) for hit in hits if hit["id"]})
    return state


def main() -> int:
    args = parse_args()
    load_env(DEFAULT_ENV_PATH)
    state_path = Path(os.path.expanduser(args.state_path))
    state = load_state(state_path)
    client = InboxClient(timeout=45)

    watch = args.watch and not args.once
    deadline = (
        datetime.now() + timedelta(minutes=args.max_minutes) if args.max_minutes > 0 else None
    )

    while True:
        state = poll_once(args, client, state)
        save_state(state_path, state)
        if not watch:
            return 0
        if deadline and datetime.now() >= deadline:
            return 0
        time.sleep(max(args.interval_seconds, 1))


if __name__ == "__main__":
    raise SystemExit(main())
