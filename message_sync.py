from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from datetime import UTC, datetime
from email.utils import getaddresses
from pathlib import Path
from typing import Any

from message_index_store import IndexedItem, MessageIndexStore
from services import (
    IMSG_DB,
    _clean_body,
    _decode_body,
    _openhuman_linkedin_db_path,
    _openhuman_whatsapp_db_path,
    _parse_email_address,
    google_auth_all,
)

GMAIL_BOOTSTRAP_BATCH_SIZE = 250
GMAIL_INCREMENTAL_BATCH_SIZE = 100
GMAIL_HISTORY_CURSOR = "gmailHistoryId"
GMAIL_TIMESTAMP_CURSOR = "internalDateMs"
IMESSAGE_PROGRESS_EVERY = 250
WHATSAPP_PROGRESS_EVERY = 250
LINKEDIN_PROGRESS_EVERY = 250
_ATTACHMENT_TEXT = "(attachment)"
CLI_MODES = ("bootstrap", "incremental", "rebuild", "summary")
SyncScope = tuple[str, str]


def _iso_from_ms(value: int | str | None) -> str:
    if not value:
        return datetime.now(UTC).isoformat()
    milliseconds = int(value)
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC).isoformat()


def _iso_from_apple_seconds(value: float | int | None) -> str:
    if not value:
        return datetime.now(UTC).isoformat()
    return datetime.fromtimestamp(float(value), tz=UTC).isoformat()


def _iso_from_unix_seconds(value: int | str | None) -> str:
    if not value:
        return datetime.now(UTC).isoformat()
    return datetime.fromtimestamp(int(value), tz=UTC).isoformat()


def _hash_body(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _clean_imessage_body(text: str | None) -> str:
    body = _clean_body(text)
    return "" if body.replace(_ATTACHMENT_TEXT, "").strip() == "" else body


def _gmail_recipients(headers: dict[str, str]) -> list[str]:
    to_raw = headers.get("To", "")
    if not to_raw:
        return []
    return [email or name for name, email in getaddresses([to_raw]) if email or name]


def _gmail_item(account: str, message: dict[str, Any]) -> IndexedItem:
    payload = message.get("payload", {})
    headers = {header["name"]: header["value"] for header in payload.get("headers", [])}
    raw_from = headers.get("From", "Unknown")
    display_name, email_addr = _parse_email_address(raw_from)
    body_text = _decode_body(payload) or ""
    created_at = _iso_from_ms(message.get("internalDate"))
    labels = message.get("labelIds", [])
    subject = headers.get("Subject", "")
    sender = (
        "Me" if email_addr.lower() == account.lower() else (display_name or email_addr or "Unknown")
    )
    return IndexedItem(
        source="gmail",
        account=account,
        external_id=str(message["id"]),
        thread_id=str(message.get("threadId", message["id"])),
        kind="email",
        created_at=created_at,
        updated_at=created_at,
        ingested_at=datetime.now(UTC).isoformat(),
        sender=sender,
        recipients_json=_json(_gmail_recipients(headers)),
        subject=subject,
        snippet=(message.get("snippet") or subject)[:240],
        body_text=body_text,
        body_hash=_hash_body(body_text),
        labels_json=_json(labels),
        raw_pointer=f"gmail:{account}:{message['id']}",
        is_deleted=0,
        is_read=0 if "UNREAD" in labels else 1,
    )


def _json(value: object) -> str:
    import json

    return json.dumps(value, sort_keys=True)


def _fetch_gmail_full_message(service: Any, message_id: str) -> dict[str, Any]:
    return service.users().messages().get(userId="me", id=message_id, format="full").execute()


def _fetch_gmail_profile_history_id(service: Any) -> str:
    try:
        request = service.users().getProfile(userId="me")
    except AttributeError:
        return ""
    profile = request.execute()
    return str(profile.get("historyId") or "")


def _gmail_history_api(service: Any) -> Any | None:
    try:
        return service.users().history()
    except AttributeError:
        return None


def _gmail_timestamp_checkpoint(state: dict[str, Any]) -> int:
    metadata = state.get("metadata") or {}
    if state.get("checkpoint_type") == GMAIL_TIMESTAMP_CURSOR:
        return int(state.get("checkpoint_value", "0") or 0)
    return int(metadata.get("timestamp_checkpoint_ms") or 0)


def _gmail_history_cursor(state: dict[str, Any]) -> str:
    metadata = state.get("metadata") or {}
    if state.get("checkpoint_type") == GMAIL_HISTORY_CURSOR:
        return str(state.get("checkpoint_value") or "")
    return str(metadata.get("history_id") or "")


def _gmail_bootstrap_metadata(
    *,
    page_token: str | None,
    count: int,
    newest_seen: int,
) -> dict[str, object]:
    return {
        "bootstrap_page_token": page_token or "",
        "messages_processed": count,
        "cursor_mode": "bootstrap",
        "timestamp_checkpoint_ms": str(newest_seen),
    }


def _gmail_timestamp_metadata(
    *,
    count: int,
    checkpoint: int,
    fallback_reason: str,
) -> dict[str, object]:
    return {
        "messages_processed": count,
        "cursor_mode": "timestamp_fallback",
        "fallback_reason": fallback_reason,
        "timestamp_checkpoint_ms": str(checkpoint),
    }


def _gmail_history_metadata(
    *,
    count: int,
    history_id: str,
    timestamp_checkpoint: int,
) -> dict[str, object]:
    return {
        "messages_processed": count,
        "cursor_mode": "history",
        "history_id": history_id,
        "timestamp_checkpoint_ms": str(timestamp_checkpoint),
    }


def _history_message_ids(history_entries: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    message_ids: list[str] = []
    for entry in history_entries:
        for key in ("messagesAdded", "labelsAdded", "labelsRemoved"):
            for change in entry.get(key, []):
                message = change.get("message") or {}
                message_id = str(message.get("id") or "")
                if message_id and message_id not in seen:
                    seen.add(message_id)
                    message_ids.append(message_id)
    return message_ids


def sync_gmail_bootstrap(store: MessageIndexStore) -> dict[str, int]:
    gmail_services, _, _, _, _, _ = google_auth_all()
    stats: dict[str, int] = {}
    for account, service_obj in gmail_services.items():
        service: Any = service_obj
        state = store.get_sync_state("gmail", account) or {}
        metadata = state.get("metadata") or {}
        newest_seen = _gmail_timestamp_checkpoint(state)
        page_token = str(metadata.get("bootstrap_page_token") or "") or None
        count = 0
        store.mark_sync_started(
            source="gmail",
            account=account,
            checkpoint_type=GMAIL_TIMESTAMP_CURSOR,
            checkpoint_value=str(newest_seen),
            metadata=_gmail_bootstrap_metadata(
                page_token=page_token,
                count=count,
                newest_seen=newest_seen,
            ),
        )
        try:
            while True:
                request = (
                    service.users()
                    .messages()
                    .list(
                        userId="me",
                        maxResults=GMAIL_BOOTSTRAP_BATCH_SIZE,
                        includeSpamTrash=False,
                        pageToken=page_token,
                    )
                )
                response = request.execute()
                messages = response.get("messages", [])
                if not messages:
                    break
                for stub in messages:
                    full_message = _fetch_gmail_full_message(service, stub["id"])
                    if store.insert_item_if_absent(_gmail_item(account, full_message)):
                        count += 1
                    newest_seen = max(newest_seen, int(full_message.get("internalDate", 0) or 0))
                page_token = response.get("nextPageToken")
                store.update_sync_progress(
                    source="gmail",
                    account=account,
                    checkpoint_type=GMAIL_TIMESTAMP_CURSOR,
                    checkpoint_value=str(newest_seen),
                    metadata=_gmail_bootstrap_metadata(
                        page_token=page_token,
                        count=count,
                        newest_seen=newest_seen,
                    ),
                )
                if not page_token:
                    break
        except Exception as exc:
            store.record_sync_error(source="gmail", account=account, error=str(exc))
            raise
        history_id = _fetch_gmail_profile_history_id(service)
        checkpoint_type = GMAIL_HISTORY_CURSOR if history_id else GMAIL_TIMESTAMP_CURSOR
        checkpoint_value = history_id or str(newest_seen)
        final_metadata = (
            _gmail_history_metadata(
                count=count,
                history_id=history_id,
                timestamp_checkpoint=newest_seen,
            )
            if history_id
            else {
                **_gmail_timestamp_metadata(
                    count=count,
                    checkpoint=newest_seen,
                    fallback_reason="missing_history_cursor",
                ),
                "bootstrap_page_token": "",  # nosec B105
            }
        )
        store.set_sync_state(
            source="gmail",
            account=account,
            checkpoint_type=checkpoint_type,
            checkpoint_value=checkpoint_value,
            full_sync=True,
            status="idle",
            metadata=final_metadata,
        )
        stats[account] = count
    return stats


def _sync_gmail_incremental_history(
    store: MessageIndexStore,
    *,
    account: str,
    service: Any,
    history_api: Any,
    history_id: str,
    timestamp_checkpoint: int,
) -> int:
    page_token: str | None = None
    latest_history_id = history_id
    changed_message_ids: list[str] = []
    store.mark_sync_started(
        source="gmail",
        account=account,
        checkpoint_type=GMAIL_HISTORY_CURSOR,
        checkpoint_value=history_id,
        metadata=_gmail_history_metadata(
            count=0,
            history_id=history_id,
            timestamp_checkpoint=timestamp_checkpoint,
        ),
    )
    try:
        while True:
            response = history_api.list(
                userId="me",
                startHistoryId=history_id,
                pageToken=page_token,
                historyTypes=["messageAdded", "labelAdded", "labelRemoved"],
            ).execute()
            latest_history_id = str(response.get("historyId") or latest_history_id)
            changed_message_ids.extend(_history_message_ids(response.get("history", [])))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        count = 0
        seen: set[str] = set()
        for message_id in changed_message_ids:
            if message_id in seen:
                continue
            seen.add(message_id)
            full_message = _fetch_gmail_full_message(service, message_id)
            timestamp_checkpoint = max(
                timestamp_checkpoint, int(full_message.get("internalDate", 0) or 0)
            )
            store.upsert_item(_gmail_item(account, full_message))
            count += 1

        store.set_sync_state(
            source="gmail",
            account=account,
            checkpoint_type=GMAIL_HISTORY_CURSOR,
            checkpoint_value=latest_history_id,
            full_sync=False,
            status="idle",
            metadata=_gmail_history_metadata(
                count=count,
                history_id=latest_history_id,
                timestamp_checkpoint=timestamp_checkpoint,
            ),
        )
        return count
    except Exception as exc:
        store.record_sync_error(source="gmail", account=account, error=str(exc))
        raise


def _sync_gmail_incremental_timestamp(
    store: MessageIndexStore,
    *,
    account: str,
    service: Any,
    checkpoint: int,
    fallback_reason: str,
) -> int:
    page_token: str | None = None
    newest_seen = checkpoint
    count = 0
    stop = False
    store.mark_sync_started(
        source="gmail",
        account=account,
        checkpoint_type=GMAIL_TIMESTAMP_CURSOR,
        checkpoint_value=str(checkpoint),
        metadata=_gmail_timestamp_metadata(
            count=0,
            checkpoint=checkpoint,
            fallback_reason=fallback_reason,
        ),
    )
    try:
        while not stop:
            response = (
                service.users()
                .messages()
                .list(
                    userId="me",
                    maxResults=GMAIL_INCREMENTAL_BATCH_SIZE,
                    includeSpamTrash=False,
                    pageToken=page_token,
                )
                .execute()
            )
            messages = response.get("messages", [])
            if not messages:
                break
            for stub in messages:
                full_message = _fetch_gmail_full_message(service, stub["id"])
                internal_date = int(full_message.get("internalDate", 0) or 0)
                if internal_date <= checkpoint:
                    stop = True
                    break
                store.upsert_item(_gmail_item(account, full_message))
                newest_seen = max(newest_seen, internal_date)
                count += 1
            store.update_sync_progress(
                source="gmail",
                account=account,
                checkpoint_type=GMAIL_TIMESTAMP_CURSOR,
                checkpoint_value=str(newest_seen),
                metadata=_gmail_timestamp_metadata(
                    count=count,
                    checkpoint=newest_seen,
                    fallback_reason=fallback_reason,
                ),
            )
            page_token = response.get("nextPageToken")
            if not page_token:
                break
    except Exception as exc:
        store.record_sync_error(source="gmail", account=account, error=str(exc))
        raise
    store.set_sync_state(
        source="gmail",
        account=account,
        checkpoint_type=GMAIL_TIMESTAMP_CURSOR,
        checkpoint_value=str(newest_seen),
        full_sync=False,
        status="idle",
        metadata=_gmail_timestamp_metadata(
            count=count,
            checkpoint=newest_seen,
            fallback_reason=fallback_reason,
        ),
    )
    return count


def sync_gmail_incremental(store: MessageIndexStore) -> dict[str, int]:
    gmail_services, _, _, _, _, _ = google_auth_all()
    stats: dict[str, int] = {}
    for account, service_obj in gmail_services.items():
        service: Any = service_obj
        state = store.get_sync_state("gmail", account) or {}
        timestamp_checkpoint = _gmail_timestamp_checkpoint(state)
        history_id = _gmail_history_cursor(state)
        history_api = _gmail_history_api(service) if history_id else None
        if history_id and history_api is not None:
            stats[account] = _sync_gmail_incremental_history(
                store,
                account=account,
                service=service,
                history_api=history_api,
                history_id=history_id,
                timestamp_checkpoint=timestamp_checkpoint,
            )
        else:
            fallback_reason = "history_api_unavailable" if history_id else "missing_history_cursor"
            stats[account] = _sync_gmail_incremental_timestamp(
                store,
                account=account,
                service=service,
                checkpoint=timestamp_checkpoint,
                fallback_reason=fallback_reason,
            )
    return stats


def _imessage_messages_after(last_rowid: int | None = None) -> list[sqlite3.Row]:
    if not IMSG_DB.exists():
        return []
    conn = sqlite3.connect(f"file:{Path(IMSG_DB)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        predicate = "AND m.rowid > ?" if last_rowid is not None else ""
        params: tuple[object, ...] = (last_rowid,) if last_rowid is not None else ()
        _q = (
            "SELECT m.rowid AS message_rowid, cmj.chat_id AS chat_id, m.text AS text,"
            " m.is_from_me AS is_from_me, m.date / 1000000000 + 978307200 AS ts, h.id AS sender_id"
            " FROM message m JOIN chat_message_join cmj ON cmj.message_id = m.rowid"
            f" LEFT JOIN handle h ON h.rowid = m.handle_id WHERE m.text IS NOT NULL {predicate} ORDER BY m.rowid ASC"  # nosec B608
        )
        rows = conn.execute(_q, params).fetchall()
    finally:
        conn.close()
    return rows


def _imessage_item(row: sqlite3.Row) -> IndexedItem:
    body = _clean_imessage_body(row["text"] or "")
    created_at = _iso_from_apple_seconds(row["ts"])
    sender = "Me" if row["is_from_me"] else (row["sender_id"] or "?")
    return IndexedItem(
        source="imessage",
        account="local",
        external_id=str(row["message_rowid"]),
        thread_id=str(row["chat_id"]),
        kind="imessage",
        created_at=created_at,
        updated_at=created_at,
        ingested_at=datetime.now(UTC).isoformat(),
        sender=sender,
        recipients_json=_json([]),
        subject="",
        snippet=body[:240],
        body_text=body,
        body_hash=_hash_body(body),
        labels_json=_json([]),
        raw_pointer=f"imessage:{row['chat_id']}:{row['message_rowid']}",
        is_deleted=0,
        is_read=1 if row["is_from_me"] else 0,
    )


def _sync_imessage_from_local_store(store: MessageIndexStore, *, full_sync: bool) -> dict[str, int]:
    state = store.get_sync_state("imessage", "local") or {}
    checkpoint_rowid = int(state.get("checkpoint_value", "0") or 0)
    highest_rowid = checkpoint_rowid
    count = 0
    store.mark_sync_started(
        source="imessage",
        account="local",
        checkpoint_type="rowid",
        checkpoint_value=str(checkpoint_rowid),
        metadata={"messages_processed": 0},
    )
    try:
        start_after = (checkpoint_rowid or None) if full_sync else checkpoint_rowid
        rows = _imessage_messages_after(start_after)
        for row in rows:
            highest_rowid = max(highest_rowid, int(row["message_rowid"]))
            body = _clean_imessage_body(row["text"] or "")
            if not body:
                continue
            store.upsert_item(_imessage_item(row))
            count += 1
            if count % IMESSAGE_PROGRESS_EVERY == 0:
                store.update_sync_progress(
                    source="imessage",
                    account="local",
                    checkpoint_type="rowid",
                    checkpoint_value=str(highest_rowid),
                    metadata={"messages_processed": count},
                )
    except Exception as exc:
        store.record_sync_error(source="imessage", account="local", error=str(exc))
        raise
    store.set_sync_state(
        source="imessage",
        account="local",
        checkpoint_type="rowid",
        checkpoint_value=str(highest_rowid),
        full_sync=full_sync,
        status="idle",
        metadata={"messages_processed": count},
    )
    return {"local": count}


def sync_imessage_bootstrap(store: MessageIndexStore) -> dict[str, int]:
    return _sync_imessage_from_local_store(store, full_sync=True)


def sync_imessage_incremental(store: MessageIndexStore) -> dict[str, int]:
    return _sync_imessage_from_local_store(store, full_sync=False)


def _openhuman_whatsapp_rows() -> list[sqlite3.Row]:
    db_path = _openhuman_whatsapp_db_path()
    if not db_path:
        return []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            """
            SELECT
                m.account_id,
                m.chat_id,
                m.message_id,
                m.sender,
                m.from_me,
                m.body,
                m.timestamp,
                m.message_type,
                m.source AS wa_source,
                c.display_name
            FROM wa_messages m
            LEFT JOIN wa_chats c
              ON c.account_id = m.account_id AND c.chat_id = m.chat_id
            ORDER BY m.account_id, m.timestamp ASC, m.message_id ASC
            """
        ).fetchall()
    finally:
        conn.close()


def _openhuman_linkedin_rows() -> list[sqlite3.Row]:
    db_path = _openhuman_linkedin_db_path()
    if not db_path:
        return []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            """
            SELECT
                m.account_id,
                m.thread_id,
                m.message_id,
                m.sender,
                m.sender_profile_url,
                m.from_me,
                m.body,
                m.timestamp,
                m.source_url,
                t.display_name,
                t.profile_url
            FROM li_messages m
            LEFT JOIN li_threads t
              ON t.account_id = m.account_id AND t.thread_id = m.thread_id
            ORDER BY m.account_id, m.timestamp ASC, m.message_id ASC
            """
        ).fetchall()
    finally:
        conn.close()


def _whatsapp_item(row: sqlite3.Row) -> IndexedItem:
    body = _clean_body(row["body"] or "")
    created_at = _iso_from_unix_seconds(row["timestamp"])
    sender = "Me" if row["from_me"] else (row["sender"] or "?")
    account = str(row["account_id"] or "local")
    chat_id = str(row["chat_id"])
    message_id = str(
        row["message_id"] or f"{chat_id}:{row['timestamp']}:{sender}:{_hash_body(body)}"
    )
    display_name = str(row["display_name"] or chat_id)
    return IndexedItem(
        source="whatsapp",
        account=account,
        external_id=message_id,
        thread_id=chat_id,
        kind="whatsapp",
        created_at=created_at,
        updated_at=created_at,
        ingested_at=datetime.now(UTC).isoformat(),
        sender=sender,
        recipients_json=_json([]),
        subject=display_name,
        snippet=body[:240],
        body_text=body,
        body_hash=_hash_body(body),
        labels_json=_json([row["message_type"] or "chat"]),
        raw_pointer=f"whatsapp:{account}:{chat_id}:{message_id}",
        is_deleted=0,
        is_read=1,
    )


def _linkedin_item(row: sqlite3.Row) -> IndexedItem:
    body = _clean_body(row["body"] or "")
    created_at = _iso_from_unix_seconds(row["timestamp"])
    sender = "Me" if row["from_me"] else (row["sender"] or "?")
    account = str(row["account_id"] or "local")
    thread_id = str(row["thread_id"])
    message_id = str(
        row["message_id"] or f"{thread_id}:{row['timestamp']}:{sender}:{_hash_body(body)}"
    )
    display_name = str(row["display_name"] or thread_id)
    return IndexedItem(
        source="linkedin",
        account=account,
        external_id=message_id,
        thread_id=thread_id,
        kind="linkedin",
        created_at=created_at,
        updated_at=created_at,
        ingested_at=datetime.now(UTC).isoformat(),
        sender=sender,
        recipients_json=_json([]),
        subject=display_name,
        snippet=body[:240],
        body_text=body,
        body_hash=_hash_body(body),
        labels_json=_json(["linkedin"]),
        raw_pointer=f"linkedin:{account}:{thread_id}:{message_id}",
        is_deleted=0,
        is_read=1,
    )


def _sync_whatsapp_from_openhuman(store: MessageIndexStore, *, full_sync: bool) -> dict[str, int]:
    rows = _openhuman_whatsapp_rows()
    checkpoints: dict[str, int] = {}
    counts: dict[str, int] = {}
    highest_ts: dict[str, int] = {}
    started: set[str] = set()

    for row in rows:
        account = str(row["account_id"] or "local")
        if account not in checkpoints:
            state = store.get_sync_state("whatsapp", account) or {}
            checkpoints[account] = 0 if full_sync else int(state.get("checkpoint_value", "0") or 0)
            highest_ts[account] = checkpoints[account]
        ts = int(row["timestamp"] or 0)
        highest_ts[account] = max(highest_ts[account], ts)
        if ts <= checkpoints[account]:
            continue
        body = _clean_body(row["body"] or "")
        if not body:
            continue
        if account not in started:
            store.mark_sync_started(
                source="whatsapp",
                account=account,
                checkpoint_type="unixTimestamp",
                checkpoint_value=str(checkpoints[account]),
                metadata={"messages_processed": 0},
            )
            started.add(account)
        store.upsert_item(_whatsapp_item(row))
        counts[account] = counts.get(account, 0) + 1
        if counts[account] % WHATSAPP_PROGRESS_EVERY == 0:
            store.update_sync_progress(
                source="whatsapp",
                account=account,
                checkpoint_type="unixTimestamp",
                checkpoint_value=str(highest_ts[account]),
                metadata={"messages_processed": counts[account]},
            )

    for account in sorted(set(checkpoints) | set(counts)):
        store.set_sync_state(
            source="whatsapp",
            account=account,
            checkpoint_type="unixTimestamp",
            checkpoint_value=str(highest_ts.get(account, checkpoints.get(account, 0))),
            full_sync=full_sync,
            status="idle",
            metadata={"messages_processed": counts.get(account, 0)},
        )
    return counts


def sync_whatsapp_bootstrap(store: MessageIndexStore) -> dict[str, int]:
    return _sync_whatsapp_from_openhuman(store, full_sync=True)


def sync_whatsapp_incremental(store: MessageIndexStore) -> dict[str, int]:
    return _sync_whatsapp_from_openhuman(store, full_sync=False)


def _sync_linkedin_from_openhuman(store: MessageIndexStore, *, full_sync: bool) -> dict[str, int]:
    rows = _openhuman_linkedin_rows()
    checkpoints: dict[str, int] = {}
    counts: dict[str, int] = {}
    highest_ts: dict[str, int] = {}
    started: set[str] = set()

    for row in rows:
        account = str(row["account_id"] or "local")
        if account not in checkpoints:
            state = store.get_sync_state("linkedin", account) or {}
            checkpoints[account] = 0 if full_sync else int(state.get("checkpoint_value", "0") or 0)
            highest_ts[account] = checkpoints[account]
        ts = int(row["timestamp"] or 0)
        highest_ts[account] = max(highest_ts[account], ts)
        if ts <= checkpoints[account]:
            continue
        body = _clean_body(row["body"] or "")
        if not body:
            continue
        if account not in started:
            store.mark_sync_started(
                source="linkedin",
                account=account,
                checkpoint_type="unixTimestamp",
                checkpoint_value=str(checkpoints[account]),
                metadata={"messages_processed": 0},
            )
            started.add(account)
        store.upsert_item(_linkedin_item(row))
        counts[account] = counts.get(account, 0) + 1
        if counts[account] % LINKEDIN_PROGRESS_EVERY == 0:
            store.update_sync_progress(
                source="linkedin",
                account=account,
                checkpoint_type="unixTimestamp",
                checkpoint_value=str(highest_ts[account]),
                metadata={"messages_processed": counts[account]},
            )

    for account in sorted(set(checkpoints) | set(counts)):
        store.set_sync_state(
            source="linkedin",
            account=account,
            checkpoint_type="unixTimestamp",
            checkpoint_value=str(highest_ts.get(account, checkpoints.get(account, 0))),
            full_sync=full_sync,
            status="idle",
            metadata={"messages_processed": counts.get(account, 0)},
        )
    return counts


def sync_linkedin_bootstrap(store: MessageIndexStore) -> dict[str, int]:
    return _sync_linkedin_from_openhuman(store, full_sync=True)


def sync_linkedin_incremental(store: MessageIndexStore) -> dict[str, int]:
    return _sync_linkedin_from_openhuman(store, full_sync=False)


def _changed_scopes(source: str, stats: dict[str, int]) -> set[SyncScope]:
    return {(source, account) for account, count in stats.items() if count > 0}


def rebuild_changed_threads(
    store: MessageIndexStore, scopes: set[SyncScope]
) -> dict[SyncScope, int]:
    rebuilt: dict[SyncScope, int] = {}
    for source, account in sorted(scopes):
        rebuilt[(source, account)] = store.rebuild_threads(source=source, account=account)
    return rebuilt


def rebuild_all_threads(store: MessageIndexStore) -> int:
    return store.rebuild_threads()


def bootstrap(store: MessageIndexStore) -> dict[str, dict[str, int]]:
    gmail_stats = sync_gmail_bootstrap(store)
    imessage_stats = sync_imessage_bootstrap(store)
    whatsapp_stats = sync_whatsapp_bootstrap(store)
    linkedin_stats = sync_linkedin_bootstrap(store)
    result = {
        "gmail": gmail_stats,
        "imessage": imessage_stats,
        "whatsapp": whatsapp_stats,
        "linkedin": linkedin_stats,
    }
    rebuild_changed_threads(
        store,
        _changed_scopes("gmail", gmail_stats)
        | _changed_scopes("imessage", imessage_stats)
        | _changed_scopes("whatsapp", whatsapp_stats)
        | _changed_scopes("linkedin", linkedin_stats),
    )
    return result


def incremental(store: MessageIndexStore) -> dict[str, dict[str, int]]:
    gmail_stats = sync_gmail_incremental(store)
    imessage_stats = sync_imessage_incremental(store)
    whatsapp_stats = sync_whatsapp_incremental(store)
    linkedin_stats = sync_linkedin_incremental(store)
    result = {
        "gmail": gmail_stats,
        "imessage": imessage_stats,
        "whatsapp": whatsapp_stats,
        "linkedin": linkedin_stats,
    }
    rebuild_changed_threads(
        store,
        _changed_scopes("gmail", gmail_stats)
        | _changed_scopes("imessage", imessage_stats)
        | _changed_scopes("whatsapp", whatsapp_stats)
        | _changed_scopes("linkedin", linkedin_stats),
    )
    return result


def print_summary(store: MessageIndexStore, limit: int) -> None:
    for row in store.list_threads(limit=limit, actionable_only=True, newest_only=True):
        print(
            f"{row['latest_item_at']} | {row['source']} | {row['actionability']} | "
            f"{row['urgency']} | {row['summary']}"
        )


def smoke_contract() -> dict[str, object]:
    return {
        "ok": True,
        "entrypoint": "message_sync.py",
        "modes": list(CLI_MODES),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize raw inbox sources into a local index."
    )
    parser.add_argument("mode", nargs="?", choices=CLI_MODES)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Verify CLI imports and argument parsing without touching data stores or auth.",
    )
    parser.add_argument("--db", default="", help="Override index database path.")
    parser.add_argument("--limit", type=int, default=20, help="Summary row limit.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.smoke:
        print(_json(smoke_contract()))
        return 0

    if not args.mode:
        parser.error("mode is required unless --smoke is provided")

    store = MessageIndexStore(Path(args.db).expanduser() if args.db else None)
    if args.mode == "bootstrap":
        print(bootstrap(store))
    elif args.mode == "incremental":
        print(incremental(store))
    elif args.mode == "rebuild":
        print({"threads": rebuild_all_threads(store)})
    else:
        print_summary(store, args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
