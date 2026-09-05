"""Durable, metadata-only storage for governed LifeOps work items.

This store is intentionally not a worker queue.  It records a bounded proposal
and its append-only lifecycle events so that a future Bridge adapter can admit
the proposal without losing scope, evidence references, or acceptance criteria.
No source bodies, credentials, or terminal commands are accepted here.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

DEFAULT_WORK_ITEM_DB = Path(
    os.environ.get(
        "LIFEOPS_WORK_ITEM_DB",
        str(Path.home() / "Library" / "Application Support" / "LifeOps" / "work_items.sqlite3"),
    )
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class WorkItemStore:
    """Persist bounded work-item proposals and their metadata-only events."""

    def __init__(self, db_path: Path | str = DEFAULT_WORK_ITEM_DB) -> None:
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
                CREATE TABLE IF NOT EXISTS work_items (
                    work_item_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    request_hash TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    scope_json TEXT NOT NULL,
                    evidence_refs_json TEXT NOT NULL,
                    worker TEXT NOT NULL,
                    model TEXT NOT NULL,
                    budget_json TEXT NOT NULL,
                    acceptance_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    dispatch_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    receipt_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS work_item_events (
                    event_id TEXT PRIMARY KEY,
                    work_item_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(work_item_id) REFERENCES work_items(work_item_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_work_items_updated_at "
                "ON work_items(updated_at DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_work_item_events_item "
                "ON work_item_events(work_item_id, event_at ASC)"
            )

    @staticmethod
    def _request_hash(payload: dict[str, Any]) -> str:
        return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        value = {
            "schema_version": row["schema_version"],
            "work_item_id": row["work_item_id"],
            "idempotency_key": row["idempotency_key"],
            "objective": row["objective"],
            "scope": json.loads(row["scope_json"]),
            "evidence_refs": json.loads(row["evidence_refs_json"]),
            "worker": row["worker"],
            "model": row["model"] or None,
            "budget": json.loads(row["budget_json"]),
            "acceptance_criteria": json.loads(row["acceptance_json"]),
            "status": row["status"],
            "dispatch_status": row["dispatch_status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "receipt": json.loads(row["receipt_json"]),
        }
        return value

    def _events(self, connection: sqlite3.Connection, work_item_id: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT event_id, event_type, event_at, payload_json
            FROM work_item_events
            WHERE work_item_id = ?
            ORDER BY event_at ASC, event_id ASC
            """,
            (work_item_id,),
        ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "event_at": row["event_at"],
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
        ]

    def create(self, proposal: dict[str, Any]) -> dict[str, Any]:
        """Create a proposal, or return the existing identical idempotent one."""
        request_hash = self._request_hash(proposal)
        work_item_id = f"work_item:{uuid4().hex}"
        created_at = _now()
        receipt = {
            "receipt_type": "lifeops.work_item_receipt.v1",
            "work_item_id": work_item_id,
            "accepted": True,
            "durable": True,
            "stored_at": created_at,
            "dispatch_status": "not_admitted",
            "authority": {
                "provider_access": False,
                "terminal_access": False,
                "credential_access": False,
            },
        }
        columns = (
            work_item_id,
            proposal["idempotency_key"],
            request_hash,
            "lifeops.work_item.v1",
            proposal["objective"],
            _json(proposal["scope"]),
            _json(proposal["evidence_refs"]),
            proposal["worker"],
            proposal.get("model") or "",
            _json(proposal["budget"]),
            _json(proposal["acceptance_criteria"]),
            "proposed",
            "not_admitted",
            created_at,
            created_at,
            _json(receipt),
        )
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM work_items WHERE idempotency_key = ?",
                (proposal["idempotency_key"],),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise ValueError("idempotency_key already exists with a different proposal")
                result = self._decode(existing)
                result["created"] = False
                result["events"] = self._events(connection, existing["work_item_id"])
                return result

            connection.execute(
                """
                INSERT INTO work_items (
                    work_item_id, idempotency_key, request_hash, schema_version,
                    objective, scope_json, evidence_refs_json, worker, model,
                    budget_json, acceptance_json, status, dispatch_status,
                    created_at, updated_at, receipt_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                columns,
            )
            connection.execute(
                """
                INSERT INTO work_item_events
                    (event_id, work_item_id, event_type, event_at, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    f"event:{uuid4().hex}",
                    work_item_id,
                    "proposal_created",
                    created_at,
                    _json({"request_hash": request_hash, "dispatch_status": "not_admitted"}),
                ),
            )
            result = self._decode(
                connection.execute(
                    "SELECT * FROM work_items WHERE work_item_id = ?",
                    (work_item_id,),
                ).fetchone()
            )
            result["created"] = True
            result["events"] = self._events(connection, work_item_id)
            return result

    def get(self, work_item_id: str) -> dict[str, Any] | None:
        clean_id = str(work_item_id or "").strip()
        if not clean_id:
            return None
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM work_items WHERE work_item_id = ?",
                (clean_id,),
            ).fetchone()
            if row is None:
                return None
            result = self._decode(row)
            result["events"] = self._events(connection, clean_id)
            return result

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 200))
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM work_items ORDER BY updated_at DESC LIMIT ?",
                (bounded_limit,),
            ).fetchall()
            values: list[dict[str, Any]] = []
            for row in rows:
                result = self._decode(row)
                result["events"] = self._events(connection, row["work_item_id"])
                values.append(result)
            return values
