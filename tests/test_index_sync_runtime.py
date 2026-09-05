import asyncio
import time

import inbox_server


def test_index_sync_helper_serializes_runs_and_returns_stats():
    active = 0
    maximum_active = 0

    def fake_sync(_store):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        time.sleep(0.02)
        active -= 1
        return {"imessage": {"indexed": 2}}

    async def run_both():
        return await asyncio.gather(
            inbox_server._run_index_sync(fake_sync, "first"),
            inbox_server._run_index_sync(fake_sync, "second"),
        )

    results = asyncio.run(run_both())

    assert maximum_active == 1
    assert results == [
        {"imessage": {"indexed": 2}},
        {"imessage": {"indexed": 2}},
    ]


def test_embedding_refresh_processes_bounded_backlog(monkeypatch):
    class FakeStore:
        def __init__(self):
            self.rows = [
                {"id": 11, "subject": "Subject", "sender": "Sender", "snippet": "Text"},
                {"id": 12, "subject": "Second", "sender": "Sender", "snippet": "More"},
            ]
            self.writes = []

        def embedding_backlog(self, *, model_id, limit):
            assert model_id == inbox_server.DEFAULT_MODEL_ID
            rows, self.rows = self.rows[:limit], self.rows[limit:]
            return rows

        def upsert_embedding(self, **kwargs):
            self.writes.append(kwargs)

        def embedding_status(self, model_id):
            return {"items": 2, "embedded": len(self.writes), "pending": 2 - len(self.writes)}

    class FakeEmbedder:
        def encode(self, texts, batch_size):
            assert batch_size == 2
            return [[float(index)] for index, _ in enumerate(texts, start=1)]

    store = FakeStore()
    monkeypatch.setattr(inbox_server, "_index_embedder", FakeEmbedder())

    result = inbox_server._embed_pending_items(store, batch_size=2, max_items=2)

    assert result == {"processed": 2, "items": 2, "embedded": 2, "pending": 0}
    assert [write["item_id"] for write in store.writes] == [11, 12]
    assert all(write["content_hash"] for write in store.writes)


def test_embedding_refresh_respects_max_items(monkeypatch):
    class FakeStore:
        def embedding_backlog(self, *, model_id, limit):
            return [{"id": 21, "subject": "Only one"}]

        def upsert_embedding(self, **kwargs):
            raise AssertionError("should not write when max_items is zero")

        def embedding_status(self, model_id):
            return {"items": 1, "embedded": 0, "pending": 1}

    monkeypatch.setattr(inbox_server, "_index_embedder", None)
    result = inbox_server._embed_pending_items(FakeStore(), max_items=0)

    assert result == {"processed": 0, "items": 1, "embedded": 0, "pending": 1}
