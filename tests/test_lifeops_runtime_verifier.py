from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "verify_lifeops_read_surface.py"
SPEC = importlib.util.spec_from_file_location("verify_lifeops_read_surface", MODULE_PATH)
assert SPEC and SPEC.loader
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)


class FakeRpcClient:
    def __init__(self, *, protocol=verifier.PROTOCOL_VERSION, tools=None, packet=None, context=None):
        self.protocol = protocol
        self.tools = tools if tools is not None else _tools()
        self.packet = packet if packet is not None else _packet()
        self.context = context if context is not None else _context()
        self.receipt = _receipt()
        self.calls = []

    def request(self, method, params=None):
        self.calls.append((method, params))
        if method == "initialize":
            return {"protocolVersion": self.protocol, "serverInfo": {"name": "LifeOps", "version": "test"}}
        if method == "tools/list":
            return {"tools": self.tools}
        if method == "tools/call":
            name = params["name"]
            if name == "evidence_packet":
                return {"structuredContent": self.packet}
            if name == "triage_all":
                return {"structuredContent": {"read_receipt": self.receipt}}
            if name == "read_triage_receipt":
                return {
                    "structuredContent": {
                        "schema_version": "lifeops.triage_receipt_lookup.v1",
                        "read_only": True,
                        "receipt": self.receipt,
                    }
                }
            if name == "list_triage_receipts":
                return {
                    "structuredContent": {
                        "schema_version": "lifeops.triage_receipt_list.v1",
                        "read_only": True,
                        "receipts": [self.receipt],
                        "count": 1,
                        "limit": 1,
                    }
                }
            account = params["arguments"]["account"]
            context = {
                **self.context,
                "scope": {
                    **self.context["scope"],
                    "account": account,
                    "provider_accounts": [account],
                },
            }
            return {"structuredContent": context}
        raise AssertionError(method)

    def notification(self, method):
        self.calls.append((method, None))


def _tools():
    return [{"name": name, "annotations": {"read_only_hint": True}} for name in verifier.REQUIRED_READ_TOOLS]


def _packet():
    return {
        "schema_version": "lifeops.evidence_packet.v1",
        "read_only": True,
        "scope": {
            "account_scope_mode": "provider_account_where_supported",
            "provider_writes": False,
            "worker_control": False,
            "secret_access": False,
            "raw_event_mutation": False,
        },
        "sections": {"attention": []},
    }


def _context():
    return {
        "schema_version": "lifeops.context.v1",
        "read_only": True,
        "scope": {
            "account": "account@example.com",
            "provider_account_scope": "selected_account",
            "provider_accounts": ["account@example.com"],
        },
        "source_health": {
            name: {"status": "ok"} for name in verifier.REQUIRED_CONTEXT_SOURCES
        },
        "provenance": {"reference_count": 1, "references": [{"source": "test"}]},
        "limitations": [],
    }


def _receipt():
    return {
        "schema_version": "lifeops.triage_receipt.v1",
        "run_id": "triage:test",
        "started_at": "2026-08-26T10:00:00+00:00",
        "finished_at": "2026-08-26T10:00:01+00:00",
        "account": "account@example.com",
        "account_scope": "selected_account",
        "read_only": True,
        "transport_complete": True,
        "sources": [],
        "persistence": {"status": "stored", "run_id": "triage:test"},
    }


def test_summary_proves_handshake_tools_annotations_and_bounded_packet():
    client = FakeRpcClient()
    summary = verifier.summarize_read_surface(client, account="jshah1331@gmail.com")

    assert summary["protocol_version"] == "2025-06-18"
    assert summary["tool_count"] == 9
    assert all(summary["required_tools"].values())
    assert all(summary["required_read_only"].values())
    assert summary["evidence_packet"]["read_only"] is True
    assert summary["evidence_packet"]["provider_writes"] is False
    assert summary["life_context"]["schema_version"] == "lifeops.context.v1"
    assert summary["life_context"]["scope"]["provider_account_scope"] == "selected_account"
    assert summary["life_context"]["provenance_reference_count"] == 1
    assert summary["triage_receipt"] == {
        "run_id": "triage:test",
        "durable": True,
        "read_back": True,
        "listed": True,
    }
    assert client.calls[0][0] == "initialize"
    assert any(
        method == "tools/call"
        and params["name"] == "life_context"
        and params["arguments"]["account"] == "jshah1331@gmail.com"
        for method, params in client.calls
    )


def test_summary_rejects_unmarked_required_tool():
    tools = _tools()
    tools[0] = {"name": tools[0]["name"], "annotations": {"read_only_hint": False}}
    with pytest.raises(verifier.VerificationError, match="not marked read-only"):
        verifier.summarize_read_surface(FakeRpcClient(tools=tools), account="account@example.com")


def test_summary_rejects_unsafe_scope():
    packet = _packet()
    packet["scope"]["secret_access"] = True
    with pytest.raises(verifier.VerificationError, match="not read-only"):
        verifier.summarize_read_surface(FakeRpcClient(packet=packet), account="account@example.com")


def test_summary_rejects_protocol_mismatch_and_unscoped_call():
    with pytest.raises(verifier.VerificationError, match="account is required"):
        verifier.summarize_read_surface(FakeRpcClient(), account="")
    with pytest.raises(verifier.VerificationError, match="unexpected protocol"):
        verifier.summarize_read_surface(FakeRpcClient(protocol="2024-11-05"), account="account@example.com")


def test_summary_rejects_context_without_provenance():
    context = _context()
    context["provenance"] = {}
    with pytest.raises(verifier.VerificationError, match="provenance"):
        verifier.summarize_read_surface(
            FakeRpcClient(context=context), account="account@example.com"
        )
