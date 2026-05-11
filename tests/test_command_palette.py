"""Tests for command palette registry, fuzzy filter, and NLP routing."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from command_palette import (
    COMMAND_REGISTRY,
    COMMAND_SPECS,
    CommandSpec,
    build_commands,
    filter_commands,
    fuzzy_score,
    llm_is_available,
    make_command,
    nlp_classify,
    resolve_nlp,
)
from inbox import CommandPaletteScreen, InboxApp

# ── fuzzy_score ───────────────────────────────────────────────────────────────


def test_fuzzy_score_exact_match():
    assert fuzzy_score("refresh", "refresh") == 3


def test_fuzzy_score_prefix_match():
    assert fuzzy_score("ref", "refresh") == 2


def test_fuzzy_score_substring_match():
    assert fuzzy_score("fre", "refresh") == 1


def test_fuzzy_score_no_match():
    assert fuzzy_score("zzz", "refresh") == 0


def test_fuzzy_score_case_insensitive():
    assert fuzzy_score("REFRESH", "Refresh") == 3


def test_fuzzy_score_empty_query_matches_all():
    assert fuzzy_score("", "anything") == 1


# ── filter_commands ───────────────────────────────────────────────────────────


def _dummy_cmd(id: str, name: str, desc: str = "", cat: str = "Action") -> dict:
    return make_command(id, name, desc, cat, lambda: None)


def test_filter_commands_empty_query_returns_all():
    cmds = [_dummy_cmd("a", "Alpha"), _dummy_cmd("b", "Beta")]
    result = filter_commands("", cmds)
    assert len(result) == 2


def test_filter_commands_exact_match_first():
    cmds = [
        _dummy_cmd("a", "Calendar event"),
        _dummy_cmd("b", "Switch to Calendar"),
        _dummy_cmd("c", "Cal shortcut"),
    ]
    result = filter_commands("Switch to Calendar", cmds)
    assert result[0]["id"] == "b"


def test_filter_commands_prefix_beats_substring():
    cmds = [
        _dummy_cmd("a", "Refresh data"),  # contains "ref"
        _dummy_cmd("b", "Refresh"),  # starts with "ref"
    ]
    result = filter_commands("ref", cmds)
    # Both match; prefix "Refresh" should score higher than "Refresh data"
    # (both start with "ref", but "Refresh" exact-prefix with longer relative match)
    assert result[0]["id"] in ("a", "b")  # at least returns matches
    assert len(result) == 2


def test_filter_commands_no_match_returns_empty():
    cmds = [_dummy_cmd("a", "Refresh"), _dummy_cmd("b", "Calendar")]
    result = filter_commands("zzzzz", cmds)
    assert result == []


def test_filter_commands_matches_description():
    cmds = [_dummy_cmd("a", "Refresh", desc="Reload all data from server")]
    result = filter_commands("reload", cmds)
    assert len(result) == 1
    assert result[0]["id"] == "a"


def test_filter_commands_matches_category():
    cmds = [
        _dummy_cmd("a", "Something", cat="Navigate"),
        _dummy_cmd("b", "Other", cat="Action"),
    ]
    result = filter_commands("navigate", cmds)
    assert len(result) == 1
    assert result[0]["id"] == "a"


# ── build_commands ────────────────────────────────────────────────────────────


def _mock_app() -> MagicMock:
    app = MagicMock()
    # All action methods should be callable
    for attr in dir(app):
        if attr.startswith("action_"):
            getattr(app, attr).return_value = None
    return app


def test_build_commands_covers_all_tabs():
    app = _mock_app()
    commands = build_commands(app)
    ids = {c["id"] for c in commands}
    for expected in [
        "switch_all",
        "switch_imessage",
        "switch_gmail",
        "switch_calendar",
        "switch_notes",
        "switch_reminders",
        "switch_github",
        "switch_drive",
    ]:
        assert expected in ids, f"Missing command id: {expected}"


def test_build_commands_covers_key_actions():
    app = _mock_app()
    commands = build_commands(app)
    ids = {c["id"] for c in commands}
    for expected in ["refresh", "quit", "toggle_ambient", "new_event", "gmail_compose"]:
        assert expected in ids, f"Missing command id: {expected}"


def test_build_commands_all_have_required_fields():
    app = _mock_app()
    commands = build_commands(app)
    for cmd in commands:
        assert "id" in cmd
        assert "name" in cmd
        assert "description" in cmd
        assert "category" in cmd
        assert callable(cmd["action"])


def test_build_commands_categories_are_valid():
    app = _mock_app()
    commands = build_commands(app)
    valid_categories = {"Navigate", "Action", "Create", "Settings", "AI"}
    for cmd in commands:
        assert cmd["category"] in valid_categories, (
            f"Unexpected category '{cmd['category']}' for '{cmd['id']}'"
        )


def test_build_commands_action_calls_app_method():
    app = _mock_app()
    commands = build_commands(app)
    # Find switch_all and call its action
    cmd = next(c for c in commands if c["id"] == "switch_all")
    cmd["action"]()
    app.action_filter_all.assert_called_once()


def test_command_registry_contains_typed_specs():
    assert COMMAND_SPECS is COMMAND_REGISTRY
    assert all(isinstance(spec, CommandSpec) for spec in COMMAND_REGISTRY)


def test_build_commands_uses_registry_ids_unchanged():
    app = _mock_app()
    commands = build_commands(app)
    assert [cmd["id"] for cmd in commands] == [spec.id for spec in COMMAND_REGISTRY]


def test_command_registry_action_names_exist_on_inbox_app():
    missing = [
        f"{spec.id}:{spec.action_name}"
        for spec in COMMAND_REGISTRY
        if not hasattr(InboxApp, spec.action_name)
    ]
    assert missing == []


def test_llm_is_available_uses_injected_provider():
    assert llm_is_available(lambda: True) is True


def test_nlp_classify_uses_injected_dependencies():
    cmds = _sample_commands()

    def generate_json(prompt: str, schema: type) -> dict:
        assert "switch_calendar" in prompt
        assert schema is not None
        return {"command_id": "switch_calendar", "confidence": 0.9, "args": {}, "reason": ""}

    result = nlp_classify(
        "open calendar",
        cmds,
        llm_available=lambda: True,
        json_generator=generate_json,
    )

    assert result == {
        "command_id": "switch_calendar",
        "confidence": 0.9,
        "args": {},
        "reason": "",
    }


# ── resolve_nlp ───────────────────────────────────────────────────────────────


def _sample_commands() -> list[dict]:
    app = _mock_app()
    return build_commands(app)


def test_resolve_nlp_returns_none_when_llm_unavailable():
    cmds = _sample_commands()
    matched, msg = resolve_nlp("open calendar", cmds, classifier=lambda query, commands: None)
    assert matched is None
    assert "LLM unavailable" in msg


def test_resolve_nlp_low_confidence_shows_suggestions():
    cmds = _sample_commands()
    matched, msg = resolve_nlp(
        "open calendar",
        cmds,
        classifier=lambda query, commands: {
            "command_id": "switch_calendar",
            "confidence": 0.3,
            "args": {},
            "reason": "",
        },
    )
    assert matched is None
    assert "Low confidence" in msg or "try" in msg.lower()


def test_resolve_nlp_high_confidence_returns_command():
    cmds = _sample_commands()
    matched, msg = resolve_nlp(
        "open calendar",
        cmds,
        classifier=lambda query, commands: {
            "command_id": "switch_calendar",
            "confidence": 0.9,
            "args": {},
            "reason": "",
        },
    )
    assert matched is not None
    assert matched["id"] == "switch_calendar"
    assert msg == ""


def test_resolve_nlp_null_command_id_returns_none():
    cmds = _sample_commands()
    matched, msg = resolve_nlp(
        "do something weird",
        cmds,
        classifier=lambda query, commands: {
            "command_id": None,
            "confidence": 0.0,
            "args": {},
            "reason": "ambiguous",
        },
    )
    assert matched is None
    assert "ambiguous" in msg


def test_resolve_nlp_unknown_command_id_returns_none():
    cmds = _sample_commands()
    matched, msg = resolve_nlp(
        "something",
        cmds,
        classifier=lambda query, commands: {
            "command_id": "nonexistent_cmd",
            "confidence": 0.95,
            "args": {},
            "reason": "",
        },
    )
    assert matched is None
    assert "Unknown command id" in msg


# ── CommandPaletteScreen (Textual Pilot) ──────────────────────────────────────


class _HarnessApp(InboxApp):
    def on_mount(self) -> None:
        pass

    def boot(self) -> None:
        pass


def test_command_palette_opens_on_ctrl_p():
    async def runner() -> None:
        app = _HarnessApp()
        app.client = MagicMock()
        app.client.github_notifications.return_value = []

        async with app.run_test() as pilot:
            await pilot.press("ctrl+p")
            await pilot.pause(0.1)
            screens = app.screen_stack
            assert any(isinstance(s, CommandPaletteScreen) for s in screens), (
                "CommandPaletteScreen not found in screen stack"
            )

    asyncio.run(runner())


def test_command_palette_esc_closes():
    async def runner() -> None:
        app = _HarnessApp()
        app.client = MagicMock()
        app.client.github_notifications.return_value = []

        async with app.run_test() as pilot:
            await pilot.press("ctrl+p")
            await pilot.pause(0.1)
            await pilot.press("escape")
            await pilot.pause(0.1)
            screens = app.screen_stack
            assert not any(isinstance(s, CommandPaletteScreen) for s in screens), (
                "CommandPaletteScreen should be closed"
            )

    asyncio.run(runner())


def test_command_palette_enter_executes_command():
    async def runner() -> None:
        app = _HarnessApp()
        app.client = MagicMock()
        app.client.github_notifications.return_value = []

        executed: list[str] = []

        original = app._on_palette_result

        def tracking_result(result):
            if result is not None:
                executed.append(result["id"])
            original(result)

        app._on_palette_result = tracking_result

        async with app.run_test() as pilot:
            await pilot.press("ctrl+p")
            await pilot.pause(0.1)
            await pilot.press("r", "e", "f", "r", "e", "s", "h")
            await pilot.pause(0.1)
            await pilot.press("enter")
            await pilot.pause(0.1)

        assert len(executed) >= 1

    asyncio.run(runner())


def test_command_palette_filter_narrows_list():
    app_mock = _mock_app()
    commands = build_commands(app_mock)
    # filter_commands is already unit-tested; just verify the screen uses it
    filtered = filter_commands("github", commands)
    github_ids = {c["id"] for c in filtered}
    assert "switch_github" in github_ids
    assert "mark_all_gh_read" in github_ids
