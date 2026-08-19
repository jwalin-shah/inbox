#!/usr/bin/env python3
"""think_through.py — LLM reasoner for the trigger engine.

Consumes pending `think_through` items (Slice B iMessage replies, and can reuse
for other sources), reads the real thread context via the inbox API, and uses a
local LLM (Ollama qwen) to:
  - summarize what the new reply means in context
  - recommend an action (respond / note / ignore)
  - propose a follow-up timing (so it's "thought through even after")

OUTPUT-ONLY: it writes an analysis to data/thinkthrough/results/ and flags a
recommended follow-up. It does NOT auto-send or auto-schedule (control stays
with the captain); scheduling is surfaced as a proposed item.
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
THINK_DIR = ROOT / "data" / "thinkthrough"
RESULTS_DIR = THINK_DIR / "results"
LLM = os.environ.get("THINK_LLM", "qwen3.8:27b-mlx")
OLLAMA = os.environ.get("OLLAMA_URL", "http://localhost:11434")


def token() -> str:
    for line in TOKEN_SRC.read_text().splitlines():
        k, _, v = line.partition("=")
        if k.strip() == "INBOX_SERVER_TOKEN":
            return v.strip()
    return ""


def api(path: str) -> list | dict:
    req = urllib.request.Request(BASE + path, headers={"Authorization": "Bearer " + token()})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode())


def thread_context(conv_id: str, limit: int = 12) -> list[dict]:
    try:
        msgs = api(f"/messages/imessage/{urllib.parse.quote(conv_id)}?limit={limit}")
        return msgs if isinstance(msgs, list) else []
    except Exception:
        return []


def llm(prompt: str, max_tokens: int = 700) -> str:
    body = json.dumps({"model": LLM, "prompt": prompt, "stream": False,
                       "options": {"num_predict": max_tokens, "temperature": 0.3}}).encode()
    req = urllib.request.Request(OLLAMA + "/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read()).get("response", "")


def pending_items() -> list[dict]:
    items = []
    for f in sorted(THINK_DIR.glob("*.md")):
        if f.parent == RESULTS_DIR:
            continue
        raw = f.read_text()
        j = raw[raw.find("{"):]
        try:
            d = json.loads(j)
            items.append({"file": f, "data": d})
        except Exception:
            continue
    return items


def main() -> int:
    items = pending_items()
    if not items:
        print("no pending think-through items")
        return 0
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    for it in items:
        d = it["data"]
        ctx = thread_context(d.get("conv_id", ""))
        lines = [f"[{m.get('sender','')} @ {m.get('ts','')}] {m.get('body','')}" for m in ctx]
        thread = "\n".join(lines[-12:])
        prompt = (
            "You are a helpful personal assistant reviewing an iMessage thread.\n"
            "A NEW reply arrived. In context:\n---\n" + (thread or "(no context)") + "\n---\n"
            "New reply: " + (d.get("body") or "") + "\n"
            "Reply:\n1) ONE-paragraph summary of what's happening/what the other person wants.\n"
            "2) RECOMMENDED ACTION: 'respond', 'note', or 'ignore' + one line why.\n"
            "3) FOLLOW-UP: a concrete follow-up time ('e.g. reply tomorrow morning') if action != ignore, else 'none'."
        )
        analysis = llm(prompt)
        stamp = re.sub(r"[^0-9A-Za-z]", "_", d.get("ts") or "new")
        out = RESULTS_DIR / f"analysis_{stamp}_{it['data'].get('conv_id','x')[-8:]}.md"
        out.write_text(f"# Think-through analysis\n\n{item_meta(d)}\n\n{analysis}\n")
        # mark processed by moving the source item out of the live glob
        it["file"].replace(it["file"].with_name("._done_" + it["file"].name))
        print(f"→ analyzed conv={d.get('conv_name')} pending={len(items)} → {out.name}\n{analysis[:260]}\n")
    return 0


def item_meta(d: dict) -> str:
    return (f"- source: {d.get('source')}\n- conv: {d.get('conv_name')}\n- from: {d.get('sender')}\n"
            f"- ts: {d.get('ts')}\n- body: {d.get('body')}")


if __name__ == "__main__":
    sys.exit(main())