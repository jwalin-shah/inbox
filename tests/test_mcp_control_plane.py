"""PR-1 ingest-only MCP control plane. No Bridge, no spawn, no epistemic tool."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from approval_store import ApprovalStore
from event_store import CaptureEvent, EventStore, identity_digest_for
from mcp_control_plane import (
    CONTROL_PLANE_PORT,
    CONTROL_PLANE_TOKEN_ENV,
    CONTROL_PLANE_TOOL_NAMES,
    SPAWN_ENV,
    ControlPlane,
    build_control_plane_mcp,
    make_control_plane_app,
    spawn_flag,
)
from tools_registry import TOOLS, include_names

pytestmark = pytest.mark.safe

ROOT = Path(__file__).resolve().parents[1]


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


@pytest.fixture
def plane(tmp_path) -> ControlPlane:
    return ControlPlane(
        event_store=EventStore(tmp_path / "events.sqlite3"),
        approval_store=ApprovalStore(tmp_path / "approvals.sqlite3"),
    )


def test_frozen_tools_are_not_rest_registry_names():
    with pytest.raises(ValueError, match="unknown tool names"):
        include_names(CONTROL_PLANE_TOOL_NAMES)
    rest_names = {tool.name for tool in TOOLS}
    assert rest_names.isdisjoint(CONTROL_PLANE_TOOL_NAMES)


def test_seven_tools_enumerate(plane):
    mcp = build_control_plane_mcp(plane)
    names = tuple(tool.name for tool in asyncio.run(mcp.list_tools()))
    assert names == CONTROL_PLANE_TOOL_NAMES
    assert len(names) == 7


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


def test_submit_work_confirm_true_is_intake_not_execution(plane, monkeypatch):
    monkeypatch.setenv(SPAWN_ENV, "0")
    result = plane.submit_work(_evidence_refs(), confirm=True, summary="do the thing")
    assert result["result"] == "accepted_for_intake"
    assert result["executed"] is False
    assert result["confirm_is_authority"] is False
    assert result["spawn_flag"] == 0
    assert plane.execution_log == []
    listed = plane.get_work()
    assert listed["result"] == "ok"
    assert listed["work"][0]["work_id"] == result["work_id"]
    assert listed["work"][0]["executed"] is False


def test_submit_work_cannot_supply_lease_or_capability(plane):
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


def test_submit_work_spawn_flag_one_still_does_not_execute(plane, monkeypatch):
    monkeypatch.setenv(SPAWN_ENV, "1")
    assert spawn_flag() == 1
    result = plane.submit_work(_evidence_refs(), confirm=True)
    assert result["result"] == "accepted_for_intake"
    assert result["executed"] is False
    assert result["spawn_flag"] == 1
    assert plane.execution_log == []


def test_submit_work_requires_evidence_refs(plane):
    assert plane.submit_work([])["result"] == "DENIED"
    assert plane.submit_work(None)["result"] == "DENIED"


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


def test_control_plane_source_cannot_import_spawn_or_bridge():
    source = (ROOT / "mcp_control_plane.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "subprocess" not in imported
    assert "bridge" not in imported
    assert "inbox_bridge_adapter" not in imported
    assert "bridge_work_client" not in source
    assert "run_shell" not in source
    assert "epistemic" not in source.lower()
    assert "PublicAuthMiddleware" not in source
    assert "_is_publicly_authorized" not in source
