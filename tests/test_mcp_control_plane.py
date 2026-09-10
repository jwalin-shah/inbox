"""PR-2B MCP control plane: Bridge ingest only. No spawn, no epistemic tool."""

from __future__ import annotations

import ast
import asyncio
import json
import shutil
from pathlib import Path

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.testclient import TestClient

from approval_store import ApprovalStore
from bridge_work_client import (
    BRIDGE_BIN_ENV,
    BRIDGE_REPO_ENV,
    BridgeIngestError,
    BridgeIngestReceipt,
    BridgeWorkClient,
    build_ingest_argv,
    build_submit_work_envelope,
)
from event_store import CaptureEvent, EventStore, identity_digest_for
from mcp_control_plane import (
    CONTROL_PLANE_PORT,
    CONTROL_PLANE_TOKEN_ENV,
    CONTROL_PLANE_TOOL_NAMES,
    SPAWN_ENV,
    TRUST_LOOPBACK_ENV,
    ControlPlane,
    build_control_plane_mcp,
    make_control_plane,
    make_control_plane_app,
    spawn_flag,
    trust_loopback,
)
from tools_registry import TOOLS, include_names

pytestmark = pytest.mark.safe

ROOT = Path(__file__).resolve().parents[1]
BRIDGE_BIN = shutil.which("bridge")


class StubBridgeClient:
    """Test double: records envelopes; never executes workers."""

    def __init__(self, *, fail_with: str | None = None) -> None:
        self.calls: list[dict] = []
        self.fail_with = fail_with
        self.executor_invocations = 0

    def ingest_event(self, envelope: dict) -> BridgeIngestReceipt:
        self.calls.append(envelope)
        if self.fail_with:
            raise BridgeIngestError(self.fail_with)
        work_id = envelope.get("external_id") or "wrk_stub"
        return BridgeIngestReceipt(
            result_id=f"result:workpacket:inbox:control_plane:{work_id}",
            work_packet_id=f"workpacket:inbox:control_plane:{work_id}",
            status="accepted_for_intake",
            summary="event accepted for intake; execution authority was not granted",
            intake_path=f"/tmp/.bridge/intake/{work_id}.json",
        )


def _evidence_refs(**overrides) -> list[dict]:
    ref = {
        "ref": "inbox:evt_test",
        "authority_type": "inbox_event",
        "authority_id": "evt_test",
        "digest": "abc",
    }
    ref.update(overrides)
    return [ref]


def _capture_body(**overrides) -> dict:
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
    return body


class SpyOrcaTerminalClient:
    """Test double: records every call, never shells out to a real orca
    binary. Asserting zero calls after execution_start is the zero-spawn
    proof at the canonical MCP surface, not just inside execution_adapter.py."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def create(self, **_kwargs) -> dict:
        self.calls.append("create")
        return {"terminal": "term_shouldneverhappen"}

    def show(self, **_kwargs) -> dict:
        self.calls.append("show")
        return {}

    def close(self, **_kwargs) -> dict:
        self.calls.append("close")
        return {}

    def wait(self, **_kwargs) -> dict:
        self.calls.append("wait")
        return {}


@pytest.fixture
def bridge_stub() -> StubBridgeClient:
    return StubBridgeClient()


@pytest.fixture
def orca_spy() -> SpyOrcaTerminalClient:
    return SpyOrcaTerminalClient()


@pytest.fixture
def plane(tmp_path, bridge_stub) -> ControlPlane:
    return ControlPlane(
        event_store=EventStore(tmp_path / "events.sqlite3"),
        approval_store=ApprovalStore(tmp_path / "approvals.sqlite3"),
        bridge_client=bridge_stub,
    )


@pytest.fixture
def plane_with_orca_spy(tmp_path, bridge_stub, orca_spy) -> ControlPlane:
    """Same ControlPlane construction as `plane`, plus an injected Orca spy
    -- DI added only so tests can prove zero Orca calls; production callers
    of make_control_plane/make_control_plane_app get the real, lazily
    resolved OrcaTerminalClient by default."""
    return ControlPlane(
        event_store=EventStore(tmp_path / "events.sqlite3"),
        approval_store=ApprovalStore(tmp_path / "approvals.sqlite3"),
        bridge_client=bridge_stub,
        orca_client=orca_spy,
    )


def test_frozen_tools_are_not_rest_registry_names():
    with pytest.raises(ValueError, match="unknown tool names"):
        include_names(CONTROL_PLANE_TOOL_NAMES)
    rest_names = {tool.name for tool in TOOLS}
    assert rest_names.isdisjoint(CONTROL_PLANE_TOOL_NAMES)


def test_fifteen_tools_enumerate(plane):
    mcp = build_control_plane_mcp(plane)
    names = tuple(tool.name for tool in asyncio.run(mcp.list_tools()))
    assert names == CONTROL_PLANE_TOOL_NAMES
    assert len(names) == 15


def test_execution_adapter_tools_are_on_the_canonical_surface(plane):
    """The five execution-adapter tools are registered on the same
    ControlPlane MCP surface as the original ten -- not a second server."""
    mcp = build_control_plane_mcp(plane)
    names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert {
        "execution_inspect",
        "execution_start",
        "execution_run_status",
        "execution_cancel",
        "execution_verify_close",
    }.issubset(names)
    # And the pre-existing tools, including execution_status(work_ref) from
    # the prior slice, are untouched and still present alongside them.
    assert {"resolve", "capture", "submit_work", "execution_status"}.issubset(names)


def test_no_epistemic_mcp_tool(plane):
    mcp = build_control_plane_mcp(plane)
    names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert "epistemic" not in names
    assert not any("epistemic" in name for name in names)


def test_auth_fails_closed_when_token_unset(plane, monkeypatch):
    monkeypatch.delenv(CONTROL_PLANE_TOKEN_ENV, raising=False)
    monkeypatch.setenv("INBOX_MCP_TOKEN", "gateway-secret")
    app = make_control_plane_app(plane)
    with TestClient(app) as client:
        health = client.get("/health")
        mcp = client.get("/mcp")
    assert health.status_code == 200
    assert health.json()["bind"] == f"127.0.0.1:{CONTROL_PLANE_PORT}"
    assert health.json()["auth_fail_closed"] is True
    assert mcp.status_code == 401


def test_auth_rejects_missing_and_invalid_token(plane, monkeypatch):
    monkeypatch.setenv(CONTROL_PLANE_TOKEN_ENV, "control-secret")
    app = make_control_plane_app(plane)
    with TestClient(app) as client:
        missing = client.get("/mcp")
        invalid = client.get("/mcp", headers={"Authorization": "Bearer nope"})
        valid = client.get("/mcp", headers={"Authorization": "Bearer control-secret"})
        health = client.get("/health")
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert valid.status_code != 401
    assert health.status_code == 200


def test_trust_loopback_defaults_off(monkeypatch):
    monkeypatch.delenv(TRUST_LOOPBACK_ENV, raising=False)
    assert trust_loopback() is False
    monkeypatch.setenv(TRUST_LOOPBACK_ENV, "1")
    assert trust_loopback() is True


def test_oauth_protected_resource_is_absent_like_lifeops(plane, monkeypatch):
    """ChatGPT Auth=None create matches LifeOps: no RFC 9728 card."""
    monkeypatch.setenv(CONTROL_PLANE_TOKEN_ENV, "control-secret")
    app = make_control_plane_app(plane)
    with TestClient(app) as client:
        root = client.get("/.well-known/oauth-protected-resource")
        nested = client.get("/.well-known/oauth-protected-resource/mcp")
    assert root.status_code == 404
    assert nested.status_code == 404


def test_server_discover_does_not_require_token(plane, monkeypatch):
    """ChatGPT Secure MCP Tunnel refresh probes server/discover without our bearer."""
    monkeypatch.setenv(CONTROL_PLANE_TOKEN_ENV, "control-secret")
    app = make_control_plane_app(plane)
    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": "openai-mcp-discover",
                "method": "server/discover",
                "params": {},
            },
        )
        initialize = client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "openai-mcp-discover"
    assert payload["result"]["resultType"] == "complete"
    assert payload["result"]["supportedVersions"] == ["2025-06-18"]
    assert (
        payload["result"]["_meta"]["io.modelcontextprotocol/serverInfo"]["name"]
        == "Inbox Control Plane"
    )
    assert initialize.status_code == 401


def test_capture_reuses_pr0_event_store_identity(plane):
    body = _capture_body()
    mcp_result = plane.capture(**body)
    digest = identity_digest_for(
        source=body["source"],
        source_object_id=body["source_object_id"],
        occurred_at=body["occurred_at"],
        event_type=body["event_type"],
        payload=body["payload"],
        source_ref=body["provenance"]["source_ref"],
    )
    expected_id = f"evt_{digest[:32]}"
    stored = plane.event_store.get(expected_id)
    assert mcp_result["result"] == "created"
    assert mcp_result["executed"] is False
    assert mcp_result["event"]["event_id"] == expected_id
    assert stored is not None
    assert stored.event_id == expected_id
    retry = plane.capture(**body)
    assert retry["result"] == "already_exists"
    assert retry["event"]["event_id"] == expected_id
    assert plane.event_store.count() == 1


def test_capture_matches_direct_eventstore_append(tmp_path):
    store = EventStore(tmp_path / "events.sqlite3")
    plane = ControlPlane(
        event_store=store,
        approval_store=ApprovalStore(tmp_path / "approvals.sqlite3"),
    )
    body = _capture_body(source_object_id="capture-compare")
    event = CaptureEvent.create(**body)
    stored, result = store.append(event)
    mcp = plane.capture(**body)
    assert result == "created"
    assert mcp["result"] == "already_exists"
    assert mcp["event"]["event_id"] == stored.event_id


def test_submit_work_confirm_true_is_intake_not_execution(plane, bridge_stub, monkeypatch):
    monkeypatch.setenv(SPAWN_ENV, "0")
    result = plane.submit_work(_evidence_refs(), confirm=True, summary="do the thing")
    assert result["result"] == "accepted_for_intake"
    assert result["executed"] is False
    assert result["confirm_is_authority"] is False
    assert result["spawn_flag"] == 0
    assert result["bridge_intake_path"]
    assert result["bridge_result_id"]
    assert result["bridge_work_packet_id"]
    assert plane.execution_log == []
    assert bridge_stub.executor_invocations == 0
    assert len(bridge_stub.calls) == 1
    listed = plane.get_work()
    assert listed["result"] == "ok"
    assert listed["work"][0]["work_id"] == result["work_id"]
    assert listed["work"][0]["executed"] is False
    assert listed["work"][0]["bridge"]["intake_path"] == result["bridge_intake_path"]


def test_submit_work_cannot_supply_lease_or_capability(plane, bridge_stub):
    for kwargs in (
        {"lease": "lease_fake"},
        {"lease_token": "tok"},
        {"capability_token": "cap"},
        {"approval_digest": "deadbeef"},
        {"spawn": 1},
        {"evidence_refs": _evidence_refs(lease_token="nested")},
    ):
        evidence = kwargs.pop("evidence_refs", _evidence_refs())
        result = plane.submit_work(evidence, confirm=True, **kwargs)
        assert result["result"] == "DENIED"
        assert result["reason"] == "model_supplied_authority"
        assert result["executed"] is False
    assert plane.execution_log == []
    assert plane.work == {}
    assert bridge_stub.calls == []


def test_submit_work_spawn_flag_one_still_does_not_execute(plane, monkeypatch):
    monkeypatch.setenv(SPAWN_ENV, "1")
    assert spawn_flag() == 1
    result = plane.submit_work(_evidence_refs(), confirm=True)
    assert result["result"] == "accepted_for_intake"
    assert result["executed"] is False
    assert result["spawn_flag"] == 1
    assert plane.execution_log == []


def test_submit_work_requires_evidence_refs(plane, bridge_stub):
    assert plane.submit_work([])["result"] == "DENIED"
    assert plane.submit_work(None)["result"] == "DENIED"
    assert bridge_stub.calls == []


def test_submit_work_bridge_reject_does_not_invoke_executor(tmp_path):
    stub = StubBridgeClient(fail_with="bridge_rejected")
    plane = ControlPlane(
        event_store=EventStore(tmp_path / "events.sqlite3"),
        approval_store=ApprovalStore(tmp_path / "approvals.sqlite3"),
        bridge_client=stub,
    )
    result = plane.submit_work(_evidence_refs(), confirm=True, summary="should fail closed")
    assert result["result"] == "DENIED"
    assert result["reason"] == "bridge_rejected"
    assert result["executed"] is False
    assert plane.work == {}
    assert plane.execution_log == []
    assert stub.executor_invocations == 0
    assert len(stub.calls) == 1


def test_submit_work_missing_bridge_authority_fails_closed(tmp_path, monkeypatch):
    monkeypatch.delenv(BRIDGE_BIN_ENV, raising=False)
    monkeypatch.delenv(BRIDGE_REPO_ENV, raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    plane = ControlPlane(
        event_store=EventStore(tmp_path / "events.sqlite3"),
        approval_store=ApprovalStore(tmp_path / "approvals.sqlite3"),
        bridge_client=BridgeWorkClient.from_env(),
    )
    result = plane.submit_work(_evidence_refs(), confirm=True)
    assert result["result"] == "DENIED"
    assert result["executed"] is False
    assert result["reason"] in {
        "bridge_binary_missing",
        "bridge_repo_missing",
        "bridge_binary_not_allowlisted",
    }
    assert plane.work == {}
    assert plane.execution_log == []


def test_bridge_work_client_argv_is_allowlisted_ingest_only(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    bridge = bin_dir / "bridge"
    bridge.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    bridge.chmod(0o755)
    repo = tmp_path / "repo"
    repo.mkdir()
    argv = build_ingest_argv(bridge_bin=bridge.resolve(), repo=repo.resolve())
    assert argv == [str(bridge.resolve()), "ingest", "-", "--repo", str(repo.resolve())]
    assert "spawn" not in argv
    assert "shell" not in "".join(argv).lower()


def test_bridge_work_client_rejects_non_bridge_binary_name(tmp_path):
    impostor = tmp_path / "not-bridge"
    impostor.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    impostor.chmod(0o755)
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(BridgeIngestError, match="bridge_binary_not_allowlisted"):
        build_ingest_argv(bridge_bin=impostor.resolve(), repo=repo.resolve())


@pytest.mark.skipif(not BRIDGE_BIN, reason="local bridge binary not installed")
def test_submit_work_integration_against_local_bridge(tmp_path, monkeypatch):
    """Real `bridge ingest` handshake; stores intake path/id only."""
    bridge_bin = Path(BRIDGE_BIN).resolve()
    assert bridge_bin.name == "bridge"
    repo = tmp_path / "bridge-repo"
    repo.mkdir()
    client = BridgeWorkClient(bridge_bin=bridge_bin, repo=repo)
    plane = ControlPlane(
        event_store=EventStore(tmp_path / "events.sqlite3"),
        approval_store=ApprovalStore(tmp_path / "approvals.sqlite3"),
        bridge_client=client,
    )
    monkeypatch.setenv(SPAWN_ENV, "0")
    result = plane.submit_work(
        _evidence_refs(),
        confirm=True,
        summary="LA-03 integration against local Bridge ingest",
    )
    assert result["result"] == "accepted_for_intake"
    assert result["executed"] is False
    assert result["spawn_flag"] == 0
    assert result["confirm_is_authority"] is False
    intake_path = Path(result["bridge_intake_path"])
    assert intake_path.is_file()
    assert str(repo.resolve()) in str(intake_path.resolve())
    assert result["bridge_work_packet_id"].startswith("workpacket:")
    assert result["bridge_result_id"].startswith("result:")
    stored = json.loads(intake_path.read_text(encoding="utf-8"))
    assert "event" in stored and "work_packet" in stored
    assert plane.execution_log == []
    # Adversarial: reject path does not write executor state
    bad = StubBridgeClient(fail_with="bridge_rejected")
    denied_plane = ControlPlane(
        event_store=EventStore(tmp_path / "events2.sqlite3"),
        approval_store=ApprovalStore(tmp_path / "approvals2.sqlite3"),
        bridge_client=bad,
    )
    denied = denied_plane.submit_work(_evidence_refs(), confirm=True)
    assert denied["result"] == "DENIED"
    assert denied_plane.execution_log == []


def test_server_side_approval_lookup_is_not_execution(plane):
    minted = plane.approval_store.create_request(
        method="POST",
        path="/messages/compose",
        body={},
        provider="gmail",
        operation="submit_work",
        approval_class="consequential",
        executor="inbox",
        account_ref="",
        resource_ref="",
        item_count=1,
        payload_hash="",
        query_hash="",
    )
    plane.approval_store.decide_request(
        minted["request_id"], approved=True, lease_id="lease_server_only"
    )
    result = plane.submit_work(_evidence_refs(), confirm=True)
    assert result["result"] == "accepted_for_intake"
    assert result["executed"] is False
    assert result["server_authority_present"] is True
    fetched = plane.get_work(result["work_id"])
    assert fetched["work"]["server_authority"]["lease_id"] == "lease_server_only"


def test_resolve_is_per_world_and_does_not_fill_from_memory(plane):
    ok = plane.resolve(["control_plane", "capture"])
    assert ok["result"] == "ok"
    assert ok["missing_filled_from_memory"] is False
    assert [row["world"] for row in ok["worlds"]] == ["control_plane", "capture"]
    bridge = plane.resolve(["bridge"])
    assert bridge["result"] == "DENIED"
    assert bridge["worlds"][0]["status"] == "unavailable"
    assert bridge["worlds"][0]["source"] == "not_probed"
    unknown = plane.resolve(["invented_world"])
    assert unknown["result"] == "DENIED"
    assert unknown["worlds"][0]["source"] == "unknown_world"
    mixed = plane.resolve(["capture", "bridge"])
    assert mixed["worlds"][0]["status"] == "ok"
    assert mixed["worlds"][1]["status"] == "unavailable"


def test_run_shortcut_unknown_id_denied_known_id_does_not_execute(plane):
    unknown = plane.run_shortcut("SC-999", confirm=True)
    assert unknown["result"] == "DENIED"
    assert unknown["executed"] is False
    known = plane.run_shortcut("SC-014", confirm=True)
    assert known["result"] == "accepted_for_intake"
    assert known["executed"] is False
    assert known["argv_executed"] is False
    assert known["stored_name_returned"] is False
    named = plane.run_shortcut("SC-014", stored_name="Open Inbox")
    assert named["result"] == "DENIED"
    assert named["reason"] == "model_supplied_authority"


def test_cancel_and_verify_do_not_execute(plane):
    submitted = plane.submit_work(_evidence_refs(), confirm=True)
    work_id = submitted["work_id"]
    cancelled = plane.cancel_work(work_id, confirm=True)
    verified = plane.verify_work(work_id, confirm=True)
    assert cancelled["result"] == "accepted_for_intake"
    assert verified["result"] == "accepted_for_intake"
    assert cancelled["executed"] is False
    assert verified["executed"] is False
    assert verified["verifier_executed"] is False
    assert plane.cancel_work("wrk_missing")["result"] == "DENIED"
    assert plane.verify_work("wrk_missing")["result"] == "DENIED"


def test_execution_submit_declares_intent_not_execution(plane):
    submitted = plane.submit_work(_evidence_refs(), confirm=True)
    work_ref = submitted["work_id"]
    result = plane.execution_submit(
        work_ref, execution_mode="dry_run", requested_backend="mac_controller", note="prep"
    )
    assert result["result"] == "created"
    assert result["executed"] is False
    assert result["execution_claimed"] is False
    assert result["intent"]["payload"]["work_ref"] == work_ref
    assert result["intent"]["payload"]["execution_mode"] == "dry_run"
    assert result["intent"]["payload"]["requested_backend"] == "mac_controller"
    assert result["intent"]["event_type"] == "execution.intent.v1"
    assert plane.execution_log == []


def test_execution_submit_defaults_backend_to_unspecified(plane):
    result = plane.execution_submit("wrk_abc123def456", execution_mode="supervised")
    assert result["result"] == "created"
    assert result["intent"]["payload"]["requested_backend"] == "unspecified"


def test_execution_submit_rejects_unknown_backend_and_mode(plane):
    unknown_backend = plane.execution_submit(
        "wrk_abc123def456", execution_mode="dry_run", requested_backend="ssh_shell"
    )
    unknown_mode = plane.execution_submit("wrk_abc123def456", execution_mode="autonomous")
    assert unknown_backend["result"] == "DENIED"
    assert unknown_backend["reason"] == "requested_backend is not a known backend"
    assert unknown_backend["executed"] is False
    assert unknown_mode["result"] == "DENIED"
    assert unknown_mode["reason"] == "execution_mode is not a bounded mode"
    assert plane.event_store.count() == 0


def test_execution_submit_rejects_bad_work_ref_formats(plane):
    for bad_ref in ("", "../etc/passwd", "shell:rm -rf", "totally-made-up-id", "wrk_short"):
        result = plane.execution_submit(bad_ref, execution_mode="dry_run")
        assert result["result"] == "DENIED"
        assert "work_ref" in result["reason"]
    assert plane.event_store.count() == 0


def test_execution_submit_rejects_unknown_and_confirm_fields(plane):
    for kwargs in ({"confirm": True}, {"lease_id": "lease_fake"}, {"stray_field": "x"}):
        result = plane.execution_submit("wrk_abc123def456", execution_mode="dry_run", **kwargs)
        assert result["result"] == "DENIED"
        assert result["executed"] is False
    assert plane.event_store.count() == 0
    assert plane.execution_log == []


def test_execution_status_reports_no_intent_then_latest_intent(plane):
    ref = "wrk_abc123def456"
    empty = plane.execution_status(ref)
    assert empty["result"] == "ok"
    assert empty["status"] == "no_intent_recorded"
    assert empty["intents_recorded"] == 0
    assert empty["latest_intent"] is None
    assert empty["executed"] is False

    plane.execution_submit(ref, execution_mode="dry_run")
    plane.execution_submit(ref, execution_mode="supervised", note="second declaration")

    status = plane.execution_status(ref)
    assert status["status"] == "intent_recorded"
    assert status["intents_recorded"] == 2
    assert status["latest_intent"]["payload"]["execution_mode"] == "supervised"
    assert status["executed"] is False


def test_execution_status_rejects_malformed_ref_and_unknown_field(plane):
    bad = plane.execution_status("not-a-real-ref")
    assert bad["result"] == "DENIED"
    extra = plane.execution_status("wrk_abc123def456", surprise="field")
    assert extra["result"] == "DENIED"
    assert extra["reason"] == "unknown_field"


def test_execution_events_lists_across_and_within_work_refs(plane):
    ref_a = "wrk_aaaaaaaaaaaaaaaa"
    ref_b = "wrk_bbbbbbbbbbbbbbbb"
    plane.execution_submit(ref_a, execution_mode="dry_run")
    plane.execution_submit(ref_b, execution_mode="supervised")

    scoped = plane.execution_events(ref_a)
    assert scoped["result"] == "ok"
    assert scoped["count"] == 1
    assert scoped["events"][0]["payload"]["work_ref"] == ref_a

    unscoped = plane.execution_events()
    assert unscoped["count"] == 2
    assert {e["payload"]["work_ref"] for e in unscoped["events"]} == {ref_a, ref_b}
    assert unscoped["executed"] is False


def test_execution_intent_survives_across_control_plane_instances(tmp_path, bridge_stub):
    """Durable means it outlives the process, not just the ControlPlane object."""
    event_db = tmp_path / "shared_events.sqlite3"
    approval_db = tmp_path / "shared_approvals.sqlite3"
    first = ControlPlane(
        event_store=EventStore(event_db),
        approval_store=ApprovalStore(approval_db),
        bridge_client=bridge_stub,
    )
    submitted = first.execution_submit("wrk_durable1234567", execution_mode="dry_run")
    assert submitted["result"] == "created"

    second = ControlPlane(
        event_store=EventStore(event_db),
        approval_store=ApprovalStore(approval_db),
        bridge_client=bridge_stub,
    )
    status = second.execution_status("wrk_durable1234567")
    assert status["status"] == "intent_recorded"
    assert status["intents_recorded"] == 1


def _direct_call_payload(blocks) -> dict:
    """mcp.call_tool() (no session) returns raw ContentBlocks, not a
    CallToolResult -- unlike the session-based helper `_tool_payload` above."""
    return json.loads(blocks[0].text)


def test_execution_tools_reach_control_plane_over_mcp(plane):
    mcp = build_control_plane_mcp(plane)

    async def scenario():
        submit = await mcp.call_tool(
            "execution_submit",
            {"work_ref": "wrk_mcpwired1234567", "execution_mode": "dry_run"},
        )
        status = await mcp.call_tool("execution_status", {"work_ref": "wrk_mcpwired1234567"})
        events = await mcp.call_tool("execution_events", {})
        return submit, status, events

    submit_result, status_result, events_result = asyncio.run(scenario())
    submit_payload = _direct_call_payload(submit_result)
    status_payload = _direct_call_payload(status_result)
    events_payload = _direct_call_payload(events_result)
    assert submit_payload["result"] == "created"
    assert submit_payload["executed"] is False
    assert status_payload["status"] == "intent_recorded"
    assert events_payload["count"] == 1


def test_execution_adapter_tools_reach_control_plane_over_mcp(plane_with_orca_spy, orca_spy):
    """The new execution_inspect/start/run_status/cancel/verify_close tools,
    called the same way as execution_submit/status/events above, actually
    reach ControlPlane's shared ExecutionAdapter -- and execution_start
    still denies with zero Orca calls even over the full MCP call path."""
    mcp = build_control_plane_mcp(plane_with_orca_spy)

    async def scenario():
        inspect = await mcp.call_tool("execution_inspect", {"work_id": "wrk_abc123def456"})
        start = await mcp.call_tool(
            "execution_start",
            {
                "work_id": "wrk_abc123def456",
                "admission_ref": "adm-ref-mcp-001",
                "idempotency_key": "idem-mcp-001",
            },
        )
        run_status = await mcp.call_tool("execution_run_status", {"run_id": "run_" + "d" * 32})
        cancel = await mcp.call_tool("execution_cancel", {"run_id": "run_" + "d" * 32})
        verify = await mcp.call_tool("execution_verify_close", {"run_id": "run_" + "d" * 32})
        return inspect, start, run_status, cancel, verify

    inspect_r, start_r, status_r, cancel_r, verify_r = asyncio.run(scenario())
    assert _direct_call_payload(inspect_r)["result"] == "ok"
    assert _direct_call_payload(start_r)["result"] == "DENIED"
    assert _direct_call_payload(start_r)["reason"] == "authority_interface_missing"
    assert _direct_call_payload(status_r)["status"] == "not_found"
    assert _direct_call_payload(cancel_r)["reason"] == "unknown_run"
    assert _direct_call_payload(verify_r)["reason"] == "unknown_run"
    assert orca_spy.calls == []


def test_execution_start_denied_by_default_zero_orca_calls(plane_with_orca_spy, orca_spy):
    """Direct-call form of the zero-spawn proof: MissingAuthorityInterface
    is still the only shipped AdmissionAuthority on the canonical
    ControlPlane, so execution_start denies before ever reaching Orca."""
    result = plane_with_orca_spy.execution_start(
        "wrk_abc123def456", admission_ref="adm-ref-001", idempotency_key="idem-canonical-001"
    )
    assert result["result"] == "DENIED"
    assert result["reason"] == "authority_interface_missing"
    assert result["executed"] is False
    assert orca_spy.calls == []


def test_execution_start_replay_and_conflict_reach_canonical_control_plane(plane):
    """Idempotency semantics (proved at the adapter level in
    tests/test_execution_adapter.py) also hold through ControlPlane's thin
    delegation -- not reimplemented, not bypassed."""
    first = plane.execution_start(
        "wrk_abc123def456", admission_ref="adm-ref-001", idempotency_key="idem-replay-001"
    )
    second = plane.execution_start(
        "wrk_abc123def456", admission_ref="adm-ref-001", idempotency_key="idem-replay-001"
    )
    assert first["result"] == "DENIED"
    assert second["idempotent_replay"] is True

    conflict = plane.execution_start(
        "wrk_abc123def456", admission_ref="adm-ref-DIFFERENT", idempotency_key="idem-replay-001"
    )
    assert conflict["reason"] == "idempotency_key_conflict"


def test_health_advertises_execution_tools_as_authority_gated_not_a_live_canary(monkeypatch):
    monkeypatch.setenv(CONTROL_PLANE_TOKEN_ENV, "control-secret")
    app = make_control_plane_app()
    with TestClient(app) as client:
        health = client.get("/health").json()
    assert set(CONTROL_PLANE_TOOL_NAMES).issubset(set(health["tools"]))
    for name in (
        "execution_inspect",
        "execution_start",
        "execution_run_status",
        "execution_cancel",
        "execution_verify_close",
    ):
        assert name in health["tools"]
    assert health["execution_tools_exposed"] is True
    assert health["execution_authority_gated"] is True
    # Not a live-canary claim: no grant path exists in this repo today.
    assert health["execution_enabled"] is False


def test_make_control_plane_injects_execution_adapter_dependencies_for_tests(tmp_path, orca_spy):
    """DI added to make_control_plane only as needed for tests: a caller can
    inject an ExecutionAdapter, an AdmissionAuthority, or an Orca client
    double without standing up a second store or a second authority."""
    plane = make_control_plane(
        event_db=tmp_path / "events.sqlite3",
        approval_db=tmp_path / "approvals.sqlite3",
        orca_client=orca_spy,
    )
    assert plane.execution_adapter.orca_client is orca_spy
    assert plane.execution_adapter.event_store is plane.event_store
    assert plane.execution_adapter.approval_store is plane.approval_store


def test_control_plane_source_cannot_import_spawn_or_subprocess():
    source = (ROOT / "mcp_control_plane.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    # PR-2B: thin bridge_work_client is allowed; subprocess/spawn stay out.
    assert "bridge_work_client" in imported
    assert "subprocess" not in imported
    assert "bridge" not in imported  # no Go package / spawn module
    assert "inbox_bridge_adapter" not in imported
    assert "run_shell" not in source
    assert "epistemic" not in source.lower()
    assert "PublicAuthMiddleware" not in source
    assert "_is_publicly_authorized" not in source
    assert 'Mount("/mcp"' not in source
    assert "streamable_http_app()" in source
    assert "bridge spawn" not in source.lower()
    assert "promote-approval" not in source.lower()
    # Client itself must not allowlist spawn.
    client_src = (ROOT / "bridge_work_client.py").read_text(encoding="utf-8")
    assert 'ALLOWED_VERBS = frozenset({"ingest"})' in client_src
    assert "shell=False" in client_src
    assert '"spawn"' not in client_src
    assert '"promote-approval"' not in client_src


def test_build_submit_work_envelope_is_bridge_contracts_v1():
    envelope = build_submit_work_envelope(
        work_id="wrk_abc",
        summary="hello",
        evidence_refs=_evidence_refs(),
        occurred_at="2026-09-06T06:00:00Z",
    )
    assert envelope["version"] == "bridge.contracts.v1"
    assert envelope["id"] == "inbox:control_plane:wrk_abc"
    assert envelope["kind"] == "inbox.control_plane.submit_work"
    assert envelope["source"] == "inbox"
    assert envelope["payload"]["text"] == "hello"
    assert "role" not in envelope
    assert "lease" not in envelope
    assert "capability" not in envelope


def _tool_payload(result) -> dict:
    if getattr(result, "structuredContent", None) is not None:
        payload = result.structuredContent
        if (
            isinstance(payload, dict)
            and set(payload) == {"result"}
            and isinstance(payload["result"], dict)
        ):
            payload = payload["result"]
        if isinstance(payload, dict):
            return payload
    texts = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            texts.append(text)
    if len(texts) == 1:
        try:
            parsed = json.loads(texts[0])
        except json.JSONDecodeError:
            return {"text": texts[0]}
        if isinstance(parsed, dict):
            return parsed
    return {"isError": getattr(result, "isError", None), "content": texts}


async def _serve_control_plane(app):
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(200):
            if server.started:
                break
            await asyncio.sleep(0.025)
        else:
            raise RuntimeError("control plane uvicorn did not start")
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


def test_real_mcp_client_initialize_lists_tools_and_resolve(plane, monkeypatch):
    """Official Streamable HTTP client against the production ASGI topology."""
    monkeypatch.setenv(CONTROL_PLANE_TOKEN_ENV, "control-secret")
    monkeypatch.setenv(SPAWN_ENV, "0")
    app = make_control_plane_app(plane)
    token = "control-secret"

    async def scenario():
        agen = _serve_control_plane(app)
        base = await anext(agen)
        try:
            url = f"{base}/mcp"
            headers = {"Authorization": f"Bearer {token}"}
            async with (
                httpx.AsyncClient(
                    headers=headers,
                    timeout=httpx.Timeout(30.0, read=60.0),
                    follow_redirects=False,
                ) as http,
                streamable_http_client(url, http_client=http) as streams,
            ):
                read, write = streams[0], streams[1]
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    listed = await session.list_tools()
                    resolved = await session.call_tool("resolve", {"worlds": ["control_plane"]})
                    return init, listed, resolved
        finally:
            await agen.aclose()

    init, listed, resolved = asyncio.run(scenario())
    names = tuple(tool.name for tool in listed.tools)
    payload = _tool_payload(resolved)
    assert init.serverInfo is not None
    assert init.serverInfo.name == "Inbox Control Plane"
    assert names == CONTROL_PLANE_TOOL_NAMES
    assert resolved.isError is False
    assert payload["result"] == "ok"
    assert payload["executed"] is False
    assert payload["spawn_flag"] == 0
    assert payload["missing_filled_from_memory"] is False


def test_mcp_post_does_not_307_and_does_not_500_without_session_manager(plane, monkeypatch):
    monkeypatch.setenv(CONTROL_PLANE_TOKEN_ENV, "control-secret")
    app = make_control_plane_app(plane)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer control-secret",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
    assert response.status_code not in {307, 404, 500}
    assert response.status_code != 401
