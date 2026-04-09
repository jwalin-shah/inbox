"""
Ambient notes — writes to Obsidian vault as markdown files.
Daily notes go to {vault}/daily/YYYY-MM-DD.md, ambient captures to {vault}/ambient/.
"""

from __future__ import annotations

import datetime
from pathlib import Path

VAULT_PATH = Path.home() / "vault"
DAILY_DIR = VAULT_PATH / "daily"
AMBIENT_DIR = VAULT_PATH / "ambient"


def _ensure_dirs():
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    AMBIENT_DIR.mkdir(parents=True, exist_ok=True)


def _today_file() -> Path:
    return DAILY_DIR / f"{datetime.date.today()}.md"


def append_to_daily(content: str):
    """Append a note entry to today's daily note."""
    _ensure_dirs()
    path = _today_file()
    ts = datetime.datetime.now().strftime("%H:%M")

    if not path.exists():
        path.write_text(f"# {datetime.date.today()}\n\n")

    with open(path, "a") as f:
        f.write(f"## {ts}\n{content}\n\n")


def save_note(
    raw_transcript: str,
    summary: str | None,
    topics: str = "",
):
    """Save an ambient capture — appends to daily note with structured content."""
    parts = []

    if summary:
        parts.append(summary)

    # Action items as checkboxes
    if "→" in (summary or ""):
        # extract_summary formats action items as "→ item1; item2"
        for segment in (summary or "").split("→"):
            segment = segment.strip()
            if segment and segment != summary:
                for item in segment.split(";"):
                    item = item.strip()
                    if item:
                        parts.append(f"- [ ] {item}")

    # Topics as tags
    if topics:
        tags = " ".join(f"#{t.strip().replace(' ', '-')}" for t in topics.split(",") if t.strip())
        parts.append(tags)

    # Raw transcript in collapsed details
    parts.append(f"> [!note]- Transcript\n> {raw_transcript}")

    append_to_daily("\n".join(parts))


def list_daily_notes(limit: int = 30) -> list[dict]:
    """List recent daily notes. Returns [{date, path, size}]."""
    _ensure_dirs()
    files = sorted(DAILY_DIR.glob("*.md"), reverse=True)[:limit]
    return [
        {
            "date": f.stem,
            "path": str(f),
            "size": f.stat().st_size,
        }
        for f in files
    ]


def read_daily_note(date: str) -> str | None:
    """Read a daily note by date string (YYYY-MM-DD)."""
    path = DAILY_DIR / f"{date}.md"
    if path.exists():
        return path.read_text()
    return None
