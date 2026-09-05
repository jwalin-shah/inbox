from __future__ import annotations

import pytest


@pytest.mark.anyio
async def test_task_duplicate_review_is_bounded_and_non_mutating(monkeypatch) -> None:
    import lifeops_mcp

    async def fake_reconciliation(*, account: str, limit: int):
        assert account == "jshah1331@gmail.com"
        assert limit == 500
        return {
            "projection": "inbox_task_reconciliation_v1",
            "task_count": 4,
            "unmatched_existing_task_count": 2,
            "coverage": {"provider_writes": False},
            "duplicate_task_groups": [
                [
                    {"id": "task-2", "account": account, "title": "Call Yadel tomorrow"},
                    {"id": "task-1", "account": account, "title": "Call Yadel tomorrow"},
                ],
                [
                    {"id": "task-3", "account": account, "title": "Follow up with health office"},
                    {"id": "task-4", "account": account, "title": "Follow up with the health office"},
                ],
            ],
        }

    monkeypatch.setattr(lifeops_mcp, "task_reconciliation", fake_reconciliation)
    result = await lifeops_mcp.task_duplicate_review(
        account="jshah1331@gmail.com", limit=1
    )

    assert result["schema_version"] == "lifeops.task_duplicate_review.v1"
    assert result["read_only"] is True
    assert result["group_count"] == 1
    assert result["task_count"] == 4
    assert result["groups"][0]["match_type"] == "exact_title"
    assert result["groups"][0]["automatic_mutation"] is False
    assert [task["id"] for task in result["groups"][0]["tasks"]] == ["task-2", "task-1"]
    assert result["groups"][0]["review_id"].startswith("task_duplicate_review:")


@pytest.mark.anyio
async def test_task_duplicate_review_classifies_near_duplicates(monkeypatch) -> None:
    import lifeops_mcp

    async def fake_reconciliation(*, account: str, limit: int):
        return {
            "duplicate_task_groups": [
                [
                    {"id": "task-1", "account": account, "title": "Review B12 appointment"},
                    {"id": "task-2", "account": account, "title": "Review the B12 appointment"},
                ]
            ]
        }

    monkeypatch.setattr(lifeops_mcp, "task_reconciliation", fake_reconciliation)
    result = await lifeops_mcp.task_duplicate_review(account="me@example.com")

    assert result["groups"][0]["match_type"] == "conservative_near_duplicate"
    assert result["groups"][0]["automatic_mutation"] is False
