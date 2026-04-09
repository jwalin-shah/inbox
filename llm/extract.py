"""
Structured extraction from transcripts using Outlines constrained generation.
Replaces the LFM2-350M-Extract pipeline with Qwen3.5-0.8B.
"""

from __future__ import annotations

from pydantic import BaseModel

from llm.engine import generate_json

EXTRACT_PROMPT = (
    "Extract structured information from this spoken note. "
    "key_points: main ideas stated. action_items: things to do. topics: subjects mentioned. "
    "Use empty lists if nothing relevant.\n\nText: {text}"
)


class Extraction(BaseModel):
    key_points: list[str]
    action_items: list[str]
    topics: list[str]


def extract(text: str) -> Extraction:
    """Extract key points, action items, and topics from transcript text."""
    return generate_json(EXTRACT_PROMPT.format(text=text), Extraction)


def extract_summary(text: str) -> str | None:
    """Extract and format as a single-line summary. Returns None if nothing useful."""
    result = extract(text)
    parts = []
    if result.key_points:
        parts.append("; ".join(result.key_points))
    if result.action_items:
        parts.append("\u2192 " + "; ".join(result.action_items))
    return " | ".join(parts) if parts else None
