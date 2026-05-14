#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import socket
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from request_personal_data_exports import (  # noqa: E402
    DEFAULT_STATE_PATH,
    EXPORT_TARGETS,
    ExportTarget,
    load_state,
    save_state,
)

DEFAULT_CDP_URL = "http://127.0.0.1:9222"
DEFAULT_SNAPSHOT_DIR = Path.home() / ".local/state/inbox/data-export-browser-snapshots"

LOGIN_TERMS = (
    "sign in",
    "log in",
    "login",
    "password",
    "passkey",
    "two-factor",
    "2-step",
    "verification code",
    "verify it's you",
    "verify your identity",
    "confirm access",
    "sudo mode",
    "reauthenticate",
)

REQUEST_UI_TERMS = (
    "request data",
    "request export",
    "start export",
    "new export",
    "create export",
    "export data",
    "download my data",
    "download your data",
    "download your information",
    "get a copy",
    "request archive",
)

SUBMITTED_TERMS = (
    "your request to download",
    "your request to download larger data archive",
    "was made on",
    "request received",
    "request submitted",
    "export requested",
    "archive requested",
    "successfully requested your data export",
    "you will receive an email with the details",
    "we're preparing",
    "we are preparing",
    "preparing your",
    "we'll email",
    "we will email",
    "when your archive is ready",
    "the status of the requests you've made within the last 30 days",
    "you have 6 more scheduled exports",
    "scheduled exports",
    "will start on",
    "no completed exports available",
)

READY_TERMS = (
    "ready to download",
    "archive is ready",
    "data is ready",
    "available to download",
    "download archive",
    "download your files",
    "your google data is ready",
    "copy of your information is ready",
)

STATUS_RANK = {
    "not_started": 0,
    "opened_export_page": 1,
    "browser_seen_export_page": 2,
    "login_required_seen": 3,
    "request_ui_seen": 4,
    "request_submitted_seen": 5,
    "request_submitted_manually": 6,
    "confirmation_email_seen": 7,
    "ready_ui_seen": 8,
    "ready_email_seen": 9,
}

PROVIDER_HOSTS = {
    "linkedin": ("linkedin.com",),
    "google": ("takeout.google.com", "myaccount.google.com", "accounts.google.com"),
    "openai": ("privacy.openai.com", "chatgpt.com", "openai.com"),
    "claude": ("claude.ai", "anthropic.com"),
    "apple": ("privacy.apple.com", "appleid.apple.com"),
    "meta": ("accountscenter.facebook.com", "facebook.com", "instagram.com"),
    "github": ("github.com",),
    "x": ("x.com", "twitter.com"),
    "spotify": ("spotify.com",),
    "netflix": ("netflix.com",),
    "amazon": ("amazon.com",),
    "uber": ("uber.com",),
    "tiktok": ("tiktok.com",),
    "reddit": ("reddit.com",),
}


@dataclass
class BrowserPage:
    target_id: str
    websocket_url: str
    url: str
    title: str


class CdpError(RuntimeError):
    pass


class CdpConnection:
    def __init__(self, websocket_url: str, timeout: float = 5) -> None:
        self.websocket_url = websocket_url
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self.next_id = 1

    def __enter__(self) -> CdpConnection:
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def connect(self) -> None:
        parsed = urllib.parse.urlparse(self.websocket_url)
        if parsed.scheme != "ws":
            raise CdpError(f"Only ws:// CDP URLs are supported: {self.websocket_url}")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path
        if parsed.query:
            path = f"{path}?{parsed.query}"
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        sock = socket.create_connection((host, port), timeout=self.timeout)
        sock.settimeout(self.timeout)
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = sock.recv(4096)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            sock.close()
            raise CdpError("CDP websocket upgrade failed")
        self.sock = sock

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def command(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        msg_id = self.next_id
        self.next_id += 1
        payload = {"id": msg_id, "method": method, "params": params or {}}
        self._send_text(json.dumps(payload, separators=(",", ":")))
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            message = self._recv_json()
            if message.get("id") != msg_id:
                continue
            if "error" in message:
                raise CdpError(json.dumps(message["error"]))
            return message.get("result", {})
        raise CdpError(f"Timed out waiting for {method}")

    def _send_text(self, text: str) -> None:
        if self.sock is None:
            raise CdpError("CDP websocket is not connected")
        data = text.encode("utf-8")
        header = bytearray([0x81])
        length = len(data)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(data))
        self.sock.sendall(bytes(header) + mask + masked)

    def _recv_json(self) -> dict[str, Any]:
        text = self._recv_text()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CdpError("Invalid JSON from CDP") from exc
        if not isinstance(data, dict):
            raise CdpError("Unexpected CDP payload")
        return data

    def _recv_text(self) -> str:
        if self.sock is None:
            raise CdpError("CDP websocket is not connected")
        while True:
            first = self._recv_exact(2)
            opcode = first[0] & 0x0F
            masked = bool(first[1] & 0x80)
            length = first[1] & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]
            mask = self._recv_exact(4) if masked else b""
            payload = self._recv_exact(length)
            if masked:
                payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
            if opcode == 0x1:
                return payload.decode("utf-8", errors="replace")
            if opcode == 0x8:
                raise CdpError("CDP websocket closed")
            if opcode == 0x9:
                self._send_pong(payload)

    def _recv_exact(self, size: int) -> bytes:
        if self.sock is None:
            raise CdpError("CDP websocket is not connected")
        chunks = bytearray()
        while len(chunks) < size:
            chunk = self.sock.recv(size - len(chunks))
            if not chunk:
                raise CdpError("CDP websocket closed")
            chunks.extend(chunk)
        return bytes(chunks)

    def _send_pong(self, payload: bytes) -> None:
        if self.sock is None:
            return
        header = bytearray([0x8A])
        length = len(payload)
        header.append(0x80 | length)
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Track personal-data export progress from a browser CDP endpoint."
    )
    parser.add_argument("--once", action="store_true", help="Run once and exit.")
    parser.add_argument("--watch", action="store_true", help="Poll until stopped.")
    parser.add_argument("--interval-seconds", type=int, default=30)
    parser.add_argument("--cdp-url", default=DEFAULT_CDP_URL)
    parser.add_argument("--state-path", default=str(DEFAULT_STATE_PATH))
    parser.add_argument("--json", action="store_true", help="Print JSON results.")
    parser.add_argument(
        "--save-snapshots",
        action="store_true",
        help="Save sanitized page snapshots for debugging.",
    )
    parser.add_argument("--snapshot-dir", default=str(DEFAULT_SNAPSHOT_DIR))
    return parser.parse_args()


def cdp_json(cdp_url: str, path: str) -> Any:
    url = f"{cdp_url.rstrip('/')}{path}"
    with urllib.request.urlopen(url, timeout=3) as response:  # nosec B310
        return json.loads(response.read().decode("utf-8"))


def list_pages(cdp_url: str) -> list[BrowserPage]:
    try:
        targets = cdp_json(cdp_url, "/json/list")
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return []
    pages: list[BrowserPage] = []
    for target in targets:
        if not isinstance(target, dict) or target.get("type") != "page":
            continue
        websocket_url = str(target.get("webSocketDebuggerUrl") or "")
        if not websocket_url:
            continue
        pages.append(
            BrowserPage(
                target_id=str(target.get("id") or ""),
                websocket_url=websocket_url,
                url=str(target.get("url") or ""),
                title=str(target.get("title") or ""),
            )
        )
    return pages


def provider_for_url(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    for provider, hosts in PROVIDER_HOSTS.items():
        if any(host == item or host.endswith(f".{item}") for item in hosts):
            return provider
    return None


def target_by_key() -> dict[str, ExportTarget]:
    return {target.key: target for target in EXPORT_TARGETS}


def evaluate_page(page: BrowserPage) -> dict[str, Any]:
    expression = r"""
(() => {
  const controls = Array.from(document.querySelectorAll('button,a,input,select,[role="button"]'))
    .slice(0, 120)
    .map((el) => ({
      tag: el.tagName,
      type: el.getAttribute('type') || '',
      text: (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('placeholder') || '').slice(0, 160),
      href: el.href || ''
    }));
  return JSON.stringify({
    href: location.href,
    title: document.title,
    text: (document.body ? document.body.innerText : '').slice(0, 30000),
    htmlLength: document.documentElement ? document.documentElement.outerHTML.length : 0,
    htmlHash: document.documentElement
      ? String(document.documentElement.outerHTML.length) + ':' + document.documentElement.outerHTML.slice(0, 200000).length
      : '0:0',
    controls
  });
})()
"""
    with CdpConnection(page.websocket_url, timeout=5) as cdp:
        result = cdp.command(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
                "timeout": 5000,
            },
        )
    value = result.get("result", {}).get("value")
    if not isinstance(value, str):
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def classify_status(page_data: dict[str, Any]) -> tuple[str, str]:
    text = " ".join(
        [
            str(page_data.get("href") or ""),
            str(page_data.get("title") or ""),
            str(page_data.get("text") or ""),
            json.dumps(page_data.get("controls") or [])[:20000],
        ]
    ).lower()
    if any(term in text for term in READY_TERMS):
        return "ready_ui_seen", "ready/download language visible"
    if any(term in text for term in SUBMITTED_TERMS):
        return "request_submitted_seen", "submitted/preparing language visible"
    if any(term in text for term in REQUEST_UI_TERMS):
        return "request_ui_seen", "export request controls visible"
    if any(term in text for term in LOGIN_TERMS):
        return "login_required_seen", "login/verification language visible"
    return "browser_seen_export_page", "provider page visible"


def better_status(old: str, new: str) -> str:
    return new if STATUS_RANK.get(new, 0) >= STATUS_RANK.get(old, 0) else old


def update_state_for_page(
    state: dict[str, Any],
    provider_key: str,
    page: BrowserPage,
    page_data: dict[str, Any],
    status: str,
    signal: str,
) -> None:
    targets = target_by_key()
    target = targets.get(provider_key)
    providers = state.setdefault("providers", {})
    provider = providers.setdefault(provider_key, {})
    old_status = str(provider.get("status") or "not_started")
    provider.update(
        {
            "name": target.name if target else provider_key,
            "url": target.url if target else page.url,
            "last_browser_seen_at": datetime.now().isoformat(timespec="seconds"),
            "last_browser_url": str(page_data.get("href") or page.url),
            "last_browser_title": str(page_data.get("title") or page.title),
            "last_browser_signal": signal,
            "last_browser_html_length": int(page_data.get("htmlLength") or 0),
        }
    )
    provider["status"] = better_status(old_status, status)


def sanitize_snapshot(provider: str, page_data: dict[str, Any]) -> dict[str, Any]:
    text = str(page_data.get("text") or "")
    return {
        "provider": provider,
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "href": page_data.get("href") or "",
        "title": page_data.get("title") or "",
        "text_sample": text[:5000],
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else "",
        "html_length": page_data.get("htmlLength") or 0,
        "controls": page_data.get("controls") or [],
    }


def save_snapshot(snapshot_dir: Path, provider: str, page_data: dict[str, Any]) -> None:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = snapshot_dir / f"{stamp}-{provider}.json"
    path.write_text(json.dumps(sanitize_snapshot(provider, page_data), indent=2, sort_keys=True))
    path.chmod(0o600)


def scan_once(args: argparse.Namespace) -> list[dict[str, Any]]:
    pages = list_pages(args.cdp_url)
    state_path = Path(os.path.expanduser(args.state_path))
    state = load_state(state_path)
    results: list[dict[str, Any]] = []
    for page in pages:
        provider = provider_for_url(page.url)
        if provider is None:
            continue
        try:
            page_data = evaluate_page(page)
        except CdpError as exc:
            results.append(
                {
                    "provider": provider,
                    "url": page.url,
                    "status": "cdp_error",
                    "signal": str(exc),
                }
            )
            continue
        status, signal = classify_status(page_data)
        update_state_for_page(state, provider, page, page_data, status, signal)
        if args.save_snapshots:
            save_snapshot(Path(os.path.expanduser(args.snapshot_dir)), provider, page_data)
        results.append(
            {
                "provider": provider,
                "url": page_data.get("href") or page.url,
                "title": page_data.get("title") or page.title,
                "status": status,
                "signal": signal,
            }
        )
    save_state(state_path, state)
    return results


def print_results(results: list[dict[str, Any]], as_json: bool) -> None:
    if as_json:
        print(json.dumps(results, indent=2, sort_keys=True))
        return
    if not results:
        print(
            "No export-provider tabs found through CDP. "
            "Launch Brave with scripts/open_export_tracker_browser.sh brave, then open export pages."
        )
        return
    for result in results:
        print(
            f"{result['provider']:9} {result['status']:24} "
            f"{result.get('title') or result.get('url')}"
        )
        print(f"          {result['signal']}")
        print(f"          {result['url']}")


def main() -> int:
    args = parse_args()
    watch = args.watch and not args.once
    while True:
        results = scan_once(args)
        print_results(results, args.json)
        if not watch:
            return 0
        time.sleep(max(args.interval_seconds, 1))


if __name__ == "__main__":
    raise SystemExit(main())
