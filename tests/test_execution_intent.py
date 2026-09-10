"""Typed ExecutionIntent contract: bounded fields, fail-closed validation."""

from __future__ import annotations

import pytest

from event_store import EventStore
from execution_intent import (
    EXECUTION_INTENT_EVENT_TYPE,
    EXECUTION_MODES,
    REQUESTED_BACKENDS,
    ExecutionIntentValidationError,
    build_execution_intent_event,
    validate_execution_mode,
    validate_requested_backend,
    validate_work_ref,
)

VALID_WORK_REF = "wrk_abc123def4567890"


def test_valid_work_ref_prefixes_are_accepted():
    for ref in ("wrk_abc123def456", "apr_abc123def456", "sched_prop_abc123def456", "evt_abc123def456"):
        assert validate_work_ref(ref) == ref


def test_malformed_work_refs_are_rejected():
    for bad in ("", "  ", "../etc/passwd", "shell:rm -rf /", "totally-made-up-id", "wrk_short", "wrk_ evil"):
        with pytest.raises(ExecutionIntentValidationError, match="work_ref"):
            validate_work_ref(bad)


def test_requested_backend_defaults_and_is_bounded():
    assert validate_requested_backend("") == "unspecified"
    assert validate_requested_backend(None) == "unspecified"
    for backend in REQUESTED_BACKENDS:
        assert validate_requested_backend(backend) == backend
    with pytest.raises(ExecutionIntentValidationError, match="requested_backend"):
        validate_requested_backend("ssh_shell")


def test_execution_mode_is_required_and_bounded():
    with pytest.raises(ExecutionIntentValidationError, match="execution_mode"):
        validate_execution_mode("")
    for mode in EXECUTION_MODES:
        assert validate_execution_mode(mode) == mode
    with pytest.raises(ExecutionIntentValidationError, match="execution_mode"):
        validate_execution_mode("autonomous")


def test_build_execution_intent_event_is_a_capture_event_shape():
    event = build_execution_intent_event(
        work_ref=VALID_WORK_REF, execution_mode="dry_run", requested_backend="mac_controller"
    )
    assert event.event_type == EXECUTION_INTENT_EVENT_TYPE
    assert event.source == "inbox"
    assert event.source_object_id == VALID_WORK_REF
    assert event.payload["work_ref"] == VALID_WORK_REF
    assert event.payload["execution_mode"] == "dry_run"
    assert event.payload["requested_backend"] == "mac_controller"
    assert event.payload["execution_claimed"] is False
    assert event.provenance["source_ref"] == f"inbox:execution_intent/{VALID_WORK_REF}"


def test_build_execution_intent_event_is_appendable_to_event_store(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    event = build_execution_intent_event(work_ref=VALID_WORK_REF, execution_mode="supervised")
    stored, result = store.append(event)
    assert result == "created"
    assert stored.event_id.startswith("evt_")
    fetched = store.get(stored.event_id)
    assert fetched is not None
    assert fetched.payload["execution_mode"] == "supervised"


def test_build_execution_intent_event_rejects_bad_inputs():
    with pytest.raises(ExecutionIntentValidationError):
        build_execution_intent_event(work_ref="not-a-ref", execution_mode="dry_run")
    with pytest.raises(ExecutionIntentValidationError):
        build_execution_intent_event(work_ref=VALID_WORK_REF, execution_mode="live")
    with pytest.raises(ExecutionIntentValidationError):
        build_execution_intent_event(
            work_ref=VALID_WORK_REF, execution_mode="dry_run", requested_backend="claude_code_cli"
        )
