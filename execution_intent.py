"""Typed, durable ExecutionIntent contract (governed-execution-surface slice 1).

Prep for a future Mac-controller consumer (prop-448205ebb3b8). This module
declares intent only: it names a work/proposal reference, a bounded
execution mode, and an optional backend. It never selects a live provider,
mints a lease, launches a worker, or claims execution occurred. Declaring an
intent is recorded exactly like any other observation, via the existing
EventStore -- there is no separate authority path.

Unknown backends, unknown modes, and malformed references fail closed.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from event_store import CaptureEvent

EXECUTION_INTENT_EVENT_TYPE = "execution.intent.v1"

# Closed set. Adding a backend is a new PR, not a runtime config knob --
# this module is a declaration channel, not a dispatch table.
REQUESTED_BACKENDS = frozenset({"unspecified", "mac_controller"})

# Closed set. Both values are non-executing classifications: there is no
# "autonomous" or "live" mode until a controller exists to honor one.
EXECUTION_MODES = frozenset({"dry_run", "supervised"})

# work_ref must name an id already minted by an existing durable surface in
# this repo (control-plane work, approval request, scheduler proposal, or a
# capture event) -- never an arbitrary caller-supplied string.
WORK_REF_RE = re.compile(r"^(wrk|apr|sched_prop|evt)_[A-Za-z0-9]{6,64}$")


class ExecutionIntentValidationError(ValueError):
    """Malformed or out-of-contract ExecutionIntent declaration."""


def validate_work_ref(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ExecutionIntentValidationError("work_ref is required")
    if not WORK_REF_RE.fullmatch(text):
        raise ExecutionIntentValidationError("work_ref is malformed")
    return text


def validate_requested_backend(value: str) -> str:
    text = str(value if value is not None else "unspecified").strip() or "unspecified"
    if text not in REQUESTED_BACKENDS:
        raise ExecutionIntentValidationError("requested_backend is not a known backend")
    return text


def validate_execution_mode(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ExecutionIntentValidationError("execution_mode is required")
    if text not in EXECUTION_MODES:
        raise ExecutionIntentValidationError("execution_mode is not a bounded mode")
    return text


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_execution_intent_event(
    *,
    work_ref: str,
    execution_mode: str,
    requested_backend: str = "unspecified",
    note: str = "",
) -> CaptureEvent:
    """Build the durable, provider-neutral ExecutionIntent record.

    Returns a CaptureEvent for the existing EventStore -- the same durable
    source `capture` already writes to. Each call declares intent *now*;
    retries are not deduplicated (occurred_at advances), so a client that
    resubmits the identical intent gets a new row, not a rejected duplicate.
    """
    ref = validate_work_ref(work_ref)
    mode = validate_execution_mode(execution_mode)
    backend = validate_requested_backend(requested_backend)
    declared_at = _now_iso()
    return CaptureEvent.create(
        source="inbox",
        source_object_id=ref,
        observed_at=declared_at,
        occurred_at=declared_at,
        event_type=EXECUTION_INTENT_EVENT_TYPE,
        payload={
            "work_ref": ref,
            "execution_mode": mode,
            "requested_backend": backend,
            "note": str(note or ""),
            "execution_claimed": False,
        },
        provenance={"source_ref": f"inbox:execution_intent/{ref}"},
    )
