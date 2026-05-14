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
    assert google["installed"] is False
    assert google["auth_state"] == "not_installed"


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


def test_unknown_sync_connector_reports_error():
    from connector_registry import connector_sync_plan

    result = connector_sync_plan("missing")

    assert result["ok"] is False
    assert result["error"] == "unknown_connector"
