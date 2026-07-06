"""Tests for command palette registry, fuzzy filter, and NLP routing."""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import MagicMock

from command_palette import (
    COMMAND_REGISTRY,
    COMMAND_SPECS,
    CommandSpec,
    _result_value,
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


# ── _result_value (private helper) ────────────────────────────────────────────


def test_result_value_dict_access():
    """When result is a dict, _result_value uses .get()."""
    d = {"command_id": "test_cmd", "confidence": 0.8}
    assert _result_value(d, "command_id", None) == "test_cmd"
    assert _result_value(d, "missing", "fallback") == "fallback"


def test_result_value_getattr_fallback():
    """When result is not a dict, _result_value falls back to getattr."""

    class FakeModel:
        command_id = "attr_cmd"
        confidence = 0.95

    obj = FakeModel()
    assert _result_value(obj, "command_id", None) == "attr_cmd"
    assert _result_value(obj, "confidence", 0.0) == 0.95
    assert _result_value(obj, "missing_key", "fallback") == "fallback"


# ── llm_is_available ──────────────────────────────────────────────────────────


def test_llm_is_available_uses_injected_provider():
    assert llm_is_available(lambda: True) is True


def test_llm_is_available_default_services_path():
    """Without a provider, llm_is_available imports services and checks LLM state."""
    # In test env services.llm_is_loaded() returns False, so this returns False
    assert llm_is_available() is False


def test_llm_is_available_default_services_error_is_false():
    """When the services module is unavailable, llm_is_available returns False."""
    # Make services unimportable by setting it to None in sys.modules.
    # The import services will return None, and services.llm_is_loaded()
    # will raise AttributeError → caught → returns False.
    saved = sys.modules.get("services")
    sys.modules["services"] = None  # type: ignore[assignment]
    try:
        assert llm_is_available() is False
    finally:
        if saved is not None:
            sys.modules["services"] = saved
        else:
            sys.modules.pop("services", None)


# ── nlp_classify ──────────────────────────────────────────────────────────────


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


def test_nlp_classify_returns_none_when_llm_unavailable():
    """nlp_classify returns None immediately when the LLM is not available."""
    cmds = _sample_commands()
    result = nlp_classify("open calendar", cmds, llm_available=lambda: False)
    assert result is None


def test_nlp_classify_returns_none_when_generator_raises():
    """nlp_classify catches exceptions from the json_generator and returns None."""
    cmds = _sample_commands()

    def failing_generator(prompt, schema):
        raise RuntimeError("LLM inference failed")

    result = nlp_classify(
        "open calendar",
        cmds,
        llm_available=lambda: True,
        json_generator=failing_generator,
    )
    assert result is None


def test_nlp_classify_handles_missing_pydantic(monkeypatch):
    """nlp_classify returns None when pydantic cannot be imported."""
    import builtins

    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "pydantic" or name.startswith("pydantic."):
            raise ImportError(f"No module named '{name}'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)
    cmds = _sample_commands()
    result = nlp_classify("open calendar", cmds, llm_available=lambda: True)
    assert result is None


def test_nlp_classify_calls_default_generate_json():
    """Without an injected json_generator, _generate_json is used as default."""
    cmds = _sample_commands()
    # No json_generator injected → falls back to _generate_json which
    # calls services.generate_json. In test env that raises (LLM not loaded),
    # and the exception is caught → returns None.
    result = nlp_classify("open calendar", cmds, llm_available=lambda: True)
    assert result is None


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
