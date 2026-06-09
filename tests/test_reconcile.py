"""Tests for the cross-channel reconcile CLI."""

from __future__ import annotations

import json
from unittest.mock import patch

from scripts import reconcile


def test_build_report_groups_hits_and_errors_by_channel():
    search_payload = {
        "query": "meeting",
        "total": 1,
        "results": [
            {
                "source": "whatsapp",
                "id": "m1",
                "title": "Alice",
                "snippet": "meeting tomorrow",
                "timestamp": "2026-05-12T02:00:00",
            }
        ],
        "errors": [{"source": "discord", "error": "not_installed"}],
    }

    with patch("scripts.reconcile.search_connectors", return_value=search_payload):
        report = reconcile.build_report("meeting", sources=["whatsapp", "discord"], limit=5)

    assert report["schema_version"] == reconcile.SCHEMA_VERSION
    assert report["summary"]["total_hits"] == 1
    assert report["summary"]["channels_with_hits"] == 1
    assert report["summary"]["channels_with_errors"] == 1
    assert report["summary"]["channels_confirmed"] == 1
    assert report["channels"]["whatsapp"]["state"] == "ok"
    assert report["channels"]["whatsapp"]["hits"] == 1
    assert report["channels"]["whatsapp"]["reconciliation"]["state"] == "confirmed"
    assert report["channels"]["whatsapp"]["reconciliation"]["matched_terms"] == ["meeting"]
    assert report["channels"]["discord"]["state"] == "not_installed"
    assert report["timeline"][0]["id"] == "m1"
    assert report["timeline"][0]["reconciliation"]["score"] == 0.9


def test_build_report_marks_empty_channels_without_errors():
    with patch(
        "scripts.reconcile.search_connectors",
        return_value={"query": "quiet", "total": 0, "results": [], "errors": []},
    ):
        report = reconcile.build_report("quiet", sources=["whatsapp"], limit=3)

    assert report["channels"]["whatsapp"]["state"] == "empty"
    assert report["channels"]["whatsapp"]["hits"] == 0
    assert report["channels"]["whatsapp"]["reconciliation"]["state"] == "empty"
    assert report["summary"]["channels_empty"] == 1


def test_build_report_dedupes_and_sorts_by_match_strength():
    search_payload = {
        "query": "hardware screening",
        "total": 3,
        "results": [
            {
                "source": "google",
                "id": "older",
                "title": "Recruiter",
                "snippet": "screening",
                "timestamp": "2026-05-01T01:00:00",
            },
            {
                "source": "google",
                "id": "dup",
                "title": "Hardware TPM screening",
                "snippet": "hardware screening questions",
                "timestamp": "2026-05-02T01:00:00",
            },
            {
                "source": "google",
                "id": "dup",
                "title": "Hardware TPM screening",
                "snippet": "hardware screening questions",
                "timestamp": "2026-05-03T01:00:00",
            },
        ],
        "errors": [],
    }

    with patch("scripts.reconcile.search_connectors", return_value=search_payload):
        report = reconcile.build_report("hardware screening", sources=["google"], limit=5)

    assert report["summary"]["duplicate_results_removed"] == 1
    assert report["summary"]["total_hits"] == 2
    assert report["summary"]["raw_hits"] == 3
    assert [item["id"] for item in report["timeline"]] == ["dup", "older"]
    assert report["channels"]["google"]["reconciliation"]["state"] == "confirmed"
    assert report["channels"]["google"]["reconciliation"]["matched_terms"] == [
        "hardware",
        "screening",
    ]


def test_format_text_includes_channel_states():
    report = {
        "query": "hello",
        "summary": {
            "total_hits": 1,
            "channels_with_hits": 1,
            "channels_with_errors": 0,
            "channels_confirmed": 1,
            "channels_candidates": 0,
        },
        "channels": {
            "whatsapp": {
                "state": "ok",
                "hits": 1,
                "results": [
                    {
                        "title": "Alice",
                        "snippet": "hello there",
                        "reconciliation": {"score": 1.0},
                    }
                ],
                "error": None,
                "reconciliation": {
                    "state": "confirmed",
                    "best_score": 1.0,
                    "matched_terms": ["hello"],
                },
            },
            "discord": {"state": "empty", "hits": 0, "results": [], "error": None},
        },
        "timeline": [
            {
                "source": "whatsapp",
                "timestamp": "2026-05-12T01:00:00",
                "title": "Alice",
                "snippet": "hello there",
                "reconciliation": {"score": 1.0},
            }
        ],
    }

    text = reconcile.format_text(report)

    assert "Reconcile: hello" in text
    assert "whatsapp: 1 hit(s), confirmed match (1.0)" in text
    assert "matched terms: hello" in text
    assert "discord: no hits" in text
    assert "[whatsapp score=1.0]" in text


def test_main_json_mode_prints_report(capsys):
    with patch(
        "scripts.reconcile.build_report",
        return_value={"query": "ping", "summary": {}},
    ):
        exit_code = reconcile.main(["ping", "--json", "--sources", "whatsapp"])

    assert exit_code == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["query"] == "ping"


def test_main_delegates_to_search_connectors():
    with (
        patch(
            "scripts.reconcile.search_connectors",
            return_value={"query": "hi", "total": 0, "results": [], "errors": []},
        ) as mock_search,
        patch("scripts.reconcile.build_report", wraps=reconcile.build_report) as mock_build,
    ):
        reconcile.main(["hi", "--sources", "whatsapp,imessage", "--limit", "7"])

    mock_build.assert_called_once()
    mock_search.assert_called_once_with("hi", sources=["whatsapp", "imessage"], limit=7)
