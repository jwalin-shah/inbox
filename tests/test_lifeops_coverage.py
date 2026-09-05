import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import lifeops_mcp


def _run(awaitable):
    return asyncio.run(awaitable)


def test_coverage_report_combines_account_health_index_and_policy():
    now = datetime.now(UTC)
    last_success = (now - timedelta(seconds=60)).isoformat()
    newest_seen = (now - timedelta(seconds=120)).isoformat()
    health = {
        "providers": {
            "summary": {"total": 2, "ready": 2, "blocked": 0, "not_configured": 0},
            "providers": [
                {
                    "provider": "google_gmail",
                    "accounts": ["me@example.com"],
                    "configured": True,
                    "authenticated": True,
                    "readable": True,
                    "writable": True,
                    "blockers": [],
                    "notes": "Gmail provider",
                }
            ],
        },
        "capture": {
            "sources": [
                {
                    "key": "gmail:me@example.com",
                    "configured": True,
                    "authenticated": True,
                    "readable": True,
                    "writable": True,
                    "status": "ok",
                    "last_success_at": last_success,
                    "newest_seen_at": newest_seen,
                    "last_error": "",
                    "coverage_notes": "indexed",
                },
                {
                    "key": "apple_contacts:",
                    "source_id": "apple_contacts",
                    "configured": True,
                    "authenticated": False,
                    "readable": True,
                    "writable": False,
                    "status": "ok",
                    "last_success_at": last_success,
                    "newest_seen_at": "",
                    "item_count": 2,
                    "last_error": "",
                    "coverage_notes": "local contacts",
                }
            ]
        },
    }
    gmail = {
        "accounts": [
            {
                "account": "me@example.com",
                "indexed": True,
                "item_count": 12,
                "thread_count": 8,
                "actionable_count": 3,
                "open_loop_count": 2,
                "time_sensitive_count": 1,
                "latest_item_at": newest_seen,
                "coverage": "indexed_and_last_sync_healthy",
                "sync": {"last_success_at": last_success, "status": "idle"},
            }
        ]
    }
    registry = {
        "registry_version": "lifeops.source_registry.v1",
        "sources": [
            {"source_id": "gmail", "display_name": "Gmail", "authority": "Gmail", "freshness_seconds": 1200},
            {"source_id": "browser_share", "lifecycle": "planned", "freshness_seconds": None},
        ],
    }
    with (
        patch.object(lifeops_mcp, "source_health", new=AsyncMock(return_value=health)),
        patch.object(lifeops_mcp, "gmail_normalization", new=AsyncMock(return_value=gmail)),
        patch.object(
            lifeops_mcp,
            "embedding_status",
            new=AsyncMock(return_value={"model_id": "bge", "pending": 0}),
        ),
        patch.object(lifeops_mcp, "source_registry", new=AsyncMock(return_value=registry)),
    ):
        result = _run(lifeops_mcp.coverage_report())

    assert result["schema_version"] == "lifeops.coverage.v1"
    assert result["read_only"] is True
    assert result["accounts"][0]["account"] == "me@example.com"
    source = result["accounts"][0]["sources"][0]
    assert source["source_id"] == "gmail"
    assert source["status"] == "ready"
    assert source["item_count"] == 12
    assert source["freshness"]["status"] == "fresh"
    assert result["unscoped_sources"][0]["source_id"] == "apple_contacts"
    assert result["unscoped_sources"][0]["status"] == "ready"
    assert result["unscoped_sources"][0]["item_count"] == 2
    assert "planned_source:browser_share" in result["completeness"]["reasons"]
