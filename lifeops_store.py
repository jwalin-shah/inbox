from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CAPTURE_STATES = {"NEW", "PROCESSING", "PROCESSED", "FAILED"}
COMMITMENT_STATES = {
    "INBOX",
    "READY_MACHINE",
    "READY_HUMAN",
    "SCHEDULED",
    "WAITING",
    "WATCHING",
    "VERIFYING",
    "REVIEW",
    "DONE",
}


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class LifeOpsStore:
    """Durable capture and commitment state for the first LifeOps slice."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS life_captures (
                    capture_id TEXT PRIMARY KEY,
                    raw_text TEXT NOT NULL,
                    source TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    processing_state TEXT NOT NULL
                        CHECK (processing_state IN ('NEW', 'PROCESSING', 'PROCESSED', 'FAILED')),
                    processing_error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS life_commitments (
                    commitment_id TEXT PRIMARY KEY,
                    capture_id TEXT NOT NULL REFERENCES life_captures(capture_id),
                    title TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    state TEXT NOT NULL
                        CHECK (state IN (
                            'INBOX', 'READY_MACHINE', 'READY_HUMAN', 'SCHEDULED',
                            'WAITING', 'WATCHING', 'VERIFYING', 'REVIEW', 'DONE'
                        )),
                    next_condition TEXT NOT NULL
                        CHECK (length(trim(next_condition)) > 0),
                    next_condition_at TEXT,
                    confidence REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    UNIQUE (capture_id, title, owner)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_life_commitments_attention
                ON life_commitments(state, next_condition_at, updated_at DESC)
                """
            )

    def create_capture(self, raw_text: str, source: str = "manual") -> dict[str, Any]:
        if not raw_text.strip():
            raise ValueError("capture text must not be empty")
        if not source.strip():
            raise ValueError("capture source must not be empty")

        now = _utcnow()
        capture_id = _new_id("cap")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO life_captures (
                    capture_id, raw_text, source, captured_at,
                    processing_state, processing_error, updated_at
                ) VALUES (?, ?, ?, ?, 'NEW', '', ?)
                """,
                (capture_id, raw_text, source, now, now),
            )
        return self.get_capture(capture_id)

    def get_capture(self, capture_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM life_captures WHERE capture_id = ?", (capture_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"capture {capture_id} not found")
        return dict(row)

    def list_capture_commitments(self, capture_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM life_commitments
                WHERE capture_id = ?
                ORDER BY created_at ASC, commitment_id ASC
                """,
                (capture_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def process_capture(
        self,
        capture_id: str,
        extractor: Callable[[str], dict[str, Any]],
    ) -> dict[str, Any]:
        """Extract and project a capture without ever losing its raw row."""
        capture = self.get_capture(capture_id)
        if capture["processing_state"] == "PROCESSED":
            return self.capture_result(capture_id)

        now = _utcnow()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE life_captures
                SET processing_state = 'PROCESSING', processing_error = '', updated_at = ?
                WHERE capture_id = ?
                """,
                (now, capture_id),
            )

        try:
            extracted = extractor(str(capture["raw_text"])) or {}
            commitments = self._normalize_commitments(extracted)
            now = _utcnow()
            with self._connect() as conn:
                for commitment in commitments:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO life_commitments (
                            commitment_id, capture_id, title, owner, state,
                            next_condition, next_condition_at, confidence,
                            created_at, updated_at, completed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                        """,
                        (
                            _new_id("com"),
                            capture_id,
                            commitment["title"],
                            commitment["owner"],
                            commitment["state"],
                            commitment["next_condition"],
                            commitment["next_condition_at"],
                            commitment["confidence"],
                            now,
                            now,
                        ),
                    )
                conn.execute(
                    """
                    UPDATE life_captures
                    SET processing_state = 'PROCESSED', processing_error = '', updated_at = ?
                    WHERE capture_id = ?
                    """,
                    (now, capture_id),
                )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:1000]
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE life_captures
                    SET processing_state = 'FAILED', processing_error = ?, updated_at = ?
                    WHERE capture_id = ?
                    """,
                    (error, _utcnow(), capture_id),
                )

        return self.capture_result(capture_id)

    def capture_result(self, capture_id: str) -> dict[str, Any]:
        capture = self.get_capture(capture_id)
        return {
            "capture": capture,
            "commitments": self.list_capture_commitments(capture_id),
        }

    def list_failed_captures(self, limit: int = 25) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT capture_id, raw_text, source, captured_at, processing_state,
                       processing_error, updated_at
                FROM life_captures
                WHERE processing_state = 'FAILED'
                ORDER BY updated_at ASC, capture_id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def what_needs_me(self, limit: int = 25) -> dict[str, Any]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        now = _utcnow()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM life_commitments
                WHERE state IN ('READY_HUMAN', 'REVIEW')
                   OR (
                        state IN ('SCHEDULED', 'WAITING', 'WATCHING', 'VERIFYING')
                        AND next_condition_at IS NOT NULL
                        AND next_condition_at <= ?
                   )
                ORDER BY
                    CASE WHEN next_condition_at IS NULL THEN 1 ELSE 0 END,
                    next_condition_at ASC,
                    updated_at ASC,
                    commitment_id ASC
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()
        items = [dict(row) for row in rows]
        return {
            "checked_at": now,
            "needs_attention": bool(items),
            "message": "Nothing needs you." if not items else f"{len(items)} item(s) need you.",
            "items": items,
            "capture_failures": self.list_failed_captures(limit),
        }

    def list_open_commitments(self, limit: int = 25) -> list[dict[str, Any]]:
        """List durable LifeOps commitments that have not been completed."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM life_commitments
                WHERE state != 'DONE'
                ORDER BY
                    CASE WHEN next_condition_at IS NULL THEN 1 ELSE 0 END,
                    next_condition_at ASC,
                    updated_at DESC,
                    commitment_id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_commitment(self, commitment_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM life_commitments WHERE commitment_id = ?",
                (commitment_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"commitment {commitment_id} not found")
        return dict(row)

    def complete_commitment(self, commitment_id: str) -> dict[str, Any]:
        current = self.get_commitment(commitment_id)
        if current["state"] == "DONE":
            return current
        now = _utcnow()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE life_commitments
                SET state = 'DONE', completed_at = ?, updated_at = ?
                WHERE commitment_id = ?
                """,
                (now, now, commitment_id),
            )
        return self.get_commitment(commitment_id)

    @staticmethod
    def _normalize_commitments(extracted: dict[str, Any]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for value in extracted.get("commitments", []) or []:
            if isinstance(value, dict):
                candidates.append(value)
        for value in extracted.get("action_items", []) or []:
            if isinstance(value, str):
                candidates.append({"text": value})

        normalized: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for candidate in candidates:
            title = str(candidate.get("text") or candidate.get("title") or "").strip()
            if not title:
                continue
            owner_raw = str(candidate.get("owner") or "").strip()
            owner = "YOU" if owner_raw.lower() in {"", "i", "me", "self", "you"} else owner_raw
            state = "READY_HUMAN" if owner == "YOU" else "WAITING"
            next_condition = str(candidate.get("next_condition") or "").strip()
            if not next_condition:
                next_condition = (
                    "next reasonable available context"
                    if state == "READY_HUMAN"
                    else f"Awaiting progress from {owner}"
                )
            key = (title.casefold(), owner.casefold())
            if key in seen:
                continue
            seen.add(key)
            try:
                confidence = float(candidate.get("confidence", 0.9))
            except (TypeError, ValueError):
                confidence = 0.9
            normalized.append(
                {
                    "title": title,
                    "owner": owner,
                    "state": state,
                    "next_condition": next_condition,
                    "next_condition_at": candidate.get("deadline") or candidate.get("next_condition_at"),
                    "confidence": min(max(confidence, 0.0), 1.0),
                }
            )
        return normalized
