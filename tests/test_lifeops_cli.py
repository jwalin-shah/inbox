from __future__ import annotations

import json

import pytest

from lifeops_cli import main

pytestmark = pytest.mark.safe


def test_execute_task_create_is_plan_only_and_traceable(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LIFEOPS_REGISTRY_PATH", str(tmp_path / "registry.json"))
    monkeypatch.setenv("LIFEOPS_TRACE_PATH", str(tmp_path / "traces.jsonl"))

    assert main(["execute", "task.create", "--title", "Call Nathan"]) == 0
    output = json.loads(capsys.readouterr().out)
    command_id = output["envelope"]["command_id"]

    assert output["result"]["status"] == "PLANNED"
    assert main(["trace", command_id]) == 0
    trace = json.loads(capsys.readouterr().out)
    assert trace["command_id"] == command_id
    assert trace["result"]["live_execution"] is False


def test_live_cli_refuses_unproven_route(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LIFEOPS_REGISTRY_PATH", str(tmp_path / "registry.json"))
    monkeypatch.setenv("LIFEOPS_TRACE_PATH", str(tmp_path / "traces.jsonl"))

    assert main(["execute", "task.create", "--title", "Call Nathan", "--live"]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "BLOCKED"
    assert "proven available" in output["reason"]
