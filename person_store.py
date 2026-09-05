"""Local, evidence-linked person profiles for LifeOps.

This store is deliberately separate from Apple/Google Contacts.  External
contacts provide identifiers and source facts; this store holds local notes,
relationship claims, and a stable profile projection without writing back to
those providers.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).parent
DEFAULT_PEOPLE_DB = BASE_DIR / ".inbox_people.sqlite3"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _norm_identifier(value: str) -> tuple[str, str]:
    raw = str(value or "").strip()
    lowered = raw.casefold()
    if "@" in lowered:
        return "email", lowered
    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 7:
        return "phone", digits[-10:]
    return "alias", lowered


def person_id_for_external(external_id: str) -> str:
    kind, value = _norm_identifier(external_id)
    digest = hashlib.sha256(f"{kind}:{value}".encode()).hexdigest()[:20]
    return f"person_{digest}"


class PersonProfileStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or DEFAULT_PEOPLE_DB
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

                CREATE TABLE IF NOT EXISTS people (
                    person_id TEXT PRIMARY KEY,
                    external_contact_id TEXT NOT NULL DEFAULT '',
                    display_name TEXT NOT NULL DEFAULT '',
                    external_contact_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS person_identifiers (
                    person_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    value_norm TEXT NOT NULL,
                    value_display TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'contacts',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    confirmed INTEGER NOT NULL DEFAULT 0,
                    observed_at TEXT NOT NULL,
                    PRIMARY KEY (person_id, kind, value_norm),
                    FOREIGN KEY (person_id) REFERENCES people(person_id)
                );

                CREATE TABLE IF NOT EXISTS person_notes (
                    note_id TEXT PRIMARY KEY,
                    person_id TEXT NOT NULL,
                    body TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'manual',
                    source_ref TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    confirmed INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (person_id) REFERENCES people(person_id)
                );

                CREATE TABLE IF NOT EXISTS person_relationships (
                    relationship_id TEXT PRIMARY KEY,
                    person_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    context TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'manual',
                    source_ref TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    confirmed INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (person_id) REFERENCES people(person_id)
                );

                CREATE INDEX IF NOT EXISTS idx_people_name ON people(display_name);
                CREATE INDEX IF NOT EXISTS idx_person_identifiers_value
                    ON person_identifiers(kind, value_norm);
                CREATE INDEX IF NOT EXISTS idx_person_notes_person
                    ON person_notes(person_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_person_relationships_person
                    ON person_relationships(person_id, created_at DESC);
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(people)").fetchall()}
            if "external_contact_json" not in columns:
                conn.execute(
                    "ALTER TABLE people ADD COLUMN external_contact_json TEXT NOT NULL DEFAULT '{}'"
                )

    def ensure_external_contact(self, contact: dict[str, Any]) -> str:
        external_id = str(contact.get("id") or "").strip()
        if not external_id:
            raise ValueError("contact id is required")
        person_id = person_id_for_external(external_id)
        now = _now()
        name = str(contact.get("name") or external_id).strip()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO people (
                    person_id, external_contact_id, display_name, external_contact_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(person_id) DO UPDATE SET
                    external_contact_id=excluded.external_contact_id,
                    external_contact_json=excluded.external_contact_json,
                    display_name=CASE
                        WHEN excluded.display_name != '' THEN excluded.display_name
                        ELSE people.display_name
                    END,
                    updated_at=excluded.updated_at
                """,
                (person_id, external_id, name, _json(contact), now, now),
            )
            identifiers: list[tuple[str, str]] = [("contact_id", external_id)]
            identifiers.extend(("email", str(value)) for value in contact.get("emails", []) or [])
            identifiers.extend(("phone", str(value)) for value in contact.get("phones", []) or [])
            for kind, raw in identifiers:
                normalized_kind, normalized = _norm_identifier(raw)
                kind = "contact_id" if kind == "contact_id" else normalized_kind
                if not normalized:
                    continue
                conn.execute(
                    """
                    INSERT INTO person_identifiers (
                        person_id, kind, value_norm, value_display, source,
                        confidence, confirmed, observed_at
                    ) VALUES (?, ?, ?, ?, 'contacts', 1.0, 0, ?)
                    ON CONFLICT(person_id, kind, value_norm) DO UPDATE SET
                        value_display=excluded.value_display,
                        observed_at=excluded.observed_at
                    """,
                    (person_id, kind, normalized, raw.strip(), now),
                )
        return person_id

    def get_profile(self, person_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            person = conn.execute(
                "SELECT * FROM people WHERE person_id = ?", (person_id,)
            ).fetchone()
            if person is None:
                return None
            identifiers = conn.execute(
                "SELECT kind, value_norm, value_display, source, confidence, confirmed, observed_at "
                "FROM person_identifiers WHERE person_id = ? ORDER BY kind, value_display",
                (person_id,),
            ).fetchall()
            notes = conn.execute(
                "SELECT note_id, body, source, source_ref, confidence, confirmed, created_at, expires_at "
                "FROM person_notes WHERE person_id = ? ORDER BY created_at DESC",
                (person_id,),
            ).fetchall()
            relationships = conn.execute(
                "SELECT relationship_id, label, context, source, source_ref, confidence, confirmed, created_at "
                "FROM person_relationships WHERE person_id = ? ORDER BY created_at DESC",
                (person_id,),
            ).fetchall()
        person_data = dict(person)
        external_contact_raw = person_data.pop("external_contact_json", "{}")
        try:
            external_contact = json.loads(external_contact_raw or "{}")
        except json.JSONDecodeError:
            external_contact = {}
        return {
            "person": person_data,
            "external_contact": external_contact,
            "identifiers": [dict(row) for row in identifiers],
            "notes": [dict(row) for row in notes],
            "relationships": [dict(row) for row in relationships],
            "authority_rule": "External contacts provide source identifiers; local notes and relationship claims are separate LifeOps data.",
        }

    def search(self, query: str = "", limit: int = 20) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 100))
        q = str(query or "").strip().casefold()
        with self._connect() as conn:
            if q:
                like = f"%{q}%"
                rows = conn.execute(
                    """
                    SELECT DISTINCT p.*
                    FROM people p
                    LEFT JOIN person_identifiers i ON i.person_id = p.person_id
                    WHERE lower(p.display_name) LIKE ?
                       OR lower(p.external_contact_id) LIKE ?
                       OR lower(i.value_norm) LIKE ?
                       OR lower(i.value_display) LIKE ?
                    ORDER BY p.display_name, p.person_id
                    LIMIT ?
                    """,
                    (like, like, like, like, bounded),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM people ORDER BY updated_at DESC, display_name LIMIT ?",
                    (bounded,),
                ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            profile = self.get_profile(str(row["person_id"]))
            if profile:
                result.append(profile)
        return result

    def add_note(
        self,
        person_id: str,
        *,
        body: str,
        source: str = "manual",
        source_ref: str = "",
        confidence: float = 1.0,
        confirmed: bool = True,
        expires_at: str = "",
    ) -> dict[str, Any]:
        if not body.strip():
            raise ValueError("note body is required")
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.get_profile(person_id) is None:
            raise KeyError("person not found")
        note = {
            "note_id": f"note_{uuid.uuid4().hex}",
            "person_id": person_id,
            "body": body.strip(),
            "source": source.strip() or "manual",
            "source_ref": source_ref.strip(),
            "confidence": float(confidence),
            "confirmed": int(bool(confirmed)),
            "created_at": _now(),
            "expires_at": expires_at.strip(),
        }
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO person_notes (
                    note_id, person_id, body, source, source_ref, confidence,
                    confirmed, created_at, expires_at
                ) VALUES (:note_id, :person_id, :body, :source, :source_ref,
                          :confidence, :confirmed, :created_at, :expires_at)""",
                note,
            )
        return note

    def add_relationship(
        self,
        person_id: str,
        *,
        label: str,
        context: str = "",
        source: str = "manual",
        source_ref: str = "",
        confidence: float = 1.0,
        confirmed: bool = True,
    ) -> dict[str, Any]:
        if not label.strip():
            raise ValueError("relationship label is required")
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.get_profile(person_id) is None:
            raise KeyError("person not found")
        relationship = {
            "relationship_id": f"rel_{uuid.uuid4().hex}",
            "person_id": person_id,
            "label": label.strip(),
            "context": context.strip(),
            "source": source.strip() or "manual",
            "source_ref": source_ref.strip(),
            "confidence": float(confidence),
            "confirmed": int(bool(confirmed)),
            "created_at": _now(),
        }
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO person_relationships (
                    relationship_id, person_id, label, context, source, source_ref,
                    confidence, confirmed, created_at
                ) VALUES (:relationship_id, :person_id, :label, :context, :source,
                          :source_ref, :confidence, :confirmed, :created_at)""",
                relationship,
            )
        return relationship
