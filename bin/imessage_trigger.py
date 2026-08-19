#!/usr/bin/env python3
"""imessage_trigger.py — Slice B of the inbox trigger engine.

Detects NEW iMessage replies after a persisted per-conversation cursor and
emits a "think-through" item (the newest incoming reply + thread context) so
an LLM/agent layer can reason about it afterward and optionally schedule a
follow-up. NOTIFY-ONLY: reads iMessage, never sends.

Detection: fetch iMessage conversations (id, last_ts), and for any whose
last_ts advanced past our cursor, pull that conversation's newest message.
First run seeds the cursor (no flood of the existing backlog).
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

ROOT = Path(__file__).resolve().parent.parent
TOKEN_SRC = Path.home() / ".config/inbox/server.env"
BASE = os.environ.get("INBOX_SERVER_URL", "http://127.0.0.1:9849")
CURSOR_FILE = ROOT / "data" / "imessage_cursor.json"
THINK_DIR = ROOT / "data" / "thinkthrough"


def _token() -> str:
    for line in TOKEN_SRC.read_text().splitlines():
        k, _, v = line.partition("=")
        if k.strip() == "INBOX_SERVER_TOKEN":
            return v.strip()
    return ""


def api(path: str) -> list | dict:
    req = urllib.request.Request(BASE + path, headers={"Authorization": "Bearer " + _token()})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def conversations() -> list:
    d = api("/conversations?source=imessage&limit=100")
    return d if isinstance(d, list) else d.get("conversations", [])


def newest_message(conv_id: str) -> dict | None:
    try:
        msgs = api(f"/messages/imessage/{urllib.parse.quote(conv_id)}?limit=20")
    except Exception:
        return None
    if not isinstance(msgs, list) or not msgs:
        return None
    non_me = [m for m in msgs if m.get("is_me") is not True]
    return non_me[0] if non_me else msgs[0]


def run() -> int:
    cursor = {}
    if CURSOR_FILE.exists():
        cursor = json.loads(CURSOR_FILE.read_text())

    seed = not cursor  # first run = baseline, don't flood backlog
    new_items = []

    for conv in conversations():
        cid = str(conv.get("id") or "")
        last_ts = str(conv.get("last_ts") or "")
        if not cid or not last_ts:
            continue
        if seed or cursor.get(cid) == last_ts:
            cursor[cid] = last_ts
            continue
        # last_ts advanced → new activity; grab the newest incoming reply
        m = newest_message(cid)
        cursor[cid] = last_ts
        if not m:
            continue
        new_items.append({
            "source": "imessage",
            "conv_id": cid,
            "conv_name": conv.get("name") or "(unknown)",
            "sender": m.get("sender") or "",
            "ts": m.get("ts") or "",
            "body": (m.get("body") or "")[:300],
            "kind": "think_through",  # layer below summarizes + may schedule a follow-up
        })

    THINK_DIR.mkdir(parents=True, exist_ok=True)
    CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
    for it in new_items:
        stamp = re.sub(r"[^0-9A-Za-z]", "_", it["ts"] or "new")
        out = THINK_DIR / f"imessage_{stamp}_{it['conv_id'][-8:]}.md"
        out.write_text(f"# Think-through (new iMessage reply)\n\n{json.dumps(it, indent=2)}\n")
        subprocess.run(
            ["osascript", "-e", f'display notification "{it["sender"]}: {it["body"][:60].replace(chr(34),"")}" with title "New iMessage — think through"'],
            capture_output=True)
    CURSOR_FILE.write_text(json.dumps(cursor))

    status = "seeded (baseline)" if seed else f"{len(new_items)} new reply(ies) to think through"
    print(f"iMessage trigger: {status}; tracked {len(cursor)} conversations")
    for it in new_items:
        print(f"  → think_through conv={it['conv_name']} from={it['sender'][:24]} ts={it['ts']} body={it['body'][:40]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(run())