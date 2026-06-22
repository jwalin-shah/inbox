"""Fixture-backed tests for the inbox/calendar/todo control surface."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import inbox_calendar_todo_control as control

FIXTURE = Path(__file__).parent / "fixtures" / "inbox_calendar_todo_control.json"
pytestmark = pytest.mark.safe


def test_build_report_extracts_dedupes_and_reconciles_from_fixture():
    report = control.build_report(control.load_fixture(FIXTURE), now="2026-06-05T12:00:00-07:00")

    assert report["schema_version"] == control.SCHEMA_VERSION
    assert report["dry_run"] is True
    assert report["invariants"]["external_mutations"] is False
    assert report["summary"]["actionable_items"] == 3

    states_by_title = {item["title"]: item["state"] for item in report["actionable_items"]}
    assert states_by_title["review Stanford insurance paperwork"] == "already_tracked"
    assert states_by_title["send hardware TPM screening answers"] == "new"
    assert states_by_title["hold dentist follow-up"] == "new"

    proposal_kinds = {proposal["kind"] for proposal in report["proposed_changes"]}
    assert proposal_kinds == {"create_task", "calendar_hold"}
    assert all(proposal["approval"]["required"] is True for proposal in report["proposed_changes"])
    assert all(proposal["execute"] is False for proposal in report["proposed_changes"])


def test_every_action_and_proposal_links_to_evidence():
    report = control.build_report(control.load_fixture(FIXTURE))
    evidence_ids = {item["id"] for item in report["evidence"]}

    assert evidence_ids
    for item in report["actionable_items"]:
        assert item["evidence_ids"]
        assert set(item["evidence_ids"]) <= evidence_ids
    for proposal in report["proposed_changes"]:
        assert proposal["evidence_ids"]
        assert set(proposal["evidence_ids"]) <= evidence_ids
        assert "Evidence:" in proposal["payload"].get("notes", proposal["payload"].get("description", ""))


def test_default_source_status_respects_deferred_custom_clis():
    with patch("scripts.inbox_calendar_todo_control.shutil.which", return_value=None):
        report = control.build_report({})

    states = {source["id"]: source["state"] for source in report["sources"]}
    assert states["gmail"] == "configured_external_connector"
    assert states["google_calendar"] == "configured_external_connector"
    assert states["google_tasks"] == "configured_external_connector"
    assert states["gog"] == "not_installed"
    assert states["imsg"] == "not_installed"
    assert states["wacli"] == "not_installed"


def test_cli_json_dry_run_outputs_proposals_without_mutation(capsys):
    exit_code = control.main(["--fixture", str(FIXTURE), "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["invariants"]["provider_calls"] is False
    assert payload["invariants"]["connector_binaries_executed"] is False
    assert payload["invariants"]["external_mutations"] is False
    assert payload["summary"]["proposed_changes"] == 2


def test_cli_refuses_execute(capsys):
    exit_code = control.main(["--fixture", str(FIXTURE), "--execute"])

    assert exit_code == 2
    assert "Refusing --execute" in capsys.readouterr().err
