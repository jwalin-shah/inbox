"""Shared approval-gate helpers for inbox tests."""

from __future__ import annotations


def wrap_approval_lease(c):
    """Patch client.request to auto-mint approval leases for gated endpoints.

    Call after creating a TestClient to avoid 403s on write endpoints
    in tests that aren't specifically testing the approval gate.
    """
    import inbox_server as _srv

    original = c.request

    def _request(method, url, **kwargs):
        path = str(url)
        rule = _srv._approval_rule_for_request(method.upper(), path.split("?", 1)[0])
        headers = dict(kwargs.pop("headers", {}) or {})
        if rule is not None and "X-Inbox-Approval-Lease" not in headers:
            headers["X-Inbox-Approval-Lease"] = _srv.mint_local_approval_lease(
                method.upper(), path, body=kwargs.get("json")
            )
        return original(method, url, headers=headers, **kwargs)

    c.request = _request
