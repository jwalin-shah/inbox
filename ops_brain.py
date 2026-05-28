"""Provider-agnostic bridge for the local ops kernel."""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_OPS_KERNEL = Path(
    "/Users/jwalinshah/Documents/Codex/2026-05-26/can-we-please-do-a-review/ops_kernel"
)


@dataclass(frozen=True)
class OpsQueueSpec:
    id: str
    label: str
    filename: str
    priority: str = ""
    limit: int = 12


OPS_QUEUE_SPECS: tuple[OpsQueueSpec, ...] = (
    OpsQueueSpec("resume", "Resume evidence", "resume_interview_evidence_queue.csv", limit=8),
    OpsQueueSpec("connector_gmail", "Live Gmail evidence", "connector_gmail_evidence_queue.csv"),
    OpsQueueSpec("gmail", "Gmail export queue", "gmail_reconciliation_queue.csv", "P0"),
    OpsQueueSpec("linkedin", "LinkedIn queue", "linkedin_reconciliation_queue.csv", "P0"),
    OpsQueueSpec("drive", "Drive evidence", "drive_evidence_queue.csv", "P0"),
    OpsQueueSpec(
        "data_exports",
        "Data export processing",
        "data_export_processing_queue.csv",
        "P0",
    ),
    OpsQueueSpec(
        "apple_admin",
        "Apple admin evidence",
        "../parsed/apple/admin_reconciliation_queue.csv",
        "P0",
        limit=8,
    ),
)


def ops_kernel_path() -> Path:
    """Return the configured local ops kernel path."""
    return Path(os.environ.get("OPS_KERNEL_PATH", str(DEFAULT_OPS_KERNEL))).expanduser()


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _title_for_row(row: dict[str, str]) -> str:
    for key in (
        "subject",
        "subject_or_sender",
        "people",
        "project_id",
        "name",
        "evidence_role",
        "bucket",
    ):
        if row.get(key):
            return str(row[key])
    return "Untitled"


def _summary_for_row(row: dict[str, str]) -> str:
    for key in (
        "candidate_action",
        "resume_use",
        "evidence_role",
        "matched_terms",
        "evidence_excerpt",
        "snippet",
    ):
        if row.get(key):
            return str(row[key])
    return ""


def load_ops_queue_rows(kernel: Path | None = None) -> list[dict[str, str]]:
    """Load a compact read-only work queue from local ops reconciliation CSVs."""
    root = kernel or ops_kernel_path()
    reconciliation = root / "reconciliation"
    rows: list[dict[str, str]] = []

    for spec in OPS_QUEUE_SPECS:
        source_rows = _read_csv(reconciliation / spec.filename)
        if spec.priority:
            source_rows = [row for row in source_rows if row.get("priority") == spec.priority]
        for index, row in enumerate(source_rows[: spec.limit], start=1):
            normalized = dict(row)
            normalized["_ops_queue_id"] = spec.id
            normalized["_ops_queue_label"] = spec.label
            normalized["_ops_source_file"] = spec.filename
            normalized["_ops_rank"] = str(index)
            normalized["_ops_title"] = _title_for_row(row)
            normalized["_ops_summary"] = _summary_for_row(row)
            rows.append(normalized)
    return rows


def ops_brain_status(kernel: Path | None = None) -> dict[str, str | int]:
    """Summarize the local brain/control-plane state for CLIs, TUIs, and agents."""
    root = kernel or ops_kernel_path()
    rows = load_ops_queue_rows(root)
    queues = len({row.get("_ops_queue_id", "") for row in rows})
    p0 = sum(1 for row in rows if row.get("priority") == "P0")
    return {
        "kernel": str(root),
        "queue_rows": len(rows),
        "queues": queues,
        "p0_rows": p0,
        "interface": "local-cli-tui",
        "provider_policy": "providers are replaceable adapters; local ledgers are truth",
    }


def main() -> None:
    """Print the local ops brain packet for shell scripts and provider adapters."""
    root = ops_kernel_path()
    packet = {
        "status": ops_brain_status(root),
        "rows": load_ops_queue_rows(root),
    }
    print(json.dumps(packet, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
