# Ops Brain

Inbox can now read the local ops kernel without depending on Codex.

## Run

```bash
cd /Users/jwalinshah/projects/inbox
OPS_KERNEL_PATH=/Users/jwalinshah/Documents/Codex/2026-05-26/can-we-please-do-a-review/ops_kernel uv run python inbox.py
```

Open the `Ops` tab from the tab bar or command palette. It renders local
reconciliation queues read-only:

- resume/interview evidence
- live Gmail connector evidence already copied into local CSV
- Gmail export reconciliation
- LinkedIn reconciliation
- Drive evidence

## Adapter Contract

The durable state lives in local CSV/Markdown ledgers. Providers are adapters:
they can read queue rows, draft work, or write handoff evidence, but they are not
the place where state lives.

Machine-readable packet:

```bash
cd /Users/jwalinshah/projects/inbox
OPS_KERNEL_PATH=/Users/jwalinshah/Documents/Codex/2026-05-26/can-we-please-do-a-review/ops_kernel uv run python ops_brain.py
```

The JSON packet is intentionally simple so Codex, Claude, local models, shell
scripts, Pioneer, Adaption, or future workers can all consume the same queue.
