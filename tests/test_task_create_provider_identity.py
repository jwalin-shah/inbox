"""Regression: same canary idempotency key cannot create a second Google Task."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
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


def test_put_binding_then_get_roundtrips(tmp_path: Path):
    from task_create_bindings import get_binding, put_binding

    db = tmp_path / "bindings.sqlite3"
    put_binding(
        "canary-1",
        list_id="LIST123",
        task_id="TASK456",
        title="LIFEOPS CANARY — TASK-026 — canary-1",
        db_path=db,
    )
    got = get_binding("canary-1", db_path=db)
    assert got is not None
    assert got["list_id"] == "LIST123"
    assert got["task_id"] == "TASK456"


def test_put_binding_is_idempotent_and_preserves_first_provider_ids(tmp_path: Path):
    from task_create_bindings import get_binding, put_binding

    db = tmp_path / "bindings.sqlite3"
    put_binding("canary-1", list_id="LIST_A", task_id="TASK_A", title="t", db_path=db)
    put_binding("canary-1", list_id="LIST_B", task_id="TASK_B", title="t2", db_path=db)
    got = get_binding("canary-1", db_path=db)
    assert got is not None
    assert got["list_id"] == "LIST_A"
    assert got["task_id"] == "TASK_A"


def test_create_task_route_replays_binding_without_second_provider_insert(
    approval_client, monkeypatch, tmp_path
):
    import inbox_server
    import task_create_bindings

    db = tmp_path / "bindings.sqlite3"
    monkeypatch.setattr(task_create_bindings, "BINDINGS_DB", db)

    inbox_server.state.tasks_services = {"me@example.com": MagicMock()}
    body = {
        "title": "LIFEOPS CANARY — TASK-026 — req-abc",
        "list_id": "@default",
        "notes": "phase-c",
        "idempotency_key": "req-abc",
    }
    lease = inbox_server.mint_local_approval_lease("POST", "/tasks", body=body)

    calls = {"n": 0}

    def _fake_create(service, title, list_id="@default", due="", notes=""):
        calls["n"] += 1
        return {"ok": True, "task_id": f"TASK-{calls['n']}", "list_id": "LIST_REAL"}

    monkeypatch.setattr(inbox_server, "task_create", _fake_create)

    first = approval_client.post(
        "/tasks",
        headers={"X-Inbox-Approval-Lease": lease},
        json=body,
    )
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["ok"] is True
    assert first_body["task_id"] == "TASK-1"
    assert first_body["list_id"] == "LIST_REAL"
    assert first_body.get("idempotent_replay") is False
    assert calls["n"] == 1

    # Fresh lease for the same canary identity — must not call provider again.
    lease2 = inbox_server.mint_local_approval_lease("POST", "/tasks", body=body)
    second = approval_client.post(
        "/tasks",
        headers={"X-Inbox-Approval-Lease": lease2},
        json=body,
    )
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["ok"] is True
    assert second_body["task_id"] == "TASK-1"
    assert second_body["list_id"] == "LIST_REAL"
    assert second_body.get("idempotent_replay") is True
    assert calls["n"] == 1
