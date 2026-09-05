import asyncio
from unittest.mock import AsyncMock, patch

import lifeops_mcp


def _run(awaitable):
    return asyncio.run(awaitable)


def test_identity_review_filters_people_and_preserves_place_project_evidence():
    context = {
        "sections": {
            "people": [
                {
                    "title": "Harsh",
                    "identity_resolution": {"status": "candidate"},
                    "candidate_source_refs": [{"source": "contacts", "id": "c-1"}],
                    "source_ref": {"source": "lifeops_sheet", "id": "p-1"},
                },
                {
                    "title": "Known",
                    "identity_resolution": {"status": "matched"},
                    "source_ref": {"source": "lifeops_sheet", "id": "p-2"},
                },
            ],
            "places": [
                {
                    "title": "45738 Bridgeport Dr.",
                    "observation_count": 2,
                    "source_ref": {"source": "calendar", "id": "event-1"},
                    "evidence_refs": [{"source": "contacts", "id": "c-1"}],
                }
            ],
            "projects": [
                {
                    "title": "Street play",
                    "source_ref": {"source": "lifeops_memory", "id": "project-1"},
                    "linked_source_refs": [{"source": "google_sheets", "id": "row-1"}],
                }
            ],
        },
        "source_health": {"triage": {"status": "ok"}},
    }
    with patch.object(lifeops_mcp, "life_context", new=AsyncMock(return_value=context)) as read:
        result = _run(lifeops_mcp.identity_review(status="candidate", limit=10))

    assert result["schema_version"] == "lifeops.identity_review.v1"
    assert result["read_only"] is True
    assert [item["title"] for item in result["people"]] == ["Harsh"]
    assert result["counts"] == {"people": 1, "places": 1, "projects": 1}
    assert {ref["source"] for ref in result["provenance"]["references"]} == {
        "contacts",
        "lifeops_sheet",
        "calendar",
        "lifeops_memory",
        "google_sheets",
    }
    read.assert_awaited_once_with(
        limit=10,
        section_limit=100,
        calendar_days=30,
        account="",
        use_model=False,
    )


def test_people_projection_exposes_exact_contact_candidates_for_ambiguous_match():
    result = lifeops_mcp._context_lifeops_people(
        [
            {
                "person_id": "person-1",
                "name": "Alex",
                "source_ref": {"source": "lifeops_sheet", "id": "row-1"},
            }
        ],
        [
            {"id": "contact-1", "name": "Alex Johnson", "emails": ["alex@example.com"]},
            {"id": "contact-2", "name": "Alex Shah", "phones": ["+15550001"]},
        ],
        10,
    )

    person = result[0]
    resolution = person["identity_resolution"]
    assert resolution["status"] == "ambiguous"
    assert {ref["id"] for ref in resolution["candidate_source_refs"]} == {
        "contact-1",
        "contact-2",
    }
    assert {ref["id"] for ref in person["candidate_source_refs"]} == {
        "contact-1",
        "contact-2",
    }
    refs_by_id = {ref["id"]: ref for ref in resolution["candidate_source_refs"]}
    assert refs_by_id["contact-1"]["emails"] == ["alex@example.com"]
    assert refs_by_id["contact-2"]["phones"] == ["+15550001"]


def test_people_projection_does_not_match_common_surname_fragment():
    result = lifeops_mcp._context_lifeops_people(
        [
            {
                "person_id": "person-1",
                "name": "Anish Shah",
                "source_ref": {"source": "lifeops_sheet", "id": "row-1"},
            }
        ],
        [
            {"id": "contact-1", "name": "Riti Shah"},
            {"id": "contact-2", "name": "Nalin Shah"},
        ],
        10,
    )

    person = result[0]
    assert person["identity_resolution"]["status"] == "unmatched"
    assert person["candidate_source_refs"] == []


def test_project_shorthand_is_candidate_without_becoming_a_link():
    refs, resolutions = lifeops_mcp._resolve_explicit_projects(
        "GitHits",
        [
            {
                "project_id": "project-1",
                "title": "GitHits one-pager + introduction graph",
                "source_ref": {"source": "google_sheets", "id": "row-1"},
            }
        ],
    )

    assert refs == []
    assert resolutions == [
        {
            "input": "GitHits",
            "status": "candidate",
            "candidate_project_ids": ["project-1"],
            "candidate_project_names": ["GitHits one-pager + introduction graph"],
        }
    ]


def test_review_queue_combines_unresolved_identity_and_project_links():
    context = {
        "sections": {
            "people": [
                {
                    "item_id": "lifeops_sheet_person:p-1",
                    "title": "Vivek",
                    "identity_resolution": {
                        "status": "ambiguous",
                        "candidate_source_refs": [{"source": "contacts", "id": "c-1"}],
                    },
                    "candidate_source_refs": [{"source": "contacts", "id": "c-1"}],
                    "source_ref": {"source": "google_sheets", "id": "people-1"},
                }
            ],
            "commitments": [
                {
                    "item_id": "lifeops_sheet_action:a-1",
                    "title": "Follow up with Nathan",
                    "related_project_resolution": [
                        {
                            "input": "GitHits",
                            "status": "candidate",
                            "candidate_project_ids": ["p-1"],
                        }
                    ],
                    "source_ref": {"source": "google_sheets", "id": "action-1"},
                }
            ],
        },
        "source_health": {"unified_contacts": {"status": "ok"}},
    }
    with (
        patch.object(lifeops_mcp, "life_context", new=AsyncMock(return_value=context)),
        patch.object(
            lifeops_mcp,
            "coverage_report",
            new=AsyncMock(return_value={"accounts": [], "completeness": {"planned_sources": []}}),
        ),
    ):
        result = _run(lifeops_mcp.review_queue(limit=10))

    assert result["schema_version"] == "lifeops.review_queue.v1"
    assert result["read_only"] is True
    assert result["counts"] == {
        "total": 2,
        "identity_link": 1,
        "project_link": 1,
        "source_health": 0,
        "source_gap": 0,
        "ambiguous": 1,
        "candidate": 1,
        "unmatched": 0,
    }
    assert result["available_counts"] == result["counts"]
    assert result["truncated"] is False
    assert result["pagination"] == {
        "offset": 0,
        "limit": 10,
        "has_more": False,
        "next_offset": None,
    }
    assert [item["kind"] for item in result["items"]] == ["identity_link", "project_link"]

    with (
        patch.object(lifeops_mcp, "life_context", new=AsyncMock(return_value=context)),
        patch.object(
            lifeops_mcp,
            "coverage_report",
            new=AsyncMock(return_value={"accounts": [], "completeness": {"planned_sources": []}}),
        ),
    ):
        page = _run(lifeops_mcp.review_queue(limit=1, offset=1))

    assert len(page["items"]) == 1
    assert page["items"][0]["kind"] == "project_link"
    assert page["pagination"] == {
        "offset": 1,
        "limit": 1,
        "has_more": False,
        "next_offset": None,
    }


def test_review_queue_includes_unscoped_source_gaps():
    context = {"sections": {}, "source_health": {}}
    coverage = {
        "accounts": [],
        "unscoped_sources": [
            {
                "source_id": "whatsapp",
                "display_name": "WhatsApp",
                "status": "not_configured",
                "configured": False,
                "readable": False,
                "freshness": {"status": "unknown"},
            }
        ],
        "completeness": {"planned_sources": []},
    }
    with (
        patch.object(lifeops_mcp, "life_context", new=AsyncMock(return_value=context)),
        patch.object(lifeops_mcp, "coverage_report", new=AsyncMock(return_value=coverage)),
    ):
        result = _run(lifeops_mcp.review_queue(limit=10))

    assert result["counts"]["source_health"] == 1
    assert result["items"][0]["kind"] == "source_health"
    assert result["items"][0]["title"] == "WhatsApp (local)"
    assert result["items"][0]["status"] == "blocked"


def test_review_queue_marks_partial_context_without_conflating_pagination():
    context = {
        "sections": {},
        "source_health": {"unified_contacts": {"status": "unavailable"}},
        "limitations": ["contacts_read_unavailable"],
    }
    coverage = {"accounts": [], "unscoped_sources": [], "completeness": {"planned_sources": []}}
    with (
        patch.object(lifeops_mcp, "life_context", new=AsyncMock(return_value=context)),
        patch.object(lifeops_mcp, "coverage_report", new=AsyncMock(return_value=coverage)),
    ):
        result = _run(lifeops_mcp.review_queue(limit=10))

    assert result["complete"] is False
    assert result["completeness"]["status"] == "partial"
    assert "contacts_read_unavailable" in result["limitations"]
    assert result["truncated"] is False
