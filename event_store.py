"""Append-only local capture log.

PR-0 atom only. Retries are idempotent. Conflicting same-id payloads fail closed.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

BASE_DIR = Path(__file__).parent
DEFAULT_EVENT_DB = BASE_DIR / ".inbox_event_log.sqlite3"
EVENT_SCHEMA_VERSION = "inbox.capture.v1"
MAX_PAYLOAD_BYTES = 65536
SOURCE_REF_RE = re.compile(
    r"^(manual|inbox|test|gmail|imessage|local):[A-Za-z0-9][A-Za-z0-9._:/-]{0,240}$"
)

# GitHits: unique event_id + payload hash conflict; WAL; triggers abort
# UPDATE/DELETE on the events table.


class EventStoreValidationError(ValueError):
    """Malformed capture observation."""


class EventStoreConflict(EventStoreValidationError):
    """event_id already stores a different observation."""


def _json_dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _json_loads(value: str | None) -> Any:
    return json.loads(value or "null")


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalise_timestamp(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise EventStoreValidationError(f"{field_name} is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EventStoreValidationError(f"{field_name} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise EventStoreValidationError(f"{field_name} must include a timezone")
    return text


def _validate_source_ref(source_ref: str) -> str:
    text = str(source_ref or "").strip()
    if not text:
        raise EventStoreValidationError("provenance.source_ref is required")
    if ".." in text or "://" in text:
        raise EventStoreValidationError("provenance.source_ref is untrusted")
    if not SOURCE_REF_RE.fullmatch(text):
        raise EventStoreValidationError("provenance.source_ref is malformed")
    return text


def identity_digest_for(
    *,
    source: str,
    source_object_id: str,
    occurred_at: str,
    event_type: str,
    payload: Any,
    source_ref: str,
) -> str:
    canonical = {
        "source": source,
        "source_object_id": source_object_id,
        "occurred_at": occurred_at,
        "event_type": event_type,
        "payload": payload,
        "source_ref": source_ref,
    }
    return hashlib.sha256(_json_dumps(canonical).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CaptureEvent:
    event_id: str
    source: str
    source_object_id: str
    observed_at: str
    occurred_at: str
    event_type: str
    payload: Any
    provenance: dict[str, str]
    ingested_at: str
    identity_digest: str
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
        provenance: dict[str, Any] | None,
        event_id: str | None = None,
        ingested_at: str | None = None,
    ) -> CaptureEvent:
        source_text = str(source or "").strip()
        event_type_text = str(event_type or "").strip()
        object_id = str(source_object_id or "").strip()
        if not source_text:
            raise EventStoreValidationError("source is required")
        if not event_type_text:
            raise EventStoreValidationError("event_type is required")
        if not object_id:
            raise EventStoreValidationError("source_object_id is required")
        if not isinstance(provenance, dict) or not provenance:
            raise EventStoreValidationError("provenance is required")
        source_ref = _validate_source_ref(str(provenance.get("source_ref", "")))
        if payload is None:
            raise EventStoreValidationError("payload is required")
        encoded_payload = _json_dumps(payload)
        if len(encoded_payload.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise EventStoreValidationError("payload is oversized")
        occurred = _normalise_timestamp(occurred_at, "occurred_at")
        observed = _normalise_timestamp(observed_at, "observed_at")
        digest = identity_digest_for(
            source=source_text,
            source_object_id=object_id,
            occurred_at=occurred,
            event_type=event_type_text,
            payload=payload,
            source_ref=source_ref,
        )
        computed_id = f"evt_{digest[:32]}"
        supplied = str(event_id or "").strip()
        return cls(
            event_id=supplied or computed_id,
            source=source_text,
            source_object_id=object_id,
            observed_at=observed,
            occurred_at=occurred,
            event_type=event_type_text,
            payload=payload,
            provenance={"source_ref": source_ref},
            ingested_at=ingested_at or _utcnow(),
            identity_digest=digest,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "source": self.source,
            "source_object_id": self.source_object_id,
            "observed_at": self.observed_at,
            "occurred_at": self.occurred_at,
            "event_type": self.event_type,
            "payload": self.payload,
            "provenance": self.provenance,
            "ingested_at": self.ingested_at,
            "schema_version": self.schema_version,
        }


class EventStore:
    """SQLite-backed append-only capture log."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or DEFAULT_EVENT_DB
        self._ready = False

    def _connect(self) -> sqlite3.Connection:
        if not self._ready:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_db()
            self._ready = True
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    identity_digest TEXT NOT NULL UNIQUE,
                    schema_version TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_object_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    provenance_json TEXT NOT NULL,
                    ingested_at TEXT NOT NULL
                );

                CREATE TRIGGER IF NOT EXISTS events_append_only_update
                BEFORE UPDATE ON events
                BEGIN
                    SELECT RAISE(ABORT, 'events are append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS events_append_only_delete
                BEFORE DELETE ON events
                BEGIN
                    SELECT RAISE(ABORT, 'events are append-only');
                END;
                """
            )
        finally:
            conn.close()

    def append(
        self, event: CaptureEvent
    ) -> tuple[CaptureEvent, Literal["created", "already_exists"]]:
        values = {
            "event_id": event.event_id,
            "identity_digest": event.identity_digest,
            "schema_version": event.schema_version,
            "source": event.source,
            "source_object_id": event.source_object_id,
            "observed_at": event.observed_at,
            "occurred_at": event.occurred_at,
            "event_type": event.event_type,
            "payload_json": _json_dumps(event.payload),
            "provenance_json": _json_dumps(event.provenance),
            "ingested_at": event.ingested_at,
        }
        with self._connect() as conn:
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO events (
                        event_id, identity_digest, schema_version, source,
                        source_object_id, observed_at, occurred_at, event_type,
                        payload_json, provenance_json, ingested_at
                    ) VALUES (
                        :event_id, :identity_digest, :schema_version, :source,
                        :source_object_id, :observed_at, :occurred_at, :event_type,
                        :payload_json, :provenance_json, :ingested_at
                    )
                    """,
                    values,
                )
            except sqlite3.IntegrityError as exc:
                by_id = conn.execute(
                    "SELECT * FROM events WHERE event_id = ?", (event.event_id,)
                ).fetchone()
                by_digest = conn.execute(
                    "SELECT * FROM events WHERE identity_digest = ?",
                    (event.identity_digest,),
                ).fetchone()
                if by_id is not None:
                    stored = self._row_to_event(by_id)
                    if stored.identity_digest != event.identity_digest:
                        raise EventStoreConflict(
                            "event_id already belongs to a different event"
                        ) from exc
                    return stored, "already_exists"
                if by_digest is not None:
                    stored = self._row_to_event(by_digest)
                    if stored.event_id != event.event_id:
                        raise EventStoreConflict(
                            "event_id already belongs to a different event"
                        ) from exc
                    return stored, "already_exists"
                raise EventStoreValidationError("capture insert conflict") from exc
            if int(cursor.rowcount or 0) != 1:
                raise EventStoreValidationError("capture insert did not persist")
            return event, "created"

    def get(self, event_id: str) -> CaptureEvent | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
        return self._row_to_event(row) if row is not None else None

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT count(*) FROM events").fetchone()
        return int(row[0] if row else 0)

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> CaptureEvent:
        return CaptureEvent(
            event_id=row["event_id"],
            source=row["source"],
            source_object_id=row["source_object_id"],
            observed_at=row["observed_at"],
            occurred_at=row["occurred_at"],
            event_type=row["event_type"],
            payload=_json_loads(row["payload_json"]),
            provenance=_json_loads(row["provenance_json"]),
            ingested_at=row["ingested_at"],
            identity_digest=row["identity_digest"],
            schema_version=row["schema_version"],
        )
