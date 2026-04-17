"""3-judge median scoring. Runs N parallel judges, takes median per metric."""

import concurrent.futures
import json
import os
import statistics
from dataclasses import dataclass

from anthropic import Anthropic

JUDGE_MODEL = "claude-sonnet-4-6"
NUM_JUDGES = 3

JUDGE_PROMPT = """You are scoring an AI agent's response to a task.

TASK SPEC:
{spec}

EXPECTED KEYWORDS (must appear if relevant): {keywords}
EXPECTED SOURCES (citations): {sources}

AGENT OUTPUT:
{output}

Score 0-10 on each dimension. Return ONLY valid JSON:
{{"completion": <int>, "efficiency": <int>, "quality": <int>, "overall": <int>, "notes": "<one sentence>"}}

- completion: did it satisfy the spec?
- efficiency: minimal steps, no fluff?
- quality: structure, citations, accuracy?
- overall: holistic 0-10."""


@dataclass
class Score:
    completion: int
    efficiency: int
    quality: int
    overall: int
    notes: str = ""


def _single_judge(client: Anthropic, prompt: str) -> Score:
    msg = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    block = msg.content[0]
    text = (getattr(block, "text", "") or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1].lstrip("json\n")
    data = json.loads(text)
    return Score(
        **{k: data.get(k, 0) for k in ("completion", "efficiency", "quality", "overall", "notes")}
    )


def judge_median(task: dict, output: str) -> Score:
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    prompt = JUDGE_PROMPT.format(
        spec=task["spec"],
        keywords=task.get("expected_keywords", []),
        sources=task.get("expected_sources", []),
        output=output[:8000],
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_JUDGES) as ex:
        scores = list(ex.map(lambda _: _single_judge(client, prompt), range(NUM_JUDGES)))
    return Score(
        completion=int(statistics.median(s.completion for s in scores)),
        efficiency=int(statistics.median(s.efficiency for s in scores)),
        quality=int(statistics.median(s.quality for s in scores)),
        overall=int(statistics.median(s.overall for s in scores)),
        notes=" | ".join(s.notes for s in scores)[:300],
    )
