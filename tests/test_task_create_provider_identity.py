"""Regression: provider identity + provider-native idempotency (no local binding DB)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import services


class _Exec:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


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


def test_task_create_bindings_module_and_sqlite_removed():
    repo = Path(__file__).resolve().parents[1]
    assert not (repo / "task_create_bindings.py").exists()
    assert not (repo / ".inbox_task_create_bindings.sqlite3").exists()
    gitignore = (repo / ".gitignore").read_text(encoding="utf-8")
    assert ".inbox_task_create_bindings.sqlite3" not in gitignore
    # Local package must not reintroduce the module under this checkout.
    assert "task_create_bindings" not in (repo / "inbox_server.py").read_text(encoding="utf-8")
    assert "task_create_bindings" not in (repo / "services.py").read_text(encoding="utf-8")


def test_task_create_preserves_exact_provider_identity(monkeypatch):
    monkeypatch.delenv("INBOX_TEST_MODE", raising=False)

    class _Tasks:
        def insert(self, tasklist, body):
            assert tasklist == "@default"
            assert body["title"] == "t"
            return _Exec(
                {
                    "id": "TASK_PROVIDER",
                    "selfLink": (
                        "https://tasks.googleapis.com/tasks/v1/lists/LIST_REAL/tasks/TASK_PROVIDER"
                    ),
                }
            )

    class _Svc:
        def tasks(self):
            return _Tasks()

        def tasklists(self):
            raise RuntimeError("force selfLink resolution")

    out = services.task_create(_Svc(), "t", "@default")
    assert out == {"ok": True, "task_id": "TASK_PROVIDER", "list_id": "LIST_REAL"}
    assert not Path(".inbox_task_create_bindings.sqlite3").exists()


def test_retry_same_idempotency_key_does_not_insert_second_provider_object(monkeypatch):
    """Durability boundary = Google Tasks projection (notes marker), not a local DB."""
    monkeypatch.delenv("INBOX_TEST_MODE", raising=False)
    marker = services.task_idempotency_marker("req-abc")
    inserts: list[dict] = []
    provider_items: list[dict] = []

    class _Tasks:
        def list(self, tasklist, showCompleted, maxResults):
            return _Exec({"items": list(provider_items)})

        def insert(self, tasklist, body):
            inserts.append({"tasklist": tasklist, "body": dict(body)})
            task_id = f"TASK-{len(inserts)}"
            provider_items.append(
                {
                    "id": task_id,
                    "title": body["title"],
                    "status": "needsAction",
                    "notes": body.get("notes", ""),
                }
            )
            return _Exec(
                {
                    "id": task_id,
                    "selfLink": (
                        f"https://tasks.googleapis.com/tasks/v1/lists/LIST_REAL/tasks/{task_id}"
                    ),
                }
            )

    class _Tasklists:
        def get(self, tasklist):
            return _Exec({"id": "LIST_REAL", "title": "My Tasks"})

    class _Svc:
        def tasks(self):
            return _Tasks()

        def tasklists(self):
            return _Tasklists()

    svc = _Svc()
    first = services.task_create(
        svc, "LIFEOPS CANARY", "@default", notes="phase-c", idempotency_key="req-abc"
    )
    assert first == {
        "ok": True,
        "task_id": "TASK-1",
        "list_id": "LIST_REAL",
        "idempotent_replay": False,
        "idempotency_key": "req-abc",
    }
    assert marker in inserts[0]["body"]["notes"]
    assert len(inserts) == 1

    # Restart / process boundary: fresh call re-reads provider state only.
    second = services.task_create(
        svc, "LIFEOPS CANARY", "@default", notes="phase-c", idempotency_key="req-abc"
    )
    assert second == {
        "ok": True,
        "task_id": "TASK-1",
        "list_id": "LIST_REAL",
        "idempotent_replay": True,
        "idempotency_key": "req-abc",
    }
    assert len(inserts) == 1
    assert not (
        Path(__file__).resolve().parents[1] / ".inbox_task_create_bindings.sqlite3"
    ).exists()


def test_create_task_route_preserves_identity_and_replays(approval_client, monkeypatch):
    import inbox_server

    inserts: list[dict] = []
    provider_items: list[dict] = []

    class _Tasks:
        def list(self, tasklist, showCompleted, maxResults):
            return _Exec({"items": list(provider_items)})

        def insert(self, tasklist, body):
            inserts.append(dict(body))
            task_id = f"TASK-{len(inserts)}"
            provider_items.append(
                {
                    "id": task_id,
                    "title": body["title"],
                    "status": "needsAction",
                    "notes": body.get("notes", ""),
                }
            )
            return _Exec(
                {
                    "id": task_id,
                    "selfLink": (
                        f"https://tasks.googleapis.com/tasks/v1/lists/LIST_REAL/tasks/{task_id}"
                    ),
                }
            )

    class _Tasklists:
        def get(self, tasklist):
            return _Exec({"id": "LIST_REAL", "title": "My Tasks"})

    class _Svc:
        def tasks(self):
            return _Tasks()

        def tasklists(self):
            return _Tasklists()

    # Real task_create must run; fixture sets INBOX_TEST_MODE=1 which blocks writes.
    monkeypatch.setenv("INBOX_TEST_MODE", "0")
    inbox_server.state.tasks_services = {"me@example.com": _Svc()}

    body = {
        "title": "LIFEOPS CANARY — TASK-026 — req-abc",
        "list_id": "@default",
        "notes": "phase-c",
        "idempotency_key": "req-abc",
    }
    lease = inbox_server.mint_local_approval_lease("POST", "/tasks", body=body)
    first = approval_client.post(
        "/tasks",
        headers={"X-Inbox-Approval-Lease": lease},
        json=body,
    )
    assert first.status_code == 200
    assert first.json() == {
        "ok": True,
        "task_id": "TASK-1",
        "list_id": "LIST_REAL",
        "idempotent_replay": False,
        "idempotency_key": "req-abc",
    }
    assert len(inserts) == 1

    lease2 = inbox_server.mint_local_approval_lease("POST", "/tasks", body=body)
    second = approval_client.post(
        "/tasks",
        headers={"X-Inbox-Approval-Lease": lease2},
        json=body,
    )
    assert second.status_code == 200
    assert second.json() == {
        "ok": True,
        "task_id": "TASK-1",
        "list_id": "LIST_REAL",
        "idempotent_replay": True,
        "idempotency_key": "req-abc",
    }
    assert len(inserts) == 1
    assert not Path(".inbox_task_create_bindings.sqlite3").exists()


def test_create_task_still_requires_approval_lease(approval_client):
    resp = approval_client.post(
        "/tasks",
        json={"title": "no-lease", "list_id": "@default", "idempotency_key": "k1"},
    )
    assert resp.status_code in {401, 403}
    body = resp.json()
    assert body.get("error") == "approval_required" or "approval" in str(body).lower()
    assert not Path(".inbox_task_create_bindings.sqlite3").exists()


def test_lease_is_execution_transport_not_homebase_authorization(approval_client):
    """Inbox lease_* remains local execution transport; not HomeBase auth."""
    import inbox_server

    body = {"title": "lease-semantics", "list_id": "@default", "idempotency_key": "lease-sem"}
    lease = inbox_server.mint_local_approval_lease("POST", "/tasks", body=body)
    assert lease.startswith("lease_")
    assert "homebase" not in lease.lower()
    assert "AdmissionCheckReceipt" not in lease
    # Without a Google Tasks service the route may error after the gate; the
    # gate itself must still accept a valid lease as transport only.
    inbox_server.state.tasks_services = {"me@example.com": MagicMock()}
    with patch.object(
        inbox_server,
        "task_create",
        return_value={"ok": True, "task_id": "T", "list_id": "L", "idempotent_replay": False},
    ):
        resp = approval_client.post(
            "/tasks",
            headers={"X-Inbox-Approval-Lease": lease},
            json=body,
        )
    assert resp.status_code == 200
    assert resp.json()["task_id"] == "T"
