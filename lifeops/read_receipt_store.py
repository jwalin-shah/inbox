"""Durable, metadata-only storage for LifeOps read receipts."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

DEFAULT_READ_RECEIPT_DB = Path(
    os.environ.get(
        "LIFEOPS_READ_RECEIPT_DB",
        str(Path.home() / "Library" / "Application Support" / "LifeOps" / "read_receipts.sqlite3"),
    )
)


class ReadReceiptStore:
    """Persist bounded read-attempt metadata without storing source content."""

    def __init__(self, db_path: Path | str = DEFAULT_READ_RECEIPT_DB) -> None:
        self.db_path = Path(db_path).expanduser()
        self._lock = threading.RLock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        parent_existed = self.db_path.parent.exists()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not parent_existed:
            os.chmod(self.db_path.parent, 0o700)
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        os.chmod(self.db_path, 0o600)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS read_receipts (
                    run_id TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    route TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    account TEXT NOT NULL,
                    account_scope TEXT NOT NULL,
                    read_only INTEGER NOT NULL,
                    transport_complete INTEGER NOT NULL,
                    receipt_json TEXT NOT NULL,
                    stored_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_read_receipts_finished_at "
                "ON read_receipts(finished_at DESC)"
            )

    def record(self, receipt: dict[str, Any]) -> dict[str, Any]:
        """Store one receipt and return a metadata-only persistence result."""
        run_id = str(receipt.get("run_id") or "").strip()
        if not run_id:
            raise ValueError("read receipt requires run_id")
        schema_version = str(receipt.get("schema_version") or "").strip()
        started_at = str(receipt.get("started_at") or "").strip()
        finished_at = str(receipt.get("finished_at") or "").strip()
        if not schema_version or not started_at or not finished_at:
            raise ValueError("read receipt requires schema_version, started_at, and finished_at")
        # The receipt contains only transport metadata and references. Serializing
        # it as JSON preserves the trace while avoiding any source-item payload.
        receipt_json = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO read_receipts (
                    run_id, schema_version, route, started_at, finished_at,
                    account, account_scope, read_only, transport_complete, receipt_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    schema_version=excluded.schema_version,
                    route=excluded.route,
                    started_at=excluded.started_at,
                    finished_at=excluded.finished_at,
                    account=excluded.account,
                    account_scope=excluded.account_scope,
                    read_only=excluded.read_only,
                    transport_complete=excluded.transport_complete,
                    receipt_json=excluded.receipt_json,
                    stored_at=CURRENT_TIMESTAMP
                """,
                (
                    run_id,
                    schema_version,
                    "triage_all",
                    started_at,
                    finished_at,
                    str(receipt.get("account") or ""),
                    str(receipt.get("account_scope") or ""),
                    int(bool(receipt.get("read_only"))),
                    int(bool(receipt.get("transport_complete"))),
                    receipt_json,
                ),
            )
        return {"status": "stored", "run_id": run_id}

    def get(self, run_id: str) -> dict[str, Any] | None:
        clean_run_id = str(run_id or "").strip()
        if not clean_run_id:
            return None
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT receipt_json FROM read_receipts WHERE run_id = ?",
                (clean_run_id,),
            ).fetchone()
        if row is None:
            return None
        value = json.loads(str(row["receipt_json"]))
        return value if isinstance(value, dict) else None

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 200))
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT receipt_json
                FROM read_receipts
                ORDER BY finished_at DESC
                LIMIT ?
                """,
                (bounded_limit,),
            ).fetchall()
        values: list[dict[str, Any]] = []
        for row in rows:
            value = json.loads(str(row["receipt_json"]))
            if isinstance(value, dict):
                values.append(value)
        return values
