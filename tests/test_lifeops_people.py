import asyncio
import json
from unittest.mock import AsyncMock, patch

import lifeops_mcp


def _run(awaitable):
    return asyncio.run(awaitable)


def test_people_search_and_profile_use_first_class_routes():
    with patch.object(lifeops_mcp, "_request", new=AsyncMock(return_value=[{"person": {"person_id": "person_1"}}])) as request:
        result = _run(lifeops_mcp.people_search("Harsh"))
    assert result == [{"person": {"person_id": "person_1"}}]
    request.assert_awaited_once()
    assert request.await_args.args[:2] == ("GET", "/people/search")


def test_person_profile_does_not_request_provider_activity_by_default():
    with patch.object(lifeops_mcp, "_request", new=AsyncMock(return_value={"person": {}})) as request:
        _run(lifeops_mcp.person_profile("person_1"))
    assert request.await_args.kwargs["params"] == {"include_activity": False}


def test_proposed_person_note_is_payload_bound_approval():
    with patch.object(
        lifeops_mcp,
        "_request_approval",
        new=AsyncMock(return_value={"request_id": "req_1", "state": "pending"}),
    ) as approval:
        result = _run(lifeops_mcp.propose_person_note("person_1", "Met at practice."))
    assert result["state"] == "pending"
    body = approval.await_args.args[2]
    assert body["body"] == "Met at practice."
    assert approval.await_args.args[:2] == ("POST", "/people/person_1/notes")


def test_person_profile_actions_are_allowed_only_for_exact_local_routes():
    assert lifeops_mcp._allowed_execution({"method": "POST", "path": "/people/person_1/notes"})
    assert lifeops_mcp._allowed_execution({"method": "POST", "path": "/people/person_1/relationships"})
    assert not lifeops_mcp._allowed_execution({"method": "DELETE", "path": "/people/person_1/notes"})


def test_identity_link_proposal_is_payload_bound_and_readback_verified():
    with patch.object(
        lifeops_mcp,
        "_request_approval",
        new=AsyncMock(return_value={"request_id": "req_identity", "state": "pending"}),
    ) as approval:
        result = _run(
            lifeops_mcp.propose_person_identity_link(
                "person-sheet-1",
                "Harsh",
                "contact-1",
                target_name="Harsh Shah",
                source_refs=[{"source": "google_sheets", "id": "people-row-1"}],
            )
        )
    assert result["state"] == "pending"
    assert approval.await_args.args[:2] == ("POST", "/identity/links")
    assert lifeops_mcp._allowed_execution({"method": "POST", "path": "/identity/links"})

    row = {
        "method": "POST",
        "path": "/identity/links",
        "body_json": json.dumps(
            {
                "canonical_person_id": "person-sheet-1",
                "target_source": "contacts",
                "target_id": "contact-1",
            }
        ),
    }
    with patch.object(
        lifeops_mcp,
        "_request",
        new=AsyncMock(
            return_value={
                "links": [
                    {
                        "link_id": "identity_link_1",
                        "canonical_person_id": "person-sheet-1",
                        "target_source": "contacts",
                        "target_id": "contact-1",
                    }
                ]
            }
        ),
    ) as request:
        verified = _run(
            lifeops_mcp._verify_approved_action(
                row,
                {"ok": True, "link": {"link_id": "identity_link_1"}},
            )
        )
    assert verified["status"] == "verified"
    request.assert_awaited_once_with(
        "GET",
        "/identity/links",
        params={
            "canonical_person_id": "person-sheet-1",
            "target_source": "contacts",
            "target_id": "contact-1",
            "limit": 100,
        },
    )


def test_gmail_normalization_and_todo_candidates_use_read_only_routes():
    with patch.object(
        lifeops_mcp,
        "_request",
        new=AsyncMock(side_effect=[{"account_count": 3}, {"items": []}]),
    ) as request:
        assert _run(lifeops_mcp.gmail_normalization()) == {"account_count": 3}
        assert _run(lifeops_mcp.todo_candidates(source="gmail", account="me@example.com", limit=7)) == {"items": []}
    assert request.await_args_list[0].args[:2] == ("GET", "/gmail/normalization")
    assert request.await_args_list[1].kwargs["params"] == {
        "source": "gmail",
        "account": "me@example.com",
        "category": "",
        "limit": 7,
    }


def test_task_from_candidate_uses_exact_message_payload_and_approval():
    candidate = {
        "candidate_id": "todo_1",
        "source": "gmail",
        "account": "me@example.com",
        "thread_id": "thread_1",
        "suggested_task_title": "Confirm pickup",
        "notes": "Harsh is waiting for a reply.",
        "evidence": {"external_id": "message_1"},
    }
    with (
        patch.object(lifeops_mcp, "_request", new=AsyncMock(return_value={"items": [candidate]})),
        patch.object(
            lifeops_mcp,
            "_request_approval",
            new=AsyncMock(return_value={"request_id": "req_1", "state": "pending"}),
        ) as approval,
    ):
        result = _run(lifeops_mcp.propose_task_from_candidate("todo_1"))
    assert result["state"] == "pending"
    assert approval.await_args.args[:2] == ("POST", "/tasks/from-message")
    assert approval.await_args.args[2] == {
        "message_id": "message_1",
        "message_source": "gmail",
        "title": "Confirm pickup",
        "task_type": "google_tasks",
        "list_id": "@default",
        "notes": "Harsh is waiting for a reply.",
        "thread_id": "thread_1",
        "account": "me@example.com",
    }
    assert lifeops_mcp._allowed_execution({"method": "POST", "path": "/tasks/from-message"})


def test_task_reconciliation_uses_read_only_route():
    with patch.object(
        lifeops_mcp,
        "_request",
        new=AsyncMock(return_value={"task_count": 47, "candidate_counts": {"missing": 2}}),
    ) as request:
        result = _run(lifeops_mcp.task_reconciliation(account="jshah1331@gmail.com", limit=12))
    assert result["task_count"] == 47
    assert request.await_args.args[:2] == ("GET", "/tasks/reconciliation")
    assert request.await_args.kwargs["params"] == {
        "source": "",
        "account": "jshah1331@gmail.com",
        "limit": 12,
    }
