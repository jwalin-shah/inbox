"""Tests for Apple Reminders connector."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from services import reminder_complete, reminder_create, reminders_list, reminders_lists


class TestRemindersLists:
    def test_returns_lists_with_counts(self, tmp_reminders_db):
        with patch("services.REMINDERS_DIR", tmp_reminders_db):
            lists = reminders_lists()
        names = {item["name"] for item in lists}
        assert "Daily" in names
        assert "Work" in names
        # Daily has 1 incomplete, Work has 1 incomplete
        daily = next(item for item in lists if item["name"] == "Daily")
        assert daily["incomplete_count"] == 1  # "Done task" is completed

    def test_empty_dir_returns_empty(self, tmp_path):
        with patch("services.REMINDERS_DIR", tmp_path / "nonexistent"):
            assert reminders_lists() == []


class TestRemindersList:
    def test_lists_incomplete_by_default(self, tmp_reminders_db):
        with patch("services.REMINDERS_DIR", tmp_reminders_db):
            items = reminders_list()
        titles = [r.title for r in items]
        assert "Buy groceries" in titles
        assert "Ship feature" in titles
        assert "Done task" not in titles

    def test_show_completed(self, tmp_reminders_db):
        with patch("services.REMINDERS_DIR", tmp_reminders_db):
            items = reminders_list(show_completed=True)
        titles = [r.title for r in items]
        assert "Done task" in titles

    def test_filter_by_list(self, tmp_reminders_db):
        with patch("services.REMINDERS_DIR", tmp_reminders_db):
            items = reminders_list(list_name="Work")
        assert len(items) == 1
        assert items[0].title == "Ship feature"
        assert items[0].flagged is True
        assert items[0].priority == 1

    def test_due_dates_parsed(self, tmp_reminders_db):
        with patch("services.REMINDERS_DIR", tmp_reminders_db):
            items = reminders_list()
        for r in items:
            assert r.due_date is not None
            assert r.creation_date is not None

    def test_limit(self, tmp_reminders_db):
        with patch("services.REMINDERS_DIR", tmp_reminders_db):
            items = reminders_list(limit=1)
        assert len(items) == 1

    def test_ordered_by_due_date(self, tmp_reminders_db):
        with patch("services.REMINDERS_DIR", tmp_reminders_db):
            items = reminders_list()
        # "Ship feature" is due sooner (3h) than "Buy groceries" (1d)
        assert items[0].title == "Ship feature"
        assert items[1].title == "Buy groceries"


class TestReminderComplete:
    def test_calls_osascript(self):
        with patch("services.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok")
            result = reminder_complete("Buy groceries")
        assert result is True
        args = mock_run.call_args
        assert args[0][0][0] == "osascript"
        assert "Buy groceries" in args[0][0][2]

    def test_returns_false_on_failure(self):
        with patch("services.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="fail")
            result = reminder_complete("Nonexistent")
        assert result is False

    def test_escapes_quotes_in_title(self):
        with patch("services.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok")
            reminder_complete('Buy "fancy" cheese')
        script = mock_run.call_args[0][0][2]
        assert '\\"fancy\\"' in script


class TestReminderCreate:
    def test_creates_via_osascript(self):
        with patch("services.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok")
            result = reminder_create("New task", list_name="Daily")
        assert result is True
        script = mock_run.call_args[0][0][2]
        assert "New task" in script
        assert "Daily" in script

    def test_with_notes(self):
        with patch("services.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok")
            reminder_create("Task", notes="Some details")
        script = mock_run.call_args[0][0][2]
        assert "Some details" in script
