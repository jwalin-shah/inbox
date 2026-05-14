#!/usr/bin/env -S uv run python
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from request_personal_data_exports import DEFAULT_STATE_PATH, load_state, save_state
from track_data_export_browser import CdpConnection

from services import google_auth_all

DEFAULT_CDP_URL = "http://127.0.0.1:9222"
DEFAULT_DOWNLOAD_DIR = Path.home() / "Documents/inbox-data-exports/_downloads"


@dataclass(frozen=True)
class ReadyProvider:
    key: str
    account: str
    query: str
    preferred_domains: tuple[str, ...]


READY_PROVIDERS: tuple[ReadyProvider, ...] = (
    ReadyProvider(
        key="claude",
        account="jwalinshah13@gmail.com",
        query='from:(Anthropic) "Your data is ready for download" newer_than:7d',
        preferred_domains=("claude.ai",),
    ),
    ReadyProvider(
        key="github",
        account="jwalinshah13@gmail.com",
        query='from:(GitHub) "Your data export is ready to download" newer_than:7d',
        preferred_domains=("github.com",),
    ),
)


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attr_map = dict(attrs)
        href = attr_map.get("href")
        if href:
            self.links.append(href)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open ready export links from Gmail in the tracked Brave/Chromium browser."
    )
    parser.add_argument(
        "providers",
        nargs="*",
        help="Ready providers to open. Defaults to all configured ready providers.",
    )
    parser.add_argument("--cdp-url", default=DEFAULT_CDP_URL)
    parser.add_argument("--download-dir", default=str(DEFAULT_DOWNLOAD_DIR))
    parser.add_argument("--state-path", default=str(DEFAULT_STATE_PATH))
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def decode_payload(payload: dict[str, Any]) -> list[tuple[str, str]]:
    parts: list[tuple[str, str]] = []

    def walk(part: dict[str, Any]) -> None:
        mime = str(part.get("mimeType") or "")
        data = str(part.get("body", {}).get("data") or "")
        if data and mime in ("text/plain", "text/html"):
            padding = "=" * ((4 - len(data) % 4) % 4)
            body = base64.urlsafe_b64decode(data + padding).decode("utf-8", "replace")
            parts.append((mime, body))
        for sub in part.get("parts", []) or []:
            if isinstance(sub, dict):
                walk(sub)

    walk(payload)
    return parts


def extract_links(payload: dict[str, Any]) -> list[str]:
    links: list[str] = []
    for mime, body in decode_payload(payload):
        if mime == "text/html":
            parser = LinkParser()
            parser.feed(body)
            links.extend(parser.links)
        else:
            links.extend(re.findall(r"https?://[^\s<>\"]+", body))
    return links


def domain_for(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return (parsed.hostname or "").lower()


def keep_link(url: str, preferred_domains: tuple[str, ...]) -> bool:
    lower = url.lower()
    if any(term in lower for term in ("unsubscribe", "privacy", "terms", "preferences")):
        return False
    host = domain_for(url)
    return any(host == domain or host.endswith(f".{domain}") for domain in preferred_domains)


def ready_provider_map() -> dict[str, ReadyProvider]:
    return {provider.key: provider for provider in READY_PROVIDERS}


def selected_providers(args: argparse.Namespace) -> list[ReadyProvider]:
    provider_map = ready_provider_map()
    if not args.providers:
        return list(READY_PROVIDERS)
    selected: list[ReadyProvider] = []
    unknown: list[str] = []
    for raw in args.providers:
        key = raw.lower().strip()
        if key in provider_map:
            selected.append(provider_map[key])
        else:
            unknown.append(raw)
    if unknown:
        raise SystemExit(f"Unknown ready provider(s): {', '.join(unknown)}")
    return selected


def cdp_json(cdp_url: str, path: str, method: str = "GET") -> Any:
    request = urllib.request.Request(f"{cdp_url.rstrip('/')}{path}", method=method)
    with urllib.request.urlopen(request, timeout=5) as response:  # nosec B310
        return json.loads(response.read().decode("utf-8"))


def browser_ws(cdp_url: str) -> str:
    version = cdp_json(cdp_url, "/json/version")
    websocket_url = str(version.get("webSocketDebuggerUrl") or "")
    if not websocket_url:
        raise RuntimeError("CDP browser websocket not available")
    return websocket_url


def set_download_dir(cdp_url: str, download_dir: Path) -> None:
    download_dir.mkdir(parents=True, exist_ok=True)
    with CdpConnection(browser_ws(cdp_url), timeout=5) as cdp:
        cdp.command(
            "Browser.setDownloadBehavior",
            {
                "behavior": "allow",
                "downloadPath": str(download_dir),
                "eventsEnabled": True,
            },
        )


def open_in_browser(cdp_url: str, url: str) -> None:
    encoded = urllib.parse.quote(url, safe=":/?&=%#")
    request = urllib.request.Request(f"{cdp_url.rstrip('/')}/json/new?{encoded}", method="PUT")
    with urllib.request.urlopen(request, timeout=5) as response:  # nosec B310
        response.read()


def collect_ready_links(provider: ReadyProvider) -> list[dict[str, str]]:
    gmail_svcs, *_ = google_auth_all()
    svc = gmail_svcs.get(provider.account)
    if svc is None:
        return []
    response = svc.users().messages().list(userId="me", q=provider.query, maxResults=10).execute()
    found: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for msg_ref in response.get("messages", []):
        msg_id = str(msg_ref.get("id") or "")
        full = svc.users().messages().get(userId="me", id=msg_id, format="full").execute()
        headers = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", [])}
        for url in extract_links(full.get("payload", {})):
            if url in seen_urls or not keep_link(url, provider.preferred_domains):
                continue
            seen_urls.add(url)
            found.append(
                {
                    "provider": provider.key,
                    "message_id": msg_id,
                    "subject": headers.get("Subject", ""),
                    "domain": domain_for(url),
                    "url": url,
                }
            )
    return found


def update_state(path: Path, opened: list[dict[str, str]], download_dir: Path) -> None:
    if not opened:
        return
    state = load_state(path)
    providers = state.setdefault("providers", {})
    now = datetime.now().isoformat(timespec="seconds")
    for item in opened:
        provider = providers.setdefault(item["provider"], {})
        provider["last_download_opened_at"] = now
        provider["download_dir"] = str(download_dir)
        events = provider.setdefault("download_open_events", [])
        if isinstance(events, list):
            event = {
                "message_id": item["message_id"],
                "subject": item["subject"],
                "domain": item["domain"],
                "opened_at": now,
            }
            existing = {
                (str(e.get("message_id")), str(e.get("domain")))
                for e in events
                if isinstance(e, dict)
            }
            if (event["message_id"], event["domain"]) not in existing:
                events.append(event)
                del events[20:]
    save_state(path, state)


def main() -> int:
    args = parse_args()
    download_dir = Path(os.path.expanduser(args.download_dir))
    providers = selected_providers(args)

    ready_links: list[dict[str, str]] = []
    for provider in providers:
        ready_links.extend(collect_ready_links(provider))

    print(
        json.dumps(
            [
                {
                    "provider": item["provider"],
                    "message_id": item["message_id"],
                    "subject": item["subject"],
                    "domain": item["domain"],
                }
                for item in ready_links
            ],
            indent=2,
            sort_keys=True,
        )
    )
    if args.dry_run or not ready_links:
        return 0

    set_download_dir(args.cdp_url, download_dir)
    opened: list[dict[str, str]] = []
    for item in ready_links:
        open_in_browser(args.cdp_url, item["url"])
        opened.append(item)
        time.sleep(0.5)
    update_state(Path(os.path.expanduser(args.state_path)), opened, download_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
