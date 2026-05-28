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
from typing import Any

DEFAULT_STATE_PATH = Path.home() / ".local/state/inbox/data-export-email-watch.json"
DEFAULT_CDP_URL = "http://127.0.0.1:9222"

STATUS_RANK = {
    "not_started": 0,
    "opened_export_page": 10,
    "browser_seen_export_page": 20,
    "login_required_seen": 30,
    "request_ui_seen": 40,
    "request_submitted_seen": 50,
    "request_submitted_manually": 60,
    "confirmation_email_seen": 70,
    "export_email_seen": 75,
    "ready_ui_seen": 80,
    "ready_email_seen": 90,
    "download_link_expired": 95,
    "download_link_opened": 100,
}

STATUS_STAGE = {
    "not_started": "request",
    "opened_export_page": "request",
    "browser_seen_export_page": "request",
    "login_required_seen": "request",
    "request_ui_seen": "request",
    "request_submitted_seen": "status",
    "request_submitted_manually": "status",
    "confirmation_email_seen": "status",
    "export_email_seen": "status",
    "ready_ui_seen": "ready",
    "ready_email_seen": "ready",
    "download_link_expired": "request",
    "download_link_opened": "download",
}

MANUAL_BOUNDARY = {
    "not_started": "open_request_page",
    "opened_export_page": "complete_provider_request_in_browser",
    "browser_seen_export_page": "complete_provider_request_in_browser",
    "login_required_seen": "login_or_2fa_required",
    "request_ui_seen": "submit_export_request_manually",
    "request_submitted_seen": "wait_for_ready_email_or_status",
    "request_submitted_manually": "wait_for_ready_email_or_status",
    "confirmation_email_seen": "wait_for_ready_email_or_status",
    "export_email_seen": "review_export_email",
    "ready_ui_seen": "open_download_link_manually",
    "ready_email_seen": "open_download_link_manually",
    "download_link_expired": "re_request_export_in_browser",
    "download_link_opened": "browser_download_may_require_manual_confirmation",
}


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
        "--json",
        action="store_true",
        help="With --status, print the normalized status model as JSON.",
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
        "--open",
        action="store_true",
        help="Actually open selected export pages. Default only reports what would be opened.",
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
        "--mark-expired",
        action="store_true",
        help="Mark selected providers' prior ready/download links as expired and needing re-request.",
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


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    path.write_text(json.dumps(state, indent=2, sort_keys=True))


def better_status(old: str, new: str) -> str:
    return new if STATUS_RANK.get(new, 0) >= STATUS_RANK.get(old, 0) else old


def provider_status(raw: dict[str, Any]) -> str:
    status = str(raw.get("status") or "not_started")
    if status == "download_link_expired":
        return status
    requested_at = str(raw.get("requested_at") or "")
    last_email_at = str(raw.get("last_email_at") or "")
    if (
        requested_at
        and last_email_at
        and requested_at > last_email_at
        and status in {"ready_email_seen", "export_email_seen", "confirmation_email_seen"}
    ):
        return "request_submitted_manually"
    if raw.get("last_download_opened_at"):
        status = better_status(status, "download_link_opened")
    elif last_email_at and not raw.get("status"):
        status = better_status(status, "export_email_seen")
    return status if status in STATUS_RANK else "export_email_seen"


def provider_stage(status: str) -> str:
    return STATUS_STAGE.get(status, "status")


def provider_manual_boundary(status: str) -> str:
    return MANUAL_BOUNDARY.get(status, "review_provider_status_manually")


def normalize_provider_status(target: ExportTarget, raw: dict[str, Any]) -> dict[str, Any]:
    status = provider_status(raw)
    ready_at = raw.get("last_email_at") if status == "ready_email_seen" else ""
    if status == "ready_ui_seen":
        ready_at = raw.get("last_browser_seen_at") or ""
    download_opened_at = str(raw.get("last_download_opened_at") or "")
    return {
        "key": target.key,
        "name": str(raw.get("name") or target.name),
        "status": status,
        "stage": provider_stage(status),
        "manual_boundary": provider_manual_boundary(status),
        "priority": target.priority,
        "url": str(raw.get("url") or target.url),
        "request": {
            "opened_at": str(raw.get("opened_at") or ""),
            "opened_count": int(raw.get("opened_count") or 0),
            "requested_at": str(raw.get("requested_at") or ""),
        },
        "browser": {
            "seen_at": str(raw.get("last_browser_seen_at") or ""),
            "url": str(raw.get("last_browser_url") or ""),
            "title": str(raw.get("last_browser_title") or ""),
            "signal": str(raw.get("last_browser_signal") or ""),
        },
        "email": {
            "seen_at": str(raw.get("last_email_at") or ""),
            "title": str(raw.get("last_email_title") or ""),
            "snippet": str(raw.get("last_email_snippet") or ""),
            "event_count": len(raw.get("email_events") or [])
            if isinstance(raw.get("email_events"), list)
            else 0,
        },
        "ready": {
            "ready_at": str(ready_at or ""),
            "source": "email"
            if status == "ready_email_seen"
            else "browser"
            if status == "ready_ui_seen"
            else "",
        },
        "download": {
            "opened_at": download_opened_at,
            "download_dir": str(raw.get("download_dir") or ""),
            "expired_at": str(raw.get("last_download_expired_at") or ""),
            "expired_reason": str(raw.get("download_expired_reason") or ""),
            "event_count": len(raw.get("download_open_events") or [])
            if isinstance(raw.get("download_open_events"), list)
            else 0,
        },
    }


def build_status_model(state: dict[str, Any]) -> dict[str, Any]:
    providers_state = state.get("providers") if isinstance(state.get("providers"), dict) else {}
    providers = [
        normalize_provider_status(
            target,
            providers_state.get(target.key, {})
            if isinstance(providers_state.get(target.key), dict)
            else {},
        )
        for target in EXPORT_TARGETS
    ]
    counts: dict[str, int] = {}
    for provider in providers:
        stage = str(provider["stage"])
        counts[stage] = counts.get(stage, 0) + 1
    return {
        "schema": "inbox.data_exports.status.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "state_updated_at": str(state.get("updated_at") or ""),
        "summary": {
            "total": len(providers),
            "by_stage": counts,
            "ready": sum(1 for provider in providers if provider["stage"] == "ready"),
            "download": sum(1 for provider in providers if provider["stage"] == "download"),
            "manual_attention": sum(
                1
                for provider in providers
                if provider["manual_boundary"]
                not in {"wait_for_ready_email_or_status", "review_export_email"}
            ),
        },
        "providers": providers,
    }


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
                "status": better_status(
                    str(provider.get("status") or "not_started"),
                    "opened_export_page",
                ),
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
        old_status = str(provider.get("status") or "not_started")
        status = (
            "request_submitted_manually"
            if old_status == "download_link_expired"
            else better_status(old_status, "request_submitted_manually")
        )
        provider.update(
            {
                "name": target.name,
                "url": target.url,
                "note": target.note,
                "login_hint": target.login_hint,
                "requested_at": requested_at,
                "status": status,
            }
        )
        if old_status == "download_link_expired":
            provider.pop("last_download_expired_at", None)
            provider.pop("download_expired_reason", None)
    save_state(path, state)


def mark_expired(path: Path, targets: list[ExportTarget], reason: str) -> None:
    state = load_state(path)
    providers = state.setdefault("providers", {})
    expired_at = datetime.now().isoformat(timespec="seconds")
    for target in targets:
        provider = providers.setdefault(target.key, {})
        provider.update(
            {
                "name": target.name,
                "url": target.url,
                "note": target.note,
                "login_hint": target.login_hint,
                "last_download_expired_at": expired_at,
                "download_expired_reason": reason,
                "status": "download_link_expired",
            }
        )
    save_state(path, state)


def print_status(path: Path, *, as_json: bool = False) -> None:
    state = load_state(path)
    model = build_status_model(state)
    if as_json:
        print(json.dumps(model, indent=2, sort_keys=True))
        return
    for provider in model["providers"]:
        print(f"{provider['key']:9} {provider['stage']}:{provider['status']}")
        print(f"          next:   {provider['manual_boundary']}")
        opened_at = provider["request"]["opened_at"] or "not opened"
        print(f"          opened: {opened_at}")
        if provider["request"]["requested_at"]:
            print(f"          requested: {provider['request']['requested_at']}")
        if provider["email"]["seen_at"] or provider["email"]["title"]:
            print(
                f"          email:  {provider['email']['seen_at']} "
                f"{provider['email']['title']}".rstrip()
            )
        if provider["download"]["opened_at"]:
            print(f"          download opened: {provider['download']['opened_at']}")
        if provider["download"]["expired_at"]:
            print(f"          expired: {provider['download']['expired_at']}")
        print(f"          url:    {provider['url']}")


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
        print_status(state_path, as_json=args.json)
        return 0

    selected = select_targets(args)
    print_targets(selected)
    if args.mark_requested:
        mark_requested(state_path, selected)
        return 0
    if getattr(args, "mark_expired", False):
        mark_expired(
            state_path,
            selected,
            "ready/download link was stale and no file landed in the downloads directory",
        )
        return 0
    if args.record_only:
        mark_opened(state_path, selected)
        return 0
    if args.dry_run:
        return 0
    if not args.open:
        print("Dry run only. Re-run with --open to open browser tabs.")
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
