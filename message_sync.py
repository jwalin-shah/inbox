from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import getaddresses
from pathlib import Path
from typing import Any

from googleapiclient.errors import HttpError

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
GMAIL_API_UNIT_COSTS = {
    "users.history.list": 2,
    "users.messages.get": 20,
    "users.messages.list": 5,
    "users.getProfile": 1,
}
IMESSAGE_PROGRESS_EVERY = 250
WHATSAPP_PROGRESS_EVERY = 250
LINKEDIN_PROGRESS_EVERY = 250
_ATTACHMENT_TEXT = "(attachment)"


class GmailHistoryCursorExpired(Exception):
    """history.list returned 404 — startHistoryId is too old for incremental replay."""


@dataclass
class _GmailApiUnitMeter:
    """Accumulate Gmail API quota units attributable by method (account is sync-state key)."""

    account: str
    units: dict[str, int] = field(default_factory=dict)

    def record(self, method: str, *, calls: int = 1) -> None:
        cost = GMAIL_API_UNIT_COSTS.get(method, 0) * calls
        if cost:
            self.units[method] = self.units.get(method, 0) + cost

    def as_metadata(self) -> dict[str, object]:
        return {
            "api_units_account": self.account,
            "api_units": dict(sorted(self.units.items())),
            "api_units_total": sum(self.units.values()),
        }


@dataclass
class _HistoryMessageChange:
    message_id: str
    message_added: bool = False
    labels_added: set[str] = field(default_factory=set)
    labels_removed: set[str] = field(default_factory=set)
    snapshot_label_ids: list[str] | None = None
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
    return json.dumps(value, sort_keys=True)


def _http_error_status(exc: HttpError) -> int | None:
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _fetch_gmail_full_message(
    service: Any, message_id: str, *, meter: _GmailApiUnitMeter | None = None
) -> dict[str, Any]:
    if meter is not None:
        meter.record("users.messages.get")
    return service.users().messages().get(userId="me", id=message_id, format="full").execute()


def _fetch_gmail_profile_history_id(
    service: Any, *, meter: _GmailApiUnitMeter | None = None
) -> str:
    try:
        request = service.users().getProfile(userId="me")
    except AttributeError:
        return ""
    if meter is not None:
        meter.record("users.getProfile")
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
    api_units: dict[str, object] | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "messages_processed": count,
        "cursor_mode": "timestamp_fallback",
        "fallback_reason": fallback_reason,
        "timestamp_checkpoint_ms": str(checkpoint),
    }
    if api_units:
        metadata.update(api_units)
    return metadata


def _gmail_history_metadata(
    *,
    count: int,
    history_id: str,
    timestamp_checkpoint: int,
    api_units: dict[str, object] | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "messages_processed": count,
        "cursor_mode": "history",
        "history_id": history_id,
        "timestamp_checkpoint_ms": str(timestamp_checkpoint),
    }
    if api_units:
        metadata.update(api_units)
    return metadata


def _history_message_changes(history_entries: list[dict[str, Any]]) -> list[_HistoryMessageChange]:
    changes: dict[str, _HistoryMessageChange] = {}
    order: list[str] = []

    def _change_for(message_id: str) -> _HistoryMessageChange:
        if message_id not in changes:
            changes[message_id] = _HistoryMessageChange(message_id=message_id)
            order.append(message_id)
        return changes[message_id]

    for entry in history_entries:
        for added in entry.get("messagesAdded", []):
            message = added.get("message") or {}
            message_id = str(message.get("id") or "")
            if not message_id:
                continue
            change = _change_for(message_id)
            change.message_added = True
            if "labelIds" in message:
                change.snapshot_label_ids = [str(label) for label in message.get("labelIds") or []]
        for key, target in (("labelsAdded", "labels_added"), ("labelsRemoved", "labels_removed")):
            for label_change in entry.get(key, []):
                message = label_change.get("message") or {}
                message_id = str(message.get("id") or "")
                if not message_id:
                    continue
                change = _change_for(message_id)
                getattr(change, target).update(
                    str(label) for label in label_change.get("labelIds") or []
                )
                if "labelIds" in message:
                    change.snapshot_label_ids = [
                        str(label) for label in message.get("labelIds") or []
                    ]
    return [changes[message_id] for message_id in order]


def _history_message_ids(history_entries: list[dict[str, Any]]) -> list[str]:
    return [change.message_id for change in _history_message_changes(history_entries)]


def _apply_cached_label_change(
    item: IndexedItem, change: _HistoryMessageChange
) -> IndexedItem:
    if change.snapshot_label_ids is not None:
        labels = list(change.snapshot_label_ids)
    else:
        labels = [str(label) for label in json.loads(item.labels_json or "[]")]
        labels = [label for label in labels if label not in change.labels_removed]
        for label in change.labels_added:
            if label not in labels:
                labels.append(label)
    return IndexedItem(
        source=item.source,
        account=item.account,
        external_id=item.external_id,
        thread_id=item.thread_id,
        kind=item.kind,
        created_at=item.created_at,
        updated_at=datetime.now(UTC).isoformat(),
        ingested_at=item.ingested_at,
        sender=item.sender,
        recipients_json=item.recipients_json,
        subject=item.subject,
        snippet=item.snippet,
        body_text=item.body_text,
        body_hash=item.body_hash,
        labels_json=_json(labels),
        raw_pointer=item.raw_pointer,
        is_deleted=item.is_deleted,
        is_read=0 if "UNREAD" in labels else 1,
    )


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
    pending_changes: list[_HistoryMessageChange] = []
    meter = _GmailApiUnitMeter(account=account)
    store.mark_sync_started(
        source="gmail",
        account=account,
        checkpoint_type=GMAIL_HISTORY_CURSOR,
        checkpoint_value=history_id,
        metadata=_gmail_history_metadata(
            count=0,
            history_id=history_id,
            timestamp_checkpoint=timestamp_checkpoint,
            api_units=meter.as_metadata(),
        ),
    )
    try:
        while True:
            try:
                response = history_api.list(
                    userId="me",
                    startHistoryId=history_id,
                    pageToken=page_token,
                    historyTypes=["messageAdded", "labelAdded", "labelRemoved"],
                ).execute()
            except HttpError as exc:
                if _http_error_status(exc) == 404:
                    raise GmailHistoryCursorExpired(
                        f"history cursor expired for {account}: startHistoryId={history_id}"
                    ) from exc
                raise
            meter.record("users.history.list")
            latest_history_id = str(response.get("historyId") or latest_history_id)
            pending_changes.extend(_history_message_changes(response.get("history", [])))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        # Merge duplicate message ids across pages while preserving first-seen order.
        merged: dict[str, _HistoryMessageChange] = {}
        order: list[str] = []
        for change in pending_changes:
            existing = merged.get(change.message_id)
            if existing is None:
                merged[change.message_id] = change
                order.append(change.message_id)
                continue
            existing.message_added = existing.message_added or change.message_added
            existing.labels_added.update(change.labels_added)
            existing.labels_removed.update(change.labels_removed)
            if change.snapshot_label_ids is not None:
                existing.snapshot_label_ids = change.snapshot_label_ids

        count = 0
        for message_id in order:
            change = merged[message_id]
            cached = store.get_item(source="gmail", account=account, external_id=message_id)
            label_only = (
                not change.message_added
                and (change.labels_added or change.labels_removed or change.snapshot_label_ids)
            )
            if label_only and cached is not None:
                store.upsert_item(_apply_cached_label_change(cached, change))
                count += 1
                continue

            try:
                full_message = _fetch_gmail_full_message(service, message_id, meter=meter)
            except HttpError as exc:
                if _http_error_status(exc) != 404:
                    raise
                store.mark_item_deleted(source="gmail", account=account, external_id=message_id)
                count += 1
                continue
            timestamp_checkpoint = max(
                timestamp_checkpoint, int(full_message.get("internalDate", 0) or 0)
            )
            store.upsert_item(_gmail_item(account, full_message))
            count += 1

        # Cursor advances only after every local application above succeeded.
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
                api_units=meter.as_metadata(),
            ),
        )
        return count
    except GmailHistoryCursorExpired:
        # Caller performs bounded timestamp recovery; do not poison status here.
        raise
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
    meter = _GmailApiUnitMeter(account=account)
    store.mark_sync_started(
        source="gmail",
        account=account,
        checkpoint_type=GMAIL_TIMESTAMP_CURSOR,
        checkpoint_value=str(checkpoint),
        metadata=_gmail_timestamp_metadata(
            count=0,
            checkpoint=checkpoint,
            fallback_reason=fallback_reason,
            api_units=meter.as_metadata(),
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
            meter.record("users.messages.list")
            messages = response.get("messages", [])
            if not messages:
                break
            for stub in messages:
                full_message = _fetch_gmail_full_message(service, stub["id"], meter=meter)
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
                    api_units=meter.as_metadata(),
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
            api_units=meter.as_metadata(),
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
            try:
                stats[account] = _sync_gmail_incremental_history(
                    store,
                    account=account,
                    service=service,
                    history_api=history_api,
                    history_id=history_id,
                    timestamp_checkpoint=timestamp_checkpoint,
                )
            except GmailHistoryCursorExpired:
                # Bounded recovery: one timestamp fallback classified as expired cursor.
                stats[account] = _sync_gmail_incremental_timestamp(
                    store,
                    account=account,
                    service=service,
                    checkpoint=timestamp_checkpoint,
                    fallback_reason="expired_history_cursor",
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
