#!/usr/bin/env python3
"""autoslash_trigger.py — Slice A of the inbox trigger engine.

Detects NEW AutoSlash emails (price-drop alerts) since a stored cursor and
surfaces them as structured alerts. NOTIFY-ONLY: reads Gmail, never sends,
never rebooks, never writes to AutoSlash.

This is the first instance of a general "arrival -> reaction" engine:
  source cursor -> detect -> classify -> react (notify + optional follow-up).

Built to run against the inbox server API (the proven /gmail/search path) so it
needs no direct Gmail creds of its own.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# --- config ---
ROOT = Path(__file__).resolve().parent.parent
TOKEN_SRC = Path.home() / ".config/inbox/server.env"
BASE = os.environ.get("INBOX_SERVER_URL", "http://127.0.0.1:9849")
CURSOR_FILE = ROOT / "data" / "autoslash_cursor.json"
ALERT_DIR = ROOT / "data" / "alerts"
SOURCE_QUERY = "from:autoslash.com"
ACCOUNTS = ["jshah1331@gmail.com", "jwalinsshah@gmail.com", "jwalinshah13@gmail.com"]


def _token() -> str:
    for line in TOKEN_SRC.read_text().splitlines():
        k, _, v = line.partition("=")
        if k.strip() == "INBOX_SERVER_TOKEN":
            return v.strip()
    return ""


def api(path: str) -> dict | list:
    req = urllib.request.Request(
        BASE + path, headers={"Authorization": "Bearer " + _token()}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def gmail_search(q: str, account: str = "") -> list:
    enc = urllib.parse.quote(q)
    acct = f"&account={urllib.parse.quote(account)}" if account else ""
    d = api(f"/gmail/search?q={enc}{acct}")
    return d if isinstance(d, list) else d.get("messages", [])


def load_cursor() -> set[str]:
    return set(json.loads(CURSOR_FILE.read_text())) if CURSOR_FILE.exists() else set()


def save_cursor(ids: set[str]) -> None:
    ALERT_DIR.mkdir(parents=True, exist_ok=True)
    CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
    CURSOR_FILE.write_text(json.dumps(sorted(ids)))


def classify(subject: str, snippet: str) -> dict | None:
    """Best-effort classify an AutoSlash email into a structured alert."""
    low = (subject + " " + snippet).lower()
    is_alert = re.search(r"lower rate|save|price drop|found a better|daily rate|rebook", low)
    if not is_alert:
        return None
    conf = re.findall(r"\b([A-Z]{1}\d{8,10}|2\d{7}US\d)\b", subject + " " + snippet)
    prices = re.findall(r"\$[\d,]+\.?\d*", subject + " " + snippet)
    return {
        "kind": "autoslash_price_signal" if re.search(r"lower rate|save|price drop", low) else "autoslash_update",
        "confirmation": conf[0] if conf else "",
        "prices": prices[:3],
        "subject": subject,
        "snippet": snippet[:160],
    }


def run(_dry=False) -> int:
    seen = load_cursor()
    fresh = []
    # single un-accounted search spans all Gmail accounts (verified)
    for m in gmail_search(SOURCE_QUERY):
        mid = str(m.get("id") or "")
        if not mid or mid in seen:
            continue
        seen.add(mid)
        alert = classify(m.get("name") or "", m.get("snippet") or "")
        if alert:
            alert["msg_id"] = mid
            alert["account"] = m.get("gmail_account") or ""
            alert["detected_at"] = m.get("last_ts") or ""
            fresh.append(alert)

    ALERT_DIR.mkdir(parents=True, exist_ok=True)
    reacted = 0
    for a in fresh:
        # one file per alert; surface here = write a markdown alert the inbox/notify layer can read
        stamp = re.sub(r"[^0-9A-Za-z]", "_", a.get("detected_at") or "new")
        out = ALERT_DIR / f"autoslash_{stamp}_{a['msg_id'][-8:]}.md"
        out.write_text(f"# AutoSlash alert\n\n{json.dumps(a, indent=2)}\n")
        if a["kind"] == "autoslash_price_signal":
            notice = (a.get("subject") or "").replace('"', "")[:90]
            subprocess.run(
                ["osascript", "-e", f'display notification "{notice}" with title "Rental price drop (AutoSlash)"'],
                capture_output=True)
            reacted += 1
    save_cursor(seen)
    print(f"scanned; {len(fresh)} new AutoSlash message(s), {reacted} price signal(s) reacted; cursor {len(seen)}")
    for a in fresh:
        print(f"  → {a['kind']} conf={a['confirmation']} prices={a['prices']} file={a['msg_id'][-8:]}")
    return 0


if __name__ == "__main__":
    sys.exit(run())