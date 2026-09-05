from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from thread_classifier import classify_thread, sender_freq_score

BASE_DIR = Path(__file__).parent
DEFAULT_INDEX_DB = BASE_DIR / ".inbox_index.sqlite3"


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _json_dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True)


def _json_loads(value: str | None) -> object:
    return json.loads(value or "{}")


def _coalesce_str(value: object | None) -> str:
    return "" if value is None else str(value)


def _sender_key(sender: object | None) -> str:
    value = _coalesce_str(sender).strip()
    return "" if value == "Me" else value.lower()


@dataclass
class SenderStat:
    thread_count: int = 0
    reply_count: int = 0
    last_seen_at: str = ""


@dataclass
class IndexedItem:
    source: str
    account: str
    external_id: str
    thread_id: str
    kind: str
    created_at: str
    updated_at: str
    ingested_at: str
    sender: str
    recipients_json: str
    subject: str
    snippet: str
    body_text: str
    body_hash: str
    labels_json: str
    raw_pointer: str
    is_deleted: int = 0
    is_read: int = 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class MessageIndexStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or DEFAULT_INDEX_DB
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

                CREATE TABLE IF NOT EXISTS sync_state (
                    source TEXT NOT NULL,
                    account TEXT NOT NULL,
                    checkpoint_type TEXT NOT NULL,
                    checkpoint_value TEXT NOT NULL DEFAULT '',
                    last_success_at TEXT NOT NULL DEFAULT '',
                    last_full_sync_at TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'idle',
                    last_run_started_at TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    last_error TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (source, account)
                );

                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    account TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    ingested_at TEXT NOT NULL,
                    sender TEXT NOT NULL DEFAULT '',
                    recipients_json TEXT NOT NULL DEFAULT '[]',
                    subject TEXT NOT NULL DEFAULT '',
                    snippet TEXT NOT NULL DEFAULT '',
                    body_text TEXT NOT NULL DEFAULT '',
                    body_hash TEXT NOT NULL DEFAULT '',
                    labels_json TEXT NOT NULL DEFAULT '[]',
                    raw_pointer TEXT NOT NULL DEFAULT '',
                    is_deleted INTEGER NOT NULL DEFAULT 0,
                    is_read INTEGER NOT NULL DEFAULT 0,
                    UNIQUE (source, account, external_id)
                );

                CREATE INDEX IF NOT EXISTS idx_items_thread
                    ON items(source, account, thread_id, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_items_created
                    ON items(source, account, created_at DESC);

                CREATE TABLE IF NOT EXISTS threads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    account TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    latest_item_at TEXT NOT NULL,
                    latest_external_id TEXT NOT NULL,
                    latest_sender TEXT NOT NULL DEFAULT '',
                    latest_subject TEXT NOT NULL DEFAULT '',
                    latest_snippet TEXT NOT NULL DEFAULT '',
                    participant_fingerprint TEXT NOT NULL DEFAULT '',
                    participants_json TEXT NOT NULL DEFAULT '[]',
                    message_count INTEGER NOT NULL DEFAULT 0,
                    unread_count INTEGER NOT NULL DEFAULT 0,
                    human_score REAL NOT NULL DEFAULT 0,
                    noise_class TEXT NOT NULL DEFAULT '',
                    topic TEXT NOT NULL DEFAULT '',
                    urgency TEXT NOT NULL DEFAULT '',
                    actionability TEXT NOT NULL DEFAULT '',
                    needs_reply INTEGER NOT NULL DEFAULT 0,
                    summary TEXT NOT NULL DEFAULT '',
                    open_loop TEXT NOT NULL DEFAULT '',
                    last_summary_version TEXT NOT NULL DEFAULT 'v1',
                    updated_at TEXT NOT NULL,
                    UNIQUE (source, account, thread_id)
                );

                CREATE INDEX IF NOT EXISTS idx_threads_latest
                    ON threads(source, account, latest_item_at DESC);

                CREATE INDEX IF NOT EXISTS idx_threads_actionability
                    ON threads(actionability, needs_reply, urgency, latest_item_at DESC);

                CREATE TABLE IF NOT EXISTS sender_stats (
                    email TEXT PRIMARY KEY,
                    thread_count INTEGER NOT NULL DEFAULT 0,
                    reply_count INTEGER NOT NULL DEFAULT 0,
                    last_seen_at TEXT NOT NULL DEFAULT ''
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
                    item_id UNINDEXED,
                    source,
                    account,
                    thread_id UNINDEXED,
                    sender,
                    subject,
                    snippet,
                    body_text
                );

                CREATE TABLE IF NOT EXISTS item_embeddings (
                    item_id INTEGER PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    vector BLOB NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (item_id) REFERENCES items(id)
                );

                CREATE INDEX IF NOT EXISTS idx_item_embeddings_model
                    ON item_embeddings(model_id, updated_at DESC);
                """
            )
            self._migrate_schema(conn)
            self._rebuild_fts_if_needed(conn)

    @staticmethod
    def _fts_row(item_id: int, item: IndexedItem) -> tuple[object, ...]:
        return (
            item_id,
            item.source,
            item.account,
            item.thread_id,
            item.sender,
            item.subject,
            item.snippet,
            item.body_text,
        )

    @classmethod
    def _replace_fts(cls, conn: sqlite3.Connection, item_id: int, item: IndexedItem) -> None:
        conn.execute("DELETE FROM items_fts WHERE item_id = ?", (item_id,))
        if item.is_deleted:
            return
        conn.execute(
            "INSERT INTO items_fts (item_id, source, account, thread_id, sender, subject, snippet, body_text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            cls._fts_row(item_id, item),
        )

    def _rebuild_fts_if_needed(self, conn: sqlite3.Connection) -> None:
        item_count = int(
            conn.execute("SELECT COUNT(*) FROM items WHERE is_deleted = 0").fetchone()[0]
        )
        fts_count = int(conn.execute("SELECT COUNT(*) FROM items_fts").fetchone()[0])
        if item_count == fts_count:
            return
        conn.execute("DELETE FROM items_fts")
        conn.execute(
            """
            INSERT INTO items_fts (item_id, source, account, thread_id, sender, subject, snippet, body_text)
            SELECT id, source, account, thread_id, sender, subject, snippet, body_text
            FROM items
            WHERE is_deleted = 0
            """
        )

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(sync_state)").fetchall()}
        if "status" not in columns:
            conn.execute("ALTER TABLE sync_state ADD COLUMN status TEXT NOT NULL DEFAULT 'idle'")
        if "last_run_started_at" not in columns:
            conn.execute(
                "ALTER TABLE sync_state ADD COLUMN last_run_started_at TEXT NOT NULL DEFAULT ''"
            )
        if "metadata_json" not in columns:
            conn.execute(
                "ALTER TABLE sync_state ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'"
            )

    def upsert_item(self, item: IndexedItem) -> None:
        with self._connect() as conn:
            prior = conn.execute(
                "SELECT id, body_hash, sender, subject, snippet FROM items "
                "WHERE source = ? AND account = ? AND external_id = ?",
                (item.source, item.account, item.external_id),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO items (
                    source, account, external_id, thread_id, kind, created_at, updated_at,
                    ingested_at, sender, recipients_json, subject, snippet, body_text,
                    body_hash, labels_json, raw_pointer, is_deleted, is_read
                )
                VALUES (
                    :source, :account, :external_id, :thread_id, :kind, :created_at, :updated_at,
                    :ingested_at, :sender, :recipients_json, :subject, :snippet, :body_text,
                    :body_hash, :labels_json, :raw_pointer, :is_deleted, :is_read
                )
                ON CONFLICT(source, account, external_id) DO UPDATE SET
                    thread_id=excluded.thread_id,
                    kind=excluded.kind,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at,
                    ingested_at=excluded.ingested_at,
                    sender=excluded.sender,
                    recipients_json=excluded.recipients_json,
                    subject=excluded.subject,
                    snippet=excluded.snippet,
                    body_text=excluded.body_text,
                    body_hash=excluded.body_hash,
                    labels_json=excluded.labels_json,
                    raw_pointer=excluded.raw_pointer,
                    is_deleted=excluded.is_deleted,
                    is_read=excluded.is_read
                """,
                item.to_dict(),
            )
            row = conn.execute(
                "SELECT id FROM items WHERE source = ? AND account = ? AND external_id = ?",
                (item.source, item.account, item.external_id),
            ).fetchone()
            if row:
                item_id = int(row[0])
                self._replace_fts(conn, item_id, item)
                if prior and any(
                    prior[key] != getattr(item, key)
                    for key in ("body_hash", "sender", "subject", "snippet")
                ):
                    conn.execute("DELETE FROM item_embeddings WHERE item_id = ?", (item_id,))

    def insert_item_if_absent(self, item: IndexedItem) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO items (
                    source, account, external_id, thread_id, kind, created_at, updated_at,
                    ingested_at, sender, recipients_json, subject, snippet, body_text,
                    body_hash, labels_json, raw_pointer, is_deleted, is_read
                )
                VALUES (
                    :source, :account, :external_id, :thread_id, :kind, :created_at, :updated_at,
                    :ingested_at, :sender, :recipients_json, :subject, :snippet, :body_text,
                    :body_hash, :labels_json, :raw_pointer, :is_deleted, :is_read
                )
                ON CONFLICT(source, account, external_id) DO NOTHING
                """,
                item.to_dict(),
            )
            if int(cur.rowcount or 0) == 1 and cur.lastrowid:
                self._replace_fts(conn, int(cur.lastrowid), item)
        return int(cur.rowcount or 0) == 1

    @staticmethod
    def _item_row_to_dict(row: sqlite3.Row) -> dict[str, object]:
        result = dict(row)
        for key in ("recipients_json", "labels_json"):
            if key in result:
                result[key.removesuffix("_json")] = _json_loads(str(result.pop(key) or "[]"))
        return result

    @staticmethod
    def _fts_query(query: str) -> str:
        tokens = re.findall(r"[\w@.+-]+", query.casefold())
        if not tokens:
            return ""
        # Quoted tokens prevent FTS5 operators from being injected. Prefix
        # matching makes short natural-language queries useful without a scan.
        return " AND ".join(f'"{token.replace(chr(34), "")}"*' for token in tokens)

    def search_items(
        self,
        query: str,
        *,
        limit: int = 25,
        source: str = "",
        account: str = "",
    ) -> list[dict[str, object]]:
        match = self._fts_query(query)
        if not match:
            return []
        predicates = ["items.is_deleted = 0", "items_fts MATCH ?"]
        params: list[object] = [match]
        if source:
            predicates.append("items.source = ?")
            params.append(source)
        if account:
            predicates.append("items.account = ?")
            params.append(account)
        params.append(max(1, min(int(limit), 100)))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT items.*, bm25(items_fts) AS lexical_score "
                "FROM items_fts JOIN items ON items.id = CAST(items_fts.item_id AS INTEGER) "
                f"WHERE {' AND '.join(predicates)} ORDER BY lexical_score LIMIT ?",  # noqa: S608
                params,
            ).fetchall()
        return [self._item_row_to_dict(row) for row in rows]

    def embedding_status(self, model_id: str = "") -> dict[str, object]:
        with self._connect() as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM items WHERE is_deleted = 0").fetchone()[0])
            if model_id:
                embedded = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM item_embeddings WHERE model_id = ?",
                        (model_id,),
                    ).fetchone()[0]
                )
            else:
                embedded = int(conn.execute("SELECT COUNT(*) FROM item_embeddings").fetchone()[0])
        return {"items": total, "embedded": embedded, "pending": max(0, total - embedded)}

    def embedding_backlog(
        self, *, model_id: str, limit: int = 100, source: str = "", account: str = ""
    ) -> list[dict[str, object]]:
        predicates = ["i.is_deleted = 0", "(e.item_id IS NULL OR e.model_id != ?)"]
        params: list[object] = [model_id]
        if source:
            predicates.append("i.source = ?")
            params.append(source)
        if account:
            predicates.append("i.account = ?")
            params.append(account)
        params.append(max(1, min(int(limit), 1000)))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT i.* FROM items i LEFT JOIN item_embeddings e ON e.item_id = i.id "
                f"WHERE {' AND '.join(predicates)} ORDER BY i.id LIMIT ?",  # noqa: S608
                params,
            ).fetchall()
        return [self._item_row_to_dict(row) for row in rows]

    def upsert_embedding(
        self,
        *,
        item_id: int,
        model_id: str,
        content_hash: str,
        vector: list[float],
    ) -> None:
        import numpy as np

        array = np.asarray(vector, dtype=np.float32)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO item_embeddings (
                    item_id, model_id, content_hash, dimensions, vector, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_id) DO UPDATE SET
                    model_id=excluded.model_id,
                    content_hash=excluded.content_hash,
                    dimensions=excluded.dimensions,
                    vector=excluded.vector,
                    updated_at=excluded.updated_at
                """,
                (item_id, model_id, content_hash, int(array.size), array.tobytes(), _utcnow()),
            )

    def search_embeddings(
        self,
        vector: list[float],
        *,
        model_id: str,
        limit: int = 25,
        source: str = "",
        account: str = "",
    ) -> list[dict[str, object]]:
        import numpy as np

        query = np.asarray(vector, dtype=np.float32)
        norm = float(np.linalg.norm(query))
        if norm == 0:
            return []
        query /= norm
        predicates = ["i.is_deleted = 0", "e.model_id = ?"]
        params: list[object] = [model_id]
        if source:
            predicates.append("i.source = ?")
            params.append(source)
        if account:
            predicates.append("i.account = ?")
            params.append(account)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT i.*, e.vector FROM item_embeddings e JOIN items i ON i.id = e.item_id "
                f"WHERE {' AND '.join(predicates)}",  # noqa: S608
                params,
            ).fetchall()
        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            candidate = np.frombuffer(row["vector"], dtype=np.float32)
            if candidate.size != query.size:
                continue
            scored.append((float(np.dot(query, candidate)), row))
        scored.sort(key=lambda value: value[0], reverse=True)
        results: list[dict[str, object]] = []
        for score, row in scored[: max(1, min(int(limit), 100))]:
            item = self._item_row_to_dict(row)
            item.pop("vector", None)
            item["semantic_score"] = score
            results.append(item)
        return results

    def set_sync_state(
        self,
        *,
        source: str,
        account: str,
        checkpoint_type: str,
        checkpoint_value: str,
        last_error: str = "",
        full_sync: bool = False,
        status: str = "idle",
        last_run_started_at: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = _utcnow()
        metadata_json = _json_dumps(metadata or {})
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sync_state (
                    source, account, checkpoint_type, checkpoint_value, last_success_at,
                    last_full_sync_at, status, last_run_started_at, metadata_json, last_error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, account) DO UPDATE SET
                    checkpoint_type=excluded.checkpoint_type,
                    checkpoint_value=excluded.checkpoint_value,
                    last_success_at=excluded.last_success_at,
                    last_full_sync_at=CASE
                        WHEN excluded.last_full_sync_at != '' THEN excluded.last_full_sync_at
                        ELSE sync_state.last_full_sync_at
                    END,
                    status=excluded.status,
                    last_run_started_at=CASE
                        WHEN excluded.last_run_started_at != '' THEN excluded.last_run_started_at
                        ELSE sync_state.last_run_started_at
                    END,
                    metadata_json=excluded.metadata_json,
                    last_error=excluded.last_error
                """,
                (
                    source,
                    account,
                    checkpoint_type,
                    checkpoint_value,
                    now,
                    now if full_sync else "",
                    status,
                    last_run_started_at,
                    metadata_json,
                    last_error,
                ),
            )

    def mark_sync_started(
        self,
        *,
        source: str,
        account: str,
        checkpoint_type: str,
        checkpoint_value: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.set_sync_state(
            source=source,
            account=account,
            checkpoint_type=checkpoint_type,
            checkpoint_value=checkpoint_value,
            status="running",
            last_run_started_at=_utcnow(),
            metadata=metadata,
        )

    def update_sync_progress(
        self,
        *,
        source: str,
        account: str,
        checkpoint_type: str,
        checkpoint_value: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.set_sync_state(
            source=source,
            account=account,
            checkpoint_type=checkpoint_type,
            checkpoint_value=checkpoint_value,
            status="running",
            metadata=metadata,
        )

    def record_sync_error(self, *, source: str, account: str, error: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sync_state (
                    source, account, checkpoint_type, checkpoint_value, last_success_at,
                    last_full_sync_at, status, last_run_started_at, metadata_json, last_error
                )
                VALUES (?, ?, '', '', '', '', 'error', '', '{}', ?)
                ON CONFLICT(source, account) DO UPDATE SET
                    status='error',
                    last_error=excluded.last_error
                """,
                (source, account, error),
            )

    def get_sync_state(self, source: str, account: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sync_state WHERE source = ? AND account = ?",
                (source, account),
            ).fetchone()
        return self._sync_row_to_dict(row) if row else None

    def list_sync_states(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM sync_state ORDER BY source, account").fetchall()
        return [self._sync_row_to_dict(row) for row in rows]

    def index_counts(self) -> dict[str, int]:
        with self._connect() as conn:
            items = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            threads = conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
        return {"items": int(items), "threads": int(threads)}

    def _sync_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["metadata"] = _json_loads(str(data.get("metadata_json") or "{}"))
        return data

    def _refresh_sender_stats(
        self, conn: sqlite3.Connection, rows: list[sqlite3.Row]
    ) -> dict[str, SenderStat]:
        grouped: dict[tuple[str, str, str], list[sqlite3.Row]] = {}
        for row in rows:
            key = (str(row["source"]), str(row["account"]), str(row["thread_id"]))
            grouped.setdefault(key, []).append(row)

        stats: dict[str, SenderStat] = {}
        for items in grouped.values():
            has_reply = any(str(item["sender"]) == "Me" for item in items)
            senders = {_sender_key(item["sender"]) for item in items}
            for sender in sorted(sender for sender in senders if sender):
                sender_items = [item for item in items if _sender_key(item["sender"]) == sender]
                latest_seen = max(str(item["created_at"]) for item in sender_items)
                row = stats.setdefault(sender, SenderStat())
                row.thread_count += 1
                row.reply_count += int(has_reply)
                row.last_seen_at = max(row.last_seen_at, latest_seen)

        conn.execute("DELETE FROM sender_stats")
        conn.executemany(
            """
            INSERT INTO sender_stats (email, thread_count, reply_count, last_seen_at)
            VALUES (:email, :thread_count, :reply_count, :last_seen_at)
            """,
            [
                {
                    "email": sender,
                    "thread_count": row.thread_count,
                    "reply_count": row.reply_count,
                    "last_seen_at": row.last_seen_at,
                }
                for sender, row in sorted(stats.items())
            ],
        )
        return stats

    def rebuild_threads(self, *, source: str | None = None, account: str | None = None) -> int:
        predicates: list[str] = []
        params: list[object] = []
        if source:
            predicates.append("source = ?")
            params.append(source)
        if account:
            predicates.append("account = ?")
            params.append(account)
        where_clause = f"WHERE {' AND '.join(predicates)}" if predicates else ""

        with self._connect() as conn:
            all_rows = conn.execute(
                "SELECT * FROM items ORDER BY source, account, thread_id, created_at, id"
            ).fetchall()
            sender_stats = self._refresh_sender_stats(conn, all_rows)

            _q = f"SELECT * FROM items {where_clause} ORDER BY source, account, thread_id, created_at, id"  # nosec B608
            rows = conn.execute(_q, params).fetchall()

            grouped: dict[tuple[str, str, str], list[sqlite3.Row]] = {}
            for row in rows:
                key = (str(row["source"]), str(row["account"]), str(row["thread_id"]))
                grouped.setdefault(key, []).append(row)

            now = _utcnow()
            for (row_source, row_account, thread_id), items in grouped.items():
                latest = items[-1]
                participants = sorted(
                    {
                        sender
                        for sender in [str(item["sender"]) for item in items]
                        if sender and sender != "Me"
                    }
                )
                unread_count = sum(int(item["is_read"] == 0) for item in items)
                sender_stat = sender_stats.get(_sender_key(latest["sender"]), SenderStat())
                sender_freq = sender_freq_score(
                    reply_count=sender_stat.reply_count,
                    thread_count=sender_stat.thread_count,
                )
                classification = classify_thread(latest=latest, sender_freq=sender_freq)
                conn.execute(
                    """
                    INSERT INTO threads (
                        source, account, thread_id, latest_item_at, latest_external_id,
                        latest_sender, latest_subject, latest_snippet, participant_fingerprint,
                        participants_json, message_count, unread_count, human_score, noise_class,
                        topic, urgency, actionability, needs_reply, summary, open_loop,
                        last_summary_version, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source, account, thread_id) DO UPDATE SET
                        latest_item_at=excluded.latest_item_at,
                        latest_external_id=excluded.latest_external_id,
                        latest_sender=excluded.latest_sender,
                        latest_subject=excluded.latest_subject,
                        latest_snippet=excluded.latest_snippet,
                        participant_fingerprint=excluded.participant_fingerprint,
                        participants_json=excluded.participants_json,
                        message_count=excluded.message_count,
                        unread_count=excluded.unread_count,
                        human_score=excluded.human_score,
                        noise_class=excluded.noise_class,
                        topic=excluded.topic,
                        urgency=excluded.urgency,
                        actionability=excluded.actionability,
                        needs_reply=excluded.needs_reply,
                        summary=excluded.summary,
                        open_loop=excluded.open_loop,
                        last_summary_version=excluded.last_summary_version,
                        updated_at=excluded.updated_at
                    """,
                    (
                        row_source,
                        row_account,
                        thread_id,
                        str(latest["created_at"]),
                        str(latest["external_id"]),
                        str(latest["sender"]),
                        str(latest["subject"]),
                        str(latest["snippet"]),
                        "|".join(participants),
                        _json_dumps(participants),
                        len(items),
                        unread_count,
                        classification.human_score,
                        classification.noise_class,
                        classification.topic,
                        classification.urgency,
                        classification.actionability,
                        classification.needs_reply,
                        classification.summary,
                        classification.open_loop,
                        "v1",
                        now,
                    ),
                )

            if grouped:
                keys = list(grouped.keys())
                deletion_scope_predicates: list[str] = []
                deletion_scope_params: list[object] = []
                if source:
                    deletion_scope_predicates.append("source = ?")
                    deletion_scope_params.append(source)
                if account:
                    deletion_scope_predicates.append("account = ?")
                    deletion_scope_params.append(account)
                scope_clause = (
                    " AND ".join(deletion_scope_predicates) if deletion_scope_predicates else "1=1"
                )
                conn.execute(
                    """
                    CREATE TEMP TABLE IF NOT EXISTS rebuild_thread_keep (
                        source TEXT NOT NULL,
                        account TEXT NOT NULL,
                        thread_id TEXT NOT NULL,
                        PRIMARY KEY (source, account, thread_id)
                    )
                    """
                )
                conn.execute("DELETE FROM rebuild_thread_keep")
                conn.executemany(
                    """
                    INSERT OR IGNORE INTO rebuild_thread_keep (source, account, thread_id)
                    VALUES (?, ?, ?)
                    """,
                    keys,
                )
                conn.execute(
                    f"""
                    DELETE FROM threads
                    WHERE ({scope_clause})
                      AND NOT EXISTS (
                          SELECT 1
                          FROM rebuild_thread_keep keep
                          WHERE keep.source = threads.source
                            AND keep.account = threads.account
                            AND keep.thread_id = threads.thread_id
                      )
                    """,  # nosec: B608
                    deletion_scope_params,
                )
                conn.execute("DELETE FROM rebuild_thread_keep")
            elif source and account:
                conn.execute(
                    "DELETE FROM threads WHERE source = ? AND account = ?", (source, account)
                )
            elif source:
                conn.execute("DELETE FROM threads WHERE source = ?", (source,))
            elif account:
                conn.execute("DELETE FROM threads WHERE account = ?", (account,))
            else:
                conn.execute("DELETE FROM threads")

        return len(grouped)

    def list_threads(
        self,
        *,
        limit: int = 25,
        source: str | None = None,
        account: str | None = None,
        actionable_only: bool = False,
        newest_only: bool = False,
        actions: tuple[str, ...] | None = None,
        needs_reply: bool | None = None,
        has_open_loop: bool | None = None,
        latest_sender: str | None = None,
        sort_mode: str = "priority",
    ) -> list[dict[str, object]]:
        predicates: list[str] = []
        params: list[object] = []
        if source is not None:
            predicates.append("source = ?")
            params.append(source)
        if account is not None:
            predicates.append("account = ?")
            params.append(account)
        if actionable_only:
            predicates.append("actionability IN ('reply', 'review', 'track')")
        if newest_only:
            predicates.append("latest_item_at >= datetime('now', '-7 day')")
        if actions:
            predicates.append(f"actionability IN ({','.join('?' for _ in actions)})")
            params.extend(actions)
        if needs_reply is not None:
            predicates.append("needs_reply = ?")
            params.append(1 if needs_reply else 0)
        if has_open_loop is not None:
            predicates.append("(open_loop != '') = ?")
            params.append(1 if has_open_loop else 0)
        if latest_sender is not None:
            predicates.append("latest_sender = ?")
            params.append(latest_sender)
        where_clause = f"WHERE {' AND '.join(predicates)}" if predicates else ""
        if sort_mode == "recent":
            order_clause = "latest_item_at DESC"
        else:
            order_clause = """
                CASE urgency
                    WHEN 'high' THEN 0
                    WHEN 'medium' THEN 1
                    ELSE 2
                END,
                needs_reply DESC,
                latest_item_at DESC
            """
        params.append(limit)
        with self._connect() as conn:
            _q = f"SELECT * FROM threads {where_clause} ORDER BY {order_clause} LIMIT ?"  # nosec B608
            rows = conn.execute(_q, params).fetchall()
        return [self._thread_row_to_dict(row) for row in rows]

    def _thread_row_to_dict(self, row: sqlite3.Row) -> dict[str, object]:
        keys = list(row.keys())
        return {key: (_json_loads(row[key]) if key.endswith("_json") else row[key]) for key in keys}
