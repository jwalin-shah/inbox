"""
Connector infrastructure — Playwright profile management, state machine,
checkpoint logic. Each service connector inherits from BaseConnector.

Architecture:
    ~/.inbox/
    ├── browser-profiles/   <- persistent Playwright profiles
    │   ├── chatgpt/<id>/    <- one per account
    │   └── claude/<id>/
    ├── state/
    │   └── connector_state.db
    ├── raw/                 <- raw source JSON dumps
    └── normalized/          <- normalized JSONL output
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from loguru import logger

INBOX_DATA = Path.home() / ".inbox"
PROFILES_DIR = INBOX_DATA / "browser-profiles"
RAW_DIR = INBOX_DATA / "raw"
NORMALIZED_DIR = INBOX_DATA / "normalized"
STATE_DB = INBOX_DATA / "state" / "connector_state.db"

for d in [PROFILES_DIR, RAW_DIR, NORMALIZED_DIR, STATE_DB.parent]:
    d.mkdir(parents=True, exist_ok=True)


class AuthStatus(str, Enum):
    NEEDS_LOGIN = "needs_login"
    READY = "ready"
    EXPIRED = "expired"
    NEEDS_HUMAN = "needs_human_confirmation"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass
class SyncResult:
    """What a connector returns after a sync run."""

    items_synced: int = 0
    cursor: str | None = None
    checkpoint: str | None = None
    status: JobStatus = JobStatus.COMPLETE
    error: str | None = None
    raw_files: list[Path] = field(default_factory=list)


class BaseConnector(ABC):
    """Abstract connector — each service implements these methods."""

    service: str = ""          # "chatgpt", "claude", "gmail"
    account_id: str = ""       # email or account identifier

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.connector_id = f"{self.service}:{self.account_id}"
        self.profile_path = PROFILES_DIR / self.service / self.account_id
        self._db = sqlite3.connect(str(STATE_DB))
        self._init_db()

    def _init_db(self) -> None:
        self._db.execute(
            """INSERT OR IGNORE INTO connectors (connector_id, service, account_id, profile_path)
               VALUES (?, ?, ?, ?)""",
            (self.connector_id, self.service, self.account_id, str(self.profile_path)),
        )
        self._db.commit()

    # ── State management ──────────────────────────────────────────

    def _get_auth_status(self) -> AuthStatus:
        row = self._db.execute(
            "SELECT auth_status FROM connectors WHERE connector_id=?",
            (self.connector_id,),
        ).fetchone()
        return AuthStatus(row[0]) if row else AuthStatus.NEEDS_LOGIN

    def _set_auth_status(self, status: AuthStatus) -> None:
        self._db.execute(
            "UPDATE connectors SET auth_status=?, updated_at=? WHERE connector_id=?",
            (status.value, datetime.now(UTC).isoformat(), self.connector_id),
        )
        self._db.commit()

    def _set_cursor(self, cursor: str) -> None:
        self._db.execute(
            "UPDATE connectors SET sync_cursor=?, last_sync_at=?, updated_at=? WHERE connector_id=?",
            (cursor, datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat(), self.connector_id),
        )
        self._db.commit()

    def _get_cursor(self) -> str | None:
        row = self._db.execute(
            "SELECT sync_cursor FROM connectors WHERE connector_id=?", (self.connector_id,)
        ).fetchone()
        return row[0] if row else None

    def _get_checkpoint(self) -> str | None:
        row = self._db.execute(
            "SELECT checkpoint FROM connectors WHERE connector_id=?", (self.connector_id,)
        ).fetchone()
        return row[0] if row else None

    def _set_checkpoint(self, checkpoint: str) -> None:
        self._db.execute(
            "UPDATE connectors SET checkpoint=?, updated_at=? WHERE connector_id=?",
            (checkpoint, datetime.now(UTC).isoformat(), self.connector_id),
        )
        self._db.commit()

    def _create_job(self, job_type: str) -> str:
        job_id = str(uuid.uuid4())[:8]
        self._db.execute(
            "INSERT INTO sync_jobs (job_id, connector_id, job_type, status, started_at) VALUES (?,?,?,?,?)",
            (job_id, self.connector_id, job_type, JobStatus.RUNNING.value, datetime.now(UTC).isoformat()),
        )
        self._db.commit()
        return job_id

    def _complete_job(self, job_id: str, status: JobStatus, items: int = 0, error: str | None = None) -> None:
        self._db.execute(
            "UPDATE sync_jobs SET status=?, completed_at=?, items_synced=?, error=? WHERE job_id=?",
            (status.value, datetime.now(UTC).isoformat(), items, error, job_id),
        )
        self._db.commit()

    # ── Raw storage ───────────────────────────────────────────────

    def _save_raw(self, data: list[dict], batch_id: str) -> Path:
        path = RAW_DIR / self.service / self.account_id / f"{batch_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            for item in data:
                f.write(json.dumps(item) + "\n")
        return path

    # ── Normalization ─────────────────────────────────────────────

    def _normalize_conversation(self, conv: dict, source: str, account_id: str) -> dict:
        """Default normalizer — override per connector."""
        return {
            "id": f"{source}:{account_id}:{conv.get('id', uuid.uuid4().hex)}",
            "source": source,
            "account_id": account_id,
            "external_id": str(conv.get("id", "")),
            "title": conv.get("title", ""),
            "message_count": conv.get("message_count", 0),
            "metadata_json": json.dumps(conv.get("metadata", {})),
        }

    def _save_normalized(self, conversations: list[dict]) -> None:
        path = NORMALIZED_DIR / f"{self.service}-{self.account_id}.jsonl"
        with open(path, "a") as f:
            for conv in conversations:
                f.write(json.dumps(conv) + "\n")
        logger.info(f"Saved {len(conversations)} normalized records → {path}")

    # ── Verification ──────────────────────────────────────────────

    def _verify(self, expected_count: int, actual: int, batch_id: str) -> bool:
        match = expected_count == actual
        if not match:
            logger.error(f"Verify failed: expected {expected_count}, got {actual} for {batch_id}")
        else:
            logger.info(f"Verified: {actual} items in {batch_id}")
        return match

    def _hash_file(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    # ── Public API ────────────────────────────────────────────────

    @abstractmethod
    async def connect(self) -> bool:
        """Ensure we have a working authenticated session.
        Returns True if ready to sync, False if needs human intervention."""

    @abstractmethod
    async def probe(self) -> dict[str, Any]:
        """Verify account identity and capabilities. Returns account info dict."""

    @abstractmethod
    async def sync(self, job_id: str) -> SyncResult:
        """Retrieve new or changed objects since last cursor."""

    async def run(self, job_type: str = "incremental") -> SyncResult:
        """Full connector lifecycle: connect → probe → sync → checkpoint → verify."""
        status = self._get_auth_status()
        if status == AuthStatus.NEEDS_LOGIN:
            logger.info(f"{self.connector_id}: needs login")
            ready = await self.connect()
            if not ready:
                self._set_auth_status(AuthStatus.NEEDS_HUMAN)
                return SyncResult(status=JobStatus.FAILED, error="needs_human_login")

        info = await self.probe()
        logger.info(f"{self.connector_id}: connected as {info.get('email', '?')}")

        job_id = self._create_job(job_type)
        result = await self.sync(job_id)

        if result.status == JobStatus.COMPLETE and result.cursor:
            self._set_cursor(result.cursor)
        if result.checkpoint:
            self._set_checkpoint(result.checkpoint)

        self._complete_job(job_id, result.status, result.items_synced, result.error)
        return result
