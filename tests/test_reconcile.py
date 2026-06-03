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
    assert report["channels"]["whatsapp"]["state"] == "ok"
    assert report["channels"]["whatsapp"]["hits"] == 1
    assert report["channels"]["discord"]["state"] == "not_installed"
    assert report["timeline"] == search_payload["results"]


def test_build_report_marks_empty_channels_without_errors():
    with patch(
        "scripts.reconcile.search_connectors",
        return_value={"query": "quiet", "total": 0, "results": [], "errors": []},
    ):
        report = reconcile.build_report("quiet", sources=["whatsapp"], limit=3)

    assert report["channels"]["whatsapp"]["state"] == "empty"
    assert report["channels"]["whatsapp"]["hits"] == 0
    assert report["summary"]["channels_empty"] == 1


def test_format_text_includes_channel_states():
    report = {
        "query": "hello",
        "summary": {
            "total_hits": 1,
            "channels_with_hits": 1,
            "channels_with_errors": 0,
        },
        "channels": {
            "whatsapp": {
                "state": "ok",
                "hits": 1,
                "results": [{"title": "Alice", "snippet": "hello there"}],
                "error": None,
            },
            "discord": {"state": "empty", "hits": 0, "results": [], "error": None},
        },
        "timeline": [
            {
                "source": "whatsapp",
                "timestamp": "2026-05-12T01:00:00",
                "title": "Alice",
                "snippet": "hello there",
            }
        ],
    }

    text = reconcile.format_text(report)

    assert "Reconcile: hello" in text
    assert "whatsapp: 1 hit(s)" in text
    assert "discord: no hits" in text
    assert "[whatsapp]" in text


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
