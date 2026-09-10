"""Governed LifeOps-to-Orca execution adapter (governed-execution-surface
slice 2; wired onto the canonical control plane in slice 3, PR-4).

Builds on [[execution_intent]] (slice 1, declaration-only): `execution_submit`,
`execution_status`, and `execution_events` on `mcp_control_plane.ControlPlane`
are untouched. `ControlPlane` now constructs one `ExecutionAdapter` (sharing
its own `event_store`/`approval_store` -- not a second store) and registers
`execution_inspect`/`execution_start`/`execution_run_status`/
`execution_cancel`/`execution_verify_close` directly on the canonical MCP
surface (see `mcp_control_plane.build_control_plane_mcp`). This module itself
defines no MCP server/app -- `EXECUTION_ADAPTER_TOOL_NAMES` below is only the
shared name list both `mcp_control_plane.CONTROL_PLANE_TOOL_NAMES` and this
module's own tests key off of.

Authority reality, verified by search of this repository (see
`work/overnight/execution-intent-authority-packet.md` and
`docs/invariants.md` 3.7): there is no HomeBase admission client and no
Portfolio lease client anywhere in this codebase. `MissingAuthorityInterface`
is the only `AdmissionAuthority` implementation shipped here, and it always
denies. `execution_start` therefore has no code path that reaches
`subprocess.run()` today -- every call fails closed before argv is ever
built. The Orca CLI invocation (`build_orca_terminal_*_argv`,
`OrcaTerminalClient`) is real and tested in isolation, mirroring
`bridge_work_client.py`'s pattern, but is dead code from `execution_start`'s
perspective until a real `AdmissionAuthority` is wired in.

REQUIRED_FROM_AUTHORITY (restated from the prior packet -- unchanged, and
this module is where they would actually be consumed):
  - HomeBase admission/grant reference, signer, expiry.
  - Portfolio revision and exact repository/worktree lease.
  - Approved provider allowlist (which backend launcher commands are safe to
    pass Orca's `terminal create --command`).
  - Cleanup/lease-release policy.

If/when those exist, implement a real `AdmissionAuthority` and populate
`EXECUTION_PROVIDER_COMMANDS` -- do not relax the checks in this module to
make that easier.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from approval_store import ApprovalStore
from event_store import CaptureEvent, EventStore, EventStoreConflict
from execution_intent import (
    EXECUTION_INTENT_EVENT_TYPE,
    ExecutionIntentValidationError,
    validate_work_ref,
)

EXECUTION_START_EVENT_TYPE = "execution.start_attempt.v1"
EXECUTION_RUN_EVENT_TYPE = "execution.run.v1"

TERMINAL_RUN_STATUSES = frozenset({"cancelled", "verified_closed"})

RUN_REF_RE = re.compile(r"^run_[A-Za-z0-9]{6,64}$")
ADMISSION_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
TERMINAL_HANDLE_RE = re.compile(r"^term_[A-Za-z0-9]{3,64}$")

ORCA_BIN_ENV = "INBOX_ORCA_BIN"
ORCA_TERMINAL_WAIT_TIMEOUT_MS = 30000
ORCA_ALLOWED_SUBCOMMANDS = frozenset(
    {("terminal", "create"), ("terminal", "show"), ("terminal", "close"), ("terminal", "wait")}
)

# Closed map: provider id -> fixed launcher text passed to Orca's
# `terminal create --command`. Callers never supply --command text
# directly -- only a provider id, looked up here. Empty until Portfolio
# authority publishes an approved provider list; nothing is allowed by
# default.
EXECUTION_PROVIDER_COMMANDS: dict[str, str] = {}


class ExecutionAdapterError(ValueError):
    """Malformed input or out-of-contract adapter call."""


class OrcaTerminalError(RuntimeError):
    """Orca terminal call failed closed (reject, missing config, bad output)."""


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validate_run_id(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ExecutionAdapterError("run_id is required")
    if not RUN_REF_RE.fullmatch(text):
        raise ExecutionAdapterError("run_id is malformed")
    return text


def validate_admission_ref(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ExecutionAdapterError("admission_ref is required")
    if not ADMISSION_REF_RE.fullmatch(text):
        raise ExecutionAdapterError("admission_ref is malformed")
    return text


def validate_idempotency_key(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ExecutionAdapterError("idempotency_key is required")
    if not IDEMPOTENCY_KEY_RE.fullmatch(text):
        raise ExecutionAdapterError("idempotency_key is malformed")
    return text


def validate_terminal_handle(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ExecutionAdapterError("terminal_handle is required")
    if not TERMINAL_HANDLE_RE.fullmatch(text):
        raise ExecutionAdapterError("terminal_handle is malformed")
    return text


@dataclass(frozen=True)
class AdmissionDecision:
    """Result of checking one admission_ref against real authority. The only
    shipped producer, MissingAuthorityInterface, always returns granted=False."""

    granted: bool
    reason: str = ""
    lease_id: str | None = None
    worktree_path: str | None = None
    provider: str | None = None
    expires_at: str | None = None


class AdmissionAuthority(Protocol):
    def check(self, *, admission_ref: str, work_id: str) -> AdmissionDecision: ...


class MissingAuthorityInterface:
    """No HomeBase admission client and no Portfolio lease client exist in
    this repository. Every check denies with authority_interface_missing --
    there is no path to a granted decision from this implementation."""

    def check(self, *, admission_ref: str, work_id: str) -> AdmissionDecision:
        return AdmissionDecision(granted=False, reason="authority_interface_missing")


@dataclass(frozen=True)
class WorktreeCheck:
    ok: bool
    reason: str = ""


def validate_exact_worktree(
    claimed_path: str | None, *, actual: Path | None = None
) -> WorktreeCheck:
    """The worktree an admission decision names must resolve to exactly the
    worktree this process is running in -- never a sibling checkout."""
    if not claimed_path:
        return WorktreeCheck(False, "worktree_path_missing")
    try:
        claimed = Path(claimed_path).expanduser().resolve()
    except (OSError, RuntimeError):
        return WorktreeCheck(False, "worktree_path_unresolvable")
    resolved_actual = (actual or Path.cwd()).resolve()
    if claimed != resolved_actual:
        return WorktreeCheck(False, "worktree_mismatch")
    return WorktreeCheck(True)


def _resolve_orca_bin(configured: str | None = None) -> Path:
    raw = (configured if configured is not None else os.getenv(ORCA_BIN_ENV, "")).strip()
    if raw:
        path = Path(raw).expanduser()
    else:
        found = shutil.which("orca")
        if not found:
            raise OrcaTerminalError("orca_binary_missing")
        path = Path(found)
    if not path.is_file():
        raise OrcaTerminalError("orca_binary_missing")
    if path.name != "orca":
        raise OrcaTerminalError("orca_binary_not_allowlisted")
    return path.resolve()


def _check_allowlisted(orca_bin: Path, *verb: str) -> None:
    if orca_bin.name != "orca" or not orca_bin.is_absolute():
        raise OrcaTerminalError("orca_binary_not_allowlisted")
    if verb not in ORCA_ALLOWED_SUBCOMMANDS:
        raise OrcaTerminalError("orca_verb_not_allowlisted")


def build_orca_terminal_create_argv(
    *, orca_bin: Path, worktree_selector: str, command: str
) -> list[str]:
    """Fixed argv only. `command` must already be a value out of
    EXECUTION_PROVIDER_COMMANDS -- never caller-supplied free text."""
    _check_allowlisted(orca_bin, "terminal", "create")
    if not worktree_selector.startswith("path:"):
        raise OrcaTerminalError("worktree_selector_not_allowlisted")
    if command not in EXECUTION_PROVIDER_COMMANDS.values():
        raise OrcaTerminalError("command_not_allowlisted")
    return [
        str(orca_bin),
        "terminal",
        "create",
        "--worktree",
        worktree_selector,
        "--command",
        command,
        "--json",
    ]


def build_orca_terminal_show_argv(*, orca_bin: Path, terminal_handle: str) -> list[str]:
    _check_allowlisted(orca_bin, "terminal", "show")
    handle = validate_terminal_handle(terminal_handle)
    return [str(orca_bin), "terminal", "show", "--terminal", handle, "--json"]


def build_orca_terminal_close_argv(*, orca_bin: Path, terminal_handle: str) -> list[str]:
    _check_allowlisted(orca_bin, "terminal", "close")
    handle = validate_terminal_handle(terminal_handle)
    return [str(orca_bin), "terminal", "close", "--terminal", handle, "--json"]


def build_orca_terminal_wait_argv(
    *, orca_bin: Path, terminal_handle: str, timeout_ms: int
) -> list[str]:
    _check_allowlisted(orca_bin, "terminal", "wait")
    handle = validate_terminal_handle(terminal_handle)
    bounded_timeout = max(1000, min(int(timeout_ms), 120000))
    return [
        str(orca_bin),
        "terminal",
        "wait",
        "--terminal",
        handle,
        "--for",
        "exit",
        "--timeout-ms",
        str(bounded_timeout),
        "--json",
    ]


def _run_orca(argv: list[str], *, timeout_sec: float = 30) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            shell=False,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OrcaTerminalError("orca_call_timeout") from exc
    except OSError as exc:
        raise OrcaTerminalError("orca_call_failed") from exc
    if completed.returncode != 0:
        raise OrcaTerminalError("orca_call_rejected")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise OrcaTerminalError("orca_result_unparseable") from exc
    if not isinstance(payload, dict):
        raise OrcaTerminalError("orca_result_unparseable")
    return payload


class OrcaTerminalClientProtocol(Protocol):
    def create(self, *, worktree_selector: str, command: str) -> dict[str, Any]: ...
    def show(self, *, terminal_handle: str) -> dict[str, Any]: ...
    def close(self, *, terminal_handle: str) -> dict[str, Any]: ...
    def wait(self, *, terminal_handle: str, timeout_ms: int) -> dict[str, Any]: ...


class OrcaTerminalClient:
    """Allowlisted subprocess caller for `orca terminal {create,show,close,wait}`
    only. shell=False, fixed argv, no arbitrary command/cwd/env."""

    def __init__(self, *, orca_bin: Path | None = None) -> None:
        self._orca_bin = orca_bin

    @classmethod
    def from_env(cls) -> OrcaTerminalClient:
        return cls()

    def _bin(self) -> Path:
        return self._orca_bin or _resolve_orca_bin()

    def create(self, *, worktree_selector: str, command: str) -> dict[str, Any]:
        argv = build_orca_terminal_create_argv(
            orca_bin=self._bin(), worktree_selector=worktree_selector, command=command
        )
        return _run_orca(argv)

    def show(self, *, terminal_handle: str) -> dict[str, Any]:
        argv = build_orca_terminal_show_argv(orca_bin=self._bin(), terminal_handle=terminal_handle)
        return _run_orca(argv)

    def close(self, *, terminal_handle: str) -> dict[str, Any]:
        argv = build_orca_terminal_close_argv(orca_bin=self._bin(), terminal_handle=terminal_handle)
        return _run_orca(argv)

    def wait(self, *, terminal_handle: str, timeout_ms: int) -> dict[str, Any]:
        argv = build_orca_terminal_wait_argv(
            orca_bin=self._bin(), terminal_handle=terminal_handle, timeout_ms=timeout_ms
        )
        return _run_orca(argv, timeout_sec=max(1.0, timeout_ms / 1000 + 5))


def _denied(reason: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"result": "DENIED", "reason": reason, "executed": False}
    payload.update(extra)
    return payload


class ExecutionAdapter:
    """The narrow LifeOps-to-Orca adapter boundary. `execution_start` never
    reaches `subprocess.run()` unless `authority.check()` grants -- which
    `MissingAuthorityInterface`, the only implementation shipped here, never
    does."""

    def __init__(
        self,
        *,
        event_store: EventStore,
        approval_store: ApprovalStore,
        authority: AdmissionAuthority | None = None,
        orca_client: OrcaTerminalClientProtocol | None = None,
    ) -> None:
        self.event_store = event_store
        self.approval_store = approval_store
        self.authority: AdmissionAuthority = authority or MissingAuthorityInterface()
        self.orca_client: OrcaTerminalClientProtocol = orca_client or OrcaTerminalClient.from_env()

    # -- shared read helpers -------------------------------------------------

    def _list_start_attempts(self, work_id: str) -> list[CaptureEvent]:
        return self.event_store.list_by_event_type(
            EXECUTION_START_EVENT_TYPE, source_object_id=work_id
        )

    def _find_start_attempt(self, work_id: str, idempotency_key: str) -> CaptureEvent | None:
        for event in self._list_start_attempts(work_id):
            if event.payload.get("idempotency_key") == idempotency_key:
                return event
        return None

    def _list_runs_for_work(self, work_id: str) -> list[CaptureEvent]:
        # Linear scan over the run log is acceptable here: in this repo's
        # current reality the run log is always empty, because
        # MissingAuthorityInterface never grants and execution_start
        # therefore never writes a run record.
        return [
            event
            for event in self.event_store.list_by_event_type(EXECUTION_RUN_EVENT_TYPE, limit=500)
            if event.payload.get("work_id") == work_id
        ]

    def _latest_run_event(self, run_id: str) -> CaptureEvent | None:
        events = self.event_store.list_by_event_type(
            EXECUTION_RUN_EVENT_TYPE, source_object_id=run_id
        )
        return events[0] if events else None

    def _write_run_event(
        self, *, run_id: str, work_id: str, status: str, detail: dict[str, Any]
    ) -> CaptureEvent:
        event = CaptureEvent.create(
            source="inbox",
            source_object_id=run_id,
            observed_at=_now_iso(),
            occurred_at=_now_iso(),
            event_type=EXECUTION_RUN_EVENT_TYPE,
            payload={"run_id": run_id, "work_id": work_id, "status": status, "detail": detail},
            provenance={"source_ref": f"inbox:execution_run/{run_id}"},
        )
        stored, _ = self.event_store.append(event)
        return stored

    def _record_start_attempt(
        self, *, work_id: str, idempotency_key: str, admission_ref: str, result: dict[str, Any]
    ) -> None:
        event = CaptureEvent.create(
            source="inbox",
            source_object_id=work_id,
            observed_at=_now_iso(),
            occurred_at=_now_iso(),
            event_type=EXECUTION_START_EVENT_TYPE,
            payload={
                "work_id": work_id,
                "idempotency_key": idempotency_key,
                "admission_ref": admission_ref,
                "result": result,
            },
            provenance={"source_ref": f"inbox:execution_start/{work_id}"},
        )
        # Extremely unlikely: identical (work_id, idempotency_key,
        # admission_ref, result, same-second timestamp) already recorded by
        # a concurrent caller. Not a correctness problem -- the prior
        # attempt's outcome already governs the next _find_start_attempt
        # lookup either way.
        with contextlib.suppress(EventStoreConflict):
            self.event_store.append(event)

    def _audit(self, event_type: str, **kwargs: Any) -> None:
        self.approval_store.log_event(event_type, **kwargs)

    # -- public operations ----------------------------------------------------

    def execution_inspect(self, work_id: str = "", **kwargs: Any) -> dict[str, Any]:
        """Read-only consolidated view: intent-declaration history, start-
        attempt history, and any run records for one work_id. Never spawns."""
        if kwargs:
            return _denied("unknown_field", fields=sorted(kwargs))
        try:
            ref = validate_work_ref(work_id)
        except ExecutionIntentValidationError as exc:
            return _denied(str(exc))
        intents = self.event_store.list_by_event_type(
            EXECUTION_INTENT_EVENT_TYPE, source_object_id=ref
        )
        start_attempts = self._list_start_attempts(ref)
        runs = self._list_runs_for_work(ref)
        return {
            "result": "ok",
            "work_id": ref,
            "intents_recorded": len(intents),
            "latest_intent": intents[0].to_dict() if intents else None,
            "start_attempts_recorded": len(start_attempts),
            "latest_start_attempt": start_attempts[0].to_dict() if start_attempts else None,
            "runs_recorded": len(runs),
            "runs": [r.to_dict() for r in runs],
            "executed": False,
        }

    def execution_start(
        self,
        work_id: str = "",
        *,
        admission_ref: str = "",
        idempotency_key: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Validate admission, idempotency, exact worktree binding, and
        provider allowlist before ever building argv or spawning. Fails
        closed on the first missing/malformed/unauthorized field. With the
        only shipped AdmissionAuthority (MissingAuthorityInterface), this
        always denies before subprocess.run() is reachable."""
        if kwargs:
            return _denied("unknown_field", fields=sorted(kwargs))
        try:
            ref = validate_work_ref(work_id)
        except ExecutionIntentValidationError as exc:
            return _denied(str(exc))
        try:
            key = validate_idempotency_key(idempotency_key)
        except ExecutionAdapterError as exc:
            return _denied(str(exc))
        try:
            adm = validate_admission_ref(admission_ref)
        except ExecutionAdapterError as exc:
            return _denied(str(exc))

        prior = self._find_start_attempt(ref, key)
        if prior is not None:
            if prior.payload.get("admission_ref") == adm:
                replay = dict(prior.payload.get("result") or {})
                replay["idempotent_replay"] = True
                return replay
            return _denied("idempotency_key_conflict")

        decision = self.authority.check(admission_ref=adm, work_id=ref)
        if not decision.granted:
            result = _denied(decision.reason or "authority_denied")
            self._record_start_attempt(
                work_id=ref, idempotency_key=key, admission_ref=adm, result=result
            )
            self._audit(
                "execution_start_denied",
                operation="execution_start",
                resource=ref,
                result="DENIED",
                detail={"reason": result["reason"]},
            )
            return result

        # Unreachable today: MissingAuthorityInterface.check() always returns
        # granted=False above. Implemented and unit-tested (argv builders,
        # validate_exact_worktree, provider lookup) in isolation so the
        # adapter is ready the moment a real AdmissionAuthority exists.
        worktree_check = validate_exact_worktree(decision.worktree_path)
        if not worktree_check.ok:
            result = _denied("worktree_mismatch", detail=worktree_check.reason)
            self._record_start_attempt(
                work_id=ref, idempotency_key=key, admission_ref=adm, result=result
            )
            return result
        command = EXECUTION_PROVIDER_COMMANDS.get(decision.provider or "")
        if not command:
            result = _denied("provider_not_allowlisted")
            self._record_start_attempt(
                work_id=ref, idempotency_key=key, admission_ref=adm, result=result
            )
            return result
        try:
            created = self.orca_client.create(
                worktree_selector=f"path:{Path.cwd().resolve()}", command=command
            )
        except OrcaTerminalError as exc:
            result = _denied(str(exc))
            self._record_start_attempt(
                work_id=ref, idempotency_key=key, admission_ref=adm, result=result
            )
            return result
        terminal_handle = str(created.get("terminal") or "").strip()
        if not terminal_handle:
            result = _denied("orca_result_missing_terminal_handle")
            self._record_start_attempt(
                work_id=ref, idempotency_key=key, admission_ref=adm, result=result
            )
            return result
        run_id = f"run_{uuid.uuid4().hex}"
        self._write_run_event(
            run_id=run_id,
            work_id=ref,
            status="started",
            detail={"terminal_handle": terminal_handle, "lease_id": decision.lease_id},
        )
        result = {"result": "created", "run_id": run_id, "executed": False}
        self._record_start_attempt(
            work_id=ref, idempotency_key=key, admission_ref=adm, result=result
        )
        self._audit(
            "execution_start_created", operation="execution_start", resource=ref, result="created"
        )
        return result

    def execution_run_status(self, run_id: str = "", **kwargs: Any) -> dict[str, Any]:
        """Durable run status by run_id -- distinct from execution_status on
        the frozen control plane, which reports intent-declaration history
        by work_ref, not run state."""
        if kwargs:
            return _denied("unknown_field", fields=sorted(kwargs))
        try:
            ref = validate_run_id(run_id)
        except ExecutionAdapterError as exc:
            return _denied(str(exc))
        latest = self._latest_run_event(ref)
        if latest is None:
            return {"result": "ok", "run_id": ref, "status": "not_found", "executed": False}
        return {
            "result": "ok",
            "run_id": ref,
            "status": latest.payload.get("status"),
            "work_id": latest.payload.get("work_id"),
            "detail": latest.payload.get("detail"),
            "executed": False,
        }

    def execution_cancel(self, run_id: str = "", **kwargs: Any) -> dict[str, Any]:
        if kwargs:
            return _denied("unknown_field", fields=sorted(kwargs))
        try:
            ref = validate_run_id(run_id)
        except ExecutionAdapterError as exc:
            return _denied(str(exc))
        latest = self._latest_run_event(ref)
        if latest is None:
            return _denied("unknown_run")
        status = latest.payload.get("status")
        if status in TERMINAL_RUN_STATUSES:
            return _denied("run_not_cancellable", current_status=status)
        terminal_handle = str(
            (latest.payload.get("detail") or {}).get("terminal_handle") or ""
        ).strip()
        try:
            self.orca_client.close(terminal_handle=terminal_handle)
        except OrcaTerminalError as exc:
            return _denied(str(exc))
        self._write_run_event(
            run_id=ref,
            work_id=str(latest.payload.get("work_id") or ""),
            status="cancelled",
            detail={"terminal_handle": terminal_handle},
        )
        self._audit(
            "execution_cancel", operation="execution_cancel", resource=ref, result="cancelled"
        )
        return {"result": "ok", "run_id": ref, "status": "cancelled", "executed": False}

    def execution_verify_close(self, run_id: str = "", **kwargs: Any) -> dict[str, Any]:
        if kwargs:
            return _denied("unknown_field", fields=sorted(kwargs))
        try:
            ref = validate_run_id(run_id)
        except ExecutionAdapterError as exc:
            return _denied(str(exc))
        latest = self._latest_run_event(ref)
        if latest is None:
            return _denied("unknown_run")
        status = latest.payload.get("status")
        if status == "verified_closed":
            return {
                "result": "ok",
                "run_id": ref,
                "status": status,
                "already_verified": True,
                "executed": False,
            }
        if status not in {"started", "cancelled"}:
            return _denied("run_not_verifiable", current_status=status)
        terminal_handle = str(
            (latest.payload.get("detail") or {}).get("terminal_handle") or ""
        ).strip()
        try:
            wait_result = self.orca_client.wait(
                terminal_handle=terminal_handle, timeout_ms=ORCA_TERMINAL_WAIT_TIMEOUT_MS
            )
        except OrcaTerminalError as exc:
            return _denied(str(exc))
        self._write_run_event(
            run_id=ref,
            work_id=str(latest.payload.get("work_id") or ""),
            status="verified_closed",
            detail={"terminal_handle": terminal_handle, "wait_result": wait_result},
        )
        self._audit(
            "execution_verify_close",
            operation="execution_verify_close",
            resource=ref,
            result="verified_closed",
        )
        return {"result": "ok", "run_id": ref, "status": "verified_closed", "executed": False}


EXECUTION_ADAPTER_TOOL_NAMES = (
    "execution_inspect",
    "execution_start",
    "execution_run_status",
    "execution_cancel",
    "execution_verify_close",
)
"""Shared source of truth for the five tool names. mcp_control_plane.py
registers actual @mcp.tool() wrappers for these directly on the canonical
ControlPlane MCP surface (build_control_plane_mcp) -- there is no second
MCP server/app defined by this module. Kept here only as the name list both
CONTROL_PLANE_TOOL_NAMES and this module's own tests key off of."""


def make_execution_adapter(
    *,
    event_db: Path | None = None,
    approval_db: Path | None = None,
    authority: AdmissionAuthority | None = None,
    orca_client: OrcaTerminalClientProtocol | None = None,
) -> ExecutionAdapter:
    return ExecutionAdapter(
        event_store=EventStore(event_db),
        approval_store=ApprovalStore(approval_db),
        authority=authority,
        orca_client=orca_client,
    )
