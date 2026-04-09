"""Tests for the new server endpoints (Reminders, GitHub, Drive)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    """Create a test client with mocked startup."""
    with (
        patch("inbox_server.init_contacts", return_value=0),
        patch("inbox_server.google_auth_all", return_value=({}, {}, {})),
    ):
        from inbox_server import app, state

        state.gmail_services = {}
        state.cal_services = {}
        state.drive_services = {}
        with TestClient(app) as c:
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

        mock_items = [Reminder(id="1", title="Buy milk", completed=False)]
        with (
            patch("inbox_server.reminders_list", return_value=mock_items),
            patch("inbox_server.reminder_complete", return_value=True),
        ):
            resp = c.post("/reminders/1/complete")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_complete_nonexistent_reminder(self, client):
        c, _ = client
        with patch("inbox_server.reminders_list", return_value=[]):
            resp = c.post("/reminders/999/complete")
        assert resp.status_code == 404


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
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Folder"

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
        resp = c.get("/drive/files/f1")
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
