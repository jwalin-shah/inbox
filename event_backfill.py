"""Resumable, provenance-honest backfill from the operational message index."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from event_store import RawEvent, RawEventStore


@dataclass(frozen=True)
class BackfillResult:
    job_name: str
    source: str
    account: str
    status: str
    scanned_this_run: int
    inserted_this_run: int
    duplicate_this_run: int
    processed_total: int
    last_item_id: int
    complete: bool
    event_db_path: str
    index_db_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_name": self.job_name,
            "source": self.source,
            "account": self.account,
            "status": self.status,
            "scanned_this_run": self.scanned_this_run,
            "inserted_this_run": self.inserted_this_run,
            "duplicate_this_run": self.duplicate_this_run,
            "processed_total": self.processed_total,
            "last_item_id": self.last_item_id,
            "complete": self.complete,
            "event_db_path": self.event_db_path,
            "index_db_path": self.index_db_path,
        }


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _job_name(source: str, account: str) -> str:
    return f"message-index-v1:{source or 'all'}:{account or 'all'}"


def _read_rows(
    index_db_path: Path,
    *,
    after_id: int,
    source: str,
    account: str,
    limit: int,
) -> list[sqlite3.Row]:
    uri = f"file:{index_db_path}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        clauses = ["id > ?"]
        params: list[Any] = [after_id]
        if source:
            clauses.append("source = ?")
            params.append(source)
        if account:
            clauses.append("account = ?")
            params.append(account)
        rows = conn.execute(
            f"SELECT * FROM items WHERE {' AND '.join(clauses)} ORDER BY id ASC LIMIT ?",  # noqa: S608
            (*params, limit),
        ).fetchall()
    return rows


def _event_from_indexed_row(row: sqlite3.Row, index_db_path: Path) -> RawEvent:
    source = str(row["source"] or "")
    account = str(row["account"] or "")
    external_id = str(row["external_id"] or "")
    occurred_at = str(row["updated_at"] or row["created_at"] or row["ingested_at"] or _now())
    observed_at = str(row["ingested_at"] or _now())
    indexed_item = {
        key: row[key]
        for key in (
            "id",
            "source",
            "account",
            "external_id",
            "thread_id",
            "kind",
            "created_at",
            "updated_at",
            "ingested_at",
            "sender",
            "subject",
            "snippet",
            "body_hash",
            "labels_json",
            "raw_pointer",
            "is_deleted",
            "is_read",
        )
    }
    return RawEvent.create(
        source=source,
        source_object_id=f"{account}:{external_id}",
        observed_at=observed_at,
        occurred_at=occurred_at,
        actor={"name": str(row["sender"] or "")},
        object_data={
            "kind": str(row["kind"] or ""),
            "thread_id": str(row["thread_id"] or ""),
            "subject": str(row["subject"] or ""),
        },
        event_type="message.indexed_backfill",
        content_ref=str(row["raw_pointer"] or ""),
        metadata={
            "account": account,
            "index_row_id": int(row["id"]),
            "raw_payload_available": False,
        },
        provenance={
            "adapter": "message_index_backfill",
            "source": source,
            "index_db": str(index_db_path),
            "raw_payload_available": False,
        },
        confidence=1.0,
        payload={"indexed_item": indexed_item},
    )


def backfill_message_index(
    index_db_path: Path,
    event_store: RawEventStore,
    *,
    source: str = "",
    account: str = "",
    batch_size: int = 250,
    max_items: int | None = None,
) -> BackfillResult:
    """Copy indexed message evidence in resumable batches without provider calls."""
    if not index_db_path.exists():
        raise FileNotFoundError(f"message index does not exist: {index_db_path}")
    if batch_size < 1 or batch_size > 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    if max_items is not None and max_items < 1:
        raise ValueError("max_items must be positive when supplied")

    job_name = _job_name(source, account)
    prior = event_store.get_backfill_state(job_name) or {}
    last_item_id = int(prior.get("last_item_id") or 0)
    processed_total = int(prior.get("processed_count") or 0)
    started_at = str(prior.get("started_at") or _now())
    if prior.get("status") == "completed":
        return BackfillResult(
            job_name=job_name,
            source=source,
            account=account,
            status="completed",
            scanned_this_run=0,
            inserted_this_run=0,
            duplicate_this_run=0,
            processed_total=processed_total,
            last_item_id=last_item_id,
            complete=True,
            event_db_path=str(event_store.db_path),
            index_db_path=str(index_db_path),
        )

    event_store.set_backfill_state(
        job_name=job_name,
        source=source,
        account=account,
        status="running",
        last_item_id=last_item_id,
        processed_count=processed_total,
        started_at=started_at,
    )
    scanned = 0
    inserted = 0
    duplicates = 0
    try:
        while max_items is None or scanned < max_items:
            remaining = max_items - scanned if max_items is not None else batch_size
            rows = _read_rows(
                index_db_path,
                after_id=last_item_id,
                source=source,
                account=account,
                limit=min(batch_size, remaining),
            )
            if not rows:
                event_store.set_backfill_state(
                    job_name=job_name,
                    source=source,
                    account=account,
                    status="completed",
                    last_item_id=last_item_id,
                    processed_count=processed_total,
                    started_at=started_at,
                    completed_at=_now(),
                )
                return BackfillResult(
                    job_name=job_name,
                    source=source,
                    account=account,
                    status="completed",
                    scanned_this_run=scanned,
                    inserted_this_run=inserted,
                    duplicate_this_run=duplicates,
                    processed_total=processed_total,
                    last_item_id=last_item_id,
                    complete=True,
                    event_db_path=str(event_store.db_path),
                    index_db_path=str(index_db_path),
                )
            batch_events = [_event_from_indexed_row(row, index_db_path) for row in rows]
            inserted_batch, duplicate_batch = event_store.append_many(batch_events)
            scanned += len(rows)
            processed_total += len(rows)
            inserted += inserted_batch
            duplicates += duplicate_batch
            last_item_id = int(rows[-1]["id"])
            event_store.set_backfill_state(
                job_name=job_name,
                source=source,
                account=account,
                status="running",
                last_item_id=last_item_id,
                processed_count=processed_total,
                started_at=started_at,
            )
        event_store.set_backfill_state(
            job_name=job_name,
            source=source,
            account=account,
            status="paused",
            last_item_id=last_item_id,
            processed_count=processed_total,
            started_at=started_at,
        )
        return BackfillResult(
            job_name=job_name,
            source=source,
            account=account,
            status="paused",
            scanned_this_run=scanned,
            inserted_this_run=inserted,
            duplicate_this_run=duplicates,
            processed_total=processed_total,
            last_item_id=last_item_id,
            complete=False,
            event_db_path=str(event_store.db_path),
            index_db_path=str(index_db_path),
        )
    except Exception as exc:
        event_store.set_backfill_state(
            job_name=job_name,
            source=source,
            account=account,
            status="failed",
            last_item_id=last_item_id,
            processed_count=processed_total,
            started_at=started_at,
            last_error=str(exc),
        )
        raise
