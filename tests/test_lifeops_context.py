from __future__ import annotations

from lifeops.context import build_context


def _entry(entry_id: int, memory_type: str, subject: str, status: str = "active") -> dict:
    return {
        "id": entry_id,
        "memory_type": memory_type,
        "subject": subject,
        "content": f"Evidence for {subject}",
        "source": "manual",
        "confidence": 0.9,
        "status": status,
        "created_at": "2026-08-25T12:00:00+00:00",
        "updated_at": "2026-08-25T12:00:00+00:00",
        "expires_at": None,
        "metadata": {"example": True},
    }


def test_context_groups_memory_and_retains_provenance():
    result = build_context(
        memory_entries=[
            _entry(1, "person", "Harsh"),
            _entry(2, "project", "Street play"),
            _entry(3, "decision", "Use Inbox as authority"),
            _entry(4, "commitment", "Call Omar", status="open"),
            _entry(5, "note", "Discarded", status="closed"),
        ],
        triage={
            "items": [
                {
                    "item_id": "gmail:thread:abc",
                    "title": "Pickup details",
                    "source": "gmail",
                    "source_ref": {"source": "gmail", "thread_id": "abc"},
                    "reason": "needs_reply",
                }
            ],
            "source_health": {"inbox": {"status": "ok", "reasons": []}},
        },
        limit=5,
        section_limit=5,
    )

    assert result["schema_version"] == "lifeops.context.v1"
    assert result["read_only"] is True
    assert [item["title"] for item in result["sections"]["people"]] == ["Harsh"]
    assert [item["title"] for item in result["sections"]["projects"]] == ["Street play"]
    assert [item["title"] for item in result["sections"]["commitments"]] == ["Call Omar"]
    assert result["sections"]["notes"] == []
    assert result["provenance"]["reference_count"] == 6
    assert result["provenance"]["sources"] == {"gmail": 1, "manual": 5}


def test_memory_provenance_retains_capture_id():
    result = build_context(
        memory_entries=[
            {
                **_entry(9, "project", "Street play"),
                "metadata": {"capture_id": "cap_123"},
            }
        ],
        triage={"items": [], "source_health": {}},
    )

    assert result["provenance"]["references"][0]["capture_id"] == "cap_123"


def test_context_conservatively_deduplicates_explicit_projects_with_evidence():
    result = build_context(
        memory_entries=[
            {
                **_entry(1, "project", "Street play"),
                "updated_at": "2026-08-25T12:00:00+00:00",
                "metadata": {
                    "capture_id": "cap_1",
                    "source_refs": [{"source": "calendar", "id": "evt_1", "kind": "event"}],
                },
            },
            {
                **_entry(2, "project", "street-play"),
                "updated_at": "2026-08-25T13:00:00+00:00",
                "metadata": {"capture_id": "cap_2"},
            },
        ],
        triage={"items": [], "source_health": {}},
        limit=5,
        section_limit=5,
    )

    projects = result["sections"]["projects"]
    assert len(projects) == 1
    assert projects[0]["project_key"] == "streetplay"
    assert projects[0]["evidence_count"] == 2
    assert {ref["capture_id"] for ref in projects[0]["evidence_refs"]} == {"cap_1", "cap_2"}
    assert projects[0]["linked_source_refs"] == [
        {"source": "calendar", "id": "evt_1", "kind": "event"}
    ]
    assert result["provenance"]["reference_count"] == 4


def test_context_projects_include_explicit_tracker_rows_with_attribution():
    result = build_context(
        memory_entries=[],
        triage={"items": [], "source_health": {}},
        project_rows=[
            {
                "project": "Life Ops",
                "area": "Personal Ops",
                "status": "Active",
                "next_action": "Keep rules simple",
                "source_ref": {
                    "kind": "google_sheet_row",
                    "source": "google_sheets",
                    "id": "tracker:Projects & Areas:row:4",
                    "row": 4,
                },
            }
        ],
        project_metadata={
            "available": True,
            "project_count": 1,
            "spreadsheet_id": "tracker",
            "sheet_name": "Projects & Areas",
        },
    )

    project = result["sections"]["projects"][0]
    assert project["title"] == "Life Ops"
    assert project["evidence_count"] == 1
    assert project["linked_source_refs"] == [
        {
            "kind": "google_sheet_row",
            "source": "google_sheets",
            "id": "tracker:Projects & Areas:row:4",
            "row": 4,
        }
    ]
    assert result["source_health"]["projects"]["project_count"] == 1


def test_context_surfaces_open_curated_email_actions_without_mutating_state():
    result = build_context(
        memory_entries=[],
        triage={"items": [], "source_health": {}},
        queue_rows=[
            {
                "email_id": "E-0001",
                "subject": "Review billing",
                "action_needed": "Update billing model",
                "status": "Open",
                "source_ref": {
                    "kind": "google_sheet_row",
                    "source": "google_sheets",
                    "id": "tracker:Email Action Queue:row:2",
                    "row": 2,
                },
            }
        ],
        queue_metadata={"available": True, "email_action_count": 1},
    )

    item = result["sections"]["attention"][0]
    assert item["title"] == "Review billing"
    assert item["attention_class"] == "curated_email_action"
    assert item["source_ref"]["id"] == "tracker:Email Action Queue:row:2"
    assert result["source_health"]["master_ops"]["email_action_count"] == 1
    assert result["read_only"] is True


def test_context_projects_lifeops_people_and_actions_with_identity_state():
    result = build_context(
        memory_entries=[],
        triage={"items": [], "source_health": {}},
        contact_rows=[{"id": "alex-contact", "name": "Alex"}],
        lifeops_people_rows=[
            {
                "person_id": "P-ALEX",
                "name": "Alex",
                "organization": "Example Co",
                "relationship_context": "Warm contact",
                "identity_confidence": "high",
                "source_ref": {
                    "kind": "google_sheet_row",
                    "source": "google_sheets",
                    "id": "lifeops:People:row:2",
                    "row": 2,
                },
            }
        ],
        lifeops_action_rows=[
            {
                "action_id": "A-1",
                "action": "Reply to Alex",
                "state": "READY_HUMAN",
                "related_person": "Alex",
                "source_ref": {
                    "kind": "google_sheet_row",
                    "source": "google_sheets",
                    "id": "lifeops:Actions:row:2",
                    "row": 2,
                },
            }
        ],
        lifeops_metadata={"available": True, "people_count": 1, "action_count": 1},
        section_limit=5,
    )

    person = result["sections"]["people"][0]
    action = result["sections"]["commitments"][0]
    assert person["title"] == "Alex"
    assert person["identity_resolution"]["status"] == "matched"
    assert person["linked_source_refs"][0]["id"] == "alex-contact"
    assert action["title"] == "Reply to Alex"
    assert action["source"] == "lifeops_sheet"
    assert result["source_health"]["lifeops_sheet"]["action_count"] == 1


def test_context_surfaces_stale_source_health_as_a_limitation():
    result = build_context(
        memory_entries=[],
        triage={
            "items": [],
            "source_health": {
                "inbox_index": {
                    "status": "ok",
                    "healthy": False,
                    "stale": True,
                    "reasons": ["stale_checkpoint"],
                }
            },
        },
    )

    assert "inbox_index_stale" in result["limitations"]
    assert "inbox_index_unhealthy" in result["limitations"]
    assert "inbox_index:stale_checkpoint" in result["limitations"]


def test_context_surfaces_unavailable_sources_and_bounds_sections():
    result = build_context(
        memory_entries=[_entry(index, "person", f"Person {index}") for index in range(10)],
        triage={
            "items": [],
            "source_health": {
                "inbox": {"status": "unavailable", "reasons": ["inbox_read_failed:Timeout"]},
                "lifeops": {"status": "ok", "reasons": []},
            },
        },
        limit=2,
        section_limit=3,
    )

    assert len(result["sections"]["people"]) == 3
    assert "inbox_read_unavailable" in result["limitations"]
    assert "inbox:inbox_read_failed:Timeout" in result["limitations"]
    assert result["counts"]["people"] == 3


def test_context_includes_unified_people_with_source_health():
    result = build_context(
        memory_entries=[],
        triage={"items": [], "source_health": {}},
        people_profiles=[
            {
                "contact_id": "person:harsh",
                "name": "Harsh",
                "identifiers": ["+15551234567", "harsh@example.com"],
                "sources": ["imessage", "gmail"],
                "total_interactions": 12,
                "relationship_score": 82,
                "relationship_tier": "active",
                "communication_preferences": {"preferred_channel": "imessage"},
                "interaction_history": [],
            }
        ],
        people_metadata={
            "schema": "inbox.unified_contacts.v1",
            "profile_count": 1,
            "cross_channel_profile_count": 1,
            "source_status": {
                "imessage": {"available": True, "detail": "local Messages database"},
                "gmail": {"available": False, "detail": "live Gmail scan disabled"},
            },
        },
        section_limit=5,
    )

    person = result["sections"]["people"][0]
    assert person["title"] == "Harsh"
    assert person["source_ref"] == {
        "kind": "unified_contact_profile",
        "source": "inbox.unified_contacts.v1",
        "id": "person:harsh",
    }
    assert result["source_health"]["unified_contacts"]["profile_count"] == 1
    assert "unified_contacts:gmail:live Gmail scan disabled" in result["limitations"]


def test_context_does_not_claim_contact_projection_is_healthy_after_failure():
    result = build_context(
        memory_entries=[],
        triage={"items": [], "source_health": {}},
        people_profiles=[],
        people_metadata={
            "schema": "inbox.unified_contacts.v1",
            "available": False,
            "source_status": {},
        },
    )

    assert result["source_health"]["unified_contacts"]["status"] == "unavailable"
    assert "unified_contacts_read_unavailable" in result["limitations"]


def test_context_includes_calendar_place_observations_with_provenance():
    result = build_context(
        memory_entries=[],
        triage={"items": [], "source_health": {}},
        calendar_events=[
            {
                "event_id": "evt_street_play",
                "calendar_id": "primary",
                "account": "jwalin@example.com",
                "summary": "Street play practice",
                "start": "2026-08-26T17:40:00-07:00",
                "end": "2026-08-26T19:00:00-07:00",
                "location": "45738 Bridgeport Dr.",
            }
        ],
        calendar_metadata={
            "available": True,
            "event_count": 1,
            "lookahead_days": 7,
            "detail": "Inbox upcoming calendar projection",
        },
    )

    place = result["sections"]["places"][0]
    assert place["title"] == "45738 Bridgeport Dr."
    assert place["event_summary"] == "Street play practice"
    assert place["source_ref"]["id"] == "evt_street_play"
    assert result["source_health"]["calendar"]["event_count"] == 1
    assert result["counts"]["places"] == 1


def test_context_includes_contact_address_place_observations():
    result = build_context(
        memory_entries=[],
        triage={"items": [], "source_health": {}},
        contact_rows=[
            {
                "id": "alex@example.com",
                "name": "Alex",
                "addresses": [{"formatted": "1 Main St", "label": "home"}],
            }
        ],
        contact_metadata={"available": True, "contact_count": 1, "address_count": 1},
    )

    place = result["sections"]["places"][0]
    assert place["title"] == "1 Main St"
    assert place["contact_name"] == "Alex"
    assert place["source_ref"]["kind"] == "contact_address"
    assert result["source_health"]["contacts"]["address_count"] == 1


def test_context_includes_open_life_commitments():
    result = build_context(
        memory_entries=[],
        triage={"items": [], "source_health": {}},
        life_commitments=[
            {
                "commitment_id": "com_123",
                "capture_id": "cap_123",
                "title": "Call Harsh",
                "owner": "YOU",
                "state": "READY_HUMAN",
                "next_condition": "After practice",
                "confidence": 0.9,
            }
        ],
    )

    commitment = result["sections"]["commitments"][0]
    assert commitment["title"] == "Call Harsh"
    assert commitment["source_ref"]["capture_id"] == "cap_123"
