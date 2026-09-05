from __future__ import annotations

import asyncio
import os
import stat

import pytest

import lifeops_mcp
from lifeops.work_item_store import WorkItemStore


def _proposal(key: str = "triage-2026-08-26") -> dict:
    return {
        "idempotency_key": key,
        "objective": "Classify the current inbox into reviewable attention buckets",
        "scope": {"accounts": ["jwalinshah13@gmail.com"], "sections": ["attention", "provenance"]},
        "evidence_refs": [{"source": "lifeops", "ref": "evidence_packet:synthetic"}],
        "worker": "claude",
        "model": "",
        "budget": {"max_seconds": 120, "max_cost_usd": 0},
        "acceptance_criteria": [
            "Every returned item has a source reference",
            "No provider write is performed",
        ],
    }


def test_work_item_store_is_durable_idempotent_and_append_only(tmp_path):
    store = WorkItemStore(tmp_path / "nested" / "work_items.sqlite3")
    first = store.create(_proposal())
    second = store.create(_proposal())

    assert first["created"] is True
    assert second["created"] is False
    assert second["work_item_id"] == first["work_item_id"]
    assert second["status"] == "proposed"
    assert second["dispatch_status"] == "not_admitted"
    assert [event["event_type"] for event in second["events"]] == ["proposal_created"]
    assert stat.S_IMODE(os.stat(store.db_path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(store.db_path.parent).st_mode) == 0o700


def test_work_item_store_rejects_reuse_with_changed_payload(tmp_path):
    store = WorkItemStore(tmp_path / "work_items.sqlite3")
    store.create(_proposal())
    changed = _proposal()
    changed["objective"] = "A different objective"

    with pytest.raises(ValueError, match="different proposal"):
        store.create(changed)


def test_work_item_request_rejects_credentials_and_execution_material():
    proposal = _proposal()
    proposal["scope"] = {"api_key": "do-not-store"}

    with pytest.raises(ValueError, match="credential field"):
        lifeops_mcp._validate_work_item_request(**proposal)

    proposal = _proposal()
    proposal["scope"] = {"allowed_paths": ["/tmp/project"], "command": ["rm", "-rf"]}

    with pytest.raises(ValueError, match="execution field"):
        lifeops_mcp._validate_work_item_request(**proposal)


def test_mcp_create_work_item_is_durable_and_does_not_dispatch(tmp_path, monkeypatch):
    monkeypatch.setattr(lifeops_mcp, "_WORK_ITEM_STORE", WorkItemStore(tmp_path / "work_items.sqlite3"))

    result = asyncio.run(
        lifeops_mcp.create_work_item(
            idempotency_key="synthetic-proof-1",
            objective="Produce a bounded evidence-backed review packet",
            scope={"sections": ["attention", "provenance"]},
            evidence_refs=[{"source": "lifeops", "ref": "evidence_packet:synthetic"}],
            worker="bridge",
            budget={"max_seconds": 30, "max_cost_usd": 0},
            acceptance_criteria=["Return a durable receipt"],
        )
    )

    assert result["created"] is True
    assert result["receipt"]["durable"] is True
    assert result["receipt"]["dispatch_status"] == "not_admitted"
    assert result["receipt"]["authority"] == {
        "provider_access": False,
        "terminal_access": False,
        "credential_access": False,
    }

