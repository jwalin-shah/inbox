"""Tests for inbox.py TUI resilience behaviors."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import httpx
from textual.widgets import Input, Static

import inbox
from inbox import InboxApp, MessageView


class HarnessInboxApp(InboxApp):
    def on_mount(self) -> None:
        """Skip background boot work for deterministic tests."""


def _make_app(client: MagicMock | None = None) -> HarnessInboxApp:
    app = HarnessInboxApp()
    if client is not None:
        app.client = client
    return app


def _status_text(app: InboxApp) -> str:
    return str(app.query_one("#status", Static).content)


def test_poll_interval_reads_env_override(monkeypatch) -> None:
    monkeypatch.setenv("INBOX_POLL_INTERVAL", "2.5")
    assert inbox._poll_interval_from_env() == 2.5


def test_poll_interval_invalid_value_uses_default(monkeypatch) -> None:
    monkeypatch.setenv("INBOX_POLL_INTERVAL", "-1")
    assert inbox._poll_interval_from_env() == inbox.DEFAULT_POLL_INTERVAL

    monkeypatch.setenv("INBOX_POLL_INTERVAL", "abc")
    assert inbox._poll_interval_from_env() == inbox.DEFAULT_POLL_INTERVAL


def test_collect_refresh_data_preserves_other_data_on_partial_failure() -> None:
    client = MagicMock()
    request = httpx.Request("GET", "http://test/calendar/events")
    response = httpx.Response(500, request=request)

    client.conversations.return_value = [{"id": "c1", "source": "imessage", "unread": 0}]
    client.calendar_events.side_effect = httpx.HTTPStatusError(
        "calendar failed", request=request, response=response
    )
    client.notes.return_value = [{"id": "n1", "title": "Fresh note"}]

    app = _make_app(client)
    app.conversations = [{"id": "old", "source": "imessage", "unread": 1}]
    app.events = [{"summary": "Existing event"}]
    app.notes_data = [{"id": "old-note", "title": "Old note"}]

    convos, events, notes, status = app._collect_refresh_data()

    assert convos == [{"id": "c1", "source": "imessage", "unread": 0}]
    assert events == [{"summary": "Existing event"}]
    assert notes == [{"id": "n1", "title": "Fresh note"}]
    assert status == "[red]Calendar refresh failed (HTTP 500)[/]"


def test_collect_poll_data_reports_server_unreachable() -> None:
    client = MagicMock()
    client.conversations.side_effect = httpx.ConnectError(
        "refused", request=httpx.Request("GET", "http://test/conversations")
    )

    app = _make_app(client)
    app.conversations = [{"id": "c1", "source": "imessage", "unread": 0}]
    app.events = [{"summary": "Standup"}]
    app.notes_data = [{"id": "n1"}]

    convos, events, notes, status, changed = app._collect_poll_data()

    assert changed is False
    assert convos == app.conversations
    assert events == app.events
    assert notes == app.notes_data
    assert status == "[red]Server unreachable — press Ctrl+R to retry[/]"


def test_start_polling_uses_configured_interval() -> None:
    app = _make_app(MagicMock())
    timer = MagicMock()
    app.POLL_INTERVAL = 3.25
    app.set_interval = MagicMock(return_value=timer)

    app._start_polling()

    app.set_interval.assert_called_once_with(3.25, app._poll_refresh)
    assert app._poll_timer is timer


def test_action_quit_closes_client_once() -> None:
    async def runner() -> None:
        client = MagicMock()
        app = _make_app(client)

        async with app.run_test() as pilot:
            app._poll_timer = MagicMock()
            app.action_quit()
            await pilot.pause()

        client.close.assert_called_once()
        app._poll_timer = None

    asyncio.run(runner())


def test_boot_failure_shows_status_error() -> None:
    async def runner() -> None:
        app = InboxApp()
        app.client = MagicMock()
        app.client.ensure_server.side_effect = RuntimeError(
            "Server unreachable — press Ctrl+R to retry"
        )

        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            assert "Server unreachable" in _status_text(app)

    asyncio.run(runner())


def test_imessage_send_flow_keeps_optimistic_update_and_reload() -> None:
    async def runner() -> None:
        app = _make_app(MagicMock())
        app.active_conv = {"id": "42", "source": "imessage", "name": "Alice"}
        app._do_send = MagicMock()

        async with app.run_test():
            compose = app.query_one("#compose", Input)
            event = Input.Submitted(compose, "hello there")
            app.on_send(event)

            messages = app.query_one("#messages", MessageView).messages
            assert messages[-1]["body"] == "hello there"
            assert messages[-1]["is_me"] is True
            app._do_send.assert_called_once_with(app.active_conv, "hello there")

    asyncio.run(runner())


# ── Client cleanup on exit ─────────────────────────────────────────────────


def test_on_unmount_closes_client() -> None:
    async def runner() -> None:
        client = MagicMock()
        app = _make_app(client)

        async with app.run_test() as pilot:
            # Simulate a running poll timer
            app._poll_timer = MagicMock()
            await pilot.pause()

        # After run_test exits, on_unmount fires, calling _cleanup_resources
        client.close.assert_called_once()

    asyncio.run(runner())


def test_cleanup_resources_stops_poll_timer() -> None:
    client = MagicMock()
    app = _make_app(client)
    mock_timer = MagicMock()
    app._poll_timer = mock_timer
    app._client_closed = False

    app._cleanup_resources()

    mock_timer.stop.assert_called_once()
    assert app._poll_timer is None
    client.close.assert_called_once()
    assert app._client_closed is True


def test_cleanup_resources_idempotent() -> None:
    client = MagicMock()
    app = _make_app(client)
    app._poll_timer = None
    app._client_closed = False

    app._cleanup_resources()
    assert app._client_closed is True
    client.close.assert_called_once()

    # Second call should be a no-op for client.close
    app._cleanup_resources()
    client.close.assert_called_once()  # still only one call


# ── Error formatting ────────────────────────────────────────────────────────


def test_format_request_error_server_unreachable() -> None:
    exc = httpx.ConnectError("refused", request=httpx.Request("GET", "http://test/"))
    msg = inbox._format_request_error("Refresh", exc)
    assert msg == "Server unreachable — press Ctrl+R to retry"


def test_format_request_error_http_status() -> None:
    request = httpx.Request("GET", "http://test/conversations")
    response = httpx.Response(503, request=request)
    exc = httpx.HTTPStatusError("unavailable", request=request, response=response)
    msg = inbox._format_request_error("Refresh", exc)
    assert msg == "Refresh failed (HTTP 503)"


def test_format_request_error_timeout() -> None:
    exc = httpx.TimeoutException("timed out", request=httpx.Request("GET", "http://test/"))
    msg = inbox._format_request_error("Refresh", exc)
    assert msg == "Server unreachable — press Ctrl+R to retry"


def test_format_request_error_generic_exception() -> None:
    exc = ValueError("bad data")
    msg = inbox._format_request_error("Load", exc)
    assert msg == "Load failed: bad data"


# ── Poll error recovery ─────────────────────────────────────────────────────


def test_poll_had_error_resets_after_successful_poll() -> None:
    client = MagicMock()
    # First call: server unreachable
    client.conversations.side_effect = [
        httpx.ConnectError("refused", request=httpx.Request("GET", "http://test/")),
        [{"id": "c1", "source": "imessage", "unread": 0}],  # Second call: success
    ]
    client.calendar_events.return_value = [{"summary": "Standup"}]
    client.notes.return_value = [{"id": "n1"}]

    app = _make_app(client)
    app.conversations = []
    app.events = []
    app.notes_data = []
    app._poll_had_error = False

    # First poll fails
    convos, events, notes, status, changed = app._collect_poll_data()
    assert status is not None
    assert "unreachable" in status
    assert changed is False

    # Simulate that the error was shown (flag set by _bg_poll)
    app._poll_had_error = True

    # Second poll succeeds — conversations changed so changed=True
    convos2, events2, notes2, status2, changed2 = app._collect_poll_data()
    assert changed2 is True
    assert status2 is None


def test_collect_poll_data_succeeds_with_changed_data() -> None:
    client = MagicMock()
    client.conversations.return_value = [
        {"id": "c1", "source": "imessage", "unread": 1},
        {"id": "c2", "source": "gmail", "unread": 0},
    ]
    client.calendar_events.return_value = [{"summary": "Standup"}]
    client.notes.return_value = [{"id": "n1"}]

    app = _make_app(client)
    app.conversations = [{"id": "c1", "source": "imessage", "unread": 0}]
    app.events = []
    app.notes_data = []

    convos, events, notes, status, changed = app._collect_poll_data()

    assert changed is True
    assert len(convos) == 2
    assert len(events) == 1
    assert len(notes) == 1
    assert status is None


def test_collect_refresh_data_all_succeed() -> None:
    client = MagicMock()
    client.conversations.return_value = [{"id": "c1", "source": "imessage", "unread": 0}]
    client.calendar_events.return_value = [{"summary": "Meeting"}]
    client.notes.return_value = [{"id": "n1", "title": "My Note"}]

    app = _make_app(client)
    convos, events, notes, status = app._collect_refresh_data()

    assert convos == [{"id": "c1", "source": "imessage", "unread": 0}]
    assert events == [{"summary": "Meeting"}]
    assert notes == [{"id": "n1", "title": "My Note"}]
    assert status is None


def test_collect_refresh_data_conversations_fails_preserves_old() -> None:
    client = MagicMock()
    client.conversations.side_effect = httpx.ConnectError(
        "refused", request=httpx.Request("GET", "http://test/")
    )
    client.calendar_events.return_value = [{"summary": "Meeting"}]
    client.notes.return_value = [{"id": "n1"}]

    app = _make_app(client)
    app.conversations = [{"id": "old", "source": "imessage", "unread": 0}]

    convos, events, notes, status = app._collect_refresh_data()

    # Conversations preserved from old data
    assert convos == [{"id": "old", "source": "imessage", "unread": 0}]
    assert events == [{"summary": "Meeting"}]
    assert notes == [{"id": "n1"}]
    assert status is not None
    assert "unreachable" in status


def test_poll_interval_env_not_set_uses_default(monkeypatch) -> None:
    monkeypatch.delenv("INBOX_POLL_INTERVAL", raising=False)
    assert inbox._poll_interval_from_env() == inbox.DEFAULT_POLL_INTERVAL
