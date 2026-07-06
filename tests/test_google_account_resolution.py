"""Unit tests for google_account_resolution.py."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from google_account_resolution import (
    default_google_account,
    get_cal_service_for_account,
    get_docs_service_for_account,
    get_drive_service_for_account,
    get_gmail_service,
    get_gmail_service_for_message,
    get_sheets_service_for_account,
    get_tasks_service_for_account,
    gmail_message_or_thread_exists,
    preflight_google_write_payload,
)
from service_models import Contact

pytestmark = pytest.mark.safe


# ── Helpers ──────────────────────────────────────────────────────────────

def _state(**kwargs):
    """Return a mock with arbitrary attributes set from kwargs."""
    s = MagicMock()
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


def _contact(gmail_account="user@gmail.com", **kwargs):
    return Contact(
        id="test-id",
        name="Test",
        source="gmail",
        gmail_account=gmail_account,
        **kwargs,
    )


def _cache_key(source, id_):
    return (source, id_)


# ── default_google_account ───────────────────────────────────────────────

def test_default_google_account_empty_services_returns_empty_string():
    """Line 33: iterating empty services returns ''."""
    assert default_google_account({}) == ""


# ── get_gmail_service ────────────────────────────────────────────────────

def test_get_gmail_service_cache_hit_with_valid_account():
    """Line 44: conv_cache has contact whose gmail_account is in gmail_services."""
    contact = _contact(gmail_account="cached@gmail.com")
    svc = MagicMock()
    state = _state(
        gmail_services={"cached@gmail.com": svc},
        conv_cache={("gmail", "msg-1"): contact},
    )
    result_svc, result_contact = get_gmail_service(state, "msg-1", _cache_key)
    assert result_svc is svc
    assert result_contact is contact


# ── gmail_message_or_thread_exists ───────────────────────────────────────

def test_gmail_message_or_thread_exists_no_id_returns_false():
    """Line 82: neither msg_id nor thread_id is truthy — falls through to return False."""
    assert gmail_message_or_thread_exists(MagicMock()) is False
    assert gmail_message_or_thread_exists(MagicMock(), msg_id="", thread_id="") is False


# ── get_gmail_service_for_message ────────────────────────────────────────

def test_get_gmail_service_for_message_cache_hit():
    """Line 100: cache hit via msg_id → returns (account, svc)."""
    contact = _contact(gmail_account="cached@gmail.com")
    svc = MagicMock()
    state = _state(
        gmail_services={"cached@gmail.com": svc},
        conv_cache={("gmail", "msg-1"): contact},
    )
    acct, result_svc = get_gmail_service_for_message(
        state, msg_id="msg-1", cache_key=_cache_key
    )
    assert acct == "cached@gmail.com"
    assert result_svc is svc


def test_get_gmail_service_for_message_no_cache_no_match_falls_back(monkeypatch):
    """Line 106: cache misses + no account owns the thread → falls back to default."""
    svc_a = MagicMock()
    state = _state(
        gmail_services={"a@gmail.com": svc_a},
        conv_cache={},
    )
    monkeypatch.setattr(
        "google_account_resolution.gmail_message_or_thread_exists",
        lambda *a, **kw: False,
    )
    acct, result_svc = get_gmail_service_for_message(
        state, msg_id="msg-1", cache_key=_cache_key
    )
    assert acct == "a@gmail.com"
    assert result_svc is svc_a


# ── get_*_service_for_account error paths ────────────────────────────────

def test_get_sheets_service_for_account_none_available():
    """Line 115: no sheets account raises HTTPException(404)."""
    state = _state(sheets_services={})
    with pytest.raises(HTTPException, match="No Sheets account"):
        get_sheets_service_for_account(state)


def test_get_docs_service_for_account_not_found():
    """Line 145: empty docs_services raises HTTPException(400)."""
    state = _state(docs_services={})
    with pytest.raises(HTTPException, match="No docs service"):
        get_docs_service_for_account(state)


def test_get_drive_service_for_account_none_available():
    """Line 125: no drive account raises HTTPException."""
    state = _state(drive_services={})
    with pytest.raises(HTTPException, match="No Drive account"):
        get_drive_service_for_account(state)


def test_get_tasks_service_for_account_none_available():
    """Line 135: no tasks account raises HTTPException."""
    state = _state(tasks_services={})
    with pytest.raises(HTTPException, match="No Tasks account"):
        get_tasks_service_for_account(state)


def test_get_cal_service_for_account_none_available():
    """Line 156: no calendar account raises HTTPException."""
    state = _state(cal_services={})
    with pytest.raises(HTTPException, match="No calendar account"):
        get_cal_service_for_account(state)


# ── preflight_google_write_payload ───────────────────────────────────────

def test_preflight_drive_folder_get_raises_exception():
    """Lines 203-205: drive_get raises → warning + unverified destination."""
    state = _state(
        drive_services={"user@gmail.com": MagicMock()},
    )
    with (
        patch.dict(os.environ, {"INBOX_DEFAULT_GOOGLE_ACCOUNT": "user@gmail.com"}),
        patch("google_account_resolution.drive_get", side_effect=Exception("boom")),
    ):
        result = preflight_google_write_payload(
            state, kind="sheet", folder_id="folder-1", title="Report"
        )
    assert result["valid"] is True
    assert "(unverified)" in result["destination"]
    assert any("Could not verify" in w for w in result["warnings"])


def test_preflight_task_no_tasks_account():
    """Line 220: no tasks account → valid=False with 'No Tasks account' warning."""
    state = _state(tasks_services={})
    result = preflight_google_write_payload(state, kind="task", account="nobody@gmail.com")
    assert result["valid"] is False
    assert any("No Tasks account" in w for w in result["warnings"])


def test_preflight_task_list_lookup_raises_exception():
    """Lines 257-259: tasks_lists raises → warning + unverified destination."""
    state = _state(
        tasks_services={"user@gmail.com": MagicMock()},
    )
    with (
        patch.dict(os.environ, {"INBOX_DEFAULT_GOOGLE_ACCOUNT": "user@gmail.com"}),
        patch("google_account_resolution.tasks_lists", side_effect=Exception("boom")),
    ):
        result = preflight_google_write_payload(
            state, kind="task", list_id="some-list"
        )
    assert result["valid"] is True
    assert "(unverified)" in result["destination"]
    assert any("Could not verify" in w for w in result["warnings"])


def test_preflight_calendar_event_no_calendar_account():
    """Line 274: no cal_services → valid=False with 'No calendar account' warning."""
    state = _state(cal_services={})
    result = preflight_google_write_payload(
        state, kind="calendar_event", account="nobody@gmail.com"
    )
    assert result["valid"] is False
    assert any("No calendar account" in w for w in result["warnings"])
