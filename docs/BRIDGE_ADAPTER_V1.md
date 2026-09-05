# Bridge adapter v1

Inbox is a source/capture adapter at this boundary. It converts an existing
normalized Inbox record into a versioned `EventEnvelope`; it does not move
canonical personal state, mint Bridge authority, execute workers, verify code,
or deliver Git changes.

## Contract

The adapter emits JSON with:

- `version`: `bridge.contracts.v1`
- stable `id`, `kind`, `source`, `external_id`, and `occurred_at`
- normalized `payload.text` plus optional subject/reference/metadata

Bridge's `ingest` command validates the envelope, derives a `WorkPacket`, and
persists an immutable intake record. Its result status is
`accepted_for_intake`; it is not a task completion or execution receipt.

## Ownership

Inbox remains responsible for the source record and any personal-data actions.
Bridge owns only the intake copy, later execution admission, independent
verification, and Git delivery. No provider name, legacy `role`, `model`,
`provider`, or `verify` field is interpreted by this adapter.

## Example

```sh
printf '%s\n' '{"id": 7, "source": "manual", "content": "..."}' \\
  | uv run python inbox_bridge_adapter.py \\
  | bridge ingest -
```

The command is intentionally a local handshake. Live HomeBase receipts,
provider routing, and automatic workers remain follow-up work.
