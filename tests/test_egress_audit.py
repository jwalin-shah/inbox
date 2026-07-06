import httpx
import pytest

import egress_audit
from egress_audit import (
    ALLOWLIST_ENV,
    LOCAL_ONLY_ENV,
    EgressAuditRecord,
    EgressAuditStore,
    _is_local_host,
    _normalize_host,
    _reset_allowed_hosts_cache,
    allowed_hosts,
    host_allowed,
)

pytestmark = pytest.mark.safe


@pytest.fixture(autouse=True)
def _reset_allowed_cache():
    """Ensure the allowlist cache is reset around every test."""
    _reset_allowed_hosts_cache()
    yield
    _reset_allowed_hosts_cache()


@pytest.fixture
def clean_env(monkeypatch):
    """Provide a monkeypatch with both env vars cleared."""
    monkeypatch.delenv(ALLOWLIST_ENV, raising=False)
    monkeypatch.delenv(LOCAL_ONLY_ENV, raising=False)
    return monkeypatch


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def test_normalize_host_lowercases_and_strips_port():
    assert _normalize_host("Example.COM") == "example.com"
    assert _normalize_host("Example.COM:443") == "example.com"
    assert _normalize_host("EXAMPLE.COM.") == "example.com"
    assert _normalize_host("api.github.com:443") == "api.github.com"
    # IPv6 (bracketed and unbracketed)
    assert _normalize_host("[::1]:8080") == "::1"
    assert _normalize_host("[2001:db8::1]:443") == "2001:db8::1"
    assert _normalize_host("::1") == "::1"
    # Empty / blank
    assert _normalize_host("") == ""
    assert _normalize_host("   ") == ""


def test_is_local_host_recognises_loopback_variants():
    assert _is_local_host("localhost") is True
    assert _is_local_host("LOCALHOST") is True
    assert _is_local_host("localhost:8080") is True
    assert _is_local_host("127.0.0.1") is True
    assert _is_local_host("127.0.0.1:8080") is True
    assert _is_local_host("[::1]:9000") is True
    assert _is_local_host("example.com") is False


# ---------------------------------------------------------------------------
# Local-only short-circuit
# ---------------------------------------------------------------------------


def test_localhost_passes_under_local_only_mode(clean_env):
    clean_env.setenv(LOCAL_ONLY_ENV, "1")
    # Loopback variants in many shapes
    assert host_allowed("localhost") is True
    assert host_allowed("LOCALHOST") is True
    assert host_allowed("localhost:8080") is True
    assert host_allowed("127.0.0.1") is True
    assert host_allowed("127.0.0.1:8080") is True
    assert host_allowed("[::1]:8080") is True
    # External hosts are blocked under local-only mode
    assert host_allowed("api.github.com") is False
    assert host_allowed("evil.example.com") is False


def test_local_only_does_not_consult_allowlist(clean_env):
    clean_env.setenv(LOCAL_ONLY_ENV, "true")
    clean_env.setenv(ALLOWLIST_ENV, "api.github.com")
    # Even with an allowlisted host, local-only permits loopback only
    assert host_allowed("localhost") is True
    assert host_allowed("api.github.com") is False


# ---------------------------------------------------------------------------
# Allowlist matching
# ---------------------------------------------------------------------------


def test_external_hosts_match_case_insensitive_with_or_without_port(clean_env):
    clean_env.setenv(ALLOWLIST_ENV, "api.github.com,Maps.Googleapis.com")
    # Case-insensitive
    assert host_allowed("api.github.com") is True
    assert host_allowed("API.GITHUB.COM") is True
    assert host_allowed("Api.GitHub.Com") is True
    # Port stripped
    assert host_allowed("api.github.com:443") is True
    assert host_allowed("Api.GitHub.Com:8443") is True
    assert host_allowed("maps.googleapis.com") is True
    assert host_allowed("MAPS.GOOGLEAPIS.COM:8080") is True
    # Trailing dot stripped
    assert host_allowed("api.github.com.") is True
    # Subdomain suffix matching still works
    assert host_allowed("v3.api.github.com") is True
    # Non-allowlisted host denied
    assert host_allowed("evil.example.com") is False


def test_default_allowlist_matches_case_insensitive(clean_env):
    # No env override -> default allowlist is consulted
    assert host_allowed("api.github.com") is True
    assert host_allowed("API.GITHUB.COM") is True
    assert host_allowed("Api.GitHub.Com:443") is True
    assert host_allowed("maps.googleapis.com") is True
    assert host_allowed("v3.api.github.com") is True


def test_empty_or_blank_host_is_denied(clean_env):
    assert host_allowed("") is False
    assert host_allowed("   ") is False


# ---------------------------------------------------------------------------
# Cache behavior
# ---------------------------------------------------------------------------


def test_allowed_hosts_cache_respects_reset(clean_env):
    clean_env.setenv(ALLOWLIST_ENV, "api.github.com")
    assert allowed_hosts() == {"api.github.com"}
    # Change env and reset cache; the new value should be observed
    clean_env.setenv(ALLOWLIST_ENV, "other.example.com")
    _reset_allowed_hosts_cache()
    assert allowed_hosts() == {"other.example.com"}


# ---------------------------------------------------------------------------
# End-to-end behavior with the audit store
# ---------------------------------------------------------------------------


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
    # The cache is populated lazily; flush it so the new env takes effect.
    _reset_allowed_hosts_cache()

    with pytest.raises(httpx.RequestError):
        egress_audit.get("https://example.com/private")

    rows = store.list_recent()
    assert rows[0]["host"] == "example.com"
    assert rows[0]["blocked"] is True


# ---------------------------------------------------------------------------
# local_only_enabled
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1", True),
        ("true", True),
        ("yes", True),
        ("on", True),
        ("TRUE", True),
        ("YES", True),
        ("ON", True),
        ("0", False),
        ("false", False),
        ("no", False),
        ("off", False),
        ("", False),
        ("random", False),
    ],
)
def test_local_only_enabled_detects_truthy_values(clean_env, value, expected):
    from egress_audit import local_only_enabled

    if value:
        clean_env.setenv(LOCAL_ONLY_ENV, value)
    assert local_only_enabled() is expected


# ---------------------------------------------------------------------------
# EgressAuditRecord.to_dict
# ---------------------------------------------------------------------------


def test_egress_audit_record_to_dict_includes_all_fields():
    record = EgressAuditRecord(
        method="POST",
        url="https://example.com/api",
        host="example.com",
        allowed=False,
        blocked=True,
        status_code=403,
        error="Forbidden",
        timestamp="2026-07-06T00:00:00+00:00",
    )
    d = record.to_dict()
    assert d["method"] == "POST"
    assert d["url"] == "https://example.com/api"
    assert d["host"] == "example.com"
    assert d["allowed"] is False
    assert d["blocked"] is True
    assert d["status_code"] == 403
    assert d["error"] == "Forbidden"
    assert d["timestamp"] == "2026-07-06T00:00:00+00:00"


def test_egress_audit_record_defaults():
    """EgressAuditRecord fields default to None/empty string when omitted."""
    record = EgressAuditRecord(method="GET", url="http://x", host="x", allowed=True, blocked=False)
    d = record.to_dict()
    assert d["status_code"] is None
    assert d["error"] == ""
    assert d["timestamp"] == ""


# ---------------------------------------------------------------------------
# EgressAuditStore — record and list_recent edge cases
# ---------------------------------------------------------------------------


def test_egress_store_list_recent_empty(tmp_path):
    """list_recent() on an empty store returns an empty list."""
    store = EgressAuditStore(tmp_path / "egress.sqlite3")
    assert store.list_recent() == []


def test_egress_store_list_recent_respects_limit(tmp_path):
    store = EgressAuditStore(tmp_path / "egress.sqlite3")
    for i in range(5):
        store.record(
            EgressAuditRecord(
                method="GET",
                url=f"https://api.github.com/{i}",
                host="api.github.com",
                allowed=True,
                blocked=False,
                status_code=200,
            )
        )
    assert len(store.list_recent(limit=2)) == 2
    assert len(store.list_recent(limit=10)) == 5


def test_egress_store_record_with_custom_timestamp(tmp_path):
    store = EgressAuditStore(tmp_path / "egress.sqlite3")
    store.record(
        EgressAuditRecord(
            method="GET",
            url="https://api.github.com/x",
            host="api.github.com",
            allowed=True,
            blocked=False,
            timestamp="2025-01-01T12:00:00+00:00",
        )
    )
    rows = store.list_recent()
    assert rows[0]["timestamp"] == "2025-01-01T12:00:00+00:00"


# ---------------------------------------------------------------------------
# audit_store singleton
# ---------------------------------------------------------------------------


def test_audit_store_returns_same_instance(monkeypatch, tmp_path):
    """audit_store() is a singleton — repeated calls return the same EgressAuditStore."""
    import egress_audit as ea

    monkeypatch.setattr(ea, "EGRESS_AUDIT_DB", tmp_path / "egress.sqlite3")

    original_store = ea._DEFAULT_STORE
    ea._DEFAULT_STORE = None
    try:
        store1 = ea.audit_store()
        store2 = ea.audit_store()
        assert store1 is store2
        assert isinstance(store1, EgressAuditStore)
    finally:
        ea._DEFAULT_STORE = original_store


# ---------------------------------------------------------------------------
# request() – success & error paths
# ---------------------------------------------------------------------------


def test_request_allowed_success(monkeypatch, tmp_path):
    """request() sends an HTTP call and records an allowed-audit entry on success."""
    import egress_audit as ea

    store = EgressAuditStore(tmp_path / "egress.sqlite3")
    monkeypatch.setattr(ea, "audit_store", lambda: store)

    mock_response = httpx.Response(200, json={"ok": True})
    monkeypatch.setattr(httpx, "request", lambda *a, **kw: mock_response)

    response = ea.request("GET", "https://api.github.com/repos")
    assert response is mock_response

    rows = store.list_recent()
    assert len(rows) == 1
    assert rows[0]["allowed"] is True
    assert rows[0]["blocked"] is False
    assert rows[0]["status_code"] == 200
    assert rows[0]["error"] == ""


def test_request_records_error_on_exception(monkeypatch, tmp_path):
    """request() records the error in the audit store when httpx raises."""
    import egress_audit as ea

    store = EgressAuditStore(tmp_path / "egress.sqlite3")
    monkeypatch.setattr(ea, "audit_store", lambda: store)

    def _raise(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "request", _raise)

    with pytest.raises(httpx.ConnectError):
        ea.request("GET", "https://api.github.com/repos")

    rows = store.list_recent()
    assert len(rows) == 1
    assert rows[0]["allowed"] is True
    assert rows[0]["blocked"] is False
    assert "connection refused" in rows[0]["error"]


def test_request_blocked_path_uses_upper_method_in_record(monkeypatch, tmp_path):
    """Blocked requests log the uppercased method name."""
    import egress_audit as ea

    store = EgressAuditStore(tmp_path / "egress.sqlite3")
    monkeypatch.setattr(ea, "audit_store", lambda: store)
    monkeypatch.setenv("INBOX_LOCAL_ONLY", "1")
    _reset_allowed_hosts_cache()

    with pytest.raises(httpx.RequestError):
        ea.request("get", "https://evil.example.com/private")

    rows = store.list_recent()
    assert rows[0]["method"] == "GET"


# ---------------------------------------------------------------------------
# HTTP method wrappers
# ---------------------------------------------------------------------------


def test_get_delegates_to_request(monkeypatch, tmp_path):
    """get() delegates to request('GET', ...)."""
    import egress_audit as ea

    store = EgressAuditStore(tmp_path / "egress.sqlite3")
    monkeypatch.setattr(ea, "audit_store", lambda: store)

    mock_response = httpx.Response(200)
    monkeypatch.setattr(httpx, "request", lambda *a, **kw: mock_response)

    response = ea.get("https://api.github.com/repos")
    assert response.status_code == 200
    rows = store.list_recent()
    assert rows[0]["method"] == "GET"


def test_patch_delegates_to_request(monkeypatch, tmp_path):
    """patch() delegates to request('PATCH', ...)."""
    import egress_audit as ea

    store = EgressAuditStore(tmp_path / "egress.sqlite3")
    monkeypatch.setattr(ea, "audit_store", lambda: store)

    mock_response = httpx.Response(200)
    monkeypatch.setattr(httpx, "request", lambda *a, **kw: mock_response)

    response = ea.patch("https://api.github.com/repos")
    assert response.status_code == 200
    rows = store.list_recent()
    assert rows[0]["method"] == "PATCH"


def test_put_delegates_to_request(monkeypatch, tmp_path):
    """put() delegates to request('PUT', ...)."""
    import egress_audit as ea

    store = EgressAuditStore(tmp_path / "egress.sqlite3")
    monkeypatch.setattr(ea, "audit_store", lambda: store)

    mock_response = httpx.Response(200)
    monkeypatch.setattr(httpx, "request", lambda *a, **kw: mock_response)

    response = ea.put("https://api.github.com/repos")
    assert response.status_code == 200
    rows = store.list_recent()
    assert rows[0]["method"] == "PUT"


# ---------------------------------------------------------------------------
# status()
# ---------------------------------------------------------------------------


def test_status_returns_metadata(monkeypatch, tmp_path):
    """status() returns local_only, allowlist, db_path, and metadata."""
    import egress_audit as ea

    store = EgressAuditStore(tmp_path / "egress.sqlite3")
    monkeypatch.setattr(ea, "audit_store", lambda: store)

    result = ea.status()
    assert result["local_only"] is False
    assert "api.github.com" in result["allowlist"]
    assert result["allowlist"] == sorted(ea.allowed_hosts())
    assert result["db_path"] == str(store.db_path)
    assert result["direct_httpx_wrapped"] is True
