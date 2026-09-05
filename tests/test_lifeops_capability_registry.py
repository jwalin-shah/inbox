from __future__ import annotations

import json

import pytest

from lifeops.capability_registry import CapabilityRegistry

pytestmark = pytest.mark.safe


def test_sync_reads_openclaw_metadata_without_marking_routes_available(tmp_path):
    responses = {
        ("fake", "--version"): "OpenClaw test\n",
        ("fake", "plugins", "list", "--json"): json.dumps(
            {"plugins": [{"id": "google-workspace", "status": "loaded", "enabled": True, "toolNames": ["task.create"]}]}
        ),
        ("fake", "mcp", "list", "--json"): json.dumps(
            {"inbox_tasks_approval": {"command": "inbox-mcp-tasks"}}
        ),
    }

    snapshot = CapabilityRegistry(tmp_path / "registry.json").sync(
        openclaw_command="fake",
        runner=lambda argv: responses[tuple(argv)],
    )

    google_route = snapshot["routes"][0]
    assert snapshot["openclaw"]["plugin_count"] == 1
    assert google_route["installed"] is True
    assert google_route["available"] is None
    assert snapshot["errors"] == []


def test_sync_records_malformed_or_missing_openclaw_data_as_degraded(tmp_path):
    def broken_runner(argv):
        if tuple(argv)[1] == "--version":
            raise OSError("openclaw missing")
        return "not json"

    snapshot = CapabilityRegistry(tmp_path / "registry.json").sync(
        openclaw_command="fake", runner=broken_runner
    )

    assert snapshot["errors"]
    assert snapshot["readiness"] == "degraded"


def test_resolve_fails_closed_for_live_route_without_probe(tmp_path):
    registry = CapabilityRegistry(tmp_path / "registry.json")
    registry.sync(
        openclaw_command="fake",
        runner=lambda argv: {
            ("fake", "--version"): "OpenClaw test",
            ("fake", "plugins", "list", "--json"): '{"plugins": []}',
            ("fake", "mcp", "list", "--json"): '{"inbox_tasks_approval": {}}',
        }[tuple(argv)],
    )

    assert registry.resolve("task.create")["route_id"] == "openclaw/inbox_tasks_approval"
    with pytest.raises(LookupError, match="proven available"):
        registry.resolve("task.create", require_available=True)


def test_unknown_capability_has_no_implicit_route(tmp_path):
    with pytest.raises(LookupError, match="no route candidates"):
        CapabilityRegistry(tmp_path / "registry.json").resolve("calendar.create")
