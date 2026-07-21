"""Unit tests for approval_store.py — ApprovalStore CRUD + audit log."""

from __future__ import annotations

from approval_store import ApprovalStore


def _make_request(store, **overrides):
    fields = {
        "method": "POST",
        "path": "/calendar/events",
        "body": {"summary": "1:1", "account": "me@example.com"},
        "provider": "calendar",
        "operation": "create_event",
        "approval_class": "external_write",
        "executor": "inbox.calendar.create_event",
        "account_ref": "me@example.com",
        "resource_ref": "calendar:default",
        "item_count": 1,
        "payload_hash": "hash-abc",
        "query_hash": "hash-query",
    }
    fields.update(overrides)
    return store.create_request(**fields)


def test_create_request_starts_pending(tmp_path):
    store = ApprovalStore(tmp_path / "approvals.sqlite3")
    row = _make_request(store)

    assert row["request_id"].startswith("apr_")
    assert row["state"] == "pending"
    assert row["lease_id"] == ""
    assert row["decided_at"] is None


def test_get_request_roundtrips_all_fields(tmp_path):
    store = ApprovalStore(tmp_path / "approvals.sqlite3")
    created = _make_request(store)

    fetched = store.get_request(created["request_id"])

    assert fetched == created


def test_get_request_missing_returns_none(tmp_path):
    store = ApprovalStore(tmp_path / "approvals.sqlite3")
    assert store.get_request("apr_does_not_exist") is None


def test_list_requests_filters_by_state(tmp_path):
    store = ApprovalStore(tmp_path / "approvals.sqlite3")
    pending = _make_request(store)
    approved = _make_request(store, resource_ref="calendar:other")
    store.decide_request(approved["request_id"], approved=True, lease_id="lease-1")

    pending_rows = store.list_requests("pending")
    approved_rows = store.list_requests("approved")

    assert [r["request_id"] for r in pending_rows] == [pending["request_id"]]
    assert [r["request_id"] for r in approved_rows] == [approved["request_id"]]


def test_decide_request_approve_records_lease(tmp_path):
    store = ApprovalStore(tmp_path / "approvals.sqlite3")
    row = _make_request(store)

    updated = store.decide_request(
        row["request_id"], approved=True, decided_by="captain", lease_id="lease_xyz"
    )

    assert updated["state"] == "approved"
    assert updated["lease_id"] == "lease_xyz"
    assert updated["decided_by"] == "captain"
    assert updated["decided_at"] is not None


def test_decide_request_deny_records_reason(tmp_path):
    store = ApprovalStore(tmp_path / "approvals.sqlite3")
    row = _make_request(store)

    updated = store.decide_request(
        row["request_id"], approved=False, decided_by="captain", denial_reason="not now"
    )

    assert updated["state"] == "denied"
    assert updated["lease_id"] == ""
    assert updated["denial_reason"] == "not now"


def test_decide_request_twice_second_call_is_noop(tmp_path):
    store = ApprovalStore(tmp_path / "approvals.sqlite3")
    row = _make_request(store)
    store.decide_request(row["request_id"], approved=True, lease_id="lease-1")

    second = store.decide_request(row["request_id"], approved=False, denial_reason="too late")

    assert second is None
    assert store.get_request(row["request_id"])["state"] == "approved"


def test_decide_request_unknown_id_returns_none(tmp_path):
    store = ApprovalStore(tmp_path / "approvals.sqlite3")
    assert store.decide_request("apr_missing", approved=True) is None


def test_log_event_and_list_audit_log(tmp_path):
    store = ApprovalStore(tmp_path / "approvals.sqlite3")

    store.log_event(
        "approval_requested",
        request_id="apr_1",
        method="POST",
        path="/calendar/events",
        provider="calendar",
        operation="create_event",
        result="pending",
    )
    store.log_event(
        "approval_decided",
        request_id="apr_1",
        lease_id="lease_1",
        result="approved",
        actor="captain",
    )

    entries = store.list_audit_log()

    assert len(entries) == 2
    assert entries[0]["event_type"] == "approval_decided"  # most recent first
    assert entries[0]["actor"] == "captain"
    assert entries[1]["event_type"] == "approval_requested"


def test_list_audit_log_filters_by_event_type_and_request_id(tmp_path):
    store = ApprovalStore(tmp_path / "approvals.sqlite3")
    store.log_event("approval_requested", request_id="apr_1")
    store.log_event("approval_requested", request_id="apr_2")
    store.log_event("guarded_write_executed", request_id="apr_1", result="success")

    by_type = store.list_audit_log(event_type="guarded_write_executed")
    by_request = store.list_audit_log(request_id="apr_2")

    assert [e["request_id"] for e in by_type] == ["apr_1"]
    assert [e["event_type"] for e in by_request] == ["approval_requested"]


def test_store_persists_across_reconnects(tmp_path):
    db_path = tmp_path / "approvals.sqlite3"
    store = ApprovalStore(db_path)
    row = _make_request(store)
    store.log_event("approval_requested", request_id=row["request_id"])

    reopened = ApprovalStore(db_path)

    assert reopened.get_request(row["request_id"]) is not None
    assert len(reopened.list_audit_log()) == 1
