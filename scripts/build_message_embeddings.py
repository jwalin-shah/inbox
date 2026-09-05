#!/usr/bin/env python3
"""Build the local message-index embeddings in resumable batches.

The script is intentionally separate from the Inbox server.  Search remains
available through FTS5 while this derived index is being built or refreshed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow the documented ``python scripts/...`` invocation to import the Inbox
# modules from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from message_index_store import MessageIndexStore
from semantic_index import DEFAULT_MODEL_ID, LocalTextEmbedder, content_hash, item_embedding_text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=None, help="message index SQLite path")
    parser.add_argument("--model", default=DEFAULT_MODEL_ID)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-items", type=int, default=0, help="0 means all pending items")
    parser.add_argument("--source", default="")
    parser.add_argument("--account", default="")
    args = parser.parse_args()
    batch_size = max(1, min(args.batch_size, 64))
    max_items = max(0, args.max_items)

    store = MessageIndexStore(args.db)
    embedder = LocalTextEmbedder(args.model)
    processed = 0
    while max_items == 0 or processed < max_items:
        remaining = max_items - processed if max_items else batch_size
        rows = store.embedding_backlog(
            model_id=args.model,
            limit=min(batch_size, remaining),
            source=args.source,
            account=args.account,
        )
        if not rows:
            break
        texts = [item_embedding_text(row) for row in rows]
        vectors = embedder.encode(texts, batch_size=batch_size)
        for row, text, vector in zip(rows, texts, vectors, strict=True):
            store.upsert_embedding(
                item_id=int(row["id"]),
                model_id=args.model,
                content_hash=content_hash(text),
                vector=vector,
            )
        processed += len(rows)
        status = store.embedding_status(args.model)
        print(
            f"embedded={status['embedded']} pending={status['pending']} processed_this_run={processed}",
            flush=True,
        )
    status = store.embedding_status(args.model)
    print(f"complete={status['pending'] == 0} embedded={status['embedded']} pending={status['pending']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
