"""Focused tests for the REST route approval gate."""

from __future__ import annotations

import asyncio
import os
import re
import sqlite3
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient


@pytest.fixture
def approval_client():
    import inbox_server

    inbox_server._approval_leases.clear()
    fake_state = inbox_server.ServerState()
    runtime = inbox_server.InboxServerRuntime(
        server_state=fake_state,
        init_contacts_func=lambda: 0,
        google_auth_func=inbox_server._empty_google_services,
        start_scheduler=False,
        ambient_autostart=False,
    )

    with (
        patch.dict(
            os.environ,
            {
                "INBOX_SERVER_TOKEN": "",
                "INBOX_TEST_MODE": "1",
                "INBOX_SERVER_ALLOW_UNAUTHENTICATED": "1",
            },
            clear=False,
        ),
        TestClient(inbox_server.create_app(runtime), raise_server_exceptions=False) as client,
    ):
        yield client
    inbox_server._approval_leases.clear()


MUTATING_ROUTE_MATRIX = (
    pytest.param(
        "Gmail",
        "POST",
        "/messages/compose",
        {"account": "me@example.com", "to": "a@example.com", "subject": "No-op", "body": "hello"},
        "inbox_server.gmail_compose_send",
        "inbox.gmail.send_email",
        id="gmail-compose",
    ),
    pytest.param(
        "Calendar",
        "POST",
        "/calendar/events",
        {
            "summary": "No-op",
            "start": "2026-05-30T12:00:00",
            "end": "2026-05-30T12:30:00",
            "account": "me@example.com",
        },
        "inbox_server.calendar_create_event",
        "inbox.calendar.create_event",
        id="calendar-create",
    ),
    pytest.param(
        "Drive",
        "POST",
        "/drive/folder",
        {"name": "No-op", "account": "me@example.com", "parent_id": "parent-1"},
        "inbox_server.drive_create_folder",
        "inbox.drive.write",
        id="drive-folder",
    ),
    pytest.param(
        "Docs",
        "POST",
        "/docs/doc-1/text",
        {"text": "hello", "index": 1, "account": "me@example.com"},
        "inbox_server.docs_insert_text",
        "inbox.docs.write",
        id="docs-insert-text",
    ),
    pytest.param(
        "Sheets",
        "PUT",
        "/sheets/sheet-1/values/A1",
        {"values": [["hello"]], "account": "me@example.com"},
        "inbox_server.sheets_values_update",
        "inbox.sheets.update_cells",
        id="sheets-update-values",
    ),
    pytest.param(
        "Reminders",
        "POST",
        "/reminders",
        {"title": "No-op"},
        "inbox_server.reminder_create",
        "inbox.reminders.write",
        id="reminders-create",
    ),
    pytest.param(
        "Tasks",
        "POST",
        "/tasks?account=me@example.com",
        {"title": "No-op", "notes": "hello"},
        "inbox_server.task_create",
        "inbox.tasks.write",
        id="tasks-create",
    ),
    pytest.param(
        "WhatsApp",
        "POST",
        "/whatsapp/send",
        {"chat_name": "Alice", "text": "hello"},
        "inbox_server.whatsapp_send",
        "inbox.whatsapp.write",
        id="whatsapp-send",
    ),
    pytest.param(
        "Scheduler",
        "POST",
        "/scheduled",
        {
            "source": "gmail",
            "conv_id": "msg-1",
            "text": "hello",
            "send_at": "2026-05-30T12:00:00",
            "account": "me@example.com",
        },
        "inbox_server.state.scheduler.schedule_message",
        "inbox.scheduler.write",
        id="scheduler-create",
    ),
    pytest.param(
        "ConnectorSync",
        "POST",
        "/connectors/whatsapp/sync",
        {"execute": True},
        "inbox_server.connector_sync_plan",
        "inbox.connectors.sync",
        id="connector-sync-execute",
    ),
)

STABLE_RESOURCE_ROUTE_MATRIX = tuple(
    param
    for param in MUTATING_ROUTE_MATRIX
    if param.values[0] not in {"Drive", "Reminders"}
)

QUERY_MUTATING_ROUTE_MATRIX = (
    pytest.param(
        "Sheets",
        "PATCH",
        "/sheets/sheet-1/tabs/123?title=Approved&account=me@example.com",
        "/sheets/sheet-1/tabs/123?title=Mutated&account=me@example.com",
        None,
        "inbox_server.sheets_rename_sheet",
        "inbox.sheets.write",
        id="sheets-tab-rename-title",
    ),
    pytest.param(
        "Calendar",
        "PUT",
        "/calendar/events/event-1?calendar_id=primary&account=me@example.com",
        "/calendar/events/event-1?calendar_id=secondary&account=me@example.com",
        {"summary": "No-op"},
        "inbox_server.calendar_update_event",
        "inbox.calendar.update_event",
        id="calendar-update-calendar-id",
    ),
)


@dataclass(frozen=True)
class ApprovalExceptionPolicy:
    side_effect_class: str
    provider_safe: bool
    reason: str


APPROVAL_EXCEPTION_CLASSES = frozenset(
    {
        "pure_read",
        "external_read_sync",
        "llm_call",
        "local_audio_capture",
        "local_write",
        "local_notification",
        "oauth_consent",
    }
)


MUTATING_METHOD_EXCEPTION_POLICY = {
    ("POST", "/ai/action-items"): ApprovalExceptionPolicy("llm_call", True, "LLM-only extraction; no provider write"),
    ("POST", "/ai/briefing"): ApprovalExceptionPolicy("llm_call", True, "LLM-only briefing; no provider write"),
    ("POST", "/ai/categorize"): ApprovalExceptionPolicy("llm_call", True, "LLM-only categorization; no provider write"),
    ("POST", "/ai/digest"): ApprovalExceptionPolicy("llm_call", True, "LLM-only digest; no provider write"),
    ("POST", "/ai/extract-actions"): ApprovalExceptionPolicy("llm_call", True, "LLM-only action extraction; no provider write"),
    ("POST", "/ai/gemini-summarize"): ApprovalExceptionPolicy("llm_call", True, "LLM-only summarization; no provider write"),
    ("POST", "/ai/smart-reply"): ApprovalExceptionPolicy("llm_call", True, "LLM-only reply drafting; no provider write"),
    ("POST", "/ai/summarize"): ApprovalExceptionPolicy("llm_call", True, "LLM-only summarization; no provider write"),
    ("POST", "/ai/triage"): ApprovalExceptionPolicy("llm_call", True, "LLM-only triage; no provider write"),
    ("POST", "/ambient/start"): ApprovalExceptionPolicy("local_audio_capture", True, "local microphone listener; no provider write"),
    ("POST", "/ambient/stop"): ApprovalExceptionPolicy("local_audio_capture", True, "local microphone listener; no provider write"),
    ("POST", "/autocomplete"): ApprovalExceptionPolicy("pure_read", True, "local suggestion lookup"),
    ("POST", "/calendar/conflicts"): ApprovalExceptionPolicy("pure_read", True, "calendar conflict calculation"),
    ("POST", "/calendar/free-slots"): ApprovalExceptionPolicy("pure_read", True, "calendar availability calculation"),
    ("POST", "/calendar/freebusy"): ApprovalExceptionPolicy("external_read_sync", True, "calendar free/busy provider read; no provider write"),
    ("POST", "/connectors/search"): ApprovalExceptionPolicy("pure_read", True, "connector metadata search"),
    ("POST", "/accounts/add"): ApprovalExceptionPolicy(
        "oauth_consent", True, "Google's own OAuth consent screen is the real approval step; a lease can't be minted before the browser flow completes"
    ),
    ("POST", "/accounts/reauth"): ApprovalExceptionPolicy(
        "oauth_consent", True, "Google's own OAuth consent screen is the real approval step; a lease can't be minted before the browser flow completes"
    ),
    ("POST", "/gateway/dry-run/ahmed-office-location-calendar-update"): ApprovalExceptionPolicy(
        "pure_read", True, "iMessage/calendar read dry-run that returns a proposal without provider write"
    ),
    ("POST", "/gateway/read-proof"): ApprovalExceptionPolicy(
        "external_read_sync",
        True,
        "Gmail/Calendar/Tasks read-only proof via provider list/read helpers; no provider write",
    ),
    ("POST", "/gateway/gmail-readiness"): ApprovalExceptionPolicy(
        "external_read_sync",
        True,
        "Multi-Gmail profile/inbox-count metadata read dry-run; no provider write",
    ),
    ("POST", "/dictation/start"): ApprovalExceptionPolicy("local_audio_capture", True, "local dictation listener; no provider write"),
    ("POST", "/dictation/stop"): ApprovalExceptionPolicy("local_audio_capture", True, "local dictation listener; no provider write"),
    ("DELETE", "/contacts/favorites/{contact_id}"): ApprovalExceptionPolicy(
        "local_write", True, "local favorites file update; no provider write"
    ),
    ("POST", "/contacts/favorites/{contact_id}"): ApprovalExceptionPolicy(
        "local_write", True, "local favorites file update; no provider write"
    ),
    ("POST", "/index/sync/bootstrap"): ApprovalExceptionPolicy(
        "external_read_sync", True, "provider reads into local index; no provider write"
    ),
    ("POST", "/index/sync/incremental"): ApprovalExceptionPolicy(
        "external_read_sync", True, "provider reads into local index; no provider write"
    ),
    ("POST", "/llm/warmup"): ApprovalExceptionPolicy("llm_call", True, "LLM warmup call; no provider write"),
    ("POST", "/memory/extract"): ApprovalExceptionPolicy("local_write", True, "optional local memory file save; no provider write"),
    ("PUT", "/notifications/config"): ApprovalExceptionPolicy(
        "local_write", True, "local notification config file update; no provider write"
    ),
    ("POST", "/notifications/test"): ApprovalExceptionPolicy(
        "local_notification", True, "desktop notification test only; no provider write"
    ),
    ("POST", "/query"): ApprovalExceptionPolicy("pure_read", True, "local query with request body"),
    ("POST", "/search"): ApprovalExceptionPolicy("pure_read", True, "local search with request body"),
    ("POST", "/sheets/{spreadsheet_id}/values/batch-get"): ApprovalExceptionPolicy("pure_read", True, "sheets batch read"),
    ("PUT", "/voice/config"): ApprovalExceptionPolicy("local_write", True, "local voice config file update; no provider write"),
    ("POST", "/approvals/request"): ApprovalExceptionPolicy(
        "local_write",
        True,
        "records a pending approval request in local sqlite; does not mint a "
        "lease or reach any provider, no provider write",
    ),
    ("POST", "/approvals/{request_id}/decide"): ApprovalExceptionPolicy(
        "local_write",
        True,
        "captain decision on a pending approval request; mints a lease into "
        "local state on approval but performs no provider write itself, no "
        "provider write",
    ),
}


RISKY_EXCEPTION_REASON_REQUIREMENTS = {
    "external_read_sync": ("no provider write",),
    "llm_call": ("no provider write",),
    "local_audio_capture": ("no provider write",),
    "local_write": ("local", "no provider write"),
    "local_notification": ("notification", "no provider write"),
}


def _example_path(route_path: str) -> str:
    return re.sub(r"\{[^}/]+\}", "example-id", route_path)


def test_all_mutating_routes_are_approval_gated_or_explicitly_excepted():
    import inbox_server

    uncovered = []
    for route in inbox_server.app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in sorted(route.methods & inbox_server.APPROVAL_GUARDED_METHODS):
            route_key = (method, route.path)
            if route_key in MUTATING_METHOD_EXCEPTION_POLICY:
                continue
            example_path = _example_path(route.path)
            if inbox_server._approval_rule_for_request(method, example_path) is None:
                uncovered.append(f"{method} {route.path}")

    assert uncovered == []


def test_capability_inventory_routes_align_with_approval_policy():
    import inbox_server
    from capability_inventory import build_capability_inventory

    mismatches = []
    inventory = build_capability_inventory()
    for capability in inventory["capabilities"]:
        route = capability.get("route")
        if not isinstance(route, dict):
            continue
        method = str(route.get("method") or "").upper()
        path = str(route.get("path") or "")
        if method not in inbox_server.APPROVAL_GUARDED_METHODS:
            continue
        example_path = _example_path(path)
        rule = inbox_server._approval_rule_for_request(method, example_path)
        route_key = (method, path)
        category = capability.get("category")
        approval_required = bool((capability.get("approval") or {}).get("required"))
        if category in {"external_write", "delete", "publish", "pay", "submit"}:
            if rule is None:
                mismatches.append(f"{capability['id']} mutating capability lacks approval route")
            if not approval_required:
                mismatches.append(f"{capability['id']} mutating capability lacks required approval metadata")
        elif rule is None and route_key not in MUTATING_METHOD_EXCEPTION_POLICY:
            mismatches.append(f"{capability['id']} guarded-method read/draft route lacks exception policy")

    assert mismatches == []


def test_approval_route_rules_still_match_registered_routes():
    import inbox_server

    registered_routes = {
        (method, route.path)
        for route in inbox_server.app.routes
        if isinstance(route, APIRoute)
        for method in route.methods & inbox_server.APPROVAL_GUARDED_METHODS
    }

    unmatched_rules = []
    for rule in inbox_server.APPROVAL_ROUTE_RULES:
        if not any(
            method == rule.method
            and rule.pattern.match(_example_path(route_path))
            and (method, route_path) not in MUTATING_METHOD_EXCEPTION_POLICY
            for method, route_path in registered_routes
        ):
            unmatched_rules.append(f"{rule.method} {rule.pattern.pattern}")

    assert unmatched_rules == []


def test_mutating_route_exceptions_are_explicitly_classed_and_documented():
    undocumented = []
    invalid = []
    for route_key, policy in MUTATING_METHOD_EXCEPTION_POLICY.items():
        if policy.side_effect_class not in APPROVAL_EXCEPTION_CLASSES:
            invalid.append(f"{route_key[0]} {route_key[1]}: {policy.side_effect_class}")
        if not policy.provider_safe:
            invalid.append(f"{route_key[0]} {route_key[1]}: provider_safe=false")
        if not policy.reason.strip():
            undocumented.append(f"{route_key[0]} {route_key[1]}")

    assert invalid == []
    assert undocumented == []


def test_mutating_route_exception_policy_has_no_stale_routes():
    import inbox_server

    registered_routes = {
        (method, route.path)
        for route in inbox_server.app.routes
        if isinstance(route, APIRoute)
        for method in route.methods & inbox_server.APPROVAL_GUARDED_METHODS
    }

    stale = [
        f"{method} {route_path}"
        for method, route_path in sorted(MUTATING_METHOD_EXCEPTION_POLICY)
        if (method, route_path) not in registered_routes
    ]

    assert stale == []


def test_risky_exception_reasons_make_provider_boundary_explicit():
    ambiguous = []
    for route_key, policy in MUTATING_METHOD_EXCEPTION_POLICY.items():
        required_markers = RISKY_EXCEPTION_REASON_REQUIREMENTS.get(policy.side_effect_class, ())
        reason = policy.reason.lower()
        missing = [marker for marker in required_markers if marker not in reason]
        if missing:
            ambiguous.append(f"{route_key[0]} {route_key[1]} missing {', '.join(missing)}")

    assert ambiguous == []


def test_connector_sync_exception_stays_default_dry_run():
    import inbox_server

    request = inbox_server.ConnectorSyncRequest()

    assert request.execute is False


@pytest.mark.parametrize("execute_value", [1, 0, "true", "false", "yes", "no", "1", "0"])
def test_connector_sync_request_rejects_coercible_execute_values(execute_value):
    from pydantic import ValidationError

    import inbox_server

    with pytest.raises(ValidationError):
        inbox_server.ConnectorSyncRequest(execute=execute_value)


def test_connector_sync_execute_route_is_approval_gated_but_dry_run_is_exempt():
    import inbox_server

    rule = inbox_server._approval_rule_for_request("POST", "/connectors/whatsapp/sync")

    assert rule is not None
    assert rule.executor == "inbox.connectors.sync"
    assert inbox_server._connector_sync_is_dry_run("/connectors/whatsapp/sync", {}) is True
    assert inbox_server._connector_sync_is_dry_run("/connectors/whatsapp/sync", {"execute": False}) is True
    assert inbox_server._connector_sync_is_dry_run("/connectors/whatsapp/sync", {"execute": True}) is False


def test_local_approval_helper_does_not_return_static_lease_outside_test_mode():
    import inbox_server

    with patch.dict(
        os.environ,
        {
            "INBOX_TEST_MODE": "0",
            "INBOX_APPROVAL_LEASE": "lease_from_adapter",
        },
        clear=False,
    ):
        lease = inbox_server._local_approval_lease()

    assert lease == "lease_from_adapter"
    assert lease != inbox_server.APPROVAL_TEST_LEASE


def test_minted_sheets_update_lease_has_stable_account_resource_and_item_count():
    import inbox_server

    inbox_server._approval_leases.clear()
    body = {"values": [["a"], ["b"]], "account": "me@example.com"}
    lease_id = inbox_server.mint_local_approval_lease("PUT", "/sheets/sheet-1/values/A1", body=body)

    lease = inbox_server._approval_leases[lease_id]

    assert lease.account_ref == "me@example.com"
    assert lease.resource_ref == "path:A1"
    assert lease.item_count == 2
    assert not lease.resource_ref.startswith("payload:")


def test_provider_safe_exception_reasons_do_not_smuggle_provider_write_semantics():
    provider_write_markers = (
        "send",
        "delete",
        "archive",
        "unsubscribe",
        "rsvp",
        "create event",
        "create task",
        "execute=true",
    )
    ambiguous = []
    for route_key, policy in MUTATING_METHOD_EXCEPTION_POLICY.items():
        reason = policy.reason.lower()
        if policy.side_effect_class in {"local_write", "local_notification"}:
            continue
        if any(marker in reason for marker in provider_write_markers):
            ambiguous.append(f"{route_key[0]} {route_key[1]}: {policy.reason}")

    assert ambiguous == []


def test_critical_approval_executors_have_adversarial_missing_lease_probes():
    import inbox_server

    probed_rules = {
        (
            method,
            inbox_server._approval_rule_for_request(method, urlsplit(path).path).provider,
            inbox_server._approval_rule_for_request(method, urlsplit(path).path).operation,
            inbox_server._approval_rule_for_request(method, urlsplit(path).path).executor,
        )
        for _, method, path, _, _, _ in (param.values for param in MUTATING_ROUTE_MATRIX)
        if inbox_server._approval_rule_for_request(method, urlsplit(path).path) is not None
    }
    probed_executors = {executor for _, _, _, executor in probed_rules}
    critical_executors = {
        "inbox.gmail.send_email",
        "inbox.calendar.create_event",
        "inbox.drive.write",
        "inbox.docs.write",
        "inbox.sheets.update_cells",
        "inbox.reminders.write",
        "inbox.tasks.write",
        "inbox.whatsapp.write",
        "inbox.scheduler.write",
        "inbox.connectors.sync",
    }

    assert critical_executors - probed_executors == set()


@pytest.mark.parametrize(
    ("surface", "method", "path", "json_body", "helper_target", "executor"),
    MUTATING_ROUTE_MATRIX,
)
def test_missing_lease_route_matrix_fails_closed_before_provider_helper(
    approval_client, surface, method, path, json_body, helper_target, executor
):
    with patch(helper_target) as helper:
        resp = approval_client.request(method, path, json=json_body)

    assert resp.status_code == 403, surface
    data = resp.json()
    assert data["approval_class"] == "external_write"
    assert data["can_execute"] is False
    assert data["reason"] == "missing_per_action_approval_lease"
    assert data["executor"] == executor
    helper.assert_not_called()


def _configure_route_matrix_state(inbox_server, helper_target: str) -> None:
    inbox_server.state.gmail_services = {"me@example.com": MagicMock()}
    inbox_server.state.cal_services = {"me@example.com": MagicMock()}
    inbox_server.state.drive_services = {"me@example.com": MagicMock()}
    inbox_server.state.docs_services = {"me@example.com": MagicMock()}
    inbox_server.state.sheets_services = {"me@example.com": MagicMock()}
    inbox_server.state.tasks_services = {"me@example.com": MagicMock()}
    if helper_target == "inbox_server.state.scheduler.schedule_message":
        inbox_server.state.scheduler.schedule_message = MagicMock(return_value={"id": 1, "status": "scheduled"})


def _route_matrix_helper_return(inbox_server, helper_target: str):
    if helper_target == "inbox_server.drive_create_folder":
        return inbox_server.DriveFile(
            id="folder-1",
            name="No-op",
            mime_type="application/vnd.google-apps.folder",
            modified=datetime.now(UTC),
            parents=["parent-1"],
        )
    if helper_target == "inbox_server.sheets_values_update":
        return {"updatedCells": 1}
    if helper_target == "inbox_server.connector_sync_plan":
        return {"ok": True, "connector": "whatsapp", "dry_run": False}
    return True


def _mutated_route_matrix_body(json_body: dict) -> dict:
    changed = deepcopy(json_body)
    if "body" in changed:
        changed["body"] = f"{changed['body']} mutated"
    elif "summary" in changed:
        changed["summary"] = f"{changed['summary']} mutated"
    elif "name" in changed:
        changed["name"] = f"{changed['name']} mutated"
    elif "text" in changed:
        changed["text"] = f"{changed['text']} mutated"
    elif "values" in changed:
        changed["values"] = [["mutated"]]
    elif "notes" in changed:
        changed["notes"] = f"{changed['notes']} mutated"
    elif "title" in changed:
        changed["title"] = f"{changed['title']} mutated"
    elif "execute" in changed:
        changed["sync_scope"] = "mutated"
    else:
        raise AssertionError(f"no mutation rule for body keys: {sorted(json_body)}")
    return changed


@pytest.mark.parametrize(
    ("surface", "method", "path", "json_body", "helper_target", "executor"),
    STABLE_RESOURCE_ROUTE_MATRIX,
)
def test_replay_denied_for_each_stable_resource_route_before_provider_helper(
    approval_client, surface, method, path, json_body, helper_target, executor
):
    import inbox_server

    _configure_route_matrix_state(inbox_server, helper_target)
    lease = inbox_server.mint_local_approval_lease(method, path, body=json_body)

    with patch(helper_target, return_value=_route_matrix_helper_return(inbox_server, helper_target)) as helper:
        first = approval_client.request(
            method,
            path,
            headers={"X-Inbox-Approval-Lease": lease},
            json=json_body,
        )
        replay = approval_client.request(
            method,
            path,
            headers={"X-Inbox-Approval-Lease": lease},
            json=json_body,
        )

    assert first.status_code == 200, (surface, first.text)
    assert replay.status_code == 403, surface
    assert replay.json()["reason"] == "lease_replayed"
    assert replay.json()["executor"] == executor
    helper.assert_called_once()


@pytest.mark.parametrize(
    ("surface", "method", "path", "json_body", "helper_target", "executor"),
    STABLE_RESOURCE_ROUTE_MATRIX,
)
def test_body_mutation_denied_for_each_stable_resource_route_before_provider_helper(
    approval_client, surface, method, path, json_body, helper_target, executor
):
    import inbox_server

    _configure_route_matrix_state(inbox_server, helper_target)
    lease = inbox_server.mint_local_approval_lease(method, path, body=json_body)
    changed = _mutated_route_matrix_body(json_body)

    with patch(helper_target, return_value=_route_matrix_helper_return(inbox_server, helper_target)) as helper:
        resp = approval_client.request(
            method,
            path,
            headers={"X-Inbox-Approval-Lease": lease},
            json=changed,
        )

    assert resp.status_code == 403, surface
    assert resp.json()["reason"] == "payload_hash_mismatch"
    assert resp.json()["executor"] == executor
    helper.assert_not_called()


def test_missing_lease_denies_gmail_send_before_provider_call(approval_client):
    import inbox_server
    from services import Contact

    inbox_server.state.conv_cache = {
        "gmail:msg-1": Contact(
            id="msg-1",
            name="Alice",
            source="gmail",
            gmail_account="me@example.com",
        )
    }
    inbox_server.state.gmail_services = {"me@example.com": MagicMock()}

    with patch("inbox_server.gmail_send") as mock_send:
        resp = approval_client.post(
            "/messages/send",
            json={"conv_id": "msg-1", "source": "gmail", "text": "hello"},
        )

    assert resp.status_code == 403
    data = resp.json()
    assert data["approval_class"] == "external_write"
    assert data["can_execute"] is False
    assert data["reason"] == "missing_per_action_approval_lease"
    mock_send.assert_not_called()


def test_missing_lease_denies_imessage_send_before_provider_call(approval_client):
    with patch("inbox_server.imsg_send") as mock_send:
        resp = approval_client.post(
            "/imessage/send",
            params={"contact_id": "+1234567890", "text": "hello"},
        )

    assert resp.status_code == 403
    data = resp.json()
    assert data["approval_class"] == "external_write"
    assert data["can_execute"] is False
    assert data["reason"] == "missing_per_action_approval_lease"
    assert data["executor"] == "inbox.messages.send"
    mock_send.assert_not_called()


def test_invalid_lease_denies_calendar_create_before_provider_call(approval_client):
    import inbox_server

    inbox_server.state.cal_services = {"me@example.com": MagicMock()}

    with patch("inbox_server.calendar_create_event") as mock_create:
        resp = approval_client.post(
            "/calendar/events",
            headers={"X-Inbox-Approval-Lease": "wrong"},
            json={
                "summary": "No-op",
                "start": "2026-05-30T12:00:00",
                "end": "2026-05-30T12:30:00",
                "account": "me@example.com",
            },
        )

    assert resp.status_code == 403
    assert resp.json()["executor"] == "inbox.calendar.create_event"
    assert resp.json()["reason"] == "unknown_per_action_approval_lease"
    mock_create.assert_not_called()


def test_valid_per_action_lease_allows_mocked_task_route_once_then_denies_replay(approval_client):
    import inbox_server

    inbox_server.state.tasks_services = {"me@example.com": MagicMock()}
    body = {"title": "Local mocked task"}
    lease = inbox_server.mint_local_approval_lease("POST", "/tasks?account=me@example.com", body=body)

    with patch("inbox_server.task_create", return_value=True) as mock_create:
        resp = approval_client.post(
            "/tasks?account=me@example.com",
            headers={"X-Inbox-Approval-Lease": lease},
            json=body,
        )
        replay = approval_client.post(
            "/tasks?account=me@example.com",
            headers={"X-Inbox-Approval-Lease": lease},
            json=body,
        )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert replay.status_code == 403
    assert replay.json()["reason"] == "lease_replayed"
    mock_create.assert_called_once()


def test_body_change_fails_payload_hash_before_provider_helper(approval_client):
    import inbox_server

    inbox_server.state.gmail_services = {"me@example.com": MagicMock()}
    original = {"account": "me@example.com", "to": "a@example.com", "subject": "No-op", "body": "Original"}
    changed = {"account": "me@example.com", "to": "a@example.com", "subject": "No-op", "body": "Changed"}
    lease = inbox_server.mint_local_approval_lease("POST", "/messages/compose", body=original)

    with patch("inbox_server.gmail_compose_send") as mock_create:
        resp = approval_client.post(
            "/messages/compose",
            headers={"X-Inbox-Approval-Lease": lease},
            json=changed,
        )

    assert resp.status_code == 403
    assert resp.json()["reason"] == "payload_hash_mismatch"
    mock_create.assert_not_called()


def test_canonical_json_key_reordering_allows_same_gmail_compose_body_once(approval_client):
    import inbox_server

    inbox_server.state.gmail_services = {"me@example.com": MagicMock()}
    body_bytes = (
        b'{"subject":"No-op","to":"a@example.com","account":"me@example.com","body":"same"}'
    )
    reordered = {"account": "me@example.com", "body": "same", "subject": "No-op", "to": "a@example.com"}
    lease = inbox_server.mint_local_approval_lease("POST", "/messages/compose", body=body_bytes)

    with patch("inbox_server.gmail_compose_send", return_value=True) as mock_send:
        resp = approval_client.post(
            "/messages/compose",
            headers={"X-Inbox-Approval-Lease": lease},
            json=reordered,
        )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    mock_send.assert_called_once()


def test_sheets_same_count_body_mutation_fails_payload_hash_before_provider_helper(approval_client):
    import inbox_server

    inbox_server.state.sheets_services = {"me@example.com": MagicMock()}
    original = {"values": [["a"]], "account": "me@example.com"}
    changed = {"values": [["b"]], "account": "me@example.com"}
    lease = inbox_server.mint_local_approval_lease("PUT", "/sheets/sheet-1/values/A1", body=original)

    with patch("inbox_server.sheets_values_update") as mock_update:
        resp = approval_client.put(
            "/sheets/sheet-1/values/A1",
            headers={"X-Inbox-Approval-Lease": lease},
            json=changed,
        )

    assert resp.status_code == 403
    assert resp.json()["reason"] == "payload_hash_mismatch"
    mock_update.assert_not_called()


def test_docs_index_body_mutation_fails_payload_hash_before_provider_helper(approval_client):
    import inbox_server

    inbox_server.state.docs_services = {"me@example.com": MagicMock()}
    original = {"text": "hello", "index": 1, "account": "me@example.com"}
    changed = {"text": "hello", "index": 2, "account": "me@example.com"}
    lease = inbox_server.mint_local_approval_lease("POST", "/docs/doc-1/text", body=original)

    with patch("inbox_server.docs_insert_text") as mock_insert:
        resp = approval_client.post(
            "/docs/doc-1/text",
            headers={"X-Inbox-Approval-Lease": lease},
            json=changed,
        )

    assert resp.status_code == 403
    assert resp.json()["reason"] == "payload_hash_mismatch"
    mock_insert.assert_not_called()


@pytest.mark.parametrize(
    ("surface", "method", "approved_path", "mutated_path", "json_body", "helper_target", "executor"),
    QUERY_MUTATING_ROUTE_MATRIX,
)
def test_query_mutation_route_matrix_fails_before_provider_helper(
    approval_client, surface, method, approved_path, mutated_path, json_body, helper_target, executor
):
    import inbox_server

    _configure_route_matrix_state(inbox_server, helper_target)
    lease = inbox_server.mint_local_approval_lease(method, approved_path, body=json_body)

    with patch(helper_target) as helper:
        resp = approval_client.request(
            method,
            mutated_path,
            headers={"X-Inbox-Approval-Lease": lease},
            json=json_body,
        )

    assert resp.status_code == 403, surface
    assert resp.json()["reason"] == "query_hash_mismatch"
    assert resp.json()["executor"] == executor
    helper.assert_not_called()


def test_expired_per_action_lease_fails_before_provider_helper(approval_client):
    import inbox_server

    inbox_server.state.tasks_services = {"me@example.com": MagicMock()}
    lease = inbox_server.mint_local_approval_lease(
        "POST",
        "/tasks?account=me@example.com",
        body={"title": "Expired"},
        now=datetime.now(UTC) - timedelta(minutes=10),
        ttl_seconds=1,
    )

    with patch("inbox_server.task_create") as mock_create:
        resp = approval_client.post(
            "/tasks?account=me@example.com",
            headers={"X-Inbox-Approval-Lease": lease},
            json={"title": "Expired"},
        )

    assert resp.status_code == 403
    assert resp.json()["reason"] == "lease_expired"
    mock_create.assert_not_called()


def test_static_approval_test_lease_is_not_a_production_bypass():
    import inbox_server

    inbox_server._approval_leases.clear()
    fake_state = inbox_server.ServerState()
    runtime = inbox_server.InboxServerRuntime(
        server_state=fake_state,
        init_contacts_func=lambda: 0,
        google_auth_func=inbox_server._empty_google_services,
        start_scheduler=False,
        ambient_autostart=False,
    )

    with (
        patch.dict(
            os.environ,
            {
                "INBOX_SERVER_TOKEN": "",
                "INBOX_TEST_MODE": "0",
                "INBOX_SERVER_ALLOW_UNAUTHENTICATED": "1",
            },
            clear=False,
        ),
        TestClient(inbox_server.create_app(runtime), raise_server_exceptions=False) as client,
        patch("inbox_server.task_create") as mock_create,
    ):
        resp = client.post(
            "/tasks?account=me@example.com",
            headers={"X-Inbox-Approval-Lease": inbox_server.APPROVAL_TEST_LEASE},
            json={"title": "Should not bypass"},
        )

    assert resp.status_code == 403
    assert resp.json()["reason"] == "unknown_per_action_approval_lease"
    mock_create.assert_not_called()


def test_static_approval_test_lease_denied_even_in_test_mode_after_migration(approval_client):
    import inbox_server

    inbox_server.state.gmail_services = {"me@example.com": MagicMock()}

    with patch("inbox_server.gmail_compose_send") as mock_send:
        resp = approval_client.post(
            "/messages/compose",
            headers={"X-Inbox-Approval-Lease": inbox_server.APPROVAL_TEST_LEASE},
            json={"account": "me@example.com", "to": "a@example.com", "subject": "No-op", "body": "hello"},
        )

    assert resp.status_code == 403
    assert resp.json()["reason"] in {"unknown_per_action_approval_lease", "legacy_static_lease_denied"}
    mock_send.assert_not_called()


def test_cross_provider_lease_reuse_fails_before_provider_helper(approval_client):
    import inbox_server

    inbox_server.state.tasks_services = {"me@example.com": MagicMock()}
    inbox_server.state.gmail_services = {"me@example.com": MagicMock()}
    lease = inbox_server.mint_local_approval_lease(
        "POST",
        "/tasks?account=me@example.com",
        body={"title": "Local task"},
    )

    with patch("inbox_server.gmail_compose_send") as mock_send:
        resp = approval_client.post(
            "/messages/compose",
            headers={"X-Inbox-Approval-Lease": lease},
            json={"account": "me@example.com", "to": "a@example.com", "subject": "No-op", "body": "hello"},
        )

    assert resp.status_code == 403
    assert resp.json()["reason"] == "path_mismatch"
    mock_send.assert_not_called()


def test_body_change_gap_for_batch_item_count_fails_before_provider_helper(approval_client):
    import inbox_server

    inbox_server.state.sheets_services = {"me@example.com": MagicMock()}
    original = {"values": [["a"]], "account": "me@example.com"}
    changed = {"values": [["a"], ["b"]], "account": "me@example.com"}
    lease = inbox_server.mint_local_approval_lease("PUT", "/sheets/sheet-1/values/A1", body=original)

    with patch("inbox_server.sheets_values_update") as mock_update:
        resp = approval_client.put(
            "/sheets/sheet-1/values/A1",
            headers={"X-Inbox-Approval-Lease": lease},
            json=changed,
        )

    assert resp.status_code == 403
    assert resp.json()["reason"] == "item_count_mismatch"
    mock_update.assert_not_called()


def test_wrong_route_same_provider_operation_fails_before_provider_helper(approval_client):
    import inbox_server

    inbox_server.state.sheets_services = {"me@example.com": MagicMock()}
    body = {"values": [["a"]], "account": "me@example.com"}
    lease = inbox_server.mint_local_approval_lease("POST", "/sheets/sheet-1/values/A1/append", body=body)

    with patch("inbox_server.sheets_values_update") as mock_update:
        resp = approval_client.put(
            "/sheets/sheet-1/values/A1",
            headers={"X-Inbox-Approval-Lease": lease},
            json=body,
        )

    assert resp.status_code == 403
    assert resp.json()["reason"] == "method_mismatch"
    mock_update.assert_not_called()


def test_missing_stable_resource_binding_blocks_provider_mutation(approval_client):
    import inbox_server

    inbox_server.state.drive_services = {"me@example.com": MagicMock()}
    body = {"name": "Ambiguous folder"}
    lease = inbox_server.mint_local_approval_lease("POST", "/drive/folder", body=body)

    with patch("inbox_server.drive_create_folder") as mock_create:
        resp = approval_client.post(
            "/drive/folder",
            headers={"X-Inbox-Approval-Lease": lease},
            json=body,
    )

    assert resp.status_code == 403
    assert resp.json()["reason"] == "missing_resource_ref"
    mock_create.assert_not_called()


def test_connector_sync_execute_true_missing_lease_denies_before_sync_helper(approval_client):
    with patch("inbox_server.connector_sync_plan") as mock_sync:
        resp = approval_client.post("/connectors/whatsapp/sync", json={"execute": True})

    assert resp.status_code == 403
    assert resp.json()["executor"] == "inbox.connectors.sync"
    assert resp.json()["reason"] == "missing_per_action_approval_lease"
    mock_sync.assert_not_called()


def test_due_scheduled_send_without_durable_approval_denies_before_provider_helper(monkeypatch):
    import inbox_server

    scheduler = MagicMock()
    scheduler.get_due_messages.return_value = [
        {
            "id": 7,
            "source": "gmail",
            "conv_id": "to@example.com|Subject",
            "text": "hello",
            "send_at": "2026-05-30T00:00:00",
            "status": "pending",
            "account": "me@example.com",
            "created_at": "2026-05-30T00:00:00",
        }
    ]
    monkeypatch.setattr(inbox_server.state, "scheduler", scheduler)
    monkeypatch.setattr(inbox_server.state, "gmail_services", {"me@example.com": MagicMock()})

    with patch("inbox_server.gmail_compose_send") as mock_send:
        asyncio.run(inbox_server._process_scheduled_messages())

    mock_send.assert_not_called()
    scheduler.mark_failed.assert_called_once_with(7, "missing_durable_approval_proposal_id")


def test_due_followup_without_durable_approval_denies_before_provider_helpers(monkeypatch):
    import inbox_server

    scheduler = MagicMock()
    scheduler.get_due_followups.return_value = [
        {
            "id": 8,
            "source": "gmail",
            "conv_id": "msg-1",
            "thread_id": "",
            "remind_after": "2026-05-30T00:00:00",
            "reminder_title": "Follow up",
            "reminder_list": "Reminders",
            "status": "active",
            "created_at": "2026-05-30T00:00:00",
        }
    ]
    monkeypatch.setattr(inbox_server.state, "scheduler", scheduler)
    monkeypatch.setattr(inbox_server.state, "tasks_services", {"me@example.com": MagicMock()})

    with (
        patch("inbox_server.task_create") as mock_task_create,
        patch("inbox_server.reminder_create") as mock_reminder_create,
    ):
        asyncio.run(inbox_server._process_followup_reminders())

    mock_task_create.assert_not_called()
    mock_reminder_create.assert_not_called()
    scheduler.mark_followup_fired.assert_not_called()


def test_old_scheduler_rows_migrate_to_blocked_missing_approval(tmp_path):
    from scheduler import SchedulerStore

    db_path = tmp_path / "legacy-scheduler.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE scheduled_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                conv_id TEXT NOT NULL,
                text TEXT NOT NULL,
                send_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                account TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                sent_at TEXT,
                error TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE followup_reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                conv_id TEXT NOT NULL,
                thread_id TEXT NOT NULL DEFAULT '',
                remind_after TEXT NOT NULL,
                reminder_title TEXT NOT NULL,
                reminder_list TEXT NOT NULL DEFAULT 'Reminders',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                fired_at TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO scheduled_messages
            (source, conv_id, text, send_at, status, account, created_at)
            VALUES ('gmail', 'to@example.com|Subject', 'hello', '2000-01-01T00:00:00',
                    'pending', 'me@example.com', '2000-01-01T00:00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO followup_reminders
            (source, conv_id, thread_id, remind_after, reminder_title, reminder_list, status, created_at)
            VALUES ('gmail', 'msg-1', 'thread-1', '2000-01-01T00:00:00',
                    'Follow up', 'Reminders', 'active', '2000-01-01T00:00:00')
            """
        )

    store = SchedulerStore(db_path)

    due_message = store.get_due_messages()[0]
    due_followup = store.get_due_followups()[0]

    assert due_message["approval_state"] == "blocked_missing_approval"
    assert due_message["proposal_id"] == ""
    assert due_message["intent_hash"] == ""
    assert due_followup["approval_state"] == "blocked_missing_approval"
    assert due_followup["proposal_id"] == ""
    assert due_followup["intent_hash"] == ""


def test_scheduler_approval_schema_creates_durable_pending_proposals(tmp_path):
    from scheduler import SchedulerStore

    db_path = tmp_path / "scheduler.sqlite3"
    store = SchedulerStore(db_path)

    scheduled = store.schedule_message(
        source="gmail",
        conv_id="to@example.com|Subject",
        text="hello",
        send_at="2000-01-01T00:00:00",
        account="me@example.com",
    )
    followup = store.create_followup(
        source="gmail",
        conv_id="msg-1",
        thread_id="thread-1",
        remind_after="2000-01-01T00:00:00",
        reminder_title="Follow up",
    )

    restarted = SchedulerStore(db_path)
    due_message = restarted.get_due_messages()[0]
    due_followup = restarted.get_due_followups()[0]

    assert scheduled["approval_state"] == "proposal_pending"
    assert scheduled["proposal_id"].startswith("sched_prop_")
    assert scheduled["intent_hash"].startswith("sha256:")
    assert scheduled["preview"]["text_chars"] == 5
    assert due_message["approval_state"] == "proposal_pending"
    assert due_message["proposal_id"] == scheduled["proposal_id"]
    assert due_message["intent_hash"] == scheduled["intent_hash"]

    assert followup["approval_state"] == "proposal_pending"
    assert followup["proposal_id"].startswith("sched_prop_")
    assert followup["intent_hash"].startswith("sha256:")
    assert due_followup["approval_state"] == "proposal_pending"
    assert due_followup["proposal_id"] == followup["proposal_id"]
    assert due_followup["intent_hash"] == followup["intent_hash"]

    with sqlite3.connect(db_path) as conn:
        proposal_count = conn.execute("SELECT COUNT(*) FROM scheduler_proposals").fetchone()[0]
        lease_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'scheduler_execution_leases'"
        ).fetchone()
        receipt_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'scheduler_execution_receipts'"
        ).fetchone()

    assert proposal_count == 2
    assert lease_table == ("scheduler_execution_leases",)
    assert receipt_table == ("scheduler_execution_receipts",)


def test_proposal_pending_scheduled_send_still_denies_before_provider_helper(
    monkeypatch, tmp_path
):
    import inbox_server
    from scheduler import SchedulerStore

    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    store.schedule_message(
        source="gmail",
        conv_id="to@example.com|Subject",
        text="hello",
        send_at="2000-01-01T00:00:00",
        account="me@example.com",
    )
    monkeypatch.setattr(inbox_server.state, "scheduler", store)
    monkeypatch.setattr(inbox_server.state, "gmail_services", {"me@example.com": MagicMock()})

    with patch("inbox_server.gmail_compose_send") as mock_send:
        asyncio.run(inbox_server._process_scheduled_messages())

    mock_send.assert_not_called()
    failed = store.list_scheduled(status="failed")[0]
    assert failed["approval_state"] == "proposal_pending"
    assert failed["error"] == "scheduler_durable_approval_not_approved:proposal_pending"


@pytest.mark.parametrize("execute_value", [1, "true", "yes", "1"])
def test_connector_sync_coercible_truthy_execute_is_rejected_before_sync_helper(
    approval_client, execute_value
):
    with patch("inbox_server.connector_sync_plan") as mock_sync:
        resp = approval_client.post("/connectors/whatsapp/sync", json={"execute": execute_value})

    assert resp.status_code == 422
    mock_sync.assert_not_called()


# ── Approval-request / decide / audit-log workflow ───────────────────────────
#
# POST /approvals/request + POST /approvals/{id}/decide are the human-in-the-
# loop front end for mint_local_approval_lease(): a caller describes the
# pending action, the captain decides, and only on approval is a real lease
# minted (server-side, from the exact recorded action -- the caller cannot
# choose what gets minted). GET /audit/log is the persistent record of every
# request, decision, mint, and executed guarded write.


@pytest.fixture(autouse=False)
def _isolated_approvals(approval_client, tmp_path):
    """approval_client's ServerState() already built a real ApprovalStore at
    the module default path; point it at a tmp_path db so tests don't share
    state with each other or with a running dev server."""
    import inbox_server
    from approval_store import ApprovalStore

    inbox_server.state.approvals = ApprovalStore(tmp_path / "approvals.sqlite3")
    return approval_client


def test_approval_request_records_pending_row_without_minting_lease(_isolated_approvals):
    import inbox_server

    resp = _isolated_approvals.post(
        "/approvals/request",
        json={
            "method": "POST",
            "path": "/tasks?account=me@example.com",
            "body": {"title": "Ping Alice"},
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "pending"
    assert body["lease_id"] == ""
    assert body["provider"] == "google_tasks"
    assert body["executor"] == "inbox.tasks.write"
    assert body["request_id"].startswith("apr_")
    # No lease exists yet -- nothing was minted just by describing the action.
    assert inbox_server._approval_leases == {}


def test_approval_request_unknown_route_is_rejected(_isolated_approvals):
    resp = _isolated_approvals.post(
        "/approvals/request",
        json={"method": "POST", "path": "/not/a/guarded/route", "body": {}},
    )

    assert resp.status_code == 400


def test_approve_decision_mints_lease_that_executes_the_real_route_once(_isolated_approvals):
    import inbox_server

    inbox_server.state.tasks_services = {"me@example.com": MagicMock()}
    body = {"title": "Ping Alice"}
    created = _isolated_approvals.post(
        "/approvals/request",
        json={"method": "POST", "path": "/tasks?account=me@example.com", "body": body},
    ).json()

    decision = _isolated_approvals.post(
        f"/approvals/{created['request_id']}/decide",
        json={"approve": True, "decided_by": "captain"},
    )

    assert decision.status_code == 200
    decided = decision.json()
    assert decided["state"] == "approved"
    assert decided["lease_id"].startswith("lease_")

    fetched = _isolated_approvals.get(f"/approvals/{created['request_id']}")
    assert fetched.json()["lease_id"] == decided["lease_id"]

    with patch("inbox_server.task_create", return_value=True) as mock_create:
        executed = _isolated_approvals.post(
            "/tasks?account=me@example.com",
            headers={"X-Inbox-Approval-Lease": decided["lease_id"]},
            json=body,
        )
    assert executed.status_code == 200
    mock_create.assert_called_once()

    # Lease is single-use: replaying it must still fail closed.
    with patch("inbox_server.task_create") as mock_replay:
        replay = _isolated_approvals.post(
            "/tasks?account=me@example.com",
            headers={"X-Inbox-Approval-Lease": decided["lease_id"]},
            json=body,
        )
    assert replay.status_code == 403
    assert replay.json()["reason"] == "lease_replayed"
    mock_replay.assert_not_called()


def test_deny_decision_never_mints_a_lease(_isolated_approvals):
    import inbox_server

    created = _isolated_approvals.post(
        "/approvals/request",
        json={
            "method": "POST",
            "path": "/reminders",
            "body": {"title": "No-op"},
        },
    ).json()

    decision = _isolated_approvals.post(
        f"/approvals/{created['request_id']}/decide",
        json={"approve": False, "decided_by": "captain", "denial_reason": "not today"},
    )

    assert decision.status_code == 200
    decided = decision.json()
    assert decided["state"] == "denied"
    assert decided["lease_id"] == ""
    assert decided["denial_reason"] == "not today"
    assert inbox_server._approval_leases == {}

    with patch("inbox_server.reminder_create") as mock_create:
        resp = _isolated_approvals.post("/reminders", json={"title": "No-op"})
    assert resp.status_code == 403
    mock_create.assert_not_called()


def test_deciding_an_already_decided_request_is_rejected(_isolated_approvals):
    created = _isolated_approvals.post(
        "/approvals/request",
        json={"method": "POST", "path": "/reminders", "body": {"title": "No-op"}},
    ).json()
    _isolated_approvals.post(
        f"/approvals/{created['request_id']}/decide", json={"approve": True}
    )

    second = _isolated_approvals.post(
        f"/approvals/{created['request_id']}/decide", json={"approve": False}
    )

    assert second.status_code == 409


def test_decide_unknown_request_id_is_404(_isolated_approvals):
    resp = _isolated_approvals.post(
        "/approvals/apr_does_not_exist/decide", json={"approve": True}
    )
    assert resp.status_code == 404


def test_list_approvals_defaults_to_pending_only(_isolated_approvals):
    pending = _isolated_approvals.post(
        "/approvals/request",
        json={"method": "POST", "path": "/reminders", "body": {"title": "Pending one"}},
    ).json()
    approved = _isolated_approvals.post(
        "/approvals/request",
        json={"method": "POST", "path": "/reminders", "body": {"title": "Approved one"}},
    ).json()
    _isolated_approvals.post(f"/approvals/{approved['request_id']}/decide", json={"approve": True})

    resp = _isolated_approvals.get("/approvals")

    ids = {row["request_id"] for row in resp.json()}
    assert ids == {pending["request_id"]}


def test_audit_log_captures_full_lifecycle_of_an_approved_action(_isolated_approvals):
    import inbox_server

    inbox_server.state.tasks_services = {"me@example.com": MagicMock()}
    body = {"title": "Audit me"}
    created = _isolated_approvals.post(
        "/approvals/request",
        json={"method": "POST", "path": "/tasks?account=me@example.com", "body": body},
    ).json()
    decided = _isolated_approvals.post(
        f"/approvals/{created['request_id']}/decide", json={"approve": True}
    ).json()
    with patch("inbox_server.task_create", return_value=True):
        _isolated_approvals.post(
            "/tasks?account=me@example.com",
            headers={"X-Inbox-Approval-Lease": decided["lease_id"]},
            json=body,
        )

    log = _isolated_approvals.get("/audit/log").json()
    event_types = [e["event_type"] for e in log if e["request_id"] == created["request_id"]]

    assert "approval_requested" in event_types
    assert "approval_decided" in event_types
    assert "lease_minted" in event_types
    write_events = [e for e in log if e["event_type"] == "guarded_write_executed"]
    assert any(e["result"] == "success" and e["lease_id"] == decided["lease_id"] for e in write_events)


def test_audit_log_records_failed_guarded_write_execution(_isolated_approvals):
    import inbox_server

    inbox_server.state.tasks_services = {"me@example.com": MagicMock()}
    lease = inbox_server.mint_local_approval_lease(
        "POST", "/tasks?account=me@example.com", body={"title": "Will fail"}
    )

    with patch("inbox_server.task_create", side_effect=RuntimeError("boom")):
        resp = _isolated_approvals.post(
            "/tasks?account=me@example.com",
            headers={"X-Inbox-Approval-Lease": lease},
            json={"title": "Will fail"},
        )
    assert resp.status_code >= 400

    log = _isolated_approvals.get("/audit/log").json()
    write_events = [e for e in log if e["event_type"] == "guarded_write_executed"]
    assert any(e["result"] == "failed" and e["lease_id"] == lease for e in write_events)


def test_audit_log_filters_by_event_type(_isolated_approvals):
    _isolated_approvals.post(
        "/approvals/request",
        json={"method": "POST", "path": "/reminders", "body": {"title": "One"}},
    )
    _isolated_approvals.post(
        "/approvals/request",
        json={"method": "POST", "path": "/reminders", "body": {"title": "Two"}},
    )

    log = _isolated_approvals.get(
        "/audit/log", params={"event_type": "approval_requested"}
    ).json()

    assert len(log) == 2
    assert all(e["event_type"] == "approval_requested" for e in log)
