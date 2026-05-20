import httpx
import pytest

import egress_audit
from egress_audit import EgressAuditRecord, EgressAuditStore

pytestmark = pytest.mark.safe


def test_egress_store_lists_recent_records(tmp_path):
    store = EgressAuditStore(tmp_path / "egress.sqlite3")
    store.record(
        EgressAuditRecord(
            method="GET",
            url="https://api.github.com/notifications",
            host="api.github.com",
            allowed=True,
            blocked=False,
            status_code=200,
        )
    )

    rows = store.list_recent()

    assert rows[0]["host"] == "api.github.com"
    assert rows[0]["status_code"] == 200
    assert rows[0]["blocked"] is False


def test_egress_request_blocks_unallowlisted_host_in_local_only(monkeypatch, tmp_path):
    store = EgressAuditStore(tmp_path / "egress.sqlite3")
    monkeypatch.setattr(egress_audit, "audit_store", lambda: store)
    monkeypatch.setenv("INBOX_LOCAL_ONLY", "1")
    monkeypatch.setenv("INBOX_EGRESS_ALLOWLIST", "api.github.com")

    with pytest.raises(httpx.RequestError):
        egress_audit.get("https://example.com/private")

    rows = store.list_recent()
    assert rows[0]["host"] == "example.com"
    assert rows[0]["blocked"] is True
