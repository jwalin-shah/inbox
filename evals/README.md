# Inbox Evals

Codebuff-style eval harness for inbox/personal-assistant tasks.

## Structure

```
evals/
├── tasks/        # Task specs (JSON). One file per suite.
├── runners/      # Agent integrations (claude, codex, gemini)
├── judges/       # 3-judge median scoring
├── results/      # Timestamped run outputs
└── run_evals.py  # Orchestrator
```

## Task format

```json
{
  "suite": "inbox-search",
  "tasks": [
    {
      "id": "t001",
      "spec": "Find emails from Alice about the Q2 budget",
      "expected_sources": ["alice@example.com"],
      "expected_keywords": ["Q2", "budget"],
      "channel": "gmail"
    }
  ]
}
```

## Scoring (per task, 0-10 each)

- **completion** — spec satisfied vs ground truth
- **efficiency** — minimal tool calls, no wasted work
- **quality** — answer structure, citation hygiene
- **overall** — holistic

3 judges run in parallel → median taken (robust to outliers).

## Run

```bash
cd ~/projects/inbox
uv run python evals/run_evals.py --suite tasks/inbox-search.json --agent claude
uv run python evals/run_evals.py --suite tasks/inbox-search.json --agents claude,codex
```

## Output

Each run writes `results/<timestamp>_<suite>.json`:

```json
{
  "suite": "inbox-search",
  "agent": "claude",
  "timestamp": "2026-04-16T...",
  "results": [
    {
      "task_id": "t001",
      "trace": [...],
      "cost_usd": 0.012,
      "duration_ms": 4521,
      "scores": {"completion": 8, "efficiency": 7, "quality": 9, "overall": 8}
    }
  ],
  "summary": {"pass_rate": 0.85, "median_overall": 8}
}
```

Diff against prior result to spot regressions.
