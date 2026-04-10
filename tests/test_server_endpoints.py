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
