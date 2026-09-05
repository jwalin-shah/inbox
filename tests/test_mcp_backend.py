"""Tests for mcp_backend.py — InboxBackend HTTP client."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mcp_backend import (
    DEFAULT_SERVER_URL,
    SERVER_TOKEN_ENV,
    SERVER_URL_ENV,
    InboxBackend,
    InboxBackendError,
)

# ---------------------------------------------------------------------------
# helper: build an AsyncMock httpx.AsyncClient that returns the given response
# ---------------------------------------------------------------------------


def _make_async_client_mock(response: MagicMock | None = None, exc: BaseException | None = None) -> AsyncMock:
    """Return an AsyncMock that acts as an async context manager yielding itself.

    If *response* is given the mocked ``client.request`` returns it.
    If *exc* is given ``__aenter__`` raises it instead (simulating connect errors).
    """
    client = AsyncMock()
    if exc is not None:
        client.__aenter__.side_effect = exc
    else:
        client.__aenter__.return_value = client
        client.request.return_value = response if response is not None else _json_response(200, {"ok": True})
    client.__aexit__.return_value = None
    return client


def _json_response(status_code: int, data: object, text: str = "") -> MagicMock:
    """Return a MagicMock httpx.Response with .status_code, .json(), and .text."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = text or str(data)
    return resp


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestInboxBackendInit:
    """Tests for InboxBackend.__init__ URL and token resolution."""

    def test_default_base_url(self) -> None:
        """Without env vars or explicit URL, use DEFAULT_SERVER_URL."""
        backend = InboxBackend()
        assert backend.base_url == DEFAULT_SERVER_URL

    def test_explicit_base_url(self) -> None:
        """Explicit base_url overrides everything."""
        backend = InboxBackend(base_url="http://custom:9999")
        assert backend.base_url == "http://custom:9999"

    def test_explicit_base_url_strips_trailing_slash(self) -> None:
        """Trailing slash on explicit URL is stripped."""
        backend = InboxBackend(base_url="http://custom:9999/")
        assert backend.base_url == "http://custom:9999"

    def test_env_var_base_url(self) -> None:
        """INBOX_SERVER_URL env var is used when no explicit URL given."""
        with patch.dict(os.environ, {SERVER_URL_ENV: "http://env:8888"}, clear=True):
            backend = InboxBackend()
            assert backend.base_url == "http://env:8888"

    def test_env_var_base_url_strips_slash(self) -> None:
        """Trailing slash in env var URL is stripped."""
        with patch.dict(os.environ, {SERVER_URL_ENV: "http://env:8888/"}, clear=True):
            backend = InboxBackend()
            assert backend.base_url == "http://env:8888"

    def test_explicit_trumps_env(self) -> None:
        """Explicit base_url takes precedence over env var."""
        with patch.dict(os.environ, {SERVER_URL_ENV: "http://env:8888"}):
            backend = InboxBackend(base_url="http://explicit:7777")
            assert backend.base_url == "http://explicit:7777"

    def test_explicit_token(self) -> None:
        """Explicit token is used directly."""
        backend = InboxBackend(token="my-token")
        assert backend.token == "my-token"

    def test_token_from_env(self) -> None:
        """Token is read from INBOX_SERVER_TOKEN env var."""
        with patch.dict(os.environ, {SERVER_TOKEN_ENV: "env-token"}, clear=True):
            backend = InboxBackend()
            assert backend.token == "env-token"

    def test_token_env_strips_whitespace(self) -> None:
        """Token from env is stripped of surrounding whitespace."""
        with patch.dict(os.environ, {SERVER_TOKEN_ENV: "  env-token  "}, clear=True):
            backend = InboxBackend()
            assert backend.token == "env-token"

    def test_token_env_empty_defaults_to_empty_string(self) -> None:
        """Empty env var produces empty string token."""
        with patch.dict(os.environ, {}, clear=True):
            backend = InboxBackend()
            assert backend.token == ""

    def test_explicit_token_trumps_env(self) -> None:
        """Explicit token takes precedence over env var."""
        with patch.dict(os.environ, {SERVER_TOKEN_ENV: "env-token"}):
            backend = InboxBackend(token="explicit-token")
            assert backend.token == "explicit-token"

    def test_explicit_token_none_uses_env(self) -> None:
        """None token falls back to env var."""
        with patch.dict(os.environ, {SERVER_TOKEN_ENV: "env-token"}, clear=True):
            backend = InboxBackend(token=None)  # type: ignore[arg-type]
            assert backend.token == "env-token"


# ---------------------------------------------------------------------------
# _headers
# ---------------------------------------------------------------------------


class TestInboxBackendHeaders:
    """Tests for InboxBackend._headers()."""

    def test_headers_no_token(self) -> None:
        """Without a token only the Accept header is set."""
        backend = InboxBackend(token="")
        headers = backend._headers()
        assert headers == {"Accept": "application/json"}

    def test_headers_with_token(self) -> None:
        """With a token, Authorization Bearer is added."""
        backend = InboxBackend(token="secret")
        headers = backend._headers()
        assert headers == {"Accept": "application/json", "Authorization": "Bearer secret"}


# ---------------------------------------------------------------------------
# _request
# ---------------------------------------------------------------------------


class TestInboxBackendRequest:
    """Tests for the core _request() method."""

    def test_successful_get(self) -> None:
        """Successful GET returns parsed JSON body."""
        data = {"status": "ok", "version": "1.0"}
        resp = _json_response(200, data)
        client_mock = _make_async_client_mock(response=resp)

        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend._request("GET", "/health"))
            assert result == data

    def test_successful_post_with_json_body(self) -> None:
        """POST with JSON body passes json= to client.request."""
        data = {"id": 1}
        resp = _json_response(201, data)
        client_mock = _make_async_client_mock(response=resp)

        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend._request("POST", "/tasks", json={"title": "X"}))
            assert result == data
            client_mock.request.assert_called_once()
            _, kwargs = client_mock.request.call_args
            assert kwargs["json"] == {"title": "X"}

    def test_successful_get_with_params(self) -> None:
        """GET with query params passes params= to client.request."""
        resp = _json_response(200, [])
        client_mock = _make_async_client_mock(response=resp)

        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend._request("GET", "/items", params={"limit": 10}))
            assert result == []
            client_mock.request.assert_called_once()
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"limit": 10}

    def test_http_error_connection_refused(self) -> None:
        """Connection errors raise InboxBackendError with descriptive message."""
        client_mock = _make_async_client_mock(exc=httpx.ConnectError("Connection refused"))

        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            with pytest.raises(InboxBackendError, match="Unable to reach inbox server"):
                _run(backend._request("GET", "/health"))

    def test_http_error_timeout(self) -> None:
        """Timeout errors raise InboxBackendError."""
        client_mock = _make_async_client_mock(exc=httpx.ReadTimeout("timed out"))

        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://down:9999")
            with pytest.raises(InboxBackendError, match="Unable to reach inbox server.*http://down:9999"):
                _run(backend._request("GET", "/data"))

    def test_400_with_json_detail(self) -> None:
        """4xx with JSON detail extracts the detail field."""
        resp = _json_response(400, {"detail": "Missing field 'title'"}, text='{"detail": "Missing field \'title\'"}')
        client_mock = _make_async_client_mock(response=resp)

        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            with pytest.raises(InboxBackendError, match="POST /tasks failed: Missing field 'title'"):
                _run(backend._request("POST", "/tasks", json={"bad": 1}))

    def test_400_without_json_detail_falls_back_to_text(self) -> None:
        """When response.json() raises, the raw text is used in the error."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 400
        resp.text = "Bad Request"
        resp.json.side_effect = ValueError("not json")
        client_mock = _make_async_client_mock(response=resp)

        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            with pytest.raises(InboxBackendError, match="GET /items failed: Bad Request"):
                _run(backend._request("GET", "/items"))

    def test_500_server_error(self) -> None:
        """5xx errors are surfaced with status text."""
        resp = _json_response(500, {}, text="Internal Server Error")
        client_mock = _make_async_client_mock(response=resp)

        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            with pytest.raises(InboxBackendError, match="GET /health failed:"):
                _run(backend._request("GET", "/health"))

    def test_403_with_detail(self) -> None:
        """403 responses include the detail message."""
        resp = _json_response(403, {"detail": "Forbidden"}, text='{"detail": "Forbidden"}')
        client_mock = _make_async_client_mock(response=resp)

        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            with pytest.raises(InboxBackendError, match="DELETE /x failed: Forbidden"):
                _run(backend._request("DELETE", "/x"))

    def test_base_url_included_in_error(self) -> None:
        """Error messages include the base_url for debuggability."""
        client_mock = _make_async_client_mock(exc=httpx.ConnectError("refused"))

        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://special:5555")
            with pytest.raises(InboxBackendError, match="http://special:5555"):
                _run(backend._request("GET", "/health"))

    def test_timeout_passed_to_client(self) -> None:
        """The httpx.AsyncClient is constructed with timeout=30.0."""
        resp = _json_response(200, {"ok": True})
        client_mock = _make_async_client_mock(response=resp)

        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend._request("GET", "/health"))
            # Check that AsyncClient was called with timeout=30.0
            call_args, call_kwargs = httpx.AsyncClient.call_args  # type: ignore[attr-defined]
            assert call_kwargs.get("timeout") == 30.0
            assert call_kwargs.get("base_url") == "http://test:1234"


# ---------------------------------------------------------------------------
# Wrapper methods — exercised through real _request with mocked httpx
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_returns_json(self) -> None:
        data = {"status": "ok"}
        client_mock = _make_async_client_mock(response=_json_response(200, data))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.health())
            assert result == data
        client_mock.request.assert_called_once_with("GET", "/health", params=None, json=None, headers=backend._headers())


class TestListInboxThreads:
    def test_default_params(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, []))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.list_inbox_threads())
            assert result == []
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"label": "INBOX", "limit": 20, "account": ""}

    def test_custom_limit_and_account(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, [{"id": "1"}]))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.list_inbox_threads(limit=5, account="me@example.com"))
            assert result == [{"id": "1"}]
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"label": "INBOX", "limit": 5, "account": "me@example.com"}


class TestSearchEmail:
    def test_minimal_search(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, []))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.search_email("test"))
            assert result == []
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"]["q"] == "test"
            assert kwargs["params"]["limit"] == 20
            assert kwargs["params"]["account"] == ""

    def test_full_params(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, [{"id": "1"}]))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.search_email("urgent", limit=10, account="a@b.com", label="INBOX"))
            assert result == [{"id": "1"}]
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"q": "urgent", "limit": 10, "account": "a@b.com", "label": "INBOX"}


class TestGetEmailThread:
    def test_get_thread(self) -> None:
        data = [{"id": "msg1", "snippet": "hello"}]
        client_mock = _make_async_client_mock(response=_json_response(200, data))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.get_email_thread("msg1"))
            assert result == data
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"thread_id": ""}

    def test_get_thread_with_thread_id(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, []))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.get_email_thread("msg1", thread_id="th1"))
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"thread_id": "th1"}


class TestSendEmailReply:
    def test_minimal_reply(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, {"sent": True}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.send_email_reply(msg_id="m1", body="hi"))
            assert result == {"sent": True}
            _, kwargs = client_mock.request.call_args
            assert kwargs["json"] == {
                "msg_id": "m1",
                "body": "hi",
                "thread_id": "",
                "to": "",
                "subject": "",
                "message_id_header": "",
                "account": "",
            }

    def test_full_reply(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, {"sent": True}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(
                backend.send_email_reply(
                    msg_id="m1",
                    body="reply",
                    thread_id="th1",
                    to="a@b.com",
                    subject="Re: Hello",
                    message_id_header="<msg@mail>",
                    account="me@x.com",
                )
            )
            _, kwargs = client_mock.request.call_args
            assert kwargs["json"]["thread_id"] == "th1"
            assert kwargs["json"]["to"] == "a@b.com"
            assert kwargs["json"]["subject"] == "Re: Hello"
            assert kwargs["json"]["message_id_header"] == "<msg@mail>"
            assert kwargs["json"]["account"] == "me@x.com"


class TestArchiveAndMarkEmail:
    def test_archive_email(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, {"ok": True}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.archive_email_thread("m1"))
            assert result == {"ok": True}
            client_mock.request.assert_called_once_with(
                "POST", "/messages/gmail/m1/archive", params=None, json=None, headers=backend._headers()
            )

    def test_mark_email_read(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, {"ok": True}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.mark_email_read("m2"))
            client_mock.request.assert_called_once_with(
                "POST", "/messages/gmail/m2/read", params=None, json=None, headers=backend._headers()
            )


class TestIMessageMethods:
    def test_list_message_threads(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, [{"id": "1"}]))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.list_message_threads(limit=30))
            assert result == [{"id": "1"}]
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"source": "imessage", "limit": 30}

    def test_get_message_thread(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, [{"text": "hi"}]))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.get_message_thread("conv1", limit=10))
            assert result == [{"text": "hi"}]
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"limit": 10}

    def test_send_imessage(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, {"sent": True}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.send_imessage("conv1", "hello"))
            _, kwargs = client_mock.request.call_args
            assert kwargs["json"] == {"conv_id": "conv1", "source": "imessage", "text": "hello"}


class TestNotesMethods:
    def test_list_notes(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, [{"id": "n1"}]))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.list_notes(limit=10))
            assert result == [{"id": "n1"}]
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"limit": 10}

    def test_get_note(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, {"id": "n2", "body": "text"}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.get_note("n2"))
            assert result == {"id": "n2", "body": "text"}
            client_mock.request.assert_called_once_with(
                "GET", "/notes/n2", params=None, json=None, headers=backend._headers()
            )


class TestRemindersMethods:
    def test_list_reminders_defaults(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, []))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.list_reminders())
            assert result == []
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"list_name": None, "show_completed": "false", "limit": 100}

    def test_list_reminders_filtered(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, []))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.list_reminders(list_name="Work", show_completed=True, limit=5))
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"list_name": "Work", "show_completed": "true", "limit": 5}

    def test_create_reminder(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(201, {"id": "r1"}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.create_reminder(title="Buy milk"))
            assert result == {"id": "r1"}
            _, kwargs = client_mock.request.call_args
            assert kwargs["json"] == {
                "title": "Buy milk",
                "list_name": "Reminders",
                "due_date": "",
                "notes": "",
                "priority": 0,
                "flagged": False,
            }

    def test_create_reminder_full(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(201, {"id": "r2"}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(
                backend.create_reminder(
                    title="Meeting",
                    list_name="Work",
                    due_date="2026-07-10",
                    notes="Prep slides",
                    priority=1,
                    flagged=True,
                )
            )
            _, kwargs = client_mock.request.call_args
            assert kwargs["json"]["priority"] == 1
            assert kwargs["json"]["flagged"] is True

    def test_complete_reminder(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, {"ok": True}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.complete_reminder("r1"))
            client_mock.request.assert_called_once_with(
                "POST", "/reminders/r1/complete", params=None, json=None, headers=backend._headers()
            )

    def test_uncomplete_reminder(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, {"ok": True}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.uncomplete_reminder("r1"))
            client_mock.request.assert_called_once_with(
                "POST", "/reminders/r1/uncomplete", params=None, json=None, headers=backend._headers()
            )


class TestCalendarMethods:
    def test_list_upcoming_calendar_events(self) -> None:
        events = [{"event_id": "evt1", "location": "Bridgeport"}]
        client_mock = _make_async_client_mock(response=_json_response(200, events))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.list_upcoming_calendar_events(days=3, limit=5))
            assert result == events
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"days": 3, "limit": 5}

    def test_list_contacts(self) -> None:
        contacts = [{"id": "alex@example.com", "addresses": [{"formatted": "1 Main St"}]}]
        client_mock = _make_async_client_mock(response=_json_response(200, contacts))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.list_contacts(limit=5))
            assert result == contacts
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"q": "", "limit": 5}

    def test_list_project_records_unwraps_projection(self) -> None:
        projection = {
            "schema_version": "inbox.project_records.v1",
            "records": [
                {
                    "project": "Life Ops",
                    "source_ref": {"source": "google_sheets", "id": "sheet:row:2"},
                }
            ],
        }
        client_mock = _make_async_client_mock(response=_json_response(200, projection))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.list_project_records(limit=5))
            assert result == projection["records"]
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"limit": 5}

    def test_master_ops_queues_returns_projection(self) -> None:
        projection = {
            "schema_version": "inbox.master_ops_queues.v1",
            "read_only": True,
            "queues": {"email_actions": {"records": [{"email_id": "E-0001"}]}} ,
        }
        client_mock = _make_async_client_mock(response=_json_response(200, projection))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.master_ops_queues(limit=5))
            assert result == projection
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"limit": 5}

    def test_lifeops_sheet_projection_returns_tabs(self) -> None:
        projection = {
            "schema_version": "inbox.lifeops_sheet.v1",
            "read_only": True,
            "tabs": {"people": {"records": [{"person_id": "P-1"}]}},
        }
        client_mock = _make_async_client_mock(response=_json_response(200, projection))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.lifeops_sheet_projection(limit=5))
            assert result == projection
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"limit": 5}


class TestTaskMethods:
    def test_list_task_lists_no_account(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, []))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.list_task_lists())
            assert result == []
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {}

    def test_list_task_lists_with_account(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, []))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.list_task_lists(account="me@x.com"))
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"account": "me@x.com"}

    def test_list_tasks_defaults(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, []))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.list_tasks())
            assert result == []
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"list_id": "@default", "show_completed": "false", "limit": 100}

    def test_list_tasks_with_account(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, []))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.list_tasks(account="me@x.com"))
            _, kwargs = client_mock.request.call_args
            assert "account" in kwargs["params"]
            assert kwargs["params"]["account"] == "me@x.com"

    def test_create_task_minimal(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(201, {"id": "t1"}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.create_task(title="Write tests"))
            assert result == {"id": "t1"}
            _, kwargs = client_mock.request.call_args
            assert kwargs["json"] == {"title": "Write tests", "list_id": "@default", "due": "", "notes": ""}
            assert kwargs["params"] == {}

    def test_create_task_with_account(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(201, {"id": "t2"}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.create_task(title="X", account="me@x.com"))
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"account": "me@x.com"}

    def test_create_task_full(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(201, {"id": "t3"}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.create_task(title="X", list_id="custom", due="2026-07-10", notes="details"))
            _, kwargs = client_mock.request.call_args
            assert kwargs["json"] == {"title": "X", "list_id": "custom", "due": "2026-07-10", "notes": "details"}

    def test_complete_task_no_account(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, {"ok": True}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.complete_task("t1"))
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"list_id": "@default"}

    def test_complete_task_with_account(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, {"ok": True}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.complete_task("t1", account="me@x.com"))
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"list_id": "@default", "account": "me@x.com"}

    def test_update_task_minimal(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, {"ok": True}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.update_task("t1"))
            _, kwargs = client_mock.request.call_args
            assert kwargs["json"] == {}
            assert kwargs["params"] == {"list_id": "@default"}

    def test_update_task_full(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, {"ok": True}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(
                backend.update_task(
                    "t1",
                    list_id="custom",
                    title="New title",
                    due="2026-08-01",
                    notes="updated",
                    account="me@x.com",
                )
            )
            _, kwargs = client_mock.request.call_args
            assert kwargs["json"] == {"title": "New title", "due": "2026-08-01", "notes": "updated"}
            assert kwargs["params"] == {"list_id": "custom", "account": "me@x.com"}

    def test_delete_task_no_account(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, {"ok": True}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.delete_task("t1"))
            client_mock.request.assert_called_once_with(
                "DELETE", "/tasks/t1", params={"list_id": "@default"}, json=None, headers=backend._headers()
            )

    def test_delete_task_with_account(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, {"ok": True}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.delete_task("t1", account="me@x.com"))
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"list_id": "@default", "account": "me@x.com"}


class TestTravelMethods:
    def test_departure_times_defaults(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, []))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.departure_times())
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"mode": "driving", "buffer_minutes": 10, "lookahead_hours": 24}

    def test_departure_times_with_origin(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, []))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.departure_times(origin="Home"))
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"]["origin"] == "Home"

    def test_travel_time(self) -> None:
        data = {"duration": "15 mins"}
        client_mock = _make_async_client_mock(response=_json_response(200, data))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.travel_time("Home", "Office", mode="walking"))
            assert result == data
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"origin": "Home", "destination": "Office", "mode": "walking"}


class TestWhatsappMethods:
    def test_whatsapp_contacts(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, []))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.whatsapp_contacts(limit=10))
            assert result == []
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"limit": 10}

    def test_whatsapp_messages(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, [{"text": "hi"}]))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.whatsapp_messages("Alice", limit=25))
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"limit": 25}


class TestScheduledMethods:
    def test_list_scheduled(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, []))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.list_scheduled())
            assert result == []
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"status": "pending"}

    def test_list_scheduled_status(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, []))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.list_scheduled(status="sent"))
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"status": "sent"}

    def test_schedule_message(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(201, {"id": 1}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(
                backend.schedule_message(
                    source="imessage",
                    conv_id="c1",
                    text="later",
                    send_at="2026-07-07T10:00:00",
                    account="me@x.com",
                )
            )
            assert result == {"id": 1}
            _, kwargs = client_mock.request.call_args
            assert kwargs["json"] == {
                "source": "imessage",
                "conv_id": "c1",
                "text": "later",
                "send_at": "2026-07-07T10:00:00",
                "account": "me@x.com",
            }

    def test_cancel_scheduled(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, {"ok": True}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.cancel_scheduled(42))
            client_mock.request.assert_called_once_with(
                "DELETE", "/scheduled/42", params=None, json=None, headers=backend._headers()
            )


class TestFollowupMethods:
    def test_list_followups_defaults(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, []))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.list_followups())
            assert result == []
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"status": "active"}

    def test_create_followup_minimal(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(201, {"id": 1}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(
                backend.create_followup(
                    source="gmail",
                    conv_id="c1",
                    remind_after="2h",
                    reminder_title="Follow up",
                )
            )
            assert result == {"id": 1}
            _, kwargs = client_mock.request.call_args
            assert kwargs["json"]["thread_id"] == ""
            assert kwargs["json"]["reminder_list"] == "Reminders"

    def test_create_followup_full(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(201, {"id": 2}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(
                backend.create_followup(
                    source="gmail",
                    conv_id="c2",
                    remind_after="4h",
                    reminder_title="Check in",
                    thread_id="th1",
                    reminder_list="Work",
                )
            )
            _, kwargs = client_mock.request.call_args
            assert kwargs["json"]["thread_id"] == "th1"
            assert kwargs["json"]["reminder_list"] == "Work"

    def test_cancel_followup(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, {"ok": True}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.cancel_followup(7))
            client_mock.request.assert_called_once_with(
                "DELETE", "/followups/7", params=None, json=None, headers=backend._headers()
            )


class TestTaskLinksMethods:
    def test_list_task_links_empty(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, []))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.list_task_links())
            assert result == []
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {}

    def test_list_task_links_by_message(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, []))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.list_task_links(message_id="m1", message_source="gmail"))
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"message_id": "m1", "message_source": "gmail"}

    def test_list_task_links_by_task(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, []))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.list_task_links(task_id="t1", task_source="google_tasks"))
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"task_id": "t1", "task_source": "google_tasks"}

    def test_link_task_to_message_minimal(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(201, {"id": 1}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(
                backend.link_task_to_message(
                    task_id="t1",
                    task_source="google_tasks",
                    message_id="m1",
                    message_source="gmail",
                )
            )
            assert result == {"id": 1}
            _, kwargs = client_mock.request.call_args
            assert kwargs["json"]["thread_id"] == ""
            assert kwargs["json"]["account"] == ""

    def test_link_task_to_message_full(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(201, {"id": 2}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(
                backend.link_task_to_message(
                    task_id="t2",
                    task_source="google_tasks",
                    message_id="m2",
                    message_source="gmail",
                    thread_id="th1",
                    account="me@x.com",
                )
            )
            _, kwargs = client_mock.request.call_args
            assert kwargs["json"]["thread_id"] == "th1"
            assert kwargs["json"]["account"] == "me@x.com"

    def test_unlink_task(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, {"ok": True}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.unlink_task(3))
            client_mock.request.assert_called_once_with(
                "DELETE", "/tasks/links/3", params=None, json=None, headers=backend._headers()
            )


class TestCreateTaskFromMessage:
    def test_minimal(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(201, {"id": "t1"}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(
                backend.create_task_from_message(
                    message_id="m1",
                    message_source="gmail",
                    title="Review PR",
                )
            )
            assert result == {"id": "t1"}
            _, kwargs = client_mock.request.call_args
            assert kwargs["json"] == {
                "message_id": "m1",
                "message_source": "gmail",
                "title": "Review PR",
                "task_type": "google_tasks",
                "list_id": "@default",
                "list_name": "Reminders",
                "notes": "",
                "thread_id": "",
                "account": "",
            }

    def test_full(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(201, {"id": "t2"}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(
                backend.create_task_from_message(
                    message_id="m2",
                    message_source="gmail",
                    title="Write docs",
                    task_type="apple_reminders",
                    list_id="custom",
                    list_name="Work",
                    notes="urgent",
                    thread_id="th1",
                    account="me@x.com",
                )
            )
            _, kwargs = client_mock.request.call_args
            json_data = kwargs["json"]
            assert json_data["task_type"] == "apple_reminders"
            assert json_data["list_id"] == "custom"
            assert json_data["list_name"] == "Work"
            assert json_data["notes"] == "urgent"
            assert json_data["thread_id"] == "th1"
            assert json_data["account"] == "me@x.com"


class TestSearchAll:
    def test_minimal_search(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, {"results": []}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.search_all("hello"))
            assert result == {"results": []}
            _, kwargs = client_mock.request.call_args
            assert kwargs["json"] == {"q": "hello", "sources": ["all"], "limit": 50}

    def test_with_sources(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, {"results": []}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.search_all("hello", sources=["gmail", "imessage"], limit=10))
            _, kwargs = client_mock.request.call_args
            assert kwargs["json"]["sources"] == ["gmail", "imessage"]
            assert kwargs["json"]["limit"] == 10

    def test_with_all_filters(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, {"results": []}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(
                backend.search_all(
                    "invoice",
                    from_addr="billing@co.com",
                    before="2026-06-01",
                    after="2026-01-01",
                    has_attachment=True,
                    is_unread=True,
                )
            )
            _, kwargs = client_mock.request.call_args
            json_data = kwargs["json"]
            assert json_data["from_addr"] == "billing@co.com"
            assert json_data["before"] == "2026-06-01"
            assert json_data["after"] == "2026-01-01"
            assert json_data["has_attachment"] is True
            assert json_data["is_unread"] is True

    def test_without_optional_filters(self) -> None:
        """Empty from_addr/before/after should not appear in payload."""
        client_mock = _make_async_client_mock(response=_json_response(200, {"results": []}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.search_all("test", from_addr="", before="", after="", has_attachment=False, is_unread=False))
            _, kwargs = client_mock.request.call_args
            json_data = kwargs["json"]
            assert "from_addr" not in json_data
            assert "before" not in json_data
            assert "after" not in json_data
            assert "has_attachment" not in json_data
            assert "is_unread" not in json_data


class TestGmailLabelMethods:
    def test_list_gmail_labels(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, [{"id": "INBOX"}]))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.list_gmail_labels())
            assert result == [{"id": "INBOX"}]
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"account": ""}

    def test_list_gmail_labels_with_account(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, []))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.list_gmail_labels(account="me@x.com"))
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"account": "me@x.com"}

    def test_batch_modify_emails(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, {"ok": True}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(
                backend.batch_modify_emails(
                    msg_ids=["m1", "m2"],
                    add_labels=["Label1"],
                    remove_labels=["Label2"],
                    account="me@x.com",
                )
            )
            assert result == {"ok": True}
            _, kwargs = client_mock.request.call_args
            assert kwargs["json"] == {
                "msg_ids": ["m1", "m2"],
                "add_label_ids": ["Label1"],
                "remove_label_ids": ["Label2"],
                "account": "me@x.com",
            }

    def test_batch_modify_emails_none_labels(self) -> None:
        """None add_labels/remove_labels are coerced to empty lists."""
        client_mock = _make_async_client_mock(response=_json_response(200, {"ok": True}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            _run(backend.batch_modify_emails(msg_ids=["m1"]))
            _, kwargs = client_mock.request.call_args
            assert kwargs["json"]["add_label_ids"] == []
            assert kwargs["json"]["remove_label_ids"] == []

    def test_create_gmail_filter(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(201, {"id": "f1"}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(
                backend.create_gmail_filter(
                    from_filter="spam@x.com",
                    subject_filter="BUY NOW",
                    add_labels=["Trash"],
                    account="me@x.com",
                )
            )
            assert result == {"id": "f1"}
            _, kwargs = client_mock.request.call_args
            assert kwargs["json"] == {
                "from_filter": "spam@x.com",
                "subject_filter": "BUY NOW",
                "add_label_ids": ["Trash"],
                "remove_label_ids": [],
                "account": "me@x.com",
            }

    def test_create_gmail_label(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(201, {"id": "Label_new"}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.create_gmail_label("MyLabel", visibility="labelShowIfUnread", account="me@x.com"))
            assert result == {"id": "Label_new"}
            client_mock.request.assert_called_once_with(
                "POST",
                "/gmail/labels",
                params={"name": "MyLabel", "visibility": "labelShowIfUnread", "account": "me@x.com"},
                json=None,
                headers=backend._headers(),
            )


class TestCalendarConflictMethod:
    def test_check_calendar_conflicts(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, {"conflicts": []}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(
                backend.check_calendar_conflicts(
                    start="2026-07-07T10:00:00",
                    end="2026-07-07T11:00:00",
                    account="me@x.com",
                )
            )
            assert result == {"conflicts": []}
            _, kwargs = client_mock.request.call_args
            assert kwargs["json"] == {
                "start": "2026-07-07T10:00:00",
                "end": "2026-07-07T11:00:00",
                "account": "me@x.com",
            }


class TestExtractMemoryMethod:
    def test_extract_memory_minimal(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, {"facts": []}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.extract_memory("Remember this"))
            assert result == {"facts": []}
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"text": "Remember this", "source": "manual", "auto_save": "false"}

    def test_extract_memory_auto_save(self) -> None:
        client_mock = _make_async_client_mock(response=_json_response(200, {"facts": [{"text": "fact"}]}))
        with patch("httpx.AsyncClient", return_value=client_mock):
            backend = InboxBackend(base_url="http://test:1234")
            result = _run(backend.extract_memory("Important", source="chat", auto_save=True))
            assert result == {"facts": [{"text": "fact"}]}
            _, kwargs = client_mock.request.call_args
            assert kwargs["params"] == {"text": "Important", "source": "chat", "auto_save": "true"}


class TestInboxBackendError:
    def test_is_runtime_error(self) -> None:
        """InboxBackendError inherits from RuntimeError."""
        err = InboxBackendError("test")
        assert isinstance(err, RuntimeError)

    def test_str_representation(self) -> None:
        err = InboxBackendError("something went wrong")
        assert str(err) == "something went wrong"
