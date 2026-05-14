#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DEFAULT_STATE_PATH = Path.home() / ".local/state/inbox/data-export-email-watch.json"
DEFAULT_CDP_URL = "http://127.0.0.1:9222"


@dataclass(frozen=True)
class ExportTarget:
    key: str
    name: str
    url: str
    note: str
    priority: bool = False
    login_hint: str = "Uses your existing browser session; login or 2FA may be required."


EXPORT_TARGETS: tuple[ExportTarget, ...] = (
    ExportTarget(
        key="linkedin",
        name="LinkedIn",
        url="https://www.linkedin.com/mypreferences/d/download-my-data",
        note="Request the larger archive so messages and connections are included.",
        priority=True,
    ),
    ExportTarget(
        key="google",
        name="Google Takeout",
        url="https://takeout.google.com/",
        note="Use for Gmail, Drive, Calendar, Photos, YouTube, Contacts, and account activity.",
        priority=True,
    ),
    ExportTarget(
        key="openai",
        name="OpenAI / ChatGPT",
        url="https://privacy.openai.com/",
        note="Privacy Portal: consumer ChatGPT account -> Download my data.",
        priority=True,
    ),
    ExportTarget(
        key="claude",
        name="Anthropic / Claude",
        url="https://claude.ai/settings/privacy",
        note="Settings -> Privacy -> Export data; download email normally expires quickly.",
        priority=True,
    ),
    ExportTarget(
        key="apple",
        name="Apple Data & Privacy",
        url="https://privacy.apple.com/",
        note="Request a copy of Apple account/iCloud-associated data.",
        priority=True,
    ),
    ExportTarget(
        key="meta",
        name="Meta / Facebook / Instagram",
        url="https://accountscenter.facebook.com/info_and_permissions/dyi/",
        note="Accounts Center -> Download your information for Facebook and Instagram.",
        priority=True,
    ),
    ExportTarget(
        key="github",
        name="GitHub",
        url="https://github.com/settings/admin",
        note="Settings -> Account -> Export account data.",
        priority=True,
    ),
    ExportTarget(
        key="x",
        name="X / Twitter",
        url="https://x.com/settings/download_your_data",
        note="Request archive after identity verification; may take a few days.",
    ),
    ExportTarget(
        key="spotify",
        name="Spotify",
        url="https://www.spotify.com/account/privacy/",
        note="Account privacy page has personal data download controls.",
    ),
    ExportTarget(
        key="netflix",
        name="Netflix",
        url="https://www.netflix.com/account/getmyinfo",
        note="Account data export page; request may require login and email confirmation.",
    ),
    ExportTarget(
        key="amazon",
        name="Amazon",
        url="https://www.amazon.com/hz/privacy-central/data-requests/preview.html",
        note="Privacy Central -> Request your data.",
    ),
    ExportTarget(
        key="uber",
        name="Uber",
        url="https://privacy.uber.com/privacy/exploreyourdata/download",
        note="Privacy Center -> download a copy of your Uber data.",
    ),
    ExportTarget(
        key="tiktok",
        name="TikTok",
        url="https://www.tiktok.com/setting/download-your-data",
        note="If web route fails, use mobile app: Settings and privacy -> Account -> Download your data.",
    ),
    ExportTarget(
        key="reddit",
        name="Reddit",
        url="https://www.reddit.com/settings/data-request",
        note="Request account data export from Reddit settings.",
    ),
)


def _target_map() -> dict[str, ExportTarget]:
    return {target.key: target for target in EXPORT_TARGETS}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open personal-data export request pages for major providers."
    )
    parser.add_argument(
        "providers",
        nargs="*",
        help="Provider keys to open. Use --list to see keys.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Open every configured export page.",
    )
    parser.add_argument(
        "--priority",
        action="store_true",
        help="Open the highest-value export pages first.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List configured export pages without opening them.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show local request/open/email status without opening browser tabs.",
    )
    parser.add_argument(
        "--state-path",
        default=str(DEFAULT_STATE_PATH),
        help="Path for local export request/watch state.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print URLs that would open without opening browser tabs.",
    )
    parser.add_argument(
        "--record-only",
        action="store_true",
        help="Record selected pages as opened without opening browser tabs.",
    )
    parser.add_argument(
        "--mark-requested",
        action="store_true",
        help="Mark selected providers as manually requested without opening browser tabs.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.4,
        help="Seconds to wait between opening tabs.",
    )
    parser.add_argument(
        "--via-cdp",
        action="store_true",
        help="Open tabs in a DevTools-tracked Chromium/Brave browser.",
    )
    parser.add_argument(
        "--cdp-url",
        default=DEFAULT_CDP_URL,
        help="Chrome DevTools HTTP endpoint for --via-cdp.",
    )
    return parser.parse_args()


def select_targets(args: argparse.Namespace) -> list[ExportTarget]:
    targets = _target_map()
    if args.all:
        return list(EXPORT_TARGETS)
    if args.priority or not args.providers:
        return [target for target in EXPORT_TARGETS if target.priority]

    selected: list[ExportTarget] = []
    unknown: list[str] = []
    for provider in args.providers:
        key = provider.lower().strip()
        if key in targets:
            selected.append(targets[key])
        else:
            unknown.append(provider)

    if unknown:
        print(f"Unknown provider(s): {', '.join(unknown)}", file=sys.stderr)
        print("Run with --list to see valid keys.", file=sys.stderr)
        raise SystemExit(2)
    return selected


def print_targets(targets: list[ExportTarget]) -> None:
    for target in targets:
        print(f"{target.key:9} {target.name}")
        print(f"          {target.url}")
        print(f"          {target.note}")
        print(f"          {target.login_hint}")


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    path.write_text(json.dumps(state, indent=2, sort_keys=True))


def mark_opened(path: Path, targets: list[ExportTarget]) -> None:
    state = load_state(path)
    providers = state.setdefault("providers", {})
    opened_at = datetime.now().isoformat(timespec="seconds")
    for target in targets:
        provider = providers.setdefault(target.key, {})
        provider.update(
            {
                "name": target.name,
                "url": target.url,
                "note": target.note,
                "login_hint": target.login_hint,
                "opened_at": opened_at,
                "status": "opened_export_page",
            }
        )
        provider["opened_count"] = int(provider.get("opened_count", 0)) + 1
    save_state(path, state)


def mark_requested(path: Path, targets: list[ExportTarget]) -> None:
    state = load_state(path)
    providers = state.setdefault("providers", {})
    requested_at = datetime.now().isoformat(timespec="seconds")
    for target in targets:
        provider = providers.setdefault(target.key, {})
        provider.update(
            {
                "name": target.name,
                "url": target.url,
                "note": target.note,
                "login_hint": target.login_hint,
                "requested_at": requested_at,
                "status": "request_submitted_manually",
            }
        )
    save_state(path, state)


def print_status(path: Path) -> None:
    state = load_state(path)
    providers = state.get("providers", {})
    for target in EXPORT_TARGETS:
        status = providers.get(target.key, {})
        opened_at = status.get("opened_at", "not opened")
        requested_at = status.get("requested_at", "")
        current = status.get("status", "not_started")
        email_at = status.get("last_email_at", "")
        email_title = status.get("last_email_title", "")
        print(f"{target.key:9} {current}")
        print(f"          opened: {opened_at}")
        if requested_at:
            print(f"          requested: {requested_at}")
        if email_at or email_title:
            print(f"          email:  {email_at} {email_title}".rstrip())
        events = status.get("email_events")
        if isinstance(events, list) and len(events) > 1:
            print(f"          email events: {len(events)}")
        print(f"          url:    {target.url}")


def open_target_via_cdp(cdp_url: str, target: ExportTarget) -> None:
    # Chrome/Brave's CDP /json/new endpoint expects the target URL as the raw
    # query string, not as a `url=` parameter.
    encoded_url = urllib.parse.quote(target.url, safe=":/?&=%#")
    endpoint = f"{cdp_url.rstrip('/')}/json/new?{encoded_url}"
    request = urllib.request.Request(endpoint, method="PUT")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # nosec B310
            response.read()
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError(
            f"Could not open {target.key} through CDP at {cdp_url}. "
            "Start the tracker browser first."
        ) from exc


def main() -> int:
    args = parse_args()
    state_path = Path(os.path.expanduser(args.state_path))
    if args.list:
        print_targets(list(EXPORT_TARGETS))
        return 0
    if args.status:
        print_status(state_path)
        return 0

    selected = select_targets(args)
    print_targets(selected)
    if args.mark_requested:
        mark_requested(state_path, selected)
        return 0
    if args.record_only:
        mark_opened(state_path, selected)
        return 0
    if args.dry_run:
        return 0

    for target in selected:
        if args.via_cdp:
            open_target_via_cdp(args.cdp_url, target)
        else:
            webbrowser.open_new_tab(target.url)
        time.sleep(max(args.delay, 0))
    mark_opened(state_path, selected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
