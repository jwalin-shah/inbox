"""EventStore atom: append-only, deterministic identity, idempotent retry."""

from __future__ import annotations

import sqlite3

import pytest

from event_store import (
    CaptureEvent,
    EventStore,
    EventStoreConflict,
    EventStoreValidationError,
    MAX_PAYLOAD_BYTES,
)


def _event(**overrides) -> CaptureEvent:
    body = {
        "source": "manual",
        "source_object_id": "capture-1",
        "observed_at": "2026-09-05T18:00:00+00:00",
        "occurred_at": "2026-09-05T17:59:00+00:00",
        "event_type": "manual.capture",
        "payload": {"text": "Nathan said 100 drones may cost $6 each."},
        "provenance": {"source_ref": "manual:test/capture-1"},
    }
    body.update(overrides)
    return CaptureEvent.create(**body)


def test_append_is_created_then_already_exists_on_exact_retry(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    event = _event()

    stored, result = store.append(event)
    retry, retry_result = store.append(event)

    assert result == "created"
    assert retry_result == "already_exists"
    assert stored.event_id == retry.event_id == event.event_id
    assert store.count() == 1
    assert not hasattr(store, "update")
    assert not hasattr(store, "delete")


def test_identity_is_deterministic_for_the_same_observation(tmp_path):
    first = _event()
    second = _event()
    assert first.event_id == second.event_id
    assert first.identity_digest == second.identity_digest


def test_missing_provenance_is_rejected():
    with pytest.raises(EventStoreValidationError, match="provenance"):
        _event(provenance={})


def test_malformed_source_locator_is_rejected():
    with pytest.raises(EventStoreValidationError, match="source_ref"):
        _event(provenance={"source_ref": "file:///etc/passwd"})
    with pytest.raises(EventStoreValidationError, match="source_ref"):
        _event(provenance={"source_ref": "javascript:alert(1)"})
    with pytest.raises(EventStoreValidationError, match="source_ref"):
        _event(provenance={"source_ref": "manual:../escape"})


def test_oversized_payload_is_rejected():
    with pytest.raises(EventStoreValidationError, match="payload"):
        _event(payload={"text": "x" * (MAX_PAYLOAD_BYTES + 1)})


def test_conflicting_same_id_payload_is_rejected(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    first, _ = store.append(_event())
    with pytest.raises(EventStoreConflict):
        store.append(
            _event(
                event_id=first.event_id,
                payload={"text": "different observation"},
            )
        )
    assert store.count() == 1


def test_supplied_event_id_digest_mismatch_is_rejected(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    with pytest.raises(EventStoreValidationError, match="event_id"):
        store.append(_event(event_id="evt_deadbeefdeadbeefdeadbeefdeadbeef"))
    assert store.count() == 0


def test_interrupted_retry_does_not_duplicate(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    event = _event()
    store.append(event)
    # Simulate client retry after a dropped response.
    stored, result = store.append(event)
    assert result == "already_exists"
    assert store.count() == 1
    assert store.get(event.event_id).payload == event.payload


def test_sqlite_rejects_update_and_delete(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    event = _event()
    store.append(event)
    with sqlite3.connect(store.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "UPDATE events SET source = 'tamper' WHERE event_id = ?", (event.event_id,)
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM events WHERE event_id = ?", (event.event_id,))
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_event_store_module_does_not_call_bridge_or_spawn():
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1] / "event_store.py"
    ).read_text()
    lowered = source.lower()
    assert "bridge" not in lowered
    assert "spawn" not in lowered
    assert "subprocess" not in lowered
