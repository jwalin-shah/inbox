"""Durable, provenance-linked identity decisions for the local LifeOps layer.

This store does not modify Apple or Google Contacts.  It records only an
explicitly approved link between a canonical LifeOps person and a source
record, so later projections can reuse the decision without re-inferring it.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).parent
DEFAULT_IDENTITY_LINKS_DB = BASE_DIR / ".inbox_identity_links.sqlite3"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


class IdentityLinkStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or DEFAULT_IDENTITY_LINKS_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS identity_links (
                    link_id TEXT PRIMARY KEY,
                    canonical_person_id TEXT NOT NULL,
                    canonical_name TEXT NOT NULL DEFAULT '',
                    target_source TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    target_name TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    confirmed INTEGER NOT NULL DEFAULT 1,
                    source_refs_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    UNIQUE(canonical_person_id, target_source, target_id)
                );
                CREATE INDEX IF NOT EXISTS idx_identity_links_person
                    ON identity_links(canonical_person_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_identity_links_target
                    ON identity_links(target_source, target_id);
                """
            )

    def add_link(
        self,
        *,
        canonical_person_id: str,
        canonical_name: str,
        target_source: str,
        target_id: str,
        target_name: str,
        confidence: float = 1.0,
        confirmed: bool = True,
        source_refs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        canonical_person_id = canonical_person_id.strip()
        target_source = target_source.strip()
        target_id = target_id.strip()
        if not canonical_person_id or not target_source or not target_id:
            raise ValueError("canonical_person_id, target_source, and target_id are required")
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        refs = [ref for ref in (source_refs or []) if isinstance(ref, dict)]
        link = {
            "link_id": f"identity_link_{uuid.uuid4().hex}",
            "canonical_person_id": canonical_person_id,
            "canonical_name": canonical_name.strip(),
            "target_source": target_source,
            "target_id": target_id,
            "target_name": target_name.strip(),
            "confidence": float(confidence),
            "confirmed": int(bool(confirmed)),
            "source_refs": refs,
            "created_at": _now(),
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO identity_links (
                    link_id, canonical_person_id, canonical_name, target_source,
                    target_id, target_name, confidence, confirmed,
                    source_refs_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(canonical_person_id, target_source, target_id) DO UPDATE SET
                    canonical_name=excluded.canonical_name,
                    target_name=excluded.target_name,
                    confidence=excluded.confidence,
                    confirmed=excluded.confirmed,
                    source_refs_json=excluded.source_refs_json
                """,
                (
                    link["link_id"],
                    link["canonical_person_id"],
                    link["canonical_name"],
                    link["target_source"],
                    link["target_id"],
                    link["target_name"],
                    link["confidence"],
                    link["confirmed"],
                    _json(refs),
                    link["created_at"],
                ),
            )
            row = conn.execute(
                """
                SELECT link_id, canonical_person_id, canonical_name, target_source,
                       target_id, target_name, confidence, confirmed,
                       source_refs_json, created_at
                FROM identity_links
                WHERE canonical_person_id = ? AND target_source = ? AND target_id = ?
                """,
                (canonical_person_id, target_source, target_id),
            ).fetchone()
        if row is None:
            raise RuntimeError("identity link write did not return a row")
        return self._row_to_dict(row)

    def list_links(
        self,
        *,
        canonical_person_id: str = "",
        target_source: str = "",
        target_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        for column, value in (
            ("canonical_person_id", canonical_person_id),
            ("target_source", target_source),
            ("target_id", target_id),
        ):
            if value.strip():
                clauses.append(f"{column} = ?")
                values.append(value.strip())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        bounded = max(1, min(int(limit), 500))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT link_id, canonical_person_id, canonical_name, target_source,
                       target_id, target_name, confidence, confirmed,
                       source_refs_json, created_at
                FROM identity_links {where}
                ORDER BY created_at DESC, link_id DESC LIMIT ?
                """,
                (*values, bounded),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        try:
            item["source_refs"] = json.loads(item.pop("source_refs_json") or "[]")
        except json.JSONDecodeError:
            item["source_refs"] = []
        item["confirmed"] = bool(item["confirmed"])
        return item
