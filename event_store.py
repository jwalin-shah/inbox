"""Append-only raw observation storage for the LifeOps evidence spine.

This store deliberately does not contain derived labels, tasks, entities, or
current-state projections.  It preserves the source observation so those
interpretations can be rebuilt later without rewriting history.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).parent
DEFAULT_EVENT_DB = BASE_DIR / ".inbox_event_log.sqlite3"
EVENT_SCHEMA_VERSION = "lifeops.event.v1"


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _json_dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _json_loads(value: str | None) -> object:
    return json.loads(value or "{}")


def _normalise_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return {str(key): item for key, item in (value or {}).items()}


def _normalise_timestamp(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return text


@dataclass(frozen=True)
class RawEvent:
    event_id: str
    source: str
    source_object_id: str
    observed_at: str
    occurred_at: str
    actor: dict[str, Any]
    object_data: dict[str, Any]
    event_type: str
    content_ref: str
    metadata: dict[str, Any]
    provenance: dict[str, Any]
    confidence: float
    payload: Any
    ingested_at: str
    schema_version: str = EVENT_SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        source: str,
        source_object_id: str,
        observed_at: str,
        occurred_at: str,
        event_type: str,
        payload: Any,
        actor: Mapping[str, Any] | None = None,
        object_data: Mapping[str, Any] | None = None,
        content_ref: str = "",
        metadata: Mapping[str, Any] | None = None,
        provenance: Mapping[str, Any] | None = None,
        confidence: float = 1.0,
        event_id: str | None = None,
    ) -> RawEvent:
        source_text = str(source or "").strip()
        event_type_text = str(event_type or "").strip()
        if not source_text:
            raise ValueError("source is required")
        if not event_type_text:
            raise ValueError("event_type is required")
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        observed_text = _normalise_timestamp(observed_at, "observed_at")
        occurred_text = _normalise_timestamp(occurred_at, "occurred_at")
        return cls(
            event_id=str(event_id or f"evt_{uuid.uuid4().hex}"),
            source=source_text,
            source_object_id=str(source_object_id or f"manual:{uuid.uuid4().hex}"),
            observed_at=observed_text,
            occurred_at=occurred_text,
            actor=_normalise_mapping(actor),
            object_data=_normalise_mapping(object_data),
            event_type=event_type_text,
            content_ref=str(content_ref or ""),
            metadata=_normalise_mapping(metadata),
            provenance=_normalise_mapping(provenance),
            confidence=float(confidence),
            payload=payload,
            ingested_at=_utcnow(),
        )

    @property
    def dedupe_key(self) -> str:
        value = {
            "source": self.source,
            "source_object_id": self.source_object_id,
            "occurred_at": self.occurred_at,
            "event_type": self.event_type,
            "payload": self.payload,
        }
        return hashlib.sha256(_json_dumps(value).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "source": self.source,
            "source_object_id": self.source_object_id,
            "observed_at": self.observed_at,
            "occurred_at": self.occurred_at,
            "actor": self.actor,
            "object": self.object_data,
            "event_type": self.event_type,
            "content_ref": self.content_ref,
            "metadata": self.metadata,
            "provenance": self.provenance,
            "confidence": self.confidence,
            "payload": self.payload,
            "ingested_at": self.ingested_at,
            "schema_version": self.schema_version,
        }


class RawEventStore:
    """SQLite-backed append-only event log.

    ``append`` is idempotent for the same source object, event type, timestamp,
    and payload.  There are intentionally no update or delete methods.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or DEFAULT_EVENT_DB
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

                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    dedupe_key TEXT NOT NULL UNIQUE,
                    schema_version TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_object_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    actor_json TEXT NOT NULL DEFAULT '{}',
                    object_json TEXT NOT NULL DEFAULT '{}',
                    event_type TEXT NOT NULL,
                    content_ref TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    provenance_json TEXT NOT NULL DEFAULT '{}',
                    confidence REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    ingested_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_events_occurred
                    ON events(occurred_at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_source
                    ON events(source, occurred_at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_type
                    ON events(event_type, occurred_at DESC);

                CREATE TABLE IF NOT EXISTS backfill_runs (
                    job_name TEXT PRIMARY KEY,
                    source TEXT NOT NULL DEFAULT '',
                    account TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    last_item_id INTEGER NOT NULL DEFAULT 0,
                    processed_count INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    completed_at TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT ''
                );
                """
            )

    def append(self, event: RawEvent) -> tuple[RawEvent, bool]:
        """Append an event, returning the stored event and whether it was new."""
        values = {
            "event_id": event.event_id,
            "dedupe_key": event.dedupe_key,
            "schema_version": event.schema_version,
            "source": event.source,
            "source_object_id": event.source_object_id,
            "observed_at": event.observed_at,
            "occurred_at": event.occurred_at,
            "actor_json": _json_dumps(event.actor),
            "object_json": _json_dumps(event.object_data),
            "event_type": event.event_type,
            "content_ref": event.content_ref,
            "metadata_json": _json_dumps(event.metadata),
            "provenance_json": _json_dumps(event.provenance),
            "confidence": event.confidence,
            "payload_json": _json_dumps(event.payload),
            "ingested_at": event.ingested_at,
        }
        with self._connect() as conn:
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO events (
                        event_id, dedupe_key, schema_version, source, source_object_id,
                        observed_at, occurred_at, actor_json, object_json, event_type,
                        content_ref, metadata_json, provenance_json, confidence,
                        payload_json, ingested_at
                    ) VALUES (
                        :event_id, :dedupe_key, :schema_version, :source, :source_object_id,
                        :observed_at, :occurred_at, :actor_json, :object_json, :event_type,
                        :content_ref, :metadata_json, :provenance_json, :confidence,
                        :payload_json, :ingested_at
                    ) ON CONFLICT(dedupe_key) DO NOTHING
                    """,
                    values,
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("event_id already belongs to a different event") from exc
            inserted = int(cursor.rowcount or 0) == 1
            if not inserted:
                row = conn.execute(
                    "SELECT * FROM events WHERE dedupe_key = ?", (event.dedupe_key,)
                ).fetchone()
                if row is None:
                    raise RuntimeError("event append conflict had no stored row")
                return self._row_to_event(row), False
            return event, True

    def append_many(self, events: list[RawEvent]) -> tuple[int, int]:
        """Append one batch atomically, returning ``(inserted, duplicates)``."""
        inserted = 0
        duplicates = 0
        with self._connect() as conn:
            for event in events:
                values = {
                    "event_id": event.event_id,
                    "dedupe_key": event.dedupe_key,
                    "schema_version": event.schema_version,
                    "source": event.source,
                    "source_object_id": event.source_object_id,
                    "observed_at": event.observed_at,
                    "occurred_at": event.occurred_at,
                    "actor_json": _json_dumps(event.actor),
                    "object_json": _json_dumps(event.object_data),
                    "event_type": event.event_type,
                    "content_ref": event.content_ref,
                    "metadata_json": _json_dumps(event.metadata),
                    "provenance_json": _json_dumps(event.provenance),
                    "confidence": event.confidence,
                    "payload_json": _json_dumps(event.payload),
                    "ingested_at": event.ingested_at,
                }
                try:
                    cursor = conn.execute(
                        """
                        INSERT INTO events (
                            event_id, dedupe_key, schema_version, source, source_object_id,
                            observed_at, occurred_at, actor_json, object_json, event_type,
                            content_ref, metadata_json, provenance_json, confidence,
                            payload_json, ingested_at
                        ) VALUES (
                            :event_id, :dedupe_key, :schema_version, :source, :source_object_id,
                            :observed_at, :occurred_at, :actor_json, :object_json, :event_type,
                            :content_ref, :metadata_json, :provenance_json, :confidence,
                            :payload_json, :ingested_at
                        ) ON CONFLICT(dedupe_key) DO NOTHING
                        """,
                        values,
                    )
                except sqlite3.IntegrityError as exc:
                    raise ValueError("event_id already belongs to a different event") from exc
                if int(cursor.rowcount or 0) == 1:
                    inserted += 1
                else:
                    duplicates += 1
        return inserted, duplicates

    def get(self, event_id: str) -> RawEvent | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
        return self._row_to_event(row) if row is not None else None

    def list_recent(
        self,
        *,
        limit: int = 100,
        source: str = "",
        event_type: str = "",
    ) -> list[RawEvent]:
        bounded_limit = max(1, min(int(limit), 500))
        clauses: list[str] = []
        params: list[str | int] = []
        if source:
            clauses.append("source = ?")
            params.append(source)
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM events {where} ORDER BY occurred_at DESC, event_id DESC LIMIT ?",  # noqa: S608
                (*params, bounded_limit),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def count(self, *, source: str = "") -> int:
        with self._connect() as conn:
            if source:
                row = conn.execute("SELECT count(*) FROM events WHERE source = ?", (source,)).fetchone()
            else:
                row = conn.execute("SELECT count(*) FROM events").fetchone()
        return int(row[0] if row else 0)

    def list_for_source_object(
        self, source: str, source_object_id: str, *, limit: int = 10
    ) -> list[RawEvent]:
        bounded_limit = max(1, min(int(limit), 100))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM events
                WHERE source = ? AND source_object_id = ?
                ORDER BY observed_at DESC, event_id DESC
                LIMIT ?
                """,
                (source, source_object_id, bounded_limit),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def get_backfill_state(self, job_name: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM backfill_runs WHERE job_name = ?", (job_name,)
            ).fetchone()
        return dict(row) if row is not None else None

    def set_backfill_state(
        self,
        *,
        job_name: str,
        source: str,
        account: str,
        status: str,
        last_item_id: int,
        processed_count: int,
        started_at: str = "",
        completed_at: str = "",
        last_error: str = "",
    ) -> None:
        now = _utcnow()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO backfill_runs (
                    job_name, source, account, status, last_item_id, processed_count,
                    started_at, updated_at, completed_at, last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_name) DO UPDATE SET
                    source=excluded.source,
                    account=excluded.account,
                    status=excluded.status,
                    last_item_id=excluded.last_item_id,
                    processed_count=excluded.processed_count,
                    started_at=excluded.started_at,
                    updated_at=excluded.updated_at,
                    completed_at=excluded.completed_at,
                    last_error=excluded.last_error
                """,
                (
                    job_name,
                    source,
                    account,
                    status,
                    int(last_item_id),
                    int(processed_count),
                    started_at,
                    now,
                    completed_at,
                    last_error,
                ),
            )

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> RawEvent:
        return RawEvent(
            event_id=row["event_id"],
            source=row["source"],
            source_object_id=row["source_object_id"],
            observed_at=row["observed_at"],
            occurred_at=row["occurred_at"],
            actor=_json_loads(row["actor_json"]),
            object_data=_json_loads(row["object_json"]),
            event_type=row["event_type"],
            content_ref=row["content_ref"],
            metadata=_json_loads(row["metadata_json"]),
            provenance=_json_loads(row["provenance_json"]),
            confidence=float(row["confidence"]),
            payload=_json_loads(row["payload_json"]),
            ingested_at=row["ingested_at"],
            schema_version=row["schema_version"],
        )
