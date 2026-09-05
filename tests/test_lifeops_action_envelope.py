from __future__ import annotations

import pytest

from lifeops.action_envelope import ActionEnvelope, TraceStore

pytestmark = pytest.mark.safe


def _envelope(**overrides):
    values = {
        "capability": "task.create",
        "target": "personal",
        "inputs": {"title": "Call Nathan"},
        "risk": "R1",
        "route": "openclaw/inbox_tasks_approval",
        "expected_postcondition": "task exists exactly once",
    }
    values.update(overrides)
    return ActionEnvelope.create(**values)


def test_envelope_has_stable_identity_and_round_trips():
    envelope = _envelope()
    restored = ActionEnvelope.from_dict(envelope.to_dict())

    assert envelope.command_id.startswith("cmd_")
    assert envelope.intent_id.startswith("intent_")
    assert restored == envelope


def test_envelope_rejects_invalid_risk_and_secret_fields():
    with pytest.raises(ValueError, match="risk"):
        _envelope(risk="R9")
    with pytest.raises(ValueError, match="secret-looking"):
        _envelope(inputs={"title": "Call Nathan", "oauth_token": "do-not-store"})


def test_trace_store_is_append_only_by_command_id(tmp_path):
    store = TraceStore(tmp_path / "traces.jsonl")
    envelope = _envelope()
    record = store.append(envelope, {"status": "PLANNED"})

    assert record["command_id"] == envelope.command_id
    assert store.get(envelope.command_id) == record
    with pytest.raises(ValueError, match="already exists"):
        store.append(envelope, {"status": "PLANNED"})


def test_trace_store_rejects_secret_result_fields(tmp_path):
    with pytest.raises(ValueError, match="secret-looking"):
        TraceStore(tmp_path / "traces.jsonl").append(
            _envelope(),
            {"status": "BLOCKED", "access_token": "redacted"},
        )
