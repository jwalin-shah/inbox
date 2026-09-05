from __future__ import annotations

import asyncio

import pytest


@pytest.mark.anyio
async def test_life_context_provider_gates_are_shared_within_a_runtime(monkeypatch) -> None:
    import lifeops_mcp

    monkeypatch.setattr(lifeops_mcp, "_LIFE_CONTEXT_GATE_STATE", None)
    first = lifeops_mcp._life_context_gates()
    second = lifeops_mcp._life_context_gates()

    assert first[0] is second[0]
    assert first[1] is second[1]


@pytest.mark.anyio
async def test_life_context_returns_bounded_source_errors_when_a_read_hangs(monkeypatch) -> None:
    import lifeops_mcp

    real_sleep = asyncio.sleep

    async def fake_triage_all(*, limit: int, account: str, use_model: bool):
        return {"items": [], "coverage": {}}

    async def hanging_request(*args, **kwargs):
        await real_sleep(1)
        return {}

    monkeypatch.setattr(lifeops_mcp, "triage_all", fake_triage_all)
    monkeypatch.setattr(lifeops_mcp, "_request", hanging_request)
    monkeypatch.setattr(lifeops_mcp, "_LIFE_CONTEXT_READ_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(lifeops_mcp, "_LIFE_CONTEXT_TOTAL_TIMEOUT_SECONDS", 0.03)

    result = await lifeops_mcp.life_context(
        limit=1,
        section_limit=1,
        account="a@example.com",
        use_model=False,
    )

    assert result["source_health"]["calendar"]["status"] == "unavailable"
    assert "life_context_" in result["source_health"]["calendar"]["error"]


@pytest.mark.anyio
async def test_life_context_composes_existing_read_surfaces(monkeypatch) -> None:
    import lifeops_mcp

    async def fake_triage_all(*, limit: int, account: str, use_model: bool):
        assert (limit, account, use_model) == (5, "", False)
        return {
            "items": [
                {
                    "item_id": "gmail:thread:t1",
                    "title": "Reply to Alex",
                    "source": "gmail",
                    "source_ref": {"kind": "thread", "source": "gmail", "id": "t1"},
                }
            ],
            "coverage": {"gmail": {"status": "ok", "read_only": True}},
        }

    async def fake_request(method, path, *, params=None, body=None, extra_headers=None):
        assert method == "GET"
        if path == "/contacts/search":
            return [{
                "id": "person-1",
                "name": "Alex",
                "sources": ["imessage", "gmail"],
                "addresses": [{"formatted": "1 Main St", "label": "home"}],
            }]
        if path == "/memory":
            return [{
                "id": 9,
                "memory_type": "project",
                "subject": "Street play",
                "content": "Practice coordination",
                "source": "manual",
                "confidence": 1.0,
                "status": "active",
                "metadata": {"capture_id": "cap_9"},
            }]
        if path == "/calendar/upcoming":
            return [{"id": "event-1", "summary": "Practice", "location": "Bridgeport Dr.", "start": "2026-08-25T17:40:00-07:00"}]
        if path == "/tasks":
            return [{"id": "task-1", "title": "Follow up", "completed": False}]
        raise AssertionError(path)

    monkeypatch.setattr(lifeops_mcp, "triage_all", fake_triage_all)
    monkeypatch.setattr(lifeops_mcp, "_request", fake_request)

    result = await lifeops_mcp.life_context(limit=5, section_limit=5)

    assert result["schema_version"] == "lifeops.context.v1"
    assert result["read_only"] is True
    assert result["counts"] == {
        "attention": 1,
        "people": 1,
        "places": 2,
        "projects": 1,
        "goals": 0,
        "decisions": 0,
        "notes": 0,
        "documents": 0,
        "commitments": 1,
    }
    assert result["sections"]["people"][0]["source_ref"]["id"] == "person-1"
    assert result["sections"]["places"][0]["source_ref"]["id"] == "event-1"
    assert result["sections"]["places"][1]["source_ref"]["kind"] == "contact_address"
    assert result["sections"]["projects"][0]["source_ref"]["capture_id"] == "cap_9"
    assert result["sections"]["commitments"][0]["source_ref"]["id"] == "task-1"
    assert result["provenance"]["reference_count"] == 7
    assert "no_explicit_project_records_observed" not in result["limitations"]


@pytest.mark.anyio
async def test_life_context_retries_transient_read_transport_failure(monkeypatch) -> None:
    import httpx

    import lifeops_mcp

    async def fake_triage_all(*, limit: int, account: str, use_model: bool):
        return {"items": [], "coverage": {}}

    attempts: dict[str, int] = {}

    async def flaky_request(method, path, *, params=None, body=None, extra_headers=None):
        attempts[path] = attempts.get(path, 0) + 1
        if path == "/contacts/search" and attempts[path] == 1:
            raise httpx.ConnectError(
                "transient disconnect",
                request=httpx.Request("GET", "http://test/contacts/search"),
            )
        return []

    monkeypatch.setattr(lifeops_mcp, "triage_all", fake_triage_all)
    monkeypatch.setattr(lifeops_mcp, "_request", flaky_request)

    result = await lifeops_mcp.life_context(limit=3, section_limit=3)

    assert result["read_only"] is True
    assert attempts["/contacts/search"] == 2
    assert "contacts_read_unavailable" not in result["limitations"]


@pytest.mark.anyio
async def test_life_context_keeps_canonical_sheets_separate_from_provider_account(monkeypatch) -> None:
    import lifeops_mcp

    async def fake_triage_all(*, limit: int, account: str, use_model: bool):
        assert account == "jwalinshah13@gmail.com"
        return {"items": [], "coverage": {}}

    seen: dict[str, dict] = {}

    async def fake_request(method, path, *, params=None, body=None, extra_headers=None):
        seen[path] = dict(params or {})
        return []

    monkeypatch.setattr(lifeops_mcp, "triage_all", fake_triage_all)
    monkeypatch.setattr(lifeops_mcp, "_request", fake_request)
    monkeypatch.setattr(lifeops_mcp, "LIFEOPS_CANONICAL_GOOGLE_ACCOUNT", "jshah1331@gmail.com")

    result = await lifeops_mcp.life_context(
        limit=3,
        section_limit=3,
        account="jwalinshah13@gmail.com",
    )

    assert result["source_health"]["master_ops"]["source_account"] == "jshah1331@gmail.com"
    assert result["source_health"]["lifeops_sheet"]["scope"] == "canonical_user_scoped"
    for path in ("/project-records", "/master-ops/queues", "/lifeops-sheet/projection"):
        assert seen[path]["account"] == "jshah1331@gmail.com"


@pytest.mark.anyio
async def test_life_context_aggregates_account_scoped_docs_and_tasks_when_unscoped(monkeypatch) -> None:
    import lifeops_mcp

    async def fake_triage_all(*, limit: int, account: str, use_model: bool):
        assert account == ""
        return {"items": [], "coverage": {}}

    requested_accounts: dict[str, list[str]] = {"/docs": [], "/tasks": []}

    async def fake_request(method, path, *, params=None, body=None, extra_headers=None):
        params = params or {}
        if path == "/accounts":
            return {
                "gmail": ["one@example.com", "two@example.com"],
                "calendar": ["one@example.com", "two@example.com"],
                "drive": ["one@example.com", "two@example.com"],
                "docs": ["one@example.com", "two@example.com"],
                "tasks": ["one@example.com", "two@example.com"],
            }
        if path == "/docs":
            requested_accounts[path].append(params["account"])
            return [{"id": f"doc-{params['account']}", "title": "Doc", "account": params["account"]}]
        if path == "/tasks":
            requested_accounts[path].append(params["account"])
            return [{"id": f"task-{params['account']}", "title": "Task", "account": params["account"]}]
        return []

    monkeypatch.setattr(lifeops_mcp, "triage_all", fake_triage_all)
    monkeypatch.setattr(lifeops_mcp, "_request", fake_request)

    result = await lifeops_mcp.life_context(limit=5, section_limit=5)

    assert requested_accounts["/docs"] == ["one@example.com", "two@example.com"]
    assert requested_accounts["/tasks"] == ["one@example.com", "two@example.com"]
    assert result["scope"]["provider_account_scope"] == "all_loaded_provider_accounts"
    assert result["source_health"]["google_docs"]["accounts"] == [
        "one@example.com",
        "two@example.com",
    ]
    assert result["source_health"]["tasks"]["accounts"] == [
        "one@example.com",
        "two@example.com",
    ]
    assert result["counts"]["documents"] == 2
    assert result["counts"]["commitments"] == 2


@pytest.mark.anyio
async def test_life_context_includes_document_metadata_and_embedding_health(monkeypatch) -> None:
    import lifeops_mcp

    async def fake_triage_all(*, limit: int, account: str, use_model: bool):
        return {"items": [], "coverage": {}}

    async def fake_request(method, path, *, params=None, body=None, extra_headers=None):
        if path == "/index/embedding-status":
            return {
                "read_only": True,
                "model_id": "BAAI/bge-small-en-v1.5",
                "items": 100,
                "embedded": 99,
                "pending": 1,
            }
        if path == "/drive/files":
            return [{
                "id": "drive-1",
                "name": "LifeOps Tracker",
                "mime_type": "application/vnd.google-apps.spreadsheet",
                "modified": "2026-08-25T20:00:00Z",
                "web_link": "https://drive.google.com/file/d/drive-1/view",
                "account": "jshah1331@gmail.com",
            }]
        if path == "/docs":
            return [{
                "id": "doc-1",
                "title": "README",
                "url": "https://docs.google.com/document/d/doc-1/edit",
                "account": "jshah1331@gmail.com",
            }]
        return []

    monkeypatch.setattr(lifeops_mcp, "triage_all", fake_triage_all)
    monkeypatch.setattr(lifeops_mcp, "_request", fake_request)
    result = await lifeops_mcp.life_context(limit=5, section_limit=5)

    assert [item["title"] for item in result["sections"]["documents"]] == [
        "LifeOps Tracker",
        "README",
    ]
    assert result["sections"]["documents"][0]["source_ref"]["id"] == "drive-1"
    assert result["source_health"]["embedding_index"]["pending"] == 1
    assert "embeddings_pending" in result["limitations"]
    assert "document_content_not_part_of_context_v1" in result["limitations"]


@pytest.mark.anyio
async def test_life_context_includes_captured_property_evidence(monkeypatch) -> None:
    import lifeops_mcp

    async def fake_triage_all(*, limit: int, account: str, use_model: bool):
        return {"items": [], "coverage": {}}

    async def fake_request(method, path, *, params=None, body=None, extra_headers=None):
        if path == "/events":
            return {
                "count": 1,
                "events": [
                    {
                        "event_id": "evt-side-yard",
                        "source": "property",
                        "source_object_id": "photo-side-yard",
                        "occurred_at": "2026-08-25T20:00:00Z",
                        "observed_at": "2026-08-25T20:01:00Z",
                        "confidence": 0.7,
                        "metadata": {
                            "property_id": "home-fremont",
                            "zone_id": "side-yard-01",
                            "evidence_kind": "photo",
                            "title": "Long side-yard dirt strip",
                        },
                        "payload": {"image_path": "/tmp/side-yard.jpg"},
                    }
                ],
            }
        return []

    monkeypatch.setattr(lifeops_mcp, "triage_all", fake_triage_all)
    monkeypatch.setattr(lifeops_mcp, "_request", fake_request)
    result = await lifeops_mcp.life_context(limit=5, section_limit=5)

    assert result["property_evidence"][0]["zone_id"] == "side-yard-01"
    assert result["property_evidence"][0]["source_ref"]["id"] == "evt-side-yard"
    assert result["source_health"]["property_evidence"] == {
        "status": "ok",
        "read_only": True,
        "observation_count": 1,
        "error": None,
    }
    assert "property_evidence_not_captured" not in result["limitations"]


@pytest.mark.anyio
async def test_life_context_preserves_identity_candidates_and_merges_places(monkeypatch) -> None:
    import lifeops_mcp

    async def fake_triage_all(*, limit: int, account: str, use_model: bool):
        return {"items": [], "coverage": {}}

    async def fake_request(method, path, *, params=None, body=None, extra_headers=None):
        if path == "/contacts/search":
            return [
                {"id": "fabia-contact", "name": "Fabia", "addresses": [{"formatted": "45738 Bridgeport Dr"}]},
                {"id": "alex-contact", "name": "Alex", "addresses": [{"formatted": "45738 Bridgeport Dr"}]},
            ]
        if path == "/lifeops-sheet/projection":
            return {
                "tabs": {
                    "people": {
                        "records": [
                            {
                                "person_id": "P-FABIA",
                                "name": "Fabia Becaus",
                                "identity_confidence": "medium",
                                "source_ref": {"kind": "google_sheet_row", "source": "google_sheets", "id": "people:2"},
                            }
                        ]
                    },
                    "actions": {"records": []},
                    "projects": {
                        "records": [
                            {
                                "project_id": "PR-ALEX",
                                "project": "Alex follow-up",
                                "related_people": "Alex",
                                "status": "ACTIVE",
                                "source_ref": {
                                    "kind": "google_sheet_row",
                                    "source": "google_sheets",
                                    "id": "lifeops:Projects:row:2",
                                },
                            }
                        ]
                    },
                }
            }
        if path == "/calendar/upcoming":
            return [{"event_id": "event-1", "summary": "Practice", "location": "45738 Bridgeport Dr"}]
        return []

    monkeypatch.setattr(lifeops_mcp, "triage_all", fake_triage_all)
    monkeypatch.setattr(lifeops_mcp, "_request", fake_request)
    result = await lifeops_mcp.life_context(limit=5, section_limit=5)

    person = next(item for item in result["sections"]["people"] if item["source"] == "lifeops_sheet")
    assert person["identity_resolution"]["status"] == "unmatched"
    assert person["candidate_source_refs"] == []
    places = result["sections"]["places"]
    assert len(places) == 1
    assert places[0]["observation_count"] == 3
    assert len(places[0]["evidence_refs"]) == 3
    assert places[0]["observed_sources"] == ["calendar", "contacts"]
    assert places[0]["source_counts"] == {"calendar": 1, "contacts": 2}


@pytest.mark.anyio
async def test_life_context_merges_safe_address_format_variants_without_merging_units(monkeypatch) -> None:
    import lifeops_mcp

    async def fake_triage_all(*, limit: int, account: str, use_model: bool):
        return {"items": [], "coverage": {}}

    async def fake_request(method, path, *, params=None, body=None, extra_headers=None):
        if path == "/contacts/search":
            return [
                {
                    "id": "contact-1",
                    "name": "Harsh",
                    "addresses": [{"formatted": "45738 Bridgeport Drive, Fremont, CA"}],
                },
                {
                    "id": "contact-2",
                    "name": "Arav",
                    "addresses": [{"formatted": "45738 Bridgeport Dr., Fremont, CA"}],
                },
                {
                    "id": "contact-3",
                    "name": "Different unit",
                    "addresses": [{"formatted": "45738 Bridgeport Dr. Apt 2"}],
                },
            ]
        if path == "/calendar/upcoming":
            return []
        return []

    monkeypatch.setattr(lifeops_mcp, "triage_all", fake_triage_all)
    monkeypatch.setattr(lifeops_mcp, "_request", fake_request)

    result = await lifeops_mcp.life_context(limit=5, section_limit=10)

    places = result["sections"]["places"]
    assert len(places) == 2
    assert places[0]["place_key"] == "45738 bridgeport dr fremont ca"
    assert places[0]["observation_count"] == 2
    assert places[0]["source_counts"] == {"contacts": 2}
    assert places[0]["normalization_method"] == "case_punctuation_whitespace_and_street_suffix"
    assert places[1]["place_key"] == "45738 bridgeport dr apt 2"


@pytest.mark.anyio
async def test_life_context_preserves_distinct_addresses_when_calendar_repeats_fill_source_limit(monkeypatch) -> None:
    import lifeops_mcp

    async def fake_triage_all(*, limit: int, account: str, use_model: bool):
        return {"items": [], "coverage": {}}

    async def fake_request(method, path, *, params=None, body=None, extra_headers=None):
        if path == "/contacts/search":
            return [{"id": "contact-1", "name": "Harsh", "addresses": [{"formatted": "1 Main St"}]}]
        if path == "/calendar/upcoming":
            return [
                {"event_id": "event-1", "summary": "Practice", "location": "45738 Bridgeport Dr"},
                {"event_id": "event-2", "summary": "Practice", "location": "45738 Bridgeport Dr."},
            ]
        return []

    monkeypatch.setattr(lifeops_mcp, "triage_all", fake_triage_all)
    monkeypatch.setattr(lifeops_mcp, "_request", fake_request)

    result = await lifeops_mcp.life_context(limit=5, section_limit=2)

    places = result["sections"]["places"]
    assert len(places) == 2
    assert places[0]["observation_count"] == 2
    assert places[1]["place"] == "1 Main St"


def test_place_keys_preserve_hyphenated_address_tokens() -> None:
    import lifeops_mcp

    merged = lifeops_mcp._context_merge_places(
        [
            {"title": "12-A Main St", "place": "12-A Main St", "source_ref": {"id": "a"}},
            {"title": "12 A Main St", "place": "12 A Main St", "source_ref": {"id": "b"}},
            {"title": "12/1 Main St", "place": "12/1 Main St", "source_ref": {"id": "c"}},
            {"title": "12 1 Main St", "place": "12 1 Main St", "source_ref": {"id": "d"}},
        ],
        10,
    )

    assert len(merged) == 4


@pytest.mark.anyio
async def test_life_context_includes_auxiliary_lifeops_tabs_as_notes(monkeypatch) -> None:
    import lifeops_mcp

    async def fake_triage_all(*, limit: int, account: str, use_model: bool):
        return {"items": [], "coverage": {}}

    async def fake_request(method, path, *, params=None, body=None, extra_headers=None):
        if path == "/lifeops-sheet/projection":
            return {
                "tabs": {
                    "people": {"records": []},
                    "actions": {"records": []},
                    "projects": {"records": []},
                    "values": {
                        "records": [
                            {
                                "value_id": "V-1",
                                "value": "Connection",
                                "confidence": "high",
                                "source_ref": {"kind": "google_sheet_row", "source": "google_sheets", "id": "values:2"},
                            }
                        ]
                    },
                    "authority_map": {
                        "records": [
                            {
                                "fact_family": "Email",
                                "canonical_authority": "Gmail",
                                "source_ref": {"kind": "google_sheet_row", "source": "google_sheets", "id": "authority:2"},
                            }
                        ]
                    },
                }
            }
        return []

    monkeypatch.setattr(lifeops_mcp, "triage_all", fake_triage_all)
    monkeypatch.setattr(lifeops_mcp, "_request", fake_request)
    result = await lifeops_mcp.life_context(limit=5, section_limit=5)

    assert [item["title"] for item in result["sections"]["notes"]] == ["Connection", "Email"]
    assert result["sections"]["notes"][0]["tab"] == "values"
    assert result["sections"]["notes"][1]["source_ref"]["id"] == "authority:2"


@pytest.mark.anyio
async def test_life_context_deduplicates_explicit_project_records(monkeypatch) -> None:
    import lifeops_mcp

    async def fake_triage_all(*, limit: int, account: str, use_model: bool):
        return {"items": [], "coverage": {}}

    async def fake_request(method, path, *, params=None, body=None, extra_headers=None):
        if path == "/memory":
            return [
                {
                    "id": 1,
                    "subject": "Street play",
                    "content": "First capture",
                    "source": "manual",
                    "status": "active",
                    "updated_at": "2026-08-25T12:00:00+00:00",
                    "metadata": {
                        "capture_id": "cap_1",
                        "source_refs": [{"source": "sheets", "id": "sheet_1"}],
                    },
                },
                {
                    "id": 2,
                    "subject": "street-play",
                    "content": "Second capture",
                    "source": "manual",
                    "status": "active",
                    "updated_at": "2026-08-25T13:00:00+00:00",
                    "metadata": {"capture_id": "cap_2"},
                },
            ]
        return []

    monkeypatch.setattr(lifeops_mcp, "triage_all", fake_triage_all)
    monkeypatch.setattr(lifeops_mcp, "_request", fake_request)
    result = await lifeops_mcp.life_context(limit=5, section_limit=5)

    project = result["sections"]["projects"][0]
    assert len(result["sections"]["projects"]) == 1
    assert project["project_key"] == "streetplay"
    assert project["evidence_count"] == 2
    assert project["linked_source_refs"] == [{"source": "sheets", "id": "sheet_1"}]
    assert result["provenance"]["reference_count"] == 4


def test_explicit_project_resolution_splits_conjunctions() -> None:
    import lifeops_mcp

    refs, resolutions = lifeops_mcp._resolve_explicit_projects(
        "BTW v2 and LifeOps",
        [
            {
                "title": "BTW v2",
                "project_id": "btw-v2",
                "source_ref": {"source": "projects", "id": "p1"},
            },
            {
                "title": "LifeOps",
                "project_id": "lifeops",
                "source_ref": {"source": "projects", "id": "p2"},
            },
        ],
    )

    assert [item["project_id"] for item in refs] == ["btw-v2", "lifeops"]
    assert [item["status"] for item in resolutions] == ["matched", "matched"]


@pytest.mark.anyio
async def test_life_context_includes_canonical_tracker_projects(monkeypatch) -> None:
    import lifeops_mcp

    async def fake_triage_all(*, limit: int, account: str, use_model: bool):
        return {"items": [], "coverage": {}}

    async def fake_request(method, path, *, params=None, body=None, extra_headers=None):
        if path == "/project-records":
            return {
                "schema_version": "inbox.project_records.v1",
                "records": [
                    {
                        "project": "Life Ops",
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
            }
        return []

    monkeypatch.setattr(lifeops_mcp, "triage_all", fake_triage_all)
    monkeypatch.setattr(lifeops_mcp, "_request", fake_request)
    result = await lifeops_mcp.life_context(limit=5, section_limit=5)

    project = result["sections"]["projects"][0]
    assert project["title"] == "Life Ops"
    assert project["source"] == "google_sheets"
    assert project["linked_source_refs"][0]["kind"] == "google_sheet_row"
    assert result["source_health"]["projects"]["tracker_status"] == "ok"


@pytest.mark.anyio
async def test_life_context_includes_open_curated_email_action(monkeypatch) -> None:
    import lifeops_mcp

    async def fake_triage_all(*, limit: int, account: str, use_model: bool):
        return {"items": [], "coverage": {}}

    async def fake_request(method, path, *, params=None, body=None, extra_headers=None):
        if path == "/master-ops/queues":
            return {
                "schema_version": "inbox.master_ops_queues.v1",
                "queues": {
                    "email_actions": {
                        "records": [
                            {
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
                        ]
                    }
                },
            }
        return []

    monkeypatch.setattr(lifeops_mcp, "triage_all", fake_triage_all)
    monkeypatch.setattr(lifeops_mcp, "_request", fake_request)
    result = await lifeops_mcp.life_context(limit=5, section_limit=5)

    item = result["sections"]["attention"][0]
    assert item["title"] == "Review billing"
    assert item["attention_class"] == "curated_email_action"
    assert result["source_health"]["master_ops"]["email_action_count"] == 1


@pytest.mark.anyio
async def test_life_context_projects_persistent_people_and_actions(monkeypatch) -> None:
    import lifeops_mcp

    async def fake_triage_all(*, limit: int, account: str, use_model: bool):
        return {"items": [], "coverage": {}}

    async def fake_request(method, path, *, params=None, body=None, extra_headers=None):
        if path == "/contacts/search":
            return [{"id": "alex-contact", "name": "Alex"}]
        if path == "/lifeops-sheet/projection":
            return {
                "tabs": {
                    "people": {
                        "records": [
                            {
                                "person_id": "P-ALEX",
                                "name": "Alex",
                                "identity_confidence": "high",
                                "source_ref": {
                                    "kind": "google_sheet_row",
                                    "source": "google_sheets",
                                    "id": "lifeops:People:row:2",
                                },
                            }
                        ]
                    },
                    "actions": {
                        "records": [
                            {
                                "action_id": "A-1",
                                "action": "Reply to Alex",
                                "related_person": "Alex",
                                "related_project": "Alex follow-up",
                                "state": "READY_HUMAN",
                                "source_ref": {
                                    "kind": "google_sheet_row",
                                    "source": "google_sheets",
                                    "id": "lifeops:Actions:row:2",
                                },
                            }
                        ]
                    },
                    "projects": {
                        "records": [
                            {
                                "project_id": "PR-ALEX",
                                "project": "Alex follow-up",
                                "related_people": "Alex",
                                "status": "ACTIVE",
                                "source_ref": {
                                    "kind": "google_sheet_row",
                                    "source": "google_sheets",
                                    "id": "lifeops:Projects:row:2",
                                },
                            }
                        ]
                    },
                }
            }
        return []

    monkeypatch.setattr(lifeops_mcp, "triage_all", fake_triage_all)
    monkeypatch.setattr(lifeops_mcp, "_request", fake_request)
    result = await lifeops_mcp.life_context(limit=5, section_limit=5)

    person = next(item for item in result["sections"]["people"] if item["source"] == "lifeops_sheet")
    action = next(item for item in result["sections"]["commitments"] if item["source"] == "lifeops_sheet")
    assert person["identity_resolution"]["status"] == "matched"
    assert action["title"] == "Reply to Alex"
    assert action["related_person_refs"][0]["person_id"] == "P-ALEX"
    assert action["related_person_resolution"][0]["status"] == "matched"
    assert action["related_project_resolution"][0]["status"] == "matched"
    assert action["related_project_refs"][0]["project_id"] == "lifeops_sheet_project:PR-ALEX"
    project = next(item for item in result["sections"]["projects"] if item["title"] == "Alex follow-up")
    assert any(ref.get("person_id") == "P-ALEX" for ref in project["linked_source_refs"])
    assert result["source_health"]["lifeops_sheet"]["action_count"] == 1
    assert result["source_health"]["triage"]["status"] == "ok"
    assert result["source_health"]["triage"]["read_only"] is True


@pytest.mark.anyio
async def test_life_context_surfaces_nested_stale_index_health(monkeypatch) -> None:
    import lifeops_mcp

    async def fake_triage_all(*, limit: int, account: str, use_model: bool):
        return {
            "items": [],
            "coverage": {
                "inbox_index": {
                    "healthy": False,
                    "stale": True,
                    "reasons": ["stale_checkpoint"],
                }
            },
        }

    async def fake_request(method, path, *, params=None, body=None, extra_headers=None):
        return []

    monkeypatch.setattr(lifeops_mcp, "triage_all", fake_triage_all)
    monkeypatch.setattr(lifeops_mcp, "_request", fake_request)
    result = await lifeops_mcp.life_context(limit=3, section_limit=3)

    assert "triage.inbox_index_stale" in result["limitations"]
    assert "triage.inbox_index_unhealthy" in result["limitations"]
    assert "triage.inbox_index:stale_checkpoint" in result["limitations"]


@pytest.mark.anyio
async def test_life_context_reports_unavailable_context_sources(monkeypatch) -> None:
    import lifeops_mcp

    async def fake_triage_all(*, limit: int, account: str, use_model: bool):
        return {"items": [], "coverage": {}}

    async def failed_request(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(lifeops_mcp, "triage_all", fake_triage_all)
    monkeypatch.setattr(lifeops_mcp, "_request", failed_request)

    result = await lifeops_mcp.life_context(limit=3, section_limit=3)

    assert result["read_only"] is True
    assert result["counts"]["people"] == 0
    assert result["source_health"]["calendar"]["status"] == "unavailable"
    assert result["source_health"]["projects"]["status"] == "unavailable"
    assert result["source_health"]["triage"]["status"] == "ok"
    assert "calendar_read_unavailable" in result["limitations"]
