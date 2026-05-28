#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_EXPORT_ROOT = Path("/Users/jwalinshah/Documents/inbox-data-exports")
DEFAULT_CONTEXT_ROOT = Path(
    "/Users/jwalinshah/Documents/Codex/2026-05-26/can-we-please-do-a-review"
)
DEFAULT_OPS_KERNEL = DEFAULT_CONTEXT_ROOT / "ops_kernel"


@dataclass(frozen=True)
class ProviderRule:
    priority: str
    action: str
    rationale: str


PROVIDER_RULES = {
    "apple": ProviderRule(
        "P0",
        "extract_contacts_notes_calendars_reminders_bookmarks",
        "High-value local context for people, todos, appointments, and notes.",
    ),
    "linkedin": ProviderRule(
        "P0",
        "reconcile_parsed_threads_connections_warm_intros",
        "Highest leverage for job search, recruiting, and warm intro graph.",
    ),
    "openai": ProviderRule(
        "P1",
        "extract_project_and_interview_context",
        "Useful for reconstructing project history and resume/interview evidence.",
    ),
    "x": ProviderRule(
        "P2",
        "extract_relationship_or_outreach_history_if_needed",
        "Lower priority unless a target person/company history matters.",
    ),
    "spotify": ProviderRule(
        "P3",
        "defer_unless_personal_analytics_needed",
        "Low direct value for job/admin command center work.",
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build local processing manifest and reconciliation queue for personal data exports."
    )
    parser.add_argument("--export-root", default=str(DEFAULT_EXPORT_ROOT))
    parser.add_argument("--context-root", default=str(DEFAULT_CONTEXT_ROOT))
    parser.add_argument("--ops-kernel", default=str(DEFAULT_OPS_KERNEL))
    return parser.parse_args()


def zip_summary(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        samples = [name for name in names[:12]]
    return {
        "zip_entry_count": len(names),
        "sample_entries": " | ".join(samples),
    }


def provider_for_path(path: Path, export_root: Path) -> str:
    try:
        return path.relative_to(export_root).parts[0]
    except (ValueError, IndexError):
        return "unknown"


def local_archive_rows(export_root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(export_root.rglob("*.zip")):
        provider = provider_for_path(path, export_root)
        rule = PROVIDER_RULES.get(
            provider,
            ProviderRule("P2", "inspect_and_classify", "No provider-specific rule yet."),
        )
        try:
            summary = zip_summary(path)
            status = "zip_verified"
            error = ""
        except zipfile.BadZipFile as exc:
            summary = {"zip_entry_count": 0, "sample_entries": ""}
            status = "zip_error"
            error = str(exc)
        rows.append(
            {
                "source_type": "local_zip",
                "provider": provider,
                "priority": rule.priority,
                "status": status,
                "path_or_id": str(path),
                "name": path.name,
                "size_bytes": str(path.stat().st_size),
                "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(
                    timespec="seconds"
                ),
                "zip_entry_count": str(summary["zip_entry_count"]),
                "sample_entries": str(summary["sample_entries"]),
                "recommended_action": rule.action,
                "rationale": rule.rationale,
                "error": error,
            }
        )
    return rows


def drive_rows(context_root: Path) -> list[dict[str, str]]:
    manifest = context_root / "drive_export_manifest.csv"
    if not manifest.exists():
        return []
    rows: list[dict[str, str]] = []
    with manifest.open(newline="", encoding="utf-8") as f:
        for item in csv.DictReader(f):
            terms = (item.get("matched_terms") or "").lower()
            name = item.get("name") or ""
            if any(term in terms for term in ("facebook", "meta")):
                provider = "meta"
                priority = "P0"
                action = "download_or_parse_drive_resident_meta_export"
                rationale = "Meta export appears already transferred to Drive."
            elif "takeout" in terms or name.lower().startswith("takeout-"):
                provider = "google_takeout"
                priority = "P0"
                action = "process_takeout_batch_selectively"
                rationale = (
                    "Google Takeout contains high-value Gmail/Drive/Contacts/Calendar context."
                )
            elif "archive" in terms:
                provider = "drive_archive"
                priority = "P1"
                action = "inspect_drive_archive_candidate"
                rationale = "Drive export-like artifact needs provider classification."
            else:
                continue
            rows.append(
                {
                    "source_type": "drive_manifest",
                    "provider": provider,
                    "priority": priority,
                    "status": "drive_resident_not_localized",
                    "path_or_id": item.get("id") or "",
                    "name": name,
                    "size_bytes": item.get("size") or "",
                    "modified": item.get("modified") or "",
                    "zip_entry_count": "",
                    "sample_entries": item.get("web_link") or "",
                    "recommended_action": action,
                    "rationale": rationale,
                    "error": "",
                }
            )
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "source_type",
        "provider",
        "priority",
        "status",
        "path_or_id",
        "name",
        "size_bytes",
        "modified",
        "zip_entry_count",
        "sample_entries",
        "recommended_action",
        "rationale",
        "error",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    by_provider: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    for row in rows:
        by_provider[row["provider"]] = by_provider.get(row["provider"], 0) + 1
        by_priority[row["priority"]] = by_priority.get(row["priority"], 0) + 1
    path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "row_count": len(rows),
                "by_provider": by_provider,
                "by_priority": by_priority,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    export_root = Path(args.export_root).expanduser()
    context_root = Path(args.context_root).expanduser()
    ops_kernel = Path(args.ops_kernel).expanduser()
    rows = local_archive_rows(export_root) + drive_rows(context_root)
    rows.sort(key=lambda row: (row["priority"], row["provider"], row["name"]))

    parsed_dir = ops_kernel / "parsed" / "data_exports"
    reconciliation_dir = ops_kernel / "reconciliation"
    write_csv(parsed_dir / "archive_manifest.csv", rows)
    write_csv(reconciliation_dir / "data_export_processing_queue.csv", rows)
    write_summary(parsed_dir / "summary.json", rows)

    print(
        json.dumps(
            {
                "archive_manifest": str(parsed_dir / "archive_manifest.csv"),
                "processing_queue": str(reconciliation_dir / "data_export_processing_queue.csv"),
                "summary": str(parsed_dir / "summary.json"),
                "rows": len(rows),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
