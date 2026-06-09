"""Tests for the local connector registry."""

from __future__ import annotations

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
