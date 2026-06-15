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
