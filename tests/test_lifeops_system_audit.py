import asyncio
from unittest.mock import AsyncMock, patch

import lifeops_mcp


def _run(awaitable):
    return asyncio.run(awaitable)


def test_system_audit_keeps_partial_reads_and_known_gaps_explicit():
    coverage = {
        "completeness": {
            "status": "partial",
            "reasons": ["planned_source:slack"],
        },
        "embedding_index": {"model_id": "qwen", "pending": 2},
    }
    tasks = {"duplicate_task_groups": [[{"title": "Reply"}]]}
    property_data = {"count": 0}
    with (
        patch.object(lifeops_mcp, "coverage_report", new=AsyncMock(return_value=coverage)),
        patch.object(lifeops_mcp, "task_reconciliation", new=AsyncMock(return_value=tasks)),
        patch.object(lifeops_mcp, "property_evidence", new=AsyncMock(return_value=property_data)),
    ):
        result = _run(lifeops_mcp.system_audit())

    assert result["schema_version"] == "lifeops.system_audit.v1"
    assert result["read_only"] is True
    assert result["overall_status"] == "attention"
    issue_codes = {issue["code"] for issue in result["issues"]}
    assert issue_codes == {
        "coverage_partial",
        "duplicate_tasks_detected",
        "property_evidence_not_captured",
        "embeddings_pending",
    }
    assert result["checks"]["write_policy"]["status"] == "ready"
    assert result["scope"] == {
        "provider_writes": False,
        "worker_control": False,
        "secret_access": False,
        "raw_event_mutation": False,
    }
    assert {gap["code"] for gap in result["known_gaps"]} >= {
        "agent_runtime_adapter_not_exposed",
        "btw_v2_adapter_not_exposed",
    }


def test_system_audit_can_be_ready_without_claiming_unplanned_coverage():
    coverage = {
        "completeness": {
            "status": "complete_for_observed_accounts",
            "reasons": [],
        },
        "embedding_index": {"model_id": "qwen", "pending": 0},
    }
    with (
        patch.object(lifeops_mcp, "coverage_report", new=AsyncMock(return_value=coverage)),
        patch.object(lifeops_mcp, "task_reconciliation", new=AsyncMock(return_value={"duplicate_task_groups": []})),
        patch.object(lifeops_mcp, "property_evidence", new=AsyncMock(return_value={"count": 1})),
    ):
        result = _run(lifeops_mcp.system_audit())

    assert result["overall_status"] == "ready"
    assert result["issues"] == []
    assert result["checks"]["embedding_index"]["status"] == "ready"
    assert result["checks"]["property_evidence"]["status"] == "observed"

