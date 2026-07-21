"""
Approval-request + audit-log persistence layer — SQLite-backed storage for the
per-action approval-lease workflow. Pattern mirrors scheduler.py/memory_store.py.

Lifecycle this module supports:
  1. A caller describes a pending guarded write (POST /approvals/request) ->
     row in `approval_requests`, state="pending". No lease exists yet.
  2. The captain (or an interactive script) decides (POST /approvals/{id}/decide).
     On approve, inbox_server mints a real lease via mint_local_approval_lease()
     using the exact recorded method/path/body, and this module records the
     resulting lease_id against the request, state="approved".
     On deny, state="denied".
  3. Every request creation, decision, lease mint, and guarded-write execution
     is appended to `audit_log` so "what happened / can we revert" is answerable
     from the database instead of assumed.

This module only persists state; it does not know how to mint leases or
compute approval-route rules (payload hashing, resource-ref derivation, etc
already live in inbox_server.py) -- callers pass in the already-computed
fields.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).parent
APPROVAL_DB = BASE_DIR / ".inbox_approvals.sqlite3"


def _now_iso() -> str:
    return datetime.now().isoformat()


def _request_id() -> str:
    return f"apr_{uuid.uuid4().hex}"


def _event_id() -> str:
    return f"aud_{uuid.uuid4().hex}"


@dataclass
class ApprovalRequest:
    id: int | None = None
    request_id: str = ""
    method: str = ""
    path: str = ""
    body_json: str = "{}"
    provider: str = ""
    operation: str = ""
    approval_class: str = ""
    executor: str = ""
    account_ref: str = ""
    resource_ref: str = ""
    item_count: int = 1
    payload_hash: str = ""
    query_hash: str = ""
    state: str = "pending"  # pending | approved | denied
    created_at: str = ""
    decided_at: str | None = None
    decided_by: str = ""
    lease_id: str = ""
    denial_reason: str = ""


_REQUEST_COLUMNS = (
    "id",
    "request_id",
    "method",
    "path",
    "body_json",
    "provider",
    "operation",
    "approval_class",
    "executor",
    "account_ref",
    "resource_ref",
    "item_count",
    "payload_hash",
    "query_hash",
    "state",
    "created_at",
    "decided_at",
    "decided_by",
    "lease_id",
    "denial_reason",
)


def _row_to_request(row: tuple) -> dict[str, Any]:
    return dict(zip(_REQUEST_COLUMNS, row, strict=True))


class ApprovalStore:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or APPROVAL_DB
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path, timeout=5.0) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS approval_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL UNIQUE,
                    method TEXT NOT NULL,
                    path TEXT NOT NULL,
                    body_json TEXT NOT NULL DEFAULT '{}',
                    provider TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    approval_class TEXT NOT NULL,
                    executor TEXT NOT NULL,
                    account_ref TEXT NOT NULL DEFAULT '',
                    resource_ref TEXT NOT NULL DEFAULT '',
                    item_count INTEGER NOT NULL DEFAULT 1,
                    payload_hash TEXT NOT NULL DEFAULT '',
                    query_hash TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    decided_at TEXT,
                    decided_by TEXT NOT NULL DEFAULT '',
                    lease_id TEXT NOT NULL DEFAULT '',
                    denial_reason TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    ts TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    lease_id TEXT NOT NULL DEFAULT '',
                    method TEXT NOT NULL DEFAULT '',
                    path TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL DEFAULT '',
                    operation TEXT NOT NULL DEFAULT '',
                    account TEXT NOT NULL DEFAULT '',
                    resource TEXT NOT NULL DEFAULT '',
                    payload_hash TEXT NOT NULL DEFAULT '',
                    actor TEXT NOT NULL DEFAULT '',
                    result TEXT NOT NULL DEFAULT '',
                    detail_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_log_ts ON audit_log(ts)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_log_request_id ON audit_log(request_id)"
            )
            conn.commit()

    # ── Approval requests ────────────────────────────────────────────────

    def create_request(
        self,
        *,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        provider: str,
        operation: str,
        approval_class: str,
        executor: str,
        account_ref: str,
        resource_ref: str,
        item_count: int,
        payload_hash: str,
        query_hash: str,
    ) -> dict[str, Any]:
        request_id = _request_id()
        created_at = _now_iso()
        body_json = json.dumps(body or {}, sort_keys=True, separators=(",", ":"))
        with self._lock, sqlite3.connect(self.db_path, timeout=5.0) as conn:
            conn.execute(
                """
                INSERT INTO approval_requests (
                    request_id, method, path, body_json, provider, operation,
                    approval_class, executor, account_ref, resource_ref,
                    item_count, payload_hash, query_hash, state, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    request_id,
                    method.upper(),
                    path,
                    body_json,
                    provider,
                    operation,
                    approval_class,
                    executor,
                    account_ref,
                    resource_ref,
                    item_count,
                    payload_hash,
                    query_hash,
                    created_at,
                ),
            )
            conn.commit()
        return self.get_request(request_id)  # type: ignore[return-value]

    def get_request(self, request_id: str) -> dict[str, Any] | None:
        with self._lock, sqlite3.connect(self.db_path, timeout=5.0) as conn:
            row = conn.execute(
                f"SELECT {', '.join(_REQUEST_COLUMNS)} FROM approval_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        return _row_to_request(row) if row else None

    def list_requests(self, state: str | None = "pending", limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, sqlite3.connect(self.db_path, timeout=5.0) as conn:
            if state:
                rows = conn.execute(
                    f"SELECT {', '.join(_REQUEST_COLUMNS)} FROM approval_requests "
                    "WHERE state = ? ORDER BY created_at DESC LIMIT ?",
                    (state, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {', '.join(_REQUEST_COLUMNS)} FROM approval_requests "
                    "ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [_row_to_request(row) for row in rows]

    def decide_request(
        self,
        request_id: str,
        *,
        approved: bool,
        decided_by: str = "captain",
        lease_id: str = "",
        denial_reason: str = "",
    ) -> dict[str, Any] | None:
        decided_at = _now_iso()
        new_state = "approved" if approved else "denied"
        with self._lock, sqlite3.connect(self.db_path, timeout=5.0) as conn:
            cur = conn.execute(
                """
                UPDATE approval_requests
                SET state = ?, decided_at = ?, decided_by = ?, lease_id = ?, denial_reason = ?
                WHERE request_id = ? AND state = 'pending'
                """,
                (new_state, decided_at, decided_by, lease_id, denial_reason, request_id),
            )
            conn.commit()
            if cur.rowcount == 0:
                return None
        return self.get_request(request_id)

    # ── Audit log ────────────────────────────────────────────────────────

    def log_event(
        self,
        event_type: str,
        *,
        request_id: str = "",
        lease_id: str = "",
        method: str = "",
        path: str = "",
        provider: str = "",
        operation: str = "",
        account: str = "",
        resource: str = "",
        payload_hash: str = "",
        actor: str = "",
        result: str = "",
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event_id = _event_id()
        ts = _now_iso()
        detail_json = json.dumps(detail or {}, sort_keys=True, separators=(",", ":"))
        with self._lock, sqlite3.connect(self.db_path, timeout=5.0) as conn:
            conn.execute(
                """
                INSERT INTO audit_log (
                    event_id, ts, event_type, request_id, lease_id, method, path,
                    provider, operation, account, resource, payload_hash, actor,
                    result, detail_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    ts,
                    event_type,
                    request_id,
                    lease_id,
                    method,
                    path,
                    provider,
                    operation,
                    account,
                    resource,
                    payload_hash,
                    actor,
                    result,
                    detail_json,
                ),
            )
            conn.commit()
        return {
            "event_id": event_id,
            "ts": ts,
            "event_type": event_type,
            "request_id": request_id,
            "lease_id": lease_id,
            "method": method,
            "path": path,
            "provider": provider,
            "operation": operation,
            "account": account,
            "resource": resource,
            "payload_hash": payload_hash,
            "actor": actor,
            "result": result,
            "detail": detail or {},
        }

    def list_audit_log(
        self,
        *,
        limit: int = 200,
        event_type: str | None = None,
        request_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT event_id, ts, event_type, request_id, lease_id, method, path, provider, operation, account, resource, payload_hash, actor, result, detail_json FROM audit_log"
        clauses = []
        params: list[Any] = []
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if request_id:
            clauses.append("request_id = ?")
            params.append(request_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        with self._lock, sqlite3.connect(self.db_path, timeout=5.0) as conn:
            rows = conn.execute(query, params).fetchall()
        cols = (
            "event_id",
            "ts",
            "event_type",
            "request_id",
            "lease_id",
            "method",
            "path",
            "provider",
            "operation",
            "account",
            "resource",
            "payload_hash",
            "actor",
            "result",
            "detail_json",
        )
        out = []
        for row in rows:
            entry = dict(zip(cols, row, strict=True))
            entry["detail"] = json.loads(entry.pop("detail_json") or "{}")
            out.append(entry)
        return out
