"""Tests for inbox_server.py — FastAPI endpoint tests via TestClient."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from services import CalendarEvent, Contact, DriveFile, GitHubNotification, Msg, Note, Reminder

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    """TestClient with mocked lifespan (no real Google auth / contacts)."""
    import inbox_server

    # Patch lifespan dependencies so real auth doesn't run
    with (
        patch("inbox_server.init_contacts", return_value=0),
        patch("inbox_server.google_auth_all", return_value=({}, {}, {})),
        TestClient(inbox_server.app, raise_server_exceptions=False) as c,
    ):
        # Reset state after lifespan has run (lifespan sets from mocked return)
        inbox_server.state.gmail_services = {}
        inbox_server.state.cal_services = {}
        inbox_server.state.drive_services = {}
        inbox_server.state.conv_cache = {}
        inbox_server.state.events_cache = []
        # Replace ambient/dictation with mocks for testing
        mock_ambient = MagicMock()
        mock_ambient.is_running = False
        mock_dictation = MagicMock()
        mock_dictation.is_running = False
        mock_dictation.available = True
        inbox_server.state.ambient = mock_ambient
        inbox_server.state.dictation = mock_dictation
        yield c


@pytest.fixture
def populated_client(client):
    """Client with some fake data in the conv_cache."""
    import inbox_server

    inbox_server.state.conv_cache = {
        "imessage:42": Contact(
            id="42", name="Alice", source="imessage", guid="iMessage;-;+1234567890"
        ),
        "gmail:msg123": Contact(
            id="msg123",
            name="Bob",
            source="gmail",
            reply_to="bob@example.com",
            thread_id="thread456",
            gmail_account="me@gmail.com",
        ),
    }
    return client


# ── Health ──────────────────────────────────────────────────────────────────


class TestHealth:
    def test_health_returns_ok(self, client):
        with patch("services._github_token", return_value=None):
            resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_health_shows_account_lists(self, client):
        import inbox_server

        inbox_server.state.gmail_services = {"a@gmail.com": MagicMock()}
        with patch("services._github_token", return_value="ghp_xxx"):
            resp = client.get("/health")
        data = resp.json()
        assert "a@gmail.com" in data["gmail_accounts"]
        assert data["github_configured"] is True


# ── Conversations ───────────────────────────────────────────────────────────


class TestConversations:
    @patch("inbox_server.imsg_contacts")
    def test_list_imessage(self, mock_imsg, client):
        mock_imsg.return_value = [
            Contact(
                id="1",
                name="Alice",
                source="imessage",
                snippet="hey",
                last_ts=datetime(2025, 1, 1),
            ),
        ]
        resp = client.get("/conversations", params={"source": "imessage"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Alice"
        assert data[0]["source"] == "imessage"

    @patch("inbox_server.gmail_contacts")
    def test_list_gmail(self, mock_gmail, client):
        import inbox_server

        inbox_server.state.gmail_services = {"me@gmail.com": MagicMock()}
        mock_gmail.return_value = [
            Contact(
                id="msg1",
                name="Bob",
                source="gmail",
                last_ts=datetime(2025, 1, 2),
            ),
        ]
        resp = client.get("/conversations", params={"source": "gmail"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Bob"

    @patch("inbox_server.imsg_contacts")
    def test_list_all_sorts_by_ts(self, mock_imsg, client):
        mock_imsg.return_value = [
            Contact(id="1", name="Old", source="imessage", last_ts=datetime(2024, 1, 1)),
            Contact(id="2", name="New", source="imessage", last_ts=datetime(2025, 6, 1)),
        ]
        resp = client.get("/conversations", params={"source": "imessage"})
        data = resp.json()
        assert data[0]["name"] == "New"


# ── Messages ────────────────────────────────────────────────────────────────


class TestMessages:
    @patch("inbox_server.imsg_thread")
    def test_get_imessage_thread(self, mock_thread, populated_client):
        mock_thread.return_value = [
            Msg(sender="Alice", body="hi", ts=datetime(2025, 1, 1), is_me=False, source="imessage"),
        ]
        resp = populated_client.get("/messages/imessage/42")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["sender"] == "Alice"

    def test_unknown_source_400(self, client):
        resp = client.get("/messages/foobar/123")
        assert resp.status_code == 400

    @patch("inbox_server.imsg_send")
    def test_send_imessage(self, mock_send, populated_client):
        mock_send.return_value = True
        resp = populated_client.post(
            "/messages/send",
            json={"conv_id": "42", "source": "imessage", "text": "hello"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_send_unknown_conv_404(self, client):
        resp = client.post(
            "/messages/send",
            json={"conv_id": "999", "source": "imessage", "text": "hello"},
        )
        assert resp.status_code == 404


# ── Calendar ────────────────────────────────────────────────────────────────


class TestCalendar:
    @patch("inbox_server.calendar_events")
    def test_list_events(self, mock_events, client):
        mock_events.return_value = [
            CalendarEvent(
                summary="Standup",
                start=datetime(2025, 6, 15, 9, 0),
                end=datetime(2025, 6, 15, 9, 30),
            ),
        ]
        resp = client.get("/calendar/events")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["summary"] == "Standup"

    def test_create_event_no_account_404(self, client):
        resp = client.post(
            "/calendar/events",
            json={
                "summary": "Test",
                "start": "2025-06-15T14:00:00",
                "end": "2025-06-15T15:00:00",
            },
        )
        assert resp.status_code == 404

    @patch("inbox_server.parse_quick_event")
    @patch("inbox_server.calendar_create_event")
    def test_quick_event(self, mock_create, mock_parse, client):
        import inbox_server

        inbox_server.state.cal_services = {"me@gmail.com": MagicMock()}
        mock_parse.return_value = {
            "summary": "Lunch",
            "start": datetime(2025, 6, 15, 12, 0),
            "end": datetime(2025, 6, 15, 13, 0),
            "location": "Cafe",
            "all_day": False,
        }
        mock_create.return_value = "evt123"
        resp = client.post("/calendar/events/quick", json={"text": "Lunch 12pm-1pm @ Cafe"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_delete_event_no_account_404(self, client):
        resp = client.delete("/calendar/events/evt123")
        assert resp.status_code == 404


# ── Notes ───────────────────────────────────────────────────────────────────


class TestNotes:
    @patch("inbox_server.notes_list")
    def test_list_notes(self, mock_list, client):
        mock_list.return_value = [
            Note(id="1", title="My Note", snippet="Hello...", modified=datetime(2025, 1, 1)),
        ]
        resp = client.get("/notes")
        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["title"] == "My Note"

    @patch("inbox_server.note_body")
    @patch("inbox_server.notes_list")
    def test_get_note(self, mock_list, mock_body, client):
        mock_list.return_value = [
            Note(id="42", title="Test", snippet="snip", modified=datetime(2025, 1, 1)),
        ]
        mock_body.return_value = "Full body text"
        resp = client.get("/notes/42")
        assert resp.status_code == 200
        assert resp.json()["body"] == "Full body text"

    @patch("inbox_server.notes_list")
    def test_get_note_not_found(self, mock_list, client):
        mock_list.return_value = []
        resp = client.get("/notes/999")
        assert resp.status_code == 404


# ── Ambient ─────────────────────────────────────────────────────────────────


class TestAmbient:
    def test_start_ambient(self, client):
        import inbox_server

        inbox_server.state.ambient.is_running = False
        resp = client.post("/ambient/start")
        assert resp.status_code == 200
        assert resp.json()["status"] == "started"

    def test_start_ambient_already_running(self, client):
        import inbox_server

        inbox_server.state.ambient.is_running = True
        resp = client.post("/ambient/start")
        assert resp.json()["status"] == "already_running"

    def test_stop_ambient(self, client):
        import inbox_server

        inbox_server.state.ambient.is_running = True
        resp = client.post("/ambient/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "stopped"

    def test_ambient_status(self, client):
        import inbox_server

        inbox_server.state.ambient.is_running = False
        inbox_server.state.dictation.is_running = False
        inbox_server.state.dictation.available = True
        resp = client.get("/ambient/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ambient"] is False
        assert data["dictation_available"] is True


# ── Ambient Notes ───────────────────────────────────────────────────────────


class TestAmbientNotes:
    @patch("inbox_server.ambient_notes.list_daily_notes")
    def test_list_ambient_notes(self, mock_list, client):
        mock_list.return_value = [
            {"date": "2025-04-01", "path": "/tmp/daily/2025-04-01.md", "size": 100},
        ]
        resp = client.get("/ambient/notes")
        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["date"] == "2025-04-01"

    @patch("inbox_server.ambient_notes.read_daily_note")
    def test_get_ambient_note(self, mock_read, client):
        mock_read.return_value = "# Today\nSome content"
        resp = client.get("/ambient/notes/2025-04-01")
        assert resp.status_code == 200
        assert resp.json()["content"] == "# Today\nSome content"

    @patch("inbox_server.ambient_notes.read_daily_note")
    def test_get_ambient_note_not_found(self, mock_read, client):
        mock_read.return_value = None
        resp = client.get("/ambient/notes/1999-01-01")
        assert resp.status_code == 404


# ── Dictation ───────────────────────────────────────────────────────────────


class TestDictation:
    def test_start_dictation_no_binary(self, client):
        import inbox_server

        inbox_server.state.dictation.is_running = False
        inbox_server.state.dictation.available = False
        resp = client.post("/dictation/start")
        assert resp.status_code == 400

    def test_stop_dictation_not_running(self, client):
        import inbox_server

        inbox_server.state.dictation.is_running = False
        resp = client.post("/dictation/stop")
        assert resp.json()["status"] == "not_running"


# ── Reminders ───────────────────────────────────────────────────────────────


class TestReminders:
    @patch("inbox_server.reminders_lists")
    def test_list_reminder_lists(self, mock_lists, client):
        mock_lists.return_value = [{"name": "Shopping", "incomplete_count": 3}]
        resp = client.get("/reminders/lists")
        assert resp.status_code == 200
        assert resp.json()[0]["name"] == "Shopping"

    @patch("inbox_server.reminders_list")
    def test_list_reminders(self, mock_list, client):
        mock_list.return_value = [
            Reminder(id="1", title="Buy milk", completed=False, list_name="Shopping"),
        ]
        resp = client.get("/reminders")
        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["title"] == "Buy milk"

    @patch("inbox_server.reminder_complete")
    @patch("inbox_server.reminders_list")
    def test_complete_reminder(self, mock_list, mock_complete, client):
        mock_list.return_value = [
            Reminder(id="99", title="Buy milk", completed=False),
        ]
        mock_complete.return_value = True
        resp = client.post("/reminders/99/complete")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    @patch("inbox_server.reminders_list")
    def test_complete_reminder_not_found(self, mock_list, client):
        mock_list.return_value = []
        resp = client.post("/reminders/999/complete")
        assert resp.status_code == 404


# ── GitHub ──────────────────────────────────────────────────────────────────


class TestGitHub:
    @patch("inbox_server.github_notifications")
    def test_list_notifications(self, mock_notifs, client):
        mock_notifs.return_value = [
            GitHubNotification(
                id="1",
                title="PR Review",
                repo="owner/repo",
                type="PullRequest",
                reason="review_requested",
                unread=True,
                updated_at=datetime(2025, 1, 1),
                url="https://github.com/owner/repo/pull/1",
            ),
        ]
        resp = client.get("/github/notifications")
        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["title"] == "PR Review"
        assert data[0]["unread"] is True


# ── Accounts ────────────────────────────────────────────────────────────────


class TestAccounts:
    def test_list_accounts(self, client):
        import inbox_server

        inbox_server.state.gmail_services = {"a@g.com": MagicMock()}
        with patch("services._github_token", return_value=None):
            resp = client.get("/accounts")
        assert resp.status_code == 200
        data = resp.json()
        assert "a@g.com" in data["gmail"]
        assert data["github"] is False


# ── Drive ───────────────────────────────────────────────────────────────────


class TestDrive:
    @patch("inbox_server.drive_files")
    def test_list_drive_files(self, mock_files, client):
        import inbox_server

        inbox_server.state.drive_services = {"me@gmail.com": MagicMock()}
        mock_files.return_value = [
            DriveFile(
                id="f1",
                name="doc.pdf",
                mime_type="application/pdf",
                modified=datetime(2025, 1, 1),
                size=1024,
            ),
        ]
        resp = client.get("/drive/files")
        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["name"] == "doc.pdf"
        assert data[0]["account"] == "me@gmail.com"

    def test_get_drive_file_no_account_404(self, client):
        resp = client.get("/drive/files/abc123")
        assert resp.status_code == 404

    def test_delete_drive_file_no_account_404(self, client):
        resp = client.delete("/drive/files/abc123")
        assert resp.status_code == 404


# ── Autocomplete ────────────────────────────────────────────────────────────


class TestAutocomplete:
    @patch("inbox_server.services_autocomplete")
    def test_complete_mode(self, mock_autocomplete, client):
        """Test autocomplete endpoint in complete mode."""
        mock_autocomplete.return_value = "sounds good"
        resp = client.post(
            "/autocomplete",
            json={
                "draft": "That ",
                "messages": [{"sender": "Alice", "body": "Wanna meet?"}],
                "mode": "complete",
                "max_tokens": 32,
                "temperature": 0.5,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["completion"] == "sounds good"
        # Verify params passed correctly
        call_args = mock_autocomplete.call_args
        assert call_args[0][0] == "That "
        assert call_args[0][1] == [{"sender": "Alice", "body": "Wanna meet?"}]
        assert call_args[0][2] == 32
        assert call_args[0][3] == 0.5
        assert call_args[0][4] == "complete"

    @patch("inbox_server.services_autocomplete")
    def test_reply_mode(self, mock_autocomplete, client):
        """Test autocomplete endpoint in reply mode."""
        mock_autocomplete.return_value = "Absolutely!"
        resp = client.post(
            "/autocomplete",
            json={
                "messages": [
                    {"sender": "Alice", "body": "Want to meet up?"},
                ],
                "mode": "reply",
                "max_tokens": 32,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["completion"] == "Absolutely!"

    @patch("inbox_server.services_autocomplete")
    def test_autocomplete_with_temperature(self, mock_autocomplete, client):
        """Test that temperature parameter is passed."""
        mock_autocomplete.return_value = "result"
        client.post(
            "/autocomplete",
            json={
                "draft": "Hello",
                "temperature": 0.8,
            },
        )
        call_args = mock_autocomplete.call_args
        assert call_args[0][3] == 0.8

    @patch("inbox_server.services_autocomplete")
    def test_autocomplete_returns_none(self, mock_autocomplete, client):
        """Test that None completions are returned."""
        mock_autocomplete.return_value = None
        resp = client.post(
            "/autocomplete",
            json={"draft": "Hi"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["completion"] is None

    @patch("inbox_server.services_autocomplete")
    def test_autocomplete_error_handling(self, mock_autocomplete, client):
        """Test that errors are caught and returned gracefully."""
        mock_autocomplete.side_effect = RuntimeError("LLM failed")
        resp = client.post(
            "/autocomplete",
            json={"draft": "Hello"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["completion"] is None
        assert "error" in data

    @patch("inbox_server.services_autocomplete")
    def test_autocomplete_defaults(self, mock_ac, client):
        """Test that defaults are applied to request."""
        mock_ac.return_value = None
        client.post(
            "/autocomplete",
            json={"draft": "Hi there"},
        )
        call_args = mock_ac.call_args
        # Should use defaults: max_tokens=32, temp=0.5, mode=complete
        assert call_args[0][2] == 32
        assert call_args[0][3] == 0.5
        assert call_args[0][4] == "complete"


# ── Ambient Note Callback Wiring ────────────────────────────────────────────


class TestAmbientNoteCallback:
    def test_server_state_ambient_callback_calls_save_note(self):
        """Verify that ServerState wires AmbientService on_note to ambient_notes.save_note."""
        with patch("inbox_server.ambient_notes.save_note") as mock_save:
            import inbox_server

            fresh_state = inbox_server.ServerState()
            # Invoke the callback that AmbientService was initialized with
            fresh_state.ambient._on_note("raw transcript text", "summary of note")
            mock_save.assert_called_once_with("raw transcript text", "summary of note")

    def test_server_state_ambient_callback_handles_none_summary(self):
        """Verify callback works when summary is None."""
        with patch("inbox_server.ambient_notes.save_note") as mock_save:
            import inbox_server

            fresh_state = inbox_server.ServerState()
            fresh_state.ambient._on_note("raw transcript only", None)
            mock_save.assert_called_once_with("raw transcript only", None)

    def test_ambient_callback_is_not_noop(self):
        """Verify the callback is not a no-op lambda."""
        import inbox_server

        fresh_state = inbox_server.ServerState()
        # The old code had: on_note=lambda raw, summary: None
        # A real callback should not just return None silently
        callback = fresh_state.ambient._on_note
        # Verify it's not a trivial lambda by checking it references save_note
        assert callback is not None
        # Call it with mock to ensure it actually does something
        with patch("inbox_server.ambient_notes.save_note") as mock_save:
            callback("test", "test summary")
            assert mock_save.called
