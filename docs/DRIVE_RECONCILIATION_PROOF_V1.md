# Drive reconciliation proof v1

Inbox now has a read-only proof primitive at `POST /drive/reconciliation/proof`.
It is deliberately separate from every Drive mutation endpoint and accepts
only this explicit scope:

```json
{
  "account": "jshah1331@gmail.com",
  "source_root_id": "<source-folder-id>",
  "canonical_root_id": "<canonical-folder-id>"
}
```

The server resolves the Drive service by the exact account string. It validates
both IDs as non-trashed Drive folders, recursively lists only children whose
single parent is the current in-scope folder, and never follows shortcuts.
Names that cannot safely be represented as relative path segments, malformed
metadata, duplicate paths/IDs, scope escapes, and traversal cycles become
`UNRESOLVED` evidence rather than being guessed through.

The response is a deterministic receipt with:

- `status`: `ZERO_UNIQUE_PROVEN` only when the snapshot is stable and there
  are zero unresolved objects and zero source objects absent from the
  canonical tree; otherwise `UNRESOLVED`.
- `counts` and `bytes`: source/canonical totals plus `matched`,
  `unmatched_unique`, `unresolved`, and canonical-only counts.
- `checksum_coverage`: counts of objects with provider checksums and objects
  with checksums on both sides. Size and normalized modified time are always
  compared when file metadata is valid.
- `snapshot`: the start/end Drive change tokens and whether the adapter saw a
  stable snapshot. Any change during inventory fails closed.
- `account`, both root IDs, `proof_digest`, and a digest-derived `proof_id`.

The adapter calls only Drive metadata reads (`files.get`, `files.list`,
`changes.getStartPageToken`, and `changes.list`). It does not accept or return
OAuth credentials and has no delete, trash, move, rename, upload, sharing,
ownership, or OAuth flow. This work item does not implement cleanup or a
deletion lease. A later cleanup operation must accept an immutable proof ID
and digest, revalidate the provider snapshot, and obtain separate explicit
approval before any candidate action exists.

`GET /sources/registry` is the static source authority/capability map. It does
not probe providers. The live 9849 process may need a separately authorized
restart/deployment because its current owner is an older runtime checkout; this
change does not mutate that runtime checkout.
