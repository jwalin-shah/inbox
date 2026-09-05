import asyncio
import json
from unittest.mock import AsyncMock, patch

import lifeops_mcp


def _run(awaitable):
    return asyncio.run(awaitable)


def _row(method: str, path: str, body: dict) -> dict:
    return {
        "method": method,
        "path": path,
        "body_json": json.dumps(body),
        "state": "approved",
        "lease_id": "lease_test",
    }


def test_calendar_update_readback_verifies_exact_fields():
    row = _row(
        "PUT",
        "/calendar/events/event-1?calendar_id=primary&account=me@example.com",
        {
            "summary": "Street play practice",
            "location": "45738 Bridgeport Dr.",
            "description": "Pickup first",
            "start": "2026-08-27T17:40:00-07:00",
        },
    )
    observed = {
        "event_id": "event-1",
        "summary": "Street play practice",
        "location": "45738 Bridgeport Dr.",
        "description": "Pickup first",
        "start": "2026-08-28T00:40:00+00:00",
    }
    with patch.object(lifeops_mcp, "_request", new=AsyncMock(return_value=observed)) as request:
        result = _run(lifeops_mcp._verify_approved_action(row, {"ok": True}))

    assert result["status"] == "verified"
    assert result["mismatches"] == []
    request.assert_awaited_once_with(
        "GET",
        "/calendar/events/event-1",
        params={"calendar_id": "primary", "account": "me@example.com"},
    )


def test_person_note_readback_uses_returned_note_id():
    row = _row("POST", "/people/person-1/notes", {"body": "Parent of Arav"})
    profile = {
        "notes": [
            {"note_id": "note-new", "body": "Parent of Arav"},
            {"note_id": "note-old", "body": "Parent of Arav"},
        ]
    }
    with patch.object(lifeops_mcp, "_request", new=AsyncMock(return_value=profile)) as request:
        result = _run(
            lifeops_mcp._verify_approved_action(
                row,
                {"ok": True, "note": {"note_id": "note-new", "body": "Parent of Arav"}},
            )
        )

    assert result["status"] == "verified"
    request.assert_awaited_once_with(
        "GET", "/people/person-1/profile", params={"include_activity": False}
    )


def test_task_readback_refuses_to_claim_when_duplicate_exact_matches_exist():
    row = _row(
        "POST",
        "/tasks?account=me@example.com",
        {"title": "Message Washington Health", "list_id": "@default", "notes": "", "due": ""},
    )
    tasks = [
        {"id": "task-1", "title": "Message Washington Health", "notes": "", "due": None},
        {"id": "task-2", "title": "Message Washington Health", "notes": "", "due": None},
    ]
    with patch.object(lifeops_mcp, "_request", new=AsyncMock(return_value=tasks)) as request:
        result = _run(lifeops_mcp._verify_approved_action(row, {"ok": True}))

    assert result["status"] == "ambiguous"
    assert result["evidence"]["match_count"] == 2
    request.assert_awaited_once_with(
        "GET",
        "/tasks",
        params={
            "list_id": "@default",
            "show_completed": True,
            "limit": 200,
            "account": "me@example.com",
        },
    )


def test_pending_actions_exposes_exact_supported_proposal_without_approval():
    rows = [
        {
            "request_id": "apr_task",
            "state": "pending",
            "created_at": "2026-08-26T18:00:00",
            "method": "POST",
            "path": "/tasks?account=me@example.com",
            "body_json": json.dumps(
                {"title": "Call Yadel", "list_id": "@default", "notes": "", "due": ""}
            ),
            "provider": "google_tasks",
            "operation": "create",
            "approval_class": "external_write",
            "executor": "google_tasks",
            "account_ref": "me@example.com",
            "resource_ref": "tasks:@default",
            "item_count": 1,
            "payload_hash": "payload-hash",
            "query_hash": "query-hash",
        },
        {
            "request_id": "apr_other",
            "state": "approved",
            "method": "POST",
            "path": "/messages/compose",
            "body_json": "{}",
        },
        {
            "request_id": "apr_unsupported",
            "state": "pending",
            "method": "POST",
            "path": "/messages/compose",
            "body_json": "{}",
        },
    ]
    with patch.object(lifeops_mcp, "_request", new=AsyncMock(return_value=rows)) as request:
        result = _run(lifeops_mcp.pending_actions(limit=200))

    assert result["schema_version"] == "lifeops.pending_actions.v1"
    assert result["read_only"] is True
    assert result["count"] == 1
    assert result["omitted_unsupported"] == 1
    assert result["items"][0]["request_id"] == "apr_task"
    assert result["items"][0]["body"]["title"] == "Call Yadel"
    assert result["items"][0]["path"] == "/tasks?account=me@example.com"
    request.assert_awaited_once_with(
        "GET", "/approvals", params={"state": "pending", "limit": 100}
    )
