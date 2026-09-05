from __future__ import annotations

import os
import stat

from lifeops.read_receipt_store import ReadReceiptStore


def _receipt(run_id: str, *, transport_complete: bool = True) -> dict:
    return {
        "schema_version": "lifeops.triage_receipt.v1",
        "run_id": run_id,
        "started_at": "2026-08-26T10:00:00+00:00",
        "finished_at": "2026-08-26T10:00:01+00:00",
        "account": "account@example.com",
        "account_scope": "selected_account",
        "limit": 1,
        "use_model": False,
        "read_only": True,
        "transport_complete": transport_complete,
        "sources": [{"name": "gmail", "path": "/inbox/now", "status": "ok"}],
        "note": "metadata only",
    }


def test_read_receipt_store_round_trips_metadata_and_is_owner_only(tmp_path):
    store = ReadReceiptStore(tmp_path / "nested" / "receipts.sqlite3")
    receipt = _receipt("triage:one")

    assert store.record(receipt) == {"status": "stored", "run_id": "triage:one"}
    assert store.get("triage:one") == receipt
    assert store.list_recent(10) == [receipt]
    assert stat.S_IMODE(os.stat(store.db_path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(store.db_path.parent).st_mode) == 0o700


def test_read_receipt_store_updates_same_run_without_duplicates(tmp_path):
    store = ReadReceiptStore(tmp_path / "receipts.sqlite3")
    first = _receipt("triage:one")
    second = _receipt("triage:one", transport_complete=False)

    store.record(first)
    store.record(second)

    assert store.get("triage:one")["transport_complete"] is False
    assert len(store.list_recent(10)) == 1
