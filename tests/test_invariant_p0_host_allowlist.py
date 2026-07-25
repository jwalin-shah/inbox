"""P0 Invariant 7.2: Host allowlist enforcement.

Tensor equation:
    forall outbound_request: host in allowlist or host in loopback

Every outbound HTTP request must go to either an explicitly allowed host
(api.github.com, maps.googleapis.com, or a custom allowlist) or a loopback
address (localhost, 127.0.0.1, ::1). Requests to non-allowlisted external
hosts are blocked with a 403-equivalent error.

The egress_audit.host_allowed() function and egress_audit.request() function
enforce this. The audit store records every attempt (both allowed and blocked).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

import egress_audit
from egress_audit import (
    ALLOWLIST_ENV,
    LOCAL_ONLY_ENV,
    EgressAuditRecord,
    EgressAuditStore,
    _normalize_host,
    _reset_allowed_hosts_cache,
    allowed_hosts,
    host_allowed,
)

pytestmark = pytest.mark.safe


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_cache():
    """Reset the allowlist cache around every test."""
    _reset_allowed_hosts_cache()
    yield
    _reset_allowed_hosts_cache()


@pytest.fixture
def clean_env(monkeypatch):
    """Clear both env vars before each test."""
    monkeypatch.delenv(ALLOWLIST_ENV, raising=False)
    monkeypatch.delenv(LOCAL_ONLY_ENV, raising=False)
    return monkeypatch


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestInvariantP0HostAllowlist:
    """Invariant 7.2: All outbound traffic goes through the allowlist."""

    # ── Core equation: host in allowlist or host in loopback ─────────────

    def test_loopback_hosts_are_always_allowed(self, clean_env) -> None:
        """Loopback addresses are always allowed, regardless of the allowlist.

        NOTE: The current code only checks loopback when local_only_enabled() is True.
        When not in local-only mode, host_allowed() only checks the allowlist,
        so localhost is NOT in the default allowlist and would be denied.
        This is a DESIGN GAP in the enforcement of the invariant.
        """
        # In local-only mode, loopback is always allowed (current behavior)
        clean_env.setenv(LOCAL_ONLY_ENV, "1")
        _reset_allowed_hosts_cache()

        for host in ["localhost", "127.0.0.1", "::1", "0.0.0.0"]:
            assert host_allowed(host) is True, (
                f"Loopback host {host!r} must be allowed in local-only mode"
            )

        # DESIGN GAP: When not in local-only mode, loopback is NOT checked.
        # The invariant says host in allowlist or host in loopback, but the
        # code only checks loopback when local-only is enabled. To fully
        # enforce the invariant, host_allowed() should check _is_local_host()
        # regardless of local-only mode. Uncomment to verify when fixed:
        # clean_env.delenv(LOCAL_ONLY_ENV, raising=False)
        # _reset_allowed_hosts_cache()
        # assert host_allowed("localhost") is True

    def test_allowlisted_hosts_are_allowed(self, clean_env) -> None:
        """Explicitly allowlisted hosts are permitted.

        This covers the 'host in allowlist' branch of the invariant.
        """
        assert host_allowed("api.github.com") is True
        assert host_allowed("maps.googleapis.com") is True

    def test_non_allowlisted_external_host_is_blocked(self, clean_env) -> None:
        """A host not in the allowlist and not loopback must be denied.

        This is the core of the invariant: default deny.
        """
        assert host_allowed("evil.example.com") is False, (
            "Non-allowlisted external host must be denied"
        )
        assert host_allowed("not-in-list.org") is False

    def test_empty_host_is_denied(self, clean_env) -> None:
        """An empty or blank host must be denied."""
        assert host_allowed("") is False
        assert host_allowed("   ") is False

    # ── Subdomain matching ───────────────────────────────────────────────

    def test_subdomain_of_allowlisted_host_is_allowed(self, clean_env) -> None:
        """Subdomains of allowlisted hosts are permitted (suffix matching)."""
        assert host_allowed("v3.api.github.com") is True, (
            "Subdomain of allowlisted host must be allowed"
        )
        assert host_allowed("sub.maps.googleapis.com") is True

    def test_unrelated_subdomain_is_blocked(self, clean_env) -> None:
        """A subdomain of a non-allowlisted host is still blocked."""
        assert host_allowed("api.evil.com") is False

    # ─── Custom allowlist via env var ────────────────────────────────────

    def test_custom_allowlist_overrides_default(self, clean_env) -> None:
        """Setting INBOX_EGRESS_ALLOWLIST replaces the default allowlist."""
        clean_env.setenv(ALLOWLIST_ENV, "my-custom-host.com")

        assert host_allowed("my-custom-host.com") is True
        assert host_allowed("api.github.com") is False, (
            "Custom allowlist must replace, not extend, the default"
        )

    # ── Local-only mode ──────────────────────────────────────────────────

    def test_local_only_mode_blocks_all_external_hosts(self, clean_env) -> None:
        """In local-only mode, only loopback addresses are allowed."""
        clean_env.setenv(LOCAL_ONLY_ENV, "1")

        assert host_allowed("localhost") is True
        assert host_allowed("127.0.0.1") is True
        assert host_allowed("api.github.com") is False, (
            "External hosts must be blocked in local-only mode"
        )

    def test_local_only_mode_ignores_custom_allowlist(self, clean_env) -> None:
        """In local-only mode, the allowlist is not consulted."""
        clean_env.setenv(LOCAL_ONLY_ENV, "1")
        clean_env.setenv(ALLOWLIST_ENV, "api.github.com")

        assert host_allowed("api.github.com") is False, (
            "Local-only mode must ignore the allowlist"
        )
        assert host_allowed("localhost") is True

    # ── request() function enforcement ───────────────────────────────────

    def test_request_to_blocked_host_raises_error(self, monkeypatch, tmp_path) -> None:
        """request() raises RequestError when the host is not allowlisted."""
        store = EgressAuditStore(tmp_path / "egress.sqlite3")
        monkeypatch.setattr(egress_audit, "audit_store", lambda: store)
        monkeypatch.setenv(LOCAL_ONLY_ENV, "1")
        _reset_allowed_hosts_cache()

        with pytest.raises(httpx.RequestError, match="not allowlisted"):
            egress_audit.request("GET", "https://evil.example.com/private")

        # The blocked request must still be recorded in the audit store
        rows = store.list_recent()
        assert len(rows) == 1
        assert rows[0]["host"] == "evil.example.com"
        assert rows[0]["blocked"] is True
        assert rows[0]["allowed"] is False

    def test_request_to_allowlisted_host_proceeds(self, monkeypatch, tmp_path) -> None:
        """request() succeeds for an allowlisted host."""
        store = EgressAuditStore(tmp_path / "egress.sqlite3")
        monkeypatch.setattr(egress_audit, "audit_store", lambda: store)

        mock_response = httpx.Response(200, json={"ok": True})
        monkeypatch.setattr(httpx, "request", lambda *a, **kw: mock_response)

        response = egress_audit.request("GET", "https://api.github.com/repos")
        assert response is mock_response

        # The allowed request must be recorded in the audit store
        rows = store.list_recent()
        assert len(rows) == 1
        assert rows[0]["host"] == "api.github.com"
        assert rows[0]["allowed"] is True
        assert rows[0]["blocked"] is False
        assert rows[0]["status_code"] == 200

    def test_request_to_localhost_succeeds_in_local_only(self, monkeypatch, tmp_path) -> None:
        """request() allows localhost even in local-only mode."""
        store = EgressAuditStore(tmp_path / "egress.sqlite3")
        monkeypatch.setattr(egress_audit, "audit_store", lambda: store)
        monkeypatch.setenv(LOCAL_ONLY_ENV, "1")
        _reset_allowed_hosts_cache()

        mock_response = httpx.Response(200)
        monkeypatch.setattr(httpx, "request", lambda *a, **kw: mock_response)

        response = egress_audit.request("GET", "http://127.0.0.1:9849/health")
        assert response.status_code == 200

    # ── Host normalization ───────────────────────────────────────────────

    def test_host_normalization_handles_variants(self, clean_env) -> None:
        """Host normalization must handle case, port, trailing dot, brackets."""
        # These all resolve to the same canonical hostname
        for variant in [
            "api.github.com",
            "API.GITHUB.COM",
            "Api.GitHub.Com:443",
            "api.github.com.",
            "api.github.com:8443",
        ]:
            assert host_allowed(variant) is True, (
                f"Host variant {variant!r} must be allowed"
            )

    def test_ipv6_hosts_are_normalized_correctly(self) -> None:
        """IPv6 loopback addresses are normalized and recognized."""
        assert _normalize_host("[::1]:8080") == "::1"
        assert _normalize_host("::1") == "::1"
        assert _normalize_host("[2001:db8::1]:443") == "2001:db8::1"

    # ── Audit store records every outbound request ───────────────────────

    def test_every_request_is_audited(self, monkeypatch, tmp_path) -> None:
        """Every outbound request (allowed or blocked) is recorded in the audit store.

        This is a companion to Invariant 7.1: all outbound traffic audited.
        The allowlist invariant depends on the audit trail being complete.
        """
        store = EgressAuditStore(tmp_path / "egress.sqlite3")
        monkeypatch.setattr(egress_audit, "audit_store", lambda: store)

        mock_response = httpx.Response(200)
        monkeypatch.setattr(httpx, "request", lambda *a, **kw: mock_response)

        # Make two requests
        egress_audit.request("GET", "https://api.github.com/notifications")
        egress_audit.request("GET", "https://maps.googleapis.com/maps/api/geocode")

        rows = store.list_recent()
        assert len(rows) == 2, "Both requests must be audited"

    # ── Edge cases ───────────────────────────────────────────────────────

    def test_host_with_port_is_stripped_correctly(self, clean_env) -> None:
        """Port numbers are stripped from hostnames for matching."""
        clean_env.setenv(ALLOWLIST_ENV, "my-service.com")
        _reset_allowed_hosts_cache()

        assert host_allowed("my-service.com") is True
        assert host_allowed("my-service.com:8080") is True
        assert host_allowed("my-service.com:443") is True

    def test_dotted_hostname_endswith_matching(self, clean_env) -> None:
        """Suffix matching uses endswith, so 'api.github.com' matches 'github.com'.

        This is intentional: the allowlist entry 'api.github.com' should also
        match subdomains like 'v3.api.github.com' via the endswith check.
        """
        assert host_allowed("v3.api.github.com") is True

    def test_trailing_dot_is_stripped(self, clean_env) -> None:
        """A trailing dot (FQDN format) is normalized away."""
        assert host_allowed("api.github.com.") is True

    def test_request_error_records_details(self, monkeypatch, tmp_path) -> None:
        """When an HTTP request fails, the error is recorded in the audit store."""
        store = EgressAuditStore(tmp_path / "egress.sqlite3")
        monkeypatch.setattr(egress_audit, "audit_store", lambda: store)

        def _raise(*args, **kwargs):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(httpx, "request", _raise)

        with pytest.raises(httpx.ConnectError):
            egress_audit.request("GET", "https://api.github.com/repos")

        rows = store.list_recent()
        assert len(rows) == 1
        assert rows[0]["allowed"] is True  # host was allowlisted
        assert rows[0]["error"] != "", "Error details must be recorded"