"""Tiny durable bindings for idempotent Google Tasks creates.

Maps a caller-supplied idempotency/canary key to the exact provider
``list_id`` + ``task_id`` so a retry of the same key cannot insert a second
Google Tasks object. Not a sync engine or task authority — only a projection
binding store for governed creates.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).parent
BINDINGS_DB = BASE_DIR / ".inbox_task_create_bindings.sqlite3"

_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now().isoformat()


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or BINDINGS_DB
    conn = sqlite3.connect(str(path), timeout=30)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_create_bindings (
            idempotency_key TEXT PRIMARY KEY,
            list_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    return conn


def get_binding(idempotency_key: str, db_path: Path | None = None) -> dict[str, Any] | None:
    key = str(idempotency_key or "").strip()
    if not key:
        return None
    with _lock:
        conn = _connect(db_path)
        try:
            row = conn.execute(
                "SELECT idempotency_key, list_id, task_id, title, created_at "
                "FROM task_create_bindings WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
        finally:
            conn.close()
    if not row:
        return None
    return {
        "idempotency_key": row[0],
        "list_id": row[1],
        "task_id": row[2],
        "title": row[3],
        "created_at": row[4],
    }


def put_binding(
    idempotency_key: str,
    *,
    list_id: str,
    task_id: str,
    title: str = "",
    db_path: Path | None = None,
) -> dict[str, Any]:
    key = str(idempotency_key or "").strip()
    if not key:
        raise ValueError("idempotency_key is required")
    if not list_id or not task_id:
        raise ValueError("list_id and task_id are required")
    created_at = _now_iso()
    with _lock:
        conn = _connect(db_path)
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO task_create_bindings
                    (idempotency_key, list_id, task_id, title, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (key, list_id, task_id, title, created_at),
            )
            conn.commit()
            row = conn.execute(
                "SELECT idempotency_key, list_id, task_id, title, created_at "
                "FROM task_create_bindings WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
        finally:
            conn.close()
    assert row is not None
    return {
        "idempotency_key": row[0],
        "list_id": row[1],
        "task_id": row[2],
        "title": row[3],
        "created_at": row[4],
    }
