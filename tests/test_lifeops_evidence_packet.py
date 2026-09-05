from __future__ import annotations

import pytest


@pytest.mark.anyio
async def test_evidence_packet_is_bounded_and_excludes_unrequested_sections(monkeypatch) -> None:
    import lifeops_mcp

    async def fake_life_context(**kwargs):
        assert kwargs == {
            "limit": 2,
            "section_limit": 2,
            "calendar_days": 3,
            "account": "jwalinshah13@gmail.com",
            "use_model": False,
        }
        return {
            "sections": {
                "attention": [{"id": 1}, {"id": 2}, {"id": 3}],
                "notes": [{"secret": "not requested"}],
            },
            "property_evidence": [{"id": "property-1"}, {"id": "property-2"}],
            "source_health": {"triage": {"status": "ok"}},
            "limitations": ["partial_source"],
            "provenance": {"references": [{"source": "gmail", "id": "msg-1"}]},
        }

    monkeypatch.setattr(lifeops_mcp, "life_context", fake_life_context)
    result = await lifeops_mcp.evidence_packet(
        consumer="deepseek",
        purpose="classify this review batch",
        sections=["attention", "property_evidence"],
        limit=2,
        calendar_days=3,
        account="jwalinshah13@gmail.com",
    )

    assert result["schema_version"] == "lifeops.evidence_packet.v1"
    assert result["read_only"] is True
    assert result["consumer"] == "deepseek"
    assert result["scope"] == {
        "account": "jwalinshah13@gmail.com",
        "sections": ["attention", "property_evidence"],
        "max_items_per_section": 2,
        "calendar_days": 3,
        "account_scope_mode": "provider_account_where_supported; canonical_local_personal_sources_are_user_scoped",
        "source_access": "LifeOps read models only",
        "provider_writes": False,
        "worker_control": False,
        "secret_access": False,
        "raw_event_mutation": False,
    }
    assert result["sections"] == {
        "attention": [{"id": 1}, {"id": 2}],
        "property_evidence": [{"id": "property-1"}, {"id": "property-2"}],
    }
    assert "notes" not in result["sections"]
    assert "packet_is_ephemeral_and_read_only" in result["limitations"]
    assert (
        "account_scope_applies_to_provider_reads; canonical_local_personal_sources_are_user_scoped"
        in result["limitations"]
    )


@pytest.mark.anyio
async def test_evidence_packet_rejects_unknown_sections_and_empty_purpose() -> None:
    import lifeops_mcp

    with pytest.raises(ValueError, match="purpose is required"):
        await lifeops_mcp.evidence_packet(purpose=" ")
    with pytest.raises(ValueError, match="Unsupported evidence packet section"):
        await lifeops_mcp.evidence_packet(sections=["raw_messages"])


@pytest.mark.anyio
async def test_worker_evidence_packet_cannot_expand_into_notes_or_documents(monkeypatch) -> None:
    import lifeops_mcp

    monkeypatch.setenv("LIFEOPS_MCP_PROFILE", "worker")
    with pytest.raises(ValueError, match="cannot include: documents"):
        await lifeops_mcp.evidence_packet(sections=["documents"])


@pytest.mark.anyio
async def test_worker_evidence_packet_requires_exact_account_scope(monkeypatch) -> None:
    import lifeops_mcp

    monkeypatch.setenv("LIFEOPS_MCP_PROFILE", "worker")
    with pytest.raises(ValueError, match="account scope is not configured"):
        await lifeops_mcp.evidence_packet(account="jwalinshah13@gmail.com")

    monkeypatch.setenv("LIFEOPS_WORKER_ACCOUNT_ALLOWLIST", "jwalinshah13@gmail.com")

    async def fake_life_context(**kwargs):
        assert kwargs["account"] == "jwalinshah13@gmail.com"
        return {
            "sections": {"attention": []},
            "source_health": {},
            "limitations": [],
            "provenance": {},
        }

    monkeypatch.setattr(lifeops_mcp, "life_context", fake_life_context)
    result = await lifeops_mcp.evidence_packet(account="jwalinshah13@gmail.com")
    assert result["scope"]["account"] == "jwalinshah13@gmail.com"
