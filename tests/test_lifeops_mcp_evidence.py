import asyncio
from unittest.mock import AsyncMock, patch

import lifeops_mcp


def run(coro):
    return asyncio.run(coro)


def test_source_registry_reads_the_inbox_registry():
    with patch.object(
        lifeops_mcp,
        "_request",
        new=AsyncMock(return_value={"registry_version": "v1", "sources": []}),
    ) as request:
        result = run(lifeops_mcp.source_registry())

    assert result["registry_version"] == "v1"
    request.assert_awaited_once_with("GET", "/sources/registry")


def test_evidence_events_bounds_and_filters_the_read():
    with patch.object(
        lifeops_mcp,
        "_request",
        new=AsyncMock(return_value={"count": 1, "events": []}),
    ) as request:
        result = run(lifeops_mcp.evidence_events(source="imessage", limit=999))

    assert result["count"] == 1
    request.assert_awaited_once_with(
        "GET",
        "/events",
        params={"source": "imessage", "event_type": "", "limit": 200},
    )


def test_property_evidence_is_a_read_only_projection_over_property_events():
    with patch.object(
        lifeops_mcp,
        "_request",
        new=AsyncMock(
            return_value={
                "count": 1,
                "events": [
                    {
                        "event_id": "evt-photo-1",
                        "source": "property",
                        "source_object_id": "photo-1",
                        "event_type": "property.observation",
                        "metadata": {
                            "property_id": "home-fremont",
                            "zone_id": "side-yard-01",
                            "evidence_kind": "photo",
                        },
                        "payload": {"image_path": "/tmp/side-yard.jpg"},
                    }
                ],
            }
        ),
    ) as request:
        result = run(lifeops_mcp.property_evidence(limit=999))

    assert result["schema_version"] == "lifeops.property_evidence.v1"
    assert result["read_only"] is True
    assert result["observations"][0]["zone_id"] == "side-yard-01"
    assert result["observations"][0]["evidence_kind"] == "photo"
    assert result["observations"][0]["source_ref"]["id"] == "evt-photo-1"
    request.assert_awaited_once_with(
        "GET",
        "/events",
        params={"source": "property", "event_type": "property.observation", "limit": 200},
    )


def test_capture_observation_is_local_and_provenance_tagged():
    with patch.object(
        lifeops_mcp,
        "_request",
        new=AsyncMock(return_value={"ok": True, "inserted": True}),
    ) as request:
        result = run(
            lifeops_mcp.capture_observation(
                "Nathan said the supplier may do 100 units at $6 each.",
                source_object_id="manual-1",
                confidence=0.6,
            )
        )

    assert result["inserted"] is True
    request.assert_awaited_once_with(
        "POST",
        "/events/capture",
        body={
            "source": "manual",
            "event_type": "manual.capture",
            "source_object_id": "manual-1",
            "occurred_at": "",
            "content": "Nathan said the supplier may do 100 units at $6 each.",
            "confidence": 0.6,
            "metadata": {},
            "provenance": {"channel": "lifeops_mcp"},
        },
    )


def test_document_evidence_is_bounded_and_source_linked():
    with patch.object(
        lifeops_mcp,
        "_request",
        new=AsyncMock(
            side_effect=[
                {
                    "id": "doc-1",
                    "title": "LifeOps rules",
                    "url": "https://docs.google.com/document/d/doc-1/edit",
                    "account": "jshah1331@gmail.com",
                },
                {"text": "A" * 20},
            ]
        ),
    ) as request:
        result = run(
            lifeops_mcp.document_evidence(
                "doc-1", account="jshah1331@gmail.com", max_chars=10
            )
        )

    assert result["schema_version"] == "lifeops.document_evidence.v1"
    assert result["read_only"] is True
    assert result["text"] == "A" * 10
    assert result["truncated"] is True
    assert result["source_ref"] == {
        "kind": "google_doc_body",
        "source": "google_docs",
        "id": "doc-1",
        "account": "jshah1331@gmail.com",
    }
    assert request.await_args_list[0].args == ("GET", "/docs/doc-1")
    assert request.await_args_list[1].args == ("GET", "/docs/doc-1/text")
