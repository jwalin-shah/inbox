"""Unit tests for scheduler.py — SchedulerStore CRUD operations."""

from __future__ import annotations

from scheduler import SchedulerStore

# ── Scheduled Messages ──────────────────────────────────────────────────


def test_schedule_message_creates_entry(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    result = store.schedule_message(
        source="gmail",
        conv_id="conv-1",
        text="Hello tomorrow",
        send_at="2026-07-07T09:00:00",
        account="test@gmail.com",
    )
    assert result["source"] == "gmail"
    assert result["conv_id"] == "conv-1"
    assert result["status"] == "pending"
    assert result["account"] == "test@gmail.com"
    assert result["id"] is not None
    assert result["proposal_id"].startswith("sched_prop_")
    assert result["approval_state"] == "proposal_pending"


def test_cancel_scheduled(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    msg = store.schedule_message("gmail", "c1", "text", "2026-07-07T09:00:00")
    result = store.cancel_scheduled(msg["id"])
    assert result is True
    pending = store.list_scheduled("pending")
    assert len(pending) == 0
    cancelled = store.list_scheduled("cancelled")
    assert len(cancelled) == 1
    assert cancelled[0]["id"] == msg["id"]


def test_cancel_scheduled_nonexistent(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    result = store.cancel_scheduled(999)  # nonexistent id — succeeds silently
    assert result is True


def test_mark_sent(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    msg = store.schedule_message("imessage", "c2", "hi", "2026-07-07T09:00:00")
    result = store.mark_sent(msg["id"])
    assert result is True
    sent_msgs = store.list_scheduled("sent")
    assert len(sent_msgs) == 1
    assert sent_msgs[0]["id"] == msg["id"]
    assert sent_msgs[0]["sent_at"] is not None


def test_mark_failed(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    msg = store.schedule_message("gmail", "c3", "fail", "2026-07-07T09:00:00")
    result = store.mark_failed(msg["id"], "send_error: timeout")
    assert result is True
    failed = store.list_scheduled("failed")
    assert len(failed) == 1
    assert failed[0]["error"] == "send_error: timeout"


def test_list_scheduled_empty(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    assert store.list_scheduled("pending") == []


def test_get_due_messages_past(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    store.schedule_message("gmail", "c1", "past", "2020-01-01T00:00:00")
    store.schedule_message("gmail", "c2", "future", "2099-12-31T23:59:59")
    due = store.get_due_messages()
    assert len(due) == 1
    assert due[0]["text"] == "past"


def test_get_due_messages_empty(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    assert store.get_due_messages() == []


# ── Follow-up Reminders ─────────────────────────────────────────────────


def test_create_followup(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    result = store.create_followup(
        source="gmail",
        conv_id="conv-1",
        thread_id="thread-1",
        remind_after="2026-07-08T12:00:00",
        reminder_title="Follow up with Alice",
        reminder_list="Work",
    )
    assert result["source"] == "gmail"
    assert result["reminder_title"] == "Follow up with Alice"
    assert result["status"] == "active"
    assert result["reminder_list"] == "Work"
    assert result["id"] is not None
    assert result["proposal_id"].startswith("sched_prop_")
    assert result["approval_state"] == "proposal_pending"


def test_create_followup_default_list(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    result = store.create_followup(
        source="imessage",
        conv_id="c1",
        thread_id="",
        remind_after="2026-07-08T12:00:00",
        reminder_title="Check in",
    )
    assert result["reminder_list"] == "Reminders"


def test_cancel_followup(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    fup = store.create_followup("gmail", "c1", "t1", "2026-07-08T12:00:00", "Test")
    result = store.cancel_followup(fup["id"])
    assert result is True
    cancelled = store.list_followups("cancelled")
    assert len(cancelled) == 1
    assert cancelled[0]["id"] == fup["id"]


def test_list_followups_by_status(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    store.create_followup("gmail", "c1", "t1", "2026-07-08T12:00:00", "Active 1")
    store.create_followup("gmail", "c2", "t2", "2026-07-09T12:00:00", "Active 2")
    fup3 = store.create_followup("imessage", "c3", "t3", "2026-07-10T12:00:00", "Will cancel")
    store.cancel_followup(fup3["id"])
    active = store.list_followups("active")
    assert len(active) == 2
    cancelled = store.list_followups("cancelled")
    assert len(cancelled) == 1


def test_list_followups_empty(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    assert store.list_followups("active") == []


def test_mark_followup_fired(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    fup = store.create_followup("gmail", "c1", "t1", "2026-07-08T12:00:00", "Test")
    result = store.mark_followup_fired(fup["id"])
    assert result is True
    fired = store.list_followups("fired")
    assert len(fired) == 1
    assert fired[0]["fired_at"] is not None


def test_mark_followup_replied(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    fup = store.create_followup("gmail", "c1", "t1", "2026-07-08T12:00:00", "Test")
    result = store.mark_followup_replied(fup["id"])
    assert result is True
    replied = store.list_followups("replied")
    assert len(replied) == 1


def test_get_due_followups(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    store.create_followup("gmail", "c1", "t1", "2020-01-01T00:00:00", "Past")
    store.create_followup("imessage", "c2", "t2", "2099-12-31T23:59:59", "Future")
    due = store.get_due_followups()
    assert len(due) == 1
    assert due[0]["reminder_title"] == "Past"


def test_get_due_followups_empty(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    assert store.get_due_followups() == []


# ── Task↔Message Links ─────────────────────────────────────────────────


def test_link_task(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    result = store.link_task(
        task_id="task-1",
        task_source="google_tasks",
        message_id="msg-1",
        message_source="gmail",
        thread_id="thread-1",
        account="test@gmail.com",
    )
    assert result["id"] is not None
    assert result["task_id"] == "task-1"
    assert result["task_source"] == "google_tasks"
    assert result["message_id"] == "msg-1"
    assert result["message_source"] == "gmail"
    assert result["thread_id"] == "thread-1"
    assert result["account"] == "test@gmail.com"
    assert result["created_at"] != ""


def test_link_task_defaults(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    result = store.link_task(
        task_id="rem-1",
        task_source="reminders",
        message_id="conv-1",
        message_source="imessage",
    )
    assert result["thread_id"] == ""
    assert result["account"] == ""


def test_unlink_task(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    link = store.link_task("task-1", "google_tasks", "msg-1", "gmail")
    result = store.unlink_task(link["id"])
    assert result is True
    found = store.links_for_message("msg-1", "gmail")
    assert found == []


def test_unlink_task_nonexistent(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    result = store.unlink_task(999)  # nonexistent — succeeds silently
    assert result is True


def test_links_for_message(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    store.link_task("task-1", "google_tasks", "msg-1", "gmail")
    store.link_task("task-2", "google_tasks", "msg-1", "gmail")
    store.link_task("task-3", "reminders", "msg-2", "imessage")
    links = store.links_for_message("msg-1", "gmail")
    assert len(links) == 2
    assert {link["task_id"] for link in links} == {"task-1", "task-2"}


def test_links_for_message_empty(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    assert store.links_for_message("nonexistent", "gmail") == []


def test_links_for_task(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    store.link_task("task-1", "google_tasks", "msg-1", "gmail")
    store.link_task("task-1", "google_tasks", "msg-2", "imessage")
    store.link_task("task-2", "google_tasks", "msg-3", "gmail")
    links = store.links_for_task("task-1", "google_tasks")
    assert len(links) == 2
    assert {link["message_id"] for link in links} == {"msg-1", "msg-2"}


def test_links_for_task_empty(tmp_path):
    store = SchedulerStore(tmp_path / "scheduler.sqlite3")
    assert store.links_for_task("nonexistent", "reminders") == []
