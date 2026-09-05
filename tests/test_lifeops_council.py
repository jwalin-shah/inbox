from __future__ import annotations

import json

import pytest

from lifeops.council import CouncilRouter, CouncilStore, CouncilSurfaceRegistry

pytestmark = pytest.mark.safe


def test_surface_registry_preserves_unknown_provider_availability(tmp_path):
    registry = CouncilSurfaceRegistry(tmp_path / "surfaces.json")
    snapshot = registry.sync_static()

    perplexity = next(item for item in snapshot["surfaces"] if item["surface_id"] == "perplexity/best")
    assert perplexity["subscription_sunk_cost"] is True
    assert perplexity["marginal_cost"] == 0.0
    assert perplexity["availability"] == "unknown"


def test_router_prefers_paid_surface_when_available_but_does_not_invent_it(tmp_path):
    registry = CouncilSurfaceRegistry(tmp_path / "surfaces.json")
    registry.sync_static()
    ranked = CouncilRouter(registry).rank("research.search", mode="normal")

    assert ranked[0]["surface_id"] == "perplexity/best"
    assert ranked[0]["eligible_for_automatic"] is False
    assert CouncilRouter(registry).rank("research.search", require_available=True) == []

    deep = CouncilRouter(registry).rank("research.search", mode="deep")
    assert deep[0]["surface_id"] == "perplexity/research"


def test_chatgpt_sol_is_manual_only_by_policy(tmp_path):
    registry = CouncilSurfaceRegistry(tmp_path / "surfaces.json")
    registry.sync_static()
    snapshot = registry.load()
    sol = next(item for item in snapshot["surfaces"] if item["surface_id"] == "chatgpt/sol")
    sol["availability"] = "available"
    registry.path.write_text(json.dumps(snapshot), encoding="utf-8")

    ranked = CouncilRouter(registry).rank("reasoning.synthesis")
    sol_rank = next(item for item in ranked if item["surface_id"] == "chatgpt/sol")
    assert sol_rank["automatic_enabled"] is False
    assert sol_rank["eligible_for_automatic"] is False
    assert sol_rank["selection_reason"] == "manual-only by policy; interactive handoff only"


def test_perplexity_mac_app_surface_is_manual_until_connector_proof(tmp_path):
    registry = CouncilSurfaceRegistry(tmp_path / "surfaces.json")
    snapshot = registry.sync_static()
    app = next(
        item for item in snapshot["surfaces"] if item["surface_id"] == "perplexity/mac-local-mcp"
    )
    assert app["automation_level"] == "local_mcp"
    assert app["automatic_enabled"] is False
    assert app["availability"] == "unknown"


def test_quota_sync_marks_only_proven_codex_surface_available(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "/bin")
    registry = CouncilSurfaceRegistry(tmp_path / "surfaces.json")
    registry.sync_static()
    quota = {
        "providers": [
            {
                "provider": "codex",
                "plan": "plus",
                "windows": [{"percentRemaining": 95, "resetsAt": "2026-08-29T09:32:41Z"}],
                "state": {"status": "fresh"},
            },
            {"provider": "perplexity", "state": {"status": "fresh"}},
        ]
    }
    snapshot = registry.sync_quota(
        quota_command="fake-quota",
        runner=lambda argv: json.dumps(quota),
    )

    codex = next(item for item in snapshot["surfaces"] if item["surface_id"] == "chatgpt/codex")
    perplexity = next(item for item in snapshot["surfaces"] if item["surface_id"] == "perplexity/best")
    assert codex["availability"] == "unknown"
    assert codex["quota_status"] == "ready"
    assert codex["quota_remaining"] == 95
    assert perplexity["availability"] == "unknown"


def test_council_claim_is_priority_ordered_and_idempotent(tmp_path):
    store = CouncilStore(tmp_path / "council.jsonl")
    low = store.create("low", priority=10)
    high = store.create("high", priority=90)

    claimed = store.claim_next("worker-1", surface_id="perplexity/best")
    assert claimed is not None
    assert claimed.job_id == high.job_id
    assert claimed.state == "CLAIMED"

    claimed_again = store.claim_next("worker-2", surface_id="chatgpt/sol")
    assert claimed_again is not None
    assert claimed_again.job_id == low.job_id

    assert store.claim_next("worker-3", surface_id="tokenrouter/local") is None


def test_result_requires_claim_identity_and_is_readable_back(tmp_path):
    store = CouncilStore(tmp_path / "council.jsonl")
    job = store.create("question")
    store.claim_next("worker-1", surface_id="perplexity/best")

    with pytest.raises(PermissionError):
        store.submit_result(
            job.job_id,
            worker_id="worker-2",
            surface_id="perplexity/best",
            summary="nope",
        )

    result = store.submit_result(
        job.job_id,
        worker_id="worker-1",
        surface_id="perplexity/best",
        summary="supported",
        evidence=[{"url": "https://example.com", "title": "Example"}],
        claims=[{"claim": "supported", "confidence": 0.8}],
    )
    assert result["result_id"].startswith("result_")
    stored = store.get(job.job_id)
    assert stored is not None
    assert stored.state == "RESULTS"
    assert stored.result_count == 1


def test_result_rejects_secret_looking_fields(tmp_path):
    store = CouncilStore(tmp_path / "council.jsonl")
    job = store.create("question")
    store.claim_next("worker-1", surface_id="perplexity/best")

    with pytest.raises(ValueError, match="secret-looking"):
        store.submit_result(
            job.job_id,
            worker_id="worker-1",
            surface_id="perplexity/best",
            summary="supported",
            evidence=[{"api_token": "redacted"}],
        )


def test_council_cli_round_trip(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LIFEOPS_COUNCIL_PATH", str(tmp_path / "council.jsonl"))
    monkeypatch.setenv("LIFEOPS_COUNCIL_SURFACES_PATH", str(tmp_path / "surfaces.json"))

    from lifeops_cli import main

    assert main(["council", "create", "--question", "Should we pursue this?"]) == 0
    job = json.loads(capsys.readouterr().out)
    assert job["state"] == "QUEUED"
    assert main(["council", "claim", "--worker", "firstmate", "--surface", "perplexity/best"]) == 0
    claimed = json.loads(capsys.readouterr().out)
    assert claimed["job_id"] == job["job_id"]
    assert claimed["claimed_surface"] == "perplexity/best"
