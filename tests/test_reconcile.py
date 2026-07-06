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


# --- _fingerprint fallback paths (lines 74-79) ---


def test_fingerprint_falls_back_to_token_based_when_no_source_or_id():
    """When an item has no source and no id, _fingerprint uses title+snippet tokens."""
    item = {"title": "Hardware TPM screening", "snippet": "screening questions"}
    fp = reconcile._fingerprint(item)
    # Token-based fallback: sorted unique tokens from title+snippet, first 16
    assert fp == "hardware questions screening tpm"


def test_fingerprint_uses_sha256_when_no_tokens():
    """When an item has no source, no id, and no tokenizable text, fall back to sha256."""
    item = {"field": "irrelevant"}
    fp = reconcile._fingerprint(item)
    # sha256 digest of the json-serialized item, first 16 hex chars
    assert len(fp) == 16
    assert all(c in "0123456789abcdef" for c in fp)


# --- _match_state candidate and weak paths (lines 86-87) ---


def test_match_state_returns_candidate_for_mid_scores():
    """Scores between CANDIDATE_SCORE (0.35) and CONFIRMED_SCORE (0.75) return 'candidate'."""
    assert reconcile._match_state(0.35) == "candidate"
    assert reconcile._match_state(0.50) == "candidate"
    assert reconcile._match_state(0.74) == "candidate"


def test_match_state_returns_weak_for_low_scores():
    """Scores below CANDIDATE_SCORE (0.35) return 'weak'."""
    assert reconcile._match_state(0.0) == "weak"
    assert reconcile._match_state(0.10) == "weak"
    assert reconcile._match_state(0.34) == "weak"


# --- format_text edge cases ---


def test_format_text_shows_duplicates_removed_when_present():
    """Line 249: duplicate_results_removed > 0 emits a duplicates line."""
    report = {
        "query": "test",
        "summary": {
            "total_hits": 1,
            "channels_with_hits": 1,
            "channels_with_errors": 0,
            "channels_confirmed": 0,
            "channels_candidates": 0,
            "duplicate_results_removed": 3,
        },
        "channels": {},
        "timeline": [],
    }
    text = reconcile.format_text(report)
    assert "Duplicates removed: 3" in text


def test_format_text_shows_errors_when_channels_have_errors():
    """Line 251: channels_with_errors > 0 emits an errors line."""
    report = {
        "query": "test",
        "summary": {
            "total_hits": 0,
            "channels_with_hits": 0,
            "channels_with_errors": 2,
            "channels_confirmed": 0,
            "channels_candidates": 0,
        },
        "channels": {},
        "timeline": [],
    }
    text = reconcile.format_text(report)
    assert "Errors: 2 channel(s)" in text


def test_format_text_renders_error_channel_with_error_detail():
    """Lines 272-273: channels in error state (not 'ok' and not 'empty') show error detail."""
    report = {
        "query": "test",
        "summary": {
            "total_hits": 0,
            "channels_with_hits": 0,
            "channels_with_errors": 1,
            "channels_confirmed": 0,
            "channels_candidates": 0,
        },
        "channels": {
            "discord": {
                "state": "not_installed",
                "hits": 0,
                "results": [],
                "error": {"source": "discord", "error": "not_installed"},
            },
        },
        "timeline": [],
    }
    text = reconcile.format_text(report)
    assert "discord: not_installed" in text


def test_format_text_renders_error_channel_with_raw_state_when_no_error_detail():
    """Lines 272-273: when error dict is missing, falls back to raw state string."""
    report = {
        "query": "test",
        "summary": {
            "total_hits": 0,
            "channels_with_hits": 0,
            "channels_with_errors": 1,
            "channels_confirmed": 0,
            "channels_candidates": 0,
        },
        "channels": {
            "broken": {
                "state": "timeout",
                "hits": 0,
                "results": [],
                "error": {},
            },
        },
        "timeline": [],
    }
    text = reconcile.format_text(report)
    assert "broken: timeout" in text
