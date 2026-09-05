"""Tests for inbox_mcp_factory.py."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import inbox_mcp_factory

# ── RecordingMCP — captures tool registrations for inspection ──────────

class RecordingMCP:
    """A FastMCP stand-in that records tool registrations."""

    def __init__(self, name, stateless_http=False, json_response=False):
        self.name = name
        self.stateless_http = stateless_http
        self.json_response = json_response
        self.tools: dict[str, callable] = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func
        return decorator


# ── Helpers ────────────────────────────────────────────────────────────

def _build_with_mocks(*, readonly=False, for_http=False):
    """Build an MCP with mocked dependencies; return (mcp, backend, memory)."""
    mock_backend = MagicMock()
    mock_memory = MagicMock()
    with patch("inbox_mcp_factory.make_backend", return_value=mock_backend), \
         patch("inbox_mcp_factory.make_memory_store", return_value=mock_memory), \
         patch("inbox_mcp_factory.FastMCP", RecordingMCP), \
         patch("inbox_mcp_factory._register_registry_tools"):
        mcp, backend, memory = inbox_mcp_factory.build_mcp(
            readonly=readonly, for_http=for_http,
        )
    return mcp, backend, memory


# ═══════════════════════════════════════════════════════════════════════
# _require_confirmation
# ═══════════════════════════════════════════════════════════════════════

class TestRequireConfirmation:
    def test_confirm_true_returns_none(self):
        assert inbox_mcp_factory._require_confirmation(True, "test_action") is None

    def test_confirm_false_raises_valueerror(self):
        with pytest.raises(ValueError, match="test_action"):
            inbox_mcp_factory._require_confirmation(False, "test_action")

    def test_confirm_falsy_zero_raises(self):
        """Falsy non-bool values like 0 also trigger rejection."""
        with pytest.raises(ValueError):
            inbox_mcp_factory._require_confirmation(0, "action")

    def test_confirm_empty_string_raises(self):
        with pytest.raises(ValueError):
            inbox_mcp_factory._require_confirmation("", "action")


# ═══════════════════════════════════════════════════════════════════════
# Module-level read_daily_note
# ═══════════════════════════════════════════════════════════════════════

class TestModuleReadDailyNote:
    def test_default_date_uses_today_file(self, monkeypatch):
        fake_path = Path("/fake/daily/2026-07-06.md")
        monkeypatch.setattr(
            inbox_mcp_factory.ambient_notes, "_today_file", lambda: fake_path,
        )
        result = asyncio.run(inbox_mcp_factory.read_daily_note())
        assert result == {"ok": False, "path": str(fake_path), "content": ""}

    def test_default_date_existing_file(self, monkeypatch, tmp_path):
        daily = tmp_path / "daily"
        daily.mkdir()
        note = daily / "2026-07-06.md"
        note.write_text("# Hello")
        monkeypatch.setattr(
            inbox_mcp_factory.ambient_notes, "_today_file", lambda: note,
        )
        result = asyncio.run(inbox_mcp_factory.read_daily_note())
        assert result == {"ok": True, "path": str(note), "content": "# Hello"}

    def test_specific_date_missing_file(self, monkeypatch, tmp_path):
        daily = tmp_path / "daily"
        monkeypatch.setattr(inbox_mcp_factory.ambient_notes, "DAILY_DIR", daily)
        result = asyncio.run(inbox_mcp_factory.read_daily_note("2026-01-15"))
        assert result["ok"] is False
        assert result["path"] == str(daily / "2026-01-15.md")
        assert result["content"] == ""

    def test_specific_date_existing_file(self, monkeypatch, tmp_path):
        daily = tmp_path / "daily"
        daily.mkdir()
        note = daily / "2026-01-15.md"
        note.write_text("content")
        monkeypatch.setattr(inbox_mcp_factory.ambient_notes, "DAILY_DIR", daily)
        result = asyncio.run(inbox_mcp_factory.read_daily_note("2026-01-15"))
        assert result == {"ok": True, "path": str(note), "content": "content"}


# ═══════════════════════════════════════════════════════════════════════
# build_mcp — structural / factory behaviour
# ═══════════════════════════════════════════════════════════════════════

class TestBuildMcp:
    def test_returns_triple(self):
        mcp, backend, memory = _build_with_mocks()
        assert isinstance(mcp, RecordingMCP)
        assert backend is not None
        assert memory is not None

    def test_stdio_mode_no_http_flags(self):
        mcp, _, _ = _build_with_mocks(for_http=False)
        assert mcp.stateless_http is False
        assert mcp.json_response is False

    def test_http_mode_sets_flags(self):
        mcp, _, _ = _build_with_mocks(for_http=True)
        assert mcp.stateless_http is True
        assert mcp.json_response is True

    def test_readonly_name_includes_read_only(self):
        mcp, _, _ = _build_with_mocks(readonly=True)
        assert "(Read Only)" in mcp.name

    def test_non_readonly_name_omits_read_only(self):
        mcp, _, _ = _build_with_mocks(readonly=False)
        assert "(Read Only)" not in mcp.name

    def test_common_tools_always_registered(self):
        mcp, _, _ = _build_with_mocks(readonly=False)
        assert "read_daily_note" in mcp.tools
        assert "get_memory" in mcp.tools
        assert "list_open_commitments" in mcp.tools
        assert "life_what_needs_me" in mcp.tools
        assert "life_triage" in mcp.tools
        assert "life_context" in mcp.tools

    def test_readonly_omits_write_tools(self):
        mcp, _, _ = _build_with_mocks(readonly=True)
        assert "append_daily_note" not in mcp.tools
        assert "save_memory_note" not in mcp.tools
        assert "update_memory" not in mcp.tools
        assert "close_commitment" not in mcp.tools
        assert "life_capture" not in mcp.tools
        assert "life_complete_commitment" not in mcp.tools

    def test_non_readonly_registers_write_tools(self):
        mcp, _, _ = _build_with_mocks(readonly=False)
        assert "append_daily_note" in mcp.tools
        assert "save_memory_note" in mcp.tools
        assert "update_memory" in mcp.tools
        assert "close_commitment" in mcp.tools
        assert "life_capture" in mcp.tools
        assert "life_complete_commitment" in mcp.tools

    def test_calls_register_registry_tools(self):
        from unittest.mock import ANY

        with patch("inbox_mcp_factory.make_backend", return_value=MagicMock()), \
             patch("inbox_mcp_factory.make_memory_store", return_value=MagicMock()), \
             patch("inbox_mcp_factory.FastMCP", RecordingMCP), \
             patch("inbox_mcp_factory._register_registry_tools") as mock_reg:
            inbox_mcp_factory.build_mcp(readonly=True, for_http=True)
            mock_reg.assert_called_once_with(ANY, ANY, readonly_only=True)

    def test_calls_make_backend_and_store(self):
        with patch("inbox_mcp_factory.make_backend", return_value=MagicMock()) as mock_be, \
             patch("inbox_mcp_factory.make_memory_store", return_value=MagicMock()) as mock_ms, \
             patch("inbox_mcp_factory.FastMCP", RecordingMCP), \
             patch("inbox_mcp_factory._register_registry_tools"):
            inbox_mcp_factory.build_mcp()
            mock_be.assert_called_once()
            mock_ms.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════
# Tool body tests — capture tool functions and exercise them
# ═══════════════════════════════════════════════════════════════════════

class TestToolBodies:
    """Exercise tool function bodies captured via RecordingMCP."""

    @pytest.fixture
    def captured(self):
        """Return (mcp, backend, memory) from a non-readonly build."""
        return _build_with_mocks(readonly=False)

    # -- read_daily_note tool --------------------------------------------

    @pytest.mark.anyio
    async def test_tool_read_daily_note_default_missing(self, captured, monkeypatch):
        mcp, _, _ = captured
        fn = mcp.tools["read_daily_note"]
        fake = Path("/fake/daily/2026-07-06.md")
        monkeypatch.setattr(inbox_mcp_factory.ambient_notes, "_today_file", lambda: fake)
        result = await fn()
        assert result == {"ok": False, "path": str(fake), "content": ""}

    @pytest.mark.anyio
    async def test_life_capture_durably_projects_commitments(self, captured, monkeypatch):
        mcp, _, memory = captured
        memory.capture_and_process.return_value = {
            "capture": {"capture_id": "cap_test", "processing_state": "PROCESSED"},
            "commitments": [],
        }
        monkeypatch.setattr(
            inbox_mcp_factory,
            "ai_extract_memory",
            lambda _text: {"action_items": ["Call Yadel"]},
        )

        result = await mcp.tools["life_capture"]("I need to call Yadel.", confirm=True)

        assert result["capture"]["capture_id"] == "cap_test"
        memory.capture_and_process.assert_called_once()
        args = memory.capture_and_process.call_args.args
        assert args[0] == "I need to call Yadel."
        assert args[1] == "chatgpt"
        assert args[2] is inbox_mcp_factory.ai_extract_memory

    @pytest.mark.anyio
    async def test_life_capture_requires_confirmation(self, captured):
        mcp, _, _ = captured

        with pytest.raises(ValueError, match="life_capture requires explicit confirmation"):
            await mcp.tools["life_capture"]("Call Yadel")

    @pytest.mark.anyio
    async def test_life_what_needs_me_delegates_to_store(self, captured):
        mcp, _, memory = captured
        memory.what_needs_me.return_value = {"message": "Nothing needs you.", "items": []}

        result = await mcp.tools["life_what_needs_me"](limit=3)

        assert result["message"] == "Nothing needs you."
        memory.what_needs_me.assert_called_once_with(3)

    @pytest.mark.anyio
    async def test_life_triage_reads_inbox_and_merges_local_state(self, captured):
        mcp, backend, memory = captured
        memory.what_needs_me.return_value = {"items": [], "capture_failures": []}
        backend.inbox_now = AsyncMock(
            return_value={"now_items": [], "waiting_threads": [], "reasons": []}
        )

        result = await mcp.tools["life_triage"](limit=3)

        assert result["read_only"] is True
        backend.inbox_now.assert_awaited_once_with(limit=3, workflow="", account="")

    @pytest.mark.anyio
    async def test_life_context_reads_existing_models_without_writes(self, captured):
        mcp, backend, memory = captured
        memory.what_needs_me.return_value = {"items": [], "capture_failures": []}
        memory.query_entries.return_value = [
            {
                "id": 7,
                "memory_type": "person",
                "subject": "Harsh",
                "content": "Pickup contact",
                "source": "manual",
                "confidence": 0.9,
                "status": "active",
                "created_at": "2026-08-25T12:00:00+00:00",
                "updated_at": "2026-08-25T12:00:00+00:00",
                "expires_at": None,
                "metadata": {},
            }
        ]
        memory.list_open_life_commitments.return_value = []
        backend.inbox_now = AsyncMock(
            return_value={"now_items": [], "waiting_threads": [], "reasons": []}
        )
        backend.list_upcoming_calendar_events = AsyncMock(return_value=[])
        backend.list_contacts = AsyncMock(return_value=[])
        with patch(
            "inbox_mcp_factory.build_unified_profiles",
            return_value=([], {"schema": "inbox.unified_contacts.v1", "source_status": {}}),
        ) as profiles:
            result = await mcp.tools["life_context"](limit=3, section_limit=4)

        assert result["read_only"] is True
        assert result["sections"]["people"][0]["title"] == "Harsh"
        backend.inbox_now.assert_awaited_once_with(limit=3, workflow="", account="")
        memory.query_entries.assert_called_once_with(
            query="", memory_type="", subject="", status="", limit=32
        )
        memory.list_open_life_commitments.assert_called_once_with(4)
        profiles.assert_called_once_with(gmail_limit=24, include_gmail=False, limit=4)
        backend.list_upcoming_calendar_events.assert_awaited_once_with(
            days=7, limit=16, account=""
        )
        backend.list_contacts.assert_awaited_once_with(limit=16)

    @pytest.mark.anyio
    async def test_life_context_can_include_live_gmail_for_people(self, captured):
        mcp, backend, memory = captured
        memory.what_needs_me.return_value = {"items": [], "capture_failures": []}
        memory.query_entries.return_value = []
        backend.inbox_now = AsyncMock(
            return_value={"now_items": [], "waiting_threads": [], "reasons": []}
        )
        backend.list_upcoming_calendar_events = AsyncMock(return_value=[])
        backend.list_contacts = AsyncMock(return_value=[])
        with patch(
            "inbox_mcp_factory.build_unified_profiles",
            return_value=([], {"schema": "inbox.unified_contacts.v1", "source_status": {}}),
        ) as profiles:
            await mcp.tools["life_context"](
                limit=2, section_limit=3, include_live_gmail=True
            )

        profiles.assert_called_once_with(gmail_limit=18, include_gmail=True, limit=3)

    @pytest.mark.anyio
    async def test_life_context_reports_calendar_failure(self, captured):
        mcp, backend, memory = captured
        memory.what_needs_me.return_value = {"items": [], "capture_failures": []}
        memory.query_entries.return_value = []
        backend.inbox_now = AsyncMock(
            return_value={"now_items": [], "waiting_threads": [], "reasons": []}
        )
        backend.list_upcoming_calendar_events = AsyncMock(side_effect=RuntimeError("down"))
        backend.list_contacts = AsyncMock(return_value=[])
        with patch(
            "inbox_mcp_factory.build_unified_profiles",
            return_value=([], {"schema": "inbox.unified_contacts.v1", "source_status": {}}),
        ):
            result = await mcp.tools["life_context"](limit=2, section_limit=3)

        assert result["source_health"]["calendar"]["status"] == "unavailable"
        assert "calendar_read_unavailable" in result["limitations"]

    @pytest.mark.anyio
    async def test_tool_read_daily_note_specific_date(self, captured, monkeypatch, tmp_path):
        mcp, _, _ = captured
        fn = mcp.tools["read_daily_note"]
        daily = tmp_path / "daily"
        monkeypatch.setattr(inbox_mcp_factory.ambient_notes, "DAILY_DIR", daily)
        result = await fn("2026-03-15")
        assert result["ok"] is False
        assert result["path"] == str(daily / "2026-03-15.md")

    @pytest.mark.anyio
    async def test_tool_read_daily_note_existing_file(self, captured, monkeypatch, tmp_path):
        """Tool body: when the file exists, returns ok=True with content."""
        mcp, _, _ = captured
        fn = mcp.tools["read_daily_note"]
        daily = tmp_path / "daily"
        daily.mkdir()
        note = daily / "2026-03-15.md"
        note.write_text("# Note content")
        monkeypatch.setattr(inbox_mcp_factory.ambient_notes, "DAILY_DIR", daily)
        result = await fn("2026-03-15")
        assert result == {"ok": True, "path": str(note), "content": "# Note content"}

    # -- append_daily_note tool ------------------------------------------

    @pytest.mark.anyio
    async def test_tool_append_daily_note_confirm_false_raises(self, captured):
        mcp, _, _ = captured
        fn = mcp.tools["append_daily_note"]
        with pytest.raises(ValueError, match="append_daily_note"):
            await fn("some content")

    @pytest.mark.anyio
    async def test_tool_append_daily_note_confirm_true_calls_ambient(self, captured, monkeypatch):
        mcp, _, _ = captured
        fn = mcp.tools["append_daily_note"]
        monkeypatch.setattr(inbox_mcp_factory.ambient_notes, "append_to_daily", MagicMock())
        monkeypatch.setattr(
            inbox_mcp_factory.ambient_notes,
            "_today_file",
            lambda: Path("/fake/daily/2026-07-06.md"),
        )
        result = await fn("hello world", confirm=True)
        assert result["ok"] is True
        assert result["date"] == "2026-07-06"
        inbox_mcp_factory.ambient_notes.append_to_daily.assert_called_once_with(
            "hello world",
        )

    # -- get_memory tool -------------------------------------------------

    @pytest.mark.anyio
    async def test_tool_get_memory_delegates_to_store(self, captured):
        mcp, _, memory = captured
        fn = mcp.tools["get_memory"]
        memory.query_entries.return_value = [{"id": 1}]
        result = await fn(query="test", memory_type="pref", limit=5)
        memory.query_entries.assert_called_once_with(
            query="test", memory_type="pref", subject="", status="", limit=5,
        )
        assert result == [{"id": 1}]

    @pytest.mark.anyio
    async def test_tool_get_memory_defaults(self, captured):
        mcp, _, memory = captured
        fn = mcp.tools["get_memory"]
        memory.query_entries.return_value = []
        result = await fn()
        memory.query_entries.assert_called_once_with(
            query="", memory_type="", subject="", status="", limit=10,
        )
        assert result == []

    # -- list_open_commitments tool --------------------------------------

    @pytest.mark.anyio
    async def test_tool_list_open_commitments_delegates(self, captured):
        mcp, _, memory = captured
        fn = mcp.tools["list_open_commitments"]
        memory.list_open_commitments.return_value = [{"entry_id": 1}]
        result = await fn(limit=5)
        memory.list_open_commitments.assert_called_once_with(limit=5)
        assert result == [{"entry_id": 1}]

    # -- save_memory_note tool -------------------------------------------

    @pytest.mark.anyio
    async def test_tool_save_memory_note_confirm_false_raises(self, captured):
        mcp, _, _ = captured
        fn = mcp.tools["save_memory_note"]
        with pytest.raises(ValueError, match="save_memory_note"):
            await fn("note", "subj", "body")

    @pytest.mark.anyio
    async def test_tool_save_memory_note_confirm_true_delegates(self, captured):
        mcp, _, memory = captured
        fn = mcp.tools["save_memory_note"]
        memory.save_entry.return_value = {"entry_id": 42}
        result = await fn(
            "preference", "theme", "dark mode", confirm=True,
            source="cli", confidence=0.9, status="active",
        )
        memory.save_entry.assert_called_once_with(
            memory_type="preference",
            subject="theme",
            content="dark mode",
            source="cli",
            confidence=0.9,
            status="active",
            expires_at=None,
        )
        assert result == {"entry_id": 42}

    @pytest.mark.anyio
    async def test_tool_save_memory_note_expires_at_passed_through(self, captured):
        mcp, _, memory = captured
        fn = mcp.tools["save_memory_note"]
        memory.save_entry.return_value = {"entry_id": 1}
        await fn("task", "remind", "do thing", confirm=True, expires_at="2026-12-31")
        memory.save_entry.assert_called_once_with(
            memory_type="task",
            subject="remind",
            content="do thing",
            source="chat",
            confidence=0.8,
            status="active",
            expires_at="2026-12-31",
        )

    @pytest.mark.anyio
    async def test_tool_save_memory_note_empty_expires_at_becomes_none(self, captured):
        """An empty expires_at string is coerced to None."""
        mcp, _, memory = captured
        fn = mcp.tools["save_memory_note"]
        memory.save_entry.return_value = {"entry_id": 1}
        await fn("task", "remind", "do thing", confirm=True, expires_at="")
        memory.save_entry.assert_called_once_with(
            memory_type="task",
            subject="remind",
            content="do thing",
            source="chat",
            confidence=0.8,
            status="active",
            expires_at=None,
        )

    # -- update_memory tool ----------------------------------------------

    @pytest.mark.anyio
    async def test_tool_update_memory_confirm_false_raises(self, captured):
        mcp, _, _ = captured
        fn = mcp.tools["update_memory"]
        with pytest.raises(ValueError, match="update_memory"):
            await fn(1)

    @pytest.mark.anyio
    async def test_tool_update_memory_confirm_true_with_all_fields(self, captured):
        mcp, _, memory = captured
        fn = mcp.tools["update_memory"]
        memory.update_entry.return_value = {"entry_id": 1, "status": "updated"}
        result = await fn(
            1, confirm=True,
            subject="new subj", content="new body",
            status="done", confidence=0.5,
        )
        memory.update_entry.assert_called_once_with(
            1, subject="new subj", content="new body",
            status="done", confidence=0.5,
        )
        assert result == {"entry_id": 1, "status": "updated"}

    @pytest.mark.anyio
    async def test_tool_update_memory_confirm_true_partial_fields(self, captured):
        """Only non-None args should be passed to update_entry."""
        mcp, _, memory = captured
        fn = mcp.tools["update_memory"]
        memory.update_entry.return_value = {"entry_id": 1}
        result = await fn(1, confirm=True, status="closed")
        memory.update_entry.assert_called_once_with(1, status="closed")
        assert result == {"entry_id": 1}

    # -- close_commitment tool -------------------------------------------

    @pytest.mark.anyio
    async def test_tool_close_commitment_confirm_false_raises(self, captured):
        mcp, _, _ = captured
        fn = mcp.tools["close_commitment"]
        with pytest.raises(ValueError, match="close_commitment"):
            await fn(1)

    @pytest.mark.anyio
    async def test_tool_close_commitment_confirm_true_delegates(self, captured):
        mcp, _, memory = captured
        fn = mcp.tools["close_commitment"]
        memory.close_commitment.return_value = {"entry_id": 1, "status": "closed"}
        result = await fn(1, confirm=True)
        memory.close_commitment.assert_called_once_with(1)
        assert result == {"entry_id": 1, "status": "closed"}
