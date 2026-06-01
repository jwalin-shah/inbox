"""
Scheduler persistence layer — SQLite-backed storage for message scheduling,
follow-up reminders, and task↔message links. Pattern mirrors memory_store.py.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).parent
SCHEDULER_DB = BASE_DIR / ".inbox_scheduler.sqlite3"


@dataclass
class ScheduledMessage:
    id: int | None = None
    source: str = ""  # "gmail" | "imessage"
    conv_id: str = ""
    text: str = ""
    send_at: str = ""  # ISO datetime
    status: str = "pending"  # "pending" | "sent" | "cancelled" | "failed"
    account: str = ""  # Gmail account
    created_at: str = ""
    sent_at: str | None = None
    error: str | None = None


@dataclass
class FollowupReminder:
    id: int | None = None
    source: str = ""  # "gmail" | "imessage"
    conv_id: str = ""
    thread_id: str = ""  # Gmail thread_id
    remind_after: str = ""  # ISO datetime
    reminder_title: str = ""
    reminder_list: str = "Reminders"
    status: str = "active"  # "active" | "fired" | "cancelled" | "replied"
    created_at: str = ""
    fired_at: str | None = None


@dataclass
class TaskMessageLink:
    id: int | None = None
    task_id: str = ""  # Google Task id OR reminder_id
    task_source: str = ""  # "google_tasks" | "reminders"
    message_id: str = ""  # Gmail msg_id OR iMessage conv_id
    message_source: str = ""  # "gmail" | "imessage"
    thread_id: str = ""
    account: str = ""
    created_at: str = ""


@dataclass
class SchedulerApprovalProposal:
    id: int | None = None
    proposal_id: str = ""
    scheduler_kind: str = ""
    scheduler_row_id: int = 0
    provider: str = ""
    operation: str = ""
    executor: str = "inbox.scheduler.execute"
    account_ref: str = ""
    resource_ref: str = ""
    item_count: int = 1
    payload_hash: str = ""
    query_hash: str = ""
    normalized_intent_hash: str = ""
    preview_json: str = "{}"
    state: str = "proposal_pending"
    created_at: str = ""
    approved_at: str | None = None
    approved_by: str = ""
    approval_expires_at: str | None = None
    revoked_at: str | None = None
    denial_reason: str = ""


@dataclass
class SchedulerExecutionLease:
    id: int | None = None
    lease_id: str = ""
    proposal_id: str = ""
    scheduler_kind: str = ""
    scheduler_row_id: int = 0
    provider: str = ""
    operation: str = ""
    executor: str = "inbox.scheduler.execute"
    payload_hash: str = ""
    query_hash: str = ""
    normalized_intent_hash: str = ""
    not_after: str = ""
    allowed_uses: int = 1
    spent: int = 0
    created_at: str = ""


@dataclass
class SchedulerExecutionReceipt:
    id: int | None = None
    execution_id: str = ""
    proposal_id: str = ""
    lease_id: str = ""
    scheduler_kind: str = ""
    scheduler_row_id: int = 0
    provider: str = ""
    operation: str = ""
    status: str = ""
    changed_count: int = 0
    provider_receipt_hash: str = ""
    error: str = ""
    created_at: str = ""


def canonical_json_hash(value: dict[str, Any]) -> str:
    """Return a stable hash for scheduler approval intent material."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def scheduler_query_hash() -> str:
    return canonical_json_hash({})


def _proposal_id() -> str:
    return f"sched_prop_{uuid.uuid4().hex}"


def scheduled_message_intent(
    scheduler_row_id: int,
    source: str,
    conv_id: str,
    text: str,
    send_at: str,
    account: str,
) -> dict[str, Any]:
    payload = {
        "source": source,
        "conv_id": conv_id,
        "text": text,
        "send_at": send_at,
        "account": account,
    }
    return {
        "scheduler_kind": "scheduled_message",
        "scheduler_row_id": scheduler_row_id,
        "provider": source,
        "operation": "scheduled_send",
        "executor": "inbox.scheduler.execute",
        "account_ref": account,
        "resource_ref": conv_id,
        "item_count": 1,
        "payload": payload,
        "payload_hash": canonical_json_hash(payload),
        "query_hash": scheduler_query_hash(),
    }


def followup_intent(
    scheduler_row_id: int,
    source: str,
    conv_id: str,
    thread_id: str,
    remind_after: str,
    reminder_title: str,
    reminder_list: str,
) -> dict[str, Any]:
    payload = {
        "source": source,
        "conv_id": conv_id,
        "thread_id": thread_id,
        "remind_after": remind_after,
        "reminder_title": reminder_title,
        "reminder_list": reminder_list,
    }
    return {
        "scheduler_kind": "followup_reminder",
        "scheduler_row_id": scheduler_row_id,
        "provider": "google_tasks",
        "operation": "followup_task_create",
        "executor": "inbox.scheduler.execute",
        "account_ref": "",
        "resource_ref": thread_id or conv_id,
        "item_count": 1,
        "payload": payload,
        "payload_hash": canonical_json_hash(payload),
        "query_hash": scheduler_query_hash(),
    }


def normalized_intent_hash(intent: dict[str, Any]) -> str:
    return canonical_json_hash(intent)


def preview_for_intent(intent: dict[str, Any]) -> dict[str, Any]:
    payload = intent.get("payload", {})
    preview: dict[str, Any] = {
        "scheduler_kind": intent["scheduler_kind"],
        "provider": intent["provider"],
        "operation": intent["operation"],
        "resource_ref": intent["resource_ref"],
    }
    if intent["scheduler_kind"] == "scheduled_message":
        preview["send_at"] = payload.get("send_at", "")
        preview["text_chars"] = len(str(payload.get("text", "")))
    elif intent["scheduler_kind"] == "followup_reminder":
        preview["remind_after"] = payload.get("remind_after", "")
        preview["reminder_title"] = payload.get("reminder_title", "")
    return preview


class SchedulerStore:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or SCHEDULER_DB
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path, timeout=5.0) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduled_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    conv_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    send_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    account TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    sent_at TEXT,
                    error TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS followup_reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    conv_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL DEFAULT '',
                    remind_after TEXT NOT NULL,
                    reminder_title TEXT NOT NULL,
                    reminder_list TEXT NOT NULL DEFAULT 'Reminders',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    fired_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_message_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    task_source TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    message_source TEXT NOT NULL,
                    thread_id TEXT NOT NULL DEFAULT '',
                    account TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            self._ensure_approval_schema(conn)
            self._migrate_legacy_approval_state(conn)
            conn.commit()

    def _ensure_approval_schema(self, conn: sqlite3.Connection) -> None:
        self._add_column_if_missing(
            conn,
            "scheduled_messages",
            "proposal_id",
            "TEXT NOT NULL DEFAULT ''",
        )
        self._add_column_if_missing(
            conn,
            "scheduled_messages",
            "intent_hash",
            "TEXT NOT NULL DEFAULT ''",
        )
        self._add_column_if_missing(
            conn,
            "scheduled_messages",
            "approval_state",
            "TEXT NOT NULL DEFAULT 'missing'",
        )
        self._add_column_if_missing(
            conn,
            "scheduled_messages",
            "last_execution_id",
            "TEXT NOT NULL DEFAULT ''",
        )
        self._add_column_if_missing(
            conn,
            "followup_reminders",
            "proposal_id",
            "TEXT NOT NULL DEFAULT ''",
        )
        self._add_column_if_missing(
            conn,
            "followup_reminders",
            "intent_hash",
            "TEXT NOT NULL DEFAULT ''",
        )
        self._add_column_if_missing(
            conn,
            "followup_reminders",
            "approval_state",
            "TEXT NOT NULL DEFAULT 'missing'",
        )
        self._add_column_if_missing(
            conn,
            "followup_reminders",
            "last_execution_id",
            "TEXT NOT NULL DEFAULT ''",
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduler_proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proposal_id TEXT NOT NULL UNIQUE,
                scheduler_kind TEXT NOT NULL,
                scheduler_row_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                operation TEXT NOT NULL,
                executor TEXT NOT NULL,
                account_ref TEXT NOT NULL DEFAULT '',
                resource_ref TEXT NOT NULL,
                item_count INTEGER NOT NULL DEFAULT 1,
                payload_hash TEXT NOT NULL,
                query_hash TEXT NOT NULL,
                normalized_intent_hash TEXT NOT NULL,
                preview_json TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                approved_at TEXT,
                approved_by TEXT NOT NULL DEFAULT '',
                approval_expires_at TEXT,
                revoked_at TEXT,
                denial_reason TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduler_execution_leases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lease_id TEXT NOT NULL UNIQUE,
                proposal_id TEXT NOT NULL,
                scheduler_kind TEXT NOT NULL,
                scheduler_row_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                operation TEXT NOT NULL,
                executor TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                query_hash TEXT NOT NULL,
                normalized_intent_hash TEXT NOT NULL,
                not_after TEXT NOT NULL,
                allowed_uses INTEGER NOT NULL DEFAULT 1,
                spent INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduler_execution_receipts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                execution_id TEXT NOT NULL UNIQUE,
                proposal_id TEXT NOT NULL,
                lease_id TEXT NOT NULL,
                scheduler_kind TEXT NOT NULL,
                scheduler_row_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                operation TEXT NOT NULL,
                status TEXT NOT NULL,
                changed_count INTEGER NOT NULL DEFAULT 0,
                provider_receipt_hash TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )

    def _add_column_if_missing(
        self, conn: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _migrate_legacy_approval_state(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            UPDATE scheduled_messages
            SET approval_state = 'blocked_missing_approval'
            WHERE status = 'pending'
              AND proposal_id = ''
              AND approval_state IN ('', 'missing', 'blocked_missing_approval')
            """
        )
        conn.execute(
            """
            UPDATE followup_reminders
            SET approval_state = 'blocked_missing_approval'
            WHERE status = 'active'
              AND proposal_id = ''
              AND approval_state IN ('', 'missing', 'blocked_missing_approval')
            """
        )

    def _create_scheduler_proposal(
        self, conn: sqlite3.Connection, intent: dict[str, Any], created_at: str
    ) -> dict[str, Any]:
        proposal_id = _proposal_id()
        intent_hash = normalized_intent_hash(intent)
        preview_json = json.dumps(
            preview_for_intent(intent),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        conn.execute(
            """
            INSERT INTO scheduler_proposals
            (
                proposal_id, scheduler_kind, scheduler_row_id, provider, operation,
                executor, account_ref, resource_ref, item_count, payload_hash,
                query_hash, normalized_intent_hash, preview_json, state, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proposal_id,
                intent["scheduler_kind"],
                intent["scheduler_row_id"],
                intent["provider"],
                intent["operation"],
                intent["executor"],
                intent["account_ref"],
                intent["resource_ref"],
                intent["item_count"],
                intent["payload_hash"],
                intent["query_hash"],
                intent_hash,
                preview_json,
                "proposal_pending",
                created_at,
            ),
        )
        return {
            "proposal_id": proposal_id,
            "intent_hash": intent_hash,
            "approval_state": "proposal_pending",
            "preview": json.loads(preview_json),
        }

    # ── Scheduled Messages ──────────────────────────────────────────────

    def schedule_message(
        self,
        source: str,
        conv_id: str,
        text: str,
        send_at: str,
        account: str = "",
    ) -> dict[str, Any]:
        """Schedule a message to be sent at a future time."""
        with self._lock:  # noqa: SIM117
            with sqlite3.connect(self.db_path, timeout=5.0) as conn:
                created_at = datetime.now().isoformat()
                conn.execute(
                    """
                    INSERT INTO scheduled_messages (source, conv_id, text, send_at, status, account, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (source, conv_id, text, send_at, "pending", account, created_at),
                )
                msg_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                intent = scheduled_message_intent(
                    msg_id,
                    source,
                    conv_id,
                    text,
                    send_at,
                    account,
                )
                approval = self._create_scheduler_proposal(conn, intent, created_at)
                conn.execute(
                    """
                    UPDATE scheduled_messages
                    SET proposal_id = ?, intent_hash = ?, approval_state = ?
                    WHERE id = ?
                    """,
                    (
                        approval["proposal_id"],
                        approval["intent_hash"],
                        approval["approval_state"],
                        msg_id,
                    ),
                )
                conn.commit()
                return {
                    "id": msg_id,
                    "source": source,
                    "conv_id": conv_id,
                    "text": text,
                    "send_at": send_at,
                    "status": "pending",
                    "account": account,
                    "created_at": created_at,
                    **approval,
                }

    def cancel_scheduled(self, msg_id: int) -> bool:
        """Cancel a scheduled message."""
        with self._lock, sqlite3.connect(self.db_path, timeout=5.0) as conn:
            conn.execute(
                "UPDATE scheduled_messages SET status = 'cancelled' WHERE id = ?", (msg_id,)
            )
            conn.commit()
            return True

    def list_scheduled(self, status: str = "pending") -> list[dict[str, Any]]:
        """List scheduled messages by status."""
        with self._lock, sqlite3.connect(self.db_path, timeout=5.0) as conn:
            rows = conn.execute(
                "SELECT * FROM scheduled_messages WHERE status = ? ORDER BY send_at ASC", (status,)
            ).fetchall()
            return [
                {
                    "id": r[0],
                    "source": r[1],
                    "conv_id": r[2],
                    "text": r[3],
                    "send_at": r[4],
                    "status": r[5],
                    "account": r[6],
                    "created_at": r[7],
                    "sent_at": r[8],
                    "error": r[9],
                    "proposal_id": r[10],
                    "intent_hash": r[11],
                    "approval_state": r[12],
                    "last_execution_id": r[13],
                }
                for r in rows
            ]

    def get_due_messages(self) -> list[dict[str, Any]]:
        """Get messages that are due to send (send_at <= now)."""
        now = datetime.now().isoformat()
        with self._lock:  # noqa: SIM117
            with sqlite3.connect(self.db_path, timeout=5.0) as conn:
                rows = conn.execute(
                    "SELECT * FROM scheduled_messages WHERE status = 'pending' AND send_at <= ? ORDER BY send_at ASC",
                    (now,),
                ).fetchall()
                return [
                    {
                        "id": r[0],
                        "source": r[1],
                        "conv_id": r[2],
                        "text": r[3],
                        "send_at": r[4],
                        "status": r[5],
                        "account": r[6],
                        "created_at": r[7],
                        "sent_at": r[8],
                        "error": r[9],
                        "proposal_id": r[10],
                        "intent_hash": r[11],
                        "approval_state": r[12],
                        "last_execution_id": r[13],
                    }
                    for r in rows
                ]

    def mark_sent(self, msg_id: int) -> bool:
        """Mark a scheduled message as sent."""
        sent_at = datetime.now().isoformat()
        with self._lock, sqlite3.connect(self.db_path, timeout=5.0) as conn:
            conn.execute(
                "UPDATE scheduled_messages SET status = 'sent', sent_at = ? WHERE id = ?",
                (sent_at, msg_id),
            )
            conn.commit()
            return True

    def mark_failed(self, msg_id: int, error: str) -> bool:
        """Mark a scheduled message as failed."""
        with self._lock, sqlite3.connect(self.db_path, timeout=5.0) as conn:
            conn.execute(
                "UPDATE scheduled_messages SET status = 'failed', error = ? WHERE id = ?",
                (error, msg_id),
            )
            conn.commit()
            return True

    # ── Follow-up Reminders ────────────────────────────────────────────

    def create_followup(
        self,
        source: str,
        conv_id: str,
        thread_id: str,
        remind_after: str,
        reminder_title: str,
        reminder_list: str = "Reminders",
    ) -> dict[str, Any]:
        """Create a follow-up reminder."""
        with self._lock:  # noqa: SIM117
            with sqlite3.connect(self.db_path, timeout=5.0) as conn:
                created_at = datetime.now().isoformat()
                conn.execute(
                    """
                    INSERT INTO followup_reminders
                    (source, conv_id, thread_id, remind_after, reminder_title, reminder_list, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source,
                        conv_id,
                        thread_id,
                        remind_after,
                        reminder_title,
                        reminder_list,
                        "active",
                        created_at,
                    ),
                )
                fid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                intent = followup_intent(
                    fid,
                    source,
                    conv_id,
                    thread_id,
                    remind_after,
                    reminder_title,
                    reminder_list,
                )
                approval = self._create_scheduler_proposal(conn, intent, created_at)
                conn.execute(
                    """
                    UPDATE followup_reminders
                    SET proposal_id = ?, intent_hash = ?, approval_state = ?
                    WHERE id = ?
                    """,
                    (
                        approval["proposal_id"],
                        approval["intent_hash"],
                        approval["approval_state"],
                        fid,
                    ),
                )
                conn.commit()
                return {
                    "id": fid,
                    "source": source,
                    "conv_id": conv_id,
                    "thread_id": thread_id,
                    "remind_after": remind_after,
                    "reminder_title": reminder_title,
                    "reminder_list": reminder_list,
                    "status": "active",
                    "created_at": created_at,
                    **approval,
                }

    def cancel_followup(self, fid: int) -> bool:
        """Cancel a follow-up reminder."""
        with self._lock, sqlite3.connect(self.db_path, timeout=5.0) as conn:
            conn.execute("UPDATE followup_reminders SET status = 'cancelled' WHERE id = ?", (fid,))
            conn.commit()
            return True

    def list_followups(self, status: str = "active") -> list[dict[str, Any]]:
        """List follow-up reminders by status."""
        with self._lock, sqlite3.connect(self.db_path, timeout=5.0) as conn:
            rows = conn.execute(
                "SELECT * FROM followup_reminders WHERE status = ? ORDER BY remind_after ASC",
                (status,),
            ).fetchall()
            return [
                {
                    "id": r[0],
                    "source": r[1],
                    "conv_id": r[2],
                    "thread_id": r[3],
                    "remind_after": r[4],
                    "reminder_title": r[5],
                    "reminder_list": r[6],
                    "status": r[7],
                    "created_at": r[8],
                    "fired_at": r[9],
                    "proposal_id": r[10],
                    "intent_hash": r[11],
                    "approval_state": r[12],
                    "last_execution_id": r[13],
                }
                for r in rows
            ]

    def get_due_followups(self) -> list[dict[str, Any]]:
        """Get follow-up reminders that are due to fire."""
        now = datetime.now().isoformat()
        with self._lock:  # noqa: SIM117
            with sqlite3.connect(self.db_path, timeout=5.0) as conn:
                rows = conn.execute(
                    "SELECT * FROM followup_reminders WHERE status = 'active' AND remind_after <= ? ORDER BY remind_after ASC",
                    (now,),
                ).fetchall()
                return [
                    {
                        "id": r[0],
                        "source": r[1],
                        "conv_id": r[2],
                        "thread_id": r[3],
                        "remind_after": r[4],
                        "reminder_title": r[5],
                        "reminder_list": r[6],
                        "status": r[7],
                        "created_at": r[8],
                        "fired_at": r[9],
                        "proposal_id": r[10],
                        "intent_hash": r[11],
                        "approval_state": r[12],
                        "last_execution_id": r[13],
                    }
                    for r in rows
                ]

    def mark_followup_fired(self, fid: int) -> bool:
        """Mark a follow-up reminder as fired."""
        fired_at = datetime.now().isoformat()
        with self._lock, sqlite3.connect(self.db_path, timeout=5.0) as conn:
            conn.execute(
                "UPDATE followup_reminders SET status = 'fired', fired_at = ? WHERE id = ?",
                (fired_at, fid),
            )
            conn.commit()
            return True

    def mark_followup_replied(self, fid: int) -> bool:
        """Mark a follow-up reminder as replied."""
        with self._lock, sqlite3.connect(self.db_path, timeout=5.0) as conn:
            conn.execute("UPDATE followup_reminders SET status = 'replied' WHERE id = ?", (fid,))
            conn.commit()
            return True

    # ── Task↔Message Links ────────────────────────────────────────────

    def link_task(
        self,
        task_id: str,
        task_source: str,
        message_id: str,
        message_source: str,
        thread_id: str = "",
        account: str = "",
    ) -> dict[str, Any]:
        """Create a link between a task and a message."""
        with self._lock:  # noqa: SIM117
            with sqlite3.connect(self.db_path, timeout=5.0) as conn:
                created_at = datetime.now().isoformat()
                conn.execute(
                    """
                    INSERT INTO task_message_links
                    (task_id, task_source, message_id, message_source, thread_id, account, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        task_source,
                        message_id,
                        message_source,
                        thread_id,
                        account,
                        created_at,
                    ),
                )
                conn.commit()
                link_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                return {
                    "id": link_id,
                    "task_id": task_id,
                    "task_source": task_source,
                    "message_id": message_id,
                    "message_source": message_source,
                    "thread_id": thread_id,
                    "account": account,
                    "created_at": created_at,
                }

    def unlink_task(self, link_id: int) -> bool:
        """Delete a task↔message link."""
        with self._lock, sqlite3.connect(self.db_path, timeout=5.0) as conn:
            conn.execute("DELETE FROM task_message_links WHERE id = ?", (link_id,))
            conn.commit()
            return True

    def links_for_message(self, message_id: str, message_source: str) -> list[dict[str, Any]]:
        """Get all task links for a message."""
        with self._lock, sqlite3.connect(self.db_path, timeout=5.0) as conn:
            rows = conn.execute(
                "SELECT * FROM task_message_links WHERE message_id = ? AND message_source = ?",
                (message_id, message_source),
            ).fetchall()
            return [
                {
                    "id": r[0],
                    "task_id": r[1],
                    "task_source": r[2],
                    "message_id": r[3],
                    "message_source": r[4],
                    "thread_id": r[5],
                    "account": r[6],
                    "created_at": r[7],
                }
                for r in rows
            ]

    def links_for_task(self, task_id: str, task_source: str) -> list[dict[str, Any]]:
        """Get all message links for a task."""
        with self._lock, sqlite3.connect(self.db_path, timeout=5.0) as conn:
            rows = conn.execute(
                "SELECT * FROM task_message_links WHERE task_id = ? AND task_source = ?",
                (task_id, task_source),
            ).fetchall()
            return [
                {
                    "id": r[0],
                    "task_id": r[1],
                    "task_source": r[2],
                    "message_id": r[3],
                    "message_source": r[4],
                    "thread_id": r[5],
                    "account": r[6],
                    "created_at": r[7],
                }
                for r in rows
            ]
