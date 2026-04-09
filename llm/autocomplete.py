"""
Inline text autocomplete for the compose input.
Given conversation context + a partial draft, suggests a completion.
"""

from __future__ import annotations

from llm.engine import complete

AUTOCOMPLETE_PROMPT = """\
Complete the user's reply naturally. Output ONLY the completion text, nothing else.

Recent messages:
{context}

User is typing: {draft}"""


def build_context(messages: list[dict], max_messages: int = 6) -> str:
    """Format recent messages into context string."""
    recent = messages[-max_messages:]
    lines = []
    for msg in recent:
        sender = msg.get("sender", "?")
        body = msg.get("body", "").strip()
        # Truncate long messages
        if len(body) > 200:
            body = body[:200] + "..."
        lines.append(f"{sender}: {body}")
    return "\n".join(lines)


def autocomplete(
    draft: str,
    messages: list[dict] | None = None,
    max_tokens: int = 32,
) -> str | None:
    """Suggest a completion for the draft text.

    Returns the suggested continuation, or None if the draft is too short
    or the completion is empty.
    """
    if len(draft.strip()) < 3:
        return None

    context = build_context(messages) if messages else ""
    prompt = AUTOCOMPLETE_PROMPT.format(context=context, draft=draft)
    result = complete(prompt, max_tokens=max_tokens, temperature=0.5)

    # Clean up — strip any leading whitespace or repeated draft text
    result = result.strip()
    if not result:
        return None

    return result
