# ADR 0013: Local message index and semantic search

## Status

Accepted and implemented 2026-08-25.

## Decision

Inbox keeps provider observations and source identifiers as the authority, then
maintains a local SQLite read model for fast retrieval:

- SQLite FTS5 provides immediate keyword search across captured Gmail and
  iMessage items.
- A derived `item_embeddings` table stores normalized local BGE vectors. Message
  text is not sent to an external embedding service.
- Search results retain source, account, thread ID, external ID, and raw pointer
  so triage can fetch authoritative evidence before proposing an action.
- Embeddings are built by the resumable
  `scripts/build_message_embeddings.py` job for initial or large backfills, and
  by a bounded best-effort refresh after provider index syncs. They are not
  built during server startup.
- Updating message content invalidates only that message's derived vector.

## Triage boundary

Embeddings improve recall and ranking; they do not authorize an action and do
not replace the deterministic thread/triage projection. Triage remains
read-only and returns category, confidence, signals, and source references.
Task/calendar/message writes continue through the existing approval and
read-back gates.

The review queue is paged by `offset` and `limit` at `/triage/messages` and in
the LifeOps `triage_messages` tool. This lets a person review successive thread
pages without treating the first page as the complete historical queue.

## Operational proof

The current index contains 30,068 items and the BGE build completed with
`pending: 0`. The read-only `/index/search` and `/index/embedding-status`
endpoints are exposed through the LifeOps MCP adapter as
`search_indexed_messages` and `embedding_status`.
