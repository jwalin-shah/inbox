#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path

DEFAULT_APPLE_ROOT = Path("/Users/jwalinshah/Documents/inbox-data-exports/apple/2026-05-24")
DEFAULT_OUTPUT_ROOT = Path(
    "/Users/jwalinshah/Documents/Codex/2026-05-26/can-we-please-do-a-review/ops_kernel/parsed/apple"
)

TODO_TERMS = (
    "todo",
    "to do",
    "pay",
    "call",
    "email",
    "follow up",
    "follow-up",
    "question",
    "insurance",
    "bill",
    "stanford",
    "united",
    "credit",
    "resume",
    "interview",
    "doctor",
    "pharmacy",
)

ADMIN_TERMS = (
    "stanford",
    "insurance",
    "united",
    "bill",
    "claim",
    "doctor",
    "pharmacy",
    "lawsuit",
    "continuation of care",
    "alameda alliance",
    "car crash",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse high-value Apple export files into ops-kernel review CSVs."
    )
    parser.add_argument("--apple-root", default=str(DEFAULT_APPLE_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    return parser.parse_args()


def first_value(lines: list[str], prefix: str) -> str:
    for line in lines:
        if line.upper().startswith(prefix):
            return line.split(":", 1)[-1].strip()
    return ""


def parse_vcard(text: str) -> dict[str, str]:
    lines = [line.strip() for line in text.replace("\r\n", "\n").splitlines()]
    emails = [line.split(":", 1)[-1].strip() for line in lines if line.upper().startswith("EMAIL")]
    phones = [line.split(":", 1)[-1].strip() for line in lines if line.upper().startswith("TEL")]
    org = first_value(lines, "ORG")
    return {
        "name": first_value(lines, "FN:"),
        "emails": "; ".join(emails[:5]),
        "phones": "; ".join(phones[:5]),
        "organization": org,
    }


def read_zip_texts(zip_path: Path, suffixes: tuple[str, ...]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            if not name.lower().endswith(suffixes):
                continue
            try:
                text = archive.read(name).decode("utf-8", errors="replace")
            except KeyError:
                continue
            rows.append((name, text))
    return rows


def parse_contacts(apple_root: Path) -> list[dict[str, str]]:
    zip_path = apple_root / "iCloud Contacts.zip"
    if not zip_path.exists():
        return []
    contacts = []
    for name, text in read_zip_texts(zip_path, (".vcf",)):
        parsed = parse_vcard(text)
        parsed["source_file"] = str(zip_path)
        parsed["entry"] = name
        contacts.append(parsed)
    contacts.sort(key=lambda row: row.get("name", "").lower())
    return contacts


def todo_score(title: str, text: str) -> int:
    haystack = f"{title}\n{text}".lower()
    return sum(1 for term in TODO_TERMS if term in haystack)


def parse_note_candidates(apple_root: Path) -> list[dict[str, str]]:
    zip_path = apple_root / "iCloud Notes.zip"
    if not zip_path.exists():
        return []
    candidates = []
    for name, text in read_zip_texts(zip_path, (".txt",)):
        title = Path(name).stem.replace(".txt", "")
        score = todo_score(title, text)
        if score == 0:
            continue
        excerpt = re.sub(r"\s+", " ", text).strip()[:500]
        candidates.append(
            {
                "priority": "P0" if score >= 2 else "P1",
                "status": "needs_review",
                "title": title,
                "entry": name,
                "matched_terms": str(score),
                "excerpt": excerpt,
                "source_file": str(zip_path),
                "recommended_action": "review_note_and_promote_source_backed_todo",
            }
        )
    candidates.sort(key=lambda row: (row["priority"], row["title"].lower()))
    return candidates


def admin_note_candidates(notes: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    for note in notes:
        text = f"{note['title']} {note['excerpt']}".lower()
        matched = [term for term in ADMIN_TERMS if term in text]
        if not matched:
            continue
        rows.append(
            {
                "priority": "P0"
                if any(
                    term in matched
                    for term in (
                        "stanford",
                        "insurance",
                        "claim",
                        "doctor",
                        "pharmacy",
                        "lawsuit",
                        "continuation of care",
                        "alameda alliance",
                    )
                )
                else "P1",
                "status": "needs_reconciliation",
                "lane": "admin_health_legal",
                "title": note["title"],
                "matched_terms": "; ".join(matched),
                "excerpt": note["excerpt"],
                "source_file": note["source_file"],
                "entry": note["entry"],
                "recommended_action": "compare_against_master_todo_and_promote_or_reject",
            }
        )
    rows.sort(key=lambda row: (row["priority"], row["title"].lower()))
    return rows


def parse_calendar_reminder_inventory(apple_root: Path) -> list[dict[str, str]]:
    zip_path = apple_root / "iCloud Calendars and Reminders.zip"
    if not zip_path.exists():
        return []
    rows = []
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            lower = name.lower()
            if not (lower.endswith(".ics") or lower.endswith(".json") or lower.endswith(".csv")):
                continue
            data = archive.read(name)
            rows.append(
                {
                    "source_file": str(zip_path),
                    "entry": name,
                    "size_bytes": str(len(data)),
                    "kind": "reminders" if "reminder" in lower else "calendar",
                    "recommended_action": "parse_calendar_or_reminder_items_if_needed",
                }
            )
    return rows


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    apple_root = Path(args.apple_root).expanduser()
    output_root = Path(args.output_root).expanduser()

    contacts = parse_contacts(apple_root)
    notes = parse_note_candidates(apple_root)
    admin_notes = admin_note_candidates(notes)
    calendar = parse_calendar_reminder_inventory(apple_root)

    write_csv(
        output_root / "contacts.csv",
        contacts,
        ["name", "emails", "phones", "organization", "source_file", "entry"],
    )
    write_csv(
        output_root / "note_todo_candidates.csv",
        notes,
        [
            "priority",
            "status",
            "title",
            "entry",
            "matched_terms",
            "excerpt",
            "source_file",
            "recommended_action",
        ],
    )
    write_csv(
        output_root / "admin_reconciliation_queue.csv",
        admin_notes,
        [
            "priority",
            "status",
            "lane",
            "title",
            "matched_terms",
            "excerpt",
            "source_file",
            "entry",
            "recommended_action",
        ],
    )
    write_csv(
        output_root / "calendar_reminder_inventory.csv",
        calendar,
        ["source_file", "entry", "size_bytes", "kind", "recommended_action"],
    )

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "apple_root": str(apple_root),
        "contacts": len(contacts),
        "note_todo_candidates": len(notes),
        "admin_reconciliation_candidates": len(admin_notes),
        "calendar_reminder_files": len(calendar),
    }
    (output_root / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
