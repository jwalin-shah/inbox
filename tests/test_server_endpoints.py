"""Tests for the new server endpoints (Reminders, GitHub, Drive)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    """Create a test client with mocked startup."""
    import os

    with (
        patch.dict(os.environ, {"INBOX_SERVER_TOKEN": ""}, clear=False),
        patch("inbox_server.init_contacts", return_value=0),
        patch("inbox_server.google_auth_all", return_value=({}, {}, {}, {}, {}, {})),
        patch("inbox_server.load_voice_config", return_value={"ambient_autostart": False}),
    ):
        from inbox_server import app, state
        from services import AmbientService, DictationService

        state.gmail_services = {}
        state.cal_services = {}
        state.drive_services = {}
        state.sheets_services = {}
        # Reset ambient/dictation to real instances so tests can inspect internals
        state.ambient = AmbientService(on_note=lambda r, s: None)
        state.dictation = DictationService()
        with TestClient(app) as c:
            from approval_helpers import wrap_approval_lease
            wrap_approval_lease(c)
            yield c, state


class TestReminderEndpoints:
    def test_list_reminder_lists(self, client):
        c, _ = client
        with patch(
            "inbox_server.reminders_lists",
            return_value=[{"name": "Daily", "incomplete_count": 5}],
        ):
            resp = c.get("/reminders/lists")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Daily"

    def test_list_reminders(self, client):
        c, _ = client
        from services import Reminder

        mock_items = [
            Reminder(
                id="1",
                title="Buy milk",
                completed=False,
                list_name="Daily",
                due_date=datetime(2026, 4, 10),
                creation_date=datetime(2026, 4, 9),
            )
        ]
        with patch("inbox_server.reminders_list", return_value=mock_items):
            resp = c.get("/reminders")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Buy milk"
        assert data[0]["due_date"] is not None

    def test_create_reminder(self, client):
        c, _ = client
        with patch("inbox_server.reminder_create", return_value=True):
            resp = c.post("/reminders", json={"title": "New task"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_complete_reminder(self, client):
        c, _ = client
        from services import Reminder

        mock_reminder = Reminder(id="1", title="Buy milk", completed=False, list_name="Daily")
        with (
            patch("inbox_server.reminder_by_id", return_value=mock_reminder),
            patch("inbox_server.reminder_complete", return_value=True),
        ):
            resp = c.post("/reminders/1/complete")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_complete_nonexistent_reminder(self, client):
        c, _ = client
        with patch("inbox_server.reminder_by_id", return_value=None):
            resp = c.post("/reminders/999/complete")
        assert resp.status_code == 404

    def test_edit_reminder(self, client):
        c, _ = client
        from services import Reminder

        mock_reminder = Reminder(id="1", title="Buy milk", completed=False, list_name="Daily")
        with (
            patch("inbox_server.reminder_by_id", return_value=mock_reminder),
            patch("inbox_server.reminder_edit", return_value=True),
        ):
            resp = c.put("/reminders/1", json={"title": "Buy almond milk"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_edit_reminder_with_due_date_and_notes(self, client):
        c, _ = client
        from services import Reminder

        mock_reminder = Reminder(id="1", title="Buy milk", completed=False, list_name="Daily")
        with (
            patch("inbox_server.reminder_by_id", return_value=mock_reminder),
            patch("inbox_server.reminder_edit", return_value=True),
        ):
            resp = c.put(
                "/reminders/1",
                json={"title": "Buy almond milk", "due_date": "4/15/2026", "notes": "Oat milk"},
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


    def test_edit_nonexistent_reminder(self, client):
        c, _ = client
        with patch("inbox_server.reminder_by_id", return_value=None):
            resp = c.put("/reminders/999", json={"title": "New title"})
        assert resp.status_code == 404

    def test_delete_reminder(self, client):
        c, _ = client
        from services import Reminder

        mock_reminder = Reminder(id="1", title="Buy milk", completed=False, list_name="Daily")
        with (
            patch("inbox_server.reminder_by_id", return_value=mock_reminder),
            patch("inbox_server.reminder_delete", return_value=True),
        ):
            resp = c.delete("/reminders/1")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_delete_nonexistent_reminder(self, client):
        c, _ = client
        with patch("inbox_server.reminder_by_id", return_value=None):
            resp = c.delete("/reminders/999")
        assert resp.status_code == 404

    def test_complete_reminder_passes_list_name(self, client):
        """Server passes list_name from reminder_by_id to AppleScript for disambiguation."""
        c, _ = client
        from services import Reminder

        mock_reminder = Reminder(id="1", title="Buy milk", completed=False, list_name="Daily")
        with (
            patch("inbox_server.reminder_by_id", return_value=mock_reminder),
            patch("inbox_server.reminder_complete") as mock_complete,
        ):
            mock_complete.return_value = True
            resp = c.post("/reminders/1/complete")
        assert resp.status_code == 200
        # Verify list_name was passed to the AppleScript function
        mock_complete.assert_called_once_with("Buy milk", "Daily")

    def test_edit_reminder_passes_list_name(self, client):
        """Server passes list_name from reminder_by_id to AppleScript for disambiguation."""
        c, _ = client
        from services import Reminder

        mock_reminder = Reminder(id="1", title="Buy milk", completed=False, list_name="Daily")
        with (
            patch("inbox_server.reminder_by_id", return_value=mock_reminder),
            patch("inbox_server.reminder_edit") as mock_edit,
        ):
            mock_edit.return_value = True
            resp = c.put("/reminders/1", json={"title": "Buy oat milk"})
        assert resp.status_code == 200
        # Verify list_name was passed to the AppleScript function
        mock_edit.assert_called_once_with(
            current_title="Buy milk",
            title="Buy oat milk",
            due_date=None,
            notes=None,
            list_name="Daily",
            priority=None,
            flagged=None,
        )

    def test_delete_reminder_passes_list_name(self, client):
        """Server passes list_name from reminder_by_id to AppleScript for disambiguation."""
        c, _ = client
        from services import Reminder

        mock_reminder = Reminder(id="1", title="Buy milk", completed=False, list_name="Daily")
        with (
            patch("inbox_server.reminder_by_id", return_value=mock_reminder),
            patch("inbox_server.reminder_delete") as mock_delete,
        ):
            mock_delete.return_value = True
            resp = c.delete("/reminders/1")
        assert resp.status_code == 200
        # Verify list_name was passed to the AppleScript function
        mock_delete.assert_called_once_with("Buy milk", "Daily")


class TestRouteEndpoint:
    def test_multi_stop_route_is_read_only_and_returns_plan(self, client):
        c, _ = client
        with patch(
            "inbox_server.maps_travel_time",
            side_effect=[
                {
                    "duration_seconds": 20 * 60,
                    "duration_text": "20 mins",
                    "distance_text": "5 mi",
                },
                {
                    "duration_seconds": 15 * 60,
                    "duration_text": "15 mins",
                    "distance_text": "4 mi",
                },
            ],
        ):
            resp = c.post(
                "/maps/route",
                json={
                    "origin": "Home",
                    "stops": [
                        {"name": "Harsh", "location": "Harsh address", "dwell_minutes": 5},
                        {"name": "Practice", "location": "Practice address"},
                    ],
                    "arrival_time": "2026-08-27T17:40:00-07:00",
                    "buffer_minutes": 10,
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["read_only"] is True
        assert data["departure_time"] == "2026-08-27T16:50:00-07:00"
        assert len(data["legs"]) == 2


class TestGitHubEndpoints:
    def test_list_notifications(self, client):
        c, _ = client
        from services import GitHubNotification

        mock_notifs = [
            GitHubNotification(
                id="1",
                title="Fix bug",
                repo="owner/repo",
                type="PullRequest",
                reason="review_requested",
                unread=True,
                updated_at=datetime(2026, 4, 9),
                url="https://github.com/owner/repo/pull/1",
            )
        ]
        with patch("inbox_server.github_notifications", return_value=mock_notifs):
            resp = c.get("/github/notifications")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Fix bug"

    def test_mark_read(self, client):
        c, _ = client
        with patch("inbox_server.github_mark_read", return_value=True):
            resp = c.post("/github/notifications/1/read")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_mark_all_read(self, client):
        c, _ = client
        with patch("inbox_server.github_mark_all_read", return_value=True):
            resp = c.post("/github/notifications/read-all")
        assert resp.status_code == 200

    def test_list_pulls(self, client):
        c, _ = client
        mock_pulls = [{"id": 1, "number": 42, "title": "PR", "repo": "o/r"}]
        with patch("inbox_server.github_pulls", return_value=mock_pulls):
            resp = c.get("/github/pulls")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestDriveEndpoints:
    def test_list_files_no_account(self, client):
        c, state = client
        resp = c.get("/drive/files")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_files_with_account(self, client):
        c, state = client
        from services import DriveFile

        mock_svc = MagicMock()
        state.drive_services = {"test@gmail.com": mock_svc}
        mock_files = [
            DriveFile(
                id="f1",
                name="doc.pdf",
                mime_type="application/pdf",
                modified=datetime(2026, 4, 9),
                size=1024,
                web_link="https://drive.google.com/file/d/f1/view",
            )
        ]
        with patch("inbox_server.drive_files", return_value=mock_files):
            resp = c.get("/drive/files")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "doc.pdf"
        assert data[0]["account"] == "test@gmail.com"


class TestVoicePipelineEndpoints:
    def test_ambient_status_includes_available(self, client):
        c, _ = client
        with patch("inbox_server.ambient_available", return_value=(True, "")):
            resp = c.get("/ambient/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "available" in data
        assert "reason" in data

    def test_ambient_transcript_empty(self, client):
        c, state = client
        resp = c.get("/ambient/transcript")
        assert resp.status_code == 200
        data = resp.json()
        assert data["segments"] == []
        assert data["count"] == 0

    def test_dictation_status(self, client):
        c, _ = client
        resp = c.get("/dictation/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "running" in data
        assert "available" in data

    def test_voice_config_get(self, client):
        c, _ = client
        fake_cfg = {"ambient_autostart": True, "dictation_hotkey": "f5", "vault_dir": "/tmp"}
        with patch("inbox_server.load_voice_config", return_value=fake_cfg):
            resp = c.get("/voice/config")
        assert resp.status_code == 200
        assert resp.json()["dictation_hotkey"] == "f5"

    def test_voice_config_put(self, client):
        c, _ = client
        fake_cfg = {"ambient_autostart": True, "dictation_hotkey": "f5", "vault_dir": "/tmp"}
        with (
            patch("inbox_server.load_voice_config", return_value=fake_cfg),
            patch("inbox_server.save_voice_config") as mock_save,
        ):
            resp = c.put("/voice/config", json={"ambient_autostart": False})
        assert resp.status_code == 200
        assert resp.json()["ambient_autostart"] is False
        mock_save.assert_called_once()

    def test_ambient_notes_filter(self, client):
        c, _ = client
        notes = [
            {"date": "2026-04-10", "path": "/a", "size": 1},
            {"date": "2026-03-01", "path": "/b", "size": 2},
        ]
        with patch("inbox_server.ambient_notes.list_daily_notes", return_value=notes):
            resp = c.get("/ambient/notes?q=2026-04")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_ambient_start_stop(self, client):
        c, state = client
        # mock start/stop to avoid spawning real threads
        with (
            patch.object(state.ambient, "start"),
            patch.object(state.ambient, "stop"),
        ):
            state.ambient._running = False
            resp = c.post("/ambient/start")
            assert resp.status_code == 200
            assert resp.json()["status"] == "started"
            # fake that it's running now
            state.ambient._running = True
            resp = c.post("/ambient/stop")
            assert resp.status_code == 200
            assert resp.json()["status"] == "stopped"

    def test_get_file(self, client):
        c, state = client
        from services import DriveFile

        mock_svc = MagicMock()
        state.drive_services = {"test@gmail.com": mock_svc}
        mock_file = DriveFile(
            id="f1",
            name="doc.pdf",
            mime_type="application/pdf",
            modified=datetime(2026, 4, 9),
        )
        with patch("inbox_server.drive_get", return_value=mock_file):
            resp = c.get("/drive/files/f1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "f1"

    def test_get_file_not_found(self, client):
        c, state = client
        mock_svc = MagicMock()
        state.drive_services = {"test@gmail.com": mock_svc}
        with patch("inbox_server.drive_get", return_value=None):
            resp = c.get("/drive/files/bad-id")
        assert resp.status_code == 404

    def test_create_folder(self, client):
        c, state = client
        from services import DriveFile

        mock_svc = MagicMock()
        state.drive_services = {"test@gmail.com": mock_svc}
        mock_folder = DriveFile(
            id="folder-1",
            name="New Folder",
            mime_type="application/vnd.google-apps.folder",
            modified=datetime(2026, 4, 9),
        )
        with patch("inbox_server.drive_create_folder", return_value=mock_folder):
            resp = c.post("/drive/folder", json={"name": "New Folder"})
        # Drive folder creation is blocked by the approval gate until a stable
        # resource binding is implemented (missing_resource_ref is intentional).
        assert resp.status_code == 403
        assert resp.json()["reason"] == "missing_resource_ref"

    def test_delete_file(self, client):
        c, state = client
        mock_svc = MagicMock()
        state.drive_services = {"test@gmail.com": mock_svc}
        with patch("inbox_server.drive_delete", return_value=True):
            resp = c.delete("/drive/files/f1")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_no_drive_account_errors(self, client):
        c, state = client
        state.drive_services = {}
        state.sheets_services = {}
        resp = c.get("/drive/files/f1")
        assert resp.status_code == 404

    def test_list_files_with_folder_id(self, client):
        c, state = client
        from services import DriveFile

        mock_svc = MagicMock()
        state.drive_services = {"test@gmail.com": mock_svc}
        mock_files = [
            DriveFile(
                id="f2",
                name="readme.md",
                mime_type="text/markdown",
                modified=datetime(2026, 4, 9),
                size=256,
            )
        ]
        with patch("inbox_server.drive_files", return_value=mock_files) as mock_fn:
            resp = c.get("/drive/files", params={"folder_id": "folder-abc"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "readme.md"
        # Verify folder_id was passed through
        mock_fn.assert_called_once()
        call_kwargs = mock_fn.call_args
        assert call_kwargs.kwargs.get("folder_id") == "folder-abc"

    def test_download_file(self, client):
        c, state = client
        mock_svc = MagicMock()
        state.drive_services = {"test@gmail.com": mock_svc}
        with patch(
            "inbox_server.drive_download",
            return_value=(b"file content here", "application/pdf"),
        ):
            resp = c.get("/drive/files/f1/download")
        assert resp.status_code == 200
        assert resp.content == b"file content here"
        assert resp.headers["content-type"] == "application/pdf"

    def test_download_file_not_found(self, client):
        c, state = client
        mock_svc = MagicMock()
        state.drive_services = {"test@gmail.com": mock_svc}
        with patch("inbox_server.drive_download", return_value=None):
            resp = c.get("/drive/files/f1/download")
        assert resp.status_code == 404

    def test_download_no_drive_account(self, client):
        c, state = client
        state.drive_services = {}
        state.sheets_services = {}
        resp = c.get("/drive/files/f1/download")
        assert resp.status_code == 404


class TestHealthEndpoint:
    def test_health_includes_new_services(self, client):
        c, state = client
        with patch("services._github_token", return_value="token"):
            resp = c.get("/health")
        data = resp.json()
        assert "drive_accounts" in data
        assert "github_configured" in data
        assert data["github_configured"] is True


class TestAccountsEndpoint:
    def test_accounts_includes_drive_and_github(self, client):
        c, state = client
        state.drive_services = {"test@gmail.com": MagicMock()}
        with patch("services._github_token", return_value="token"):
            resp = c.get("/accounts")
        data = resp.json()
        assert "drive" in data
        assert "github" in data
        assert data["drive"] == ["test@gmail.com"]
        assert data["github"] is True

    def test_accounts_auth_status_returns_google_auth_diagnostics(self, client):
        c, _ = client
        diagnostics = {
            "counts": {"tokens_present": 1, "revoked_or_expired": 1},
            "tokens": [{"email_hint": "a@example.com"}],
        }
        with patch("inbox_server.google_auth_diagnostics", return_value=diagnostics) as mock:
            resp = c.get("/accounts/auth-status?check_refresh=true")
        assert resp.status_code == 200
        assert resp.json() == diagnostics
        mock.assert_called_once_with(True)


class TestGmailFilterAuditEndpoint:
    def test_filter_audit_returns_read_only_filter_summary(self, client):
        c, state = client
        svc = MagicMock()
        state.gmail_services = {"me@example.com": svc}
        audit = {
            "account": "me@example.com",
            "filters_count": 2,
            "trash_filters": [{"id": "trash"}],
            "archive_filters": [{"id": "archive"}],
            "triage_filters": [{"id": "triage"}],
        }
        with patch("inbox_server.gmail_filter_audit", return_value=audit) as mock:
            resp = c.get("/gmail/filters/audit")
        assert resp.status_code == 200
        data = resp.json()
        assert data["accounts"] == [audit]
        assert data["trash_filters_count"] == 1
        assert data["archive_filters_count"] == 1
        assert data["triage_filters_count"] == 1
        mock.assert_called_once_with(svc, "me@example.com")


class TestContactsEndpoints:
    def test_search_contacts_returns_list(self, client):
        c, _ = client
        mock_results = [
            {
                "id": "alice@example.com",
                "name": "Alice Smith",
                "emails": ["alice@example.com"],
                "phones": [],
                "github_handle": "",
                "photo_url": "",
                "source_counts": {"imessage": 0, "gmail": 2, "calendar": 0},
            }
        ]
        with patch("inbox_server.contacts_search", return_value=mock_results):
            resp = c.get("/contacts/search", params={"q": "alice"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Alice Smith"

    def test_search_contacts_empty(self, client):
        c, _ = client
        with patch("inbox_server.contacts_search", return_value=[]):
            resp = c.get("/contacts/search", params={"q": "nobody"})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_memory_read_is_bounded_and_preserves_records(self, client):
        c, _ = client
        rows = [
            {
                "id": 7,
                "memory_type": "project",
                "subject": "Street play",
                "content": "Practice coordination",
                "source": "manual",
                "confidence": 1.0,
                "status": "active",
                "metadata": {"capture_id": "cap_1"},
            }
        ]
        with patch("inbox_server.memory_store.query_entries", return_value=rows) as query:
            resp = c.get("/memory", params={"memory_type": "project", "limit": 9999})
        assert resp.status_code == 200
        assert resp.json() == rows
        query.assert_called_once_with(
            query="",
            memory_type="project",
            subject="",
            status="",
            limit=500,
        )

    def test_project_records_are_bounded_and_source_linked(self, client):
        c, _ = client
        with (
            patch("inbox_server._get_sheets_service_for_account", return_value=("jshah1331@gmail.com", object())),
            patch(
                "inbox_server.sheets_values_get",
                return_value=[
                    ["Area", "Project", "Status", "Next Action", "Source of Truth"],
                    ["Personal Ops", "Life Ops", "Active", "Keep rules simple", "System Map"],
                    ["Hardware", "Hardware Lab", "Active", "Inventory", "Drive folder"],
                ],
            ) as read_values,
        ):
            resp = c.get("/project-records", params={"limit": 1})
        assert resp.status_code == 200
        data = resp.json()
        assert data["schema_version"] == "inbox.project_records.v1"
        assert data["read_only"] is True
        assert data["record_count"] == 1
        assert data["records"][0]["project"] == "Life Ops"
        assert data["records"][0]["source_ref"]["source"] == "google_sheets"
        assert data["records"][0]["source_ref"]["row"] == 2
        read_values.assert_called_once()

    def test_master_ops_queues_are_read_only_and_row_attributed(self, client):
        c, _ = client
        tab_values = {
            "Email Action Queue": [
                ["Email ID", "Subject", "Action Needed", "Status"],
                ["E-0001", "Review billing", "Update billing model", "Open"],
            ],
            "Capture Inbox": [["Captured At", "Text", "Status"]],
            "Google Tasks Mirror": [
                ["google_task_id", "title", "status"],
                ["task-1", "Follow up", "needsAction"],
            ],
        }

        def read_values(_service, _spreadsheet_id, range_name):
            for name, values in tab_values.items():
                if name in range_name:
                    return values
            raise AssertionError(range_name)

        with (
            patch("inbox_server._get_sheets_service_for_account", return_value=("jshah1331@gmail.com", object())),
            patch("inbox_server.sheets_values_get", side_effect=read_values),
        ):
            resp = c.get("/master-ops/queues", params={"limit": 1})
        assert resp.status_code == 200
        data = resp.json()
        assert data["schema_version"] == "inbox.master_ops_queues.v1"
        assert data["read_only"] is True
        email_row = data["queues"]["email_actions"]["records"][0]
        assert email_row["email_id"] == "E-0001"
        assert email_row["source_ref"]["sheet_name"] == "Email Action Queue"
        assert email_row["source_ref"]["row"] == 2

    def test_lifeops_sheet_projection_preserves_people_and_action_rows(self, client):
        c, _ = client
        tab_values = {
            "04_PEOPLE": [["person_id", "name", "identity_confidence"], ["P-1", "Alex", "high"]],
            "05_ACTIONS": [["action_id", "action", "state"], ["A-1", "Reply to Alex", "READY_HUMAN"]],
            "03_PROJECTS": [["project_id", "project", "status"], ["PR-1", "LifeOps", "ACTIVE"]],
        }

        def read_values(_service, _spreadsheet_id, range_name):
            for name, values in tab_values.items():
                if name in range_name:
                    return values
            raise AssertionError(range_name)

        with (
            patch("inbox_server._get_sheets_service_for_account", return_value=("jshah1331@gmail.com", object())),
            patch("inbox_server.sheets_values_get", side_effect=read_values),
        ):
            resp = c.get("/lifeops-sheet/projection", params={"limit": 1})
        assert resp.status_code == 200
        data = resp.json()
        assert data["schema_version"] == "inbox.lifeops_sheet.v1"
        assert data["read_only"] is True
        assert data["spreadsheet_id"] == "10XAlrmI7tMvXADyrHVK7hLYGcDV6V-IxZhihtxsh5m8"
        assert data["tabs"]["people"]["records"][0]["person_id"] == "P-1"
        assert data["tabs"]["actions"]["records"][0]["action_id"] == "A-1"
        assert data["tabs"]["projects"]["records"][0]["source_ref"]["row"] == 2
        assert data["tabs"]["people"]["records"][0]["source_ref"]["sheet_name"] == "04_PEOPLE"

    def test_lifeops_sheet_projection_can_include_bounded_auxiliary_tabs(self, client):
        c, _ = client
        tab_values = {
            "04_PEOPLE": [["person_id", "name"], ["P-1", "Alex"]],
            "05_ACTIONS": [["action_id", "action"], ["A-1", "Reply"]],
            "03_PROJECTS": [["project_id", "project"], ["PR-1", "LifeOps"]],
            "08_EVIDENCE": [["evidence_id", "claim"], ["E-1", "Connection"]],
            "11_SOURCES": [["source_id", "canonical_authority"], ["S-1", "Gmail"]],
        }

        def read_values(_service, _spreadsheet_id, range_name):
            for name, values in tab_values.items():
                if name in range_name:
                    return values
            raise AssertionError(range_name)

        with (
            patch("inbox_server._get_sheets_service_for_account", return_value=("jwalinshah13@gmail.com", object())),
            patch("inbox_server.sheets_values_get", side_effect=read_values),
        ):
            resp = c.get(
                "/lifeops-sheet/projection",
                params={"limit": 1, "include_tabs": "evidence,sources"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tabs"]["evidence"]["records"][0]["evidence_id"] == "E-1"
        assert data["tabs"]["sources"]["records"][0]["source_id"] == "S-1"
        assert data["tabs"]["evidence"]["records"][0]["source_ref"]["sheet_name"] == "08_EVIDENCE"
        assert data["spreadsheet_id"] == "10XAlrmI7tMvXADyrHVK7hLYGcDV6V-IxZhihtxsh5m8"

    def test_get_contact_profile(self, client):
        c, _ = client
        mock_profile = {
            "contact": {
                "id": "alice@example.com",
                "name": "Alice Smith",
                "emails": ["alice@example.com"],
                "phones": [],
                "github_handle": "",
                "photo_url": "",
                "source_counts": {"imessage": 1, "gmail": 2, "calendar": 0},
            },
            "imessages": [],
            "gmail_threads": [],
            "calendar_events": [],
            "timeline": [],
        }
        with patch("inbox_server.contacts_profile", return_value=mock_profile):
            resp = c.get("/contacts/alice@example.com/profile")
        assert resp.status_code == 200
        data = resp.json()
        assert data["contact"]["name"] == "Alice Smith"
        assert "timeline" in data

    def test_favorites_round_trip(self, client, tmp_path, monkeypatch):
        c, _ = client
        fav_file = tmp_path / "favorites.json"
        monkeypatch.setattr("services.FAVORITES_FILE", fav_file)
        monkeypatch.setattr("inbox_server.load_favorites", lambda: set())
        monkeypatch.setattr("inbox_server.save_favorites", lambda ids: None)

        with patch("inbox_server.load_favorites", return_value=set()):
            resp = c.get("/contacts/favorites")
        assert resp.status_code == 200
        assert resp.json()["favorites"] == []

    def test_add_favorite(self, client):
        c, _ = client
        with (
            patch("inbox_server.load_favorites", return_value=set()),
            patch("inbox_server.save_favorites"),
        ):
            resp = c.post("/contacts/favorites/alice@example.com")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "alice@example.com" in data["favorites"]

    def test_remove_favorite(self, client):
        c, _ = client
        with (
            patch("inbox_server.load_favorites", return_value={"alice@example.com"}),
            patch("inbox_server.save_favorites"),
        ):
            resp = c.delete("/contacts/favorites/alice@example.com")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "alice@example.com" not in data["favorites"]


class TestSearchEndpoint:
    def test_search_returns_expected_shape(self, client):
        c, _ = client
        mock_result = {
            "query": "standup",
            "total": 1,
            "results": [
                {
                    "source": "calendar",
                    "id": "evt1",
                    "title": "Team standup",
                    "snippet": "standup call",
                    "timestamp": "2026-04-10T10:00:00",
                    "metadata": {"calendar_id": "primary"},
                }
            ],
        }
        with patch("inbox_server.search_all", return_value=mock_result):
            resp = c.post("/search", json={"q": "standup"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "standup"
        assert data["total"] == 1
        assert len(data["results"]) == 1
        r = data["results"][0]
        assert r["source"] == "calendar"
        assert r["id"] == "evt1"
        assert "title" in r
        assert "snippet" in r
        assert "timestamp" in r
        assert "metadata" in r

    def test_search_empty_query_returns_zero(self, client):
        c, _ = client
        with patch(
            "inbox_server.search_all", return_value={"query": "", "total": 0, "results": []}
        ):
            resp = c.post("/search", json={"q": ""})
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_search_source_filter_passed_through(self, client):
        c, _ = client
        with patch(
            "inbox_server.search_all", return_value={"query": "x", "total": 0, "results": []}
        ) as mock_sa:
            resp = c.post("/search", json={"q": "x", "sources": ["imessage", "notes"], "limit": 20})
        assert resp.status_code == 200
        mock_sa.assert_called_once()
        call_kwargs = mock_sa.call_args
        assert call_kwargs.kwargs.get("sources") == ["imessage", "notes"]
        assert call_kwargs.kwargs.get("limit") == 20

    def test_search_default_sources(self, client):
        c, _ = client
        with patch(
            "inbox_server.search_all", return_value={"query": "x", "total": 0, "results": []}
        ) as mock_sa:
            resp = c.post("/search", json={"q": "x"})
        assert resp.status_code == 200
        call_kwargs = mock_sa.call_args
        assert call_kwargs.kwargs.get("sources") == ["all"]


class TestLLMStatusEndpoint:
    def test_llm_status_includes_both_models(self, client):
        c, _ = client
        with (
            patch("services.llm_is_loaded", return_value=False),
            patch("inbox_server.llm_large_is_loaded", return_value=False),
            patch("inbox_server.llm_large_is_loading", return_value=False),
        ):
            resp = c.get("/llm/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "small" in data
        assert "large" in data
        assert "loaded" in data["small"]
        assert "loaded" in data["large"]
        assert "loading" in data["large"]
        assert "model_id" in data["small"]
        assert "model_id" in data["large"]

    def test_llm_status_small_loaded(self, client):
        c, _ = client
        with (
            patch("services.llm_is_loaded", return_value=True),
            patch("inbox_server.llm_large_is_loaded", return_value=False),
            patch("inbox_server.llm_large_is_loading", return_value=False),
        ):
            resp = c.get("/llm/status")
        data = resp.json()
        assert data["small"]["loaded"] is True
        assert data["large"]["loaded"] is False

    def test_llm_status_large_loading(self, client):
        c, _ = client
        with (
            patch("services.llm_is_loaded", return_value=False),
            patch("inbox_server.llm_large_is_loaded", return_value=False),
            patch("inbox_server.llm_large_is_loading", return_value=True),
        ):
            resp = c.get("/llm/status")
        data = resp.json()
        assert data["large"]["loading"] is True


class TestAIEndpoints:
    def test_ai_briefing_returns_structure(self, client):
        c, _ = client
        with (
            patch("inbox_server.calendar_events", return_value=[]),
            patch("inbox_server.reminders_list", return_value=[]),
            patch("inbox_server.gmail_contacts", return_value=[]),
            patch("inbox_server.imsg_contacts", return_value=[]),
            patch("inbox_server.github_notifications", return_value=[]),
            patch("inbox_server.github_pulls", return_value=[]),
            patch(
                "inbox_server.ai_briefing",
                return_value={
                    "events": [],
                    "pending_reminders": [],
                    "unread_counts": {
                        "imessage": 0,
                        "gmail": 0,
                        "github_notifications": 0,
                        "github_prs": 0,
                    },
                    "summary": None,
                },
            ),
        ):
            resp = c.post("/ai/briefing")
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data
        assert "pending_reminders" in data
        assert "unread_counts" in data

    def test_ai_triage_empty_conversations(self, client):
        c, _ = client
        with patch("inbox_server.ai_triage", return_value={}):
            resp = c.post("/ai/triage", json={"conversations": []})
        assert resp.status_code == 200
        assert resp.json() == {}

    def test_ai_triage_with_conversations(self, client):
        c, _ = client
        priorities = {"c1": "urgent", "c2": "normal"}
        with patch("inbox_server.ai_triage", return_value=priorities):
            resp = c.post(
                "/ai/triage",
                json={
                    "conversations": [
                        {
                            "id": "c1",
                            "source": "gmail",
                            "name": "Boss",
                            "snippet": "urgent",
                            "unread": 1,
                        },
                        {
                            "id": "c2",
                            "source": "imessage",
                            "name": "Alice",
                            "snippet": "hi",
                            "unread": 0,
                        },
                    ]
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["c1"] == "urgent"
        assert data["c2"] == "normal"

    def test_ai_summarize_short_thread(self, client):
        c, _ = client
        with patch(
            "inbox_server.ai_summarize",
            return_value={
                "summary": None,
                "key_points": [],
                "action_items": [],
                "decisions": [],
                "skipped": True,
            },
        ):
            resp = c.post(
                "/ai/summarize",
                json={
                    "thread_id": "t1",
                    "messages": [
                        {"sender": "Alice", "body": "hi"},
                    ],
                },
            )
        assert resp.status_code == 200
        assert resp.json()["skipped"] is True

    def test_ai_summarize_long_thread(self, client):
        c, _ = client
        with patch(
            "inbox_server.ai_summarize",
            return_value={
                "summary": "Thread summary here.",
                "key_points": ["Point A"],
                "action_items": ["Do X"],
                "decisions": [],
                "skipped": False,
            },
        ):
            resp = c.post(
                "/ai/summarize",
                json={
                    "thread_id": "t1",
                    "messages": [{"sender": f"U{i}", "body": f"msg {i}"} for i in range(6)],
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"] == "Thread summary here."
        assert "action_items" in data

    def test_ai_extract_actions_returns_actions(self, client):
        c, _ = client
        with patch(
            "inbox_server.ai_extract_actions",
            return_value={
                "actions": [{"text": "Schedule meeting", "deadline": None, "type": "meeting"}]
            },
        ):
            resp = c.post(
                "/ai/extract-actions",
                json={"text": "Please schedule a meeting with Alice tomorrow about Q2 planning."},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "actions" in data
        assert len(data["actions"]) == 1
        assert data["actions"][0]["type"] == "meeting"

    def test_ai_extract_actions_empty_result(self, client):
        c, _ = client
        with patch("inbox_server.ai_extract_actions", return_value={"actions": []}):
            resp = c.post("/ai/extract-actions", json={"text": "No actions in this message."})
        assert resp.status_code == 200
        assert resp.json() == {"actions": []}


class TestLifeOpsReadPrimitives:
    def test_current_location_is_explicitly_read_only(self, client):
        c, _ = client
        with patch("inbox_server.get_current_location", return_value="37.5485,-121.9886"):
            resp = c.get("/location/current")
        assert resp.status_code == 200
        assert resp.json() == {
            "location": "37.5485,-121.9886",
            "available": True,
            "source": "macos_core_location_or_home_address",
            "read_only": True,
        }
