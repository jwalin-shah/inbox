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
