import asyncio

import pytest

from lifeops.deepseek import classify_items
from lifeops.triage import apply_model_labels, build_triage, build_unified_triage


@pytest.mark.anyio
async def test_triage_all_returns_bounded_read_errors_when_a_source_hangs(monkeypatch) -> None:
    import lifeops_mcp
    real_sleep = asyncio.sleep

    class FakeReceiptStore:
        def __init__(self):
            self.receipt = None

        def record(self, receipt):
            self.receipt = receipt
            return {"status": "stored", "run_id": receipt["run_id"]}

    async def hanging_request(*args, **kwargs):
        await real_sleep(1)
        return {}

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(lifeops_mcp, "_request", hanging_request)
    monkeypatch.setattr(lifeops_mcp, "_TRIAGE_READ_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(lifeops_mcp, "_TRIAGE_TOTAL_TIMEOUT_SECONDS", 0.03)
    monkeypatch.setattr(lifeops_mcp.asyncio, "sleep", no_sleep)
    receipt_store = FakeReceiptStore()
    monkeypatch.setattr(lifeops_mcp, "_read_receipt_store", lambda: receipt_store)

    result = await lifeops_mcp.triage_all(limit=1, account="a@example.com", use_model=False)

    assert result["read_errors"]
    assert any(value == "triage_deadline_exceeded" for value in result["read_errors"].values())
    receipt = result["read_receipt"]
    assert receipt["schema_version"] == "lifeops.triage_receipt.v1"
    assert receipt["run_id"].startswith("triage:")
    assert receipt["transport_complete"] is False
    assert any(row["status"] == "deadline_exceeded" for row in receipt["sources"])
    assert receipt["persistence"] == {"status": "stored", "run_id": receipt["run_id"]}
    assert receipt_store.receipt["run_id"] == receipt["run_id"]


def test_build_triage_preserves_source_account_attribution() -> None:
    result = build_triage(
        {
            "read_model": "inbox_now",
            "index_health": {"status": "ok"},
            "now_items": [
                {
                    "title": "Street play practice",
                    "source": "calendar",
                    "start": "2026-08-25T17:40:00-07:00",
                    "ref": {
                        "kind": "event",
                        "source": "calendar",
                        "id": "evt_123",
                        "account": "jwalinshah13@gmail.com",
                    },
                }
            ],
            "waiting_threads": [],
            "reasons": [],
        },
        limit=5,
    )

    item = result["items"][0]
    assert item["source"] == "calendar"
    assert item["source_ref"]["id"] == "evt_123"
    assert item["attribution"] == {
        "authority": "calendar",
        "source": "calendar",
        "account": "jwalinshah13@gmail.com",
        "reference": item["source_ref"],
        "source_timestamp": "2026-08-25T17:40:00-07:00",
        "retrieved_at": result["checked_at"],
        "derived": True,
        "read_only": True,
        "method": "inbox_now_rule_projection",
    }
    assert result["coverage"]["inbox_now"]["read_model"] == "inbox_now"


def test_build_triage_deduplicates_same_source_reference() -> None:
    ref = {"kind": "thread", "source": "gmail", "thread_id": "thr_1", "account": "a@example.com"}
    result = build_triage(
        {
            "now_items": [{"title": "Reply", "ref": ref}],
            "waiting_threads": [{"title": "Reply", "ref": ref}],
            "reasons": [],
        },
        limit=5,
    )

    assert len(result["items"]) == 1
    assert result["counts"] == {"gmail": 1}


def test_build_triage_reports_unavailable_coverage() -> None:
    result = build_triage(None, limit=5)

    assert result["read_only"] is True
    assert result["coverage"]["inbox_now"]["status"] == "unavailable"
    assert result["coverage"]["inbox_now"]["reasons"] == ["inbox_read_failed"]


def test_build_unified_triage_merges_sources_and_keeps_sheets_as_context() -> None:
    result = build_unified_triage(
        {
            "index_health": {"healthy": True, "stale": False},
            "now_items": [
                {
                    "title": "Reply to Alex",
                    "source": "gmail",
                    "needs_reply": True,
                    "ref": {"kind": "thread", "source": "gmail", "thread_id": "t1", "account": "a@example.com"},
                }
            ],
            "waiting_threads": [],
            "reasons": [],
        },
        {
            "ok": True,
            "read_only": True,
            "mutation_applied": False,
            "sources": {
                "calendar": {"ok": True, "accounts": ["a@example.com"], "count": 1, "items": []},
                "gmail": {"ok": True, "accounts": ["a@example.com"], "count": 1, "items": []},
                "tasks": {"ok": True, "accounts": ["a@example.com"], "count": 1, "items": []},
            },
        },
        imessage_conversations=[{"id": "c1", "name": "Harsh", "last_ts": "2026-08-25T12:00:00Z"}],
        sheets=[{"id": "s1", "title": "LifeOps", "account": "a@example.com"}],
        contacts=[{"id": "harsh", "name": "Harsh"}],
        limit=10,
    )

    assert result["read_only"] is True
    assert result["coverage"]["gmail"]["accounts"] == ["a@example.com"]
    assert result["coverage"]["imessage"]["conversation_count"] == 1
    assert result["coverage"]["sheets"]["spreadsheet_count"] == 1
    assert result["context_sources"]["sheets"][0]["id"] == "s1"
    assert result["items"][0]["category"] == "reply_now"


def test_apply_model_labels_rejects_unknown_ids_and_preserves_hard_guardrails() -> None:
    result = build_unified_triage(
        {"now_items": [], "waiting_threads": [], "reasons": []},
        {"ok": True, "sources": {}},
        limit=5,
    )
    result["items"] = [
        {
            "item_id": "gmail:thread:t1",
            "source": "gmail",
            "category": "reply_now",
            "attention_class": "now",
            "state": "READY_HUMAN",
            "details": {"needs_reply": True},
        },
        {
            "item_id": "google_tasks:task:t2",
            "source": "tasks",
            "category": "task",
            "attention_class": "context",
            "state": "OBSERVED",
            "details": {},
        },
    ]
    result = apply_model_labels(
        result,
        {
            "status": "ok",
            "model": "deepseek/deepseek-v4-pro",
            "labels": {
                "gmail:thread:t1": {"category": "archive", "confidence": 0.99},
                "google_tasks:task:t2": {"category": "fyi", "confidence": 0.8},
                "not-an-item": {"category": "archive", "confidence": 1.0},
            },
        },
    )

    assert result["items"][0]["category"] == "archive"
    assert result["items"][0]["classification_method"] == "deepseek_v4_pro"
    assert result["items"][1]["category"] == "task"
    assert result["items"][1]["classification_method"] == "deterministic_guardrail"
    assert result["counts"] == {"archive": 1, "task": 1}


def test_apply_model_labels_cannot_promote_review_to_reply_now() -> None:
    result = build_unified_triage(
        {"now_items": [], "waiting_threads": [], "reasons": []},
        {"ok": True, "sources": {}},
        limit=5,
    )
    result["items"] = [
        {
            "item_id": "gmail:thread:opportunity",
            "source": "gmail",
            "category": "task",
            "attention_class": "now",
            "state": "READY_HUMAN",
            "details": {
                "actionability": "review",
                "open_loop": "Review opportunity details",
                "needs_reply": False,
            },
        }
    ]

    result = apply_model_labels(
        result,
        {
            "status": "ok",
            "labels": {
                "gmail:thread:opportunity": {"category": "reply_now", "confidence": 0.99}
            },
        },
    )

    assert result["items"][0]["category"] == "task"
    assert result["items"][0]["classification_method"] == "deterministic_guardrail"


def test_deepseek_classifier_uses_exact_model_and_validates_ids(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "model": "deepseek-v4-pro",
                "choices": [
                    {
                        "message": {
                            "content": '{"items":[{"item_id":"i1","category":"fyi","confidence":0.75},{"item_id":"bad","category":"task","confidence":1.0}]}'
                        }
                    }
                ],
            }

    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["payload"] = kwargs["json"]
        return FakeResponse()

    monkeypatch.setenv("TOKENROUTER_API_KEY", "test-only")
    monkeypatch.setattr("lifeops.deepseek.httpx.post", fake_post)
    result = classify_items([{"item_id": "i1", "title": "Example", "summary": "Info"}])

    assert result["status"] == "ok"
    assert result["model"] == "deepseek-v4-pro"
    assert result["labels"] == {"i1": {"category": "fyi", "confidence": 0.75}}
    assert captured["url"].endswith("/v1/chat/completions")
    assert captured["payload"]["model"] == "deepseek/deepseek-v4-pro"
    assert captured["payload"]["thinking"] == {"type": "disabled"}


def test_kimi_k3_classifier_uses_low_reasoning_mode(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "model": "kimi-k3",
                "choices": [
                    {
                        "message": {
                            "content": '{"items":[{"item_id":"i1","category":"fyi","confidence":0.75}]}'
                        }
                    }
                ],
            }

    captured = {}

    def fake_post(url, **kwargs):
        captured["payload"] = kwargs["json"]
        return FakeResponse()

    monkeypatch.setenv("TOKENROUTER_API_KEY", "test-only")
    monkeypatch.setenv("LIFEOPS_TRIAGE_MODEL", "moonshotai/kimi-k3")
    monkeypatch.setattr("lifeops.deepseek.httpx.post", fake_post)
    result = classify_items([{"item_id": "i1", "title": "Example", "summary": "Info"}])

    assert result["status"] == "ok"
    assert result["model"] == "kimi-k3"
    assert captured["payload"]["reasoning_effort"] == "low"
    assert "thinking" not in captured["payload"]


@pytest.mark.anyio
async def test_read_tools_preserve_exact_thread_and_event_readback_inputs(monkeypatch) -> None:
    import lifeops_mcp

    calls = []

    async def fake_request(method, path, *, params=None, body=None, extra_headers=None):
        calls.append((method, path, params))
        if path.startswith("/messages/"):
            return [{"source": "imessage", "message_id": "158", "body": "evidence"}]
        if path.startswith("/calendar/events/"):
            return {"event_id": "evt_123", "location": "45738 Bridgeport Dr."}
        return {
            "location": "37.5485,-121.9886",
            "available": True,
            "source": "macos_core_location_or_home_address",
            "read_only": True,
        }

    monkeypatch.setattr(lifeops_mcp, "_request", fake_request)

    messages = await lifeops_mcp.message_thread("imessage", "302", limit=3)
    event = await lifeops_mcp.calendar_event(
        "evt_123", calendar_id="jshah1331@gmail.com", account="jshah1331@gmail.com"
    )
    location = await lifeops_mcp.current_location()

    assert messages[0]["message_id"] == "158"
    assert messages[0]["attribution"]["reference"]["conversation_id"] == "302"
    assert messages[0]["attribution"]["derived"] is False
    assert event["location"] == "45738 Bridgeport Dr."
    assert event["attribution"]["reference"]["event_id"] == "evt_123"
    assert event["attribution"]["derived"] is False
    assert location["available"] is True
    assert calls == [
        ("GET", "/messages/imessage/302", {"limit": 3}),
        (
            "GET",
            "/calendar/events/evt_123",
            {"calendar_id": "jshah1331@gmail.com", "account": "jshah1331@gmail.com"},
        ),
        ("GET", "/location/current", None),
    ]
