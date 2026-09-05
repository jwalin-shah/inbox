from __future__ import annotations

import json
import subprocess
import sys

import pytest

from inbox_bridge_adapter import (
    BRIDGE_CONTRACT_VERSION,
    event_from_memory_entry,
    event_from_message,
)


def test_memory_entry_emits_stable_provider_neutral_event() -> None:
    event = event_from_memory_entry(
        {
            "id": 7,
            "content": "Capture this for Bridge.",
            "source": "manual",
            "created_at": "2026-08-23T20:00:00+00:00",
            "metadata": {"kind": "capture"},
            "role": "implement",
            "model": "legacy-model",
            "provider": "legacy-provider",
            "verify": ["legacy command"],
        }
    )

    assert event["version"] == BRIDGE_CONTRACT_VERSION
    assert event["id"] == "inbox:memory:7"
    assert event["source"] == "inbox"
    assert event["payload"] == {
        "text": "Capture this for Bridge.",
        "subject": "",
        "external_ref": "manual",
        "metadata": {"kind": "capture"},
    }
    assert "role" not in event
    assert "model" not in event
    assert "provider" not in event
    assert "verify" not in event


def test_message_event_has_stable_source_identity() -> None:
    event = event_from_message(
        {
            "message_id": "abc",
            "source": "imessage",
            "body": "Hello",
            "subject": "Greeting",
            "occurred_at": "2026-08-23T20:00:00Z",
        }
    )
    assert event["id"] == "inbox:message:imessage:abc"
    assert event["kind"] == "inbox.message"
    assert event["payload"]["text"] == "Hello"


def test_missing_timestamp_fails_closed() -> None:
    with pytest.raises(ValueError, match="requires one of"):
        event_from_memory_entry({"id": 7, "content": "No timestamp"})


def test_cli_emits_json_event_for_bridge_handshake() -> None:
    proc = subprocess.run(
        [sys.executable, "inbox_bridge_adapter.py"],
        input=json.dumps(
            {
                "id": 8,
                "content": "CLI capture",
                "created_at": "2026-08-23T20:00:00Z",
            }
        ),
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    event = json.loads(proc.stdout)
    assert event["id"] == "inbox:memory:8"
    assert event["version"] == BRIDGE_CONTRACT_VERSION
