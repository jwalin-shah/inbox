"""Capture health ledger for Inbox input sources."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).parent
CAPTURE_HEALTH_DB = BASE_DIR / ".inbox_capture_health.sqlite3"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class CaptureHealthRecord:
    source_id: str
    display_name: str
    source_type: str
    account: str = ""
    configured: bool = False
    authenticated: bool = False
    readable: bool = False
    writable: bool = False
    last_success_at: str = ""
    newest_seen_at: str = ""
    newest_seen_id: str = ""
    item_count: int = 0
    checked_at: str = ""
    last_error: str = ""
    coverage_notes: str = ""

    @property
    def key(self) -> str:
        return f"{self.source_id}:{self.account}"

    @property
    def status(self) -> str:
        if self.readable:
            return "ok"
        if self.configured or self.authenticated:
            return "error"
        return "not_configured"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["key"] = self.key
        data["status"] = self.status
        return data


class CaptureHealthStore:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or CAPTURE_HEALTH_DB
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path, timeout=5.0) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_health (
                    source_id TEXT NOT NULL,
                    account TEXT NOT NULL DEFAULT '',
                    display_name TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    configured INTEGER NOT NULL DEFAULT 0,
                    authenticated INTEGER NOT NULL DEFAULT 0,
                    readable INTEGER NOT NULL DEFAULT 0,
                    writable INTEGER NOT NULL DEFAULT 0,
                    last_success_at TEXT NOT NULL DEFAULT '',
                    newest_seen_at TEXT NOT NULL DEFAULT '',
                    newest_seen_id TEXT NOT NULL DEFAULT '',
                    item_count INTEGER NOT NULL DEFAULT 0,
                    checked_at TEXT NOT NULL,
                    last_error TEXT NOT NULL DEFAULT '',
                    coverage_notes TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (source_id, account)
                )
                """
            )
            conn.commit()

    def upsert(self, record: CaptureHealthRecord) -> None:
        with self._lock, sqlite3.connect(self.db_path, timeout=5.0) as conn:
            conn.execute(
                """
                INSERT INTO source_health (
                    source_id, account, display_name, source_type, configured,
                    authenticated, readable, writable, last_success_at,
                    newest_seen_at, newest_seen_id, item_count, checked_at,
                    last_error, coverage_notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id, account) DO UPDATE SET
                    display_name = excluded.display_name,
                    source_type = excluded.source_type,
                    configured = excluded.configured,
                    authenticated = excluded.authenticated,
                    readable = excluded.readable,
                    writable = excluded.writable,
                    last_success_at = excluded.last_success_at,
                    newest_seen_at = excluded.newest_seen_at,
                    newest_seen_id = excluded.newest_seen_id,
                    item_count = excluded.item_count,
                    checked_at = excluded.checked_at,
                    last_error = excluded.last_error,
                    coverage_notes = excluded.coverage_notes
                """,
                (
                    record.source_id,
                    record.account,
                    record.display_name,
                    record.source_type,
                    int(record.configured),
                    int(record.authenticated),
                    int(record.readable),
                    int(record.writable),
                    record.last_success_at,
                    record.newest_seen_at,
                    record.newest_seen_id,
                    record.item_count,
                    record.checked_at,
                    record.last_error,
                    record.coverage_notes,
                ),
            )
            conn.commit()

    def list_records(self) -> list[dict[str, Any]]:
        with self._lock, sqlite3.connect(self.db_path, timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM source_health
                ORDER BY source_type, source_id, account
                """
            ).fetchall()

        records: list[dict[str, Any]] = []
        for row in rows:
            record = CaptureHealthRecord(
                source_id=row["source_id"],
                account=row["account"],
                display_name=row["display_name"],
                source_type=row["source_type"],
                configured=bool(row["configured"]),
                authenticated=bool(row["authenticated"]),
                readable=bool(row["readable"]),
                writable=bool(row["writable"]),
                last_success_at=row["last_success_at"],
                newest_seen_at=row["newest_seen_at"],
                newest_seen_id=row["newest_seen_id"],
                item_count=int(row["item_count"]),
                checked_at=row["checked_at"],
                last_error=row["last_error"],
                coverage_notes=row["coverage_notes"],
            )
            records.append(record.to_dict())
        return records


def capture_summary(records: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(records),
        "ok": sum(1 for record in records if record.get("status") == "ok"),
        "error": sum(1 for record in records if record.get("status") == "error"),
        "not_configured": sum(1 for record in records if record.get("status") == "not_configured"),
    }
