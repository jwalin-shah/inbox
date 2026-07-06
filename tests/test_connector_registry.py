"""Tests for the local connector registry."""

from __future__ import annotations

import subprocess
from unittest.mock import patch


def test_status_reports_installed_and_auth_state():
    from connector_registry import connectors_status

    def fake_which(binary: str) -> str | None:
        return f"/usr/local/bin/{binary}" if binary == "wacli" else None

    def fake_run(command: tuple[str, ...], *, timeout: int = 12):
        assert command[:2] == ("wacli", "doctor")
        return 0, '{"success":true,"data":{"authenticated":true}}', ""

    with (
        patch("connector_registry.shutil.which", side_effect=fake_which),
        patch("connector_registry._run", side_effect=fake_run),
    ):
        result = connectors_status()

    whatsapp = next(item for item in result["connectors"] if item["id"] == "whatsapp")
    google = next(item for item in result["connectors"] if item["id"] == "google")
    assert whatsapp["installed"] is True
    assert whatsapp["auth_state"] == "ok"
    assert whatsapp["auth_detail"]["data"]["authenticated"] is True
    assert whatsapp["sync_ready"] is True
    assert whatsapp["commands"]["sync"] == ["wacli", "sync", "--once"]
    assert whatsapp["required_permissions"]
    assert whatsapp["accounts"][0]["id"] == "whatsapp:local"
    assert whatsapp["accounts"][0]["credential_refs"][0]["encrypted"] is True
    assert "encrypted_ref" in whatsapp["accounts"][0]["credential_refs"][0]
    assert "secret" not in whatsapp["accounts"][0]["credential_refs"][0]
    assert whatsapp["credential_pattern"]["mode"] == "encrypted_reference_only"
    assert whatsapp["credential_pattern"]["plaintext_material_allowed"] is False
    mutation_policy = {
        item["action"]: item for item in whatsapp["action_policy"]["mutations"]
    }
    assert mutation_policy["send"]["policy"] == "approval_required"
    assert mutation_policy["delete"]["policy"] == "approval_required"
    assert whatsapp["action_policy"]["registry_executes_provider_writes"] is False
    assert google["installed"] is False
    assert google["auth_state"] == "not_installed"
    assert google["commands"]["auth"] == ["gog", "auth", "status", "--json"]


def test_status_includes_linkedin_scanner_readiness(monkeypatch):
    from connector_registry import connectors_status

    monkeypatch.setenv("INBOX_ENABLE_LINKEDIN_SCRAPER", "1")

    def fake_which(binary: str) -> str | None:
        return "/usr/bin/python3" if binary == "python3" else None

    def fake_run(command: tuple[str, ...], *, timeout: int = 12):
        assert command[:2] == ("python3", "-c")
        return 0, '{"scanner_importable":true}', ""

    with (
        patch("connector_registry.shutil.which", side_effect=fake_which),
        patch("connector_registry._run", side_effect=fake_run),
    ):
        result = connectors_status()

    linkedin = next(item for item in result["connectors"] if item["id"] == "linkedin")
    assert linkedin["installed"] is True
    assert linkedin["auth_state"] == "ok"
    assert linkedin["auth_detail"] == {"scanner_importable": True}
    assert linkedin["required_env"] == [{"name": "INBOX_ENABLE_LINKEDIN_SCRAPER", "present": True}]
    assert linkedin["sync_ready"] is False
    assert any("LinkedIn" in step for step in linkedin["remediation"])


def test_search_connectors_normalizes_json_results():
    from connector_registry import search_connectors

    with (
        patch("connector_registry.shutil.which", return_value="/usr/local/bin/wacli"),
        patch(
            "connector_registry._run",
            return_value=(
                0,
                '{"messages":[{"id":"m1","chat_name":"Alice","text":"hello there","timestamp":"2026-05-12T01:00:00"}]}',
                "",
            ),
        ) as mock_run,
    ):
        result = search_connectors("hello", sources=["whatsapp"], limit=5)

    mock_run.assert_called_once()
    assert result["total"] == 1
    assert result["results"][0]["source"] == "whatsapp"
    assert result["results"][0]["id"] == "m1"
    assert result["results"][0]["title"] == "Alice"
    assert result["errors"] == []


def test_search_connectors_rejects_malformed_json_output():
    from connector_registry import search_connectors

    with (
        patch("connector_registry.shutil.which", return_value="/usr/local/bin/wacli"),
        patch("connector_registry._run", return_value=(0, "not json", "")),
    ):
        result = search_connectors("hello", sources=["whatsapp"], limit=5)

    assert result["total"] == 0
    assert result["results"] == []
    assert result["errors"] == [
        {"source": "whatsapp", "error": "malformed_json", "detail": "not json"}
    ]


def test_partition_search_sources_hides_connector_markers_from_callers():
    from connector_registry import partition_search_sources

    built_in, connector = partition_search_sources(
        ["gmail", "connector:whatsapp", "connector:missing", "connectors"]
    )

    assert built_in == ["gmail"]
    assert connector == ["all"]


def test_merge_connector_search_results_sorts_and_caps_results():
    from connector_registry import merge_connector_search_results

    result = {
        "query": "hello",
        "total": 1,
        "results": [{"source": "gmail", "timestamp": "2026-05-12T00:00:00"}],
    }
    connector_result = {
        "results": [
            {"source": "whatsapp", "timestamp": "2026-05-12T02:00:00"},
            {"source": "discord", "timestamp": "2026-05-12T01:00:00"},
        ],
        "errors": [{"source": "twitter", "error": "not_installed"}],
    }

    merged = merge_connector_search_results(result, connector_result, limit=2)

    assert [item["source"] for item in merged["results"]] == ["whatsapp", "discord"]
    assert merged["total"] == 2
    assert merged["connector_errors"] == [{"source": "twitter", "error": "not_installed"}]
    assert result["results"] == [{"source": "gmail", "timestamp": "2026-05-12T00:00:00"}]


def test_sync_plan_defaults_to_dry_run():
    from connector_registry import connector_sync_plan

    result = connector_sync_plan("whatsapp")

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["command"] == ["wacli", "sync", "--once"]
    assert result["approval_required_for_execute"] is True


def test_sync_execute_requires_approval_before_binary_lookup(monkeypatch):
    from connector_registry import connector_sync_plan

    monkeypatch.delenv("INBOX_APPROVAL_LEASE", raising=False)
    with patch("connector_registry.shutil.which") as mock_which:
        result = connector_sync_plan("whatsapp", execute=True)

    assert result["ok"] is False
    assert result["error"] == "approval_required"
    assert result["dry_run"] is True
    assert result["approval_required_for_execute"] is True
    mock_which.assert_not_called()


def test_sync_execute_with_approval_can_run_installed_connector(monkeypatch):
    from connector_registry import connector_sync_plan

    monkeypatch.setenv("INBOX_APPROVAL_LEASE", "lease-test")
    with (
        patch("connector_registry.shutil.which", return_value="/usr/local/bin/wacli"),
        patch("connector_registry._run", return_value=(0, '{"ok":true}', "")) as mock_run,
    ):
        result = connector_sync_plan("whatsapp", execute=True)

    assert result["ok"] is True
    assert result["dry_run"] is False
    mock_run.assert_called_once_with(("wacli", "sync", "--once"), timeout=60)


def test_registry_does_not_expose_send_delete_or_calendar_write_commands():
    from connector_registry import connectors_status

    result = connectors_status()
    forbidden = {"send", "delete", "calendar-write", "calendar_write"}

    for connector in result["connectors"]:
        command_names = set(connector["commands"])
        assert command_names.isdisjoint(forbidden)
        for action in connector["action_policy"]["mutations"]:
            if action["action"] in {"send", "delete", "calendar_write"}:
                assert action["policy"] == "approval_required"
                assert action["executor"] == "outside_connector_registry"


def test_unknown_sync_connector_reports_error():
    from connector_registry import connector_sync_plan

    result = connector_sync_plan("missing")

    assert result["ok"] is False
    assert result["error"] == "unknown_connector"


# ---------------------------------------------------------------------------
# _run error handling (lines 375-380)
# ---------------------------------------------------------------------------


def test_run_handles_file_not_found_error():
    """_run returns (127, '', str(exc)) when the binary cannot be found."""
    from connector_registry import _run

    with patch(
        "connector_registry.subprocess.run",
        side_effect=FileNotFoundError("no such binary"),
    ):
        code, stdout, stderr = _run(("no_such_binary",))

    assert code == 127
    assert stdout == ""
    assert "no such binary" in stderr


def test_run_handles_timeout_expired():
    """_run returns (124, stdout, stderr) when the subprocess times out."""
    from connector_registry import _run

    exc = subprocess.TimeoutExpired(
        ["slow_cmd"], 5, output="partial out", stderr="timeout detail"
    )
    with patch("connector_registry.subprocess.run", side_effect=exc):
        code, stdout, stderr = _run(("slow_cmd",), timeout=5)

    assert code == 124
    assert stdout == "partial out"
    assert stderr == "timeout detail"


# ---------------------------------------------------------------------------
# _parse_json (line 386)
# ---------------------------------------------------------------------------


def test_parse_json_empty_string_returns_none():
    """_parse_json returns None for an empty/whitespace string."""
    from connector_registry import _parse_json

    assert _parse_json("") is None


# ---------------------------------------------------------------------------
# connector_status — installed but no auth command (line 435)
# ---------------------------------------------------------------------------


def test_connector_status_installed_without_auth_command():
    """connector_status sets auth_state='unknown' when installed but no auth_command."""
    from connector_registry import ConnectorDefinition, connector_status

    connector = ConnectorDefinition(
        id="test_no_auth",
        label="Test No Auth",
        binary="python3",
        category="test",
    )
    result = connector_status(connector)

    assert result["installed"] is True
    assert result["auth_state"] == "unknown"


# ---------------------------------------------------------------------------
# _normalize_search_results branches (lines 549, 559, 562, 567-577)
# ---------------------------------------------------------------------------


def test_normalize_search_results_empty_raw_returns_empty():
    """_normalize_search_results returns [] when raw is empty/falsy (parsed→None)."""
    from connector_registry import _normalize_search_results

    result = _normalize_search_results("whatsapp", "")
    assert result == []


def test_normalize_search_results_dict_without_list_key():
    """_normalize_search_results wraps a dict with no recognized list key."""
    import json

    from connector_registry import _normalize_search_results

    result = _normalize_search_results("whatsapp", json.dumps({"unrecognized": "val"}))
    assert len(result) == 1
    assert result[0]["source"] == "whatsapp"
    assert result[0]["title"] == "whatsapp"


def test_normalize_search_results_non_dict_non_list_returns_empty():
    """_normalize_search_results returns [] when parsed is not a dict or list (e.g. int)."""
    from connector_registry import _normalize_search_results

    result = _normalize_search_results("whatsapp", "42")
    assert result == []


def test_normalize_search_results_non_dict_items_use_defaults():
    """_normalize_search_results builds default entries for non-dict list items."""
    import json

    from connector_registry import _normalize_search_results

    result = _normalize_search_results("whatsapp", json.dumps(["hello", 123]))
    assert len(result) == 2
    assert result[0]["source"] == "whatsapp"
    assert result[0]["title"] == "whatsapp"
    assert result[0]["snippet"] == "hello"
    assert result[1]["snippet"] == "123"


# ---------------------------------------------------------------------------
# search_connectors edge cases (lines 617, 630, 632-633, 637-644)
# ---------------------------------------------------------------------------


def test_search_connectors_empty_query_returns_empty():
    """search_connectors returns an empty result set for blank queries."""
    from connector_registry import search_connectors

    result = search_connectors("   ")
    assert result["query"] == "   "
    assert result["total"] == 0
    assert result["results"] == []
    assert result["errors"] == []


def test_search_connectors_skips_connector_without_search_command():
    """search_connectors skips connectors that have no search_command (e.g. LinkedIn)."""
    from connector_registry import search_connectors

    result = search_connectors("hello", sources=["linkedin"])
    # LinkedIn has no search_command, so it's skipped entirely — no results, no errors.
    assert result["total"] == 0
    assert result["results"] == []


def test_search_connectors_records_not_installed_error():
    """search_connectors records 'not_installed' when binary is missing."""
    from connector_registry import search_connectors

    with (
        patch("connector_registry.shutil.which", return_value=None),
    ):
        result = search_connectors("hello", sources=["whatsapp"])

    assert result["total"] == 0
    assert len(result["errors"]) == 1
    assert result["errors"][0]["source"] == "whatsapp"
    assert result["errors"][0]["error"] == "not_installed"


def test_search_connectors_records_nonzero_exit_code():
    """search_connectors records an error when the connector binary exits non-zero."""
    from connector_registry import search_connectors

    with (
        patch("connector_registry.shutil.which", return_value="/usr/bin/wacli"),
        patch(
            "connector_registry._run",
            return_value=(2, "something broke", "stderr detail"),
        ),
    ):
        result = search_connectors("hello", sources=["whatsapp"])

    assert result["total"] == 0
    assert len(result["errors"]) == 1
    assert result["errors"][0]["source"] == "whatsapp"
    assert result["errors"][0]["exit_code"] == 2
    assert "stderr detail" in result["errors"][0]["error"]


# ---------------------------------------------------------------------------
# connector_sync_plan edge cases (lines 667, 695)
# ---------------------------------------------------------------------------


def test_connector_sync_plan_no_sync_command():
    """connector_sync_plan returns 'sync_not_supported' for connectors without sync."""
    from connector_registry import connector_sync_plan

    result = connector_sync_plan("linkedin")
    assert result["ok"] is False
    assert result["error"] == "sync_not_supported"
    assert result["command"] == []


def test_connector_sync_plan_execute_binary_not_found():
    """connector_sync_plan returns 'not_installed' when execute=True and binary missing."""
    import os

    from connector_registry import connector_sync_plan

    with (
        patch.dict(os.environ, {"INBOX_APPROVAL_LEASE": "lease-test"}),
        patch("connector_registry.shutil.which", return_value=None),
    ):
        result = connector_sync_plan("whatsapp", execute=True)

    assert result["ok"] is False
    assert result["error"] == "not_installed"
