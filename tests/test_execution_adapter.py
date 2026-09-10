"""Governed LifeOps-to-Orca execution adapter (slice 2): denial/zero-spawn,
duplicate idempotency, exact worktree binding, status/cancel/verify-close,
and malformed-field tests.

No AdmissionAuthority in this repo ever grants (MissingAuthorityInterface is
the only shipped implementation) -- so there is no real "run actually
started" fixture to test against. Tests that exercise the run-record
state machine (cancel/verify_close/status once a run exists) seed a run
record directly via the adapter's own write helper, clearly as synthetic
data-layer fixtures that prove the storage/transition logic is correct --
never as a claim that any execution occurred. Per task instruction, no
positive admission/lease fixture is included because none is real.
"""

from __future__ import annotations

import pytest

from approval_store import ApprovalStore
from event_store import EventStore
from execution_adapter import (
    EXECUTION_ADAPTER_TOOL_NAMES,
    EXECUTION_PROVIDER_COMMANDS,
    AdmissionDecision,
    ExecutionAdapter,
    ExecutionAdapterError,
    MissingAuthorityInterface,
    OrcaTerminalError,
    build_orca_terminal_close_argv,
    build_orca_terminal_create_argv,
    build_orca_terminal_show_argv,
    build_orca_terminal_wait_argv,
    validate_admission_ref,
    validate_exact_worktree,
    validate_idempotency_key,
    validate_run_id,
)
from execution_intent import build_execution_intent_event

pytestmark = pytest.mark.safe

VALID_WORK_ID = "wrk_abc123def4567890"
VALID_ADMISSION_REF = "adm-test-ref-001"
VALID_IDEMPOTENCY_KEY = "idem-test-key-001"


class SpyOrcaTerminalClient:
    """Test double: records calls; never shells out to a real orca binary."""

    def __init__(self) -> None:
        self.create_calls: list[dict] = []
        self.show_calls: list[dict] = []
        self.close_calls: list[dict] = []
        self.wait_calls: list[dict] = []

    def create(self, *, worktree_selector: str, command: str) -> dict:
        self.create_calls.append({"worktree_selector": worktree_selector, "command": command})
        return {"terminal": "term_spyabc123"}

    def show(self, *, terminal_handle: str) -> dict:
        self.show_calls.append({"terminal_handle": terminal_handle})
        return {"terminal": terminal_handle, "status": "running"}

    def close(self, *, terminal_handle: str) -> dict:
        self.close_calls.append({"terminal_handle": terminal_handle})
        return {"terminal": terminal_handle, "closed": True}

    def wait(self, *, terminal_handle: str, timeout_ms: int) -> dict:
        self.wait_calls.append({"terminal_handle": terminal_handle, "timeout_ms": timeout_ms})
        return {"terminal": terminal_handle, "exitCode": 0}


class RefusingOrcaTerminalClient:
    """Fails the test if the adapter ever reaches a real-looking Orca call."""

    def create(self, *, worktree_selector: str, command: str) -> dict:
        raise AssertionError(
            "execution_start must never reach OrcaTerminalClient.create with MissingAuthorityInterface"
        )

    def show(self, *, terminal_handle: str) -> dict:
        raise AssertionError("unexpected orca show call")

    def close(self, *, terminal_handle: str) -> dict:
        raise AssertionError("unexpected orca close call")

    def wait(self, *, terminal_handle: str, timeout_ms: int) -> dict:
        raise AssertionError("unexpected orca wait call")


@pytest.fixture
def orca_spy() -> SpyOrcaTerminalClient:
    return SpyOrcaTerminalClient()


@pytest.fixture
def adapter(tmp_path) -> ExecutionAdapter:
    return ExecutionAdapter(
        event_store=EventStore(tmp_path / "events.sqlite3"),
        approval_store=ApprovalStore(tmp_path / "approvals.sqlite3"),
        orca_client=RefusingOrcaTerminalClient(),
    )


# ── denial / zero-spawn ──────────────────────────────────────────────────


def test_execution_start_denies_with_missing_authority_interface(adapter):
    result = adapter.execution_start(
        VALID_WORK_ID, admission_ref=VALID_ADMISSION_REF, idempotency_key=VALID_IDEMPOTENCY_KEY
    )
    assert result["result"] == "DENIED"
    assert result["reason"] == "authority_interface_missing"
    assert result["executed"] is False


def test_execution_start_never_spawns_a_run_record_on_denial(adapter):
    adapter.execution_start(
        VALID_WORK_ID, admission_ref=VALID_ADMISSION_REF, idempotency_key=VALID_IDEMPOTENCY_KEY
    )
    inspected = adapter.execution_inspect(VALID_WORK_ID)
    assert inspected["runs_recorded"] == 0
    assert inspected["runs"] == []


def test_execution_start_authority_check_is_an_explicit_deny_not_an_exception():
    assert MissingAuthorityInterface().check(admission_ref="x", work_id="y") == AdmissionDecision(
        granted=False, reason="authority_interface_missing"
    )


def test_execution_adapter_default_orca_client_is_never_constructed_to_run_real_subprocess(
    tmp_path,
):
    # RefusingOrcaTerminalClient asserts if invoked; a passing denial test
    # above already proves execution_start never reaches it. This test
    # documents the same guarantee independent of the fixture wiring.
    adapter = ExecutionAdapter(
        event_store=EventStore(tmp_path / "events.sqlite3"),
        approval_store=ApprovalStore(tmp_path / "approvals.sqlite3"),
        orca_client=RefusingOrcaTerminalClient(),
    )
    result = adapter.execution_start(
        VALID_WORK_ID, admission_ref=VALID_ADMISSION_REF, idempotency_key="another-key"
    )
    assert result["result"] == "DENIED"


# ── duplicate idempotency ────────────────────────────────────────────────


def test_execution_start_replays_identical_idempotency_key(adapter):
    first = adapter.execution_start(
        VALID_WORK_ID, admission_ref=VALID_ADMISSION_REF, idempotency_key=VALID_IDEMPOTENCY_KEY
    )
    second = adapter.execution_start(
        VALID_WORK_ID, admission_ref=VALID_ADMISSION_REF, idempotency_key=VALID_IDEMPOTENCY_KEY
    )
    assert first["result"] == "DENIED"
    assert second["result"] == "DENIED"
    assert second["idempotent_replay"] is True
    assert adapter.execution_inspect(VALID_WORK_ID)["start_attempts_recorded"] == 1


def test_execution_start_rejects_same_key_with_different_admission_ref(adapter):
    adapter.execution_start(
        VALID_WORK_ID, admission_ref="adm-ref-a", idempotency_key=VALID_IDEMPOTENCY_KEY
    )
    conflict = adapter.execution_start(
        VALID_WORK_ID, admission_ref="adm-ref-b", idempotency_key=VALID_IDEMPOTENCY_KEY
    )
    assert conflict["result"] == "DENIED"
    assert conflict["reason"] == "idempotency_key_conflict"
    assert adapter.execution_inspect(VALID_WORK_ID)["start_attempts_recorded"] == 1


def test_execution_start_different_keys_record_separate_attempts(adapter):
    adapter.execution_start(
        VALID_WORK_ID, admission_ref=VALID_ADMISSION_REF, idempotency_key="key-one"
    )
    adapter.execution_start(
        VALID_WORK_ID, admission_ref=VALID_ADMISSION_REF, idempotency_key="key-two"
    )
    assert adapter.execution_inspect(VALID_WORK_ID)["start_attempts_recorded"] == 2


# ── exact worktree binding ───────────────────────────────────────────────


def test_validate_exact_worktree_accepts_the_resolved_current_directory(tmp_path):
    check = validate_exact_worktree(str(tmp_path), actual=tmp_path)
    assert check.ok is True


def test_validate_exact_worktree_rejects_a_different_path(tmp_path):
    other = tmp_path / "sibling-checkout"
    other.mkdir()
    check = validate_exact_worktree(str(other), actual=tmp_path)
    assert check.ok is False
    assert check.reason == "worktree_mismatch"


def test_validate_exact_worktree_rejects_missing_path():
    check = validate_exact_worktree(None)
    assert check.ok is False
    assert check.reason == "worktree_path_missing"


def test_build_orca_terminal_create_argv_requires_exact_worktree_selector_form(
    tmp_path, monkeypatch
):
    monkeypatch.setitem(EXECUTION_PROVIDER_COMMANDS, "fixture_provider", "fixture-launch-cmd")
    orca_bin = tmp_path / "orca"
    orca_bin.write_text("#!/bin/sh\n")
    with pytest.raises(OrcaTerminalError, match="worktree_selector_not_allowlisted"):
        build_orca_terminal_create_argv(
            orca_bin=orca_bin, worktree_selector=str(tmp_path), command="fixture-launch-cmd"
        )
    argv = build_orca_terminal_create_argv(
        orca_bin=orca_bin, worktree_selector=f"path:{tmp_path}", command="fixture-launch-cmd"
    )
    assert argv == [
        str(orca_bin),
        "terminal",
        "create",
        "--worktree",
        f"path:{tmp_path}",
        "--command",
        "fixture-launch-cmd",
        "--json",
    ]


def test_build_orca_terminal_create_argv_rejects_command_not_in_provider_allowlist(tmp_path):
    orca_bin = tmp_path / "orca"
    orca_bin.write_text("#!/bin/sh\n")
    with pytest.raises(OrcaTerminalError, match="command_not_allowlisted"):
        build_orca_terminal_create_argv(
            orca_bin=orca_bin, worktree_selector=f"path:{tmp_path}", command="rm -rf /"
        )


def test_orca_argv_builders_reject_non_orca_binary(tmp_path):
    fake_bin = tmp_path / "not-orca"
    fake_bin.write_text("#!/bin/sh\n")
    with pytest.raises(OrcaTerminalError, match="orca_binary_not_allowlisted"):
        build_orca_terminal_show_argv(orca_bin=fake_bin, terminal_handle="term_abc123")


def test_orca_argv_builders_reject_malformed_terminal_handle(tmp_path):
    orca_bin = tmp_path / "orca"
    orca_bin.write_text("#!/bin/sh\n")
    for bad_handle in ("", "../etc/passwd", "term_", "shell:rm -rf", "abc123"):
        with pytest.raises(ExecutionAdapterError, match="terminal_handle"):
            build_orca_terminal_close_argv(orca_bin=orca_bin, terminal_handle=bad_handle)


def test_build_orca_terminal_wait_argv_bounds_timeout(tmp_path):
    orca_bin = tmp_path / "orca"
    orca_bin.write_text("#!/bin/sh\n")
    argv = build_orca_terminal_wait_argv(
        orca_bin=orca_bin, terminal_handle="term_abc123", timeout_ms=999999999
    )
    assert "120000" in argv
    argv_low = build_orca_terminal_wait_argv(
        orca_bin=orca_bin, terminal_handle="term_abc123", timeout_ms=1
    )
    assert "1000" in argv_low


# ── malformed fields ─────────────────────────────────────────────────────


def test_execution_start_rejects_malformed_work_id(adapter):
    result = adapter.execution_start(
        "not-a-ref", admission_ref=VALID_ADMISSION_REF, idempotency_key=VALID_IDEMPOTENCY_KEY
    )
    assert result["result"] == "DENIED"
    assert "work_ref" in result["reason"]


def test_execution_start_rejects_malformed_admission_ref(adapter):
    for bad in ("", "  ", "../etc/passwd", "a"):
        result = adapter.execution_start(
            VALID_WORK_ID, admission_ref=bad, idempotency_key=VALID_IDEMPOTENCY_KEY
        )
        assert result["result"] == "DENIED"
        assert "admission_ref" in result["reason"]


def test_execution_start_rejects_malformed_idempotency_key(adapter):
    for bad in ("", "  ", "shell:rm -rf /"):
        result = adapter.execution_start(
            VALID_WORK_ID, admission_ref=VALID_ADMISSION_REF, idempotency_key=bad
        )
        assert result["result"] == "DENIED"
        assert "idempotency_key" in result["reason"]


def test_execution_start_rejects_unknown_fields(adapter):
    result = adapter.execution_start(
        VALID_WORK_ID,
        admission_ref=VALID_ADMISSION_REF,
        idempotency_key=VALID_IDEMPOTENCY_KEY,
        lease_id="lease_fake",
    )
    assert result["result"] == "DENIED"
    assert result["reason"] == "unknown_field"


def test_execution_run_status_rejects_malformed_run_id(adapter):
    for bad in ("", "not-a-run", "wrk_abc123def456"):
        result = adapter.execution_run_status(bad)
        assert result["result"] == "DENIED"
        assert "run_id" in result["reason"]


def test_execution_cancel_and_verify_close_reject_malformed_run_id(adapter):
    assert adapter.execution_cancel("bad")["result"] == "DENIED"
    assert adapter.execution_verify_close("bad")["result"] == "DENIED"


def test_execution_inspect_rejects_malformed_work_id(adapter):
    result = adapter.execution_inspect("not-a-ref")
    assert result["result"] == "DENIED"


def test_validators_reject_malformed_input_directly():
    with pytest.raises(ExecutionAdapterError, match="run_id"):
        validate_run_id("bad")
    with pytest.raises(ExecutionAdapterError, match="admission_ref"):
        validate_admission_ref("")
    with pytest.raises(ExecutionAdapterError, match="idempotency_key"):
        validate_idempotency_key("")


# ── status / cancel / verify-close ───────────────────────────────────────


def test_execution_run_status_reports_not_found_for_unknown_run(adapter):
    result = adapter.execution_run_status("run_" + "a" * 32)
    assert result["result"] == "ok"
    assert result["status"] == "not_found"


def test_execution_cancel_denies_unknown_run(adapter):
    result = adapter.execution_cancel("run_" + "a" * 32)
    assert result["result"] == "DENIED"
    assert result["reason"] == "unknown_run"


def test_execution_verify_close_denies_unknown_run(adapter):
    result = adapter.execution_verify_close("run_" + "a" * 32)
    assert result["result"] == "DENIED"
    assert result["reason"] == "unknown_run"


def test_run_record_lifecycle_via_seeded_synthetic_run(tmp_path, orca_spy):
    """Data-layer/state-machine test only. A run record can only exist here
    because we seed it directly with the adapter's own write helper --
    execution_start can never create one with MissingAuthorityInterface.
    This proves execution_run_status/execution_cancel/execution_verify_close
    read and transition state correctly; it is not a claim that any
    execution occurred."""
    adapter = ExecutionAdapter(
        event_store=EventStore(tmp_path / "events.sqlite3"),
        approval_store=ApprovalStore(tmp_path / "approvals.sqlite3"),
        orca_client=orca_spy,
    )
    run_id = "run_" + "b" * 32
    adapter._write_run_event(
        run_id=run_id,
        work_id=VALID_WORK_ID,
        status="started",
        detail={"terminal_handle": "term_synthetic01"},
    )

    status = adapter.execution_run_status(run_id)
    assert status["status"] == "started"
    assert status["work_id"] == VALID_WORK_ID

    cancelled = adapter.execution_cancel(run_id)
    assert cancelled["result"] == "ok"
    assert cancelled["status"] == "cancelled"
    assert orca_spy.close_calls == [{"terminal_handle": "term_synthetic01"}]

    already = adapter.execution_cancel(run_id)
    assert already["result"] == "DENIED"
    assert already["reason"] == "run_not_cancellable"

    verified = adapter.execution_verify_close(run_id)
    assert verified["result"] == "ok"
    assert verified["status"] == "verified_closed"
    assert orca_spy.wait_calls == [{"terminal_handle": "term_synthetic01", "timeout_ms": 30000}]

    again = adapter.execution_verify_close(run_id)
    assert again["already_verified"] is True


def test_execution_inspect_aggregates_intent_and_start_attempt_history(tmp_path, adapter):
    event_store = adapter.event_store
    intent_event = build_execution_intent_event(work_ref=VALID_WORK_ID, execution_mode="dry_run")
    event_store.append(intent_event)
    adapter.execution_start(
        VALID_WORK_ID, admission_ref=VALID_ADMISSION_REF, idempotency_key=VALID_IDEMPOTENCY_KEY
    )

    result = adapter.execution_inspect(VALID_WORK_ID)
    assert result["result"] == "ok"
    assert result["intents_recorded"] == 1
    assert result["latest_intent"]["payload"]["work_ref"] == VALID_WORK_ID
    assert result["start_attempts_recorded"] == 1
    assert result["latest_start_attempt"]["payload"]["work_id"] == VALID_WORK_ID
    assert result["runs_recorded"] == 0
    assert result["executed"] is False


def test_execution_inspect_is_empty_for_a_work_id_with_no_history(adapter):
    result = adapter.execution_inspect(VALID_WORK_ID)
    assert result["intents_recorded"] == 0
    assert result["start_attempts_recorded"] == 0
    assert result["runs_recorded"] == 0


# ── tool-name contract ────────────────────────────────────────────────────
#
# This module defines no MCP server of its own -- mcp_control_plane.py
# registers the actual @mcp.tool() wrappers for these five names directly on
# the canonical ControlPlane surface (see tests/test_mcp_control_plane.py:
# test_fifteen_tools_enumerate, test_execution_adapter_tools_are_on_the_
# canonical_surface, test_execution_start_denied_by_default_zero_orca_calls).


def test_execution_adapter_tool_names_are_the_five_expected_names_in_order():
    assert EXECUTION_ADAPTER_TOOL_NAMES == (
        "execution_inspect",
        "execution_start",
        "execution_run_status",
        "execution_cancel",
        "execution_verify_close",
    )
