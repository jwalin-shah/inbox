"""Orchestrator: load suite, run agent(s), judge, write results, diff vs prior."""

import argparse
import datetime as dt
import glob
import json
import os
import statistics
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from judges.judge import judge_median  # type: ignore[import-not-found]  # noqa: E402
from runners.claude import ClaudeRunner  # type: ignore[import-not-found]  # noqa: E402
from runners.codex import CodexRunner  # type: ignore[import-not-found]  # noqa: E402
from runners.gemini import GeminiRunner  # type: ignore[import-not-found]  # noqa: E402

RUNNERS = {"claude": ClaudeRunner, "codex": CodexRunner, "gemini": GeminiRunner}


def run_one(runner, task):
    print(f"  [{task['id']}] {task['spec'][:60]}...", flush=True)
    res = runner.run(task["spec"])
    if res.error:
        print(f"    ERROR: {res.error}", flush=True)
        return {"task_id": task["id"], "error": res.error, "scores": None}
    score = judge_median(task, res.output)
    print(f"    overall={score.overall} cost=${res.cost_usd:.4f} {res.duration_ms}ms", flush=True)
    return {
        "task_id": task["id"],
        "trace": res.trace,
        "output": res.output,
        "cost_usd": res.cost_usd,
        "duration_ms": res.duration_ms,
        "scores": asdict(score),
    }


def diff_vs_prior(suite_name: str, current: list[dict]) -> list[str]:
    prior_files = sorted(glob.glob(f"results/*_{suite_name}_*.json"))
    if len(prior_files) < 2:
        return []
    prior = json.loads(Path(prior_files[-2]).read_text())
    prior_scores = {
        r["task_id"]: r["scores"]["overall"] for r in prior["results"] if r.get("scores")
    }
    regressions = []
    for r in current:
        if not r.get("scores"):
            continue
        prev = prior_scores.get(r["task_id"])
        if prev is not None and r["scores"]["overall"] < prev - 1:
            regressions.append(f"{r['task_id']}: {prev} → {r['scores']['overall']}")
    return regressions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", required=True)
    ap.add_argument("--agent", default="claude", help="single agent OR comma list for side-by-side")
    args = ap.parse_args()
    agents = [a.strip() for a in args.agent.split(",")]

    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]

    suite = json.loads(Path(args.suite).read_text())
    ts = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S")
    summaries = []

    for agent_name in agents:
        runner = RUNNERS[agent_name]()
        print(
            f"\n=== Agent: {agent_name} | Suite: {suite['suite']} | Tasks: {len(suite['tasks'])} ===",
            flush=True,
        )
        results = [run_one(runner, t) for t in suite["tasks"]]

        scored = [r for r in results if r.get("scores")]
        overalls = [r["scores"]["overall"] for r in scored]
        pass_rate = sum(1 for o in overalls if o >= 7) / len(overalls) if overalls else 0.0

        out = {
            "suite": suite["suite"],
            "agent": agent_name,
            "timestamp": dt.datetime.now(dt.UTC).isoformat(),
            "results": results,
            "summary": {
                "pass_rate": round(pass_rate, 3),
                "median_overall": int(statistics.median(overalls)) if overalls else 0,
                "total_cost_usd": round(sum(r.get("cost_usd", 0) for r in results), 4),
            },
        }
        out_path = Path("results") / f"{ts}_{suite['suite']}_{agent_name}.json"
        out_path.write_text(json.dumps(out, indent=2))

        regressions = diff_vs_prior(suite["suite"], results)
        line = f"{agent_name}: pass {pass_rate:.0%} | median {out['summary']['median_overall']} | ${out['summary']['total_cost_usd']:.4f} | regressions: {regressions or 'none'}"
        summaries.append(line)
        print(line, flush=True)
        print(f"Wrote: {out_path}", flush=True)

    if len(summaries) > 1:
        print("\n=== Side-by-side ===", flush=True)
        for s in summaries:
            print(s, flush=True)


if __name__ == "__main__":
    main()
